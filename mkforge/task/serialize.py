"""Результат расчета в словарь примитивов.

Поля перечислены поименно, и это не занудство. `dataclasses.asdict` здесь
применять нельзя по двум причинам сразу: свойства он не включает, а в свойствах
лежит как раз самое нужное — затраты, окупаемость, ROI, эффективная скидка; зато
он рекурсивно разворачивает `pool.members` и `forecast.members`, то есть сотни
строк с номерами договоров. Одна строка кода — и данные клиентов уезжают в
браузер вместе с тем, что просили.

Поэтому наружу отдаются только величины: размеры пулов, а не их состав. Ни
номера договора, ни псевдонима в выдаче нет ни на одном уровне вложенности —
это проверяется тестом, а не бдительностью.

Единицы базовые: доли (0.05, а не 5), рубли, тонны, договоры, месяцы. Округление
и знаки — забота того, кто показывает.
"""

from __future__ import annotations

from mkforge.campaigns.motivational import DepthResult, DistributedPlan
from mkforge.core.economics import Economics, Effect, Scenario


def scenario_payload(scenario: Scenario) -> dict:
    """Один сценарий: и поля, и посчитанные свойства."""
    return {
        "markup": scenario.markup,
        "participants": scenario.participants,
        "participant_months": scenario.participant_months,
        "tons": scenario.tons,
        "revenue": scenario.revenue,
        "discount": scenario.discount,
        "service_fee": scenario.service_fee,
        "gross_margin": scenario.gross_margin,
        "opex": scenario.opex,
        "comms": scenario.comms,
        "costs": scenario.costs,
        "net_margin": scenario.net_margin,
        "total_discount_rate": scenario.total_discount_rate,
        "effective_discount": scenario.effective_discount,
    }


def effect_payload(effect: Effect) -> dict:
    """Разница сценариев. `costs` отдается затем, чтобы читающий мог отличить
    «окупаемость ноль» от «окупаемость не определена»: при нулевых затратах
    `payback` и `roi` возвращают ноль, а не делят на ноль."""
    return {
        "tons": effect.tons,
        "costs": effect.costs,
        "margin": effect.margin,
        "service_fee": effect.service_fee,
        "payback": effect.payback,
        "roi": effect.roi,
    }


def economics_payload(economics: Economics) -> dict:
    return {
        "price_per_ton": economics.price_per_ton,
        "opex_per_ton": economics.opex_per_ton,
        "margin_per_ton": economics.margin_per_ton,
        "comms_per_client": economics.comms_per_client,
    }


def depth_payload(depth: DepthResult) -> dict:
    """Один срез пула: кому какая скидка и во что это обошлось."""
    return {
        "depth": depth.depth,
        "share": depth.share,
        "contracts": depth.contracts,
        "forecast_contracts": depth.forecast_contracts,
        "markup": depth.markup,
        "effective_discount": depth.effective_discount,
        "without": scenario_payload(depth.without),
        "with_campaign": scenario_payload(depth.with_campaign),
        "effect": effect_payload(depth.effect),
    }


def plan_payload(plan: DistributedPlan) -> dict:
    """Расчет акции целиком.

    От пула и прогнозного пула берутся только размеры: состав нужен книге,
    а не странице.
    """
    return {
        "product": plan.product,
        "months_current": plan.months_current,
        "pool_size": plan.pool.size,
        "pool_tons_per_month": plan.pool.total_tons_per_month,
        "forecast_size": plan.forecast.size,
        "rate_per_month": plan.rate.per_month,
        "rate_months": plan.rate.months,
        "by_volume": plan.distribution.by_volume,
        "effective_discount": plan.effective_discount,
        "markup": plan.markup,
        "depth": plan.depth,
        "volume_weighted_depth": plan.volume_weighted_depth,
        # None означает «в диапазоне от нуля до единицы порога нет». Это не
        # ошибка и не ноль: проглотить его нельзя, надо сказать словами.
        "breakeven_payback": plan.breakeven_payback,
        "breakeven_roi": plan.breakeven_roi,
        "without": scenario_payload(plan.without),
        "with_campaign": scenario_payload(plan.with_campaign),
        "effect": effect_payload(plan.effect),
        "depths": [depth_payload(depth) for depth in plan.depths],
        "economics": economics_payload(plan.economics),
    }


def checks_payload(report) -> dict:
    """Вердикты сверки книги.

    `worst_where` содержит псевдоним договора — на локальной странице это ключ
    к разбору расхождения. В черновик абзаца он не попадает: абзац копируют
    в переписку.
    """
    return {
        "ok": report.ok,
        "formula_errors": dict(report.formula_errors),
        "empty_cells": list(report.empty_cells),
        "levels_checked": report.levels_checked,
        "depths_checked": report.depths_checked,
        "target_equals_actual": report.target_equals_actual,
        "depth_equals_actual": report.depth_equals_actual,
        "breakeven": report.breakeven,
        "comparisons": [
            {
                "name": comparison.name,
                "compared": comparison.compared,
                "worst_diff": comparison.worst_diff,
                "worst_where": comparison.worst_contract,
                "matches": comparison.matches(report.tolerance),
            }
            for comparison in report.comparisons
        ],
    }


def build_payload(result) -> dict:
    return {
        "path": str(result.path),
        "name": result.path.name,
        "product": result.product,
        "transaction_rows": result.transaction_rows,
        "contract_rows": result.contract_rows,
        "forecast_rows": result.forecast_rows,
        "sheets": list(result.sheets),
        "notes": list(result.notes),
    }


def restore_payload(result) -> dict:
    return {
        "path": str(result.path),
        "name": result.path.name,
        "contracts": result.contracts,
        "recalculated": result.recalculated,
        "note": result.note,
    }
