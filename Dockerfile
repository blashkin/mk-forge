# Образ mk-forge: страница «Акция» и LibreOffice, которым книга пересчитывается
# и сверяется с ядром.
#
#   docker compose -f compose.dev.yaml up --build    из рабочего дерева, см. compose.dev.yaml
#   docker build --target test -t mk-forge:test .   тесты, в том числе с пересчетом
#   docker run --rm mk-forge:test pytest -m libreoffice

FROM python:3.12-slim-trixie AS base

COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /bin/

# Кириллица в именах книг и путях: кодировку имен берут из локали и Python, и LibreOffice.
# Вывод без буфера: без терминала Python копит строки, и журнал контейнера молчал бы.
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Пакеты по HTTPS: по голому HTTP прокси по пути портил примерно пакет из полутора сотен,
# и сборка падала на сверке контрольных сумм. Сертификаты в базовом образе уже есть.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-calc-nogui tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Зависимости отдельным слоем: меняются реже кода. Кэш uv в образ не попадает,
# иначе каждый пакет лежит в слое дважды.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

# Конфиги здесь только образцы: .dockerignore не пускает настоящие в контекст сборки.
COPY mkforge ./mkforge
COPY configs ./configs
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# pytest в образ для пользователя не идет, он есть только здесь.
FROM base AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --extra dev
COPY tests ./tests
COPY Dockerfile compose.yaml compose.dev.yaml ./

FROM base AS runtime

# Точка монтирования создается заранее и отдается пользователю контейнера:
# пустой именованный том берет владельца у этой папки, иначе он достался бы root,
# и первая же запись упала бы. На маке это не всплывает — Docker Desktop прячет
# права на подключенной папке.
ENV MK_FORGE_HOME=/srv/mk-forge
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin mkforge \
    && mkdir -p "$MK_FORGE_HOME" \
    && chown mkforge:mkforge "$MK_FORGE_HOME"
USER mkforge

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4)"]

# tini первым процессом: подбирает зомби и передает странице сигнал остановки.
# LibreOffice при каждом пересчете запускает gpg и gpgconf и уходит раньше них;
# осиротевшие процессы достаются первому, а Python чужих детей не подбирает —
# без tini их копилось около десятка на книгу.
#
# Все адреса контейнера: иначе проброс порта до страницы не достанет. От сети ее
# закрывает проброс на петлю хоста в compose. Браузера в контейнере нет.
ENTRYPOINT ["tini", "--", "mk-forge"]
CMD ["page", "--host", "0.0.0.0", "--no-open"]
