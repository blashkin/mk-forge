"""Прогнозный пул: новые участники строками, а не одной цифрой.

Раньше прогноз новых был произведением трех чисел: сколько их, сколько каждый
везет, сколько месяцев действует. Проверить такое нельзя — в нем нечего
проверять, кроме самих трех чисел.

Здесь прогноз разложен на строки. У каждой свой сегмент шкалы, своя дата
подключения и свой срок с этой даты до конца акции. Состав по сегментам берется
из текущего пула со сдвигом к крупным: скидку скорее дадут тем, кто больше везет.

Даты внутри каждого сегмента распределены равномерно по сроку акции. Это не
косметика: если крупные подключатся первыми, у них окажется и объем больше,
и срок длиннее, и прогноз завысит сам себя.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

from mkforge.core.calendar import term_for
from mkforge.core.economics import NewClients
from mkforge.core.pool import Mix

NUMBER_PREFIX = "Прогноз"


@dataclass(frozen=True)
class ForecastMember:
    """Один прогнозный участник."""

    number: str
    segment: str
    connected: dt.date
    term_months: float
    tons_per_month: float
    stp_rate: float
    fee_rate: float

    @property
    def ton_months(self) -> float:
        return self.tons_per_month * self.term_months

    @property
    def discount_ton_months(self) -> float:
        return self.ton_months * self.stp_rate

    @property
    def fee_base_ton_months(self) -> float:
        return self.ton_months * (1 - self.stp_rate) * self.fee_rate

    @property
    def fee_ton_months(self) -> float:
        return self.ton_months * self.fee_rate


@dataclass(frozen=True)
class ForecastPool:
    """Прогнозный пул целиком."""

    members: tuple[ForecastMember, ...]
    margin_per_ton: float

    @property
    def size(self) -> int:
        return len(self.members)

    def _total(self, attribute: str) -> float:
        return sum(getattr(member, attribute) for member in self.members)

    @property
    def ton_months(self) -> float:
        return self._total("ton_months")

    @property
    def client_months(self) -> float:
        return self._total("term_months")

    def subset(self, members: tuple[ForecastMember, ...]) -> "ForecastPool":
        return replace(self, members=members)

    def new_clients(self) -> NewClients:
        """Свести пул к тому, что нужно экономике акции."""
        return NewClients(
            count=self.size,
            ton_months=self.ton_months,
            client_months=self.client_months,
            discount_ton_months=self._total("discount_ton_months"),
            fee_base_ton_months=self._total("fee_base_ton_months"),
            fee_ton_months=self._total("fee_ton_months"),
            margin_per_ton=self.margin_per_ton,
        )


def _counts_by_segment(mix: Mix, count: int) -> tuple[int, ...]:
    """Разложить количество по сегментам по методу наибольшего остатка.

    Простое округление долей теряет или добавляет участников, а прогноз должен
    состоять ровно из того числа строк, которое мы заявили.
    """
    if count <= 0 or not mix.segments:
        return tuple(0 for _ in mix.segments)

    exact = [segment.share * count for segment in mix.segments]
    counts = [int(value) for value in exact]
    remainder = count - sum(counts)
    order = sorted(
        range(len(exact)), key=lambda i: (-(exact[i] - counts[i]), i)
    )
    for index in order[:remainder]:
        counts[index] += 1
    return tuple(counts)


def _dates(count: int, start: dt.date, end: dt.date) -> tuple[dt.date, ...]:
    """Равномерные даты подключения внутри срока акции."""
    if count <= 0:
        return ()
    if count == 1:
        return (start,)
    span = (end - start).days
    return tuple(
        start + dt.timedelta(days=round(index * span / (count - 1)))
        for index in range(count)
    )


def _nearest_free(taken: list[bool], target: int) -> int:
    """Ближайшее свободное место к желаемому."""
    for offset in range(len(taken)):
        for candidate in (target - offset, target + offset):
            if 0 <= candidate < len(taken) and not taken[candidate]:
                return candidate
    raise ValueError("свободных мест не осталось")


def _slots(counts: tuple[int, ...], total: int) -> tuple[tuple[int, ...], ...]:
    """Разнести сегменты по общему ряду дат.

    Даты раздаются одним рядом на весь прогноз, а не внутри каждого сегмента:
    сегментов больше, чем строк в ином из них, и раздача внутри сегмента
    посадила бы единственную строку на первый день. Тогда мелкие сегменты
    получили бы полный срок акции, а средний срок прогноза оказался бы завышен.

    Большие сегменты занимают места первыми: им важнее попасть в свои,
    а одиночные строки все равно встанут в промежутки.
    """
    taken = [False] * total
    places: list[tuple[int, ...]] = [() for _ in counts]
    for index in sorted(range(len(counts)), key=lambda i: (-counts[i], i)):
        count = counts[index]
        picked = []
        for position in range(count):
            target = round((position + 0.5) * total / count - 0.5)
            slot = _nearest_free(taken, min(total - 1, max(0, target)))
            taken[slot] = True
            picked.append(slot)
        places[index] = tuple(sorted(picked))
    return tuple(places)


def build_forecast(
    mix: Mix,
    count: int,
    product: str,
    start: dt.date,
    end: dt.date,
    margin_per_ton: float,
) -> ForecastPool:
    """Собрать прогнозный пул строками по составу сегментов."""
    counts = _counts_by_segment(mix, count)
    dates = _dates(count, start, end)
    members: list[ForecastMember] = []
    for segment, places in zip(mix.segments, _slots(counts, count), strict=True):
        for slot in places:
            connected = dates[slot]
            members.append(
                ForecastMember(
                    number="",
                    segment=segment.bracket.label,
                    connected=connected,
                    term_months=term_for(connected, start, end),
                    tons_per_month=segment.tons_per_contract,
                    stp_rate=segment.bracket.rate(product),
                    fee_rate=segment.fee_rate,
                )
            )

    # Номера выдаются после сортировки по дате: так строки в книге читаются
    # в том порядке, в котором участники и подключаются.
    members.sort(key=lambda m: (m.connected, -m.tons_per_month, m.segment))
    numbered = tuple(
        replace(member, number=f"{NUMBER_PREFIX}-{index:03d}")
        for index, member in enumerate(members, start=1)
    )
    return ForecastPool(members=numbered, margin_per_ton=margin_per_ton)
