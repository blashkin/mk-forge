"""Страница как процесс: стартует на пустом корне и гаснет по сигналу остановки.

В контейнере оба свойства — вопрос жизни. Без данных страница, которая отказывает,
с перезапуском `unless-stopped` падала бы по кругу. По сигналу остановки страница
гаснет сразу и говорит об этом, а не ждет, пока Docker убьет ее через десять секунд.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from mkforge.page.server import free_port


def wait_for_health(address: str, process: subprocess.Popen, limit: float = 30) -> None:
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"страница вышла с кодом {process.returncode}")
        try:
            with urllib.request.urlopen(address + "/api/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.1)
    raise AssertionError("страница не поднялась")


def test_page_starts_on_an_empty_root_and_stops_on_sigterm(home_in_tmp: Path, tmp_path: Path):
    port = free_port()
    address = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "-m", "mkforge.cli", "page", "--no-open", "--port", str(port)],
        # Как в контейнере: корень и акция из переменных, текущая папка чужая.
        env={**os.environ, "MK_FORGE_CONFIG": "configs/example_distribution.yaml"},
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_health(address, process)
        with urllib.request.urlopen(address + "/api/state", timeout=10) as response:
            state = json.loads(response.read())
        assert state["ready"] is False
        assert "transactions.csv" in state["waiting"]["missing"]
        assert (home_in_tmp / "configs" / "example_distribution.yaml").exists(), (
            "образцы конфигов легли в пустой корень"
        )

        process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()

    assert process.returncode == 0, output
    assert "страница остановлена" in output
    assert "Traceback" not in output


def test_page_without_config_refuses(home_in_tmp: Path, monkeypatch, capsys):
    from mkforge.cli import main

    monkeypatch.setenv("MK_FORGE_CONFIG", "  ")
    assert main(["page", "--no-open"]) == 1
    assert "MK_FORGE_CONFIG" in capsys.readouterr().err


def test_upload_through_the_process_lands_in_the_root(home_in_tmp: Path, tmp_path: Path, export: Path):
    """Места для загрузки считает командная строка: корень, data/raw, data/anon, таблица
    соответствия — все от корня данных, как и остальное."""
    from urllib.parse import quote

    port = free_port()
    address = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, "-m", "mkforge.cli", "page", "--no-open", "--port", str(port)],
        env={**os.environ, "MK_FORGE_CONFIG": "configs/example_distribution.yaml"},
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_health(address, process)
        request = urllib.request.Request(
            address + "/api/upload", data=export.read_bytes(),
            headers={"Content-Type": "application/octet-stream",
                     "X-File-Name": quote("Выгрузка.xlsx", safe="")},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            assert json.loads(response.read())["ok"] is True
        request = urllib.request.Request(
            address + "/api/prepare", data=b"{}", headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            job = json.loads(response.read())["job"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with urllib.request.urlopen(f"{address}/api/jobs/{job}", timeout=10) as response:
                payload = json.loads(response.read())
            if payload["state"] != "running":
                break
            time.sleep(0.1)
        assert payload["state"] == "done", payload["error"]
    finally:
        process.send_signal(signal.SIGTERM)
        output, _ = process.communicate(timeout=5)

    assert (home_in_tmp / "data" / "anon" / "transactions.csv").exists()
    assert (home_in_tmp / "data" / "contracts.mapping.json").exists()
    assert list((home_in_tmp / "data" / "raw").iterdir()) == [], output
    assert "Traceback" not in output
