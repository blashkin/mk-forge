"""Данные трех графиков. Рисует их страница, считает — ядро.

Правило жесткое: здесь только то, что уже посчитано механикой, плюс пересчет той
же механикой в других точках. Ни одной собственной формулы — иначе у проекта
станет три расчета вместо двух, и однажды картинка разойдется с книгой.

Кривая окупаемости получается пересчетом плана при разных долях объема без
акции. Аналитически она известна в замкнутой форме, но выписывать ее здесь
значило бы завести вторую формулу рядом с той, что уже стоит в книге. Пересчет
стоит около десяти миллисекунд за точку — за эту цену расхождения не бывает
по построению.
"""

from __future__ import annotations

from dataclasses import replace

from mkforge.campaigns.motivational import (
    DistributedPlan,
    assumptions_from,
    build_distributed_plan,
)
from mkforge.config import CampaignConfig
from mkforge.core.models import Inputs

CURVE_POINTS = 21


def _grid(config: CampaignConfig, plan: DistributedPlan, points: int) -> tuple[float, ...]:
    """Доли, в которых считаем кривую.

    Ровная сетка плюс три особые точки: текущая доля и оба порога. Так кривая
    проходит ровно через отметки, которые страница на ней и рисует, — иначе
    порог стоял бы рядом с кривой, а не на ней.
    """
    step = 1 / (points - 1)
    shares = {round(index * step, 10) for index in range(points)}
    shares.add(config.share_without)
    for breakeven in (plan.breakeven_payback, plan.breakeven_roi):
        if breakeven is not None:
            shares.add(breakeven)
    return tuple(sorted(share for share in shares if 0 <= share <= 1))


def payback_curve(
    inputs: Inputs,
    config: CampaignConfig,
    plan: DistributedPlan,
    points: int = CURVE_POINTS,
) -> dict:
    """Окупаемость и ROI как функция доли объема, которая сохранилась бы без акции.

    Это главный рычаг расчета: он один решает знак результата. Порог рядом с
    кривой важнее самого числа окупаемости — он показывает, где допущение
    перестает держать акцию выше нуля.
    """
    assumptions = assumptions_from(config)
    curve = []
    for share in _grid(config, plan, points):
        at = build_distributed_plan(
            inputs,
            config.product,
            config.start,
            config.end,
            replace(assumptions, share_without=share),
            config.distribution,
        )
        effect = at.effect
        curve.append({
            "share": share,
            # costs нужен читающему, чтобы отличить «окупаемость ноль» от
            # «окупаемость не определена»: при нулевых затратах ядро возвращает
            # ноль, а не делит на ноль.
            "costs": effect.costs,
            "margin": effect.margin,
            "payback": effect.payback,
            "roi": effect.roi,
        })

    return {
        "points": curve,
        "current_share": config.share_without,
        "breakeven_payback": plan.breakeven_payback,
        "breakeven_roi": plan.breakeven_roi,
        "ends": {
            "payback_at_0": curve[0]["payback"],
            "payback_at_1": curve[-1]["payback"],
            "roi_at_0": curve[0]["roi"],
            "roi_at_1": curve[-1]["roi"],
        },
    }


def money_breakdown(plan: DistributedPlan) -> dict:
    """Из чего собраны затраты акции и что возвращается.

    Считается по разнице сценариев, а не по сценарию с акцией: окупаемость —
    это отношение приростов, и раскладывать надо ровно то, что в ней стоит.
    """
    effect = plan.effect
    with_campaign, without = plan.with_campaign, plan.without
    gross = with_campaign.gross_margin - without.gross_margin
    return {
        "costs": {
            "discount": with_campaign.discount - without.discount,
            "opex": with_campaign.opex - without.opex,
            "comms": with_campaign.comms - without.comms,
            "total": effect.costs,
        },
        "returns": {
            "gross_margin": gross,
            "service_fee": effect.service_fee,
            "total": gross + effect.service_fee,
        },
        "margin": effect.margin,
        "payback": effect.payback,
        "roi": effect.roi,
    }


def depth_groups(plan: DistributedPlan) -> dict:
    """Участники по скидкам и вклад каждой группы в объем и в затраты.

    Тот самый график, которого не хватило: «по каждой скидке участвует весь план»
    было вопросом к картинке, а не к расчету. Доля пула, доля объема и доля
    затрат — три разные величины, и рядом это видно без слов.
    """
    groups = [
        {
            "depth": part.depth,
            "share": part.share,
            "contracts": part.contracts,
            "forecast_contracts": part.forecast_contracts,
            "markup": part.markup,
            "tons": part.with_campaign.tons,
            "revenue": part.with_campaign.revenue,
            "costs": part.effect.costs,
            "margin": part.effect.margin,
        }
        for part in plan.depths
    ]
    return {
        "groups": groups,
        "totals": {
            "contracts": sum(group["contracts"] for group in groups),
            "forecast_contracts": sum(group["forecast_contracts"] for group in groups),
            "tons": sum(group["tons"] for group in groups),
            "revenue": sum(group["revenue"] for group in groups),
            "costs": sum(group["costs"] for group in groups),
            "margin": sum(group["margin"] for group in groups),
        },
    }
