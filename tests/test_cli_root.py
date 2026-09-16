"""Командная строка и корень данных: текущая папка не влияет ни на что.

Корень каждого теста — своя временная папка в MK_FORGE_HOME (conftest), поэтому
настоящие data/, out/ и .env не видны ни одному вызову.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mkforge.cli import main
from mkforge.core.anonymize import KEY_ENV_VAR
from mkforge.core.validate import SOFFICE_ENV
from mkforge.home import HOME_ENV_VAR
from tests.conftest import write_branch_regions

KEY = "11" * 32


@pytest.fixture
def home(home_in_tmp: Path, monkeypatch) -> Path:
    """Корень с ключом в .env, как на маке: переменной с ключом нет.

    Таблицу отделений prepare не создает, а без нее его итоговая проверка падает.
    """
    monkeypatch.delenv(KEY_ENV_VAR, raising=False)
    (home_in_tmp / ".env").write_text(f"{KEY_ENV_VAR}={KEY}\n", encoding="utf-8")
    write_branch_regions(folder(home_in_tmp, "data/anon"))
    return home_in_tmp


def folder(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def anon_files(home: Path) -> dict[str, str]:
    anon = home / "data" / "anon"
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(anon.glob("*.csv"))}


def test_prepare_from_any_folder_gives_the_same_pseudonyms(
    export: Path, home: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(folder(tmp_path, "одна"))
    assert main(["prepare", str(export)]) == 0
    first = anon_files(home)
    first_mapping = (home / "data" / "contracts.mapping.json").read_text(encoding="utf-8")

    monkeypatch.chdir(folder(tmp_path, "другая/глубже"))
    assert main(["prepare", str(export)]) == 0

    assert first and anon_files(home) == first
    assert (home / "data" / "contracts.mapping.json").read_text(encoding="utf-8") == first_mapping
    # Ни в одной из текущих папок не появилось ни ключа, ни данных.
    assert not list((tmp_path / "одна").iterdir())
    assert not list((tmp_path / "другая" / "глубже").iterdir())


def test_relative_arguments_count_from_the_root(
    export: Path, home: Path, tmp_path: Path, monkeypatch
):
    raw = folder(home, "data/raw")
    (raw / "выгрузка.xlsx").write_bytes(export.read_bytes())
    write_branch_regions(folder(home, "data/другое"))
    monkeypatch.chdir(folder(tmp_path, "не корень"))
    assert main(["prepare", "data/raw/выгрузка.xlsx", "--out", "data/другое"]) == 0
    assert (home / "data" / "другое" / "contracts.csv").exists()


def test_prepare_refuses_without_key_when_mapping_exists(
    export: Path, home: Path, tmp_path: Path, monkeypatch, capsys
):
    """Таблица есть, ключа нет: отказ, новый ключ не создается, ничего не пишется."""
    (home / ".env").unlink()
    mapping = folder(home, "data") / "contracts.mapping.json"
    mapping.write_text(json.dumps({"Д-0000000000": "АА1"}), encoding="utf-8")
    before = mapping.read_bytes()

    monkeypatch.chdir(folder(tmp_path, "где-то"))
    assert main(["prepare", str(export)]) == 1

    error = capsys.readouterr().err
    assert "ключ обезличивания не найден" in error
    assert str(home / ".env") in error
    assert not (home / ".env").exists()
    assert not (tmp_path / "где-то" / ".env").exists()
    assert mapping.read_bytes() == before
    assert not (home / "data" / "anon" / "contracts.csv").exists()


def test_new_mapping_path_does_not_hide_the_old_one(
    export: Path, home: Path, tmp_path: Path, monkeypatch, capsys
):
    """Ключ потерян, таблица в корне есть: prepare в другую таблицу тоже отказывает."""
    (home / ".env").unlink()
    (folder(home, "data") / "contracts.mapping.json").write_text("{}", encoding="utf-8")
    fresh = tmp_path / "новая" / "map.json"

    assert main(["prepare", str(export), "--mapping", str(fresh)]) == 1
    assert "ключ обезличивания не найден" in capsys.readouterr().err
    assert not (home / ".env").exists()
    assert not fresh.exists()


def test_first_prepare_creates_the_key_in_the_root(
    export: Path, home: Path, tmp_path: Path, monkeypatch
):
    (home / ".env").unlink()
    monkeypatch.chdir(folder(tmp_path, "где-то"))
    assert main(["prepare", str(export)]) == 0
    assert KEY_ENV_VAR in (home / ".env").read_text(encoding="utf-8")
    assert not (tmp_path / "где-то" / ".env").exists()


def test_doctor_prints_the_root(home: Path, tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv(SOFFICE_ENV, str(tmp_path / "нет-такого"))
    monkeypatch.chdir(folder(tmp_path, "где-то"))
    main(["doctor"])
    output = capsys.readouterr().out
    assert f"Корень данных:  {home.resolve()} (из переменной {HOME_ENV_VAR})" in output
    assert KEY not in output


def test_doctor_fails_only_when_the_book_cannot_be_recalculated(
    tmp_path: Path, monkeypatch, capsys
):
    """На коде возврата стоит смоук образа. Пустой корень — без данных, ключа
    и конфига — не провал; провал — только когда пересчитать книгу нечем."""
    root = folder(tmp_path, "пустой корень")
    monkeypatch.setenv(HOME_ENV_VAR, str(root))
    monkeypatch.delenv(KEY_ENV_VAR, raising=False)

    monkeypatch.setenv(SOFFICE_ENV, str(tmp_path / "нет-такого"))
    assert main(["doctor"]) == 1

    soffice = tmp_path / "soffice"
    soffice.write_text("#!/bin/sh\necho LibreOffice 9.9.9\n", encoding="utf-8")
    soffice.chmod(0o755)
    monkeypatch.setenv(SOFFICE_ENV, str(soffice))
    assert main(["doctor"]) == 0
    assert "пересчет и проверка книги доступны" in capsys.readouterr().out


def test_root_not_found_is_a_refusal(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv(HOME_ENV_VAR, "относительный")
    assert main(["doctor"]) == 1
    assert "корень данных не найден" in capsys.readouterr().err
