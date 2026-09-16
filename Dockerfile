# Черновой образ: считает ли LibreOffice из Debian книгу так же, как на маке.
# Пользователя, тома и точки входа здесь еще нет.
#
#   docker build --target runtime -t mk-forge:draft .
#   docker build --target test -t mk-forge:draft-test .

FROM python:3.12-slim-trixie AS runtime

COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /bin/

# Кириллица в именах книг и путях: кодировку имен берут из локали и Python, и LibreOffice.
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-calc-nogui \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Зависимости отдельным слоем: меняются реже кода. Кэш uv в образ не попадает,
# иначе каждый пакет лежит в слое дважды.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

COPY mkforge ./mkforge
COPY configs ./configs
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# pytest в образ не идет, он есть только здесь.
FROM runtime AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --extra dev
COPY tests ./tests
