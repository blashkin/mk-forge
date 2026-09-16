"""Проверка окружения: что найдено, что готово, чего не хватает.

Нужна, чтобы не выяснять состояние по падению другой команды. Ничего не меняет
и ничего не спрашивает — только смотрит и рассказывает.

Ключ обезличивания не печатается: сообщается лишь, задан он или нет.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from mkforge.config import ConfigError, load_config
from mkforge.core.anonymize import KEY_ENV_VAR
from mkforge.core.loaders import (
    BRANCHES_FILE,
    CONTRACTS_FILE,
    ECONOMICS_FILE,
    MARGIN_FILE,
    SCALE_FILE,
    TRANSACTIONS_FILE,
)
from mkforge.core.validate import SOFFICE_ENV, RecalculationError, find_soffice

VERSION_TIMEOUT = 60


@dataclass
class Check:
    """Одна строка отчета."""

    name: str
    ok: bool
    detail: str = ""

    def line(self) -> str:
        mark = "+" if self.ok else "-"
        tail = f"  {self.detail}" if self.detail else ""
        return f"  {mark} {self.name}:{tail}"


@dataclass
class DoctorReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def can_validate(self) -> bool:
        """Хватает ли окружения, чтобы пересчитать и проверить книгу."""
        return all(c.ok for c in self.checks if c.name in REQUIRED_FOR_VALIDATE)

    def report(self) -> str:
        lines = ["окружение mk-forge:"] + [check.line() for check in self.checks]
        if self.can_validate:
            lines.append("пересчет и проверка книги доступны")
        else:
            lines.append(
                f"пересчет книги недоступен: поставь LibreOffice "
                f"или укажи путь в {SOFFICE_ENV}"
            )
        return "\n".join(lines)


REQUIRED_FOR_VALIDATE = ("LibreOffice",)


def _soffice_version(soffice: Path) -> str:
    """Версия LibreOffice. Если спросить не удалось, это не повод падать."""
    try:
        result = subprocess.run(
            [str(soffice), "--version"],
            capture_output=True,
            text=True,
            timeout=VERSION_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or "").strip().splitlines()[0] if result.stdout else ""


def _check_soffice() -> Check:
    try:
        soffice = find_soffice()
    except RecalculationError as error:
        return Check("LibreOffice", ok=False, detail=str(error))
    version = _soffice_version(soffice)
    detail = f"{soffice}" + (f", {version}" if version else "")
    return Check("LibreOffice", ok=True, detail=detail)


def _check_inputs(inputs_dir: Path) -> list[Check]:
    expected = (TRANSACTIONS_FILE, CONTRACTS_FILE, SCALE_FILE, ECONOMICS_FILE, MARGIN_FILE)
    found = [name for name in expected if (inputs_dir / name).exists()]
    missing = [name for name in expected if name not in found]
    detail = f"{inputs_dir}, файлов {len(found)} из {len(expected)}"
    if missing:
        detail += f"; не хватает {', '.join(missing)} — запусти mk-forge prepare"

    # Таблицу отделений prepare не создает, поэтому и совет к ней другой.
    branches = inputs_dir / BRANCHES_FILE
    if branches.exists():
        table = Check("Таблица отделений", ok=True, detail=str(branches))
    else:
        table = Check(
            "Таблица отделений",
            ok=False,
            detail=f"нет {branches} — ее ведут руками, prepare ее не создает; "
            f"колонки «отделение» и «регион»",
        )
    return [Check("Обезличенные данные", ok=not missing, detail=detail), table]


def _check_key(root: Path) -> Check:
    """Задан ли ключ обезличивания. Сам ключ не печатается."""
    import os

    if os.environ.get(KEY_ENV_VAR):
        return Check("Ключ обезличивания", ok=True, detail=f"из переменной {KEY_ENV_VAR}")
    env = root / ".env"
    if env.exists() and KEY_ENV_VAR in env.read_text(encoding="utf-8"):
        return Check("Ключ обезличивания", ok=True, detail=f"в {env.name}, не печатается")
    return Check(
        "Ключ обезличивания",
        ok=False,
        detail="не задан — создастся при первом mk-forge prepare",
    )


def _check_config(path: Path) -> Check:
    try:
        config = load_config(path)
    except ConfigError as error:
        return Check("Конфиг акции", ok=False, detail=str(error))
    return Check(
        "Конфиг акции",
        ok=True,
        detail=f"{path.name}: {config.product}, уровней {len(config.targets)}, "
        f"допущений {len(config.assumptions)}",
    )


def diagnose(
    inputs_dir: Path, config_path: Path, mapping_path: Path, root: Path | None = None
) -> DoctorReport:
    """Собрать отчет об окружении."""
    root = root or Path.cwd()
    report = DoctorReport()
    report.checks.append(
        Check("Python", ok=True, detail=".".join(str(p) for p in sys.version_info[:3]))
    )
    report.checks.append(_check_soffice())
    report.checks.extend(_check_inputs(inputs_dir))
    report.checks.append(
        Check(
            "Таблица соответствия",
            ok=mapping_path.exists(),
            detail=(
                str(mapping_path)
                if mapping_path.exists()
                else f"{mapping_path} — нет, создастся при mk-forge prepare"
            ),
        )
    )
    report.checks.append(_check_key(root))
    report.checks.append(_check_config(config_path))
    return report
