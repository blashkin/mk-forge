"""Корень данных: от него считаются данные, таблица соответствия, конфиги, книги и ключ.

Корень задается переменной MK_FORGE_HOME. Без нее корень — папка проекта,
найденная от кода вверх до его pyproject.toml. Текущая папка корнем не считается
никогда: запуск не из корня молча создал бы второй ключ, и псевдонимы разъехались бы.

В образе переменная задана всегда. Код там лежит рядом со своим pyproject.toml,
и поиск вверх нашел бы папку с кодом, а не том.

Корень не нашелся ни так, ни так — отказ, а не догадка.
"""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

HOME_ENV_VAR = "MK_FORGE_HOME"
PROJECT_NAME = "mk-forge"
MAPPING_FILE = Path("data") / "contracts.mapping.json"
CODE_DIR = Path(__file__).resolve().parent
# Образцы конфигов лежат рядом с кодом: в папке проекта и в образе.
SAMPLES_DIR = CODE_DIR.parent / "configs"
SAMPLE_PATTERN = "example_*.yaml"


class HomeError(Exception):
    """Корень данных не найден или задан так, что на него нельзя положиться."""


@dataclass(frozen=True)
class Home:
    """Корень данных и то, что от него считается."""

    root: Path
    source: str  # откуда взят корень — для doctor

    @property
    def inputs(self) -> Path:
        return self.root / "data" / "anon"

    @property
    def raw(self) -> Path:
        """Сырые выгрузки. Загруженные через страницу лежат здесь только до обработки."""
        return self.root / "data" / "raw"

    @property
    def mapping(self) -> Path:
        return self.root / MAPPING_FILE

    @property
    def configs(self) -> Path:
        return self.root / "configs"

    @property
    def out(self) -> Path:
        """Готовые книги."""
        return self.root / "out"

    @property
    def work(self) -> Path:
        """Рабочие копии на псевдонимах — уровнем ниже готовых."""
        return self.out / "рабочие"

    def resolve(self, path: Path) -> Path:
        """Путь из командной строки: абсолютный как есть, относительный — от корня."""
        path = path.expanduser()
        return path if path.is_absolute() else self.root / path


def find_home(environ: Mapping[str, str] | None = None, code_dir: Path = CODE_DIR) -> Home:
    """Найти корень данных. Не нашелся — HomeError."""
    environ = os.environ if environ is None else environ
    if HOME_ENV_VAR in environ:
        return _from_variable(environ[HOME_ENV_VAR])
    return _from_project(code_dir)


def _from_variable(value: str) -> Home:
    # Пустая переменная — не «не задана»: в образе это означало бы молча уйти
    # в папку с кодом вместо тома.
    if not value.strip():
        raise HomeError(f"{HOME_ENV_VAR} задана пустой")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise HomeError(
            f"{HOME_ENV_VAR}={value}: нужен абсолютный путь, "
            f"относительный считался бы от текущей папки"
        )
    if not path.is_dir():
        raise HomeError(f"{HOME_ENV_VAR} указывает на {path}, такой папки нет")
    return Home(root=path.resolve(), source=f"из переменной {HOME_ENV_VAR}")


def _from_project(code_dir: Path) -> Home:
    for folder in (code_dir, *code_dir.parents):
        project = folder / "pyproject.toml"
        if not project.is_file():
            continue
        # Ближайший pyproject.toml обязан быть нашим: чужой проект вокруг
        # установленного пакета корнем данных не станет.
        try:
            name = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["name"]
        except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError):
            name = None
        if name != PROJECT_NAME:
            raise HomeError(
                f"ближайший к коду {project} — не от {PROJECT_NAME}; "
                f"задай корень данных в {HOME_ENV_VAR}"
            )
        return Home(root=folder, source="папка проекта")
    raise HomeError(
        f"{HOME_ENV_VAR} не задана, а над кодом ({code_dir}) нет pyproject.toml "
        f"проекта; задай корень данных в {HOME_ENV_VAR}"
    )


def seed_configs(home: Home, samples: Path = SAMPLES_DIR) -> list[Path]:
    """Положить образцы конфигов в корень, где нет ни одного конфига.

    В образе корень — том, а образцы лежат рядом с кодом. Копируются они один раз,
    при первом старте, дальше конфиги правит страница: копируй их при каждом старте,
    обновление образа стирало бы параметры. Берутся только образцы: в папке проекта
    рядом с ними лежат настоящие конфиги.
    """
    if any(home.configs.glob("*.yaml")) or not samples.is_dir():
        return []
    home.configs.mkdir(parents=True, exist_ok=True)
    copied = []
    for sample in sorted(samples.glob(SAMPLE_PATTERN)):
        target = home.configs / sample.name
        shutil.copyfile(sample, target)
        copied.append(target)
    return copied
