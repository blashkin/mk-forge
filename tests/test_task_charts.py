"""Графики: картинка обязана показывать то же, что число.

Самый ценный тест здесь — что в точке порога окупаемость равна единице. Он
связывает число, посчитанное ядром, с кривой, которую увидит человек: разойдись
они, отметка порога встала бы не на том месте, и никто бы этого не заметил.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mkforge.campaigns.motivational import plan_from_config
from mkforge.config import load_config
from mkforge.core.loaders import load_inputs
from mkforge.task.charts import depth_groups, money_breakdown, payback_curve
from mkforge.task.overrides import apply


@pytest.fixture
def inputs(anon_dir: Path):
    return load_inputs(anon_dir)


@pytest.fixture
def config(distributed_config_path: Path):
    return load_config(distributed_config_path)


@pytest.fixture
def plan(inputs, config):
    return plan_from_config(inputs, config)


@pytest.fixture
def curve(inputs, config, plan):
    return payback_curve(inputs, config, plan)


def test_curve_never_rises_with_the_share(curve):
    """Чем больше объема сохранилось бы без акции, тем ниже окупаемость."""
    paybacks = [point["payback"] for point in curve["points"] if point["costs"] > 0]
    assert paybacks == sorted(paybacks, reverse=True)


def test_curve_passes_through_the_current_number(curve, plan, config):
    """Точка «сейчас» на кривой — то же число, что на экране крупно."""
    at_current = [
        point for point in curve["points"]
        if point["share"] == pytest.approx(config.share_without)
    ]
    assert len(at_current) == 1
    assert at_current[0]["payback"] == pytest.approx(plan.effect.payback)


def test_payback_is_one_at_the_breakeven(curve):
    """Порог ядра стоит ровно там, где кривая пересекает единицу."""
    share = curve["breakeven_payback"]
    if share is None:
        pytest.skip("в этом конфиге порог окупаемости вне диапазона")
    at_threshold = [
        point for point in curve["points"] if point["share"] == pytest.approx(share)
    ]
    assert len(at_threshold) == 1
    assert at_threshold[0]["payback"] == pytest.approx(1.0, abs=1e-6)


def test_roi_is_one_at_its_breakeven(curve):
    share = curve["breakeven_roi"]
    if share is None:
        ends = curve["ends"]
        assert (ends["roi_at_0"] - 1) * (ends["roi_at_1"] - 1) >= 0, (
            "порога нет — значит оба конца по одну сторону единицы, "
            "и странице есть что сказать словами"
        )
        return
    at_threshold = [
        point for point in curve["points"] if point["share"] == pytest.approx(share)
    ]
    assert at_threshold[0]["roi"] == pytest.approx(1.0, abs=1e-6)


def test_curve_covers_the_whole_range(curve):
    shares = [point["share"] for point in curve["points"]]
    assert shares[0] == 0.0 and shares[-1] == 1.0
    assert shares == sorted(shares)
    assert len(set(shares)) == len(shares), "точки не повторяются"


def test_money_adds_up(plan):
    """Разложение обязано сходиться с тем, из чего считается окупаемость."""
    money = money_breakdown(plan)
    costs = money["costs"]
    assert costs["discount"] + costs["opex"] + costs["comms"] == pytest.approx(
        costs["total"]
    )
    assert money["returns"]["total"] - costs["total"] == pytest.approx(money["margin"])
    assert money["payback"] == pytest.approx(plan.effect.payback)


def test_groups_add_up_to_the_totals(plan):
    groups = depth_groups(plan)
    assert len(groups["groups"]) == len(plan.depths)
    assert groups["totals"]["costs"] == pytest.approx(plan.effect.costs)
    assert groups["totals"]["contracts"] == pytest.approx(plan.pool.size)
    assert groups["totals"]["tons"] == pytest.approx(plan.with_campaign.tons)


def test_volume_share_differs_from_pool_share(inputs, config):
    """Иначе третий график ничего не доказывает.

    При раздаче глубже крупным доля пула и доля объема у группы — разные числа.
    Ровно это и надо было показать: план расходится по скидкам не поровну.
    """
    concentrated, errors = apply(config, {"handout": "по_объему"})
    assert not errors
    plan = plan_from_config(inputs, concentrated)
    groups = depth_groups(plan)
    total_tons = groups["totals"]["tons"]
    deepest = groups["groups"][0]
    assert deepest["tons"] / total_tons != pytest.approx(deepest["share"], abs=1e-3)
