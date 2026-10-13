"""The FastAPI service (spec 6).

    uvicorn portfoliosight.api.app:app

``app`` is created on first access, from the environment, so importing this module starts
nothing and needs no secret.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from portfoliosight.api.errors import NO_STORE, forbidden, install_handlers
from portfoliosight.api.gate import GATE_HEADER, gate_open
from portfoliosight.api.settings import Settings
from portfoliosight.data import store as store_mod
from portfoliosight.data.calendar import generation_date, trading_days_behind
from portfoliosight.engine import ENGINE_VERSION

CURRENT_KEY = "meta/current.json"
STATUS_KEY = "meta/status.json"

Clock = Callable[[], float]


def generation_key(generation: str) -> str:
    return f"meta/{generation}/generation.json"


def _optional_json(store: store_mod.Store, key: str) -> Any:
    try:
        return store_mod.get_json(store, key)
    except KeyError:
        return None


def current_generation(store: store_mod.Store) -> str | None:
    """The published generation, ``None`` before the first nightly run has published one."""
    pointer = _optional_json(store, CURRENT_KEY)
    return pointer.get("generation") if isinstance(pointer, dict) else None


def create_app(
    *,
    store: store_mod.Store | None = None,
    clock: Clock | None = None,
    build_fn: Callable[..., object] | None = None,
    start_worker: bool = True,
) -> FastAPI:
    """The service over ``store``; with every default it configures itself from the environment.

    ``clock`` returns epoch seconds. ``build_fn`` builds one tensor for the queue worker;
    ``start_worker=False`` leaves that worker paused.
    """
    settings = Settings.from_env()
    the_store = store if store is not None else store_mod.store_from_env()
    now = clock if clock is not None else time.time
    app = FastAPI(
        title="PortfolioSight build service",
        version=ENGINE_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install_handlers(app)

    @app.middleware("http")
    async def _gate(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not gate_open(request.headers.get(GATE_HEADER), settings.gate_secret):
            return forbidden()
        return await call_next(request)

    @app.get("/v1/health")
    def health() -> JSONResponse:
        generation = current_generation(the_store)
        meta = _optional_json(the_store, generation_key(generation)) if generation else None
        asof = meta.get("asof") if isinstance(meta, dict) else None
        behind = None
        if asof is not None:
            today = generation_date(datetime.fromtimestamp(now(), tz=UTC))
            behind = trading_days_behind(date.fromisoformat(asof), today)
        body = {
            "status": "ok",
            "version": ENGINE_VERSION,
            "generation": generation,
            "asof": asof,
            "asof_trading_days_behind": behind,
            "queue": {"depth": 0, "building": False},
            "nightly": _optional_json(the_store, STATUS_KEY),
        }
        return JSONResponse(body, headers=NO_STORE)

    return app


def __getattr__(name: str) -> Any:
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
