"""Обезличивание: номера не утекают, псевдонимы устойчивы, суммы не меняются."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mkforge.core.anonymize import (
    TRANSACTION_COLUMNS,
    ExportError,
    anonymize,
    pseudonym,
)


def run(export: Path, where: Path):
    return anonymize(
        source=export,
        out_dir=where / "anon",
        mapping_path=where / "mapping.json",
        root=where,
    )


def csv_text(out_dir: Path) -> str:
    """Все обезличенные csv одной строкой — чтобы искать в них следы номеров."""
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(out_dir.glob("*.csv")))


def test_real_numbers_never_leak(export, tmp_path, pool):
    result = run(export, tmp_path)
    content = csv_text(tmp_path / "anon")
    for contract in pool:
        assert contract not in content, f"номер {contract} утек в обезличенный файл"
    assert result.contracts == 20
    assert result.transactions == 40


def test_pseudonyms_are_stable(export, tmp_path):
    first = run(export, tmp_path / "one")
    second = run(export, tmp_path / "two")
    assert (tmp_path / "one/anon/contracts.csv").read_text(encoding="utf-8") == (
        tmp_path / "two/anon/contracts.csv"
    ).read_text(encoding="utf-8")
    assert first.totals == second.totals


def test_different_keys_give_different_pseudonyms():
    assert pseudonym("АА100000001", b"\x01" * 32) != pseudonym("АА100000001", b"\x02" * 32)


def test_extra_columns_dropped(export, tmp_path):
    result = run(export, tmp_path)
    header = (tmp_path / "anon/transactions.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.split(",") == list(TRANSACTION_COLUMNS.values())
    assert "Регион" not in header and "Ключ" not in header
    assert result.dropped_columns == 9  # 6 из транзакций + 3 из договоров


def test_totals_preserved(export, tmp_path, pool):
    """Суммы обезличенного файла должны совпадать с тем, что заложено в фикстуру."""
    from tests.conftest import STIU_REVENUE, liters_for, tons_for

    result = run(export, tmp_path)
    liters = sum(liters_for(i) for i in range(len(pool)))
    assert result.totals["количество_л"] == pytest.approx(liters)
    assert result.totals["объем_т"] == pytest.approx(sum(tons_for(i) for i in range(len(pool))))
    assert result.totals["выручка_со_скидкой"] == pytest.approx(
        liters * 55.0 + len(pool) * STIU_REVENUE
    )


def test_mapping_is_reversible(export, tmp_path, pool):
    run(export, tmp_path)
    mapping = json.loads((tmp_path / "mapping.json").read_text(encoding="utf-8"))
    assert sorted(mapping.values()) == sorted(pool)
    assert len(set(mapping)) == len(pool)  # ни одной коллизии


def test_missing_required_column(export, tmp_path):
    import openpyxl

    wb = openpyxl.load_workbook(export)
    wb["Транзакции участников"]["L1"] = "Объем, тонн"  # было «Объем т»
    broken = tmp_path / "broken.xlsx"
    wb.save(broken)
    with pytest.raises(ExportError, match="Объем т"):
        run(broken, tmp_path)


def test_missing_sheet(tmp_path):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "Не то"
    empty = tmp_path / "empty.xlsx"
    wb.save(empty)
    with pytest.raises(ExportError, match="Транзакции участников"):
        run(empty, tmp_path)
