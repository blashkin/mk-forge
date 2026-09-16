"""Точечная правка конфига: меняется значение, остальное остается как было.

Главный инвариант один — после записи `load_config` дает ровно тот конфиг,
который страница считала. Остальные тесты объясняют, чем именно это ломается:
комментарии, незнакомые загрузчику ключи, блочные скаляры с двоеточием внутри.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from mkforge.config import load_config
from mkforge.config_edit import Edit, EditError, apply_edits, diff, save, set_depth_distribution

PROJECT_CONFIG = Path("configs/example_distribution.yaml")
DEPTHS = ("параметры", "распределение_глубины")


@pytest.fixture
def text() -> str:
    """Конфиг проекта: комментарии и незнакомые ключи есть только в нем."""
    return PROJECT_CONFIG.read_text(encoding="utf-8")


def reload(text: str, tmp_path: Path):
    path = tmp_path / "конфиг.yaml"
    path.write_text(text, encoding="utf-8")
    return load_config(path)


def comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.lstrip().startswith("#")]


def test_scalar_edit_changes_one_line(text):
    edited = apply_edits(text, [Edit(("параметры", "план_участников"), 1200)])
    changed = [
        (was, now)
        for was, now in zip(text.splitlines(), edited.splitlines())
        if was != now
    ]
    assert len(changed) == 1
    assert "1200" in changed[0][1]


def test_trailing_comment_survives_in_its_column(text):
    edited = apply_edits(text, [Edit(("параметры", "план_участников"), 1200)])
    line = next(
        line for line in edited.splitlines() if line.strip().startswith("план_участников")
    )
    assert "#" in line, "хвостовой комментарий потерян"
    was = next(
        line for line in text.splitlines() if line.strip().startswith("план_участников")
    )
    assert line.index("#") == was.index("#"), "комментарий уехал из своей колонки"


def test_round_trip_through_load_config(text, tmp_path):
    """Файл читается ровно в тот конфиг, которым считала страница."""
    before = reload(text, tmp_path)
    edited = apply_edits(
        text,
        [
            Edit(("параметры", "план_участников"), 1200),
            Edit(("кампания", "окончание"), dt.date(2026, 11, 30)),
            Edit(("допущения", "что_считать_эффектом", "доля_пула_без_акции"), 0.25),
        ],
    )
    after = reload(edited, tmp_path)
    assert after == replace(
        before, plan_participants=1200, end=dt.date(2026, 11, 30), share_without=0.25
    )


def test_only_touched_paths_change_in_the_structure(text):
    edited = apply_edits(text, [Edit(("параметры", "план_участников"), 1200)])
    was = yaml.safe_load(text)
    now = yaml.safe_load(edited)
    assert now["параметры"].pop("план_участников") == 1200
    assert was["параметры"].pop("план_участников") == 300
    assert was == now


def test_comments_and_unknown_keys_survive(text):
    edited = apply_edits(
        text,
        [
            Edit(("параметры", "план_участников"), 1200),
            Edit(("допущения", "подключение_новых", "значение"), "равномерно_по_дням"),
        ],
    )
    assert comment_lines(edited) == comment_lines(text)
    now = yaml.safe_load(edited)
    # Ключи, которых load_config не читает вовсе.
    assert now["кампания"]["тип"] and now["кампания"]["география"]
    assert now["данные"]["транзакции"]
    assert now["ограничения"]["трассовые_азс"]
    assert now["допущения"]["раздача_скидки"]["примечание_к_альтернативе"]


def test_block_scalar_with_a_colon_inside_is_untouched(text):
    """Прямая ловушка построчного сканера.

    В объяснении стоит «Сказано прямо: неважно, крупному или мелкому» — наивный
    поиск примет это за ключ и испортит текст, который и объясняет расчет.
    """
    edited = apply_edits(text, [Edit(("параметры", "план_участников"), 1200)])
    was = yaml.safe_load(text)["допущения"]["раздача_скидки"]["почему"]
    now = yaml.safe_load(edited)["допущения"]["раздача_скидки"]["почему"]
    assert "Сказано прямо:" in was, "текст-ловушка пропал из конфига, тест ослеп"
    assert now == was


def test_editing_a_key_inside_a_block_with_prose(text):
    """Ключ, у которого сосед — многострочное объяснение."""
    edited = apply_edits(
        text, [Edit(("допущения", "структура_новых", "смещение_к_объему"), 0.4)]
    )
    assert yaml.safe_load(edited)["допущения"]["структура_новых"]["смещение_к_объему"] == 0.4
    assert comment_lines(edited) == comment_lines(text)


def test_missing_key_is_refused(text):
    """load_config глотает незнакомые ключи, поэтому догадываться нельзя."""
    with pytest.raises(EditError) as error:
        apply_edits(text, [Edit(("параметры", "план"), 1200)])
    assert "нет ключа" in str(error.value)


def test_optional_key_is_added_to_its_section(text):
    without = "\n".join(
        line for line in text.splitlines()
        if not line.strip().startswith("смещение_к_объему")
    ) + "\n"
    assert "смещение_к_объему" not in without
    edited = apply_edits(
        without, [Edit(("допущения", "структура_новых", "смещение_к_объему"), 0.4, may_add=True)]
    )
    assert yaml.safe_load(edited)["допущения"]["структура_новых"]["смещение_к_объему"] == 0.4


def test_unchanged_value_leaves_the_line_alone(text):
    """Диф показывает то, что менял человек, а не то, как мы пишем числа."""
    edited = apply_edits(text, [Edit(("параметры", "план_участников"), 300)])
    assert edited == text


def test_edits_are_idempotent(text):
    once = apply_edits(text, [Edit(("параметры", "план_участников"), 1200)])
    twice = apply_edits(once, [Edit(("параметры", "план_участников"), 1200)])
    assert twice == once


def test_distribution_with_the_same_number_of_rows(text):
    rows = [(0.05, 0.4), (0.04, 0.25), (0.03, 0.15), (0.02, 0.15), (0.01, 0.05)]
    edited = set_depth_distribution(text, rows, DEPTHS)
    assert comment_lines(edited) == comment_lines(text)
    now = yaml.safe_load(edited)["параметры"]["распределение_глубины"]
    assert [(row["глубина"], row["доля"]) for row in now] == rows


def test_distribution_with_a_different_number_of_rows(text):
    rows = [(0.05, 0.6), (0.01, 0.4)]
    edited = set_depth_distribution(text, rows, DEPTHS)
    now = yaml.safe_load(edited)["параметры"]["распределение_глубины"]
    assert [(row["глубина"], row["доля"]) for row in now] == rows
    # Комментарий над ключом объясняет, что это за блок, и обязан выжить.
    assert "Основная масса на 4-5%" in edited
    assert yaml.safe_load(edited)["параметры"]["уровни_эффективной_скидки"]


def test_distribution_round_trips(text, tmp_path):
    rows = [(0.05, 0.6), (0.01, 0.4)]
    edited = set_depth_distribution(text, rows, DEPTHS)
    config = reload(edited, tmp_path)
    assert [
        (share.depth, share.share) for share in config.distribution.shares
    ] == rows


def test_distribution_is_created_where_there_was_none(text, tmp_path):
    without = text[: text.index("  # Сколько пула")] + text[text.index("# ----"):]
    assert "распределение_глубины" not in without
    edited = set_depth_distribution(without, [(0.05, 1.0)], DEPTHS)
    config = reload(edited, tmp_path)
    assert config.distribution is not None
    assert config.distribution.shares[0].depth == 0.05


def test_diff_is_readable(text):
    edited = apply_edits(text, [Edit(("параметры", "план_участников"), 1200)])
    shown = diff(text, edited, "конфиг.yaml")
    assert "-" in shown and "+" in shown
    assert shown.count("\n+ ") + shown.count("\n+п") <= 2


def test_save_replaces_atomically(tmp_path):
    path = tmp_path / "конфиг.yaml"
    path.write_text("кампания:\n  название: акция\n", encoding="utf-8")
    save(path, "кампания:\n  название: другая\n")
    assert "другая" in path.read_text(encoding="utf-8")
    assert list(tmp_path.iterdir()) == [path], "временный файл остался рядом"
