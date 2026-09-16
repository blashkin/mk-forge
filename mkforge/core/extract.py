"""Извлечение таблиц-параметров из книги: шкала СТП, экономика, прогноз маржи.

Клиентских данных здесь нет: шкала СТП публична (уведомление), экономика и прогноз
маржи — внутренние цифры по продуктам и регионам, без привязки к контрагенту.
Поэтому эти таблицы не обезличиваются, а просто вынимаются из книги в плоские csv.

Проценты приводятся к долям: в книге шкала записана числами (2.5 = 2,5%),
в csv уходит 0.025. Экономика в книге уже в долях, пересчет к ней не применяется.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from mkforge.core.notice import parse_notice

PARAMETERS_SHEET = "База для расчета"

SCALE_FIRST_ROW = 3
ECONOMICS_HEADER_ROW = 24
ECONOMICS_FIRST_ROW = 25
ECONOMICS_LAST_ROW = 31
MARGIN_FIRST_ROW = 3

# Метки экономики, которые в книге уже лежат долями — их не делим на 100.
ECONOMICS_FRACTION_LABELS = frozenset(
    {
        "Скидка/СТП без акции, %",
        "Средняя ставка сервисного сбора, %",
        "Маржа СТиУ, %",
    }
)


class ParametersError(Exception):
    """В книге нет листа параметров или таблица не той формы."""


@dataclass
class ExtractResult:
    scale_rows: int = 0
    economics_rows: int = 0
    margin_rows: int = 0
    months: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            f"шкала СТП:        {self.scale_rows} сегментов",
            f"экономика:        {self.economics_rows} показателей",
            f"прогноз маржи:    {self.margin_rows} строк, "
            f"{len(self.months)} месяцев, {len(self.regions)} регионов",
        ]
        lines += [f"записан {path}" for path in self.files]
        lines += [f"  {note}" for note in self.notes]
        return "\n".join(lines)


def _read_scale(ws) -> list[dict]:
    """Шкала СТП: сегменты по объему выборки и скидка по каждому виду продукта.

    Таблица кончается там, где нижняя граница перестает расти: следом в книге идут
    служебные строки «Более 0» и «Средняя скидка», которые сегментами не являются.
    """
    rows: list[dict] = []
    previous = None
    row = SCALE_FIRST_ROW
    while True:
        low, high = ws[f"E{row}"].value, ws[f"F{row}"].value
        if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
            break
        if previous is not None and low <= previous:
            break  # служебная строка, а не следующий сегмент
        rows.append(
            {
                "сегмент": ws[f"A{row}"].value,
                "мин_тыс_л": low,
                "макс_тыс_л": high,
                "аб": (ws[f"B{row}"].value or 0) / 100,
                "дт": (ws[f"C{row}"].value or 0) / 100,
                "суг": (ws[f"D{row}"].value or 0) / 100,
                # В книге трассовой колонки нет: ее никто туда не переносил.
                # Настоящие ставки приходят только из уведомления.
                "дт_трасса": 0.0,
            }
        )
        previous = low
        row += 1
    if not rows:
        raise ParametersError(f"на листе «{PARAMETERS_SHEET}» не нашлась шкала СТП")
    return rows


def _read_economics(ws) -> list[dict]:
    """Экономика по виду продукта: цена, себестоимость, OPEX, маржа, ставка сбора."""
    products = [
        (letter, ws[f"{letter}{ECONOMICS_HEADER_ROW}"].value)
        for letter in ("B", "C", "D", "E")
    ]
    rows = []
    for row in range(ECONOMICS_FIRST_ROW, ECONOMICS_LAST_ROW + 1):
        label = ws[f"A{row}"].value
        if not label:
            continue
        record = {"показатель": label}
        for letter, product in products:
            value = ws[f"{letter}{row}"].value
            record[str(product).lower()] = value if value is not None else 0
        rows.append(record)
    if not rows:
        raise ParametersError(f"на листе «{PARAMETERS_SHEET}» не нашлась экономика по продукту")
    return rows


def _read_margin(ws) -> list[dict]:
    """Прогноз маржи экономистов: месяц x вид продукта x регион -> руб/т."""
    rows = []
    row = MARGIN_FIRST_ROW
    while True:
        month = ws[f"L{row}"].value
        if month in (None, ""):
            break
        rows.append(
            {
                "месяц": month,
                "вид_продукта": ws[f"M{row}"].value,
                "маржа_руб_т": ws[f"N{row}"].value,
                "регион": ws[f"O{row}"].value,
            }
        )
        row += 1
    if not rows:
        raise ParametersError(f"на листе «{PARAMETERS_SHEET}» не нашелся прогноз маржи")
    return rows


# Порядок колонок шкалы закреплен: иначе он зависит от источника — книги или
# уведомления — и диффы между запусками становятся шумными.
SCALE_FIELDS = ("сегмент", "мин_тыс_л", "макс_тыс_л", "аб", "дт", "суг", "дт_трасса")


def _write_csv(path: Path, rows: list[dict], fields: tuple[str, ...] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fields or rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def extract(source: Path, out_dir: Path, notice: Path | None = None) -> ExtractResult:
    """Вынуть таблицы-параметры в data/anon.

    Шкала СТП берется из уведомления, если оно передано: это первоисточник,
    и только в нем есть трассовые ставки. Иначе — из книги, но тогда трассовая
    шкала останется пустой, и об этом говорится в отчете.
    """
    wb = openpyxl.load_workbook(source, data_only=True)
    try:
        if PARAMETERS_SHEET not in wb.sheetnames:
            raise ParametersError(f"в книге нет листа «{PARAMETERS_SHEET}»")
        ws = wb[PARAMETERS_SHEET]
        scale = _read_scale(ws)
        economics = _read_economics(ws)
        margin = _read_margin(ws)
    finally:
        wb.close()

    notes: list[str] = []
    if notice is not None:
        brackets = parse_notice(notice)
        scale = [bracket.row() for bracket in brackets]
        if any("дт_трасса" in bracket.rates for bracket in brackets):
            notes.append(f"шкала СТП взята из уведомления {notice.name}, с трассовыми ставками")
        else:
            notes.append(
                f"шкала СТП взята из уведомления {notice.name}: трассовой колонки в нем нет, "
                "трассовые ставки нулевые"
            )
    else:
        notes.append(
            "шкала СТП взята из книги: трассовые ставки недоступны, "
            "передай уведомление ключом --notice"
        )

    paths = {
        "stp_scale.csv": scale,
        "product_economics.csv": economics,
        "margin_forecast.csv": margin,
    }
    for name, rows in paths.items():
        _write_csv(out_dir / name, rows, SCALE_FIELDS if name == "stp_scale.csv" else None)

    return ExtractResult(
        scale_rows=len(scale),
        economics_rows=len(economics),
        margin_rows=len(margin),
        months=sorted({str(r["месяц"]) for r in margin}),
        regions=sorted({str(r["регион"]) for r in margin}),
        files=[out_dir / name for name in paths],
        notes=notes,
    )
