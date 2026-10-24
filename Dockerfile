FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock* README.md ./

ARG INSTALL_DEV=false

RUN if [ "$INSTALL_DEV" = "true" ]; then \
        uv sync --no-install-project; \
    else \
        uv sync --no-install-project --no-dev; \
    fi

COPY src/ ./src/
COPY alembic.ini ./
COPY alembic ./alembic

RUN if [ "$INSTALL_DEV" = "true" ]; then \
        uv sync; \
    else \
        uv sync --no-dev; \
    fi

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "synora.main:app", "--host", "0.0.0.0", "--port", "8000"]
