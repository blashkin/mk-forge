"""Лист «База участников»: по договору на строку, все величины формулами.

Буквы колонок как в эталонной книге. Колонка Q эталона («Выручка СТиУ, справочно»)
не заполняется: она ни на что не влияла, а пустая колонка честнее мертвой.

Диапазоны по листу транзакций считаются от фактического числа строк. В эталоне
верхняя граница была вписана руками и разъехалась между колонками: часть считала
по всем строкам, часть — впритык до последней, с нулевым зазором.
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from mkforge.core.models import Contract
from mkforge.renderers import parameters as params
from mkforge.renderers import transactions as tx
from mkforge.renderers.grid import column_range, headers, put, widths

SHEET = "База участников"
FIRST_ROW = 2
CALCULATION = "Расчет акции"

CONTRACT = "A"
RANK = "E"
CUMULATIVE = "F"
DEPTH = "G"
FUEL_LITERS = "I"
STP = "K"
MARKUP = "L"
TOTAL_DISCOUNT = "M"
EFFECTIVE = "N"
PRODUCT_TONS = "O"
PERIOD = "P"
FEE_RATE = "R"
DISCOUNT_TONS = "S"
DISCOUNT_TONS_CAMPAIGN = "T"
FEE_BASE = "U"
FEE_BASE_CAMPAIGN = "V"

LABELS = {
    "A": "№ договора",
    "B": "Сегмент",
    "C": "Дата подключения",
    "D": "В пуле акции",
    "E": "Ранг по объему продукта",
    "F": "Накопленная доля договоров",
    "G": "Глубина скидки, %",
    "I": "Среднемес. объем НП, л",
    "J": "Группа участников",
    "K": "СТП продукта, %",
    "L": "Доп. скидка по акции, %",
    "M": "Итоговая скидка, %",
    "N": "Эффективная скидка, %",
    "O": "Среднемес. объем продукта, т",
    "P": "Период транзакций, мес.",
    "R": "Ставка сервисного сбора, %",
    "S": "Объем х СТП, т",
    "T": "Объем х скидка с акцией, т",
    "U": "База сервисного сбора без акции, т",
    "V": "База сервисного сбора с акцией, т",
}


def last_row(count: int) -> int:
    return FIRST_ROW + count - 1


def _sumifs_by_contract(
    value_column: str, filter_column: str, filter_value: str, row: int, tx_last: int
) -> str:
    """SUMIFS по листу транзакций: свой договор плюс один фильтр."""
    return (
        f"SUMIFS({column_range(tx.SHEET, value_column, tx_last)},"
        f"{column_range(tx.SHEET, tx.CONTRACT, tx_last)},$A{row},"
        f"{column_range(tx.SHEET, filter_column, tx_last)},\"{filter_value}\")"
    )


def write(
    ws: Worksheet,
    contracts: tuple[Contract, ...],
    product: str,
    tx_last: int,
    scale_last: int,
    depth_count: int = 0,
) -> int:
    """Выложить пул и вернуть номер последней строки с данными.

    `depth_count` — сколько глубин в распределении скидки. Ноль означает, что
    глубина одна на весь пул: тогда колонки ранга и глубины не нужны, а надбавка
    берется из выбранного на витрине уровня, как в эталонной книге.
    """
    # Локальный импорт: раздел распределения ссылается на этот лист, и на уровне
    # модуля импорты замкнулись бы в кольцо.
    from mkforge.renderers import distribution as dist

    headers(ws, 1, LABELS)
    widths(ws, {"A": 16, "B": 10, "C": 16, "D": 12, "E": 20, "F": 24, "G": 16,
                "I": 18, "J": 20, "K": 12, "L": 14,
                "M": 14, "N": 16, "O": 18, "P": 14, "R": 16, "S": 14, "T": 18,
                "U": 18, "V": 18})

    period = f"${PERIOD}${FIRST_ROW}"
    rate_range = params.scale_rate_range(product, scale_last)
    bound_range = params.scale_bound_range(scale_last)

    for offset, contract in enumerate(contracts):
        row = FIRST_ROW + offset
        put(ws, f"A{row}", contract.contract, "mk_text")
        put(ws, f"B{row}", contract.segment, "mk_text")
        put(ws, f"C{row}", contract.connected, "mk_date")
        put(ws, f"D{row}", f'=IF($A{row}="",FALSE,TRUE)', "mk_text")

        fuel = _sumifs_by_contract(tx.LITERS, tx.PRODUCT_CLASS, "НП", row, tx_last)
        put(ws, f"I{row}", f'=IF($A{row}="","",IFERROR({fuel}/{period},0))', "mk_count")
        put(ws, f"J{row}", f'=IF($A{row}="","","Текущие участники")', "mk_text")

        # Сегмент шкалы: последний, чья нижняя граница не выше объема выборки.
        put(ws, f"K{row}",
            f'=IF($I{row}="","",IFERROR(INDEX({rate_range},'
            f"MATCH($I{row}/1000,{bound_range},1)),0))", "mk_pct")
        if depth_count:
            # Ранг по объему. Равные объемы упорядочены по строке, а не по номеру
            # договора: номера в конце подменяются настоящими, и если бы они
            # участвовали в порядке, подмена меняла бы состав срезов.
            whole = f"$O${FIRST_ROW}:$O${last_row(len(contracts))}"
            earlier = (
                f'COUNTIF($O${FIRST_ROW}:$O{row - 1},"="&$O{row})'
                if row > FIRST_ROW
                else "0"
            )
            put(ws, f"{RANK}{row}",
                f'=IF($A{row}="","",COUNTIF({whole},">"&$O{row})+{earlier}+1)',
                "mk_count")
            # Знаменатель — размер пула из раздела 1 листа расчета.
            put(ws, f"{CUMULATIVE}{row}",
                f'=IF($A{row}="","",IFERROR(${RANK}{row}/\'{CALCULATION}\'!$B$18,0))',
                "mk_pct")
            put(ws, f"{DEPTH}{row}",
                f'=IF($A{row}="","",'
                f"IF('{CALCULATION}'!${dist.MODE}=1,"
                f"IFERROR(INDEX('{CALCULATION}'!{dist.depth_range(depth_count)},"
                f"MATCH(${CUMULATIVE}{row},'{CALCULATION}'!{dist.lower_range(depth_count)},1)),0),"
                f"'{CALCULATION}'!$B${dist.total_row(depth_count)}))",
                "mk_pct")
            put(ws, f"L{row}",
                f'=IF($A{row}="","",'
                f"IF('{CALCULATION}'!${dist.MODE}=1,"
                f"IFERROR(INDEX('{CALCULATION}'!{dist.markup_range(depth_count)},"
                f"MATCH(${DEPTH}{row},'{CALCULATION}'!{dist.depth_range(depth_count)},0)),0),"
                f"'{CALCULATION}'!$H${dist.total_row(depth_count)}))",
                "mk_pct_fine")
        else:
            put(ws, f"L{row}", f"='{CALCULATION}'!$B$67", "mk_pct_fine")
        put(ws, f"M{row}", f'=IF($L{row}="","",$K{row}+$L{row})', "mk_pct")
        put(ws, f"N{row}",
            f'=IF($M{row}="","",1-(1-$M{row})*(1+$R{row}))', "mk_pct")

        tons = _sumifs_by_contract(tx.TONS, tx.PRODUCT, product, row, tx_last)
        put(ws, f"O{row}", f'=IF($A{row}="","",IFERROR({tons}/{period},0))', "mk_tons")

        fee = _sumifs_by_contract(tx.SERVICE_FEE, tx.PRODUCT, product, row, tx_last)
        revenue = _sumifs_by_contract(tx.REVENUE, tx.PRODUCT, product, row, tx_last)
        put(ws, f"R{row}",
            f'=IF($A{row}="","",IFERROR(ABS({fee}/{revenue}),0))', "mk_pct_fine")

        put(ws, f"S{row}", f'=IF($A{row}="","",$O{row}*$K{row})', "mk_tons")
        put(ws, f"T{row}", f'=IF($A{row}="","",$S{row}+$O{row}*$L{row})', "mk_tons")
        put(ws, f"U{row}", f'=IF($A{row}="","",($O{row}-$S{row})*$R{row})', "mk_tons")
        put(ws, f"V{row}", f'=IF($A{row}="","",($O{row}-$T{row})*$R{row})', "mk_tons")

    # Период один на всю выгрузку: месяцы от первой транзакции до последней.
    months = column_range(tx.SHEET, tx.MONTH, tx_last)
    put(ws, f"P{FIRST_ROW}",
        f'=IFERROR(DATEDIF(MIN({months}),MAX({months}),"m")+1,1)', "mk_count")

    if depth_count:
        # Ранг и накопленная доля нужны формуле глубины, читать их незачем.
        for column in (RANK, CUMULATIVE):
            ws.column_dimensions[column].hidden = True

    ws.freeze_panes = "A2"
    return last_row(len(contracts))
