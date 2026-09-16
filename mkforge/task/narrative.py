"""Черновик абзаца для пересылки.

Принимает только словари сериализатора, а не объекты расчета. Это не лишний
слой: абзац копируют в переписку, и до номера договора ему не должно быть чем
дотянуться. Псевдоним из вердиктов сверки сюда тоже не попадает.

Текст короткий намеренно. Тому, кто получит книгу, нужны период, механика,
участники, деньги и одно предложение про допущение — а не пересказ расчета.
"""

from __future__ import annotations


def _money(value: float) -> str:
    """Миллионы рублей: в переписке про такие суммы говорят так."""
    return f"{value / 1e6:,.0f} млн руб.".replace(",", " ")


def _percent(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}".replace(".", ",") + "%"


def _ratio(value: float) -> str:
    """Отношение с запятой: 1,43, а не 1.43."""
    return f"{value:.2f}".replace(".", ",")


def _number(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def paragraph(campaign: dict, plan: dict, checks: dict | None, file_name: str) -> str:
    """Собрать абзац. `checks` может быть пустым: книгу могли не сверять."""
    effect = plan["effect"]
    handout = (
        "глубокие проценты достаются тем, кто больше везет"
        if plan["by_volume"]
        else "скидка раздается вне зависимости от размера клиента"
    )
    depths = plan["depths"]
    spread = ", ".join(
        f"{_percent(part['depth'], 0)} — {_number(part['contracts'] + part['forecast_contracts'])}"
        for part in depths
    )

    lines = [
        f"{campaign['name']}, {campaign['product']}: "
        f"с {_date(campaign['start'])} по {_date(campaign['end'])}.",
        f"Участников {_number(plan['pool_size'] + plan['forecast_size'])} — "
        f"{_number(plan['pool_size'])} действующих и {_number(plan['forecast_size'])} "
        f"новых по прогнозу. Скидки распределены так: {spread} участников. "
        f"Средняя эффективная скидка {_percent(plan['effective_discount'], 2)}, "
        f"{handout}.",
        f"Затраты акции {_money(effect['costs'])}, дополнительная маржа "
        f"{_money(effect['margin'])}, окупаемость {_ratio(effect['payback'])}, "
        f"ROI {_ratio(effect['roi'])}.",
        _assumption(plan),
    ]
    if checks is not None:
        lines.append(_verdict(checks))
    lines.append(f"Файл: {file_name}.")
    return "\n".join(lines)


def _date(iso: str) -> str:
    year, month, day = iso.split("-")
    return f"{day}.{month}.{year}"


def _assumption(plan: dict) -> str:
    """Одно предложение про то, на чем стоит знак результата."""
    share = plan["without"]["tons"] / plan["with_campaign"]["tons"] if plan["with_campaign"]["tons"] else 0
    threshold = plan["breakeven_payback"]
    if threshold is None:
        return (
            f"Расчет считает эффектом {_percent(1 - share, 0)} объема. "
            f"Окупаемость единицу в диапазоне не пересекает."
        )
    return (
        f"Расчет считает эффектом {_percent(1 - share, 0)} объема. "
        f"Акция не уходит в минус, пока без нее сохранилось бы не больше "
        f"{_percent(threshold)} объема — это и есть главное допущение."
    )


def _verdict(checks: dict) -> str:
    if checks["ok"]:
        return (
            "Книга проверена: ошибок в формулах нет, числа сходятся с независимым "
            "расчетом, заданная скидка равна фактической."
        )
    problems = []
    if checks["formula_errors"]:
        problems.append("в формулах есть ошибки")
    if checks["empty_cells"]:
        problems.append("часть ячеек не посчиталась")
    if not checks["target_equals_actual"] or not checks["depth_equals_actual"]:
        problems.append("заданная скидка не равна фактической")
    if any(not comparison["matches"] for comparison in checks["comparisons"]):
        problems.append("числа книги расходятся с независимым расчетом")
    return "Книгу отдавать нельзя: " + ", ".join(problems) + "."
