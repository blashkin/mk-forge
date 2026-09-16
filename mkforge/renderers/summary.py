"""Лист «Итог акции»: первое, что видит человек, открывший книгу.

Остальные листы отвечают на вопрос «как посчитано». Этот отвечает на вопрос
«что получилось», и больше ни на какой. Пятнадцать строк, никаких служебных
величин, ни одного слова, которого нет в обычном разговоре.

Все числа — ссылки на разделы, где они считаются. Здесь ничего не считается
заново: иначе два места стали бы расходиться.
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from mkforge.config import CampaignConfig
from mkforge.renderers import calculation as calc
from mkforge.renderers import distribution as dist
from mkforge.renderers import forecast as fc
from mkforge.renderers import showcase
from mkforge.renderers.grid import put, section, widths

SHEET = "Итог акции"


def write(ws: Worksheet, config: CampaignConfig) -> None:
    """Выложить лист итога."""
    assert config.distribution is not None, "лист итога пишется при распределении глубины"
    count = len(config.distribution.shares)
    total = dist.total_row(count)
    breakeven = list(dist.breakeven_rows(count).values())
    calculation = f"'{calc.SHEET}'!"

    widths(ws, {"A": 52, "B": 22, "C": 66})
    section(ws, 1, "Итог акции", 3)

    row = 3
    put(ws, f"A{row}", "Что за акция", "mk_label")
    put(ws, f"B{row}", f"Надбавка к СТП на {config.product}", "mk_text")
    put(ws, f"C{row}",
        "Скидку раздают менеджеры по договору, не всем одинаково. "
        "Основная масса приходится на 4-5%.", "mk_note")

    row += 1
    put(ws, f"A{row}", "Период", "mk_label")
    put(ws, f"B{row}",
        f"{config.start.strftime('%d.%m.%Y')} - {config.end.strftime('%d.%m.%Y')}",
        "mk_text")

    row += 1
    put(ws, f"A{row}", "Клиентов в акции", "mk_label")
    put(ws, f"B{row}", f"={calculation}$B$18+{calculation}$B${calc.NEW_COUNT}", "mk_count")
    put(ws, f"C{row}",
        f"=\"действующих \"&TEXT({calculation}$B$18,\"# ##0\")"
        f"&\", прогноз новых \"&TEXT({calculation}$B${calc.NEW_COUNT},\"# ##0\")"
        f"&\" (лист «{fc.SHEET}»)\"", "mk_note")

    row += 1
    put(ws, f"A{row}", "Скидка, которую в среднем получает клиент", "mk_label")
    put(ws, f"B{row}", f"={calculation}${dist.EFFECTIVE}${total}", "mk_pct")
    put(ws, f"C{row}",
        "Средневзвешенная по объему. Складывается из распределения: "
        "кому 5%, кому 1%. Само распределение — лист расчета, раздел 6.", "mk_note")

    row += 1
    put(ws, f"A{row}", "Сколько акция стоит, руб.", "mk_label")
    put(ws, f"B{row}", f"={calculation}${dist.EXTRA_COSTS}${total}", "mk_money")
    put(ws, f"C{row}", "Скидка плюс OPEX на дополнительный объем.", "mk_note")

    row += 1
    put(ws, f"A{row}", "Сколько приносит, руб.", "mk_label")
    put(ws, f"B{row}", f"={calculation}${dist.EXTRA_MARGIN}${total}", "mk_money")
    put(ws, f"C{row}", "Дополнительная маржа с учетом сервисного сбора.", "mk_note")

    row += 1
    put(ws, f"A{row}", "Окупаемость, руб. на рубль затрат", "mk_label")
    put(ws, f"B{row}", f"={calculation}${dist.PAYBACK}${total}", "mk_ratio")
    put(ws, f"C{row}",
        "Больше единицы — акция возвращает больше, чем стоит.", "mk_note")

    row += 1
    verdict_row = row
    put(ws, f"A{row}", "Уходим ли в минус", "mk_label")
    put(ws, f"B{row}",
        f'=IF({calculation}${dist.PAYBACK}${total}>1,"нет, не уходим","ДА, УХОДИМ В МИНУС")',
        "mk_text")

    row += 1
    put(ws, f"A{row}", "ROI, руб. на рубль затрат", "mk_label")
    put(ws, f"B{row}", f"={calculation}${dist.ROI}${total}", "mk_ratio")
    put(ws, f"C{row}",
        "Это не то же, что окупаемость: ROI = окупаемость минус единица. "
        "ROI выше 1 значит, что маржа перекрыла затраты вдвое.", "mk_note")

    row += 2
    section(ws, row, "От чего зависит ответ", 3)

    row += 1
    put(ws, f"A{row}", "Считаем, что без акции осталось бы объема", "mk_label")
    put(ws, f"B{row}", f"='{showcase.SHEET}'!$B${showcase.SHARE_WITHOUT}", "mk_pct")
    put(ws, f"C{row}",
        "Это не расчет, а решение. Именно оно определяет, сходится акция или нет. "
        f"Менять на листе «{showcase.SHEET}», ячейка B{showcase.SHARE_WITHOUT}.",
        "mk_note")

    row += 1
    put(ws, f"A{row}", "До какой доли акция не уходит в минус", "mk_label")
    put(ws, f"B{row}", f"={calculation}$B${breakeven[4]}", "mk_pct")
    put(ws, f"C{row}",
        "Поставишь долю выше этого значения — уходим в минус. "
        "Поставишь ниже — держимся.", "mk_note")

    row += 1
    put(ws, f"A{row}", "До какой доли ROI выше 1", "mk_label")
    put(ws, f"B{row}", f"={calculation}$B${breakeven[5]}", "mk_pct")
    put(ws, f"C{row}",
        "«Недостижимо» значит, что на глубине 4-5% ROI выше единицы "
        "не выходит ни при каком допущении.", "mk_note")

    row += 2
    section(ws, row, "Что можно поменять прямо в книге", 3)
    row += 1
    for label, where in (
        ("Кому какая скидка достается и каким долям пула",
         f"лист «{calc.SHEET}», раздел 6, колонка «Доля пула»"),
        ("Глубже крупным или вне зависимости от размера",
         f"лист «{calc.SHEET}», ячейка {dist.MODE}: 1 или 0"),
        ("Доля объема, который был бы и без акции",
         f"лист «{showcase.SHEET}», ячейка B{showcase.SHARE_WITHOUT}"),
        ("Сроки акции",
         f"лист «{showcase.SHEET}», ячейки B{showcase.START} и B{showcase.END}"),
    ):
        put(ws, f"A{row}", label, "mk_label")
        put(ws, f"B{row}", where, "mk_text")
        row += 1

    put(ws, f"A{row + 1}",
        "Книга живая: поменял ячейку — пересчиталось все. Формулы трогать не нужно.",
        "mk_note")
    ws.freeze_panes = "A3"
    return verdict_row
