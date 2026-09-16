"""Сборка книги: от параметров до файла, который можно отправить.

Порядок не случаен. Сначала параметры записываются в конфиг, потом конфиг
перечитывается с диска, и только из него собирается книга. Собирать из того,
что в памяти, было бы быстрее и привело бы к файлу, который нельзя
воспроизвести: числа есть, а из чего они — неизвестно.

Настоящие номера договоров возвращаются только если сверки сошлись. Книга,
которая не сошлась, в папку готовых не попадает вовсе: незачем держать рядом
с отправкой файл, который отдавать нельзя.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Mapping

from mkforge.campaigns.motivational import plan_from_config
from mkforge.core.loaders import check
from mkforge.core.validate import validate
from mkforge.renderers.xlsx import build
from mkforge.restore import deliverable_path, restore_numbers
from mkforge.task import persist
from mkforge.task.calculate import Workspace
from mkforge.task.jobs import Step
from mkforge.task.narrative import paragraph
from mkforge.task.serialize import (
    build_payload,
    checks_payload,
    plan_payload,
    restore_payload,
)

Report = Callable[[Step], None]


def _file_name(state: Workspace) -> str:
    """Имя книги по названию конфига: книга и конфиг должны узнаваться друг в друге."""
    return f"{state.config_path.stem}.xlsx"


def deliver(
    state: Workspace,
    overrides: Mapping[str, Any] | None = None,
    report: Report | None = None,
    with_restore: bool = True,
) -> dict:
    """Записать параметры, собрать книгу, сверить и вернуть номера."""
    say = report or (lambda step: None)

    def step(name: str, text: str, started: float, outcome: str = "done") -> None:
        say(Step(name, text, outcome, time.monotonic() - started))

    # 1. Параметры в конфиг.
    started = time.monotonic()
    say(Step("save", "сохраняю параметры в конфиг", "running"))
    saved = persist.save(state, overrides)
    if not saved["ok"]:
        step("save", "параметры не сохранить", started, "failed")
        return {"ok": False, "errors": saved["errors"], "config": saved,
                "book": None, "checks": None, "deliverable": None, "paragraph": ""}
    step(
        "save",
        "параметры записаны в конфиг" if saved.get("saved")
        else "конфиг уже содержит эти параметры",
        started,
    )

    # 2. Данные.
    started = time.monotonic()
    say(Step("data", "проверяю входные данные", "running"))
    loaded = check(state.inputs)
    if not loaded.ok:
        step("data", "входные данные не годятся", started, "failed")
        raise ValueError(loaded.report())
    step("data", "входные данные сходятся", started)

    # 3. Книга. Собирается из перечитанного конфига — persist.save его перечитал.
    started = time.monotonic()
    say(Step("build", "собираю книгу", "running"))
    book_path = Path(state.work_dir) / _file_name(state)
    built = build(inputs=state.inputs, config=state.config, path=book_path)
    plan = plan_payload(plan_from_config(state.inputs, state.config))
    step(
        "build",
        f"книга собрана, листов {len(built.sheets)} — значений в ней пока нет, "
        f"только формулы",
        started,
    )

    # 4. Пересчет и сверка. Самый долгий шаг.
    started = time.monotonic()
    say(Step("validate", "пересчитываю в LibreOffice и сверяю с ядром — это долго",
             "running"))
    verdict = validate(
        book=book_path,
        inputs=state.inputs,
        config=state.config,
        work_dir=Path(state.work_dir) / "пересчет",
    )
    checks = checks_payload(verdict)
    step(
        "validate",
        "книга сходится: ошибок в формулах нет, числа равны расчету ядра"
        if verdict.ok else "книга не сошлась — отдавать нельзя",
        started,
        "done" if verdict.ok else "failed",
    )

    # 5. Настоящие номера — только у книги, которая сошлась.
    ready = None
    if not verdict.ok:
        say(Step("restore", "настоящие номера не возвращаю: книга не сошлась",
                 "skipped"))
    elif not with_restore:
        say(Step("restore", "настоящие номера не возвращались", "skipped"))
    else:
        started = time.monotonic()
        say(Step("restore", "возвращаю настоящие номера договоров", "running"))
        restored = restore_numbers(
            book=book_path,
            mapping_path=Path(state.mapping_path),
            out=deliverable_path(book_path, Path(state.out_dir)),
        )
        ready = restore_payload(restored)
        step("restore", f"книга с настоящими номерами готова: {ready['name']}", started)

    name = (ready or build_payload(built))["name"]
    return {
        "ok": verdict.ok,
        "errors": [],
        "config": {"path": saved["path"], "changed": saved["changed"],
                   "saved": saved.get("saved", False)},
        "book": build_payload(built),
        "plan": plan,
        "checks": checks,
        "deliverable": ready,
        "paragraph": paragraph(
            {
                "name": state.config.name,
                "product": state.config.product,
                "start": state.config.start.isoformat(),
                "end": state.config.end.isoformat(),
            },
            plan,
            checks,
            name,
        ),
    }
