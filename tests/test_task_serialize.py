"""Выдача задания: только величины, никаких данных клиентов.

Главный тест здесь один — что в словаре нет ни номера договора, ни псевдонима,
ни на одном уровне вложенности. Он стоит первым, потому что защищает не от
опечатки, а от одной строки `dataclasses.asdict`, которая тихо вынесет наружу
весь состав пула.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mkforge.campaigns.motivational import plan_from_config
from mkforge.config import load_config
from mkforge.core.loaders import load_inputs
from mkforge.task.serialize import plan_payload

SCENARIO_FIELDS = (
    "markup", "participants", "participant_months", "tons", "revenue", "discount",
    "service_fee", "gross_margin", "opex", "comms", "costs", "net_margin",
    "total_discount_rate", "effective_discount",
)
EFFECT_FIELDS = ("tons", "costs", "margin", "service_fee", "payback", "roi")
# Ключи, за которыми в ядре стоит состав пула, а не величина.
FORBIDDEN_KEYS = ("contract", "contracts_list", "members", "number", "counts", "pool", "forecast")


@pytest.fixture
def inputs(anon_dir: Path):
    return load_inputs(anon_dir)


@pytest.fixture
def payload(inputs, distributed_config_path: Path):
    return plan_payload(plan_from_config(inputs, load_config(distributed_config_path)))


def walk(value, path=""):
    """Пройти словарь насквозь, отдавая пары «путь — значение»."""
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}[{index}]")


def test_payload_is_made_of_primitives(payload):
    """Сериализуется в json — значит внутри нет объектов ядра."""
    assert json.dumps(payload, ensure_ascii=False)


def test_no_contract_numbers_anywhere(payload, pool, inputs):
    """Ни настоящего номера, ни псевдонима, ни прогнозной строки."""
    texts = [
        value for _, value in walk(payload) if isinstance(value, str)
    ]
    joined = "\n".join(texts)
    for number in pool:
        assert number not in joined, "в выдаче настоящий номер договора"
    for contract in inputs.contracts:
        assert contract.contract not in joined, "в выдаче псевдоним договора"
    assert "Прогноз" not in joined, "в выдаче номер прогнозной строки"


def test_no_keys_that_hold_the_pool_itself(payload):
    """Размеры пулов наружу идут, состав — нет."""
    for path, value in walk(payload):
        if not isinstance(value, dict):
            continue
        for key in value:
            assert key not in FORBIDDEN_KEYS, f"{path}.{key} выносит состав пула"


def test_asdict_would_leak_the_pool(inputs, distributed_config_path: Path):
    """Почему сериализатор написан руками, а не одной строкой.

    Тест держит проверку выше непустой: если бы `asdict` был безопасен, искать
    в выдаче было бы нечего. Он и правда выносит номера, и при этом теряет
    свойства — затраты, окупаемость, ROI.
    """
    from dataclasses import asdict

    plan = plan_from_config(inputs, load_config(distributed_config_path))
    dumped = asdict(plan)
    joined = "\n".join(value for _, value in walk(dumped) if isinstance(value, str))
    assert any(contract.contract in joined for contract in inputs.contracts)
    assert "costs" not in dumped["with_campaign"], "свойства asdict не включает"


def test_scenarios_carry_fields_and_properties(payload):
    """Свойства важнее полей: затраты и окупаемость живут именно в них."""
    for where in ("without", "with_campaign"):
        assert set(payload[where]) == set(SCENARIO_FIELDS)
        assert all(isinstance(payload[where][name], (int, float)) for name in SCENARIO_FIELDS)
    assert set(payload["effect"]) == set(EFFECT_FIELDS)


def test_breakeven_is_a_number_or_nothing(payload):
    """None значит «порога в диапазоне нет» — это не ноль и не ошибка."""
    for name in ("breakeven_payback", "breakeven_roi"):
        assert payload[name] is None or isinstance(payload[name], float)


def test_slices_add_up_to_the_total_in_the_payload(payload):
    """Тот же инвариант механики, но через выдачу: складывать будет страница."""
    depths = payload["depths"]
    assert len(depths) == 5
    assert sum(d["with_campaign"]["revenue"] for d in depths) == pytest.approx(
        payload["with_campaign"]["revenue"]
    )
    assert sum(d["effect"]["costs"] for d in depths) == pytest.approx(
        payload["effect"]["costs"]
    )
    assert sum(d["contracts"] for d in depths) == pytest.approx(payload["pool_size"])
    assert sum(d["forecast_contracts"] for d in depths) == pytest.approx(
        payload["forecast_size"]
    )


def test_depth_equals_actual_in_the_payload(payload):
    """Главный инвариант механики читается прямо из выдачи."""
    for depth in payload["depths"]:
        assert depth["effective_discount"] == pytest.approx(depth["depth"], abs=1e-9)
