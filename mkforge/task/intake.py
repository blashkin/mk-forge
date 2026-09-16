"""Выгрузка через страницу: принять файлы, обработать и заменить ими данные.

Данные попадают в том только загрузкой, поэтому здесь то же, что делает
`mk-forge prepare`, но с тремя отличиями.

Файлы ложатся в отдельную скрытую папку в `data/raw`, а не рядом с тем, что там уже
лежит. Из исходников корень — папка проекта, и загрузка файла с тем же именем иначе
затерла бы сырую выгрузку, а потом удалила бы ее.

Обработка пишет во временную папку рядом с `data/anon` и заменяет старые данные
только после проверки. При ошибке остаются прежние данные и прежняя таблица
соответствия: сломанная выгрузка не должна отнимать то, по чему считали вчера.

Сырые файлы удаляются после обработки, удачной или нет. Для возврата номеров
хватает таблицы соответствия, а лежать в томе, куда никто не заглядывает,
с настоящими номерами и выручкой им незачем. Понадобится — загрузить заново.

Про HTTP модуль не знает: имя приходит раскодированным, байты — функцией чтения,
отказы уходят исключениями.
"""

from __future__ import annotations

import csv
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable

from mkforge.core.anonymize import ExportError, MissingKeyError, anonymize, hmac_key
from mkforge.core.extract import ParametersError, extract
from mkforge.core.loaders import (
    CONTRACTS_FILE,
    ECONOMICS_FILE,
    MARGIN_FILE,
    SCALE_FILE,
    TRANSACTIONS_FILE,
    check,
    load_inputs,
)
from mkforge.core.models import ModelError
from mkforge.core.notice import NoticeError
from mkforge.task.calculate import Places, Waiting, Workspace
from mkforge.task.jobs import Step

# Выгрузка на сегодня — несколько мегабайт. Запас на порядок, а бесконечно
# принимать то, что по ошибке уронили на страницу, незачем.
UPLOAD_LIMIT = 64 * 1024 * 1024
CHUNK = 1024 * 1024

EXPORT = "export"
NOTICE = "notice"
KINDS = {".xlsx": EXPORT, ".docx": NOTICE}
# xlsx и docx — zip-архивы. Переименованный файл лучше отвергнуть сразу и по-русски,
# чем через минуту получить от openpyxl «File is not a zip file».
ZIP_SIGNATURE = b"PK\x03\x04"

UPLOAD_PREFIX = ".upload-"
STAGING_PREFIX = ".anon-"
MAPPING_NAME = "contracts.mapping.json"
# Что пишет prepare. Таблицу отделений он не создает, и замена ее не трогает.
PREPARED_FILES = (TRANSACTIONS_FILE, CONTRACTS_FILE, SCALE_FILE, ECONOMICS_FILE, MARGIN_FILE)
NO_EXPORT = "выгрузки .xlsx среди загруженного нет: уведомление загружают вместе с ней"


class UploadError(Exception):
    """Файл не принят. Подкласс говорит транспорту, какой это отказ."""


class BadName(UploadError):
    """Имя не пришло, пришло некодированным или от него ничего не осталось."""


class WrongKind(UploadError):
    """Не xlsx и не docx — или только называется так."""


class TooLarge(UploadError):
    """Больше лимита загрузки."""


class Incomplete(UploadError):
    """Тело оборвалось раньше заявленной длины."""


class IntakeError(Exception):
    """Выгрузка не обработалась. Старые данные на месте."""


def file_name(given: str | None) -> str:
    """Базовое имя файла из того, что прислали.

    Браузер путь не шлет, но полагаться на это незачем: от пути остается последняя
    часть, а обратная косая черта — тоже разделитель, так пишет пути Windows.
    """
    if not given or not given.strip():
        raise BadName("не пришло имя файла")
    name = PureWindowsPath(given.strip()).name.strip()
    if not name or name in {".", ".."} or name.startswith("."):
        raise BadName("от имени файла ничего не осталось")
    if any(ord(char) < 32 for char in name):
        raise BadName("в имени файла управляющие символы")
    return name


def kind_of(name: str) -> str:
    kind = KINDS.get(Path(name).suffix.lower())
    if kind is None:
        raise WrongKind(f"«{name}» не подходит: нужна выгрузка .xlsx или уведомление .docx")
    return kind


@dataclass(frozen=True)
class Received:
    kind: str
    name: str
    size: int

    def payload(self) -> dict:
        return {"kind": self.kind, "name": self.name, "size": self.size}


@dataclass(frozen=True)
class Batch:
    """Загруженные файлы, переданные в обработку. Папку удаляет обработка."""

    folder: Path | None
    export: Path | None
    notice: Path | None

    def remove(self) -> None:
        _remove(self.folder)


class Uploads:
    """Принятые, но еще не обработанные файлы: одна выгрузка и одно уведомление.

    Файл того же вида заменяет прежний. Обработка забирает их все разом, и после
    этого здесь снова пусто — чем бы обработка ни кончилась. Отказ в любом файле
    выбрасывает и уже принятые: страница после отказа до обработки не дойдет,
    и принятое уведомление иначе лежало бы в томе до следующей загрузки.
    """

    def __init__(self, raw_dir: Path) -> None:
        self.raw_dir = raw_dir
        self._lock = threading.Lock()
        self._folder: Path | None = None
        self._files: dict[str, Path] = {}

    def sweep(self) -> int:
        """Убрать то, что осталось от процесса, убитого посреди загрузки."""
        return _sweep(self.raw_dir, UPLOAD_PREFIX)

    def receive(self, given_name: str | None, length: int, read: Callable[[int], bytes]) -> Received:
        try:
            return self._receive(given_name, length, read)
        except UploadError:
            self.discard()
            raise

    def _receive(self, given_name: str | None, length: int, read: Callable[[int], bytes]) -> Received:
        name = file_name(given_name)
        kind = kind_of(name)
        if length > UPLOAD_LIMIT:
            raise TooLarge(
                f"«{name}» больше {UPLOAD_LIMIT // (1024 * 1024)} МБ — это не похоже на выгрузку"
            )
        with self._lock:
            if self._folder is None:
                self._folder = self.raw_dir / f"{UPLOAD_PREFIX}{uuid.uuid4().hex[:12]}"
                self._folder.mkdir(parents=True)
            folder = self._folder
            previous = self._files.pop(kind, None)
        if previous is not None:
            previous.unlink(missing_ok=True)

        target = folder / name
        written = 0
        head = b""
        try:
            with target.open("wb") as file:
                while written < length:
                    chunk = read(min(CHUNK, length - written))
                    if not chunk:
                        break
                    if len(head) < len(ZIP_SIGNATURE):
                        head += chunk[: len(ZIP_SIGNATURE)]
                    file.write(chunk)
                    written += len(chunk)
            if written < length:
                raise Incomplete(f"«{name}» пришел не целиком")
            if not head.startswith(ZIP_SIGNATURE):
                raise WrongKind(f"«{name}» не похож на файл {Path(name).suffix.lower()}")
        except BaseException:
            target.unlink(missing_ok=True)
            raise

        with self._lock:
            self._files[kind] = target
        return Received(kind=kind, name=name, size=written)

    def take(self) -> Batch:
        """Забрать загруженное в обработку. Здесь после этого пусто."""
        with self._lock:
            batch = Batch(self._folder, self._files.get(EXPORT), self._files.get(NOTICE))
            self._folder = None
            self._files = {}
        return batch

    def discard(self) -> None:
        """Выбросить все принятое, не обрабатывая."""
        self.take().remove()


def _sweep(parent: Path, prefix: str) -> int:
    if not parent.is_dir():
        return 0
    stale = [path for path in parent.iterdir() if path.is_dir() and path.name.startswith(prefix)]
    for path in stale:
        _remove(path)
    return len(stale)


def _remove(folder: Path | None) -> None:
    if folder is not None:
        shutil.rmtree(folder, ignore_errors=True)


def sweep(places: Places) -> int:
    """Убрать временные папки загрузки и обработки, оставшиеся от убитого процесса.

    Обе папки создает только страница, и обе скрытые с узнаваемой приставкой:
    в `data/raw` проекта рядом лежат настоящие выгрузки, их это не касается.
    """
    return _sweep(places.raw_dir, UPLOAD_PREFIX) + _sweep(places.inputs_dir.parent, STAGING_PREFIX)


def _place(source: Path, target: Path) -> None:
    """Положить файл на место одним переименованием.

    Копия ложится рядом с целью и переименовывается в нее: так замена атомарна
    на любом диске, даже если таблица соответствия лежит не рядом с данными.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _has_highway(scale: Path) -> bool:
    with scale.open(encoding="utf-8") as file:
        return any(float(row.get("дт_трасса") or 0) > 0 for row in csv.DictReader(file))


def branches_in(inputs_dir: Path) -> int:
    """Сколько разных отделений в транзакциях — для слов на странице."""
    with (inputs_dir / TRANSACTIONS_FILE).open(encoding="utf-8") as file:
        return len({(row.get("отделение") or "").strip() for row in csv.DictReader(file)} - {""})


Report = Callable[[Step], None]


def intake(
    places: Places,
    batch: Batch,
    reopen: Callable[[], Workspace | Waiting],
    report: Report | None = None,
) -> dict:
    """Обработать загруженное и, если вышло, заменить им данные и перечитать их.

    Ошибка обработки — то, что на странице не исправить: выгрузка или уведомление
    не той формы, данные не читаются, выгрузка сама себе противоречит. Неполная
    таблица отделений ошибкой не считается: данные встают на место, а страница
    просит ее дополнить. Регионы в ней выбираются из прогноза маржи новой выгрузки.
    """
    say = report or (lambda step: None)
    staging = places.inputs_dir.parent / f"{STAGING_PREFIX}{uuid.uuid4().hex[:12]}"

    def step(name: str, text: str, started: float, outcome: str = "done") -> None:
        say(Step(name, text, outcome, time.monotonic() - started))

    if batch.export is None:
        batch.remove()
        raise IntakeError(NO_EXPORT)

    current = "read"
    started = time.monotonic()
    try:
        say(Step("read", f"обезличиваю «{batch.export.name}»", "running"))
        # Ключ сверяется с таблицей соответствия там, где страница ее держит: обработка
        # пишет новую таблицу во временную папку, и старую иначе никто бы не увидел.
        hmac_key(places.root, places.mapping_path)
        anonymized = anonymize(
            source=batch.export,
            out_dir=staging,
            mapping_path=staging / MAPPING_NAME,
            root=places.root,
        )
        step(
            "read",
            f"выгрузка обезличена: договоров {anonymized.contracts}, "
            f"транзакций {anonymized.transactions}",
            started,
        )

        current, started = "scale", time.monotonic()
        say(Step("scale", "вынимаю шкалу СТП, экономику и прогноз маржи", "running"))
        extract(source=batch.export, out_dir=staging, notice=batch.notice)
        if batch.notice is None:
            scale = "шкала СТП из выгрузки: уведомления нет, трассовых ставок в книге не будет"
        elif _has_highway(staging / SCALE_FILE):
            scale = f"шкала СТП из уведомления «{batch.notice.name}», с трассовыми ставками"
        else:
            scale = f"шкала СТП из уведомления «{batch.notice.name}»; трассовых ставок в нем нет"
        step("scale", scale, started)

        current, started = "check", time.monotonic()
        say(Step("check", "проверяю выгрузку", "running"))
        try:
            loaded = check(load_inputs(staging, branches=False), branches=False)
        except (ModelError, ValueError, csv.Error) as error:
            raise IntakeError(f"выгрузка не читается: {error}") from None
        if not loaded.ok:
            raise IntakeError("выгрузка не годится: " + "; ".join(loaded.errors))
        step("check", "выгрузка сходится сама с собой", started)

        current, started = "swap", time.monotonic()
        say(Step("swap", "заменяю данные", "running"))
        for name in PREPARED_FILES:
            _place(staging / name, places.inputs_dir / name)
        _place(staging / MAPPING_NAME, places.mapping_path)
        step("swap", "данные и таблица соответствия заменены", started)
    except (IntakeError, ExportError, ParametersError, NoticeError, MissingKeyError):
        step(current, _failed_text(current), started, "failed")
        raise
    finally:
        _remove(staging)
        batch.remove()

    current, started = "reload", time.monotonic()
    say(Step("reload", "перечитываю данные", "running"))
    state = reopen()
    ready = isinstance(state, Workspace)
    step(
        "reload",
        "данные перечитаны, можно считать" if ready
        else "данные перечитаны, но считать пока нельзя — что не так, видно ниже",
        started,
    )
    return {
        "ok": True,
        "ready": ready,
        "contracts": anonymized.contracts,
        "transactions": anonymized.transactions,
        "branches": branches_in(places.inputs_dir),
        "notice": batch.notice is not None,
        "warnings": loaded.warnings,
    }


def _failed_text(step: str) -> str:
    return {
        "read": "выгрузку не обезличить",
        "scale": "шкалу, экономику или прогноз маржи не вынуть",
        "check": "выгрузка не годится",
        "swap": "данные не заменить",
    }.get(step, "обработка не дошла до конца")
