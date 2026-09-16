"""Сохранение параметров в конфиг: пишется только измененное."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from mkforge.task.calculate import calculate, open_workspace
from mkforge.task.persist import preview, save

PROJECT_CONFIG = Path("configs/example_distribution.yaml")


@pytest.fixture
def state(anon_dir: Path, tmp_path: Path):
    """Рабочая копия конфига проекта: в нем есть комментарии и лишние ключи."""
    config = tmp_path / "акция.yaml"
    shutil.copy(PROJECT_CONFIG, config)
    return open_workspace(
        inputs_dir=anon_dir,
        config_path=config,
        mapping_path=tmp_path / "mapping.json",
        work_dir=tmp_path / "рабочие",
        out_dir=tmp_path / "готовые",
    )


def test_preview_lists_only_what_changed(state):
    shown = preview(state, {"plan_participants": 1800})
    assert shown["ok"] is True
    assert shown["changed"] == ["План участников, всего"]
    assert "1800" in shown["diff"]


def test_preview_writes_nothing(state):
    before = state.config_path.read_text(encoding="utf-8")
    preview(state, {"plan_participants": 1800})
    assert state.config_path.read_text(encoding="utf-8") == before


def test_nothing_to_save(state):
    answer = save(state)
    assert answer["saved"] is False
    assert "нечего" in answer["message"]


def test_bad_input_is_refused_before_touching_the_file(state):
    before = state.config_path.read_text(encoding="utf-8")
    answer = save(state, {"distribution": [{"depth": 0.05, "share": 0.4}]})
    assert answer["ok"] is False
    assert answer["errors"][0]["field"] == "distribution"
    assert state.config_path.read_text(encoding="utf-8") == before


def test_save_writes_and_rereads(state):
    answer = save(state, {"plan_participants": 1800, "share_without": 0.25})
    assert answer["saved"] is True
    assert state.config.plan_participants == 1800
    assert state.config.share_without == 0.25
    written = yaml.safe_load(state.config_path.read_text(encoding="utf-8"))
    assert written["параметры"]["план_участников"] == 1800


def test_saved_file_keeps_comments_and_unknown_keys(state):
    before = state.config_path.read_text(encoding="utf-8")
    save(state, {"plan_participants": 1800})
    after = state.config_path.read_text(encoding="utf-8")
    comments = lambda text: [
        line for line in text.splitlines() if line.lstrip().startswith("#")
    ]
    assert comments(after) == comments(before)
    written = yaml.safe_load(after)
    assert written["кампания"]["география"] and written["данные"]["транзакции"]


def test_distribution_is_saved(state):
    rows = [{"depth": 0.05, "share": 0.5}, {"depth": 0.01, "share": 0.5}]
    answer = save(state, {"distribution": rows})
    assert answer["saved"] is True
    assert [
        (share.depth, share.share) for share in state.config.distribution.shares
    ] == [(0.05, 0.5), (0.01, 0.5)]


def test_handout_is_saved_together_with_the_assumption(state):
    save(state, {"handout": "по_объему"})
    written = yaml.safe_load(state.config_path.read_text(encoding="utf-8"))
    assert written["допущения"]["раздача_скидки"]["значение"] == "по_объему"
    assert state.config.distribution.by_volume is True


def test_page_numbers_survive_the_round_trip(state):
    """После записи страница считает то же, что считала до нее.

    Это и есть смысл сохранения: файл должен стать тем, что было на экране.
    """
    before = calculate(state, {"plan_participants": 1800, "share_without": 0.2})
    save(state, {"plan_participants": 1800, "share_without": 0.2})
    after = calculate(state)
    assert after["plan"]["effect"]["payback"] == pytest.approx(
        before["plan"]["effect"]["payback"]
    )
    assert after["plan"]["forecast_size"] == before["plan"]["forecast_size"]


def test_missing_assumption_block_is_refused_not_invented(anon_dir: Path,
                                                          distributed_config_path: Path,
                                                          tmp_path: Path):
    """Целое допущение не выдумываем.

    У допущения обязательно поле «почему», без него `load_config` конфиг не
    примет. Дописать блок молча значило бы сломать файл — значит отказ, и пусть
    человек напишет причину сам.
    """
    text = distributed_config_path.read_text(encoding="utf-8")
    start = text.index("  раздача_скидки:")
    stripped = text[:start] + text[text.index("  структура_новых:"):]
    assert "раздача_скидки" not in stripped
    config = tmp_path / "без-раздачи.yaml"
    config.write_text(stripped, encoding="utf-8")

    state = open_workspace(
        inputs_dir=anon_dir,
        config_path=config,
        mapping_path=tmp_path / "mapping.json",
        work_dir=tmp_path / "рабочие",
        out_dir=tmp_path / "готовые",
    )
    before = state.config_path.read_text(encoding="utf-8")
    answer = save(state, {"handout": "вне_зависимости_от_размера"})
    assert answer["ok"] is False
    assert "раздача_скидки" in answer["errors"][0]["message"]
    assert state.config_path.read_text(encoding="utf-8") == before
