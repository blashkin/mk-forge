"""Механика с распределенной глубиной: итог складывается из срезов."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from mkforge.config import load_config
from mkforge.core.loaders import load_inputs
from mkforge.campaigns.motivational import build_distributed_plan, plan_from_config


@pytest.fixture
def inputs(anon_dir: Path):
    return load_inputs(anon_dir)


@pytest.fixture
def config(distributed_config_path: Path):
    return load_config(distributed_config_path)


@pytest.fixture
def plan(inputs, config):
    return plan_from_config(inputs, config)


def rebuild(inputs, config, **changes):
    from mkforge.campaigns.motivational import assumptions_from

    return build_distributed_plan(
        inputs, config.product, config.start, config.end,
        replace(assumptions_from(config), **changes), config.distribution,
    )


def test_every_slice_hits_its_depth_exactly(plan):
    """Главный инвариант механики: заданная глубина равна фактической."""
    for part in plan.depths:
        assert part.effective_discount == pytest.approx(part.depth, abs=1e-12)


def test_total_effective_discount_is_the_volume_weighted_depth(plan):
    """Итог не может отличаться от того, что дали срезы."""
    assert plan.effective_discount == pytest.approx(
        plan.volume_weighted_depth, abs=1e-12
    )


def test_slices_add_up_to_the_total(plan):
    assert sum(part.with_campaign.revenue for part in plan.depths) == pytest.approx(
        plan.with_campaign.revenue
    )
    assert sum(part.effect.costs for part in plan.depths) == pytest.approx(
        plan.effect.costs
    )
    assert sum(part.effect.margin for part in plan.depths) == pytest.approx(
        plan.effect.margin
    )


def test_all_contracts_are_in_some_slice(plan):
    assert sum(part.contracts for part in plan.depths) == pytest.approx(plan.pool.size)
    assert sum(part.forecast_contracts for part in plan.depths) == pytest.approx(
        plan.forecast.size
    )


def test_deeper_slice_needs_a_bigger_markup(plan):
    """Глубже скидка — выше номинал надбавки, при любом составе среза."""
    markups = [part.markup for part in plan.depths]
    assert markups == sorted(markups, reverse=True)


def test_markup_differs_between_slices(plan):
    """Та самая поправка: у крупных СТП ниже, значит надбавка нужна другая.

    Если бы надбавка была одна на пул, разным клиентам она дала бы разную
    эффективную скидку — именно это и просили исправить.
    """
    by_depth = {part.depth: part.markup for part in plan.depths}
    assert len(set(by_depth.values())) == len(by_depth)


def test_payback_equals_one_at_the_breakeven_share(inputs, config, plan):
    """Порог — это решение уравнения, а не подбор: проверяем подстановкой."""
    assert plan.breakeven_payback is not None
    at_threshold = rebuild(inputs, config, share_without=plan.breakeven_payback)
    assert at_threshold.effect.payback == pytest.approx(1.0, abs=1e-9)


def test_roi_equals_one_at_its_breakeven_share(inputs, config, plan):
    if plan.breakeven_roi is None:
        pytest.skip("на этих данных ROI=1 недостижим ни при какой доле")
    at_threshold = rebuild(inputs, config, share_without=plan.breakeven_roi)
    assert at_threshold.effect.roi == pytest.approx(1.0, abs=1e-9)


def test_stricter_assumption_never_helps(inputs, config):
    """Чем больше объема сохранилось бы без акции, тем хуже окупаемость."""
    paybacks = [
        rebuild(inputs, config, share_without=share).effect.payback
        for share in (0.0, 0.3, 0.6, 0.9)
    ]
    assert paybacks == sorted(paybacks, reverse=True)


def test_concentrated_handout_costs_more(inputs, config):
    """Раздача глубокой скидки крупным дороже, чем вне зависимости от размера."""
    from mkforge.core.allocation import Distribution
    from mkforge.campaigns.motivational import assumptions_from

    assumptions = assumptions_from(config)
    flat = Distribution(shares=config.distribution.shares, by_volume=False)
    concentrated = build_distributed_plan(
        inputs, config.product, config.start, config.end, assumptions, config.distribution
    )
    even = build_distributed_plan(
        inputs, config.product, config.start, config.end, assumptions, flat
    )
    assert concentrated.effective_discount >= even.effective_discount - 1e-12
    assert concentrated.effect.costs >= even.effect.costs - 1e-6


def test_plan_on_the_whole_campaign_sets_the_forecast(plan, config):
    """План ставят на всю акцию, значит новые — это план минус текущий пул."""
    assert config.plan_participants > plan.pool.size
    assert plan.forecast.size == config.plan_participants - plan.pool.size


def test_without_a_plan_the_forecast_comes_from_the_rate(inputs, config):
    """Плана нет — опираемся на фактический темп подключения, а не на догадку."""
    from mkforge.campaigns.motivational import assumptions_from
    from mkforge.core.growth import connection_rate, expected_new_clients
    from mkforge.core.calendar import campaign_months

    assumptions = replace(assumptions_from(config), plan_participants=None)
    from mkforge.campaigns.motivational import build_distributed_plan

    without_plan = build_distributed_plan(
        inputs, config.product, config.start, config.end,
        assumptions, config.distribution,
    )
    rate = connection_rate(inputs.contracts, assumptions.rate_window_months)
    assert without_plan.forecast.size == expected_new_clients(
        rate, campaign_months(config.start, config.end), assumptions.uplift
    )


def test_plan_needs_a_distribution(inputs, config_path: Path):
    with pytest.raises(ValueError, match="распределение"):
        plan_from_config(inputs, load_config(config_path))
