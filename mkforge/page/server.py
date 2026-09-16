"""Локальный сервер страницы.

На странице лежат числа по реальному пулу клиентов, и открывать их в сеть нельзя
даже на минуту. Из исходников сервер слушает только петлю. В контейнере он слушает
все адреса контейнера, иначе проброс порта до него не достанет, и от сети его
закрывает только проброс на петлю хоста — `127.0.0.1:8765:8765` в compose, под тестом.
Проверка `Host` здесь защищает от чужого сайта в браузере, но не от запроса
с подставленным заголовком. По той же причине в разметке нет ни одной внешней
ссылки — ни шрифтов, ни библиотек графиков: любой запрос к чужому серверу сообщил
бы ему, что страница открыта.

Порт один, без перебора: блуждающий порт рождает две страницы с разными числами.

Сервер многопоточный, потому что сборка книги идет минутами: пересчет в
LibreOffice заложен с запасом в десять минут, и однопоточный сервер все это
время не отдал бы даже стилей.

Выгрузка приходит сырым телом, по файлу на запрос, а не multipart: модуль `cgi`
из Python 3.13 удален, а свой разбор границ — шестьдесят строк ради ничего.
Имя файла идет в заголовке кодированным.
"""

from __future__ import annotations

import errno
import json
import signal
import socket
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from mkforge.config import ConfigError
from mkforge.config_edit import EditError

from mkforge.task import branches
from mkforge.task.books import Book, find_book, ready_books
from mkforge.task.calculate import Places, Waiting, Workspace, calculate, form
from mkforge.task.deliver import deliver
from mkforge.task.intake import (
    NO_EXPORT,
    UPLOAD_LIMIT,
    BadName,
    Incomplete,
    TooLarge,
    UploadError,
    Uploads,
    WrongKind,
    intake,
    sweep,
)
from mkforge.task.jobs import Busy, Jobs
from mkforge.task.persist import preview, save
from mkforge.trace import log, where

BODY_LIMIT = 256 * 1024
# Сколько лишнего готовы вычитать, прежде чем отказать: столько же на всякий
# случай хватает, а бесконечно читать мусор незачем.
DRAIN_LIMIT = 4 * BODY_LIMIT
STATIC = {
    "page.css": "text/css; charset=utf-8",
    "page.js": "text/javascript; charset=utf-8",
    "charts.js": "text/javascript; charset=utf-8",
}
PAGE = "index.html"
PORT = 8765
LOOPBACK = "127.0.0.1"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NO_DATA = "данных для расчета нет — сначала загрузите выгрузку"
NO_UPLOAD = "загрузка на этой странице недоступна"
NAME_HEADER = "X-File-Name"
# Отказ загрузке -> статус.
UPLOAD_REFUSALS = {
    BadName: HTTPStatus.BAD_REQUEST,
    WrongKind: HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    TooLarge: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    Incomplete: HTTPStatus.BAD_REQUEST,
}


class PageServer(ThreadingHTTPServer):
    """Сервер, который держит открытое задание — или ждет данных для него."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, state: Workspace | Waiting, out_dir: Path | None = None,
                 places: Places | None = None):
        if isinstance(state, Workspace):
            out_dir = out_dir or state.out_dir
        out_dir = out_dir or (places.out_dir if places else None)
        if out_dir is None:
            raise ValueError("без данных серверу нужно знать папку готовых книг")
        super().__init__(address, handler)
        self.state = state
        self.out_dir = out_dir
        self.jobs = Jobs()
        # Без мест страница не знает, куда класть выгрузку и откуда перечитывать данные.
        self.places = places
        self.uploads = Uploads(places.raw_dir) if places else None
        self._state_lock = threading.Lock()
        if places:
            sweep(places)

    @property
    def ready(self) -> bool:
        return isinstance(self.state, Workspace)

    def reopen(self) -> Workspace | Waiting:
        """Перечитать данные после загрузки или правки таблицы отделений."""
        with self._state_lock:
            self.state = self.places.open()
            return self.state


def _static(name: str) -> bytes:
    """Файл статики из пакета.

    Через importlib, а не через путь к исходнику: при установке пакета колесом
    файла рядом с модулем может не оказаться.
    """
    return (resources.files("mkforge.page") / "static" / name).read_bytes()


class PageHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "mk-forge"
    sys_version = ""

    # --- транспорт ------------------------------------------------------

    def _send(self, status: HTTPStatus, body: bytes, content_type: str,
              cache: str = "no-store", headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        if status >= HTTPStatus.BAD_REQUEST:
            # Отказ мог случиться до того, как тело дочитано. Оставить такое
            # соединение открытым значит получить на нем мусор вместо запроса.
            self.close_connection = True
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _fail(self, status: HTTPStatus, message: str) -> None:
        self._json({"ok": False, "message": message}, status)

    def _body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > BODY_LIMIT:
            # Тело сначала вычитываем, потом отказываем. Иначе отправитель
            # упрется в закрытое соединение посреди записи и получит обрыв
            # вместо внятного отказа — причем не всегда, а как повезет.
            self._drain(length)
            self._fail(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "запрос слишком большой")
            return None
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._fail(HTTPStatus.BAD_REQUEST, "тело запроса не разобралось")
            return None

    def _drain(self, length: int, limit: int = DRAIN_LIMIT) -> None:
        """Дочитать и выбросить тело, но не бесконечно."""
        left = min(length, limit)
        while left > 0:
            chunk = self.rfile.read(min(left, 64 * 1024))
            if not chunk:
                return
            left -= len(chunk)

    def _local(self) -> bool:
        """Запрос пришел на петлю и со своей же страницы.

        Проверка `Host` закрывает подмену имени: браузер, которому чужой сайт
        подсунул адрес нашей петли, придет с чужим заголовком.
        """
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in {"127.0.0.1", "localhost", "[::1]", "::1"}:
            return False
        origin = self.headers.get("Origin")
        if origin:
            name = urlparse(origin).hostname
            if name not in {"127.0.0.1", "localhost", "::1"}:
                return False
        return True

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 — имя из базового класса
        """Одна строка на запрос, без тел: в телах числа по реальному пулу.

        Проверку здоровья Docker шлет каждые полминуты, в журнале она только шум.
        """
        if urlparse(self.path).path != "/api/health":
            print(f"  {self.command} {self.path}")

    def _guarded(self, route) -> None:
        """Сбой маршрута — строка в стандартный вывод и внятный отказ странице.

        Без этого исключение уходит в stderr вместе с сообщением, а в сообщениях
        бывают псевдонимы и числа пула; страница же получает оборванное соединение.
        В строку идут только тип ошибки и где она случилась: сообщение, тело
        запроса и строка запроса в журнал не попадают.
        """
        try:
            route()
        except ConnectionError:
            self.close_connection = True  # страница ушла, отвечать некому
        except Exception as error:  # noqa: BLE001 — журналу нужен любой сбой
            log(f"сбой {self.command} {urlparse(self.path).path}: {where(error)}")
            try:
                self._fail(HTTPStatus.INTERNAL_SERVER_ERROR,
                           "на сервере сбой, подробности в журнале")
            except OSError:
                self.close_connection = True

    # --- маршруты -------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 — имя из базового класса
        self._guarded(self._get)

    def do_POST(self) -> None:  # noqa: N802 — имя из базового класса
        self._guarded(self._post)

    def _get(self) -> None:
        if not self._local():
            self._fail(HTTPStatus.FORBIDDEN, "страница открывается только на этой машине")
            return
        path = urlparse(self.path).path

        if path == "/":
            self._send(HTTPStatus.OK, _static(PAGE), "text/html; charset=utf-8", "no-cache")
            return
        if path.startswith("/static/"):
            name = path[len("/static/"):]
            content_type = STATIC.get(name)
            if content_type is None:
                self._fail(HTTPStatus.NOT_FOUND, "нет такого файла")
                return
            self._send(HTTPStatus.OK, _static(name), content_type, "no-cache")
            return
        if path == "/api/health":
            # Жив ли сервер, и только. От данных не зависит: пустой том — не болезнь.
            self._json({"ok": True})
            return
        if path == "/api/state":
            state = self.server.state
            upload = {"upload": self.server.places is not None, "upload_limit": UPLOAD_LIMIT}
            if not isinstance(state, Workspace):
                self._json({"ready": False, "waiting": state.payload(), **upload})
                return
            self._json({"ready": True, "form": form(state), "answer": calculate(state), **upload})
            return
        if path == "/api/branches":
            if self.server.places is None:
                self._json({"ok": False, "message": NO_UPLOAD})
                return
            self._json(branches.describe(self.server.places.inputs_dir))
            return
        if path == "/api/books":
            self._json({"books": [book.payload() for book in ready_books(self.server.out_dir)]})
            return
        if path.startswith("/api/books/"):
            book = find_book(self.server.out_dir, unquote(path[len("/api/books/"):]))
            if book is None:
                self._fail(HTTPStatus.NOT_FOUND, "такой готовой книги нет")
                return
            self._book(book)
            return
        if path.startswith("/api/jobs/"):
            job = self.server.jobs.get(path[len("/api/jobs/"):])
            if job is None:
                self._fail(HTTPStatus.NOT_FOUND, "такого задания нет")
                return
            self._json(job.payload())
            return

        self._fail(HTTPStatus.NOT_FOUND, "нет такого маршрута")

    def _post(self) -> None:
        if not self._local():
            self._fail(HTTPStatus.FORBIDDEN, "страница открывается только на этой машине")
            return
        path = urlparse(self.path).path
        if path == "/api/upload":
            self._upload()
            return
        body = self._body()
        if body is None:
            return

        if path == "/api/prepare":
            self._prepare()
            return
        if path == "/api/branches":
            self._branches(body)
            return

        if not self.server.ready:
            self._fail(HTTPStatus.CONFLICT, NO_DATA)
            return

        if path == "/api/calculate":
            answer = calculate(self.server.state, body.get("overrides") or {})
            # Номер запроса возвращается как есть: ответы приходят не в том
            # порядке, в котором ушли, и страница обязана уметь выбросить старый.
            answer["request"] = body.get("request")
            self._json(answer)
            return

        if path == "/api/book":
            overrides = body.get("overrides") or {}
            try:
                job = self.server.jobs.start(
                    lambda report: deliver(self.server.state, overrides, report)
                )
            except Busy as error:
                running = self.server.jobs.running()
                self._json(
                    {"ok": False, "message": str(error),
                     "job": running.id if running else None},
                    HTTPStatus.CONFLICT,
                )
                return
            self._json({"ok": True, "job": job.id}, HTTPStatus.ACCEPTED)
            return

        if path == "/api/config/preview":
            self._json(preview(self.server.state, body.get("overrides") or {}))
            return

        if path == "/api/config/save":
            try:
                self._json(save(self.server.state, body.get("overrides") or {}))
            except (ConfigError, EditError) as error:
                # Конфиг после записи не читается — говорим об этом прямо,
                # а не показываем страницу, которая считает по старому.
                self._fail(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))
            return

        self._fail(HTTPStatus.NOT_FOUND, "нет такого маршрута")

    def _upload(self) -> None:
        """Принять один файл сырым телом. Обработка — отдельным запросом."""
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit():
            # Без длины не понять, где кончается тело, и соединение не спасти.
            self._fail(HTTPStatus.LENGTH_REQUIRED, "нужна длина тела")
            return
        length = int(length)
        uploads = self.server.uploads
        running = self.server.jobs.running()
        refusal = (
            NO_UPLOAD if uploads is None
            else f"{running.name} уже идет" if running and running.state == "running"
            else None
        )
        if refusal:
            if uploads is not None:
                uploads.discard()
            self._drain(length, UPLOAD_LIMIT)
            self._fail(HTTPStatus.CONFLICT, refusal)
            return
        consumed = 0

        def read(size: int) -> bytes:
            nonlocal consumed
            chunk = self.rfile.read(size)
            consumed += len(chunk)
            return chunk

        try:
            received = uploads.receive(upload_name(self.headers.get(NAME_HEADER)), length, read)
        except UploadError as error:
            if not consumed:
                self._drain(length, UPLOAD_LIMIT)  # отказ по заголовкам, тело еще в пути
            self._fail(UPLOAD_REFUSALS[type(error)], str(error))
            return
        self._json({"ok": True, **received.payload()})

    def _prepare(self) -> None:
        """Обработать загруженное заданием: пересчета тут нет, но идет оно секунды."""
        places, uploads = self.server.places, self.server.uploads
        if uploads is None:
            self._fail(HTTPStatus.CONFLICT, NO_UPLOAD)
            return
        # Загруженное забирается сразу: чем бы ни кончился этот запрос, сырые файлы
        # в томе не остаются лежать до следующей загрузки.
        batch = uploads.take()
        if batch.export is None:
            batch.remove()
            self._fail(HTTPStatus.CONFLICT, NO_EXPORT)
            return
        try:
            job = self.server.jobs.start(
                lambda report: intake(places, batch, self.server.reopen, report),
                name="обработка выгрузки",
            )
        except Busy as error:
            batch.remove()
            self._fail(HTTPStatus.CONFLICT, str(error))
            return
        self._json({"ok": True, "job": job.id}, HTTPStatus.ACCEPTED)

    def _branches(self, body: dict) -> None:
        places = self.server.places
        if places is None:
            self._fail(HTTPStatus.CONFLICT, NO_UPLOAD)
            return
        running = self.server.jobs.running()
        if running and running.state == "running":
            # Сборка держит данные в памяти, обработка их заменяет: таблица посреди
            # любой из них разошлась бы с тем, что считается.
            self._fail(HTTPStatus.CONFLICT, f"{running.name} уже идет")
            return
        pairs = body.get("pairs")
        if not isinstance(pairs, dict):
            self._fail(HTTPStatus.BAD_REQUEST, "нет пар «отделение — регион»")
            return
        answer = branches.save(places.inputs_dir, pairs)
        if answer["ok"]:
            answer["ready"] = isinstance(self.server.reopen(), Workspace)
        self._json(answer)

    def _book(self, book: Book) -> None:
        self._send(
            HTTPStatus.OK,
            book.path.read_bytes(),
            XLSX,
            headers={"Content-Disposition": attachment(book.name)},
        )


def upload_name(header: str | None) -> str | None:
    """Имя загруженного файла из заголовка.

    Имя приходит кодированным: http.server читает заголовки в latin-1, и кириллица
    как есть стала бы кракозябрами в имени, а не отказом. Поэтому некодированное
    имя — отказ, а не догадка о кодировке.
    """
    if header is None:
        return None
    if not header.isascii():
        raise BadName("имя файла должно приходить кодированным")
    try:
        return unquote(header, errors="strict")
    except UnicodeDecodeError:
        raise BadName("имя файла не раскодировалось") from None


def attachment(name: str) -> str:
    """Заголовок скачивания с именем книги.

    Имя кириллицей в заголовок как есть не пройдет: http.server пишет заголовки
    в latin-1. Поэтому оно идет кодированным (RFC 6266), а рядом — запасное
    латиницей для клиентов, которые кодированное не читают.
    """
    plain = name.isascii() and not any(mark in name for mark in '"\\;')
    fallback = name if plain else f"book{Path(name).suffix}"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"


def serve(
    state: Workspace | Waiting,
    out_dir: Path,
    host: str = LOOPBACK,
    port: int = PORT,
    open_browser: bool = True,
    places: Places | None = None,
) -> int:
    """Поднять страницу. Возвращает код для командной строки."""
    from mkforge.task.calculate import soffice_found

    try:
        server = PageServer((host, port), PageHandler, state, out_dir, places)
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            print(
                f"порт {port} занят: страница, похоже, уже открыта — "
                f"в контейнере или из исходников. Вторую не поднимаю",
                file=sys.stderr,
            )
        else:
            print(f"не занять {host}:{port}: {error.strerror or error}", file=sys.stderr)
        return 1

    # Все адреса контейнера — это не адрес для браузера: снаружи страница на петле.
    address = f"http://{LOOPBACK if host in ('0.0.0.0', '::', '') else host}:{port}"
    print(f"страница «Акция»: {address}")
    if host != LOOPBACK:
        print(f"слушаю {host}:{port}; от сети закрывает только проброс порта на петлю")
    if isinstance(state, Workspace):
        plan = calculate(state)
        pool = plan["plan"]["pool_size"] if plan["ok"] else 0
        forecast = plan["plan"]["forecast_size"] if plan["ok"] else 0
        print(f"конфиг: {state.config_path}")
        print(f"данные: {state.inputs_dir}, договоров в пуле {pool}, прогноз новых {forecast}")
        print(f"книги: рабочие в {state.work_dir}, готовые в {state.out_dir}")
    else:
        print(f"конфиг: {state.config_path}")
        if state.missing:
            print(f"данных нет: в {state.inputs_dir} не хватает {', '.join(state.missing)}")
        else:
            # Что именно не так, видно на странице: в описании бывают числа пула.
            print(f"данные в {state.inputs_dir} не годятся — что не так, видно на странице")
        print("страница открыта с приглашением загрузить выгрузку")
    print(
        "LibreOffice найден — сборка книги с пересчетом доступна"
        if soffice_found()
        else "LibreOffice не найден — числа считаются, книгу пересчитать будет нечем"
    )
    print("Ctrl+C — остановить", flush=True)

    if open_browser:
        webbrowser.open(address)
    # Сигнал остановки идет тем же путем, что Ctrl+C: страница гаснет сразу, а прерванная
    # сборка оставляет строку в журнале. Без обработчика Python первым процессом контейнера
    # сигнал не слышал бы вовсе, и Docker убивал бы его через десять секунд.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.jobs.interrupt()
        print("\nстраница остановлена", flush=True)
    finally:
        server.server_close()
    return 0


def free_port() -> int:
    """Свободный порт. Нужен тестам, чтобы не драться за один и тот же."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
