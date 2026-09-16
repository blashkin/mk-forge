"""Лист «Прогнозный пул»: новые участники строками.

Раньше прогноз новых был произведением трех чисел в разделе параметров. Проверить
такое нельзя: в нем нечего проверять, кроме самих трех чисел. Здесь у каждого
прогнозного участника своя строка, свой сегмент шкалы, своя дата подключения
и свой срок с этой даты до конца акции.

Числа в строках — формулы. Объем, СТП и ставка сбора берутся из блока 7 листа
параметров по сегменту, срок считается по календарю акции. Значениями записаны
только сам сегмент и дата подключения: это допущение о том, кого приведут
менеджеры, и оно задается конфигом, а не считается из данных.
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from mkforge.core.forecast import NUMBER_PREFIX, ForecastPool
from mkforge.renderers import parameters as params
from mkforge.renderers.grid import headers, put, section, widths

SHEET = "Прогнозный пул"
FIRST_ROW = 3
HEADER_ROW = 2
SHOWCASE = "Витрина акции"
CALCULATION = "Расчет акции"

NUMBER = "A"
SEGMENT = "B"
CONNECTED = "C"
TERM = "D"
TONS = "E"
STP = "F"
FEE_RATE = "G"
TON_MONTHS = "H"
DISCOUNT_TON_MONTHS = "I"
FEE_BASE_TON_MONTHS = "J"
FEE_TON_MONTHS = "K"
RANK = "L"
CUMULATIVE = "M"
DEPTH = "N"
MARKUP = "O"
EFFECTIVE = "P"

# Доли месяцев акции: по колонке на месяц, столько же, сколько строк в календаре.
MONTH_FIRST_COLUMN = "R"
MONTH_COLUMNS = params.CALENDAR_LAST_ROW - params.CALENDAR_FIRST_ROW + 1

LABELS = {
    NUMBER: "№ прогнозного участника",
    SEGMENT: "Сегмент шкалы",
    CONNECTED: "Дата подключения",
    TERM: "Срок с подключения, мес.",
    TONS: "Объем продукта, т/мес.",
    STP: "СТП продукта, %",
    FEE_RATE: "Ставка сервисного сбора, %",
    TON_MONTHS: "Объем за срок, т",
    DISCOUNT_TON_MONTHS: "Объем х СТП, т",
    FEE_BASE_TON_MONTHS: "База сервисного сбора, т",
    FEE_TON_MONTHS: "Объем х ставка сбора, т",
    RANK: "Ранг по объему",
    CUMULATIVE: "Накопленная доля участников",
    DEPTH: "Глубина скидки, %",
    MARKUP: "Надбавка к СТП, %",
    EFFECTIVE: "Эффективная скидка, %",
}


def last_row(count: int) -> int:
    return FIRST_ROW + count - 1


def _month_column(offset: int) -> str:
    """Буква колонки для месяца акции по порядку."""
    from openpyxl.utils import column_index_from_string, get_column_letter

    return get_column_letter(column_index_from_string(MONTH_FIRST_COLUMN) + offset)


def range_of(column: str, last: int) -> str:
    """Абсолютная ссылка на колонку листа прогноза."""
    return f"'{SHEET}'!${column}${FIRST_ROW}:${column}${last}"


def write(
    ws: Worksheet, forecast: ForecastPool, scale_last: int, depth_count: int = 0
) -> int:
    """Выложить прогнозный пул. Возвращает последнюю строку с данными."""
    # Локальный импорт: раздел распределения ссылается на этот лист.
    from mkforge.renderers import distribution as dist

    section(ws, 1, "Прогнозный пул: новые участники, которых доберут менеджеры", 16)
    headers(ws, HEADER_ROW, LABELS)
    widths(ws, {NUMBER: 24, SEGMENT: 16, CONNECTED: 18, TERM: 22, TONS: 20, STP: 14,
                FEE_RATE: 22, TON_MONTHS: 16, DISCOUNT_TON_MONTHS: 16,
                FEE_BASE_TON_MONTHS: 22, FEE_TON_MONTHS: 20, RANK: 14,
                CUMULATIVE: 24, DEPTH: 16, MARKUP: 16, EFFECTIVE: 18})

    if not forecast.members:
        put(ws, f"{NUMBER}{FIRST_ROW}",
            "Прогноз пуст: темп подключения и множитель дают ноль новых участников",
            "mk_note")
        return HEADER_ROW

    last = last_row(forecast.size)
    mix_last = params.MIX_FIRST_ROW + scale_last - params.SCALE_FIRST_ROW
    labels = f"'{params.SHEET}'!$A${params.MIX_FIRST_ROW}:$A${mix_last}"
    tons_by_segment = f"'{params.SHEET}'!$G${params.MIX_FIRST_ROW}:$G${mix_last}"
    stp_by_segment = f"'{params.SHEET}'!$H${params.MIX_FIRST_ROW}:$H${mix_last}"
    fee_by_segment = f"'{params.SHEET}'!$I${params.MIX_FIRST_ROW}:$I${mix_last}"

    for offset, member in enumerate(forecast.members):
        row = FIRST_ROW + offset
        put(ws, f"{NUMBER}{row}", member.number, "mk_text")
        put(ws, f"{SEGMENT}{row}", member.segment, "mk_text")
        put(ws, f"{CONNECTED}{row}", member.connected, "mk_input_date")

        lookup = f"MATCH(${SEGMENT}{row},{labels},0)"
        put(ws, f"{TONS}{row}", f"=IFERROR(INDEX({tons_by_segment},{lookup}),0)", "mk_tons")
        put(ws, f"{STP}{row}", f"=IFERROR(INDEX({stp_by_segment},{lookup}),0)", "mk_pct")
        put(ws, f"{FEE_RATE}{row}",
            f"=IFERROR(INDEX({fee_by_segment},{lookup}),0)", "mk_pct_fine")

        # Срок: доли месяцев акции от даты подключения до конца. По колонке
        # на месяц календаря — так формула остается простой и проверяемой.
        for index in range(MONTH_COLUMNS):
            column = _month_column(index)
            month_cell = f"'{params.SHEET}'!$A${params.CALENDAR_FIRST_ROW + index}"
            put(ws, f"{column}{row}",
                f'=IF({month_cell}="",0,'
                f"MAX(0,MIN(EOMONTH({month_cell},0),'{SHOWCASE}'!$B${11})"
                f"-MAX({month_cell},'{SHOWCASE}'!$B${10},${CONNECTED}{row})+1)"
                f"/DAY(EOMONTH({month_cell},0)))",
                "mk_pct")
        first_month = _month_column(0)
        last_month = _month_column(MONTH_COLUMNS - 1)
        put(ws, f"{TERM}{row}", f"=SUM({first_month}{row}:{last_month}{row})", "mk_ratio")

        put(ws, f"{TON_MONTHS}{row}", f"=${TONS}{row}*${TERM}{row}", "mk_tons")
        put(ws, f"{DISCOUNT_TON_MONTHS}{row}",
            f"=${TON_MONTHS}{row}*${STP}{row}", "mk_tons")
        put(ws, f"{FEE_BASE_TON_MONTHS}{row}",
            f"=${TON_MONTHS}{row}*(1-${STP}{row})*${FEE_RATE}{row}", "mk_tons")
        put(ws, f"{FEE_TON_MONTHS}{row}",
            f"=${TON_MONTHS}{row}*${FEE_RATE}{row}", "mk_tons")

        # Ранг по объему. Равные объемы упорядочены по строке, а не по номеру:
        # номера прогнозных строк условные, а порядок должен быть устойчивым.
        whole = range_of(TONS, last)
        earlier = (
            f'COUNTIF(${TONS}${FIRST_ROW}:${TONS}{row - 1},"="&${TONS}{row})'
            if row > FIRST_ROW
            else "0"
        )
        put(ws, f"{RANK}{row}",
            f'=COUNTIF({whole},">"&${TONS}{row})+{earlier}+1', "mk_count")
        put(ws, f"{CUMULATIVE}{row}", f"=${RANK}{row}/{forecast.size}", "mk_pct")

        if depth_count:
            put(ws, f"{DEPTH}{row}",
                f"=IF('{CALCULATION}'!${dist.MODE}=1,"
                f"IFERROR(INDEX('{CALCULATION}'!{dist.depth_range(depth_count)},"
                f"MATCH(${CUMULATIVE}{row},"
                f"'{CALCULATION}'!{dist.lower_range(depth_count)},1)),0),"
                f"'{CALCULATION}'!$B${dist.total_row(depth_count)})",
                "mk_pct")
            put(ws, f"{MARKUP}{row}",
                f"=IF('{CALCULATION}'!${dist.MODE}=1,"
                f"IFERROR(INDEX('{CALCULATION}'!{dist.markup_range(depth_count)},"
                f"MATCH(${DEPTH}{row},"
                f"'{CALCULATION}'!{dist.depth_range(depth_count)},0)),0),"
                f"'{CALCULATION}'!$H${dist.total_row(depth_count)})",
                "mk_pct_fine")
            put(ws, f"{EFFECTIVE}{row}",
                f"=1-(1-${STP}{row}-${MARKUP}{row})*(1+${FEE_RATE}{row})", "mk_pct")

    # Служебные колонки прячем: они нужны формулам, а не человеку. Не удаляем —
    # спрятанную колонку можно раскрыть, а удаленную пришлось бы пересобирать.
    for column in (TON_MONTHS, DISCOUNT_TON_MONTHS, FEE_BASE_TON_MONTHS,
                   FEE_TON_MONTHS, RANK, CUMULATIVE):
        ws.column_dimensions[column].hidden = True
    for index in range(MONTH_COLUMNS):
        ws.column_dimensions[_month_column(index)].hidden = True

    ws.freeze_panes = f"{TERM}{FIRST_ROW}"
    put(ws, f"{NUMBER}{last + 2}",
        "Состав по сегментам и даты подключения — допущение из конфига. Объем, СТП, "
        "ставка сбора и срок считаются формулами: по сегменту из блока 7 листа "
        "параметров и по календарю акции. Даты внутри каждого сегмента разнесены "
        "по сроку акции: иначе крупные подключились бы первыми и получили бы "
        "и объем больше, и срок длиннее.",
        "mk_note")
    return last
