"""Таблица отделений формой: отделения из выгрузки, регионы из прогноза маржи."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from conftest import BRANCH_REGIONS

from mkforge.core.loaders import BRANCHES_FILE, MARGIN_FILE, check, load_inputs
from mkforge.task.branches import describe, save


@pytest.fixture
def inputs(anon_dir: Path, tmp_path: Path) -> Path:
    """Обработанная выгрузка без таблицы отделений."""
    folder = tmp_path / "без таблицы"
    shutil.copytree(anon_dir, folder)
    (folder / BRANCHES_FILE).unlink()
    return folder


def table(folder: Path) -> str:
    return (folder / BRANCHES_FILE).read_text(encoding="utf-8")


def test_nothing_to_describe_before_upload(tmp_path: Path):
    assert describe(tmp_path)["ok"] is False


def test_branches_come_from_transactions_and_regions_from_forecast(inputs: Path):
    described = describe(inputs)
    assert described["ok"] is True
    assert [row["branch"] for row in described["branches"]] == sorted(BRANCH_REGIONS)
    assert described["regions"] == sorted(set(BRANCH_REGIONS.values()))
    assert described["missing"] == sorted(BRANCH_REGIONS)
    assert all(row["region"] is None for row in described["branches"]), (
        "по названию пары не подбираются"
    )


def test_saved_table_makes_the_data_whole(inputs: Path):
    answer = save(inputs, dict(BRANCH_REGIONS))
    assert answer == {"ok": True, "errors": [], "saved": len(BRANCH_REGIONS)}
    assert check(load_inputs(inputs)).ok
    assert describe(inputs)["missing"] == []


def test_region_outside_the_forecast_is_refused_and_nothing_written(inputs: Path):
    answer = save(inputs, {"Отделение А": "Регион, которого нет"})
    assert answer["ok"] is False
    assert answer["errors"][0]["branch"] == "Отделение А"
    assert not (inputs / BRANCHES_FILE).exists()


def test_branch_outside_the_export_is_refused(inputs: Path):
    answer = save(inputs, {"Отделение Я": "Регион маржи А"})
    assert answer["ok"] is False and "нет" in answer["errors"][0]["message"]


def test_rows_outside_the_export_survive_and_blank_choice_is_not_written(inputs: Path):
    (inputs / BRANCHES_FILE).write_text(
        "отделение,регион\nОтделение прошлой выгрузки,Регион маржи В\n", encoding="utf-8"
    )
    save(inputs, {"Отделение А": "Регион маржи А", "Отделение Б": ""})
    text = table(inputs)
    assert "Отделение прошлой выгрузки,Регион маржи В" in text
    assert "Отделение А,Регион маржи А" in text
    assert "Отделение Б" not in text


def test_recorded_region_missing_from_new_forecast_is_shown(inputs: Path):
    (inputs / BRANCHES_FILE).write_text(
        "отделение,регион\nОтделение А,Регион маржи А\n", encoding="utf-8"
    )
    margin = inputs / MARGIN_FILE
    margin.write_text(margin.read_text(encoding="utf-8").replace("Регион маржи А", "Регион маржи Я"),
                      encoding="utf-8")
    row = next(row for row in describe(inputs)["branches"] if row["branch"] == "Отделение А")
    assert row == {"branch": "Отделение А", "region": "Регион маржи А", "known": False}
