"""Транспорт страницы: маршруты, отказы и локальность.

Сервер поднимается на свободном порту в отдельном потоке, запросы идут
стандартной библиотекой. Данные, как и везде, синтетические.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from mkforge.page.server import PageHandler, PageServer, free_port
from mkforge.task.calculate import open_workspace


@pytest.fixture
def address(anon_dir: Path, distributed_config_path: Path, tmp_path: Path):
    state = open_workspace(
        inputs_dir=anon_dir,
        config_path=distributed_config_path,
        mapping_path=tmp_path / "mapping.json",
        work_dir=tmp_path / "рабочие",
        out_dir=tmp_path / "готовые",
    )
    server = PageServer(("127.0.0.1", free_port()), PageHandler, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def get(address: str, path: str, headers: dict | None = None):
    request = urllib.request.Request(address + path, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read(), response.headers


def post(address: str, path: str, payload, raw: bytes | None = None):
    body = raw if raw is not None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        address + path, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, json.loads(response.read())


def test_page_and_static_are_served(address):
    status, body, headers = get(address, "/")
    assert status == 200
    assert b"<title>" in body
    assert "text/html" in headers["Content-Type"]

    for name, kind in (("page.css", "text/css"), ("page.js", "text/javascript")):
        status, body, headers = get(address, f"/static/{name}")
        assert status == 200 and body
        assert kind in headers["Content-Type"]


def test_nothing_outside_the_page_is_reachable(address):
    """Статика отдается по списку имен, путь из запроса не склеивается."""
    for path in ("/static/../config.py", "/static/../../mkforge/cli.py",
                 "/static/page.js.map", "/etc/hosts"):
        with pytest.raises(urllib.error.HTTPError) as error:
            get(address, path)
        assert error.value.code == 404


def test_state_gives_the_form_and_the_first_answer(address):
    status, body, _ = get(address, "/api/state")
    assert status == 200
    payload = json.loads(body)
    assert payload["form"]["fields"]
    assert payload["answer"]["ok"] is True
    assert payload["answer"]["plan"]["pool_size"] > 0


def test_calculate_returns_numbers(address):
    status, answer = post(address, "/api/calculate", {"overrides": {"share_without": 0.2}})
    assert status == 200
    assert answer["ok"] is True
    assert answer["plan"]["effect"]["payback"] > 0


def test_bad_input_is_an_answer_with_status_200(address):
    """Неверное поле — это ответ, а не сбой транспорта."""
    status, answer = post(
        address, "/api/calculate",
        {"overrides": {"distribution": [{"depth": 0.05, "share": 0.4}]}, "request": 7},
    )
    assert status == 200
    assert answer["ok"] is False
    assert answer["errors"][0]["field"] == "distribution"
    assert answer["request"] == 7, "номер запроса возвращается, чтобы отбросить старый ответ"


def test_broken_json(address):
    with pytest.raises(urllib.error.HTTPError) as error:
        post(address, "/api/calculate", None, raw="{это не json".encode("utf-8"))
    assert error.value.code == 400


def test_body_over_the_limit(address):
    with pytest.raises(urllib.error.HTTPError) as error:
        post(address, "/api/calculate", None, raw=b"x" * (256 * 1024 + 1))
    assert error.value.code == 413


def test_unknown_route(address):
    with pytest.raises(urllib.error.HTTPError) as error:
        get(address, "/api/nothing-here")
    assert error.value.code == 404


def test_foreign_host_is_refused(address):
    """Чужое имя в заголовке — попытка дотянуться до петли снаружи."""
    with pytest.raises(urllib.error.HTTPError) as error:
        get(address, "/api/state", headers={"Host": "evil.example"})
    assert error.value.code == 403


def test_foreign_origin_is_refused(address):
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(
            urllib.request.Request(
                address + "/api/calculate",
                data=b"{}",
                headers={"Content-Type": "application/json",
                         "Origin": "https://evil.example"},
            ),
            timeout=10,
        )
    assert error.value.code == 403


def test_page_has_no_external_links():
    """Ни шрифтов, ни библиотек: запрос к чужому серверу сообщил бы,
    что страница с данными клиентов открыта.

    Единственное исключение — пространство имен SVG. Оно выглядит адресом, но
    браузер по нему никогда не ходит: это имя, а не ссылка.
    """
    from importlib import resources

    svg_namespace = "http" + "://www.w3.org/2000/svg"
    for name in ("index.html", "page.css", "page.js", "charts.js"):
        text = (resources.files("mkforge.page") / "static" / name).read_text(
            encoding="utf-8"
        )
        text = text.replace(svg_namespace, "")
        for mark in ("http" + "://", "https" + "://", "//cdn", "fonts.googleapis"):
            assert mark not in text, f"{name}: внешняя ссылка {mark}"


def test_config_preview_and_save_routes(address, tmp_path: Path):
    """Просмотр ничего не пишет, запись меняет конфиг и перечитывает его."""
    status, shown = post(
        address, "/api/config/preview", {"overrides": {"plan_participants": 1800}}
    )
    assert status == 200 and shown["ok"] is True
    assert shown["changed"] and "1800" in shown["diff"]

    status, saved = post(
        address, "/api/config/save", {"overrides": {"plan_participants": 1800}}
    )
    assert status == 200 and saved["saved"] is True

    status, body, _ = get(address, "/api/state")
    values = {
        field["name"]: field["value"] for field in json.loads(body)["form"]["fields"]
    }
    assert values["plan_participants"] == 1800, "форма берет значения из файла"


def test_config_save_refuses_bad_input(address):
    status, answer = post(
        address, "/api/config/save",
        {"overrides": {"distribution": [{"depth": 0.05, "share": 0.4}]}},
    )
    assert status == 200
    assert answer["ok"] is False
    assert answer["errors"][0]["field"] == "distribution"


def test_route_failure_is_logged_without_data(address, monkeypatch, capsys):
    """Сбой маршрута — строка в стандартный вывод и отказ 500, но без сообщения ошибки:
    в сообщениях бывают псевдонимы и числа пула."""
    def broken(state, overrides=None):
        raise ValueError("Д-ABCDEF0123 выручка 98765432")

    monkeypatch.setattr("mkforge.page.server.calculate", broken)
    with pytest.raises(urllib.error.HTTPError) as error:
        post(address, "/api/calculate", {"overrides": {"share_without": 0.2}})
    assert error.value.code == 500
    assert json.loads(error.value.read())["ok"] is False

    output = capsys.readouterr().out
    assert "сбой POST /api/calculate: ValueError" in output
    assert "test_page_http.py" in output, "видно, где случилось"
    for secret in ("Д-ABCDEF0123", "98765432", "share_without", "0.2"):
        assert secret not in output

    # Сервер жив и отвечает дальше.
    status, _, _ = get(address, "/")
    assert status == 200
