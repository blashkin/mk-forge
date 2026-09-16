"""Лист «Расчет акции»: показатели акции и таблица уровней глубины скидки.

Адреса как в эталонной книге: раздел 1 с расчетными показателями сверху,
раздел 4 с параметрами двух групп участников, раздел 5 с уровнями по строкам
77-81. По этим адресам идет сверка с эталоном.

Два отличия от эталона.

Показатели раздела 1 берутся из выбранного уровня раздела 5 через INDEX и MATCH,
а не из отдельного блока помесячного свода. Числа те же, ячеек меньше.

Прогноз новых участников считается как `MAX(0, план - пул)`. В эталоне стояло
простое вычитание, и план ниже текущего пула дал бы отрицательное число новых.
"""

from __future__ import annotations

from dataclasses import dataclass

from openpyxl.worksheet.worksheet import Worksheet

from mkforge.config import CampaignConfig
from mkforge.renderers import forecast as fc
from mkforge.renderers import parameters as params
from mkforge.renderers import participants as pool
from mkforge.renderers.grid import column_range, headers, put, section, widths

SHEET = "Расчет акции"
SHOWCASE = "Витрина акции"

# Раздел 5: уровни глубины скидки.
LEVELS_SECTION_ROW = 75
LEVELS_HEADER_ROW = 76
LEVELS_FIRST_ROW = 77
LEVELS_NOTE_ROW_OFFSET = 1

# Раздел 4: параметры двух групп участников.
GROUPS_SECTION_ROW = 64
GROUPS_HEADER_ROW = 65
NEW_COUNT = 66
MARKUP_CURRENT = 67
MARKUP_NEW = 68
NEW_TONS = 69
NEW_TERM = 70
NEW_STP = 71
NEW_FEE = 72
NEW_MARGIN = 73

# Доля новых в сценарии без акции. Отдельная от доли текущих: это разные утверждения.
NEW_SHARE_WITHOUT = 15

# Раздел 1: расчетные показатели. Метка -> строка.
INDICATORS = {
    "Вид продукта акции": 3,
    "Срок действия скидки на клиента, мес.": 4,
    "Скидка без акции / СТП, %": 5,
    "Доп./номинальная скидка по акции, %": 6,
    "Итоговая скидка в акции, %": 7,
    "Средняя ставка сервисного сбора, %": 8,
    "Эффективная скидка клиента с учетом сервисного сбора, %": 9,
    "Выручка брутто, руб/т": 10,
    "OPEX, руб/т": 11,
    "Маржа средняя с учетом региона, руб/т": 12,
    "Объем продукта на договор текущего пула, т/мес.": 13,
    "Уникальные договоры с продуктом за период, ед.": 14,
    "Коэф. эффекта новых без акции, %": 15,
    "Пул акции, уникальные договоры, ед.": 18,
    "Коэф. эффекта без акции, %": 19,
    "Коэф. эффекта с акцией, %": 20,
    "Затраты коммуникации на клиента, руб.": 21,
}

LEVEL_HEADERS = {
    "A": "Уровень",
    "B": "Надбавка к СТП (номинал), %",
    "C": "Участники, факт / прогноз",
    "D": "Клиентомесяцы без акции",
    "E": "Клиентомесяцы с акцией",
    "F": "Объем доп. эффекта, т",
    "G": "Все затраты, руб.",
    "H": "Сервисный сбор доп., руб.",
    "I": "Маржа с затратами, руб.",
    "J": "Маржа продукта доп., руб.",
    "K": "Маржа СТиУ доп., руб.",
    "L": "Маржа общая доп., руб.",
    "M": "Окупаемость, руб./руб.",
    "N": "ROI, руб./руб.",
    "O": "Клиенты без",
    "P": "Клиенты с",
    "Q": "Объем без",
    "R": "Объем с",
    "S": "Выручка без",
    "T": "Выручка с",
    "U": "Скидка без",
    "V": "Скидка с",
    "W": "OPEX без",
    "X": "OPEX с",
    "Y": "Комм без",
    "Z": "Комм с",
    "AA": "Сервис без",
    "AB": "Сервис с",
    "AC": "СТиУ без",
    "AD": "СТиУ с",
    "AE": "Маржа вал без",
    "AF": "Маржа вал с",
    "AG": "Маржа продукт нетто без",
    "AH": "Маржа продукт нетто с",
    "AI": "Маржа общая без",
    "AJ": "Маржа общая с",
    "AK": "Затраты без",
    "AL": "Затраты с",
    "AM": "Окупаемость без",
    "AN": "Окупаемость с",
    "AO": "ROMI без",
    "AP": "ROMI с",
    "AQ": "Целевая эффективная скидка, %",
    "AR": "Эффективная скидка факт, %",
    "AS": "Итоговая скидка продукта, средняя, %",
    "AT": "Скидка с акцией при надбавке 0, руб.",
    "AU": "Сбор с акцией при надбавке 0, руб.",
    "AV": "Снижение сбора на 1 п.п. надбавки, руб.",
}

MONEY_COLUMNS = ("G", "H", "I", "J", "K", "L", "S", "T", "U", "V", "W", "X", "Y", "Z",
                 "AA", "AB", "AC", "AD", "AE", "AF", "AG", "AH", "AI", "AJ", "AK", "AL",
                 "AT", "AU", "AV")
PERCENT_COLUMNS = ("AQ", "AR", "AS")
RATIO_COLUMNS = ("M", "N", "AM", "AN", "AO", "AP")
TONS_COLUMNS = ("F", "Q", "R")
COUNT_COLUMNS = ("C", "D", "E", "O", "P")


def levels_last_row(count: int) -> int:
    return LEVELS_FIRST_ROW + count - 1


def _selected(column: str, last: int) -> str:
    """Значение выбранного на витрине уровня из колонки раздела 5."""
    return (
        f"=IFERROR(INDEX(${column}${LEVELS_FIRST_ROW}:${column}${last},"
        f"MATCH('{SHOWCASE}'!$B$24,$AQ${LEVELS_FIRST_ROW}:$AQ${last},0)),0)"
    )


def write(
    ws: Worksheet,
    config: CampaignConfig,
    participants_last: int,
    mix_total_row: int,
    forecast_first: int = params.CALENDAR_FIRST_ROW,
    forecast_last: int = params.CALENDAR_LAST_ROW,
    pool_forecast_last: int = 0,
    pool_forecast_size: int = 0,
) -> int:
    """Выложить лист расчета. Возвращает последнюю строку таблицы уровней.

    `pool_forecast_*` — про лист прогнозного пула. Если он собран, объем и деньги
    новых участников берутся суммами по его строкам, а не произведением средних:
    произведение средних не равно среднему произведений, и у строк с разными
    сроками это давало бы расхождение.
    """
    widths(ws, {"A": 46, "B": 18, "C": 16})
    last = levels_last_row(len(config.targets))
    aggregates = _new_aggregates(pool_forecast_last, pool_forecast_size)

    _write_indicators(ws, config, participants_last, last)
    _write_groups(
        ws, config, participants_last, forecast_first, forecast_last, last,
        mix_total_row, pool_forecast_last, pool_forecast_size,
    )
    _write_levels(ws, config, participants_last, last, aggregates)
    if config.distribution is not None:
        from mkforge.renderers import distribution as dist

        dist.write(
            ws,
            config=config,
            participants_last=participants_last,
            forecast_last=pool_forecast_last,
            forecast_size=pool_forecast_size,
        )
        _hide_levels(ws, config, last)
    return last


def scenario_note(config: CampaignConfig, where: str) -> str:
    """Указание на сценарий акции вместо спрятанного свода по уровням.

    Числа берутся из конфига, а не из текста: свод прячется у любой акции с
    распределенной глубиной, и вписанный руками план разошелся бы со следующей.
    """
    depths = sorted(share.depth for share in config.distribution.shares)
    plan = (
        f"{config.plan_participants} участников расходятся"
        if config.plan_participants
        else "пул расходится"
    )
    return (
        f"Сценарий акции — {where}: {plan} по скидкам "
        f"от {depths[0] * 100:g}% до {depths[-1] * 100:g}%. "
        "Ниже скрыт справочный свод «одна глубина на весь пул»: "
        "в нем против каждой скидки стоит весь пул, сценарием акции он не является."
    )


def _hide_levels(ws: Worksheet, config: CampaignConfig, last: int) -> None:
    """Спрятать справочную таблицу уровней, когда глубина распределена.

    В каждой ее строке участвует весь пул: строка отвечает на вопрос «что было бы,
    если бы всю акцию провели на одной глубине». Для своей задачи это верно,
    но таблица лежит первой на пути и ее принимают за сценарий акции — против
    каждой скидки стоит весь план, хотя план должен по скидкам разойтись.
    Подписи «справочно» оказалось недостаточно, поэтому строки скрыты.

    Скрыты, а не удалены: раздел 1 считает по ним выбранный уровень, а раскрыть
    их можно в любой момент.
    """
    put(ws, f"A{LEVELS_SECTION_ROW - 1}",
        scenario_note(config, "раздел 6 ниже"), "mk_note")
    ws.row_dimensions[LEVELS_SECTION_ROW - 1].height = 32
    for row in range(LEVELS_SECTION_ROW, last + LEVELS_NOTE_ROW_OFFSET + 1):
        ws.row_dimensions[row].hidden = True


@dataclass(frozen=True)
class NewAggregates:
    """Как в формулах записаны величины новых участников.

    Пока прогноз был тремя числами, все складывалось из их произведений.
    С прогнозным пулом строками величины берутся суммами по колонкам листа —
    так формула повторяет то, что в строках и написано.
    """

    tons: str
    client_months: str
    discount: str
    fee_base: str
    fee: str


def _new_aggregates(forecast_last: int, forecast_size: int) -> NewAggregates:
    product = f"$B${NEW_COUNT}*$B${NEW_TERM}*$B${NEW_TONS}"
    if forecast_size <= 0:
        return NewAggregates(
            tons=product,
            client_months=f"$B${NEW_COUNT}*$B${NEW_TERM}",
            discount=f"{product}*$B${NEW_STP}",
            fee_base=f"{product}*(1-$B${NEW_STP})*$B${NEW_FEE}",
            fee=f"{product}*$B${NEW_FEE}",
        )
    return NewAggregates(
        tons=f"SUM({fc.range_of(fc.TON_MONTHS, forecast_last)})",
        client_months=f"SUM({fc.range_of(fc.TERM, forecast_last)})",
        discount=f"SUM({fc.range_of(fc.DISCOUNT_TON_MONTHS, forecast_last)})",
        fee_base=f"SUM({fc.range_of(fc.FEE_BASE_TON_MONTHS, forecast_last)})",
        fee=f"SUM({fc.range_of(fc.FEE_TON_MONTHS, forecast_last)})",
    )


def _write_indicators(
    ws: Worksheet, config: CampaignConfig, participants_last: int, last: int
) -> None:
    section(ws, 1, "1. Расчетные показатели", 3)
    headers(ws, 2, {"A": "Показатель", "B": "Значение", "C": "Пояснение"})
    for label, row in INDICATORS.items():
        put(ws, f"A{row}", label, "mk_label")

    product_column = next(
        column for column, name in params.ECONOMICS_PRODUCTS.items() if name == config.product
    )
    tons = column_range(pool.SHEET, pool.PRODUCT_TONS, participants_last)
    in_pool = column_range(pool.SHEET, "D", participants_last)

    put(ws, "B3", f"='{SHOWCASE}'!$B$6", "mk_text")
    put(ws, "B4", f"='{SHOWCASE}'!$B$12", "mk_ratio")
    put(ws, "B5", f"='{params.SHEET}'!{product_column}25", "mk_pct")
    put(ws, "B6", _selected("B", last), "mk_pct_fine")
    put(ws, "B7", _selected("AS", last), "mk_pct")
    put(ws, "B8", f"='{params.SHEET}'!{product_column}30", "mk_pct_fine")
    put(ws, "B9", _selected("AR", last), "mk_pct")
    put(ws, "B10", f"='{params.SHEET}'!{product_column}26", "mk_money")
    put(ws, "B11", f"='{params.SHEET}'!{product_column}28", "mk_money")
    put(ws, "B12", f"='{params.SHEET}'!{product_column}29", "mk_money")
    put(ws, "B13", f"=IFERROR(SUM({tons})/$B$18,0)", "mk_tons")
    put(ws, "B14", f'=COUNTIF({tons},">0")', "mk_count")
    put(ws, "B18", f"=COUNTIFS({in_pool},TRUE())", "mk_count")
    put(ws, f"B{NEW_SHARE_WITHOUT}", config.new_share_without, "mk_input")
    put(ws, f"C{NEW_SHARE_WITHOUT}",
        "Доля новых в сценарии без акции, из конфига. Ноль означает, "
        "что без акции новых участников не было бы вовсе",
        "mk_note")
    put(ws, "B19", f"='{SHOWCASE}'!$B$19", "mk_pct")
    put(ws, "B20", f"='{SHOWCASE}'!$B$20", "mk_pct")
    put(ws, "B21", f"='{SHOWCASE}'!$B$21", "mk_money")

    put(ws, "C9", "Показатели взяты из уровня, выбранного на витрине", "mk_note")
    put(ws, "C13", "Делится на весь пул, включая договоры без продукта акции", "mk_note")


def _write_groups(
    ws: Worksheet,
    config: CampaignConfig,
    participants_last: int,
    forecast_first: int,
    forecast_last: int,
    last: int,
    mix_total_row: int,
    pool_forecast_last: int = 0,
    pool_forecast_size: int = 0,
) -> None:
    section(ws, GROUPS_SECTION_ROW, "4. Параметры двух групп участников", 3)
    headers(ws, GROUPS_HEADER_ROW, {"A": "Параметр", "B": "Значение", "C": "Пояснение"})

    labels = {
        NEW_COUNT: "Новые клиенты, прогноз, ед.",
        MARKUP_CURRENT: "Доп. скидка текущим, %",
        MARKUP_NEW: "Доп. скидка новым, %",
        NEW_TONS: f"{config.product} нового клиента, т/мес.",
        NEW_TERM: "Средний срок нового, мес.",
        NEW_STP: "СТП новых клиентов, %",
        NEW_FEE: "Сервисный сбор новых, %",
        NEW_MARGIN: "Маржа новых клиентов, руб./т",
    }
    for row, label in labels.items():
        put(ws, f"A{row}", label, "mk_label")

    product_column = next(
        column for column, name in params.ECONOMICS_PRODUCTS.items() if name == config.product
    )
    tons = column_range(pool.SHEET, pool.PRODUCT_TONS, participants_last)
    rates = column_range(pool.SHEET, pool.FEE_RATE, participants_last)
    margin_column = next(
        column for column, name in params.CALENDAR_MARGIN.items() if name == config.product
    )
    new_share = f"'{params.SHEET}'!$I${forecast_first}:$I${forecast_last}"
    margin = (
        f"'{params.SHEET}'!${margin_column}${forecast_first}:${margin_column}${forecast_last}"
    )

    if pool_forecast_size > 0:
        numbers = fc.range_of(fc.NUMBER, pool_forecast_last)
        terms = fc.range_of(fc.TERM, pool_forecast_last)
        ton_months = fc.range_of(fc.TON_MONTHS, pool_forecast_last)
        discount_tm = fc.range_of(fc.DISCOUNT_TON_MONTHS, pool_forecast_last)
        fee_tm = fc.range_of(fc.FEE_TON_MONTHS, pool_forecast_last)
        put(ws, f"B{NEW_COUNT}", f"=COUNTA({numbers})", "mk_count")
        put(ws, f"C{NEW_COUNT}",
            f"Строк на листе «{fc.SHEET}». Прогноз идет от фактического темпа "
            f"подключения по датам договоров, а не от плана",
            "mk_note")
    else:
        put(ws, f"B{NEW_COUNT}", f"=MAX(0,{config.plan_participants}-$B$18)", "mk_count")
        put(ws, f"C{NEW_COUNT}", "План участников из конфига минус текущий пул", "mk_note")
    put(ws, f"B{MARKUP_CURRENT}", _selected("B", last), "mk_pct_fine")
    put(ws, f"C{MARKUP_CURRENT}", "Надбавка выбранного на витрине уровня", "mk_note")
    put(ws, f"B{MARKUP_NEW}", f"=$B${MARKUP_CURRENT}", "mk_pct_fine")
    put(ws, f"C{MARKUP_NEW}", "Новым та же надбавка, что и текущим", "mk_note")
    if pool_forecast_size > 0:
        put(ws, f"B{NEW_TONS}",
            f"=IFERROR(SUM({ton_months})/SUM({terms}),0)", "mk_tons")
        put(ws, f"C{NEW_TONS}",
            "Средневзвешенно по строкам прогнозного пула, а не по среднему пулу",
            "mk_note")
        put(ws, f"B{NEW_TERM}", f"=IFERROR(SUM({terms})/$B${NEW_COUNT},0)", "mk_ratio")
        put(ws, f"C{NEW_TERM}",
            "Средний срок по строкам: у каждой своя дата подключения", "mk_note")
        put(ws, f"B{NEW_STP}",
            f"=IFERROR(SUM({discount_tm})/SUM({ton_months}),0)", "mk_pct")
        put(ws, f"C{NEW_STP}", "Взвешенно по объему строк: у крупных СТП ниже", "mk_note")
        put(ws, f"B{NEW_FEE}",
            f"=IFERROR(SUM({fee_tm})/SUM({ton_months}),0)", "mk_pct_fine")
        put(ws, f"C{NEW_FEE}", "Взвешенно по объему строк, как и СТП", "mk_note")
    else:
        put(ws, f"B{NEW_TONS}", f"='{params.SHEET}'!$G${mix_total_row}", "mk_tons")
        put(ws, f"C{NEW_TONS}",
            "Из состава сегментов, блок 7 листа параметров, а не из среднего по пулу",
            "mk_note")
        put(ws, f"B{NEW_TERM}", f"=SUM({new_share})", "mk_ratio")
        put(ws, f"C{NEW_TERM}", "Короче срока акции: подключение идет равномерно", "mk_note")
        put(ws, f"B{NEW_STP}", f"='{params.SHEET}'!$H${mix_total_row}", "mk_pct")
        put(ws, f"C{NEW_STP}", "Взвешенно по составу: у крупных СТП ниже", "mk_note")
        put(ws, f"B{NEW_FEE}", f"='{params.SHEET}'!$I${mix_total_row}", "mk_pct_fine")
        put(ws, f"C{NEW_FEE}", "Взвешенно по составу, как и СТП", "mk_note")
    put(ws, f"B{NEW_MARGIN}",
        f"=IFERROR(SUMPRODUCT({new_share},{margin})/SUM({new_share}),0)", "mk_money")


def _write_levels(
    ws: Worksheet,
    config: CampaignConfig,
    participants_last: int,
    last: int,
    aggregates: NewAggregates,
) -> None:
    # Когда глубина распределена, эта таблица перестает быть сценариями акции
    # и становится справкой: строка отвечает на вопрос «что было бы, если бы
    # всю акцию провели на одной глубине». Сценарий акции — раздел 6.
    title = (
        "5. Справочно: что было бы, если бы всю акцию провели на одной глубине "
        "(сценарий акции — раздел 6 ниже)"
        if config.distribution is not None
        else "5. Глубина скидки: уровни эффективной скидки клиента, текущие и новые вместе"
    )
    section(ws, LEVELS_SECTION_ROW, title, len(LEVEL_HEADERS))
    headers(ws, LEVELS_HEADER_ROW, LEVEL_HEADERS)

    tons = column_range(pool.SHEET, pool.PRODUCT_TONS, participants_last)
    discount = column_range(pool.SHEET, pool.DISCOUNT_TONS, participants_last)
    fee_base = column_range(pool.SHEET, pool.FEE_BASE, participants_last)
    rates = column_range(pool.SHEET, pool.FEE_RATE, participants_last)

    # Объем и деньги новых участников: суммами по прогнозному пулу, если он есть.
    new = aggregates.tons
    new_discount = aggregates.discount
    new_fee_base = aggregates.fee_base
    new_fee = aggregates.fee
    new_client_months = aggregates.client_months

    for index, target in enumerate(config.targets):
        row = LEVELS_FIRST_ROW + index
        put(ws, f"A{row}", f"Уровень {target * 100:g}%", "mk_label")
        put(ws, f"AQ{row}", target, "mk_pct")

        put(ws, f"B{row}",
            f"=IF(T{row}+AV{row}>0,(AQ{row}*T{row}-AT{row}+AU{row})/(T{row}+AV{row}),0)")
        put(ws, f"C{row}", "=$B$18+$B$66")
        put(ws, f"D{row}",
            f"=$B$18*$B$4*$B$19+{new_client_months}*$B${NEW_SHARE_WITHOUT}")
        put(ws, f"E{row}", f"=$B$18*$B$4*$B$20+{new_client_months}*$B$20")
        put(ws, f"F{row}", f"=R{row}-Q{row}")
        put(ws, f"G{row}", f"=AL{row}-AK{row}")
        put(ws, f"H{row}", f"=AB{row}-AA{row}")
        put(ws, f"I{row}", f"=L{row}+G{row}")
        put(ws, f"J{row}", f"=AH{row}-AG{row}")
        put(ws, f"K{row}", f"=AD{row}-AC{row}")
        put(ws, f"L{row}", f"=AJ{row}-AI{row}")
        put(ws, f"M{row}", f'=IF(G{row}>0,I{row}/G{row},"")')
        put(ws, f"N{row}", f'=IF(G{row}>0,L{row}/G{row},"")')

        put(ws, f"O{row}", f"=$B$18*$B$19+$B${NEW_COUNT}*$B${NEW_SHARE_WITHOUT}")
        put(ws, f"P{row}", f"=C{row}*$B$20")
        put(ws, f"Q{row}", f"=SUM({tons})*$B$4*$B$19+{new}*$B${NEW_SHARE_WITHOUT}")
        put(ws, f"R{row}", f"=SUM({tons})*$B$4*$B$20+{new}*$B$20")
        put(ws, f"S{row}", f"=Q{row}*$B$10")
        put(ws, f"T{row}", f"=R{row}*$B$10")
        put(ws, f"U{row}",
            f"=SUM({discount})*$B$4*$B$19*$B$10"
            f"+{new_discount}*$B$10*$B${NEW_SHARE_WITHOUT}")
        put(ws, f"V{row}", f"=AT{row}+B{row}*T{row}")
        put(ws, f"W{row}", f"=Q{row}*$B$11")
        put(ws, f"X{row}", f"=R{row}*$B$11")
        put(ws, f"Y{row}", 0)
        put(ws, f"Z{row}", f"=P{row}*$B$21")
        put(ws, f"AA{row}",
            f"=SUM({fee_base})*$B$4*$B$19*$B$10"
            f"+{new_fee_base}*$B$10*$B${NEW_SHARE_WITHOUT}")
        put(ws, f"AB{row}", f"=AU{row}-B{row}*AV{row}")
        put(ws, f"AC{row}", 0)
        put(ws, f"AD{row}", 0)
        put(ws, f"AE{row}",
            f"=SUM({tons})*$B$4*$B$19*$B$12+{new}*$B${NEW_SHARE_WITHOUT}*$B${NEW_MARGIN}")
        put(ws, f"AF{row}", f"=SUM({tons})*$B$4*$B$20*$B$12+{new}*$B$20*$B${NEW_MARGIN}")
        put(ws, f"AG{row}", f"=AE{row}-U{row}-W{row}-Y{row}+AA{row}")
        put(ws, f"AH{row}", f"=AF{row}-V{row}-X{row}-Z{row}+AB{row}")
        put(ws, f"AI{row}", f"=AG{row}+AC{row}")
        put(ws, f"AJ{row}", f"=AH{row}+AD{row}")
        put(ws, f"AK{row}", f"=U{row}+W{row}+Y{row}")
        put(ws, f"AL{row}", f"=V{row}+X{row}+Z{row}")
        put(ws, f"AM{row}", f'=IF(AK{row}>0,(AI{row}+AK{row})/AK{row},"")')
        put(ws, f"AN{row}", f'=IF(AL{row}>0,(AJ{row}+AL{row})/AL{row},"")')
        put(ws, f"AO{row}", f'=IF(AK{row}>0,AI{row}/AK{row},"")')
        put(ws, f"AP{row}", f'=IF(AL{row}>0,AJ{row}/AL{row},"")')
        put(ws, f"AR{row}", f"=IF(T{row}>0,(V{row}-AB{row})/T{row},0)")
        put(ws, f"AS{row}", f"=IF(T{row}>0,V{row}/T{row},0)")
        put(ws, f"AT{row}",
            f"=SUM({discount})*$B$4*$B$20*$B$10+{new_discount}*$B$10*$B$20")
        put(ws, f"AU{row}",
            f"=SUM({fee_base})*$B$4*$B$20*$B$10"
            f"+{new_fee_base}*$B$10*$B$20")
        put(ws, f"AV{row}",
            f"=SUMPRODUCT({tons},{rates})*$B$4*$B$20*$B$10+{new_fee}*$B$10*$B$20")

        for column in MONEY_COLUMNS:
            ws[f"{column}{row}"].number_format = "#,##0"
        for column in PERCENT_COLUMNS:
            ws[f"{column}{row}"].number_format = "0.00%"
        for column in RATIO_COLUMNS:
            ws[f"{column}{row}"].number_format = "#,##0.00"
        for column in TONS_COLUMNS:
            ws[f"{column}{row}"].number_format = "#,##0.000"
        for column in COUNT_COLUMNS:
            ws[f"{column}{row}"].number_format = "#,##0.00"
        ws[f"B{row}"].number_format = "0.000%"

    put(ws, f"A{last + LEVELS_NOTE_ROW_OFFSET}",
        "Надбавка уровня подобрана так, чтобы средневзвешенная эффективная скидка "
        "равнялась цели: надбавка = (цель x выручка с акцией - скидка при надбавке 0 "
        "+ сбор при надбавке 0) / (выручка с акцией + снижение сбора на 1 п.п.). "
        "Колонки AQ и AR должны совпадать на каждой строке.",
        "mk_note")
