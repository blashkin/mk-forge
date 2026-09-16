"""Листы «Справочник» и «Справочник МК».

В эталонной книге здесь лежали справочники продуктов и регионов. Часть из них
после обезличивания недоступна — группа продукта и регион в расчете не участвуют
и из выгрузки отбрасываются. Поэтому листы заполняются тем, что есть на самом деле,
а не воспроизводятся формально.

«Справочник» описывает состав выгрузки и уровни акции: по нему видно, из чего
собран расчет. «Справочник МК» описывает саму механику — это карточка акции.
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from mkforge.config import CampaignConfig
from mkforge.core.models import Inputs
from mkforge.renderers import transactions as tx
from mkforge.renderers.grid import column_range, headers, put, section, widths

REFERENCE_SHEET = "Справочник"
CAMPAIGN_SHEET = "Справочник МК"

PRODUCTS_FIRST_ROW = 3
LEVELS_SECTION_ROW = 14
LEVELS_HEADER_ROW = 15
LEVELS_FIRST_ROW = 16


def write_reference(ws: Worksheet, inputs: Inputs, tx_last: int, config: CampaignConfig) -> None:
    """Состав выгрузки и уровни акции."""
    widths(ws, {"A": 20, "B": 18, "C": 18, "D": 14, "E": 40})

    section(ws, 1, "1. Виды продукта в выгрузке", 4)
    headers(ws, 2, {
        "A": "Вид продукта", "B": "Класс продукта", "C": "Объем, т", "D": "Строк",
    })
    pairs = sorted(
        {(t.product, t.product_class) for t in inputs.transactions if t.is_classified}
    )
    products = column_range(tx.SHEET, tx.PRODUCT, tx_last)
    classes = column_range(tx.SHEET, tx.PRODUCT_CLASS, tx_last)
    tons = column_range(tx.SHEET, tx.TONS, tx_last)

    row = PRODUCTS_FIRST_ROW
    for product, product_class in pairs:
        put(ws, f"A{row}", product, "mk_text")
        put(ws, f"B{row}", product_class, "mk_text")
        put(ws, f"C{row}",
            f'=SUMIFS({tons},{products},$A{row},{classes},$B{row})', "mk_tons")
        put(ws, f"D{row}",
            f'=COUNTIFS({products},$A{row},{classes},$B{row})', "mk_count")
        row += 1

    unclassified = sum(1 for t in inputs.transactions if not t.is_classified)
    if unclassified:
        put(ws, f"A{row}", "Без разметки", "mk_label")
        put(ws, f"D{row}", unclassified, "mk_count")
        put(ws, f"E{row}",
            "Строки без вида или класса продукта не попадают ни в один итог", "mk_note")

    section(ws, LEVELS_SECTION_ROW, "2. Уровни акции", 3)
    headers(ws, LEVELS_HEADER_ROW, {
        "A": "Уровень", "B": "Целевая эффективная скидка, %", "C": "Пояснение",
    })
    for index, target in enumerate(config.targets):
        level_row = LEVELS_FIRST_ROW + index
        put(ws, f"A{level_row}", f"Уровень {target * 100:g}%", "mk_text")
        put(ws, f"B{level_row}", target, "mk_pct")
    put(ws, f"C{LEVELS_FIRST_ROW}",
        f"Выбирается на витрине в ячейке B24. Сейчас выбран "
        f"{config.showcase_level * 100:g}%", "mk_note")


def write_campaign(ws: Worksheet, config: CampaignConfig) -> None:
    """Карточка механики: чем эта акция задается."""
    widths(ws, {"A": 34, "B": 60})
    section(ws, 1, "Карточка механики", 2)
    headers(ws, 2, {"A": "Поле", "B": "Значение"})

    levels = ", ".join(f"{target * 100:g}%" for target in config.targets)
    excluded = ", ".join(config.products_excluded) or "нет"
    fields = (
        ("Название МК", config.name),
        ("Механика", config.mechanic),
        ("Вид продукта", config.product),
        ("Тип скидки", f"надбавка к СТП на {config.product}"),
        ("Как задается уровень", "целевая эффективная скидка клиента"),
        ("Уровни скидки", levels),
        ("Период", f"{config.start:%d.%m.%Y} - {config.end:%d.%m.%Y}"),
        ("План участников, ед.", config.plan_participants),
        ("Продукты вне акции", excluded),
        (
            "Максимальная ставка сервисного сбора",
            config.max_service_fee if config.max_service_fee is not None else "не задана",
        ),
    )
    for index, (label, value) in enumerate(fields):
        row = 3 + index
        put(ws, f"A{row}", label, "mk_label")
        put(ws, f"B{row}", value, "mk_text")

    note = 3 + len(fields) + 1
    put(ws, f"A{note}",
        "Механика: надбавка к СТП подбирается так, чтобы средневзвешенная эффективная "
        "скидка клиента равнялась выбранному уровню. Подбор и проверка — на листе "
        "«Расчет акции», раздел 5, колонки AQ и AR.", "mk_note")
