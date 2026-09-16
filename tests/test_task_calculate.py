"""Задание: открыли конфиг, поменяли поле, получили числа."""

from __future__ import annotations

from pathlib import Path

import pytest

from mkforge.task.calculate import calculate, form, open_workspace


@pytest.fixture
def state(anon_dir: Path, distributed_config_path: Path, tmp_path: Path):
    return open_workspace(
        inputs_dir=anon_dir,
        config_path=distributed_config_path,
        mapping_path=tmp_path / "mapping.json",
        work_dir=tmp_path / "рабочие",
        out_dir=tmp_path / "готовые",
    )


def test_form_describes_every_field_with_its_value(state):
    described = form(state)
    assert {field["name"] for field in described["fields"]}
    for field in described["fields"]:
        assert field["label"] and field["kind"]
        assert "value" in field
    sections = {section["key"] for section in described["sections"]}
    assert all(field["section"] in sections for field in described["fields"])
    assert described["campaign"]["product"] == "ДТ"
    assert isinstance(described["soffice"], bool)


def test_calculate_without_overrides(state):
    answer = calculate(state)
    assert answer["ok"] is True
    assert answer["plan"]["pool_size"] > 0
    assert set(answer["charts"]) == {"payback", "money", "groups"}


def test_bad_input_is_an_answer_not_a_crash(state):
    answer = calculate(state, {"distribution": [{"depth": 0.05, "share": 0.4}]})
    assert answer["ok"] is False
    assert answer["plan"] is None
    assert answer["errors"][0]["field"] == "distribution"


def test_changing_the_share_changes_the_payback(state):
    low = calculate(state, {"share_without": 0.0})
    high = calculate(state, {"share_without": 0.5})
    assert low["plan"]["effect"]["payback"] > high["plan"]["effect"]["payback"]


def test_the_curve_is_cached_across_shares(state, monkeypatch):
    """Главный рычаг должен ходить бесплатно: кривая от него не зависит.

    Считаем вызовы, а не время: тест на секунды однажды мигнет на чужой машине.
    """
    from mkforge.task import calculate as module

    calls = []
    original = module.charts.payback_curve

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module.charts, "payback_curve", counted)

    first = calculate(state, {"share_without": 0.0})
    cached = calculate(state, {"share_without": 0.3})
    assert len(calls) == 1, "кривую пересчитали из-за доли, от которой она не зависит"
    assert [point["payback"] for point in cached["charts"]["payback"]["points"]] == [
        point["payback"] for point in first["charts"]["payback"]["points"]
    ]
    assert cached["charts"]["payback"]["current_share"] == 0.3


def test_changing_the_distribution_drops_the_cache(state):
    before = calculate(state)
    after = calculate(
        state,
        {"distribution": [{"depth": 0.01, "share": 1.0}]},
    )
    assert after["ok"] is True
    assert [point["payback"] for point in after["charts"]["payback"]["points"]] != [
        point["payback"] for point in before["charts"]["payback"]["points"]
    ]


def test_config_without_a_distribution_says_so(anon_dir: Path, config_path: Path,
                                               tmp_path: Path):
    """Единственный путь, которым страница может встретить конфиг без раздела 6."""
    state = open_workspace(
        inputs_dir=anon_dir,
        config_path=config_path,
        mapping_path=tmp_path / "mapping.json",
        work_dir=tmp_path / "рабочие",
        out_dir=tmp_path / "готовые",
    )
    answer = calculate(state)
    assert answer["ok"] is False
    assert answer["errors"][0]["field"] == "distribution"
    assert "распределение" in answer["errors"][0]["message"]
