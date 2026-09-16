"""Календарь: доли месяцев должны совпадать с эталонной книгой до десятого знака."""

from __future__ import annotations

import datetime as dt

import pytest

from mkforge.core.calendar import (
    CalendarError,
    average_new_term,
    campaign_months,
    month_name,
    month_shares,
)

# Контрольные значения посчитаны вручную по формулам эталонной книги, не нашим кодом.
# Текущие: сентябрь 21 день из 30 = 0,7, октябрь целиком = 1; срок акции 1,7 мес.
# Новые: доля месяца x (накопленная доля - половина доли месяца) / срок акции:
# сентябрь 0,7 x 0,35 / 1,7, октябрь 1 x 1,2 / 1,7; средний срок нового 1,445 / 1,7 = 0,85.
START, END = dt.date(2026, 9, 10), dt.date(2026, 10, 31)


def test_shares_match_reference_book():
    shares = month_shares(START, END)
    assert [s.name for s in shares] == ["сен", "окт"]
    assert shares[0].current == pytest.approx(0.7, abs=1e-12)
    assert shares[1].current == pytest.approx(1.0, abs=1e-12)
    assert shares[0].new == pytest.approx(0.245 / 1.7, abs=1e-12)
    assert shares[1].new == pytest.approx(1.2 / 1.7, abs=1e-12)


def test_totals_match_reference_book():
    assert campaign_months(START, END) == pytest.approx(1.7, abs=1e-12)
    assert average_new_term(START, END) == pytest.approx(0.85, abs=1e-12)


def test_new_term_is_shorter_than_campaign():
    """Новые подключаются по ходу акции, поэтому в среднем действуют меньше."""
    assert average_new_term(START, END) < campaign_months(START, END)


def test_full_month_is_one():
    shares = month_shares(dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    assert len(shares) == 1
    assert shares[0].current == pytest.approx(1.0)


def test_single_day():
    shares = month_shares(dt.date(2026, 10, 15), dt.date(2026, 10, 15))
    assert shares[0].current == pytest.approx(1 / 31)


def test_period_across_year():
    shares = month_shares(dt.date(2026, 12, 20), dt.date(2027, 1, 10))
    assert [s.name for s in shares] == ["дек", "янв"]


def test_end_before_start():
    with pytest.raises(CalendarError, match="раньше начала"):
        month_shares(dt.date(2026, 10, 31), dt.date(2026, 9, 10))


def test_month_names_match_forecast_table():
    assert month_name(dt.date(2026, 9, 1)) == "сен"
    assert month_name(dt.date(2026, 1, 31)) == "янв"
