"""Лист «База для расчета»: шкала СТП, экономика продукта, календарь и прогноз маржи.

Адреса блоков как в эталонной книге. Два отличия сделаны намеренно.

Первое: проценты хранятся долями. В эталоне шкала лежала числами (2,5) и формулы
делили на 100 — ровно тот скрытый множитель, из-за которого потом не сходятся концы.

Второе: соответствие отделений и регионов прогноза вынесено в отдельный блок-справочник,
а маржа месяца считается через SUMPRODUCT по нему. В эталоне то же самое было записано
слагаемым на каждое отделение внутри одной формулы на 2600 символов, и существовало только там.
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from mkforge.core.calendar import MONTH_NAMES
from mkforge.core.models import Inputs
from mkforge.renderers import transactions as tx
from mkforge.renderers.grid import column_range, headers, put, section, widths

SHEET = "База для расчета"

SCALE_FIRST_ROW = 3
ECONOMICS_SECTION_ROW = 23
ECONOMICS_HEADER_ROW = 24
ECONOMICS_FIRST_ROW = 25
CALENDAR_SECTION_ROW = 34
CALENDAR_HEADER_ROW = 35
CALENDAR_FIRST_ROW = 36
CALENDAR_LAST_ROW = 53
FORECAST_FIRST_ROW = 3
BRANCHES_FIRST_ROW = 3

# Блок 3: показатель -> строка. Колонки B..E это АБ, ДТ, СУГ, НП.
ECONOMICS_ROWS = {
    "Скидка/СТП без акции, %": 25,
    "Выручка брутто, руб/т": 26,
    "Себестоимость, руб/т": 27,
    "OPEX, руб/т": 28,
    "Маржа базовая, руб/т": 29,
    "Средняя ставка сервисного сбора, %": 30,
    "Маржа СТиУ, %": 31,
}
ECONOMICS_PRODUCTS = {"B": "АБ", "C": "ДТ", "D": "СУГ", "E": "НП"}

# Блок 4: колонка маржи в календаре -> вид продукта.
CALENDAR_MARGIN = {"D": "АБ", "E": "ДТ", "F": "СУГ"}
# Блок 6: вид продукта -> колонка с объемом отделения.
BRANCH_VOLUME = {"АБ": "S", "ДТ": "T", "СУГ": "U"}

SHOWCASE = "Витрина акции"
PARTICIPANTS = "База участников"

# Блок 7: состав новых участников по сегментам шкалы.
MIX_SECTION_ROW = 56
MIX_HEADER_ROW = 57
MIX_FIRST_ROW = 58
MIX_THRESHOLD = "X57"  # порог крупного, тыс. л/мес — ввод
MIX_SHIFT = "X58"  # сдвиг доли крупных, п.п. — ввод
MIX_SMALL_SHARE = "X59"
MIX_LARGE_SHARE = "X60"
MIX_MOVED = "X61"
MIX_TILT = "X62"  # смещение состава к объему, 0..1 — ввод
MIX_SHIFTED = "J"  # служебная колонка: доля после сдвига, до смещения


def _months_choose(cell: str) -> str:
    names = ",".join(f'"{name}"' for name in MONTH_NAMES)
    return f'=IF({cell}="","",CHOOSE(MONTH({cell}),{names}))'


def _total_tons(product: str, tx_last: int) -> str:
    """Весь объем продукта, включая транзакции без отделения.

    Знаменатель намеренно шире числителя: безотделенческий объем разбавляет маржу
    месяца вниз. Так считает эталон, и `loaders.check` о таких строках сообщает.
    """
    return (
        f"SUMIFS({column_range(tx.SHEET, tx.TONS, tx_last)},"
        f"{column_range(tx.SHEET, tx.PRODUCT, tx_last)},\"{product}\")"
    )


def write(
    ws: Worksheet,
    inputs: Inputs,
    product: str,
    tx_last: int,
    participants_last: int,
    threshold_thousand_liters: float = 150.0,
    shift_points: float = 0.0,
    tilt_to_volume: float = 0.0,
) -> int:
    """Выложить все блоки листа параметров. Возвращает строку «Итого» блока 7."""
    widths(ws, {"A": 30, "B": 12, "C": 12, "D": 14, "E": 14, "F": 12, "G": 14, "H": 14,
                "I": 16, "J": 16, "L": 10, "M": 14, "N": 14, "O": 22, "P": 20,
                "Q": 24, "R": 22, "S": 14, "T": 14, "U": 14,
                "W": 30, "X": 12})

    scale_last = _write_scale(ws, inputs)
    forecast_last = _write_forecast(ws, inputs)
    branches_last = _write_branches(ws, inputs, product, tx_last)
    _write_forecast_volume(ws, forecast_last, branches_last)
    _write_calendar(ws, forecast_last, tx_last)
    _write_economics(ws, inputs, tx_last, participants_last)
    return write_mix(
        ws, inputs, product, participants_last, scale_last,
        threshold_thousand_liters, shift_points, tilt_to_volume,
    )


def _write_scale(ws: Worksheet, inputs: Inputs) -> int:
    section(ws, 1, "1. СТП: шкала и расчет", 7)
    headers(ws, 2, {
        "A": "Объем выборки НП, тыс. л/мес.", "B": "АБ", "C": "ДТ", "D": "СУГ",
        "E": "Мин", "F": "Макс", "G": "ДТ на трассовых АЗС",
    })
    row = SCALE_FIRST_ROW
    for bracket in inputs.scale.brackets:
        put(ws, f"A{row}", bracket.label, "mk_text")
        put(ws, f"B{row}", bracket.ab, "mk_pct")
        put(ws, f"C{row}", bracket.dt, "mk_pct")
        put(ws, f"D{row}", bracket.lpg, "mk_pct")
        put(ws, f"E{row}", bracket.low, "mk_count")
        put(ws, f"F{row}", bracket.high, "mk_count")
        put(ws, f"G{row}", bracket.dt_highway, "mk_pct")
        row += 1

    if inputs.scale.has_highway:
        put(ws, f"A{row + 1}",
            "Трассовая шкала приведена справочно: расчет по ней пока не делается, "
            "надбавка акции с ней не суммируется. Источник — уведомление о СТП.",
            "mk_note")
    else:
        put(ws, f"A{row + 1}",
            "Трассовая шкала не заполнена: шкала взята из книги, а не из уведомления.",
            "mk_note")
    return row - 1


def _write_forecast(ws: Worksheet, inputs: Inputs) -> int:
    section(ws, 1, "5. Маржа экономистов, прогноз", 5, first_column=12)  # L
    headers(ws, 2, {
        "L": "Месяц", "M": "Вид продукта", "N": "Маржа, руб/т",
        "O": "Регион экономистов", "P": "Объем отделений региона, т",
    })
    row = FORECAST_FIRST_ROW
    for line in inputs.margin:
        put(ws, f"L{row}", line.month, "mk_text")
        put(ws, f"M{row}", line.product, "mk_text")
        put(ws, f"N{row}", line.margin, "mk_money")
        put(ws, f"O{row}", line.region, "mk_text")
        row += 1
    return row - 1


def _write_branches(ws: Worksheet, inputs: Inputs, product: str, tx_last: int) -> int:
    """Блок 6: справочник отделений и объем каждого по видам продукта."""
    section(ws, 1, "6. Отделения и регионы прогноза маржи", 5, first_column=17)  # Q
    headers(ws, 2, {
        "Q": "Отделение ТО", "R": "Регион прогноза",
        "S": "Объем АБ, т", "T": "Объем ДТ, т", "U": "Объем СУГ, т",
    })
    row = BRANCHES_FIRST_ROW
    for branch, region in sorted(inputs.branch_regions.items()):
        put(ws, f"Q{row}", branch, "mk_text")
        put(ws, f"R{row}", region, "mk_text")
        for each_product, column in BRANCH_VOLUME.items():
            put(
                ws, f"{column}{row}",
                f"=SUMIFS({column_range(tx.SHEET, tx.TONS, tx_last)},"
                f"{column_range(tx.SHEET, tx.BRANCH, tx_last)},$Q{row},"
                f"{column_range(tx.SHEET, tx.PRODUCT, tx_last)},\"{each_product}\")",
                "mk_tons",
            )
        row += 1
    put(ws, f"Q{row}", "Итого по известным отделениям", "mk_label")
    for column in BRANCH_VOLUME.values():
        put(ws, f"{column}{row}", f"=SUM({column}{BRANCHES_FIRST_ROW}:{column}{row - 1})", "mk_tons")
    return row - 1


def _write_forecast_volume(ws: Worksheet, forecast_last: int, branches_last: int) -> None:
    """Колонка P блока 5: объем отделений, ссылающихся на регион этой строки."""
    for row in range(FORECAST_FIRST_ROW, forecast_last + 1):
        terms = " + ".join(
            f"SUMIFS(${column}${BRANCHES_FIRST_ROW}:${column}${branches_last},"
            f"$R${BRANCHES_FIRST_ROW}:$R${branches_last},$O{row})*($M{row}=\"{product}\")"
            for product, column in BRANCH_VOLUME.items()
        )
        put(ws, f"P{row}", f"={terms}", "mk_tons")


def _write_calendar(ws: Worksheet, forecast_last: int, tx_last: int) -> None:
    """Блок 4: месяцы акции, доли и маржа продукта по каждому месяцу."""
    section(ws, CALENDAR_SECTION_ROW, "4. Помесячная маржа для срока действия акции", 9)
    headers(ws, CALENDAR_HEADER_ROW, {
        "A": "Дата месяца", "B": "Месяц маржи", "C": "Доля месяца: текущие",
        "D": "Маржа АБ, руб/т", "E": "Маржа ДТ, руб/т", "F": "Маржа СУГ, руб/т",
        "G": "Маржа НП, руб/т", "H": "Строк прогноза", "I": "Доля месяца: новые",
    })
    first, last = CALENDAR_FIRST_ROW, CALENDAR_LAST_ROW
    months = f"$L${FORECAST_FIRST_ROW}:$L${forecast_last}"
    products = f"$M${FORECAST_FIRST_ROW}:$M${forecast_last}"
    values = f"$N${FORECAST_FIRST_ROW}:$N${forecast_last}"
    weights = f"$P${FORECAST_FIRST_ROW}:$P${forecast_last}"

    for row in range(first, last + 1):
        if row == first:
            put(ws, f"A{row}",
                f"=DATE(YEAR('{SHOWCASE}'!$B$10),MONTH('{SHOWCASE}'!$B$10),1)", "mk_date")
        else:
            put(ws, f"A{row}",
                f'=IF(A{row - 1}="","",DATE(YEAR(A{row - 1}),MONTH(A{row - 1})+1,1))', "mk_date")
        put(ws, f"B{row}", _months_choose(f"A{row}"), "mk_text")
        put(ws, f"C{row}",
            f"=MAX(0,MIN(EOMONTH(A{row},0),'{SHOWCASE}'!$B$11)"
            f"-MAX(A{row},'{SHOWCASE}'!$B$10)+1)/DAY(EOMONTH(A{row},0))", "mk_pct")
        put(ws, f"H{row}", f"=COUNTIF({months},$B{row})", "mk_count")

        for column, product in CALENDAR_MARGIN.items():
            put(ws, f"{column}{row}",
                f'=IF(COUNTIFS({months},$B{row},{products},"{product}")=0,"",'
                f"IFERROR(SUMPRODUCT(({months}=$B{row})*({products}=\"{product}\")*{values}*{weights})"
                f"/{_total_tons(product, tx_last)},0))", "mk_money")

        fuel = " + ".join(
            f'IF({column}{row}="",0,{column}{row})*{_total_tons(product, tx_last)}'
            for column, product in CALENDAR_MARGIN.items()
        )
        fuel_weight = " + ".join(
            f'IF({column}{row}="",0,{_total_tons(product, tx_last)})'
            for column, product in CALENDAR_MARGIN.items()
        )
        put(ws, f"G{row}",
            f'=IF(COUNTIF({months},$B{row})=0,"",IFERROR(({fuel})/({fuel_weight}),0))', "mk_money")

        put(ws, f"I{row}",
            f"=IFERROR(C{row}*(SUM($C${first}:C{row})-C{row}/2)/SUM($C${first}:$C${last}),0)",
            "mk_pct")


def write_mix(
    ws: Worksheet,
    inputs: Inputs,
    product: str,
    participants_last: int,
    scale_last: int,
    threshold_thousand_liters: float,
    shift_points: float,
    tilt_to_volume: float = 0.0,
) -> int:
    """Блок 7: состав новых участников по сегментам шкалы.

    Ячейки ввода стоят в колонках W и X, а не рядом с блоком: колонка L занята
    месяцами прогноза маржи на всю его высоту, и ввод блока 7 затирал пять его
    строк. Внешне это не проявлялось — затертые месяцы не попадали в период
    акции, — но при другом периоде маржа поехала бы молча.

    Нужен потому, что скидку скорее дадут тем, кто везет больше. У крупного клиента
    и объем выше, и СТП со ставкой сбора ниже, поэтому множитель на средний объем
    дал бы неверный ответ — состав приходится держать целиком.

    Все считается формулами от «Базы участников»: доли, объем на договор, ставки.
    Порог крупного и сдвиг доли — ввод, их можно менять прямо в книге.
    """
    section(ws, MIX_SECTION_ROW, "7. Состав новых участников по сегментам шкалы", 9)
    headers(ws, MIX_HEADER_ROW, {
        "A": "Сегмент", "B": "Мин, тыс. л", "C": "Макс, тыс. л",
        "D": "Договоров в пуле", "E": "Доля в пуле", "F": "Доля у новых",
        "G": "Объем на договор, т", "H": "СТП, %", "I": "Ставка сбора, %",
    })
    put(ws, f"{MIX_SHIFTED}{MIX_HEADER_ROW}", "Доля после сдвига", "mk_header")

    put(ws, "W57", "Порог крупного, тыс. л/мес", "mk_label")
    put(ws, MIX_THRESHOLD, threshold_thousand_liters, "mk_input_count")
    put(ws, "W58", "Сдвиг доли крупных, п.п.", "mk_label")
    put(ws, MIX_SHIFT, shift_points, "mk_input_count")
    put(ws, "W59", "Доля мелких сегментов", "mk_label")
    put(ws, "W60", "Доля крупных сегментов", "mk_label")
    put(ws, "W61", "Переносится к крупным", "mk_label")
    put(ws, "W62", "Новые крупнее типичного: 0 — как в пуле, 1 — как самые крупные", "mk_label")
    put(ws, MIX_TILT, tilt_to_volume, "mk_input")

    liters = column_range(PARTICIPANTS, "I", participants_last)
    tons = column_range(PARTICIPANTS, "O", participants_last)
    rates = column_range(PARTICIPANTS, "R", participants_last)
    in_pool = column_range(PARTICIPANTS, "D", participants_last)

    last = MIX_FIRST_ROW + len(inputs.scale.brackets) - 1
    shares = f"$E${MIX_FIRST_ROW}:$E${last}"
    bounds = f"$B${MIX_FIRST_ROW}:$B${last}"
    shifted = f"${MIX_SHIFTED}${MIX_FIRST_ROW}:${MIX_SHIFTED}${last}"

    for offset, bracket in enumerate(inputs.scale.brackets):
        row = MIX_FIRST_ROW + offset
        scale_row = SCALE_FIRST_ROW + offset
        # Границы сегмента в литрах: сегмент выбирается по объему выборки НП.
        low = f'">="&$B{row}*1000'
        high = f'"<"&$C{row}*1000'

        put(ws, f"A{row}", f"=$A${scale_row}", "mk_text")
        put(ws, f"B{row}", f"=$E${scale_row}", "mk_count")
        put(ws, f"C{row}", f"=$F${scale_row}", "mk_count")
        put(ws, f"D{row}",
            f"=COUNTIFS({liters},{low},{liters},{high},{in_pool},TRUE())", "mk_count")
        put(ws, f"E{row}",
            f"=IFERROR($D{row}/SUM($D${MIX_FIRST_ROW}:$D${last}),0)", "mk_pct")
        # Сдвиг: у крупных доля растет, у мелких падает, пропорционально своим.
        put(ws, f"{MIX_SHIFTED}{row}",
            f"=IF($B{row}>={MIX_THRESHOLD},"
            f"IFERROR($E{row}*({MIX_LARGE_SHARE}+{MIX_MOVED})/{MIX_LARGE_SHARE},$E{row}),"
            f"IFERROR($E{row}*({MIX_SMALL_SHARE}-{MIX_MOVED})/{MIX_SMALL_SHARE},$E{row}))",
            "mk_pct")
        # Смещение к объему: ноль — состав как у типичного договора, единица —
        # как у средней тонны. Доли смешиваются линейно.
        put(ws, f"F{row}",
            f"=${MIX_SHIFTED}{row}*(1-{MIX_TILT})"
            f"+IFERROR(${MIX_SHIFTED}{row}*$G{row}"
            f"/SUMPRODUCT({shifted},$G${MIX_FIRST_ROW}:$G${last}),0)*{MIX_TILT}",
            "mk_pct")
        put(ws, f"G{row}",
            f"=IFERROR(SUMIFS({tons},{liters},{low},{liters},{high})/$D{row},0)", "mk_tons")
        put(ws, f"H{row}", f"=$C${scale_row}", "mk_pct")
        put(ws, f"I{row}",
            f"=IFERROR(SUMPRODUCT(({liters}>=$B{row}*1000)*({liters}<$C{row}*1000)"
            f"*{tons}*{rates})/SUMIFS({tons},{liters},{low},{liters},{high}),0)",
            "mk_pct_fine")

    put(ws, MIX_SMALL_SHARE, f"=SUMIF({bounds},\"<\"&{MIX_THRESHOLD},{shares})", "mk_pct")
    put(ws, MIX_LARGE_SHARE, f"=SUMIF({bounds},\">=\"&{MIX_THRESHOLD},{shares})", "mk_pct")
    put(ws, MIX_MOVED, f"=MIN({MIX_SHIFT}/100,{MIX_SMALL_SHARE})", "mk_pct")

    total = last + 1
    put(ws, f"A{total}", "Итого / на одного нового", "mk_label")
    put(ws, f"E{total}", f"=SUM($E${MIX_FIRST_ROW}:$E${last})", "mk_pct")
    put(ws, f"F{total}", f"=SUM($F${MIX_FIRST_ROW}:$F${last})", "mk_pct")
    put(ws, f"{MIX_SHIFTED}{total}", f"=SUM({shifted})", "mk_pct")
    put(ws, f"G{total}",
        f"=SUMPRODUCT($F${MIX_FIRST_ROW}:$F${last},$G${MIX_FIRST_ROW}:$G${last})", "mk_tons")
    put(ws, f"H{total}",
        f"=IFERROR(SUMPRODUCT($F${MIX_FIRST_ROW}:$F${last},$G${MIX_FIRST_ROW}:$G${last},"
        f"$H${MIX_FIRST_ROW}:$H${last})/$G{total},0)", "mk_pct")
    put(ws, f"I{total}",
        f"=IFERROR(SUMPRODUCT($F${MIX_FIRST_ROW}:$F${last},$G${MIX_FIRST_ROW}:$G${last},"
        f"$I${MIX_FIRST_ROW}:$I${last})/$G{total},0)", "mk_pct_fine")
    put(ws, f"A{total + 1}",
        "Объем, СТП и ставка сбора нового участника берутся из строки «Итого»: "
        "взвешенно по составу, а не по среднему пулу. Сдвиг ноль означает состав как есть.",
        "mk_note")
    return total


def _write_economics(
    ws: Worksheet, inputs: Inputs, tx_last: int, participants_last: int
) -> None:
    """Блок 3: экономика по виду продукта. Считаемое — формулами, входное — числами."""
    section(ws, ECONOMICS_SECTION_ROW, "3. Экономика по виду продукта", 5)
    headers(ws, ECONOMICS_HEADER_ROW, {"A": "Показатель", **ECONOMICS_PRODUCTS})
    for label, row in ECONOMICS_ROWS.items():
        put(ws, f"A{row}", label, "mk_label")

    calendar_first, calendar_last = CALENDAR_FIRST_ROW, CALENDAR_LAST_ROW
    for column, product in ECONOMICS_PRODUCTS.items():
        economics = inputs.economics[product]
        margin_column = next(
            (c for c, p in CALENDAR_MARGIN.items() if p == product), None
        )

        stp = column_range(PARTICIPANTS, "K", participants_last)
        tons = column_range(PARTICIPANTS, "O", participants_last)
        put(ws, f"{column}25",
            f"=IFERROR(SUMPRODUCT({stp},{tons})/SUM({tons}),0)", "mk_pct")
        put(ws, f"{column}26", economics.gross_revenue, "mk_money")
        put(ws, f"{column}27", economics.cost, "mk_money")
        put(ws, f"{column}28", economics.opex, "mk_money")
        if margin_column:
            put(ws, f"{column}29",
                f"=IFERROR(SUMPRODUCT($C${calendar_first}:$C${calendar_last},"
                f"{margin_column}${calendar_first}:{margin_column}${calendar_last})"
                f'/SUMPRODUCT($C${calendar_first}:$C${calendar_last},'
                f'--({margin_column}${calendar_first}:{margin_column}${calendar_last}<>"")),0)',
                "mk_money")
        else:
            put(ws, f"{column}29",
                f"=IFERROR(SUMPRODUCT($C${calendar_first}:$C${calendar_last},"
                f"$G${calendar_first}:$G${calendar_last})"
                f'/SUMPRODUCT($C${calendar_first}:$C${calendar_last},'
                f'--($G${calendar_first}:$G${calendar_last}<>"")),0)', "mk_money")
        put(ws, f"{column}30",
            f"=IFERROR(ABS(SUMIFS({column_range(tx.SHEET, tx.SERVICE_FEE, tx_last)},"
            f"{column_range(tx.SHEET, tx.PRODUCT, tx_last)},{column}$24)"
            f"/SUMIFS({column_range(tx.SHEET, tx.REVENUE, tx_last)},"
            f"{column_range(tx.SHEET, tx.PRODUCT, tx_last)},{column}$24)),0)", "mk_pct_fine")
        put(ws, f"{column}31", economics.stiu_margin, "mk_pct")


# Вид продукта -> колонка шкалы СТП в блоке 1.
SCALE_PRODUCTS = {"АБ": "B", "ДТ": "C", "СУГ": "D"}


def scale_rate_range(product: str, scale_last: int) -> str:
    """Колонка шкалы со скидкой для вида продукта."""
    column = SCALE_PRODUCTS[product]
    return f"'{SHEET}'!${column}${SCALE_FIRST_ROW}:${column}${scale_last}"


def scale_bound_range(scale_last: int) -> str:
    """Колонка нижних границ шкалы — по ней ищется сегмент."""
    return f"'{SHEET}'!$E${SCALE_FIRST_ROW}:$E${scale_last}"
