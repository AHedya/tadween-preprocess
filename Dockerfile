FROM jrottenberg/ffmpeg:8.0-alpine AS ffmpeg
FROM python:3.14-alpine AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/
COPY --from=ffmpeg /lib /lib
COPY --from=ffmpeg /bin/ffmpeg /bin/ffprobe /usr/local/bin/

WORKDIR /app/
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV PYTHONPATH=/app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --extra worker --locked --no-install-project

FROM base AS runpod
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --extra worker --extra runpod
CMD ["uv", "run", "python","-u", "runpod_handler.py"]

FROM base AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --group test --extra worker
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --group test --extra worker
CMD ["pytest"]

FROM base AS dev
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --all-groups --all-extras
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --all-groups --all-extras
CMD []
