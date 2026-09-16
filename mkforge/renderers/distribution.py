"""Раздел «Распределение глубины скидки» на листе расчета.

Таблица уровней выше отвечает на вопрос «что будет, если вся акция пройдет
на одной глубине». Этот раздел отвечает на другой: скидку раздают менеджеры
по одному, основная масса приходится на 4-5%, и итог складывается из срезов.

Поэтому эффективная скидка здесь не задание, а результат: она получается
из долей, а не подставляется в них.

Надбавка подбирается срезу, а не пулу. У крупного клиента СТП ниже, поэтому
на одну и ту же эффективную скидку ему нужна надбавка выше — одна надбавка
на всех дала бы разным клиентам разную глубину.

Внизу раздела стоит порог безубыточности. Сценарий без акции линеен по доле
объема, поэтому порог берется решением уравнения, а не подбором: доля, при
которой дополнительная маржа обращается в ноль.
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from mkforge.config import CampaignConfig
from mkforge.renderers import forecast as fc
from mkforge.renderers import participants as pool
from mkforge.renderers.grid import column_range, headers, put, section, widths

SECTION_ROW = 85
HEADER_ROW = 86
FIRST_ROW = 87

# Ячейка ввода: как раздается скидка. Единица — глубже тем, кто больше везет.
MODE = "B22"
MODE_LABEL = "A22"

DEPTH = "B"
SHARE = "C"
CUMULATIVE = "D"
LOWER = "E"
CONTRACTS = "F"
FORECAST_CONTRACTS = "G"
MARKUP = "H"
TONS_CURRENT = "I"
TONS_NEW = "J"
REVENUE = "K"
DISCOUNT_AT_ZERO = "L"
FEE_AT_ZERO = "M"
FEE_DROP = "N"
DISCOUNT = "O"
FEE = "P"
OPEX = "Q"
COMMS = "R"
COSTS = "S"
GROSS = "T"
NET = "U"
TONS_CURRENT_WITHOUT = "V"
TONS_NEW_WITHOUT = "W"
DISCOUNT_WITHOUT = "X"
FEE_WITHOUT = "Y"
OPEX_WITHOUT = "Z"
COSTS_WITHOUT = "AA"
GROSS_WITHOUT = "AB"
NET_WITHOUT = "AC"
EXTRA_COSTS = "AD"
EXTRA_MARGIN = "AE"
PAYBACK = "AF"
ROI = "AG"
EFFECTIVE = "AH"

LABELS = {
    "A": "Глубина скидки",
    DEPTH: "Эффективная скидка, %",
    SHARE: "Доля пула, %",
    CUMULATIVE: "Нарастающий итог, %",
    LOWER: "Нижняя граница, %",
    CONTRACTS: "Договоров факт, ед.",
    FORECAST_CONTRACTS: "Договоров прогноз, ед.",
    MARKUP: "Надбавка к СТП, %",
    TONS_CURRENT: "Объем текущих, т",
    TONS_NEW: "Объем новых, т",
    REVENUE: "Выручка, руб.",
    DISCOUNT_AT_ZERO: "Скидка при надбавке 0, руб.",
    FEE_AT_ZERO: "Сбор при надбавке 0, руб.",
    FEE_DROP: "Снижение сбора на 1 п.п., руб.",
    DISCOUNT: "Скидка, руб.",
    FEE: "Сервисный сбор, руб.",
    OPEX: "OPEX, руб.",
    COMMS: "Коммуникация, руб.",
    COSTS: "Затраты, руб.",
    GROSS: "Маржа валовая, руб.",
    NET: "Маржа нетто, руб.",
    TONS_CURRENT_WITHOUT: "Объем текущих без акции, т",
    TONS_NEW_WITHOUT: "Объем новых без акции, т",
    DISCOUNT_WITHOUT: "Скидка без акции, руб.",
    FEE_WITHOUT: "Сбор без акции, руб.",
    OPEX_WITHOUT: "OPEX без акции, руб.",
    COSTS_WITHOUT: "Затраты без акции, руб.",
    GROSS_WITHOUT: "Маржа валовая без акции, руб.",
    NET_WITHOUT: "Маржа нетто без акции, руб.",
    EXTRA_COSTS: "Доп. затраты, руб.",
    EXTRA_MARGIN: "Доп. маржа, руб.",
    PAYBACK: "Окупаемость, руб./руб.",
    ROI: "ROI, руб./руб.",
    EFFECTIVE: "Эффективная скидка факт, %",
}

MONEY = (REVENUE, DISCOUNT_AT_ZERO, FEE_AT_ZERO, FEE_DROP, DISCOUNT, FEE, OPEX,
         COMMS, COSTS, GROSS, NET, DISCOUNT_WITHOUT, FEE_WITHOUT, OPEX_WITHOUT,
         COSTS_WITHOUT, GROSS_WITHOUT, NET_WITHOUT, EXTRA_COSTS, EXTRA_MARGIN)
TONS = (TONS_CURRENT, TONS_NEW, TONS_CURRENT_WITHOUT, TONS_NEW_WITHOUT)
PERCENTS = (DEPTH, SHARE, CUMULATIVE, LOWER, EFFECTIVE)
RATIOS = (PAYBACK, ROI)
COUNTS = (CONTRACTS, FORECAST_CONTRACTS)

# Порог безубыточности: подписи и строки под таблицей.
BREAKEVEN_OFFSET = 2
BREAKEVEN_LABELS = (
    "Служебное: маржа нетто без акции при доле объема 0",
    "Служебное: маржа нетто без акции при доле объема 1",
    "Служебное: затраты без акции при доле объема 0",
    "Служебное: затраты без акции при доле объема 1",
    "До какой доли объема без акции акция не уходит в минус",
    "До какой доли объема без акции ROI выше 1",
)


def total_row(count: int) -> int:
    return FIRST_ROW + count


def breakeven_rows(count: int) -> dict[str, int]:
    """Строки блока порогов: подпись -> строка."""
    first = total_row(count) + BREAKEVEN_OFFSET
    return {label: first + offset for offset, label in enumerate(BREAKEVEN_LABELS)}


def depth_range(count: int) -> str:
    return f"$B${FIRST_ROW}:$B${FIRST_ROW + count - 1}"


def lower_range(count: int) -> str:
    return f"$E${FIRST_ROW}:$E${FIRST_ROW + count - 1}"


def markup_range(count: int) -> str:
    return f"$H${FIRST_ROW}:$H${FIRST_ROW + count - 1}"


def _mode(by_volume: str, flat: str) -> str:
    """Формула, зависящая от способа раздачи."""
    return f"IF(${MODE}=1,{by_volume},{flat})"


def write(
    ws: Worksheet,
    config: CampaignConfig,
    participants_last: int,
    forecast_last: int,
    forecast_size: int,
) -> int:
    """Выложить раздел распределения. Возвращает последнюю строку блока порогов."""
    distribution = config.distribution
    assert distribution is not None, "раздел пишется только при заданном распределении"
    ordered = distribution.deepest_first()
    count = len(ordered.shares)
    last = FIRST_ROW + count - 1
    total = total_row(count)

    widths(ws, {LOWER: 16, CUMULATIVE: 20, SHARE: 14})
    section(ws, SECTION_ROW,
            "6. Распределение глубины скидки: скидку раздают менеджеры по одному",
            len(LABELS))
    headers(ws, HEADER_ROW, LABELS)

    put(ws, MODE_LABEL,
        "Кому достаются глубокие проценты: 1 — тем, кто больше везет; "
        "0 — вне зависимости от размера клиента",
        "mk_label")
    put(ws, MODE, 1 if ordered.by_volume else 0, "mk_input_count")

    # Агрегаты пула и прогноза по срезу. В режиме «по объему» срез — свои
    # договоры, поэтому SUMIFS по колонке глубины. Иначе срез — доля от всего,
    # и агрегат берется умножением итога на долю.
    pool_tons = column_range(pool.SHEET, pool.PRODUCT_TONS, participants_last)
    pool_discount = column_range(pool.SHEET, pool.DISCOUNT_TONS, participants_last)
    pool_fee_base = column_range(pool.SHEET, pool.FEE_BASE, participants_last)
    pool_rates = column_range(pool.SHEET, pool.FEE_RATE, participants_last)
    pool_depth = column_range(pool.SHEET, pool.DEPTH, participants_last)
    pool_in = column_range(pool.SHEET, "D", participants_last)

    has_forecast = forecast_size > 0
    if has_forecast:
        f_depth = fc.range_of(fc.DEPTH, forecast_last)
        f_tons = fc.range_of(fc.TON_MONTHS, forecast_last)
        f_discount = fc.range_of(fc.DISCOUNT_TON_MONTHS, forecast_last)
        f_fee_base = fc.range_of(fc.FEE_BASE_TON_MONTHS, forecast_last)
        f_fee = fc.range_of(fc.FEE_TON_MONTHS, forecast_last)

    for offset, share in enumerate(ordered.shares):
        row = FIRST_ROW + offset
        lower = sum(s.share for s in ordered.shares[:offset])

        put(ws, f"A{row}", f"Глубина {share.depth * 100:g}%", "mk_label")
        put(ws, f"{DEPTH}{row}", share.depth, "mk_pct")
        put(ws, f"{SHARE}{row}", share.share, "mk_input")
        put(ws, f"{CUMULATIVE}{row}",
            f"=SUM(${SHARE}${FIRST_ROW}:${SHARE}{row})", "mk_pct")
        put(ws, f"{LOWER}{row}",
            "0" if offset == 0 else f"=${CUMULATIVE}{row - 1}", "mk_pct")
        if offset == 0:
            put(ws, f"{LOWER}{row}", 0, "mk_pct")

        def slice_of(column_range_text: str, value_column: str) -> str:
            """Агрегат среза: по колонке глубины или долей от итога."""
            return _mode(
                f"SUMIFS({column_range_text},{pool_depth},${DEPTH}{row})",
                f"SUM({column_range_text})*${SHARE}{row}",
            )

        tons_slice = slice_of(pool_tons, pool.PRODUCT_TONS)
        discount_slice = slice_of(pool_discount, pool.DISCOUNT_TONS)
        fee_base_slice = slice_of(pool_fee_base, pool.FEE_BASE)
        fee_drop_slice = _mode(
            f"SUMPRODUCT(({pool_depth}=${DEPTH}{row})*{pool_tons}*{pool_rates})",
            f"SUMPRODUCT({pool_tons},{pool_rates})*${SHARE}{row}",
        )
        contracts_slice = _mode(
            f"COUNTIFS({pool_depth},${DEPTH}{row})",
            f"COUNTIFS({pool_in},TRUE())*${SHARE}{row}",
        )

        if has_forecast:
            f_tons_slice = _mode(
                f"SUMIFS({f_tons},{f_depth},${DEPTH}{row})",
                f"SUM({f_tons})*${SHARE}{row}",
            )
            f_discount_slice = _mode(
                f"SUMIFS({f_discount},{f_depth},${DEPTH}{row})",
                f"SUM({f_discount})*${SHARE}{row}",
            )
            f_fee_base_slice = _mode(
                f"SUMIFS({f_fee_base},{f_depth},${DEPTH}{row})",
                f"SUM({f_fee_base})*${SHARE}{row}",
            )
            f_fee_slice = _mode(
                f"SUMIFS({f_fee},{f_depth},${DEPTH}{row})",
                f"SUM({f_fee})*${SHARE}{row}",
            )
            f_contracts_slice = _mode(
                f"COUNTIFS({f_depth},${DEPTH}{row})",
                f"{forecast_size}*${SHARE}{row}",
            )
        else:
            f_tons_slice = f_discount_slice = f_fee_base_slice = "0"
            f_fee_slice = f_contracts_slice = "0"

        put(ws, f"{CONTRACTS}{row}", f"={contracts_slice}")
        put(ws, f"{FORECAST_CONTRACTS}{row}", f"={f_contracts_slice}")

        put(ws, f"{TONS_CURRENT}{row}", f"=({tons_slice})*$B$4*$B$20")
        put(ws, f"{TONS_NEW}{row}", f"=({f_tons_slice})*$B$20")
        put(ws, f"{REVENUE}{row}",
            f"=(${TONS_CURRENT}{row}+${TONS_NEW}{row})*$B$10")
        put(ws, f"{DISCOUNT_AT_ZERO}{row}",
            f"=(({discount_slice})*$B$4*$B$20+({f_discount_slice})*$B$20)*$B$10")
        put(ws, f"{FEE_AT_ZERO}{row}",
            f"=(({fee_base_slice})*$B$4*$B$20+({f_fee_base_slice})*$B$20)*$B$10")
        put(ws, f"{FEE_DROP}{row}",
            f"=(({fee_drop_slice})*$B$4*$B$20+({f_fee_slice})*$B$20)*$B$10")

        # Надбавка среза под его глубину. Та же формула, что у уровней, но
        # по агрегатам среза: у крупных СТП ниже, значит надбавка нужна выше.
        put(ws, f"{MARKUP}{row}",
            f"=IF(${REVENUE}{row}+${FEE_DROP}{row}>0,"
            f"(${DEPTH}{row}*${REVENUE}{row}-${DISCOUNT_AT_ZERO}{row}"
            f"+${FEE_AT_ZERO}{row})/(${REVENUE}{row}+${FEE_DROP}{row}),0)")

        put(ws, f"{DISCOUNT}{row}",
            f"=${DISCOUNT_AT_ZERO}{row}+${MARKUP}{row}*${REVENUE}{row}")
        put(ws, f"{FEE}{row}", f"=${FEE_AT_ZERO}{row}-${MARKUP}{row}*${FEE_DROP}{row}")
        put(ws, f"{OPEX}{row}",
            f"=(${TONS_CURRENT}{row}+${TONS_NEW}{row})*$B$11")
        put(ws, f"{COMMS}{row}",
            f"=(${CONTRACTS}{row}+${FORECAST_CONTRACTS}{row})*$B$20*$B$21")
        put(ws, f"{COSTS}{row}",
            f"=${DISCOUNT}{row}+${OPEX}{row}+${COMMS}{row}")
        put(ws, f"{GROSS}{row}",
            f"=${TONS_CURRENT}{row}*$B$12+${TONS_NEW}{row}*$B$73")
        put(ws, f"{NET}{row}", f"=${GROSS}{row}-${COSTS}{row}+${FEE}{row}")

        put(ws, f"{TONS_CURRENT_WITHOUT}{row}", f"=({tons_slice})*$B$4*$B$19")
        put(ws, f"{TONS_NEW_WITHOUT}{row}", f"=({f_tons_slice})*$B$15")
        put(ws, f"{DISCOUNT_WITHOUT}{row}",
            f"=(({discount_slice})*$B$4*$B$19+({f_discount_slice})*$B$15)*$B$10")
        put(ws, f"{FEE_WITHOUT}{row}",
            f"=(({fee_base_slice})*$B$4*$B$19+({f_fee_base_slice})*$B$15)*$B$10")
        put(ws, f"{OPEX_WITHOUT}{row}",
            f"=(${TONS_CURRENT_WITHOUT}{row}+${TONS_NEW_WITHOUT}{row})*$B$11")
        put(ws, f"{COSTS_WITHOUT}{row}",
            f"=${DISCOUNT_WITHOUT}{row}+${OPEX_WITHOUT}{row}")
        put(ws, f"{GROSS_WITHOUT}{row}",
            f"=${TONS_CURRENT_WITHOUT}{row}*$B$12+${TONS_NEW_WITHOUT}{row}*$B$73")
        put(ws, f"{NET_WITHOUT}{row}",
            f"=${GROSS_WITHOUT}{row}-${COSTS_WITHOUT}{row}+${FEE_WITHOUT}{row}")

        put(ws, f"{EXTRA_COSTS}{row}", f"=${COSTS}{row}-${COSTS_WITHOUT}{row}")
        put(ws, f"{EXTRA_MARGIN}{row}", f"=${NET}{row}-${NET_WITHOUT}{row}")
        put(ws, f"{PAYBACK}{row}",
            f'=IF(${EXTRA_COSTS}{row}>0,'
            f'(${EXTRA_MARGIN}{row}+${EXTRA_COSTS}{row})/${EXTRA_COSTS}{row},"")')
        put(ws, f"{ROI}{row}",
            f'=IF(${EXTRA_COSTS}{row}>0,${EXTRA_MARGIN}{row}/${EXTRA_COSTS}{row},"")')
        put(ws, f"{EFFECTIVE}{row}",
            f"=IF(${REVENUE}{row}>0,(${DISCOUNT}{row}-${FEE}{row})/${REVENUE}{row},0)")

        _format(ws, row)

    _write_total(ws, count, last, total)
    return _write_breakeven(
        ws, count, total, participants_last, forecast_last, forecast_size,
        pool_tons, pool_discount, pool_fee_base, pool_rates,
    )


def _format(ws: Worksheet, row: int) -> None:
    for column in MONEY:
        ws[f"{column}{row}"].number_format = "#,##0"
    for column in TONS:
        ws[f"{column}{row}"].number_format = "#,##0.000"
    for column in PERCENTS:
        ws[f"{column}{row}"].number_format = "0.00%"
    for column in RATIOS:
        ws[f"{column}{row}"].number_format = "#,##0.00"
    for column in COUNTS:
        ws[f"{column}{row}"].number_format = "#,##0.0"
    ws[f"{MARKUP}{row}"].number_format = "0.000%"


def _write_total(ws: Worksheet, count: int, last: int, total: int) -> None:
    """Строка «Итого»: это и есть ответ акции целиком."""
    put(ws, f"A{total}", "Итого по акции", "mk_label")

    # Средняя глубина по договорам. На нее ссылаются листы пула в режиме
    # раздачи, не зависящей от размера клиента: там у всех она одна.
    put(ws, f"{DEPTH}{total}",
        f"=SUMPRODUCT(${DEPTH}${FIRST_ROW}:${DEPTH}${last},"
        f"${SHARE}${FIRST_ROW}:${SHARE}${last})", "mk_pct")
    put(ws, f"{SHARE}{total}", f"=SUM(${SHARE}${FIRST_ROW}:${SHARE}${last})", "mk_pct")
    put(ws, f"{CUMULATIVE}{total}", f"=${CUMULATIVE}{last}", "mk_pct")

    for column in (CONTRACTS, FORECAST_CONTRACTS, *TONS, *MONEY):
        put(ws, f"{column}{total}", f"=SUM(${column}${FIRST_ROW}:${column}${last})")

    put(ws, f"{MARKUP}{total}",
        f"=IFERROR(SUMPRODUCT(${MARKUP}${FIRST_ROW}:${MARKUP}${last},"
        f"${REVENUE}${FIRST_ROW}:${REVENUE}${last})/${REVENUE}{total},0)")
    put(ws, f"{PAYBACK}{total}",
        f'=IF(${EXTRA_COSTS}{total}>0,'
        f'(${EXTRA_MARGIN}{total}+${EXTRA_COSTS}{total})/${EXTRA_COSTS}{total},"")')
    put(ws, f"{ROI}{total}",
        f'=IF(${EXTRA_COSTS}{total}>0,${EXTRA_MARGIN}{total}/${EXTRA_COSTS}{total},"")')
    put(ws, f"{EFFECTIVE}{total}",
        f"=IF(${REVENUE}{total}>0,(${DISCOUNT}{total}-${FEE}{total})/${REVENUE}{total},0)")
    _format(ws, total)


def _write_breakeven(
    ws: Worksheet,
    count: int,
    total: int,
    participants_last: int,
    forecast_last: int,
    forecast_size: int,
    pool_tons: str,
    pool_discount: str,
    pool_fee_base: str,
    pool_rates: str,
) -> int:
    """Порог доли объема без акции: где акция обращается в ноль."""
    rows = breakeven_rows(count)
    for label, row in rows.items():
        put(ws, f"A{row}", label, "mk_label")

    if forecast_size > 0:
        f_tons = fc.range_of(fc.TON_MONTHS, forecast_last)
        f_discount = fc.range_of(fc.DISCOUNT_TON_MONTHS, forecast_last)
        f_fee_base = fc.range_of(fc.FEE_BASE_TON_MONTHS, forecast_last)
    else:
        f_tons = f_discount = f_fee_base = "0"

    new_tons = f"SUM({f_tons})*$B$15" if forecast_size else "0"
    new_discount = f"SUM({f_discount})*$B$15*$B$10" if forecast_size else "0"
    new_fee = f"SUM({f_fee_base})*$B$15*$B$10" if forecast_size else "0"

    current_tons = f"SUM({pool_tons})*$B$4"
    current_discount = f"SUM({pool_discount})*$B$4*$B$10"
    current_fee = f"SUM({pool_fee_base})*$B$4*$B$10"

    net0, net1, cost0, cost1, payback_row, roi_row = rows.values()

    # Сценарий без акции линеен по доле: считаем его в двух точках.
    put(ws, f"B{net0}",
        f"={new_tons}*$B$73-{new_discount}-{new_tons}*$B$11+{new_fee}", "mk_money")
    put(ws, f"B{net1}",
        f"=$B${net0}+{current_tons}*$B$12-{current_discount}"
        f"-{current_tons}*$B$11+{current_fee}", "mk_money")
    put(ws, f"B{cost0}", f"={new_discount}+{new_tons}*$B$11", "mk_money")
    put(ws, f"B{cost1}",
        f"=$B${cost0}+{current_discount}+{current_tons}*$B$11", "mk_money")

    put(ws, f"B{payback_row}",
        f'=IF($B${net1}-$B${net0}=0,"нет решения",'
        f"IF(OR((${NET}{total}-$B${net0})/($B${net1}-$B${net0})<0,"
        f"(${NET}{total}-$B${net0})/($B${net1}-$B${net0})>1),"
        f'"недостижимо",(${NET}{total}-$B${net0})/($B${net1}-$B${net0})))',
        "mk_pct")
    slope = f"(($B${net1}-$B${cost1})-($B${net0}-$B${cost0}))"
    target = f"(${NET}{total}-${COSTS}{total}-($B${net0}-$B${cost0}))"
    put(ws, f"B{roi_row}",
        f'=IF({slope}=0,"нет решения",'
        f"IF(OR({target}/{slope}<0,{target}/{slope}>1),"
        f'"недостижимо",{target}/{slope}))',
        "mk_pct")

    note = roi_row + 1
    put(ws, f"A{note}",
        "Читается так: поставишь долю объема без акции выше этого значения — "
        "уходим в минус, ниже — держимся. «Недостижимо» значит, что планка "
        "не берется ни при какой доле, даже если считать, что без акции "
        "не пришел бы вообще никто. Сама доля задается на витрине: это решение, "
        "а не расчет. Итог акции целиком — на первом листе.",
        "mk_note")
    return note
