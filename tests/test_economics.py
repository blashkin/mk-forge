"""Экономика: надбавка двигает скидку и сбор в противоположные стороны."""

from __future__ import annotations

import pytest

from mkforge.core.economics import Economics, Effect, NewClients, basis, scenario


@pytest.fixture
def parts(anon_dir):
    from mkforge.core.loaders import load_inputs
    from mkforge.core.pool import build_pool

    pool = build_pool(load_inputs(anon_dir), "ДТ")
    new = NewClients.homogeneous(
        count=10, tons_per_client=pool.tons_per_contract, term_months=0.7,
        stp_rate=pool.weighted("stp_rate"), fee_rate=pool.weighted("service_fee_rate"),
        margin_per_ton=6000.0,
    )
    economics = Economics(
        price_per_ton=75_000.0, opex_per_ton=1_500.0, margin_per_ton=8_000.0,
        comms_per_client=0.0,
    )
    return pool, new, economics


def make_basis(parts, share: float, with_comms: bool = True, new_share: float | None = None):
    """Доли эффекта раздельные; по умолчанию новые идут с той же долей, что текущие."""
    pool, new, economics = parts
    return basis(
        pool=pool, new=new, economics=economics, months_current=1.7,
        current_share=share,
        new_share=share if new_share is None else new_share,
        with_comms=with_comms,
    )


def test_zero_effect_share_gives_empty_scenario(parts):
    empty = scenario(make_basis(parts, 0.0, with_comms=False), markup=0.0)
    assert empty.tons == 0.0
    assert empty.revenue == 0.0
    assert empty.costs == 0.0
    assert empty.net_margin == 0.0
    assert empty.effective_discount == 0.0


def test_markup_raises_discount_and_lowers_fee(parts):
    base = make_basis(parts, 1.0)
    plain = scenario(base, markup=0.0)
    raised = scenario(base, markup=0.02)
    assert raised.discount > plain.discount
    assert raised.service_fee < plain.service_fee
    assert raised.tons == plain.tons  # объем от надбавки не зависит
    assert raised.gross_margin == plain.gross_margin


def test_markup_adds_exactly_its_share_of_revenue(parts):
    base = make_basis(parts, 1.0)
    plain = scenario(base, markup=0.0)
    raised = scenario(base, markup=0.03)
    assert raised.discount - plain.discount == pytest.approx(0.03 * base.revenue)


def test_service_fee_is_income(parts):
    """Сбор прибавляется к марже: это доход, а не затрата."""
    plain = scenario(make_basis(parts, 1.0), markup=0.0)
    assert plain.net_margin == pytest.approx(
        plain.gross_margin - plain.costs + plain.service_fee
    )
    assert plain.service_fee > 0


def test_costs_are_discount_opex_and_comms(parts):
    plain = scenario(make_basis(parts, 1.0), markup=0.01)
    assert plain.costs == pytest.approx(plain.discount + plain.opex + plain.comms)


def test_communication_only_in_campaign_scenario(parts):
    pool, new, _ = parts
    economics = Economics(
        price_per_ton=75_000.0, opex_per_ton=1_500.0, margin_per_ton=8_000.0,
        comms_per_client=500.0,
    )
    common = dict(
        pool=pool, new=new, economics=economics, months_current=1.7,
        current_share=1.0, new_share=1.0,
    )
    without = basis(**common, with_comms=False)
    with_campaign = basis(**common, with_comms=True)
    assert without.comms == 0.0
    assert with_campaign.comms == pytest.approx(with_campaign.participants * 500.0)


def test_effect_is_the_difference(parts):
    base_without = make_basis(parts, 0.0, with_comms=False)
    base_with = make_basis(parts, 1.0)
    effect = Effect(
        without=scenario(base_without, markup=0.0),
        with_campaign=scenario(base_with, markup=0.01),
    )
    assert effect.tons == pytest.approx(base_with.tons)
    assert effect.costs > 0
    assert effect.payback == pytest.approx(effect.roi + 1)


def test_deeper_discount_costs_more_and_earns_less(parts):
    base_without = make_basis(parts, 0.0, with_comms=False)
    base_with = make_basis(parts, 1.0)
    shallow = Effect(scenario(base_without, 0.0), scenario(base_with, 0.01))
    deep = Effect(scenario(base_without, 0.0), scenario(base_with, 0.05))
    assert deep.costs > shallow.costs
    assert deep.margin < shallow.margin
    assert deep.roi < shallow.roi
