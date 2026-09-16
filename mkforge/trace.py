"""Строки журнала о сбоях: что упало и где, но без сообщения ошибки.

В сообщениях бывают псевдонимы договоров и числа пула, а журнал — стандартный
вывод, в контейнере он уходит в журнал Docker. Поэтому в строку идут только тип
ошибки и путь по коду: этого хватает, чтобы найти место, и ничего не выносит.
"""

from __future__ import annotations

import traceback
from pathlib import Path


def where(error: BaseException) -> str:
    """Тип ошибки и строки кода, через которые она прошла."""
    frames = " → ".join(
        f"{Path(frame.filename).name}:{frame.lineno}"
        for frame in traceback.extract_tb(error.__traceback__)
    )
    return f"{type(error).__name__} ({frames})"


def log(line: str) -> None:
    """Строка в стандартный вывод сразу, без буфера: процесс могут погасить следом."""
    print(f"  {line}", flush=True)
