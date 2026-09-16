"""Лист «Витрина акции»: то, что читает экономист.

Раздел 1 с параметрами повторяет адреса эталонной книги: на его ячейки ссылается
лист расчета, а B10, B11, B19-B21 и B24 — это то, что человек вправе менять руками.

Раздел 2 с итогами разложен по-своему: полной раскладки этого блока в эталоне
восстановить не удалось. Три подписи, которые известны точно — все затраты,
окупаемость и ROI — стоят на своих строках.

Раздел 5 печатает допущения расчета. Экономист должен видеть, на чем стоят числа,
не читая формулы: это то, из-за чего к прошлой книге нельзя было задать вопрос.
"""

from __future__ import annotations

from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from mkforge.config import CampaignConfig
from mkforge.renderers import calculation as calc
from mkforge.renderers import parameters as params
from mkforge.renderers.grid import headers, put, section, widths

SHEET = "Витрина акции"

PRODUCT = 6
START = 10
END = 11
TERM = 12
SHARE_WITHOUT = 19
SHARE_WITH = 20
COMMS = 21
SELECTED_LEVEL = 24

RESULTS_SECTION_ROW = 25
RESULTS_HEADER_ROW = 26
RULES_SECTION_ROW = 40
RULES_HEADER_ROW = 41
LEVELS_SECTION_ROW = 50
LEVELS_HEADER_ROW = 51
LEVELS_FIRST_ROW = 52

# Раздел 2: подпись -> (строка, колонка «без акции», колонка «с акцией», формат).
# Колонки — из раздела 5 листа расчета.
RESULTS = (
    ("Участники, ед.", 27, "O", "P", "mk_count"),
    ("Объем продукта, т", 28, "Q", "R", "mk_tons"),
    ("Выручка брутто, руб.", 29, "S", "T", "mk_money"),
    ("Все затраты, руб.", 30, "AK", "AL", "mk_money"),
    ("в том числе скидка, руб.", 31, "U", "V", "mk_money"),
    ("в том числе OPEX, руб.", 32, "W", "X", "mk_money"),
    ("в том числе коммуникация, руб.", 33, "Y", "Z", "mk_money"),
    ("Сервисный сбор, руб.", 34, "AA", "AB", "mk_money"),
    ("Маржа валовая, руб.", 35, "AE", "AF", "mk_money"),
    ("Маржа нетто, руб.", 36, "AI", "AJ", "mk_money"),
    ("Окупаемость затрат, руб./руб.", 37, "AM", "AN", "mk_ratio"),
    ("ROI на учтенные затраты, руб./руб.", 38, "AO", "AP", "mk_ratio"),
)

# Раздел 4: колонка витрины -> (подпись, колонка раздела 5, формат).
LEVEL_SUMMARY = {
    "B": ("Эффективная скидка, %", "AQ", "mk_pct"),
    "C": ("Надбавка к СТП (номинал), %", "B", "mk_pct_fine"),
    "D": ("Итоговая скидка продукта, средняя, %", "AS", "mk_pct"),
    "E": ("Все затраты, руб.", "G", "mk_money"),
    "F": ("Маржинальный доход общий, руб.", "L", "mk_money"),
    "G": ("Окупаемость, руб./руб.", "M", "mk_ratio"),
    "H": ("ROI, руб./руб.", "N", "mk_ratio"),
}


def _selected(column: str, levels_last: int) -> str:
    """Значение выбранного уровня из колонки раздела 5 листа расчета."""
    first = calc.LEVELS_FIRST_ROW
    return (
        f"=IFERROR(INDEX('{calc.SHEET}'!${column}${first}:${column}${levels_last},"
        f"MATCH($B${SELECTED_LEVEL},'{calc.SHEET}'!$AQ${first}:$AQ${levels_last},0)),0)"
    )


def write(ws: Worksheet, config: CampaignConfig, levels_last: int) -> None:
    """Выложить витрину."""
    widths(ws, {"A": 44, "B": 22, "C": 22, "D": 26, "E": 20, "F": 24, "G": 18, "H": 16})
    _write_parameters(ws, config)
    if config.distribution is not None:
        _write_distribution_summary(ws, config)
    _write_results(ws, levels_last)
    _write_rules(ws, config)
    _write_levels(ws, config, levels_last)
    _write_assumptions(ws, config, levels_last)


def _write_parameters(ws: Worksheet, config: CampaignConfig) -> None:
    section(ws, 1, "1. Параметры акции", 3)
    headers(ws, 2, {"A": "Показатель", "B": "Значение", "C": "Пояснение"})

    rows = {
        3: ("Тип акции", config.mechanic, "mk_text"),
        4: ("География", "", "mk_text"),
        5: ("Название МК", config.name, "mk_text"),
        PRODUCT: ("Вид продукта в расчете", config.product, "mk_text"),
        7: ("Механика расчета", config.mechanic, "mk_text"),
        8: ("Цель акции", "", "mk_text"),
        13: ("Тип скидки", f"+ к СТП на {config.product}", "mk_text"),
    }
    for row, (label, value, style) in rows.items():
        put(ws, f"A{row}", label, "mk_label")
        put(ws, f"B{row}", value, style)

    put(ws, "A9", "Условия, уровни и обоснование", "mk_label")
    put(ws, "B9", _conditions(config), "mk_text")
    ws.row_dimensions[9].height = 90

    put(ws, f"A{START}", "Начало действия скидок", "mk_label")
    put(ws, f"B{START}", config.start, "mk_input_date")
    put(ws, f"A{END}", "Окончание действия скидок", "mk_label")
    put(ws, f"B{END}", config.end, "mk_input_date")
    put(ws, f"C{END}", "Даты задают календарь акции на листе параметров", "mk_note")

    put(ws, f"A{TERM}", "Срок для текущего пула, мес.", "mk_label")
    put(ws, f"B{TERM}",
        f"=SUM('{params.SHEET}'!$C${params.CALENDAR_FIRST_ROW}"
        f":$C${params.CALENDAR_LAST_ROW})", "mk_ratio")

    derived = {
        14: ("Скидка без акции / СТП, %", "B5", "mk_pct"),
        15: ("Средняя доп. скидка, %", "B6", "mk_pct_fine"),
        16: ("Средняя итоговая скидка, %", "B7", "mk_pct"),
        17: ("Средняя ставка сервисного сбора, %", "B8", "mk_pct_fine"),
        18: ("Эффективная скидка клиента, %", "B9", "mk_pct"),
        22: ("Новые клиенты, прогноз, ед.", f"B{calc.NEW_COUNT}", "mk_count"),
        23: ("Доп. скидка новым, %", f"B{calc.MARKUP_NEW}", "mk_pct_fine"),
    }
    for row, (label, source, style) in derived.items():
        put(ws, f"A{row}", label, "mk_label")
        put(ws, f"B{row}", f"='{calc.SHEET}'!${source[0]}${source[1:]}", style)

    put(ws, f"A{SHARE_WITHOUT}", "Доля пула без акции, допущение", "mk_label")
    put(ws, f"B{SHARE_WITHOUT}", config.share_without, "mk_input")
    put(ws, f"A{SHARE_WITH}", "Доля пула с акцией", "mk_label")
    put(ws, f"B{SHARE_WITH}", config.share_with, "mk_input")
    put(ws, f"A{COMMS}", "Затраты коммуникации на клиента, руб.", "mk_label")
    put(ws, f"B{COMMS}", config.comms_per_client, "mk_input_count")

    put(ws, f"A{SELECTED_LEVEL}", "Выбранный уровень эффективной скидки, %", "mk_label")
    put(ws, f"B{SELECTED_LEVEL}", config.showcase_level, "mk_input")
    low, high = min(config.targets), max(config.targets)
    allowed = ", ".join(f"{target * 100:g}%" for target in config.targets)
    put(ws, f"C{SELECTED_LEVEL}", f"Ввод: {allowed}. Управляет надбавкой во всем расчете", "mk_note")

    validation = DataValidation(
        type="decimal", operator="between", formula1=str(low), formula2=str(high),
        allow_blank=False, errorTitle="Уровень",
        error=f"Эффективная скидка из набора: {allowed}",
    )
    validation.add(f"B{SELECTED_LEVEL}")
    ws.add_data_validation(validation)


# Панель итога справа от параметров: колонки E..H, строки 2..13.
SUMMARY_COLUMN = 5  # E
SUMMARY_LABEL = "E"
SUMMARY_VALUE = "G"
SUMMARY_SECTION_ROW = 2
SUMMARY_FIRST_ROW = 3


def _write_distribution_summary(ws: Worksheet, config: CampaignConfig) -> None:
    """Итог акции с распределенной глубиной — сразу, а не в глубине расчета.

    Здесь же стоит порог доли объема без акции. Он важнее самого результата:
    результат зависит от допущения, а порог показывает, где допущение перестает
    держать акцию выше нуля.
    """
    from mkforge.renderers import distribution as dist

    count = len(config.distribution.shares)
    total = dist.total_row(count)
    breakeven = list(dist.breakeven_rows(count).values())

    section(ws, SUMMARY_SECTION_ROW, "Итог акции: скидку раздают менеджеры", 4,
            first_column=SUMMARY_COLUMN)

    lines = (
        ("Эффективная скидка акции, %", f"${dist.EFFECTIVE}${total}", "mk_pct"),
        ("Средняя надбавка к СТП, %", f"${dist.MARKUP}${total}", "mk_pct_fine"),
        ("Все затраты акции, руб.", f"${dist.EXTRA_COSTS}${total}", "mk_money"),
        ("Дополнительная маржа, руб.", f"${dist.EXTRA_MARGIN}${total}", "mk_money"),
        ("Окупаемость, руб./руб.", f"${dist.PAYBACK}${total}", "mk_ratio"),
        ("ROI, руб./руб.", f"${dist.ROI}${total}", "mk_ratio"),
        ("До какой доли без акции не уходим в минус", f"$B${breakeven[4]}", "mk_pct"),
        ("До какой доли без акции ROI выше 1", f"$B${breakeven[5]}", "mk_pct"),
    )
    for offset, (label, source, style) in enumerate(lines):
        row = SUMMARY_FIRST_ROW + offset
        put(ws, f"{SUMMARY_LABEL}{row}", label, "mk_label")
        put(ws, f"{SUMMARY_VALUE}{row}", f"='{calc.SHEET}'!{source}", style)

    note = SUMMARY_FIRST_ROW + len(lines)
    put(ws, f"{SUMMARY_LABEL}{note}",
        "Глубина скидки распределена: раздел 6 листа расчета. Эффективная скидка "
        "здесь результат, а не задание. Порог читается так: акция держится, пока "
        "доля объема без акции не выше этого значения; «недостижимо» означает, "
        "что планка не берется ни при какой доле.",
        "mk_note")
    ws.row_dimensions[note].height = 60


def _conditions(config: CampaignConfig) -> str:
    levels = ", ".join(f"{target * 100:g}%" for target in config.targets)
    if config.distribution is not None:
        shares = ", ".join(
            f"{share.depth * 100:g}% — {share.share * 100:g}% пула"
            for share in config.distribution.deepest_first().shares
        )
        handout = (
            "чем больше клиент везет, тем глубже его скидка"
            if config.distribution.by_volume
            else "скидка достается вне зависимости от размера клиента"
        )
        return (
            f"Скидку раздают менеджеры по договору. Глубина задана распределением: "
            f"{shares}. Раздача: {handout}.\n"
            f"Номинал надбавки подобран каждому срезу отдельно: у крупного клиента "
            f"СТП ниже, поэтому на ту же эффективную скидку ему нужна надбавка выше. "
            f"Эффективная скидка акции — результат распределения, а не задание.\n"
            f"Прогноз новых участников идет от фактического темпа подключения "
            f"по датам договоров, лист «Прогнозный пул». Плана участников нет."
        )
    return (
        f"Уровень акции задан как эффективная скидка клиента с учетом сервисного сбора: "
        f"{levels}. Шкала СТП компенсирует сбор, поэтому базовая эффективная скидка "
        f"близка к нулю, а надбавка акции формирует заданный уровень.\n"
        f"Надбавка одна для всех сегментов объема и для новых участников. "
        f"Ее номинал подобран так, чтобы средневзвешенная эффективная скидка "
        f"равнялась выбранному уровню.\n"
        f"План участников: {config.plan_participants}. Новые подключаются равномерно "
        f"в течение акции и считаются с даты подключения."
    )


def _write_results(ws: Worksheet, levels_last: int) -> None:
    section(ws, RESULTS_SECTION_ROW, "2. Итоги расчета по выбранному уровню", 4)
    headers(ws, RESULTS_HEADER_ROW, {
        "A": "Показатель", "B": "Без акции", "C": "С акцией", "D": "Дополнительно",
    })
    for label, row, without, with_campaign, style in RESULTS:
        put(ws, f"A{row}", label, "mk_label")
        put(ws, f"B{row}", _selected(without, levels_last), style)
        put(ws, f"C{row}", _selected(with_campaign, levels_last), style)
        if style == "mk_ratio":
            source = "M" if "Окупаемость" in label else "N"
            put(ws, f"D{row}", _selected(source, levels_last), style)
        else:
            put(ws, f"D{row}", f"=C{row}-B{row}", style)


def _write_rules(ws: Worksheet, config: CampaignConfig) -> None:
    section(ws, RULES_SECTION_ROW, "3. Правила акции", 2)
    headers(ws, RULES_HEADER_ROW, {"A": "№", "B": "Правило"})
    for index, rule in enumerate(config.rules_text(), start=1):
        row = RULES_HEADER_ROW + index
        put(ws, f"A{row}", index, "mk_count")
        put(ws, f"B{row}", rule, "mk_text")
        ws.row_dimensions[row].height = 30


def _write_levels(ws: Worksheet, config: CampaignConfig, levels_last: int) -> None:
    title = (
        "4. Справочно: что было бы на одной глубине для всех. "
        "Сценарий акции — на листе «Итог акции»"
        if config.distribution is not None
        else "4. Свод по уровням эффективной скидки (расчет на листе «Расчет акции», раздел 5)"
    )
    section(ws, LEVELS_SECTION_ROW, title, 8)
    headers(ws, LEVELS_HEADER_ROW,
            {"A": "Уровень", **{column: label for column, (label, _, _) in LEVEL_SUMMARY.items()}})

    for index, target in enumerate(config.targets):
        row = LEVELS_FIRST_ROW + index
        source_row = calc.LEVELS_FIRST_ROW + index
        put(ws, f"A{row}", f"Уровень {target * 100:g}%", "mk_label")
        for column, (_, source_column, style) in LEVEL_SUMMARY.items():
            put(ws, f"{column}{row}",
                f"='{calc.SHEET}'!${source_column}${source_row}", style)

    if config.distribution is not None:
        # Тот же свод, что и на листе расчета, и та же беда: против каждой скидки
        # стоит весь пул. Сценарий акции лежит на первом листе, поэтому здесь
        # свод скрыт, а на его месте оставлена одна видимая строка.
        put(ws, f"A{LEVELS_SECTION_ROW - 1}",
            calc.scenario_note(config, "на первом листе «Итог акции»"), "mk_note")
        ws.row_dimensions[LEVELS_SECTION_ROW - 1].height = 32
        for row in range(LEVELS_SECTION_ROW, LEVELS_FIRST_ROW + len(config.targets) + 1):
            ws.row_dimensions[row].hidden = True

    note = LEVELS_FIRST_ROW + len(config.targets)
    tail = (
        " Это не сценарии акции: в акции пул получает разные скидки одновременно, "
        "и итог посчитан на первом листе."
        if config.distribution is not None
        else ""
    )
    put(ws, f"A{note}",
        "Затраты = скидка + OPEX + коммуникация. Окупаемость = (маржа + затраты) / затраты, "
        f"ROI = маржа / затраты.{tail}", "mk_note")


def _write_assumptions(ws: Worksheet, config: CampaignConfig, levels_last: int) -> None:
    """Раздел 5: допущения расчета.

    Печатаются, чтобы экономист видел, на чем стоят числа. В прошлой книге эти
    выборы жили в ячейках и восстанавливались только чтением формул.
    """
    start = LEVELS_FIRST_ROW + len(config.targets) + 2
    section(ws, start, "5. Допущения расчета", 3)
    headers(ws, start + 1, {"A": "Допущение", "B": "Выбрано", "C": "Почему и что дает"})
    for index, assumption in enumerate(config.assumptions, start=1):
        row = start + 1 + index
        put(ws, f"A{row}", assumption.name.replace("_", " "), "mk_label")
        put(ws, f"B{row}", assumption.value.replace("_", " "), "mk_text")
        tail = f" {assumption.gives}." if assumption.gives else ""
        alternative = (
            f" Альтернатива: {assumption.alternative.replace('_', ' ')}."
            if assumption.alternative else ""
        )
        put(ws, f"C{row}", f"{assumption.why.strip()}{tail}{alternative}", "mk_text")
        ws.row_dimensions[row].height = 46
