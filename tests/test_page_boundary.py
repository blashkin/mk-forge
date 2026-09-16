"""Граница между заданием и транспортом держится тестом, а не договоренностью.

Слой «задание» не должен знать, что его кто-то вызывает по HTTP. Запрещен и
`json`: словарь собирает задание, сериализует транспорт — иначе завтра в
задании появятся заголовки ответа, а следом и вторая реализация расчета
для второго фасада.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TASK_DIR = Path("mkforge/task")
FORBIDDEN = {"http", "http.server", "socketserver", "socket", "json", "urllib",
             "webbrowser", "mkforge.page"}


def imported(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("path", sorted(TASK_DIR.glob("*.py")), ids=lambda p: p.name)
def test_task_layer_knows_nothing_about_transport(path: Path):
    for name in imported(path):
        root = name.split(".")[0]
        assert name not in FORBIDDEN and root not in FORBIDDEN, (
            f"{path.name} импортирует «{name}» — это транспорт, ему здесь не место"
        )


def test_transport_layer_does_not_calculate():
    """Обратная сторона: сервер не считает сам, а зовет задание."""
    for path in Path("mkforge/page").glob("*.py"):
        names = imported(path)
        assert "mkforge.campaigns.motivational" not in names, (
            f"{path.name} считает акцию сам — это работа задания"
        )
        assert "mkforge.core.economics" not in names
