"""Сборка книги: реестр заданий, черновик абзаца и полный прогон."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from mkforge.core.validate import RecalculationError, find_soffice
from mkforge.task.calculate import calculate, open_workspace
from mkforge.task.jobs import Busy, Jobs, Step
from mkforge.task.narrative import paragraph

PROJECT_CONFIG = Path("configs/example_distribution.yaml")


@pytest.fixture
def state(anon_dir: Path, tmp_path: Path):
    config = tmp_path / "акция.yaml"
    shutil.copy(PROJECT_CONFIG, config)
    return open_workspace(
        inputs_dir=anon_dir,
        config_path=config,
        mapping_path=tmp_path / "mapping.json",
        work_dir=tmp_path / "рабочие",
        out_dir=tmp_path / "готовые",
    )


def wait(jobs: Jobs, job_id: str, limit: float = 600):
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        job = jobs.get(job_id)
        if job.state != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("задание не кончилось")


# --- реестр заданий: LibreOffice не нужен ------------------------------


def test_job_runs_and_reports_steps():
    jobs = Jobs()

    def work(report):
        report(Step("first", "начал", "running"))
        report(Step("first", "кончил", "done", 0.1))
        return {"ok": True}

    job = wait(jobs, jobs.start(work).id, limit=5)
    assert job.state == "done"
    assert job.result == {"ok": True}
    assert [step.text for step in job.steps] == ["кончил"], (
        "шаг с тем же именем заменяет прежний, а не добавляется второй строкой"
    )


def test_failed_job_keeps_the_message():
    jobs = Jobs()

    def work(report):
        report(Step("first", "иду", "running"))
        raise RuntimeError("не получилось")

    job = wait(jobs, jobs.start(work).id, limit=5)
    assert job.state == "failed"
    assert job.error == "не получилось"
    assert job.steps[0].state == "failed", "шаг, на котором упало, не остается идущим"


def test_only_one_job_at_a_time():
    """Два прогона писали бы в один файл и запустили бы два пересчета."""
    jobs = Jobs()
    jobs.start(lambda report: time.sleep(0.3) or {"ok": True})
    with pytest.raises(Busy):
        jobs.start(lambda report: {"ok": True})


# --- черновик абзаца ---------------------------------------------------


@pytest.fixture
def answer(state):
    return calculate(state)


def test_paragraph_has_the_numbers_a_person_needs(state, answer):
    text = paragraph(
        {"name": state.config.name, "product": state.config.product,
         "start": state.config.start.isoformat(), "end": state.config.end.isoformat()},
        answer["plan"],
        None,
        "книга.xlsx",
    )
    assert "Пример акции" in text
    assert "10.09.2026" in text and "31.10.2026" in text
    assert "окупаемость" in text.lower()
    assert "книга.xlsx" in text


def test_paragraph_never_carries_a_contract_number(state, answer, inputs=None):
    from mkforge.core.loaders import load_inputs

    loaded = load_inputs(state.inputs_dir)
    text = paragraph(
        {"name": state.config.name, "product": state.config.product,
         "start": state.config.start.isoformat(), "end": state.config.end.isoformat()},
        answer["plan"],
        {"ok": False, "formula_errors": {"#REF!": 1}, "empty_cells": [],
         "target_equals_actual": True, "depth_equals_actual": True,
         "comparisons": [{"name": "объем", "matches": False, "worst_where": "ПСЕВДОНИМ-1",
                          "compared": 20, "worst_diff": 0.2}]},
        "книга.xlsx",
    )
    assert "ПСЕВДОНИМ-1" not in text, "псевдоним из вердикта в переписку не уходит"
    for contract in loaded.contracts:
        assert contract.contract not in text
    assert "отдавать нельзя" in text


def test_paragraph_says_when_there_is_no_threshold(state, answer):
    plan = dict(answer["plan"])
    plan["breakeven_payback"] = None
    text = paragraph(
        {"name": "Акция", "product": "ДТ", "start": "2026-09-10", "end": "2026-10-31"},
        plan, None, "книга.xlsx",
    )
    assert "не пересекает" in text


# --- полный прогон -----------------------------------------------------


@pytest.mark.libreoffice
def test_full_delivery(state):
    """От параметров до книги с настоящими номерами."""
    try:
        find_soffice()
    except RecalculationError:
        pytest.skip("LibreOffice не установлен")

    from mkforge.task.deliver import deliver

    # Таблицу соответствия обезличивание положило туда же, куда смотрит задание.
    has_mapping = state.mapping_path.exists()

    steps: list[Step] = []
    result = deliver(state, {"plan_participants": 1800}, steps.append,
                     with_restore=has_mapping)

    assert result["ok"] is True, result["checks"]
    assert result["config"]["saved"] is True
    assert state.config.plan_participants == 1800
    assert Path(result["book"]["path"]).exists()
    assert result["checks"]["ok"] is True
    assert not result["checks"]["formula_errors"]
    assert "окупаемость" in result["paragraph"].lower()
    # Каждый шаг сообщается дважды: «иду» и «сделал». Склеивает их реестр заданий.
    order = list(dict.fromkeys(step.name for step in steps))
    assert order[:4] == ["save", "data", "build", "validate"]
    assert all(step.state != "failed" for step in steps)
    if has_mapping:
        assert Path(result["deliverable"]["path"]).exists()


def test_paragraph_reads_as_russian_prose(state, answer):
    """Точки в сокращениях — точки, а не запятые.

    Ловушка была настоящая: `.replace` применился к склейке соседних литералов
    целиком и съел точку в «руб.», превратив ее в запятую.
    """
    text = paragraph(
        {"name": "Акция", "product": "ДТ", "start": "2026-09-10", "end": "2026-10-31"},
        answer["plan"], None, "книга.xlsx",
    )
    assert "млн руб., дополнительная маржа" in text
    assert ",," not in text
    assert "руб,," not in text
