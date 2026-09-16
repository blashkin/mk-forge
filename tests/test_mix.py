"""Состав новых участников по сегментам шкалы и раздельные доли эффекта."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from mkforge.campaigns.motivational import Assumptions, build_plan, forecast_new_clients
from mkforge.core.loaders import load_inputs
from mkforge.core.pool import build_pool, segment_mix, shift_to_large

START, END = dt.date(2026, 9, 10), dt.date(2026, 10, 31)
TARGETS = (0.01, 0.03, 0.05)
THRESHOLD = 100.0  # синтетическая шкала: сегменты 0-40, 40-100, 100+


@pytest.fixture
def pool_dt(anon_dir: Path):
    return build_pool(load_inputs(anon_dir), "ДТ")


def test_mix_without_shift_equals_pool_average(pool_dt):
    """Главный инвариант: без сдвига новое считает то же, что считало старое.

    Иначе нельзя утверждать, что состав — обобщение среднего, а не замена.
    """
    mix = segment_mix(pool_dt)
    assert mix.tons_per_contract == pytest.approx(pool_dt.tons_per_contract)
    assert mix.stp_rate == pytest.approx(pool_dt.weighted("stp_rate"))
    assert mix.fee_rate == pytest.approx(pool_dt.weighted("service_fee_rate"))


def test_shares_sum_to_one(pool_dt):
    mix = segment_mix(pool_dt)
    assert sum(s.share for s in mix.segments) == pytest.approx(1.0)
    shifted = shift_to_large(mix, THRESHOLD, points=10)
    assert sum(s.share for s in shifted.segments) == pytest.approx(1.0)


def test_shift_raises_volume_and_lowers_rates(pool_dt):
    """Крупный клиент везет больше, но сидит в сегменте с меньшей СТП.

    Поэтому множитель на средний объем был бы неверен: ставки тоже меняются.
    """
    base = segment_mix(pool_dt)
    shifted = shift_to_large(base, THRESHOLD, points=10)
    assert shifted.tons_per_contract > base.tons_per_contract
    assert shifted.stp_rate < base.stp_rate
    assert shifted.fee_rate < base.fee_rate
    assert shifted.large_share(THRESHOLD) == pytest.approx(
        base.large_share(THRESHOLD) + 0.10
    )


def test_shift_is_monotonic(pool_dt):
    base = segment_mix(pool_dt)
    volumes = [
        shift_to_large(base, THRESHOLD, points=p).tons_per_contract for p in (0, 5, 10, 20)
    ]
    assert volumes == sorted(volumes)


def test_zero_shift_changes_nothing(pool_dt):
    base = segment_mix(pool_dt)
    assert shift_to_large(base, THRESHOLD, points=0) is base
    assert shift_to_large(base, THRESHOLD, points=-5) is base


def test_shift_cannot_exceed_available_small_share(pool_dt):
    """Забрать у мелких больше, чем у них есть, нельзя."""
    base = segment_mix(pool_dt)
    everything = shift_to_large(base, THRESHOLD, points=500)
    assert everything.large_share(THRESHOLD) == pytest.approx(1.0)
    assert all(s.share >= 0 for s in everything.segments)


def test_shift_without_large_segments_is_a_noop(pool_dt):
    base = segment_mix(pool_dt)
    assert shift_to_large(base, 10_000_000, points=10) is base


def test_forecast_uses_the_mix(anon_dir: Path, pool_dt, pool):
    plain = forecast_new_clients(
        load_inputs(anon_dir), pool_dt, "ДТ", START, END, len(pool) + 10
    )
    skewed = forecast_new_clients(
        load_inputs(anon_dir), pool_dt, "ДТ", START, END, len(pool) + 10,
        large_threshold_thousand_liters=THRESHOLD, large_shift_points=10,
    )
    assert plain.tons_per_client == pytest.approx(pool_dt.tons_per_contract)
    assert skewed.tons_per_client > plain.tons_per_client
    assert skewed.stp_rate < plain.stp_rate
    assert skewed.count == plain.count


def plan_for(anon_dir, **overrides):
    defaults = dict(
        plan_participants=30, share_without=0.0, share_with=1.0, new_share_without=0.0
    )
    return build_plan(
        inputs=load_inputs(anon_dir), product="ДТ", start=START, end=END,
        assumptions=Assumptions(**(defaults | overrides)), targets=TARGETS,
    )


def test_invariant_holds_with_shift(anon_dir):
    """Сдвиг состава не должен ломать подбор надбавки."""
    for level in plan_for(anon_dir, large_shift_points=10).levels:
        assert level.effective_discount == pytest.approx(level.target, abs=1e-12)


def test_kept_base_volume_lowers_the_effect(anon_dir):
    """Если объем текущих сохранился бы и без акции, эффектом остается меньше."""
    generous = plan_for(anon_dir).levels[0].effect
    honest = plan_for(anon_dir, share_without=0.9).levels[0].effect
    assert honest.tons < generous.tons
    assert honest.margin < generous.margin


def test_new_clients_are_absent_without_the_campaign(anon_dir):
    """Новых без акции не было бы: их доля в сценарии «без» нулевая."""
    level = plan_for(anon_dir, share_without=0.9).levels[0]
    assert level.without.tons > 0  # текущие остались
    assert level.without.participants == level.with_campaign.participants
    # Объем сценария «без» — только часть текущих, новых там нет.
    assert level.without.tons < level.with_campaign.tons


def test_campaign_without_extra_volume_costs_the_markup(anon_dir):
    """Если акция не приносит объема, она стоит ровно надбавку и уходит в минус.

    Проверяется крайним случаем: доли «без акции» и «с акцией» равны, то есть
    объем одинаков в обоих сценариях. Тогда весь эффект — это цена надбавки.
    """
    level = plan_for(anon_dir, share_without=1.0, new_share_without=1.0).levels[0]
    assert level.effect.tons == pytest.approx(0.0, abs=1e-9)
    assert level.effect.costs == pytest.approx(
        level.markup * level.with_campaign.revenue, rel=1e-9
    )
    assert level.effect.margin < 0
    assert level.effect.roi < 0
