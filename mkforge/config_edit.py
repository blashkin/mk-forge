"""Точечная правка конфига акции. Пара к `config.py`: тот читает, этот правит.

Почему не перезапись файла словарем через `yaml.safe_dump`. В конфигах живет
половина смысла проекта: комментарии, объяснения выбора, ключи, которых загрузчик
вообще не читает («тип», «география», примечания к альтернативам). Пересборка
словарем снесла бы все это молча, и человек получил бы файл, из которого исчезли
причины его собственных решений.

Поэтому правится текст: находим строку ключа и меняем в ней только значение.
Комментарии, отступы и порядок остаются на месте, а диф выходит однострочным —
таким, который читают глазами.

Две ловушки, из-за которых код выглядит длиннее ожидаемого.

Первая: блочные скаляры. В конфигах сплошь «почему: >» с текстом вроде «Сказано
прямо: неважно, крупному или мелкому». Построчный сканер без защиты примет это
за ключ «Сказано прямо» и испортит объяснение. Тела блочных скаляров поэтому
пропускаются по отступу.

Вторая: `load_config` молча игнорирует незнакомые ключи. Значит опечатка в пути
дала бы файл, который читается по-старому, но выглядит исправленным. Поэтому
ненайденный ключ — это отказ, а не догадка: дописываем только то, что законно
могло отсутствовать, и только в уже существующий родительский блок.
"""

from __future__ import annotations

import datetime as dt
import difflib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml

# Ключ строки: отступ, необязательный маркер элемента списка, имя, значение.
_KEY = re.compile(r"^(\s*)(-\s+)?([^\s#][^:]*?):(?=\s|$)(.*)$")
# Значение, открывающее блочный скаляр: >, |, >-, |+, |2 и прочие сочетания.
_BLOCK_SCALAR = re.compile(r"^[|>][+-]?\d*$")
# Строки, которые не несут ключей.
_SAFE_BARE = re.compile(r"^[^\s#&*!\[\]{}>|%@`'\"][^#:]*$")


class EditError(Exception):
    """Ключ не найден или блок не разобрался. Правка не применяется целиком."""


@dataclass(frozen=True)
class Edit:
    """Одна правка: путь ключа и новое значение."""

    path: tuple[str | int, ...]
    value: Any
    # Можно ли дописать ключ, если его нет. По умолчанию нельзя.
    may_add: bool = False


@dataclass(frozen=True)
class Found:
    """Найденная строка ключа, разобранная на части."""

    index: int
    indent: int  # отступ самого ключа
    content_indent: int  # отступ, на котором лежат дети этого ключа
    head: str  # все до значения, включая «ключ:»
    value: str  # текст значения
    comment: str  # хвостовой комментарий вместе с решеткой
    comment_column: int  # в какой колонке он стоял


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank(line: str) -> bool:
    return not line.strip() or line.lstrip().startswith("#")


def _split_comment(text: str) -> tuple[str, str, int]:
    """Отделить хвостовой комментарий от значения.

    Решетка начинает комментарий, только если стоит вне кавычек и отделена
    пробелом: в значении вида 'скидка#1' решетка — часть текста.
    """
    quote = ""
    for position, char in enumerate(text):
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in "'\"":
            quote = char
        elif char == "#" and (position == 0 or text[position - 1] in " \t"):
            return text[:position].rstrip(), text[position:], position
    return text.rstrip(), "", len(text)


def _keys(lines: Sequence[str], start: int, stop: int, above: int):
    """Строки-ключи внутри окна, чьи дети лежат глубже `above`.

    Тела блочных скаляров пропускаются: иначе текст с двоеточием внутри
    объяснения будет принят за ключ.
    """
    index = start
    while index < min(stop, len(lines)):
        line = lines[index]
        if _is_blank(line):
            index += 1
            continue
        match = _KEY.match(line)
        if match is None:
            index += 1
            continue
        pad, marker, name, tail = match.groups()
        indent = len(pad)
        # Ключ на строке элемента списка стоит за маркером.
        key_indent = indent + len(marker or "")
        value = _split_comment(tail.strip())[0]
        if key_indent > above:
            yield index, indent, key_indent, name.strip(), value, marker is not None
        if _BLOCK_SCALAR.match(value or ""):
            index += 1
            while index < len(lines) and (
                not lines[index].strip() or _indent(lines[index]) > key_indent
            ):
                index += 1
            continue
        index += 1


def _block_end(lines: Sequence[str], start: int, above: int) -> int:
    """Где кончается блок, начавшийся после строки родителя."""
    index = start
    last = start
    while index < len(lines):
        line = lines[index]
        if not _is_blank(line):
            if _indent(line) <= above:
                break
            last = index + 1
        index += 1
    return last


def _parse(lines: Sequence[str], index: int) -> Found:
    match = _KEY.match(lines[index])
    if match is None:  # pragma: no cover — сюда приходят только найденные строки
        raise EditError(f"строка {index + 1} перестала быть ключом")
    pad, marker, name, tail = match.groups()
    head_length = len(pad) + len(marker or "") + len(name) + 1
    value, comment, column = _split_comment(lines[index][head_length:])
    return Found(
        index=index,
        indent=len(pad),
        content_indent=len(pad) + len(marker or "") + 2,
        head=lines[index][:head_length],
        value=value.strip(),
        comment=comment,
        comment_column=head_length + column,
    )


def _locate(lines: Sequence[str], path: Sequence[str | int]) -> Found | None:
    """Найти строку ключа по пути. None — если такого ключа нет."""
    start, stop, above = 0, len(lines), -1
    found: Found | None = None

    for segment in path:
        if isinstance(segment, int):
            items = [
                (index, indent)
                for index, indent, _, _, _, is_item in _keys(lines, start, stop, above)
                if is_item
            ]
            if segment >= len(items):
                return None
            index, indent = items[segment]
            next_start = items[segment + 1][0] if segment + 1 < len(items) else stop
            found = _parse(lines, index)
            start, stop, above = index, next_start, indent
            continue

        match = None
        for index, _, key_indent, name, _, _ in _keys(lines, start, stop, above):
            if name == segment:
                match = (index, key_indent)
                break
        if match is None:
            return None
        index, key_indent = match
        found = _parse(lines, index)
        start, stop, above = index + 1, _block_end(lines, index + 1, key_indent), key_indent

    return found


def _scalar(value: Any) -> str:
    """Записать значение так, как его пишут в yaml руками."""
    if isinstance(value, (list, tuple)):
        # Короткие списки в конфигах записаны в строку: [0.01, 0.02, 0.03].
        return "[" + ", ".join(_scalar(item) for item in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # repr дает кратчайшую запись, которая читается обратно тем же числом.
        return repr(value)
    text = str(value)
    if text and _SAFE_BARE.match(text) and not text.endswith(" "):
        return text
    return "'" + text.replace("'", "''") + "'"


def _same(current: str, value: Any) -> bool:
    """Значение в файле уже такое? Тогда строку не трогаем.

    Так правка не переписывает «0.30» в «0.3» без нужды: диф должен показывать
    то, что человек менял, а не то, как мы форматируем числа.
    """
    try:
        parsed = yaml.safe_load(current) if current else None
    except yaml.YAMLError:
        return False
    if isinstance(value, float) and isinstance(parsed, (int, float)):
        return float(parsed) == value
    if isinstance(value, dt.date) and isinstance(parsed, dt.date):
        return parsed == value
    return parsed == value


def _replace(lines: list[str], found: Found, value: Any) -> None:
    text = _scalar(value)
    line = f"{found.head} {text}"
    if found.comment:
        # Комментарии в конфигах выровнены по колонке. Влезаем — сохраняем ее.
        padding = max(found.comment_column - len(line), 1)
        line = line + " " * padding + found.comment
    lines[found.index] = line


def _add(lines: list[str], path: Sequence[str | int], value: Any) -> None:
    """Дописать ключ в конец существующего родительского блока."""
    if len(path) < 2 or isinstance(path[-1], int):
        raise EditError(f"не знаю, куда дописать «{'.'.join(map(str, path))}»")
    parent = _locate(lines, path[:-1])
    if parent is None:
        raise EditError(
            f"нет раздела «{'.'.join(map(str, path[:-1]))}» — ключ дописывать некуда"
        )
    end = _block_end(lines, parent.index + 1, parent.indent)
    indent = parent.content_indent
    for index in range(parent.index + 1, end):
        if not _is_blank(lines[index]):
            indent = _indent(lines[index])
            break
    lines.insert(end, f"{' ' * indent}{path[-1]}: {_scalar(value)}")


def apply_edits(text: str, edits: Sequence[Edit]) -> str:
    """Применить правки к тексту конфига. Либо все, либо ничего."""
    lines = text.splitlines()
    for edit in edits:
        found = _locate(lines, edit.path)
        if found is None:
            if not edit.may_add:
                raise EditError(
                    f"нет ключа «{'.'.join(map(str, edit.path))}» — правка не применена"
                )
            _add(lines, edit.path, edit.value)
            continue
        if _same(found.value, edit.value):
            continue
        _replace(lines, found, edit.value)
    tail = "\n" if text.endswith("\n") else ""
    return "\n".join(lines) + tail


def set_depth_distribution(
    text: str, rows: Sequence[tuple[float, float]], path: Sequence[str | int]
) -> str:
    """Записать распределение глубины скидки.

    Число строк не изменилось — правим только числа, и тогда не страдает ничего,
    включая комментарии внутри элементов. Изменилось — блок переписывается
    целиком: комментарий над ключом и его хвостовой комментарий остаются,
    а комментарии внутри элементов теряются. Это известное ограничение.
    """
    lines = text.splitlines()
    key = _locate(lines, path)
    if key is None:
        if not rows:
            return text
        lines = _fresh_block(lines, path, rows)
        tail = "\n" if text.endswith("\n") else ""
        return "\n".join(lines) + tail

    end = _block_end(lines, key.index + 1, key.indent)
    items = [
        index
        for index in range(key.index + 1, end)
        if not _is_blank(lines[index]) and lines[index].lstrip().startswith("- ")
    ]
    if len(items) == len(rows):
        edits = []
        for position, (depth, share) in enumerate(rows):
            edits.append(Edit((*path, position, "глубина"), float(depth)))
            edits.append(Edit((*path, position, "доля"), float(share)))
        return apply_edits(text, edits)

    indent = _indent(lines[items[0]]) if items else key.content_indent
    block = _render_rows(rows, indent)
    lines[key.index + 1 : end] = block
    tail = "\n" if text.endswith("\n") else ""
    return "\n".join(lines) + tail


def _fresh_block(
    lines: list[str], path: Sequence[str | int], rows: Sequence[tuple[float, float]]
) -> list[str]:
    """Создать раздел распределения там, где его не было."""
    parent = _locate(lines, path[:-1])
    if parent is None:
        raise EditError(
            f"нет раздела «{'.'.join(map(str, path[:-1]))}» — распределение класть некуда"
        )
    end = _block_end(lines, parent.index + 1, parent.indent)
    indent = parent.content_indent
    for index in range(parent.index + 1, end):
        if not _is_blank(lines[index]):
            indent = _indent(lines[index])
            break
    block = [f"{' ' * indent}{path[-1]}:", *_render_rows(rows, indent + 2)]
    lines[end:end] = block
    return lines


def _render_rows(rows: Sequence[tuple[float, float]], indent: int) -> list[str]:
    pad = " " * indent
    rendered = []
    for depth, share in rows:
        rendered.append(f"{pad}- глубина: {_scalar(float(depth))}")
        rendered.append(f"{pad}  доля: {_scalar(float(share))}")
    return rendered


def diff(before: str, after: str, name: str) -> str:
    """Что именно изменится в файле. Показывается человеку до записи."""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{name} (было)",
            tofile=f"{name} (станет)",
        )
    )


def save(path: Path, text: str) -> None:
    """Записать через временный файл: прерванная запись не рвет конфиг."""
    temporary = path.with_name(path.name + ".новый")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
