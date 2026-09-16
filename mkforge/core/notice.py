"""Разбор уведомления о СТП: шкала скидок из документа Word.

Уведомление — первоисточник. Именно оно задает скидки, с датой и подписью,
и в нем есть трассовая шкала, которой нет нигде больше: в книгу ее никто
не переносил, поэтому трассовые АЗС до сих пор оставались оговоркой в правилах.

Разбирается таблица, у которой в подзаголовке стоят виды продукта. Индекс таблицы
не зашит: в документе есть еще таблица с адресатами, и порядок может поменяться.

Что приходится нормализовать:
скидки записаны отрицательными числами с запятой («-2,50»), границы объема —
строками с длинным тире, сносками и пробелами в тысячах («0 – 5**», «700 - 1 000»),
последний сегмент открыт («более 3 000»).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import docx

OPEN_BOUND = 999999

# Имя поля в шкале -> как подзаголовок таблицы называет этот продукт.
# Порядок важен: трассовая колонка начинается с «ДТ», поэтому проверяется первой.
PRODUCT_HEADERS = (
    ("дт_трасса", lambda text: text.startswith("ДТ на трассовых")),
    ("аб", lambda text: text == "АБ"),
    ("суг", lambda text: text == "СУГ"),
    ("дт", lambda text: text == "ДТ"),
)
REQUIRED_PRODUCTS = ("аб", "суг", "дт")

BOUNDS_HEADER = "объем выборки"
DASHES = "–—−‒"


class NoticeError(Exception):
    """Уведомление не той формы: нет таблицы шкалы или не читаются границы."""


@dataclass(frozen=True)
class NoticeBracket:
    """Сегмент шкалы, как он записан в уведомлении."""

    label: str
    low: float
    high: float
    rates: dict[str, float]

    def row(self) -> dict[str, object]:
        """Строка для stp_scale.csv.

        Продукт, колонки которого в уведомлении нет, получает ноль, а не пустую ячейку:
        пустую загрузчик не примет. Так же и шкала из книги пишет трассе ноль.
        """
        return {
            "сегмент": self.label,
            "мин_тыс_л": self.low,
            "макс_тыс_л": self.high,
            **{name: self.rates.get(name, 0.0) for name, _ in PRODUCT_HEADERS},
        }


def _clean(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def parse_rate(text: str) -> float:
    """Скидка из уведомления в долю: «-2,50» -> 0.025.

    Знак отбрасывается: в уведомлении скидка записана как отрицательная поправка
    к цене, а в расчете это положительная доля.
    """
    cleaned = _clean(text).replace(" ", "").replace(" ", "").replace(",", ".")
    if not cleaned:
        return 0.0
    try:
        return abs(float(cleaned)) / 100
    except ValueError as error:
        raise NoticeError(f"не разобрать скидку «{text}»") from error


def parse_bounds(text: str) -> tuple[float, float]:
    """Границы сегмента в тысячах литров: «0 – 5**» -> (0, 5)."""
    cleaned = _clean(text)
    for dash in DASHES:
        cleaned = cleaned.replace(dash, "-")
    cleaned = cleaned.replace("*", "")
    # Пробелы внутри чисел — разделители тысяч, а не границы токенов.
    numbers = [
        float(found.replace(" ", "").replace(" ", ""))
        for found in re.findall(r"\d[\d  ]*", cleaned)
    ]
    if not numbers:
        raise NoticeError(f"не разобрать границы объема «{text}»")
    if len(numbers) >= 2:
        return numbers[0], numbers[1]
    # Одна граница: открытый сегмент сверху («более 3 000») или снизу («до 5»).
    if "более" in cleaned.lower() or "свыше" in cleaned.lower():
        return numbers[0], OPEN_BOUND
    return 0.0, numbers[0]


def _find_scale_table(document) -> tuple[object, dict[str, int], int]:
    """Найти таблицу шкалы, колонки продуктов и номер первой строки с данными."""
    for table in document.tables:
        for index, row in enumerate(table.rows):
            cells = [_clean(cell.text) for cell in row.cells]
            columns: dict[str, int] = {}
            for position, text in enumerate(cells):
                for name, matches in PRODUCT_HEADERS:
                    if name not in columns and matches(text):
                        columns[name] = position
                        break
            if all(name in columns for name in REQUIRED_PRODUCTS):
                return table, columns, index + 1
    raise NoticeError(
        "в уведомлении не нашлась таблица шкалы: "
        f"нужна строка с подзаголовками {REQUIRED_PRODUCTS}"
    )


def _bounds_column(table, header_row: int) -> int:
    """Колонка с границами объема: ищется по подписи в шапке."""
    for row in table.rows[: header_row + 1]:
        for position, cell in enumerate(row.cells):
            if BOUNDS_HEADER in _clean(cell.text).lower():
                return position
    raise NoticeError(f"в таблице шкалы нет колонки «{BOUNDS_HEADER}»")


def parse_notice(path: Path) -> list[NoticeBracket]:
    """Прочитать шкалу СТП из уведомления."""
    if not path.exists():
        raise NoticeError(f"нет уведомления {path}")
    document = docx.Document(str(path))
    table, columns, first_data_row = _find_scale_table(document)
    bounds_column = _bounds_column(table, first_data_row - 1)

    brackets: list[NoticeBracket] = []
    previous_low: float | None = None
    for row in table.rows[first_data_row:]:
        cells = [_clean(cell.text) for cell in row.cells]
        label = cells[bounds_column] if bounds_column < len(cells) else ""
        if not label or not re.search(r"\d", label):
            continue
        low, high = parse_bounds(label)
        if previous_low is not None and low <= previous_low:
            continue  # повтор шапки или служебная строка
        brackets.append(
            NoticeBracket(
                label=label.replace("*", "").strip(),
                low=low,
                high=high,
                rates={
                    name: parse_rate(cells[position]) if position < len(cells) else 0.0
                    for name, position in columns.items()
                },
            )
        )
        previous_low = low

    if not brackets:
        raise NoticeError("в таблице шкалы не нашлось ни одного сегмента")
    return brackets
