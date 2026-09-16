"""Сохранение параметров страницы обратно в конфиг.

Правится только то, что человек действительно изменил. Не из экономии: если
писать все поля подряд, диф раздуется форматированием чисел, и в нем утонет
единственная строка, которую меняли. А диф здесь показывают до записи —
это последняя возможность сказать «нет».

Книга собирается потом из файла, а не из того, что в памяти: иначе появился бы
файл, который нельзя воспроизвести из конфига.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from mkforge.config import CampaignConfig
from mkforge.config_edit import Edit, EditError, apply_edits, diff, save as write
from mkforge.config_edit import set_depth_distribution
from mkforge.task.calculate import Workspace
from mkforge.task.fields import BY_NAME, FIELDS, values
from mkforge.task.overrides import FieldError, apply

DISTRIBUTION = "distribution"


def changed_fields(before: CampaignConfig, after: CampaignConfig) -> list[str]:
    """Какие поля отличаются от того, что лежит в файле."""
    was, now = values(before), values(after)
    return [field.name for field in FIELDS if was[field.name] != now[field.name]]


def _rewrite(text: str, before: CampaignConfig, after: CampaignConfig) -> str:
    """Наложить изменения на текст конфига."""
    names = changed_fields(before, after)
    now = values(after)

    edits = []
    for name in names:
        if name == DISTRIBUTION:
            continue  # список строк, у него свой путь
        field = BY_NAME[name]
        value = now[name]
        if field.kind == "date":
            value = getattr(after, name)
        elif field.kind == "levels":
            value = list(value)
        edits.append(Edit(field.path, value, may_add=field.optional_in_yaml()))

    if edits:
        text = apply_edits(text, edits)
    if DISTRIBUTION in names:
        rows = [(share.depth, share.share) for share in after.distribution.shares]
        text = set_depth_distribution(text, rows, BY_NAME[DISTRIBUTION].path)
    return text


def preview(state: Workspace, overrides: Mapping[str, Any] | None = None) -> dict:
    """Что изменится в файле, если нажать «записать»."""
    config, errors = apply(state.config, overrides or {})
    if config is None:
        return _refused(errors)

    text = state.config_path.read_text(encoding="utf-8")
    try:
        updated = _rewrite(text, state.config, config)
    except EditError as error:
        return _refused([FieldError("", str(error))])

    names = changed_fields(state.config, config)
    return {
        "ok": True,
        "errors": [],
        "path": str(state.config_path),
        "changed": [BY_NAME[name].label for name in names],
        "diff": diff(text, updated, state.config_path.name),
    }


def save(state: Workspace, overrides: Mapping[str, Any] | None = None) -> dict:
    """Записать параметры в конфиг и перечитать его.

    Перечитываем обязательно: если правка легла не так, как мы думали, это
    вскроется здесь, а не в книге через десять минут.
    """
    shown = preview(state, overrides)
    if not shown["ok"]:
        return shown
    if not shown["changed"]:
        return {**shown, "saved": False, "message": "менять в конфиге нечего"}

    text = state.config_path.read_text(encoding="utf-8")
    config, _ = apply(state.config, overrides or {})
    write(Path(state.config_path), _rewrite(text, state.config, config))
    state.reload_config()
    return {**shown, "saved": True, "message": "параметры записаны в конфиг"}


def _refused(errors: list[FieldError]) -> dict:
    return {
        "ok": False,
        "errors": [error.payload() for error in errors],
        "path": "",
        "changed": [],
        "diff": "",
    }
