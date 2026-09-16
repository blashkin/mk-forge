"""Пул: сегменты по шкале, период выгрузки, средние по всему пулу."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from mkforge.core.loaders import CONTRACTS_FILE, TRANSACTIONS_FILE, load_inputs
from mkforge.core.models import ModelError
from mkforge.core.pool import build_pool, period_months
from tests.conftest import liters_for, tons_for


@pytest.fixture
def pool_dt(anon_dir: Path):
    return build_pool(load_inputs(anon_dir), "ДТ")


def test_whole_pool_is_kept(pool_dt, pool):
    assert pool_dt.size == len(pool)
    assert pool_dt.contracts_with_volume == len(pool)


def test_single_month_export(pool_dt):
    assert pool_dt.period_months == 1


def test_brackets_spread_across_scale(pool_dt):
    """Фикстура должна задевать все сегменты, иначе шкала не проверена."""
    assert len({m.bracket.label for m in pool_dt.members}) == 3


def test_bracket_follows_fuel_volume(pool_dt):
    """Сегмент выбирается по объему топлива в тысячах литров, не по объему продукта."""
    for member in pool_dt.members:
        thousands = member.fuel_liters_per_month / 1000
        assert member.bracket.low <= thousands
        assert thousands < member.bracket.high or member.bracket.high >= 999_999


def test_volumes_come_from_transactions(pool_dt, pool):
    by_contract = {m.contract: m for m in pool_dt.members}
    expected = sorted(liters_for(i) for i in range(len(pool)))
    assert sorted(m.fuel_liters_per_month for m in by_contract.values()) == pytest.approx(expected)
    assert sorted(m.product_tons_per_month for m in by_contract.values()) == pytest.approx(
        sorted(tons_for(i) for i in range(len(pool)))
    )


def test_service_fee_rate_is_positive(pool_dt):
    """В выгрузке сбор со знаком минус, ставка должна получиться положительной."""
    assert all(m.service_fee_rate > 0 for m in pool_dt.members)


def test_effective_discount_without_campaign(pool_dt):
    """Шкала СТП компенсирует сбор, поэтому базовая эффективная скидка близка к нулю."""
    for member in pool_dt.members:
        assert abs(member.effective_discount_without_campaign) < 0.05


def test_markup_raises_effective_discount(pool_dt):
    member = pool_dt.members[0]
    base = member.effective_discount_without_campaign
    assert member.effective_discount(0.01) > base
    assert member.effective_discount(0.05) > member.effective_discount(0.01)


def test_average_divides_by_whole_pool(anon_dir, pool):
    """Договор без транзакций остается в пуле и тянет средний объем вниз."""
    full = build_pool(load_inputs(anon_dir), "ДТ")

    path = anon_dir / CONTRACTS_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    lines.append("Д-БЕЗДВИЖЕНИЙ,CRT,2020-01-01")
    path.write_text("\n".join(lines), encoding="utf-8")

    with_idle = build_pool(load_inputs(anon_dir), "ДТ")
    assert with_idle.size == full.size + 1
    assert with_idle.contracts_with_volume == full.contracts_with_volume
    assert with_idle.total_tons_per_month == pytest.approx(full.total_tons_per_month)
    assert with_idle.tons_per_contract < full.tons_per_contract


def test_weighted_average_is_by_volume(pool_dt):
    """Средневзвешенная СТП должна лежать между крайними ставками пула."""
    rates = [m.stp_rate for m in pool_dt.members]
    assert min(rates) <= pool_dt.weighted("stp_rate") <= max(rates)
    assert pool_dt.weighted("stp_rate") != pytest.approx(sum(rates) / len(rates))


def test_period_spans_months():
    class Fake:
        def __init__(self, month):
            self.month = month

    assert period_months((Fake(dt.date(2026, 8, 1)),)) == 1
    assert period_months((Fake(dt.date(2026, 8, 1)), Fake(dt.date(2026, 10, 1)))) == 3
    assert period_months((Fake(dt.date(2026, 12, 1)), Fake(dt.date(2027, 1, 1)))) == 2


def test_no_transactions_at_all():
    with pytest.raises(ModelError, match="период не определить"):
        period_months(())


def test_other_product_gives_zero_volume(anon_dir):
    """Для продукта, которого нет в выгрузке, пул остается, а объем нулевой."""
    lpg = build_pool(load_inputs(anon_dir), "СУГ")
    assert lpg.size > 0
    assert lpg.total_tons_per_month == 0.0
    assert lpg.weighted("stp_rate") == 0.0
