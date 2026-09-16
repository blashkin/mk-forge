"""Загрузка: понятная ошибка на испорченном файле, отчет о несогласованности."""

from __future__ import annotations

from pathlib import Path

import pytest

from mkforge.core.loaders import (
    BRANCHES_FILE,
    ECONOMICS_FILE,
    TRANSACTIONS_FILE,
    check,
    load_inputs,
)
from mkforge.core.models import ModelError


def test_loads_synthetic_pool(anon_dir):
    inputs = load_inputs(anon_dir)
    assert len(inputs.contracts) == 20
    assert len(inputs.transactions) == 40
    assert len(inputs.scale.brackets) == 3
    assert sorted(inputs.economics) == ["АБ", "ДТ", "НП", "СУГ"]
    assert len(inputs.fuel("ДТ")) == 20  # по одной топливной строке на договор


def test_synthetic_pool_is_consistent(anon_dir):
    report = check(load_inputs(anon_dir))
    assert report.ok
    assert report.report() == "входные данные согласованы"


def test_missing_file_names_the_command(tmp_path):
    with pytest.raises(ModelError, match="mk-forge prepare"):
        load_inputs(tmp_path / "нет-такого")


def test_broken_row_names_file_row_and_field(anon_dir):
    path = anon_dir / TRANSACTIONS_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    parts = lines[2].split(",")
    parts[6] = "не число"  # объем_т
    lines[2] = ",".join(parts)
    path.write_text("\n".join(lines), encoding="utf-8")

    with pytest.raises(ModelError, match=r"transactions\.csv, строка 3, «объем_т»"):
        load_inputs(anon_dir)


def test_missing_economics_indicator(anon_dir):
    path = anon_dir / ECONOMICS_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if "OPEX" not in line]
    path.write_text("\n".join(kept), encoding="utf-8")

    with pytest.raises(ModelError, match="не хватает показателей"):
        load_inputs(anon_dir)


def test_unknown_branch_is_an_error(anon_dir):
    path = anon_dir / TRANSACTIONS_FILE
    text = path.read_text(encoding="utf-8").replace("Отделение А", "Отделение Луна")
    path.write_text(text, encoding="utf-8")

    report = check(load_inputs(anon_dir))
    assert not report.ok
    assert any("Отделение Луна" in e for e in report.errors)
    assert any(BRANCHES_FILE in e for e in report.errors)


def test_missing_branch_table_says_it_is_kept_by_hand(anon_dir):
    """Совет «собери prepare» здесь был бы ложным: prepare таблицу не создает."""
    (anon_dir / BRANCHES_FILE).unlink()
    with pytest.raises(ModelError, match="ведут руками"):
        load_inputs(anon_dir)


def test_branch_listed_twice_is_refused(anon_dir):
    """Из двух регионов одного отделения молча выбрать один нельзя."""
    path = anon_dir / BRANCHES_FILE
    path.write_text(
        path.read_text(encoding="utf-8") + "Отделение А,Регион маржи Б\n", encoding="utf-8"
    )
    with pytest.raises(ModelError, match="дважды"):
        load_inputs(anon_dir)


def test_contract_without_transactions_is_a_warning(anon_dir):
    path = anon_dir / TRANSACTIONS_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-2]), encoding="utf-8")  # убрали оба движения договора

    report = check(load_inputs(anon_dir))
    assert report.ok  # расчет возможен
    assert any("без транзакций" in w for w in report.warnings)


def test_transaction_without_contract_is_an_error(anon_dir):
    path = anon_dir / TRANSACTIONS_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    parts = lines[1].split(",")
    parts[0] = "Д-ЧУЖОЙ0001"
    lines[1] = ",".join(parts)
    path.write_text("\n".join(lines), encoding="utf-8")

    report = check(load_inputs(anon_dir))
    assert not report.ok
    assert any("нет в пуле акции" in e for e in report.errors)


def test_blank_markup_surfaces_as_warning(anon_dir):
    path = anon_dir / TRANSACTIONS_FILE
    lines = path.read_text(encoding="utf-8").splitlines()
    parts = lines[1].split(",")
    parts[3] = parts[4] = ""  # вид и класс продукта
    parts[9] = ""  # отделение
    lines[1] = ",".join(parts)
    path.write_text("\n".join(lines), encoding="utf-8")

    report = check(load_inputs(anon_dir))
    assert report.ok
    assert any("без вида или класса продукта" in w for w in report.warnings)
    assert any("без отделения" in w for w in report.warnings)
