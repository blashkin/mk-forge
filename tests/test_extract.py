"""Извлечение таблиц-параметров: шкала в долях, служебные строки не попадают."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from mkforge.core.extract import ParametersError, extract


def run(export: Path, where: Path):
    return extract(source=export, out_dir=where / "anon")


def test_scale_stops_before_helper_rows(export, tmp_path):
    result = run(export, tmp_path)
    assert result.scale_rows == 3  # «Более 0» и «Средняя скидка» не сегменты


def test_scale_percents_are_fractions(export, tmp_path):
    """В книге шкала записана числами (3.5), в csv уходит доля (0.035)."""
    import csv

    from mkforge.core.extract import SCALE_FIELDS

    run(export, tmp_path)
    with (tmp_path / "anon/stp_scale.csv").open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert tuple(reader.fieldnames) == SCALE_FIELDS
        rows = list(reader)

    assert float(rows[0]["дт"]) == 0.035
    assert float(rows[0]["мин_тыс_л"]) == 0
    assert float(rows[-1]["дт"]) == 0.01
    assert float(rows[-1]["макс_тыс_л"]) == 999999
    # Трассовых ставок в книге нет, они приходят только из уведомления.
    assert all(float(row["дт_трасса"]) == 0.0 for row in rows)


def test_economics_keeps_fractions_as_is(export, tmp_path):
    result = run(export, tmp_path)
    assert result.economics_rows == 7
    text = (tmp_path / "anon/product_economics.csv").read_text(encoding="utf-8")
    assert "0.021" in text  # ставка сбора осталась долей
    assert "75000" in text  # цена осталась рублями


def test_margin_forecast(export, tmp_path):
    from conftest import margin_forecast

    forecast = margin_forecast()
    result = run(export, tmp_path)
    assert result.margin_rows == len(forecast)
    assert result.months == sorted({month for month, _, _, _ in forecast})
    assert result.regions == sorted({region for _, _, _, region in forecast})


def test_no_parameters_sheet(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Не то"
    empty = tmp_path / "empty.xlsx"
    wb.save(empty)
    with pytest.raises(ParametersError, match="База для расчета"):
        run(empty, tmp_path)


def test_notice_without_highway_column_is_readable(export, anon_dir, tmp_path):
    """Уведомление без трассовой колонки: в csv ноль, а не пустая ячейка, и данные читаются."""
    from conftest import notice_document

    from mkforge.core.loaders import check, load_inputs

    rows = [("0 – 5", ("0,00", "0,00", "-3,50")), ("более 5", ("0,00", "0,00", "-1,00"))]
    notice = notice_document(tmp_path / "без трассы.docx", highway=False, rows=rows)
    result = extract(source=export, out_dir=anon_dir, notice=notice)

    inputs = load_inputs(anon_dir)
    assert check(inputs).ok
    assert [bracket.dt for bracket in inputs.scale.brackets] == pytest.approx([0.035, 0.01])
    assert all(bracket.dt_highway == 0.0 for bracket in inputs.scale.brackets)
    assert not inputs.scale.has_highway
    assert not any("с трассовыми ставками" in note for note in result.notes)
