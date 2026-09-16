"""Лист «Транзакции участников»: обезличенная выгрузка как есть.

Буквы колонок оставлены как в эталонной книге, потому что на них ссылаются все
формулы и по ним же идет сверка. Из 32 колонок эталона заполняются только те,
что несут данные: остальные были промежуточными вычислениями Excel — ключами,
счетчиками уникальности, справочными маржами. Поэтому буквы идут с пропусками,
и это намеренно.
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from mkforge.core.models import Transaction
from mkforge.renderers.grid import headers, put, widths

SHEET = "Транзакции участников"
FIRST_ROW = 2

# Буква колонки эталона -> (подпись, поле модели, стиль)
COLUMNS: dict[str, tuple[str, str, str]] = {
    "A": ("№ договора", "contract", "mk_text"),
    "B": ("Сегмент", "segment", "mk_text"),
    "E": ("Количество", "liters", "mk_tons"),
    "F": ("Выручка со скидкой", "revenue", "mk_money"),
    "G": ("Сервисный сбор", "raw_service_fee", "mk_money"),
    "H": ("Месяц", "month", "mk_date"),
    "I": ("Вид продукта", "product", "mk_text"),
    "J": ("Класс продукта", "product_class", "mk_text"),
    "L": ("Объем т", "tons", "mk_tons"),
    "W": ("Отделение ТО", "branch", "mk_text"),
}

CONTRACT = "A"
LITERS = "E"
REVENUE = "F"
SERVICE_FEE = "G"
MONTH = "H"
PRODUCT = "I"
PRODUCT_CLASS = "J"
TONS = "L"
BRANCH = "W"


def last_row(count: int) -> int:
    """Последняя строка с данными. От нее считаются все диапазоны формул."""
    return FIRST_ROW + count - 1


def write(ws: Worksheet, transactions: tuple[Transaction, ...]) -> int:
    """Выложить транзакции и вернуть номер последней строки с данными."""
    headers(ws, 1, {column: label for column, (label, _, _) in COLUMNS.items()})
    widths(ws, {"A": 16, "B": 10, "E": 14, "F": 16, "G": 14, "H": 12, "I": 12, "J": 12, "L": 12, "W": 24})

    for offset, transaction in enumerate(transactions):
        row = FIRST_ROW + offset
        for column, (_, attribute, style) in COLUMNS.items():
            put(ws, f"{column}{row}", getattr(transaction, attribute), style)

    ws.freeze_panes = "A2"
    return last_row(len(transactions))
