"""Поля формы поверх конфига: неверный ввод дает ошибку на поле, а не исключение."""

from __future__ import annotations

from pathlib import Path

import pytest

from mkforge.config import HANDOUT_BY_VOLUME, load_config
from mkforge.task.fields import BY_NAME, FIELDS, HANDOUT_ANY_SIZE, handout_of, values
from mkforge.task.overrides import apply


@pytest.fixture
def config(distributed_config_path: Path):
    return load_config(distributed_config_path)


def only_error(config, overrides) -> tuple[str, str]:
    updated, errors = apply(config, overrides)
    assert updated is None, "конфиг с неверным вводом собираться не должен"
    assert len(errors) == 1, [error.payload() for error in errors]
    return errors[0].field, errors[0].message


def test_empty_overrides_change_nothing(config):
    updated, errors = apply(config, {})
    assert not errors
    assert updated.start == config.start
    assert updated.distribution == config.distribution


def test_shares_must_add_up_to_one(config):
    rows = [{"depth": 0.05, "share": 0.5}, {"depth": 0.04, "share": 0.4}]
    field, message = only_error(config, {"distribution": rows})
    assert field == "distribution"
    assert "единицу" in message, "текст берется из ядра дословно"


def test_depths_must_not_repeat(config):
    rows = [{"depth": 0.05, "share": 0.5}, {"depth": 0.05, "share": 0.5}]
    field, message = only_error(config, {"distribution": rows})
    assert field == "distribution"
    assert "повторяются" in message


def test_depth_is_a_fraction_not_a_percent(config):
    """Классическая ошибка: 5 вместо 0.05."""
    field, message = only_error(config, {"distribution": [{"depth": 5, "share": 1.0}]})
    assert field == "distribution"
    assert "долей" in message


def test_end_before_start(config):
    field, _ = only_error(config, {"end": "2026-01-01"})
    assert field == "end"


def test_broken_date(config):
    field, message = only_error(config, {"start": "10.09.2026"})
    assert field == "start"
    assert "2026-03-01" in message, "в сообщении показан правильный вид"


def test_unknown_field_is_refused(config):
    """В отличие от load_config, который незнакомые ключи молча глотает."""
    field, message = only_error(config, {"скидка_директору": 0.1})
    assert field == "скидка_директору"
    assert "неизвестное" in message


def test_bounds_come_from_the_field_table(config):
    assert only_error(config, {"share_without": 1.4})[0] == "share_without"
    assert only_error(config, {"plan_participants": -1})[0] == "plan_participants"
    assert only_error(config, {"rate_window_months": 0})[0] == "rate_window_months"


def test_handout_switches_the_distribution_flag(config):
    updated, errors = apply(config, {"handout": HANDOUT_ANY_SIZE})
    assert not errors
    assert updated.distribution.by_volume is False
    assert handout_of(updated) == HANDOUT_ANY_SIZE

    back, errors = apply(updated, {"handout": HANDOUT_BY_VOLUME})
    assert not errors
    assert back.distribution.by_volume is True


def test_handout_switches_both_places():
    """Флаг распределения и слово в допущении обязаны ехать вместе.

    Разойдись они — витрина книги напечатала бы один способ раздачи, а раздел
    расчета посчитал бы другой. Проверяется на конфиге проекта: только там есть
    само допущение о раздаче.
    """
    config = load_config(Path("configs/example_distribution.yaml"))
    assert config.distribution.by_volume is False

    updated, errors = apply(config, {"handout": HANDOUT_BY_VOLUME})
    assert not errors
    assert updated.distribution.by_volume is True
    assert [
        assumption.value
        for assumption in updated.assumptions
        if assumption.name == "раздача_скидки"
    ] == [HANDOUT_BY_VOLUME]


def test_unknown_handout(config):
    assert only_error(config, {"handout": "как_получится"})[0] == "handout"


def test_counts_stay_integers(config):
    updated, errors = apply(config, {"plan_participants": 1200.0})
    assert not errors
    assert updated.plan_participants == 1200
    assert isinstance(updated.plan_participants, int)


def test_levels_are_fractions(config):
    assert only_error(config, {"targets": [1, 2, 3]})[0] == "targets"
    updated, errors = apply(config, {"targets": [0.01, 0.03]})
    assert not errors
    assert updated.targets == (0.01, 0.03)


def test_every_field_round_trips(config):
    """Значение, снятое с конфига, обязано лечь обратно без изменений.

    Это связывает две половины таблицы полей: чтение для формы и запись из нее.
    """
    updated, errors = apply(config, values(config))
    assert not errors, [error.payload() for error in errors]
    assert values(updated) == values(config)


def test_field_table_is_consistent():
    """Имена не повторяются, у каждого поля есть раздел из общего списка."""
    from mkforge.task.fields import SECTIONS

    names = [field.name for field in FIELDS]
    assert len(names) == len(set(names))
    sections = {key for key, _ in SECTIONS}
    assert all(field.section in sections for field in FIELDS)
    assert set(BY_NAME) == set(names)
