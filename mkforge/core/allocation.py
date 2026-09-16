"""Распределение глубины скидки по пулу: кому какая скидка достается.

Раньше уровень акции был один на весь пул: надбавка подбиралась так, чтобы
средневзвешенная эффективная скидка равнялась цели. Это верно, когда скидку
дают всем одинаково, и неверно, когда ее раздают менеджеры по одному.

Здесь глубина задана распределением: доля пула получает 1%, доля — 2% и так
далее. Итог акции складывается из срезов, а эффективная скидка перестает быть
входом и становится выходом.

Два режима раздачи, и разница между ними заметная.

По объему: чем больше клиент везет, тем глубже его скидка. Пул концентрирован,
поэтому глубокие проценты приходятся на большую часть объема, и акция выходит
дороже. Это консервативный случай, и проверять «не уходим ли в минус» надо
именно на нем.

Не по объему: скидка достается вне зависимости от размера. Тогда срез — это
доля от каждого договора, подмножеством договоров он не выделяется.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from mkforge.core.pool import Pool

SHARE_TOLERANCE = 1e-9

T = TypeVar("T")


class AllocationError(Exception):
    """Распределение глубины задано неверно."""


@dataclass(frozen=True)
class DepthShare:
    """Одна глубина скидки и доля пула, которая ее получает."""

    depth: float  # целевая эффективная скидка клиента
    share: float  # доля договоров пула


@dataclass(frozen=True)
class Distribution:
    """Распределение глубины скидки по пулу.

    Доли задаются по договорам, а не по объему: менеджер дает скидку клиенту,
    а не тонне. Сколько объема попало в срез — следствие, а не задание.
    """

    shares: tuple[DepthShare, ...]
    by_volume: bool = True

    def __post_init__(self) -> None:
        if not self.shares:
            raise AllocationError("распределение пустое: ни одной глубины")
        total = sum(s.share for s in self.shares)
        if abs(total - 1.0) > 1e-6:
            raise AllocationError(
                f"доли распределения должны давать единицу, получено {total:.6f}"
            )
        if any(s.share < 0 for s in self.shares):
            raise AllocationError("доля распределения не может быть отрицательной")
        if any(not 0 < s.depth < 1 for s in self.shares):
            raise AllocationError(
                "глубина задается долей, 0.05 вместо 5 — "
                f"получено {[s.depth for s in self.shares]}"
            )
        depths = [s.depth for s in self.shares]
        if len(set(depths)) != len(depths):
            raise AllocationError(f"глубины повторяются: {depths}")

    @property
    def depths(self) -> tuple[float, ...]:
        return tuple(s.depth for s in self.shares)

    @property
    def weighted_depth(self) -> float:
        """Средняя глубина по договорам. По объему она может быть другой."""
        return sum(s.depth * s.share for s in self.shares)

    @property
    def cumulative(self) -> tuple[float, ...]:
        """Нарастающий итог долей — в таком виде распределение и читают."""
        running, out = 0.0, []
        for share in self.shares:
            running += share.share
            out.append(running)
        return tuple(out)

    def deepest_first(self) -> "Distribution":
        """То же распределение, отсортированное от самой глубокой скидки."""
        return Distribution(
            shares=tuple(sorted(self.shares, key=lambda s: -s.depth)),
            by_volume=self.by_volume,
        )


@dataclass(frozen=True)
class Slice:
    """Срез пула с одной глубиной скидки.

    В режиме «по объему» срез — это подпул из своих договоров, вес единица.
    Иначе срез — доля от всего пула, и вес равен этой доле.
    """

    depth: float
    share: float
    pool: Pool
    weight: float

    @property
    def contracts(self) -> float:
        return self.pool.size * self.weight

    @property
    def tons_per_month(self) -> float:
        return self.pool.total_tons_per_month * self.weight


def cut_by_shares(
    items: Sequence[T],
    shares: tuple[float, ...],
    key: Callable[[T], float],
) -> tuple[tuple[T, ...], ...]:
    """Нарезать последовательность по долям, отсортировав ее ключом.

    Правило нарезки — накопленная доля, а не округленное число элементов.
    Элемент с номером r из N попадает в тот срез, в чьи границы попадает r/N.
    Так же это считает и книга: там у каждой строки есть ранг по объему,
    и глубина ищется по накопленной доле через MATCH.

    Округление числа элементов дало бы то же самое на сотнях договоров
    и разошлось бы на десятках прогнозных строк — а сойтись должны обе.

    Сортировка устойчивая, и ключ только по объему: при равных объемах
    порядок остается исходным. Это важно потому, что номера договоров в книге
    в конце подменяются настоящими — если бы они участвовали в сортировке,
    подмена меняла бы состав срезов и числа вместе с ним.
    """
    ordered = sorted(items, key=key)
    if not ordered:
        return tuple(() for _ in shares)

    lower: list[float] = []
    running = 0.0
    for share in shares:
        lower.append(running)
        running += share

    groups: list[list[T]] = [[] for _ in shares]
    total = len(ordered)
    for position, item in enumerate(ordered, start=1):
        cumulative = position / total
        index = bisect_right(lower, cumulative) - 1
        groups[max(0, min(index, len(shares) - 1))].append(item)
    return tuple(tuple(group) for group in groups)


def allocate(pool: Pool, distribution: Distribution) -> tuple[Slice, ...]:
    """Раздать глубину скидки по пулу.

    В режиме «по объему» договоры сортируются по объему и нарезаются по долям:
    самая глубокая скидка достается самым крупным. Остаток отдается последнему
    срезу целиком, иначе округление долей потеряло бы договоры.
    """
    ordered = distribution.deepest_first()
    if not ordered.by_volume:
        return tuple(
            Slice(depth=s.depth, share=s.share, pool=pool, weight=s.share)
            for s in ordered.shares
        )

    groups = cut_by_shares(
        pool.members,
        tuple(s.share for s in ordered.shares),
        key=lambda m: -m.product_tons_per_month,
    )
    return tuple(
        Slice(
            depth=share.depth,
            share=share.share,
            pool=Pool(
                product=pool.product,
                period_months=pool.period_months,
                members=group,
            ),
            weight=1.0,
        )
        for share, group in zip(ordered.shares, groups, strict=True)
    )


def volume_weighted_depth(slices: tuple[Slice, ...]) -> float:
    """Глубина, взвешенная по объему: то, во что распределение обошлось.

    От средней по договорам отличается тем сильнее, чем концентрированнее пул.
    """
    total = sum(s.tons_per_month for s in slices)
    if total <= 0:
        return 0.0
    return sum(s.depth * s.tons_per_month for s in slices) / total
