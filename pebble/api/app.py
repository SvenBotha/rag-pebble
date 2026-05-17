"""FastAPI application factory and lifespan.

Lifespan rules (brief §3, Agent F):
- `/health` answers 200 from process start.
- Index loads in a background task during startup.
- `/ready` answers 503 until the load completes, then 200.

This contract lets a container orchestrator wait on /ready before
sending traffic while still treating /health as a basic liveness probe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pebble.api.routes import router
from pebble.bootstrap import Services, build_services
from pebble.config.loader import load_config
from pebble.core.errors import (
    BudgetExceededError,
    ConfigError,
    PebbleError,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    StoreError,
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_LOG = logging.getLogger("pebble.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.start_time = time.time()
    app.state.services = None
    app.state.ready = False
    app.state.ready_error = None

    config_path: Path | None = None
    candidate = Path.cwd() / "config.yaml"
    if candidate.is_file():
        config_path = candidate
    app.state.config_path = config_path

    config = load_config()

    async def _build() -> None:
        try:
            services = await asyncio.to_thread(build_services, config)
            app.state.services = services
            app.state.ready = True
            _LOG.info("services ready: %d chunks loaded", services.store.live_count)
        except Exception as e:  # noqa: BLE001
            _LOG.exception("failed to build services")
            app.state.ready_error = str(e)

    build_task = asyncio.create_task(_build())

    try:
        yield
    finally:
        if not build_task.done():
            build_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await build_task
        services: Services | None = app.state.services
        if services is not None:
            await services.aclose()


def create_app(config_path: Path | None = None) -> FastAPI:  # noqa: ARG001
    """Build a FastAPI app.

    `config_path` is reserved for tests and external callers; today the
    lifespan loads config from cwd. Wire it through if a caller needs
    a non-default location.
    """
    configure_logging()
    app = FastAPI(title="Pebble", version="0.0.1", lifespan=lifespan)
    app.include_router(router)
    _install_error_handlers(app)
    return app


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BudgetExceededError)
    async def _budget(_: Request, exc: BudgetExceededError) -> JSONResponse:
        return JSONResponse(
            {"error": "budget_exceeded", "detail": str(exc)},
            status_code=402,
        )

    @app.exception_handler(ProviderAuthError)
    async def _auth(_: Request, exc: ProviderAuthError) -> JSONResponse:
        return JSONResponse(
            {"error": "provider_auth", "detail": str(exc)},
            status_code=502,
        )

    @app.exception_handler(ProviderRateLimitError)
    async def _rate(_: Request, exc: ProviderRateLimitError) -> JSONResponse:
        return JSONResponse(
            {"error": "provider_rate_limit", "detail": str(exc)},
            status_code=503,
        )

    @app.exception_handler(ProviderTimeoutError)
    async def _timeout(_: Request, exc: ProviderTimeoutError) -> JSONResponse:
        return JSONResponse(
            {"error": "provider_timeout", "detail": str(exc)},
            status_code=504,
        )

    @app.exception_handler(ProviderError)
    async def _provider(_: Request, exc: ProviderError) -> JSONResponse:
        return JSONResponse(
            {"error": "provider", "detail": str(exc)},
            status_code=502,
        )

    @app.exception_handler(ConfigError)
    async def _config(_: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(
            {"error": "config", "detail": str(exc)},
            status_code=500,
        )

    @app.exception_handler(StoreError)
    async def _store(_: Request, exc: StoreError) -> JSONResponse:
        return JSONResponse(
            {"error": "store", "detail": str(exc)},
            status_code=500,
        )

    @app.exception_handler(PebbleError)
    async def _generic(_: Request, exc: PebbleError) -> JSONResponse:
        return JSONResponse(
            {"error": "pebble", "detail": str(exc)},
            status_code=500,
        )


app = create_app()
