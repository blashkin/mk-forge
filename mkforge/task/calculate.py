"""Задание целиком: на входе конфиг и поля формы, на выходе числа.

Данные читаются один раз при открытии и живут в памяти: `Inputs` неизменяем,
ни одна расчетная функция его не трогает, а полный пересчет плана стоит около
десяти миллисекунд. Поэтому числа могут меняться во время набора, и кнопка
«посчитать» не нужна.

Единственное, что стоит заметно дороже, — кривая окупаемости: это два десятка
пересчетов. Она кэшируется по всему конфигу, кроме доли объема без акции: от
этой доли кривая не зависит, доля двигает только отметку «сейчас». Значит
главный рычаг страницы ходит бесплатно.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from mkforge.campaigns.motivational import plan_from_config
from mkforge.config import CampaignConfig, load_config
from mkforge.core.loaders import INPUT_FILES, check, load_inputs
from mkforge.core.models import Inputs, ModelError
from mkforge.task import charts
from mkforge.task.fields import FIELDS, SECTIONS, values
from mkforge.task.overrides import FieldError, apply
from mkforge.task.serialize import plan_payload

NO_DISTRIBUTION = (
    "в конфиге не задано распределение глубины скидки — "
    "добавьте хотя бы одну строку «глубина — доля»"
)


@dataclass
class Workspace:
    """Что страница держит открытым: данные, конфиг и куда класть книги."""

    inputs: Inputs
    inputs_dir: Path
    config: CampaignConfig
    config_path: Path
    mapping_path: Path
    work_dir: Path
    out_dir: Path
    _curve: dict = field(default_factory=dict, repr=False)

    def reload_config(self) -> None:
        """Перечитать конфиг с диска. Вызывается после сохранения.

        Перечитываем именно файл, а не доверяем тому, что было в памяти: если
        редактор yaml применил правку не буквально, расхождение вскроется здесь,
        а не в книге через десять минут.
        """
        self.config = load_config(self.config_path)
        self._curve.clear()


def open_workspace(
    inputs_dir: Path,
    config_path: Path,
    mapping_path: Path,
    work_dir: Path,
    out_dir: Path,
) -> Workspace:
    return Workspace(
        inputs=load_inputs(inputs_dir),
        inputs_dir=inputs_dir,
        config=load_config(config_path),
        config_path=config_path,
        mapping_path=mapping_path,
        work_dir=work_dir,
        out_dir=out_dir,
    )


@dataclass(frozen=True)
class Waiting:
    """Считать не по чему: данных нет или они не годятся.

    Страница при этом открывается и предлагает загрузить выгрузку, а не отказывает:
    в контейнере с перезапуском отказ означал бы процесс, который падает по кругу.
    """

    inputs_dir: Path
    config_path: Path
    missing: tuple[str, ...] = ()   # каких файлов нет
    problems: tuple[str, ...] = ()  # что не так с теми, что есть

    def payload(self) -> dict:
        return {
            "inputs_dir": str(self.inputs_dir),
            "config_path": str(self.config_path),
            "missing": list(self.missing),
            "problems": list(self.problems),
        }


def open_page(
    inputs_dir: Path,
    config_path: Path,
    mapping_path: Path,
    work_dir: Path,
    out_dir: Path,
) -> Workspace | Waiting:
    """Открыть задание, а если считать не по чему — сказать, чего не хватает.

    Сломанный конфиг — по-прежнему отказ: его выбирает тот, кто запускает страницу,
    а не тот, кто на нее смотрит.
    """
    config = load_config(config_path)
    missing = tuple(name for name in INPUT_FILES if not (inputs_dir / name).exists())
    if missing:
        return Waiting(inputs_dir, config_path, missing=missing)
    try:
        inputs = load_inputs(inputs_dir)
    except (ModelError, ValueError, csv.Error) as error:
        return Waiting(inputs_dir, config_path, problems=(str(error),))
    report = check(inputs)
    if not report.ok:
        return Waiting(inputs_dir, config_path, problems=tuple(report.errors))
    return Workspace(
        inputs=inputs,
        inputs_dir=inputs_dir,
        config=config,
        config_path=config_path,
        mapping_path=mapping_path,
        work_dir=work_dir,
        out_dir=out_dir,
    )


def soffice_found() -> bool:
    """Есть ли LibreOffice. Сказать об этом надо при открытии страницы.

    Без него сборка книги дойдет до пересчета и остановится. Узнать об этом
    в начале работы и через десять минут ожидания — разные вещи.
    """
    from mkforge.core.validate import RecalculationError, find_soffice

    try:
        find_soffice()
    except RecalculationError:
        return False
    return True


def form(state: Workspace) -> dict:
    """Описание формы и текущие значения — все, что нужно для отрисовки."""
    current = values(state.config)
    return {
        "sections": [{"key": key, "title": title} for key, title in SECTIONS],
        "fields": [
            {
                "name": item.name,
                "kind": item.kind,
                "label": item.label,
                "hint": item.hint,
                "section": item.section,
                "low": item.low,
                "high": item.high,
                "step": item.step,
                "options": [
                    {"value": value, "label": label} for value, label in item.options
                ],
                "value": current[item.name],
            }
            for item in FIELDS
        ],
        "campaign": {
            "name": state.config.name,
            "product": state.config.product,
            "mechanic": state.config.mechanic,
        },
        "config_path": str(state.config_path),
        "inputs_dir": str(state.inputs_dir),
        "soffice": soffice_found(),
    }


def _curve(state: Workspace, config: CampaignConfig, plan) -> dict:
    """Кривая с кэшем по конфигу без доли объема без акции."""
    key = replace(config, share_without=0.0)
    cached = state._curve.get(key)
    if cached is None:
        cached = charts.payback_curve(state.inputs, config, plan)
        state._curve.clear()
        state._curve[key] = cached
    return {
        **cached,
        # Отметка «сейчас» зависит от доли, кривая — нет.
        "current_share": config.share_without,
    }


def calculate(state: Workspace, overrides: Mapping[str, Any] | None = None) -> dict:
    """Посчитать акцию по конфигу с наложенными полями формы.

    На пользовательском вводе не бросает никогда: неверное поле — это ответ
    со списком ошибок, а не сбой. Страница в этом случае оставляет на экране
    прошлые числа приглушенными: терять контекст на полуслове незачем.
    """
    started = time.monotonic()
    config, errors = apply(state.config, overrides or {})
    if config is None:
        return _failed(errors, started)

    try:
        plan = plan_from_config(state.inputs, config)
    except ValueError:
        return _failed([FieldError("distribution", NO_DISTRIBUTION)], started)

    return {
        "ok": True,
        "errors": [],
        "campaign": {
            "name": config.name,
            "product": config.product,
            "start": config.start.isoformat(),
            "end": config.end.isoformat(),
        },
        "plan": plan_payload(plan),
        "charts": {
            "payback": _curve(state, config, plan),
            "money": charts.money_breakdown(plan),
            "groups": charts.depth_groups(plan),
        },
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


def _failed(errors: list[FieldError], started: float) -> dict:
    return {
        "ok": False,
        "errors": [error.payload() for error in errors],
        "campaign": None,
        "plan": None,
        "charts": None,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }
