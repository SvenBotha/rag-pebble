# syntax=docker/dockerfile:1.7

# ---- builder ----------------------------------------------------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# Install runtime deps first (cacheable layer).
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-install-project

# Then install the package itself.
COPY pebble ./pebble
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen


# ---- runtime ----------------------------------------------------------------
FROM python:3.12-slim AS runtime

WORKDIR /app
COPY --from=builder /app /app
COPY examples ./examples

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Pebble writes its FAISS index and SQLite metadata here. Mount a volume in
# production to persist across container restarts.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

CMD ["uvicorn", "pebble.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
