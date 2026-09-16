"""Сборка книги Excel.

Книга собирается с нуля, без шаблона: стили описаны кодом, поэтому сборка
работает и в CI, где никакого файла-образца нет.

Порядок листов и адреса ячеек повторяют эталонную книгу — так собранную книгу
можно сверить с эталоном механически.

В ячейки пишутся формулы, а не результаты. Пока книгу не пересчитает Excel
или LibreOffice, числа в ней отсутствуют. Это ожидаемо: за пересчет и проверку
отвечает отдельный шаг.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook

from mkforge.config import CampaignConfig
from mkforge.campaigns import motivational
from mkforge.core.models import Inputs
from mkforge.renderers import (
    calculation,
    dictionaries,
    forecast,
    summary,
    parameters,
    participants,
    showcase,
    styles,
    transactions,
)

# Порядок вкладок как в эталонной книге. Лист прогнозного пула встает после
# листа участников: он такой же пул, только не фактический.
SHEET_ORDER = (
    summary.SHEET,
    showcase.SHEET,
    calculation.SHEET,
    parameters.SHEET,
    participants.SHEET,
    forecast.SHEET,
    transactions.SHEET,
    dictionaries.REFERENCE_SHEET,
    dictionaries.CAMPAIGN_SHEET,
)


def sheet_order(with_forecast: bool) -> tuple[str, ...]:
    """Порядок листов.

    Без распределения глубины нет ни прогнозного пула, ни листа итога: итог
    читает раздел распределения, а его в такой книге не существует.
    """
    if with_forecast:
        return SHEET_ORDER
    return tuple(
        name for name in SHEET_ORDER if name not in (forecast.SHEET, summary.SHEET)
    )


@dataclass
class BuildResult:
    """Что собрано. Числа появятся только после пересчета."""

    path: Path
    product: str
    transaction_rows: int = 0
    contract_rows: int = 0
    forecast_rows: int = 0
    sheets: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            f"книга: {self.path}",
            f"продукт акции: {self.product}",
            f"транзакций: {self.transaction_rows}, договоров: {self.contract_rows}",
            f"собрано листов: {len(self.sheets)}",
        ]
        if self.forecast_rows:
            lines.append(f"прогнозных участников: {self.forecast_rows}")
        lines += [f"  готов: {name}" for name in self.sheets]
        lines += [f"  пустой: {name}" for name in self.pending]
        lines += [f"  {note}" for note in self.notes]
        lines.append("формулы записаны, значений нет — нужен пересчет")
        return "\n".join(lines)


def build(inputs: Inputs, config: CampaignConfig, path: Path) -> BuildResult:
    """Собрать книгу по входным данным и конфигу акции."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    styles.register(workbook)

    distribution = config.distribution
    depth_count = len(distribution.shares) if distribution is not None else 0
    pool_forecast = (
        motivational.forecast_pool_from(inputs, config) if distribution else None
    )
    order = sheet_order(pool_forecast is not None)
    sheets = {name: workbook.create_sheet(name) for name in order}

    tx_last = transactions.write(sheets[transactions.SHEET], inputs.transactions)
    scale_last = parameters.SCALE_FIRST_ROW + len(inputs.scale.brackets) - 1
    participants_last = participants.write(
        sheets[participants.SHEET],
        inputs.contracts,
        product=config.product,
        tx_last=tx_last,
        scale_last=scale_last,
        depth_count=depth_count,
    )
    forecast_last, forecast_size = 0, 0
    if pool_forecast is not None:
        forecast_size = pool_forecast.size
        forecast_last = forecast.write(
            sheets[forecast.SHEET],
            pool_forecast,
            scale_last=scale_last,
            depth_count=depth_count,
        )
    mix_total_row = parameters.write(
        sheets[parameters.SHEET],
        inputs,
        product=config.product,
        tx_last=tx_last,
        participants_last=participants_last,
        threshold_thousand_liters=config.large_threshold_thousand_liters,
        shift_points=config.large_shift_points,
        tilt_to_volume=config.tilt_to_volume,
    )
    levels_last = calculation.write(
        sheets[calculation.SHEET],
        config=config,
        participants_last=participants_last,
        mix_total_row=mix_total_row,
        pool_forecast_last=forecast_last,
        pool_forecast_size=forecast_size,
    )
    showcase.write(sheets[showcase.SHEET], config=config, levels_last=levels_last)
    if pool_forecast is not None:
        summary.write(sheets[summary.SHEET], config=config)
    dictionaries.write_reference(
        sheets[dictionaries.REFERENCE_SHEET], inputs, tx_last=tx_last, config=config
    )
    dictionaries.write_campaign(sheets[dictionaries.CAMPAIGN_SHEET], config=config)

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)

    return BuildResult(
        path=path,
        product=config.product,
        transaction_rows=len(inputs.transactions),
        contract_rows=len(inputs.contracts),
        forecast_rows=forecast_size,
        sheets=order,
        pending=(),
        notes=[
            "диапазоны формул посчитаны от фактического числа строк, "
            "дефект эталона не воспроизведен",
        ],
    )
