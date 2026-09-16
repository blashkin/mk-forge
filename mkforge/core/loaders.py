"""Загрузка обезличенных csv в модели и проверка согласованности.

Разделение намеренное: `load_inputs` падает на испорченной форме данных,
`check` возвращает отчет о несогласованности, которую человек должен увидеть,
но которая не обязательно делает расчет невозможным.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from mkforge.core.models import (
    BranchRegion,
    Contract,
    Inputs,
    MarginForecast,
    ModelError,
    ProductEconomics,
    StpBracket,
    StpScale,
    Transaction,
)

TRANSACTIONS_FILE = "transactions.csv"
CONTRACTS_FILE = "contracts.csv"
SCALE_FILE = "stp_scale.csv"
ECONOMICS_FILE = "product_economics.csv"
MARGIN_FILE = "margin_forecast.csv"
BRANCHES_FILE = "branch_regions.csv"
# Все, без чего расчет не идет. Таблицу отделений prepare не создает, но и без нее не посчитать.
INPUT_FILES = (
    TRANSACTIONS_FILE, CONTRACTS_FILE, SCALE_FILE, ECONOMICS_FILE, MARGIN_FILE, BRANCHES_FILE,
)

# Метка показателя в таблице экономики -> поле модели.
ECONOMICS_FIELDS = {
    "Скидка/СТП без акции, %": "stp_without_campaign",
    "Выручка брутто, руб/т": "gross_revenue",
    "Себестоимость, руб/т": "cost",
    "OPEX, руб/т": "opex",
    "Маржа базовая, руб/т": "base_margin",
    "Средняя ставка сервисного сбора, %": "service_fee_rate",
    "Маржа СТиУ, %": "stiu_margin",
}

# Колонка таблицы экономики -> вид продукта. «нп» это агрегат по топливу.
ECONOMICS_COLUMNS = {"аб": "АБ", "дт": "ДТ", "суг": "СУГ", "нп": "НП"}


@dataclass
class LoadReport:
    """Несогласованность входных данных: что человеку надо знать перед расчетом."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def report(self) -> str:
        if not self.errors and not self.warnings:
            return "входные данные согласованы"
        lines = [f"ошибка: {e}" for e in self.errors]
        lines += [f"внимание: {w}" for w in self.warnings]
        return "\n".join(lines)


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ModelError(f"нет файла {path}; собери входные данные командой mk-forge prepare")
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _build(model, rows: list[dict], path: Path) -> tuple:
    """Разобрать строки в модели, назвав номер строки при ошибке."""
    built = []
    for number, row in enumerate(rows, start=2):  # 1 — шапка
        clean = {k: (v if v != "" else None) for k, v in row.items()}
        try:
            built.append(model(**clean))
        except ValidationError as error:
            first = error.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "строка"
            raise ModelError(f"{path.name}, строка {number}, «{where}»: {first['msg']}") from None
    if not built:
        raise ModelError(f"{path.name} пустой")
    return tuple(built)


def _economics(rows: list[dict], path: Path) -> dict[str, ProductEconomics]:
    """Свести таблицу «показатель x продукт» в модель на каждый вид продукта."""
    by_product: dict[str, dict[str, float]] = {p: {} for p in ECONOMICS_COLUMNS.values()}
    seen: set[str] = set()
    for row in rows:
        label = (row.get("показатель") or "").strip()
        field_name = ECONOMICS_FIELDS.get(label)
        if field_name is None:
            continue  # незнакомый показатель — не наше дело
        seen.add(label)
        for column, product in ECONOMICS_COLUMNS.items():
            value = row.get(column)
            by_product[product][field_name] = float(value) if value not in (None, "") else 0.0

    missing = set(ECONOMICS_FIELDS) - seen
    if missing:
        raise ModelError(f"{path.name}: не хватает показателей {sorted(missing)}")

    return {
        product: ProductEconomics(product=product, **values)
        for product, values in by_product.items()
    }


def _branch_regions(path: Path) -> dict[str, str]:
    """Таблица «отделение -> регион прогноза маржи».

    Транзакции размечены отделениями, прогноз маржи — регионами, и связи между ними
    в выгрузке нет: в эталонной книге она жила внутри одной формулы. Поэтому таблицу
    ведут руками и кладут рядом с обезличенными данными; `prepare` ее не создает
    и не трогает. В git ее нет: это оргструктура, а не код.

    Регион прогноза, на который не ссылается ни одно отделение, в расчет не попадает.
    """
    if not path.exists():
        raise ModelError(
            f"нет файла {path}: таблицу отделений и регионов прогноза маржи ведут руками, "
            f"prepare ее не создает; колонки «отделение» и «регион»"
        )
    table: dict[str, str] = {}
    for row in _build(BranchRegion, _rows(path), path):
        if row.branch in table:
            raise ModelError(f"{path.name}: отделение «{row.branch}» записано дважды")
        table[row.branch] = row.region
    return table


def load_inputs(directory: Path) -> Inputs:
    """Прочитать обезличенные csv из каталога в типизированные модели."""
    transactions = _build(Transaction, _rows(directory / TRANSACTIONS_FILE), directory / TRANSACTIONS_FILE)
    contracts = _build(Contract, _rows(directory / CONTRACTS_FILE), directory / CONTRACTS_FILE)
    brackets = _build(StpBracket, _rows(directory / SCALE_FILE), directory / SCALE_FILE)
    margin = _build(MarginForecast, _rows(directory / MARGIN_FILE), directory / MARGIN_FILE)
    economics = _economics(_rows(directory / ECONOMICS_FILE), directory / ECONOMICS_FILE)
    branch_regions = _branch_regions(directory / BRANCHES_FILE)

    return Inputs(
        transactions=transactions,
        contracts=contracts,
        scale=StpScale(brackets=brackets),
        economics=economics,
        margin=margin,
        branch_regions=branch_regions,
    )


def check(inputs: Inputs) -> LoadReport:
    """Сверить файлы между собой. Ловит то, что эталонная книга пропускала молча."""
    report = LoadReport()

    in_pool = {c.contract for c in inputs.contracts}
    in_transactions = {t.contract for t in inputs.transactions}

    orphans = in_transactions - in_pool
    if orphans:
        report.errors.append(
            f"{len(orphans)} договоров есть в транзакциях, но нет в пуле акции"
        )
    silent = in_pool - in_transactions
    if silent:
        report.warnings.append(
            f"{len(silent)} договоров пула без транзакций — они попадут в расчет с нулевым объемом"
        )

    unclassified = sum(1 for t in inputs.transactions if not t.is_classified)
    if unclassified:
        report.warnings.append(
            f"{unclassified} транзакций без вида или класса продукта — "
            f"они не попадут ни в один итог, как и в эталонной книге"
        )

    empty_branch = sum(1 for t in inputs.transactions if not t.branch)
    if empty_branch:
        report.warnings.append(
            f"{empty_branch} транзакций без отделения — их маржа не будет отнесена к региону"
        )
    branches = inputs.branch_regions
    unknown = {t.branch for t in inputs.transactions if t.branch} - set(branches)
    if unknown:
        report.errors.append(
            f"отделения без региона маржи: {sorted(unknown)}; дополни {BRANCHES_FILE}"
        )

    regions_with_margin = {m.region for m in inputs.margin}
    needed = {branches[b] for b in {t.branch for t in inputs.transactions if t.branch} & set(branches)}
    without_forecast = needed - regions_with_margin
    if without_forecast:
        report.errors.append(
            f"нет прогноза маржи для регионов: {sorted(without_forecast)}"
        )

    products = {t.product for t in inputs.transactions if t.is_fuel}
    no_economics = products - set(inputs.economics)
    if no_economics:
        report.errors.append(f"нет экономики для видов продукта: {sorted(no_economics)}")

    return report
