"""Механика: надбавка подбирается так, чтобы цель равнялась факту ровно."""

from __future__ import annotations

import datetime as dt

import pytest

from mkforge.campaigns.motivational import Assumptions, build_plan, forecast_new_clients
from mkforge.core.loaders import load_inputs
from mkforge.core.pool import build_pool

START, END = dt.date(2026, 9, 10), dt.date(2026, 10, 31)
TARGETS = (0.01, 0.02, 0.03, 0.04, 0.05)


def plan_for(anon_dir, participants: int = 30, **overrides):
    assumptions = Assumptions(
        plan_participants=participants, share_without=0.0, share_with=1.0, **overrides
    )
    return build_plan(
        inputs=load_inputs(anon_dir), product="ДТ", start=START, end=END,
        assumptions=assumptions, targets=TARGETS,
    )


def test_target_equals_actual_on_every_level(anon_dir):
    """Главный инвариант механики: эффективная скидка равна заданной цели."""
    for level in plan_for(anon_dir).levels:
        assert level.effective_discount == pytest.approx(level.target, abs=1e-12)


def test_markup_is_positive(anon_dir):
    """Положительная цель требует положительной надбавки.

    Больше или меньше цели окажется номинал — зависит от того, насколько шкала СТП
    перекрывает сервисный сбор, то есть от конкретной шкалы и состава пула.
    На реальном пуле перекрывает с избытком и номинал выходит меньше цели,
    на синтетическом — нет. Законом механики это не является.
    """
    for level in plan_for(anon_dir).levels:
        assert level.markup > 0


def test_markup_grows_with_the_gap(anon_dir):
    """Чем глубже цель, тем больше надбавка, и шаг между уровнями ровный.

    Ровный шаг — следствие того, что надбавка линейна по цели: объем и выручка
    от уровня не зависят.
    """
    markups = [level.markup for level in plan_for(anon_dir).levels]
    steps = [b - a for a, b in zip(markups, markups[1:])]
    assert all(step > 0 for step in steps)
    assert max(steps) - min(steps) < 1e-12


def test_deeper_level_needs_bigger_markup(anon_dir):
    markups = [level.markup for level in plan_for(anon_dir).levels]
    assert markups == sorted(markups)


def test_deeper_level_costs_more_and_earns_less(anon_dir):
    levels = plan_for(anon_dir).levels
    costs = [level.effect.costs for level in levels]
    margins = [level.effect.margin for level in levels]
    assert costs == sorted(costs)
    assert margins == sorted(margins, reverse=True)


def test_payback_exceeds_roi_by_one(anon_dir):
    for level in plan_for(anon_dir).levels:
        assert level.effect.payback == pytest.approx(level.effect.roi + 1)


def test_volume_does_not_depend_on_level(anon_dir):
    """Объем задан прогнозом участников, а не глубиной скидки."""
    volumes = {level.effect.tons for level in plan_for(anon_dir).levels}
    assert len(volumes) == 1


def test_new_clients_fill_up_to_plan(anon_dir, pool):
    inputs = load_inputs(anon_dir)
    dt_pool = build_pool(inputs, "ДТ")
    new = forecast_new_clients(inputs, dt_pool, "ДТ", START, END, len(pool) + 7)
    assert new.count == 7
    assert new.tons_per_client == pytest.approx(dt_pool.tons_per_contract)
    assert new.term_months < 1.44  # короче срока акции: подключаются постепенно


def test_plan_below_current_pool_gives_no_new_clients(anon_dir, pool):
    inputs = load_inputs(anon_dir)
    dt_pool = build_pool(inputs, "ДТ")
    new = forecast_new_clients(inputs, dt_pool, "ДТ", START, END, len(pool) - 5)
    assert new.count == 0
    assert new.tons == 0.0


def test_participants_are_pool_plus_new(anon_dir, pool):
    plan = plan_for(anon_dir, participants=len(pool) + 10)
    assert plan.levels[0].with_campaign.participants == len(pool) + 10


def test_communication_raises_costs(anon_dir):
    plain = plan_for(anon_dir).levels[0]
    with_comms = plan_for(anon_dir, comms_per_client=1_000.0).levels[0]
    assert with_comms.effect.costs > plain.effect.costs
    assert with_comms.effective_discount == pytest.approx(with_comms.target, abs=1e-12)


def test_new_clients_have_own_margin(anon_dir):
    """Маржа новых считается по их календарю, а не по календарю действующих."""
    plan = plan_for(anon_dir)
    assert plan.new.margin_per_ton != pytest.approx(plan.economics.margin_per_ton)
