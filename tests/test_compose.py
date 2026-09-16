"""Поставка в контейнере: то, что держится файлами compose и образом, а не памятью.

Страницу от сети закрывает только проброс порта на петлю хоста. Проверка `Host`
в сервере от запроса с подставленным заголовком не защищает, поэтому адрес
проброса держит тест.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

COMPOSE_FILES = ("compose.yaml", "compose.dev.yaml")


def services(name: str) -> dict:
    return yaml.safe_load(Path(name).read_text(encoding="utf-8"))["services"]


def image_home() -> str:
    found = re.search(r"^ENV MK_FORGE_HOME=(\S+)", Path("Dockerfile").read_text(encoding="utf-8"),
                      re.MULTILINE)
    assert found, "в образе не задан MK_FORGE_HOME — корнем стала бы папка с кодом"
    return found.group(1)


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_port_is_published_on_host_loopback_only(name):
    for service in services(name).values():
        assert "network_mode" not in service, "сеть хоста обходит проброс порта"
        assert service["ports"], "без проброса страница недоступна"
        for port in service["ports"]:
            assert isinstance(port, str) and port.startswith("127.0.0.1:"), (
                f"{name}: порт {port} открыт не только на петлю"
            )


@pytest.mark.parametrize("name", COMPOSE_FILES)
def test_volume_is_mounted_at_the_data_root(name):
    home = image_home()
    for service in services(name).values():
        targets = [volume.split(":")[1] for volume in service["volumes"]]
        assert home in targets, f"{name}: том смонтирован не в корень данных {home}"


def test_image_starts_through_init():
    """LibreOffice оставляет осиротевшие gpg и gpgconf; Python первым процессом
    их не подбирает, и зомби копились бы с каждой книгой."""
    entrypoint = re.findall(r"^ENTRYPOINT (.+)$", Path("Dockerfile").read_text(encoding="utf-8"),
                            re.MULTILINE)
    assert entrypoint and entrypoint[-1].startswith('["tini", "--"')


def test_user_container_restarts_and_dev_container_does_not():
    """Разработческий контейнер не должен держать порт, пока страница из исходников."""
    assert all(s.get("restart") == "unless-stopped" for s in services("compose.yaml").values())
    assert all("restart" not in s for s in services("compose.dev.yaml").values())


def test_user_image_version_is_a_variable_and_matches_the_published_name():
    """Откат — смена тега в переменной, а не правка файла. Имя образа в compose
    обязано совпадать с тем, под которым CI публикует: иначе pull тянул бы не то."""
    image = services("compose.yaml")["page"]["image"]
    published = yaml.safe_load(Path(".github/workflows/image.yml").read_text(encoding="utf-8"))
    assert image == f"{published['env']['IMAGE']}:${{MK_FORGE_TAG:-latest}}"
