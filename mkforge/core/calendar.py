"""Календарь акции: какую часть каждого месяца она действует.

Две доли на месяц. Для текущих участников — какая часть месяца попала в срок акции.
Для новых — меньше: они подключаются в течение акции, поэтому в среднем действуют
не весь свой месяц. Обе формулы взяты из эталонной книги.
"""

from __future__ import annotations

import calendar as _calendar
import datetime as dt
from dataclasses import dataclass

MONTH_NAMES = (
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек",
)


class CalendarError(Exception):
    """Период акции задан неверно."""


def month_name(when: dt.date) -> str:
    """Короткое имя месяца так, как оно записано в прогнозе маржи."""
    return MONTH_NAMES[when.month - 1]


@dataclass(frozen=True)
class MonthShare:
    """Доли одного месяца акции."""

    first_day: dt.date
    name: str
    current: float  # доля месяца для действующих участников
    new: float  # доля месяца для новых, с учетом равномерного подключения


def _next_month(when: dt.date) -> dt.date:
    return dt.date(when.year + when.month // 12, when.month % 12 + 1, 1)


def month_shares(start: dt.date, end: dt.date) -> list[MonthShare]:
    """Доли месяцев для периода акции.

    Текущие: доля дней месяца, попавших в период, включая границы.
    Новые: доля месяца, умноженная на среднюю накопленную долю к середине этого
    месяца — так учитывается, что подключение идет равномерно по всему сроку.
    """
    if end < start:
        raise CalendarError(f"конец акции {end} раньше начала {start}")

    months: list[dt.date] = []
    cursor = dt.date(start.year, start.month, 1)
    while cursor <= end:
        months.append(cursor)
        cursor = _next_month(cursor)

    current: list[float] = []
    for first_day in months:
        days_in_month = _calendar.monthrange(first_day.year, first_day.month)[1]
        last_day = dt.date(first_day.year, first_day.month, days_in_month)
        active_from = max(first_day, start)
        active_to = min(last_day, end)
        days = (active_to - active_from).days + 1 if active_to >= active_from else 0
        current.append(days / days_in_month)

    total = sum(current)
    if total <= 0:
        raise CalendarError(f"период {start} - {end} не покрывает ни одного дня")

    shares: list[MonthShare] = []
    cumulative = 0.0
    for first_day, share in zip(months, current, strict=True):
        cumulative += share
        shares.append(
            MonthShare(
                first_day=first_day,
                name=month_name(first_day),
                current=share,
                new=share * (cumulative - share / 2) / total,
            )
        )
    return shares


def campaign_months(start: dt.date, end: dt.date) -> float:
    """Длительность акции в месяцах для действующих участников."""
    return sum(s.current for s in month_shares(start, end))


def average_new_term(start: dt.date, end: dt.date) -> float:
    """Средний срок нового участника в месяцах при равномерном подключении."""
    return sum(s.new for s in month_shares(start, end))


def term_for(connected: dt.date, start: dt.date, end: dt.date) -> float:
    """Срок участника, подключившегося в этот день, в месяцах.

    Считается так же, как доля месяца для действующих: дни от подключения
    до конца акции, деленные на длину месяца, и так по всем месяцам.

    `average_new_term` дает ту же величину в среднем, но приближенно и сразу
    по всему пулу. Здесь срок нужен на строку: прогнозный пул лежит в книге
    строками, и у каждой своя дата подключения.
    """
    if end < start:
        raise CalendarError(f"конец акции {end} раньше начала {start}")

    total = 0.0
    for share in month_shares(start, end):
        first_day = share.first_day
        days_in_month = _calendar.monthrange(first_day.year, first_day.month)[1]
        last_day = dt.date(first_day.year, first_day.month, days_in_month)
        active_from = max(first_day, start, connected)
        active_to = min(last_day, end)
        if active_to >= active_from:
            total += ((active_to - active_from).days + 1) / days_in_month
    return total
