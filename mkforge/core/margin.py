"""Маржа продукта по месяцам из регионального прогноза экономистов.

Прогноз приходит в разрезе «месяц x вид продукта x регион». Расчету нужна одна
цифра на месяц, поэтому региональные значения взвешиваются по объему отделений,
которые на эти регионы ссылаются.

Замечание о знаменателе. Числитель суммируется только по известным отделениям,
а знаменатель — по всему объему продукта, включая транзакции без отделения.
Так считает эталонная книга: строка без отделения тянет маржу месяца вниз.
Поведение воспроизведено намеренно, а `loaders.check` о таких строках сообщает.
"""

from __future__ import annotations

from mkforge.core.calendar import MonthShare
from mkforge.core.models import Inputs


def _forecast(inputs: Inputs, product: str) -> dict[tuple[str, str], float]:
    """Средняя маржа по «месяц, регион». Повторяет AVERAGEIFS эталонной книги."""
    sums: dict[tuple[str, str], list[float]] = {}
    for row in inputs.margin:
        if row.product != product:
            continue
        sums.setdefault((row.month, row.region), []).append(row.margin)
    return {key: sum(values) / len(values) for key, values in sums.items()}


def _tons_by_branch(inputs: Inputs, product: str) -> tuple[dict[str, float], float]:
    """Объем продукта по отделениям и весь объем продукта, включая безотделенческий."""
    by_branch: dict[str, float] = {}
    total = 0.0
    for transaction in inputs.transactions:
        if transaction.product != product:
            continue
        total += transaction.tons
        if transaction.branch in inputs.branch_regions:
            by_branch[transaction.branch] = (
                by_branch.get(transaction.branch, 0.0) + transaction.tons
            )
    return by_branch, total


def monthly_margin(inputs: Inputs, product: str) -> dict[str, float]:
    """Маржа продукта на тонну по каждому месяцу, для которого есть прогноз."""
    forecast = _forecast(inputs, product)
    by_branch, total = _tons_by_branch(inputs, product)
    if total <= 0:
        return {}

    months = {month for month, _ in forecast}
    result: dict[str, float] = {}
    for month in months:
        weighted = sum(
            tons * forecast.get((month, inputs.branch_regions[branch]), 0.0)
            for branch, tons in by_branch.items()
        )
        result[month] = weighted / total
    return result


def margin_for_current(
    inputs: Inputs, product: str, shares: list[MonthShare]
) -> float:
    """Маржа действующих участников: взвешена по долям месяцев с прогнозом.

    Месяц без прогноза выпадает и из числителя, и из знаменателя.
    """
    by_month = monthly_margin(inputs, product)
    numerator = sum(s.current * by_month[s.name] for s in shares if s.name in by_month)
    denominator = sum(s.current for s in shares if s.name in by_month)
    return numerator / denominator if denominator else 0.0


def margin_for_new(inputs: Inputs, product: str, shares: list[MonthShare]) -> float:
    """Маржа новых участников: взвешена по их долям месяцев.

    Знаменатель здесь — весь их срок, а не только месяцы с прогнозом. Месяц без
    прогноза считается нулевой маржой и тянет среднее вниз; так считает книга.
    """
    by_month = monthly_margin(inputs, product)
    numerator = sum(s.new * by_month.get(s.name, 0.0) for s in shares)
    denominator = sum(s.new for s in shares)
    return numerator / denominator if denominator else 0.0
