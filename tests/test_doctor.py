"""Проверка окружения: отчет должен быть честным и не печатать ключ."""

from __future__ import annotations

from pathlib import Path

import pytest

from mkforge.core.anonymize import KEY_ENV_VAR
from mkforge.core.validate import SOFFICE_ENV
from mkforge.doctor import diagnose


def names(report) -> dict[str, bool]:
    return {check.name: check.ok for check in report.checks}


def test_full_environment_is_reported(anon_dir: Path, config_path: Path, tmp_path: Path):
    report = diagnose(
        inputs_dir=anon_dir,
        config_path=config_path,
        mapping_path=tmp_path / "mapping.json",
        root=tmp_path,
    )
    checks = names(report)
    assert checks["Обезличенные данные"]
    assert checks["Таблица отделений"]
    assert checks["Таблица соответствия"]
    assert checks["Конфиг акции"]
    assert checks["Python"]


def test_missing_inputs_name_the_command(config_path: Path, tmp_path: Path):
    report = diagnose(
        inputs_dir=tmp_path / "пусто",
        config_path=config_path,
        mapping_path=tmp_path / "нет.json",
        root=tmp_path,
    )
    assert not names(report)["Обезличенные данные"]
    assert "mk-forge prepare" in report.report()


def test_missing_branch_table_is_not_blamed_on_prepare(
    anon_dir: Path, config_path: Path, tmp_path: Path
):
    (anon_dir / "branch_regions.csv").unlink()
    report = diagnose(
        inputs_dir=anon_dir,
        config_path=config_path,
        mapping_path=tmp_path / "mapping.json",
        root=tmp_path,
    )
    checks = names(report)
    assert checks["Обезличенные данные"]
    assert not checks["Таблица отделений"]
    assert "ведут руками" in report.report()


def test_broken_config_is_reported(anon_dir: Path, tmp_path: Path):
    report = diagnose(
        inputs_dir=anon_dir,
        config_path=tmp_path / "нет.yaml",
        mapping_path=tmp_path / "mapping.json",
        root=tmp_path,
    )
    assert not names(report)["Конфиг акции"]
    assert "нет конфига" in report.report()


def test_key_is_never_printed(anon_dir: Path, config_path: Path, tmp_path: Path, monkeypatch):
    """Отчет говорит, что ключ задан, но не показывает его."""
    secret = "ab" * 32
    monkeypatch.setenv(KEY_ENV_VAR, secret)
    report = diagnose(
        inputs_dir=anon_dir,
        config_path=config_path,
        mapping_path=tmp_path / "mapping.json",
        root=tmp_path,
    )
    assert names(report)["Ключ обезличивания"]
    assert secret not in report.report()


def test_key_from_env_file_is_found(anon_dir: Path, config_path: Path, tmp_path: Path, monkeypatch):
    monkeypatch.delenv(KEY_ENV_VAR, raising=False)
    (tmp_path / ".env").write_text(f"{KEY_ENV_VAR}=00\n", encoding="utf-8")
    report = diagnose(
        inputs_dir=anon_dir,
        config_path=config_path,
        mapping_path=tmp_path / "mapping.json",
        root=tmp_path,
    )
    assert names(report)["Ключ обезличивания"]
    assert "00" not in report.report().split("Ключ обезличивания")[1].split("\n")[0]


def test_missing_key_is_not_a_blocker(anon_dir: Path, config_path: Path, tmp_path: Path, monkeypatch):
    """Ключ создастся сам при подготовке данных, это не повод пугать."""
    monkeypatch.delenv(KEY_ENV_VAR, raising=False)
    report = diagnose(
        inputs_dir=anon_dir,
        config_path=config_path,
        mapping_path=tmp_path / "mapping.json",
        root=tmp_path / "чисто",
    )
    assert not names(report)["Ключ обезличивания"]
    assert "создастся" in report.report()


def test_missing_libreoffice_blocks_validation(
    anon_dir: Path, config_path: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.setenv(SOFFICE_ENV, str(tmp_path / "нет-такого"))
    report = diagnose(
        inputs_dir=anon_dir,
        config_path=config_path,
        mapping_path=tmp_path / "mapping.json",
        root=tmp_path,
    )
    assert not names(report)["LibreOffice"]
    assert not report.can_validate
    assert SOFFICE_ENV in report.report()


@pytest.mark.libreoffice
def test_found_libreoffice_enables_validation(
    anon_dir: Path, config_path: Path, tmp_path: Path, monkeypatch
):
    monkeypatch.delenv(SOFFICE_ENV, raising=False)
    report = diagnose(
        inputs_dir=anon_dir,
        config_path=config_path,
        mapping_path=tmp_path / "mapping.json",
        root=tmp_path,
    )
    if not names(report)["LibreOffice"]:
        pytest.skip("LibreOffice не установлен")
    assert report.can_validate
    assert "доступны" in report.report()
