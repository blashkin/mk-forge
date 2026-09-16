"""Темп подключения: фактический ритм вместо плана из брифа."""

from __future__ import annotations

import datetime as dt

import pytest

from mkforge.core.growth import connection_rate, expected_new_clients
from mkforge.core.models import Contract, ModelError


def contracts(dates: list[tuple[int, int, int]]) -> tuple[Contract, ...]:
    return tuple(
        Contract.model_validate(
            {"договор": f"Д-{index:04d}", "сегмент": "Тест",
             "дата_подключения": dt.date(*date)}
        )
        for index, date in enumerate(dates)
    )


def month(year: int, number: int, count: int) -> list[tuple[int, int, int]]:
    return [(year, number, 1 + index % 28) for index in range(count)]


def test_last_month_is_dropped_as_incomplete():
    """В последнем месяце выгрузки договоры еще добавятся, считать его нельзя."""
    pool = contracts(month(2026, 1, 10) + month(2026, 2, 10) + month(2026, 3, 1))
    rate = connection_rate(pool)
    assert rate.counts == (10, 10)
    assert rate.per_month == 10


def test_median_ignores_a_spike():
    """Среднее всплеск тянет за собой, медиана — нет."""
    pool = contracts(
        month(2025, 1, 5) + month(2025, 2, 5) + month(2025, 3, 100)
        + month(2025, 4, 5) + month(2025, 5, 1)
    )
    rate = connection_rate(pool)
    assert rate.per_month == 5
    assert rate.mean_per_month > rate.per_month


def test_window_limits_how_far_back_we_look():
    dates = []
    for number in range(1, 13):
        dates += month(2026, number, number)
    dates += month(2027, 1, 1)
    rate = connection_rate(contracts(dates), window_months=3)
    assert rate.counts == (10, 11, 12)
    assert rate.first_month == dt.date(2026, 10, 1)


def test_empty_pool_is_reported():
    with pytest.raises(ModelError, match="нет договоров"):
        connection_rate(())


def test_forecast_is_rate_times_period_times_uplift():
    pool = contracts(month(2026, 1, 10) + month(2026, 2, 10) + month(2026, 3, 1))
    rate = connection_rate(pool)
    assert expected_new_clients(rate, campaign_months=1.5, uplift=1.0) == 15
    assert expected_new_clients(rate, campaign_months=1.5, uplift=2.0) == 30
    assert expected_new_clients(rate, campaign_months=1.5, uplift=0.0) == 0


def test_negative_uplift_is_refused():
    pool = contracts(month(2026, 1, 10) + month(2026, 2, 1))
    with pytest.raises(ModelError, match="отрицательным"):
        expected_new_clients(connection_rate(pool), campaign_months=1.0, uplift=-1.0)


def test_real_pool_gives_a_rate(pool_object, anon_dir):
    """На синтетическом пуле темп тоже считается: проверяем проводку."""
    from mkforge.core.loaders import load_inputs

    rate = connection_rate(load_inputs(anon_dir).contracts)
    assert rate.per_month > 0
    assert "медиана" in rate.report()
