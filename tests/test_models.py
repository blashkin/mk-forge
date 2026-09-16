"""Модели: выбор сегмента шкалы, знак сбора, допустимость пустой разметки."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from mkforge.core.models import ModelError, StpBracket, StpScale, Transaction


def bracket(low: float, high: float, dt_rate: float) -> StpBracket:
    return StpBracket(
        сегмент=f"{low} - {high}", мин_тыс_л=low, макс_тыс_л=high,
        аб=0.0, дт=dt_rate, суг=0.0,
    )


@pytest.fixture
def scale() -> StpScale:
    return StpScale(brackets=(bracket(0, 50, 0.035), bracket(50, 120, 0.025), bracket(120, 999999, 0.01)))


def test_bracket_chosen_by_lower_bound(scale):
    """Повторяет MATCH(объем, нижние границы, 1): последний сегмент, что не выше объема."""
    assert scale.rate("ДТ", 0) == 0.035
    assert scale.rate("ДТ", 49.9) == 0.035
    assert scale.rate("ДТ", 50) == 0.025  # ровно на границе — уже следующий сегмент
    assert scale.rate("ДТ", 120) == 0.01
    assert scale.rate("ДТ", 10_000) == 0.01


def test_other_products_have_no_discount(scale):
    assert scale.rate("АБ", 50) == 0.0
    assert scale.rate("СУГ", 50) == 0.0


def test_unknown_product(scale):
    with pytest.raises(ModelError, match="вида продукта"):
        scale.rate("КЕРОСИН", 50)


def test_scale_must_ascend():
    with pytest.raises(ValidationError, match="не возрастают"):
        StpScale(brackets=(bracket(50, 120, 0.025), bracket(0, 50, 0.035)))


def test_scale_cannot_be_empty():
    with pytest.raises(ValidationError, match="пустая"):
        StpScale(brackets=())


def transaction(**overrides) -> Transaction:
    row = {
        "договор": "Д-0000000001", "сегмент": "CRT", "месяц": dt.date(2026, 8, 1),
        "вид_продукта": "ДТ", "класс_продукта": "НП", "количество_л": 1000.0,
        "объем_т": 0.845, "выручка_со_скидкой": 55_000.0,
        "сервисный_сбор": -1_100.0, "отделение": "Отделение А",
    }
    return Transaction(**(row | overrides))


def test_service_fee_is_absolute():
    """В выгрузке сбор со знаком минус, эталонная книга берет его по модулю."""
    assert transaction().raw_service_fee == -1_100.0
    assert transaction().service_fee == 1_100.0


def test_blank_markup_is_accepted_not_dropped():
    """Строку без разметки книга игнорирует; мы ее принимаем, но помечаем."""
    empty = transaction(вид_продукта=None, класс_продукта=None, отделение=None)
    assert empty.product == ""
    assert empty.branch == ""
    assert not empty.is_classified
    assert not empty.is_fuel


def test_fuel_flag():
    assert transaction().is_fuel
    assert not transaction(класс_продукта="СТиУ").is_fuel


def test_unknown_column_is_rejected():
    """Лишняя колонка в csv — признак сменившегося формата, молчать нельзя."""
    with pytest.raises(ValidationError):
        transaction(неведомая_колонка=1)
