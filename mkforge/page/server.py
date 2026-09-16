"""Локальный сервер страницы.

Слушает только петлю. Это не перестраховка: на странице лежат числа по реальному
пулу клиентов, и открывать их в сеть нельзя даже на минуту. По той же причине
в разметке нет ни одной внешней ссылки — ни шрифтов, ни библиотек графиков:
любой запрос к чужому серверу сообщил бы ему, что страница открыта.

Сервер многопоточный, потому что сборка книги идет минутами: пересчет в
LibreOffice заложен с запасом в десять минут, и однопоточный сервер все это
время не отдал бы даже стилей.
"""

from __future__ import annotations

import json
import socket
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import urlparse

from mkforge.config import ConfigError
from mkforge.config_edit import EditError

from mkforge.task.calculate import Workspace, calculate, form
from mkforge.task.deliver import deliver
from mkforge.task.jobs import Busy, Jobs
from mkforge.task.persist import preview, save

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
PORT_ATTEMPTS = 10


class PageServer(ThreadingHTTPServer):
    """Сервер, который держит открытое задание."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, state: Workspace):
        super().__init__(address, handler)
        self.state = state
        self.jobs = Jobs()


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
              cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
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

    def _drain(self, length: int) -> None:
        """Дочитать и выбросить тело, но не бесконечно."""
        left = min(length, DRAIN_LIMIT)
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
        """Одна строка на запрос, без тел: в телах числа по реальному пулу."""
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
            print(
                f"  сбой {self.command} {urlparse(self.path).path}: {_where(error)}",
                flush=True,
            )
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
        if path == "/api/state":
            state = self.server.state
            self._json({"form": form(state), "answer": calculate(state)})
            return
        if path.startswith("/api/book/"):
            job = self.server.jobs.get(path[len("/api/book/"):])
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
        body = self._body()
        if body is None:
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


def _where(error: BaseException) -> str:
    """Тип ошибки и путь по коду, без сообщения: в сообщениях бывают данные."""
    frames = " → ".join(
        f"{Path(frame.filename).name}:{frame.lineno}"
        for frame in traceback.extract_tb(error.__traceback__)
    )
    return f"{type(error).__name__} ({frames})"


def _bind(state: Workspace, port: int) -> PageServer:
    """Занять порт, при занятости попробовать следующие."""
    last: OSError | None = None
    for candidate in range(port, port + PORT_ATTEMPTS):
        try:
            return PageServer(("127.0.0.1", candidate), PageHandler, state)
        except OSError as error:
            last = error
    raise OSError(f"порты с {port} по {port + PORT_ATTEMPTS - 1} заняты") from last


def serve(state: Workspace, port: int = 8765, open_browser: bool = True) -> int:
    """Поднять страницу. Возвращает код для командной строки."""
    from mkforge.task.calculate import soffice_found

    server = _bind(state, port)
    address = f"http://127.0.0.1:{server.server_address[1]}"
    plan = calculate(state)
    pool = plan["plan"]["pool_size"] if plan["ok"] else 0
    forecast = plan["plan"]["forecast_size"] if plan["ok"] else 0

    print(f"страница «Акция»: {address}")
    print(f"конфиг: {state.config_path}")
    print(f"данные: {state.inputs_dir}, договоров в пуле {pool}, прогноз новых {forecast}")
    print(f"книги: рабочие в {state.work_dir}, готовые в {state.out_dir}")
    print(
        "LibreOffice найден — сборка книги с пересчетом доступна"
        if soffice_found()
        else "LibreOffice не найден — числа считаются, книгу пересчитать будет нечем"
    )
    print("Ctrl+C — остановить")

    if open_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nстраница остановлена")
    finally:
        server.server_close()
    return 0


def free_port() -> int:
    """Свободный порт. Нужен тестам, чтобы не драться за один и тот же."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
