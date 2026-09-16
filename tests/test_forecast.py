"""Прогнозный пул: новые участники строками, а не произведением средних."""

from __future__ import annotations

import datetime as dt
from collections import Counter

import pytest

from mkforge.core.calendar import campaign_months, month_shares
from mkforge.core.forecast import build_forecast
from mkforge.core.margin import margin_for_new
from mkforge.core.pool import segment_mix

START, END = dt.date(2026, 9, 10), dt.date(2026, 10, 31)


@pytest.fixture
def mix(pool_object):
    return segment_mix(pool_object).tilted(0.5)


@pytest.fixture
def margin(anon_dir):
    from mkforge.core.loaders import load_inputs

    return margin_for_new(load_inputs(anon_dir), "ДТ", month_shares(START, END))


def build(mix, count: int, margin: float):
    return build_forecast(mix, count, "ДТ", START, END, margin)


def test_rows_match_the_requested_count(mix, margin):
    for count in (1, 5, 22, 60):
        assert build(mix, count, margin).size == count


def test_empty_forecast_is_allowed(mix, margin):
    forecast = build(mix, 0, margin)
    assert forecast.size == 0
    assert forecast.ton_months == 0
    assert forecast.new_clients().count == 0


def test_term_never_exceeds_the_campaign(mix, margin):
    limit = campaign_months(START, END)
    for member in build(mix, 22, margin).members:
        assert 0 < member.term_months <= limit + 1e-12


def test_average_term_does_not_depend_on_row_count(mix, margin):
    """Иначе прогноз зависел бы от числа строк, а не от допущения.

    Раньше даты раздавались внутри каждого сегмента, и единственная строка
    сегмента садилась на первый день акции — средний срок выходил завышенным.
    """
    terms = [build(mix, count, margin).new_clients().term_months for count in (22, 43, 64)]
    assert max(terms) - min(terms) < 0.01


def test_dates_are_spread_across_the_campaign(mix, margin):
    dates = sorted(member.connected for member in build(mix, 22, margin).members)
    assert dates[0] == START
    assert dates[-1] == END
    assert len(set(dates)) > 1


def test_every_segment_of_the_mix_is_represented_somewhere(mix, margin):
    """На большом прогнозе состав должен повторять заданный, а не терять сегменты."""
    forecast = build(mix, 400, margin)
    present = Counter(member.segment for member in forecast.members)
    expected = {
        segment.bracket.label for segment in mix.segments if segment.share > 0.01
    }
    assert expected <= set(present)


def test_aggregates_are_sums_over_rows(mix, margin):
    """Свод для экономики — сумма по строкам, а не произведение средних."""
    forecast = build(mix, 22, margin)
    new = forecast.new_clients()
    assert new.ton_months == pytest.approx(
        sum(m.tons_per_month * m.term_months for m in forecast.members)
    )
    assert new.client_months == pytest.approx(
        sum(m.term_months for m in forecast.members)
    )
    assert new.fee_base_ton_months == pytest.approx(
        sum(m.ton_months * (1 - m.stp_rate) * m.fee_rate for m in forecast.members)
    )


def test_product_of_averages_differs_from_the_sum(mix, margin):
    """Ровно поэтому агрегаты и заданы суммами.

    Срок и ставки по строкам разные, и произведение средних не обязано
    совпадать с суммой произведений. Проверяем, что мы не полагаемся на это.
    """
    forecast = build(mix, 22, margin)
    new = forecast.new_clients()
    naive = new.ton_months * (1 - new.stp_rate) * new.fee_rate
    assert new.fee_base_ton_months != pytest.approx(naive, rel=1e-9)


def test_tilt_moves_the_composition_to_the_large(pool_object, margin):
    """Смещение к объему — это утверждение о том, кого приведут менеджеры."""
    base = segment_mix(pool_object)
    small = build(base.tilted(0.0), 200, margin).new_clients()
    large = build(base.tilted(1.0), 200, margin).new_clients()
    assert large.tons_per_client > small.tons_per_client
    assert large.stp_rate < small.stp_rate, "у крупных СТП ниже"
