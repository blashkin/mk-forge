"""Конфиг: допущение без объяснения не пропускается."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from mkforge.config import ConfigError, load_config


def test_loads_project_config():
    """Конфиг в репозитории должен читаться: он часть поставки."""
    config = load_config(Path("configs/example_levels.yaml"))
    assert config.product == "ДТ"
    assert len(config.targets) == 5
    assert len(config.assumptions) == 4
    assert config.share_without == 0.0 and config.share_with == 1.0


def test_loads_minimal(config_path):
    config = load_config(config_path)
    assert config.start == dt.date(2026, 9, 10)
    assert config.end == dt.date(2026, 10, 31)
    assert config.plan_participants == 30
    assert config.products_excluded == ("АБ", "СУГ")


def test_rules_get_level_and_dates(config_path):
    rules = load_config(config_path).rules_text()
    assert rules[0] == "Надбавка +1% к СТП на ДТ. Период 10.09.2026 - 31.10.2026."
    assert rules[1].endswith("31.10.2026.")


def test_assumption_without_why_is_rejected(config_path, tmp_path):
    text = config_path.read_text(encoding="utf-8").replace(
        "    почему: кого подключат, неизвестно", "    почему: ''"
    )
    config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="нет поля «почему»"):
        load_config(config_path)


def test_missing_assumption_is_rejected(config_path):
    text = config_path.read_text(encoding="utf-8").replace(
        """  маржа_новых:
    значение: взвешенная_по_календарю
    почему: следствие равномерного подключения""",
        "",
    )
    config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="не хватает допущений"):
        load_config(config_path)


def test_effect_shares_are_required(config_path):
    text = config_path.read_text(encoding="utf-8").replace("    доля_пула_с_акцией: 1", "")
    config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="доля_пула_с_акцией"):
        load_config(config_path)


def test_levels_must_be_fractions(config_path):
    """Проценты хранятся долями: 1 вместо 0.01 — почти наверняка опечатка."""
    text = config_path.read_text(encoding="utf-8").replace(
        "уровни_эффективной_скидки: [0.01, 0.03, 0.05]", "уровни_эффективной_скидки: [1, 3, 5]"
    )
    config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="долями"):
        load_config(config_path)


def test_missing_section(config_path):
    text = config_path.read_text(encoding="utf-8").replace("параметры:", "парметры:")
    config_path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="нет раздела «параметры»"):
        load_config(config_path)


def test_missing_file():
    with pytest.raises(ConfigError, match="нет конфига"):
        load_config(Path("нет-такого.yaml"))
