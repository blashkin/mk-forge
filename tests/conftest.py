"""Синтетический пул для тестов. Реальные выгрузки в тестах не используются никогда."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import docx
import openpyxl
import pytest

PREFIXES = ["АА", "ББ", "ВВ", "ГГ"]
# Отделения условные. Каждому нужен регион в таблице отделений и прогноз маржи
# по этому региону, иначе синтетический пул сам себе противоречит.
BRANCH_REGIONS = {
    "Отделение А": "Регион маржи А",
    "Отделение Б": "Регион маржи Б",
    "Отделение В": "Регион маржи В",
}
BRANCHES = list(BRANCH_REGIONS)

# Шапка транзакций повторяет реальную: те же заголовки, часть с переносом строки,
# и лишние колонки, которых в расчете нет — они должны быть отброшены.
TX_HEADER = [
    "№ договора", "Сегмент", "Регион", "Группа продукта", "Количество",
    "Выручка со скидкой", "Сервисный сбор", "Месяц", "Вид продукта",
    "Класс продукта", "Коэф в тонны", "Объем т", "Ставка сервисного сбора",
    "Ключ месяц-договор", "Уник договор месяц", "Отделение ТО",
]
CONTRACTS_HEADER = [
    "№ договора", "Сегмент", "Дата подключения", "В пуле акции",
    "Комментарий / отделение", "Среднемес. объем НП, л\n(август 2026)",
]


def liters_for(i: int) -> float:
    """Объем i-го договора. Разброс такой, чтобы пул попадал во все сегменты шкалы."""
    return 10_000.0 * (i + 1)


def tons_for(i: int) -> float:
    return liters_for(i) * 0.845 / 1000


def fee_rate_for(i: int) -> float:
    """Ставка сервисного сбора примерно повторяет СТП сегмента.

    Так устроена предметка: шкала СТП компенсирует сбор, поэтому базовая
    эффективная скидка близка к нулю во всех сегментах. Постоянная ставка
    сделала бы синтетику непохожей на реальность — например, у крупных
    клиентов сбор обязан быть ниже.
    """
    thousands = liters_for(i) / 1000
    if thousands < 50:
        return 0.035
    if thousands < 120:
        return 0.025
    return 0.01


STIU_REVENUE = 5_000.0


def contract_number(i: int) -> str:
    return f"{PREFIXES[i % len(PREFIXES)]}{100000000 + i:09d}"


@pytest.fixture
def pool() -> list[str]:
    return [contract_number(i) for i in range(20)]


@pytest.fixture
def export(tmp_path: Path, pool: list[str]) -> Path:
    """Книга на 20 договоров: у каждого две строки — ДТ и СТиУ."""
    wb = openpyxl.Workbook()
    tx = wb.active
    tx.title = "Транзакции участников"
    tx.append(TX_HEADER)
    for i, contract in enumerate(pool):
        branch = BRANCHES[i % len(BRANCHES)]
        liters = liters_for(i)
        tons = tons_for(i)
        revenue = liters * 55.0
        fee_rate = fee_rate_for(i)
        tx.append([
            contract, "CRT", f"Регион {i % 7}", "Дизель", liters,
            revenue, -revenue * fee_rate, dt.datetime(2026, 8, 1), "ДТ",
            "НП", 0.845, tons, fee_rate, f"{contract}-авг", 1, branch,
        ])
        tx.append([
            contract, "CRT", f"Регион {i % 7}", "Услуги", 0.0,
            STIU_REVENUE, -100.0, dt.datetime(2026, 8, 1), "СТиУ",
            "СТиУ", 0.0, 0.0, 0.02, f"{contract}-авг-у", 0, branch,
        ])
    tx.append([None] * len(TX_HEADER))  # хвост форматирования

    contracts = wb.create_sheet("База участников")
    contracts.append(CONTRACTS_HEADER)
    for i, contract in enumerate(pool):
        contracts.append([contract, "CRT", dt.datetime(2020, 1, 1 + i % 28), True, None, None])
    contracts.append([None] * len(CONTRACTS_HEADER))

    _add_parameters_sheet(wb)

    path = tmp_path / "синтетическая_выгрузка.xlsx"
    wb.save(path)
    return path


def _add_parameters_sheet(wb) -> None:
    """Лист параметров с теми же адресами, что в реальной книге.

    Шкала с третьей строки, экономика с шапкой в 24-й, прогноз маржи в колонках L:O.
    После шкалы намеренно стоят служебные строки «Более 0» и «Средняя скидка» —
    извлечение должно остановиться до них.
    """
    ws = wb.create_sheet("База для расчета")

    ws["A1"] = "1. СТП: шкала и расчет"
    ws["A2"], ws["B2"], ws["C2"], ws["D2"] = "Объем выборки", "АБ", "ДТ", "СУГ"
    ws["E2"], ws["F2"] = "Мин", "Макс"
    for i, (label, low, high, dt_pct) in enumerate(
        [("0 - 50", 0, 50, 3.5), ("50 - 120", 50, 120, 2.5), ("более 120", 120, 999999, 1.0)]
    ):
        row = 3 + i
        ws[f"A{row}"], ws[f"B{row}"], ws[f"C{row}"], ws[f"D{row}"] = label, 0, dt_pct, 0
        ws[f"E{row}"], ws[f"F{row}"] = low, high
    ws["A6"], ws["E6"], ws["F6"], ws["C6"] = "Более 0", 0, 999999, 0        # служебная
    ws["A7"], ws["E7"], ws["F7"], ws["C7"] = "Средняя скидка", 0, 999999, 2.0  # служебная

    ws["A24"] = "Показатель"
    ws["B24"], ws["C24"], ws["D24"], ws["E24"] = "АБ", "ДТ", "СУГ", "НП"
    economics = [
        ("Скидка/СТП без акции, %", 0, 0.02, 0, 0.019),
        ("Выручка брутто, руб/т", 70000, 75000, 0, 74800),
        ("Себестоимость, руб/т", 56000, 57000, 0, 56900),
        ("OPEX, руб/т", 1600, 1550, 0, 1540),
        ("Маржа базовая, руб/т", 5000, 8000, 0, 7900),
        ("Средняя ставка сервисного сбора, %", 0.022, 0.021, 0, 0.021),
        ("Маржа СТиУ, %", 0.3, 0.3, 0.3, 0.3),
    ]
    for i, (label, ab, dt_, lpg, np_) in enumerate(economics):
        row = 25 + i
        ws[f"A{row}"] = label
        ws[f"B{row}"], ws[f"C{row}"], ws[f"D{row}"], ws[f"E{row}"] = ab, dt_, lpg, np_

    ws["L2"], ws["M2"], ws["N2"], ws["O2"] = "Месяц", "Вид продукта", "Маржа, руб/т", "Регион"
    for i, (month, product, value, region) in enumerate(margin_forecast()):
        row = 3 + i
        ws[f"L{row}"], ws[f"M{row}"], ws[f"N{row}"], ws[f"O{row}"] = month, product, value, region


# Месяцы периода акции и регионы, на которые ссылаются отделения пула.
CAMPAIGN_MONTHS = ("сен", "окт")
MARGIN_REGIONS = tuple(BRANCH_REGIONS.values())
OTHER_MONTHS = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "ноя", "дек")


def margin_forecast() -> list[tuple[str, str, int, str]]:
    """Прогноз маржи для синтетической выгрузки.

    Строк заметно больше, чем месяцев акции, и это нарочно: на листе параметров
    блоки стоят рядом по вертикали, и короткий прогноз не дал бы им наложиться
    друг на друга. Месяцы вне периода акции на расчет не влияют — календарь
    берет только свои, — зато делают наложение блоков видимым для теста.
    """
    rows = [
        ("сен", "ДТ", 14000, "Регион маржи А"),
        ("сен", "ДТ", 13000, "Регион маржи Б"),
        ("сен", "ДТ", 12000, "Регион маржи В"),
        ("окт", "ДТ", 5200, "Регион маржи А"),
        ("окт", "ДТ", 5000, "Регион маржи Б"),
        ("окт", "ДТ", 4800, "Регион маржи В"),
        ("сен", "АБ", 11000, "Регион маржи А"),
    ]
    for month in OTHER_MONTHS:
        for product, value in (("ДТ", 9000), ("АБ", 8000), ("СУГ", 4000)):
            for region in MARGIN_REGIONS:
                rows.append((month, product, value, region))
    return rows


@pytest.fixture(autouse=True)
def key_from_env(monkeypatch) -> str:
    """Тесты не создают .env и не трогают ключ пользователя."""
    key = "00" * 32
    monkeypatch.setenv("MK_FORGE_HMAC_KEY", key)
    return key


@pytest.fixture(autouse=True)
def home_in_tmp(monkeypatch, tmp_path_factory) -> Path:
    """Корень данных тестов — временная папка: настоящие data/, out/ и .env не трогаются."""
    home = tmp_path_factory.mktemp("корень")
    monkeypatch.setenv("MK_FORGE_HOME", str(home))
    return home


@pytest.fixture
def anon_dir(export: Path, tmp_path: Path) -> Path:
    """Обезличенные csv из синтетической книги — вход для загрузчика."""
    from mkforge.core.anonymize import anonymize
    from mkforge.core.extract import extract

    out = tmp_path / "anon"
    anonymize(
        source=export,
        out_dir=out,
        mapping_path=tmp_path / "mapping.json",
        root=tmp_path,
    )
    extract(source=export, out_dir=out)
    write_branch_regions(out)
    return out


def write_branch_regions(directory: Path) -> Path:
    """Таблица отделений: ее ведут руками, prepare ее не создает."""
    path = directory / "branch_regions.csv"
    lines = ["отделение,регион"] + [f"{b},{r}" for b, r in BRANCH_REGIONS.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def reference_book(export: Path, anon_dir: Path, tmp_path: Path) -> Path:
    """Синтетический «эталон»: книга с колонками, которые считает ядро.

    Нужна, чтобы проверять сам механизм сверки — перевод псевдонимов, поиск
    расхождений, пропущенные договоры. Значения кладем те же, что дает ядро:
    проверяем проводку, а не арифметику, ее проверяют тесты пула.
    """
    from mkforge.core.loaders import load_inputs
    from mkforge.core.pool import build_pool

    pool = build_pool(load_inputs(anon_dir), "ДТ")
    by_contract = {m.contract: m for m in pool.members}

    mapping = json.loads((tmp_path / "mapping.json").read_text(encoding="utf-8"))
    to_pseudonym = {real: code for code, real in mapping.items()}

    wb = openpyxl.load_workbook(export)
    ws = wb["База участников"]
    ws["P2"] = pool.period_months
    for row in range(2, ws.max_row + 1):
        real = ws[f"A{row}"].value
        if real in (None, ""):
            continue
        member = by_contract[to_pseudonym[str(real).strip()]]
        ws[f"I{row}"] = member.fuel_liters_per_month
        ws[f"K{row}"] = member.stp_rate
        ws[f"O{row}"] = member.product_tons_per_month
        ws[f"R{row}"] = member.service_fee_rate

    path = tmp_path / "эталон.xlsx"
    wb.save(path)
    return path


MINIMAL_CONFIG = """
кампания:
  название: Тестовая акция
  механика: надбавка_к_стп
  продукт: ДТ
  начало: 2026-09-10
  окончание: 2026-10-31
параметры:
  план_участников: 30
  уровни_эффективной_скидки: [0.01, 0.03, 0.05]
  уровень_на_витрине: 0.01
  затраты_коммуникации_на_клиента: 0
допущения:
  структура_новых:
    значение: как_у_текущего_пула
    почему: кого подключат, неизвестно
  подключение_новых:
    значение: равномерно_по_дням
    почему: причин ожидать всплеск нет
  что_считать_эффектом:
    значение: весь_прогнозный_объем
    доля_пула_без_акции: 0
    доля_пула_с_акцией: 1
    почему: как в исходной модели
  маржа_новых:
    значение: взвешенная_по_календарю
    почему: следствие равномерного подключения
ограничения:
  сервисный_сбор_максимум: 0.035
  продукты_вне_акции: [АБ, СУГ]
правила:
  - Надбавка +{уровень}% к СТП на ДТ. Период {начало} - {окончание}.
  - Новые подключаются до {окончание}.
"""


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "акция.yaml"
    path.write_text(MINIMAL_CONFIG, encoding="utf-8")
    return path

# Тот же конфиг, но с распределением глубины скидки: основная масса на 4-5%.
DISTRIBUTED_CONFIG = MINIMAL_CONFIG.replace(
    "  затраты_коммуникации_на_клиента: 0\n",
    """  затраты_коммуникации_на_клиента: 0
  распределение_глубины:
    - глубина: 0.05
      доля: 0.35
    - глубина: 0.04
      доля: 0.35
    - глубина: 0.03
      доля: 0.15
    - глубина: 0.02
      доля: 0.10
    - глубина: 0.01
      доля: 0.05
""",
).replace(
    "допущения:\n",
    """допущения:
  раздача_скидки:
    значение: по_объему
    почему: глубокая скидка достается тем, кто больше везет
""",
).replace(
    """  структура_новых:
    значение: как_у_текущего_пула
    почему: кого подключат, неизвестно""",
    """  структура_новых:
    значение: смещен_к_объему
    смещение_к_объему: 0.5
    почему: новых приводят менеджеры, и приводить будут тех, за кем объем""",
).replace(
    """  подключение_новых:
    значение: равномерно_по_дням
    почему: причин ожидать всплеск нет""",
    """  подключение_новых:
    значение: фактический_темп
    множитель: 1.0
    окно_месяцев: 12
    почему: плана нет, темп виден по датам подключения договоров""",
).replace(
    "    доля_пула_без_акции: 0\n",
    "    доля_пула_без_акции: 0.3\n",
)


@pytest.fixture
def pool_object(anon_dir: Path):
    """Собранный пул: нужен тестам распределения и механики."""
    from mkforge.core.loaders import load_inputs
    from mkforge.core.pool import build_pool

    return build_pool(load_inputs(anon_dir), "ДТ")


@pytest.fixture
def distributed_config_path(tmp_path: Path) -> Path:
    """Конфиг с распределенной глубиной: скидку раздают по одному."""
    path = tmp_path / "акция-распределение.yaml"
    path.write_text(DISTRIBUTED_CONFIG, encoding="utf-8")
    return path


def notice_document(path: Path, *, highway: bool = True, rows=None) -> Path:
    """Синтетическое уведомление: таблица-пустышка и таблица шкалы, как в настоящем."""
    document = docx.Document()

    decoy = document.add_table(rows=2, cols=2)
    decoy.rows[0].cells[0].text = "Руководителю"

    products = ["АБ", "СУГ", "ДТ"] + (["ДТ на трассовых и автоматических АЗС"] if highway else [])
    table = document.add_table(rows=2, cols=2 + len(products))
    table.rows[0].cells[0].text = "Торговая Точка"
    table.rows[0].cells[1].text = "Объем выборки НП (АБ, СУГ, ДТ) клиента"
    table.rows[1].cells[0].text = "Торговая Точка"
    table.rows[1].cells[1].text = "Объем выборки НП"
    for offset, product in enumerate(products):
        table.rows[1].cells[2 + offset].text = product

    for bounds, rates in rows or [("0 – 5**", ("0,00", "0,00", "-3,50", "-4,50")),
                                   ("5 - 10", ("0,00", "0,00", "-3,50", "-4,50")),
                                   ("более 10", ("0,00", "0,00", "-1,00", "-2,00"))]:
        row = table.add_row()
        row.cells[0].text = "АЗС, РФ"
        row.cells[1].text = bounds
        for offset in range(len(products)):
            row.cells[2 + offset].text = rates[offset]

    document.save(str(path))
    return path
