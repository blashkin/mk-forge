"""Распределение глубины скидки: кто в какой срез попал."""

from __future__ import annotations

import pytest

from mkforge.core.allocation import (
    AllocationError,
    DepthShare,
    Distribution,
    allocate,
    cut_by_shares,
    volume_weighted_depth,
)

MASS_AT_DEEP_END = ((0.05, 0.35), (0.04, 0.35), (0.03, 0.15), (0.02, 0.10), (0.01, 0.05))


def distribution(by_volume: bool = True) -> Distribution:
    return Distribution(
        shares=tuple(DepthShare(depth, share) for depth, share in MASS_AT_DEEP_END),
        by_volume=by_volume,
    )


def test_shares_must_give_one():
    with pytest.raises(AllocationError, match="единицу"):
        Distribution(shares=(DepthShare(0.05, 0.5), DepthShare(0.04, 0.2)))


def test_depth_is_a_fraction_not_a_number():
    """Пять процентов — это 0.05. Иначе расчет уехал бы в сто раз."""
    with pytest.raises(AllocationError, match="долей"):
        Distribution(shares=(DepthShare(5, 1.0),))


def test_depths_do_not_repeat():
    with pytest.raises(AllocationError, match="повторяются"):
        Distribution(shares=(DepthShare(0.05, 0.5), DepthShare(0.05, 0.5)))


def test_weighted_depth_is_by_contracts():
    assert distribution().weighted_depth == pytest.approx(0.0385)


def test_cumulative_ends_at_one():
    assert distribution().cumulative[-1] == pytest.approx(1.0)


def test_cut_keeps_everything():
    """Элемент ровно на границе достается следующему срезу.

    Так же его отдает MATCH в книге, поэтому на круглых долях срез может
    отличаться от доли на один элемент. Главное — ничего не потеряно.
    """
    groups = cut_by_shares(tuple(range(100)), (0.35, 0.35, 0.15, 0.10, 0.05), key=lambda x: -x)
    assert sum(len(g) for g in groups) == 100
    assert [len(g) for g in groups] == [34, 35, 15, 10, 6]


def test_cut_goes_by_cumulative_share_not_rounded_count():
    """Правило нарезки то же, что в книге: по накопленной доле r/N.

    На десятках элементов округление доли дало бы другой ответ, и книга
    с ядром разошлись бы — это уже случалось.
    """
    groups = cut_by_shares(tuple(range(22)), (0.35, 0.35, 0.15, 0.10, 0.05), key=lambda x: -x)
    assert [len(g) for g in groups] == [7, 8, 3, 2, 2]
    assert sum(len(g) for g in groups) == 22


def test_cut_is_stable_on_equal_keys():
    """При равных объемах порядок исходный: иначе подмена номеров меняла бы срезы."""
    items = tuple(f"договор-{index}" for index in range(10))
    groups = cut_by_shares(items, (0.5, 0.5), key=lambda _: 0.0)
    assert groups[0] + groups[1] == items, "порядок внутри срезов исходный"
    assert groups[0] == items[:4] and groups[1] == items[4:]


def test_slices_partition_the_pool(pool_object):
    slices = allocate(pool_object, distribution())
    assert sum(piece.pool.size for piece in slices) == pool_object.size
    contracts = [m.contract for piece in slices for m in piece.pool.members]
    assert len(set(contracts)) == pool_object.size


def test_deepest_discount_goes_to_the_largest(pool_object):
    slices = allocate(pool_object, distribution())
    volumes = [piece.pool.total_tons_per_month for piece in slices]
    assert volumes == sorted(volumes, reverse=True), (
        "срез с самой глубокой скидкой должен держать больше всего объема"
    )


def test_concentrated_handout_is_never_cheaper(pool_object):
    """Глубже крупным — всегда дороже или столько же, чем вне зависимости от размера.

    Это не свойство данных, а перестановочное неравенство: наибольшие глубины,
    поставленные к наибольшим объемам, дают наибольшее взвешенное среднее.
    Поэтому «не уходим ли в минус» надо проверять на этом варианте.
    """
    concentrated = volume_weighted_depth(allocate(pool_object, distribution(True)))
    flat = volume_weighted_depth(allocate(pool_object, distribution(False)))
    assert concentrated >= flat - 1e-12
    assert flat == pytest.approx(distribution().weighted_depth)


def test_flat_handout_takes_a_share_of_everyone(pool_object):
    """Раздача вне зависимости от размера не выделяется подмножеством договоров."""
    slices = allocate(pool_object, distribution(False))
    assert all(piece.pool.size == pool_object.size for piece in slices)
    assert [piece.weight for piece in slices] == [0.35, 0.35, 0.15, 0.10, 0.05]
