"""Маржа: региональный прогноз сводится к месяцу по объемам отделений."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from mkforge.core.calendar import month_shares
from mkforge.core.loaders import MARGIN_FILE, TRANSACTIONS_FILE, load_inputs
from mkforge.core.margin import margin_for_current, margin_for_new, monthly_margin

START, END = dt.date(2026, 9, 10), dt.date(2026, 10, 31)


def test_monthly_margin_covers_forecast_months(anon_dir):
    """Свод идет по всем месяцам прогноза, а не только по месяцам акции."""
    from conftest import CAMPAIGN_MONTHS, margin_forecast

    by_month = monthly_margin(load_inputs(anon_dir), "ДТ")
    expected = {month for month, product, _, _ in margin_forecast() if product == "ДТ"}
    assert set(by_month) == expected
    assert set(CAMPAIGN_MONTHS) <= set(by_month)
    assert all(value > 0 for value in by_month.values())


def test_margin_lies_between_regional_values(anon_dir):
    """Свод по объемам не может выйти за крайние региональные значения."""
    inputs = load_inputs(anon_dir)
    september = [m.margin for m in inputs.margin if m.product == "ДТ" and m.month == "сен"]
    assert min(september) <= monthly_margin(inputs, "ДТ")["сен"] <= max(september)


def test_current_margin_is_weighted_by_month_shares(anon_dir):
    inputs = load_inputs(anon_dir)
    shares = month_shares(START, END)
    by_month = monthly_margin(inputs, "ДТ")
    expected = (
        shares[0].current * by_month["сен"] + shares[1].current * by_month["окт"]
    ) / (shares[0].current + shares[1].current)
    assert margin_for_current(inputs, "ДТ", shares) == pytest.approx(expected)


def test_new_margin_leans_on_later_months(anon_dir):
    """Новые подключаются постепенно, поэтому их маржа ближе к позднему месяцу."""
    inputs = load_inputs(anon_dir)
    shares = month_shares(START, END)
    by_month = monthly_margin(inputs, "ДТ")
    assert by_month["окт"] < by_month["сен"]  # так устроена фикстура
    assert margin_for_new(inputs, "ДТ", shares) < margin_for_current(inputs, "ДТ", shares)


def test_month_without_forecast_drops_out_for_current(anon_dir):
    """Месяц без прогноза не влияет на маржу действующих участников."""
    inputs = load_inputs(anon_dir)
    shares = month_shares(START, END)
    before = margin_for_current(inputs, "ДТ", shares)

    path = anon_dir / MARGIN_FILE
    kept = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("окт")]
    path.write_text("\n".join(kept), encoding="utf-8")

    after = margin_for_current(load_inputs(anon_dir), "ДТ", shares)
    assert after == pytest.approx(monthly_margin(load_inputs(anon_dir), "ДТ")["сен"])
    assert after != pytest.approx(before)


def test_month_without_forecast_counts_as_zero_for_new(anon_dir):
    """У новых знаменатель весь срок, поэтому пропуск месяца тянет маржу вниз."""
    inputs = load_inputs(anon_dir)
    shares = month_shares(START, END)
    before = margin_for_new(inputs, "ДТ", shares)

    path = anon_dir / MARGIN_FILE
    kept = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("окт")]
    path.write_text("\n".join(kept), encoding="utf-8")

    assert margin_for_new(load_inputs(anon_dir), "ДТ", shares) < before


def test_transaction_without_branch_lowers_margin(anon_dir):
    """Документированное поведение эталона: безотделенческий объем разбавляет маржу."""
    inputs = load_inputs(anon_dir)
    before = monthly_margin(inputs, "ДТ")["сен"]

    path = anon_dir / TRANSACTIONS_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    parts = lines[1].split(",")
    parts[9] = ""
    lines[1] = ",".join(parts)
    path.write_text("\n".join(lines), encoding="utf-8")

    assert monthly_margin(load_inputs(anon_dir), "ДТ")["сен"] < before


def test_product_without_transactions(anon_dir):
    assert monthly_margin(load_inputs(anon_dir), "СУГ") == {}
