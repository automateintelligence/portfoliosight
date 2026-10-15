"""The FastAPI service (spec 6).

    uvicorn portfoliosight.api.app:app

``app`` is created on first access, from the environment, so importing this module starts
nothing and needs no secret.

Every request must carry the gate secret; nothing is looked up, counted or read before that
check. Responses name tensors by their public ``/api/...`` path, which the Worker maps back to
``/v1/...``.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import FastAPI, Path, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from portfoliosight.api.errors import (
    NO_STORE,
    ApiError,
    error_response,
    forbidden,
    install_handlers,
    unexpected_error,
)
from portfoliosight.api.gate import GATE_HEADER, TIER_HEADER, caller_tier, gate_open
from portfoliosight.api.hashing import universe_hash
from portfoliosight.api.limiter import POSTS_PER_MINUTE, REQUESTS_PER_MINUTE, RateLimiter
from portfoliosight.api.models import (
    GENERATION_PATTERN,
    HASH_PATTERN,
    MAX_BODY_BYTES,
    LookbackId,
    RangeRequest,
    TensorRequest,
    parse_range_request,
    parse_tensor_request,
    payload_too_large,
)
from portfoliosight.api.presets import presets_body, tensor_key
from portfoliosight.api.queue import BuildQueue, JobState, QueueBusy, build_job
from portfoliosight.api.ranges import RangeModels, range_body
from portfoliosight.api.settings import Settings
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.calendar import generation_date, trading_days_behind
from portfoliosight.engine import ENGINE_VERSION
from portfoliosight.jobs.build import generation_key

CURRENT_KEY = "meta/current.json"
STATUS_KEY = "meta/status.json"
CLIENT_IP_HEADER = "cf-connecting-ip"
JSON = "application/json"
CACHE_PRESETS = "public, max-age=300"
CACHE_SYMBOLS = "public, max-age=3600"
CACHE_TENSOR = "public, max-age=86400, immutable"

Clock = Callable[[], float]


def presets_key(generation: str) -> str:
    return f"meta/{generation}/presets.json"


def _optional_json(store: store_mod.Store, key: str) -> Any:
    try:
        return store_mod.get_json(store, key)
    except KeyError:
        return None


def current_generation(store: store_mod.Store) -> str | None:
    """The published generation, ``None`` before the first nightly run has published one."""
    pointer = _optional_json(store, CURRENT_KEY)
    return pointer.get("generation") if isinstance(pointer, dict) else None


def _no_generation() -> ApiError:
    return ApiError(503, "no_generation", "No generation has been published yet.")


def _rate_limited() -> JSONResponse:
    return error_response(429, "rate_limited", "Too many requests; try again in a minute.")


def _client_ip(request: Request) -> str:
    """The limiter key: the visitor's address as Cloudflare reports it (spec 6)."""
    reported = request.headers.get(CLIENT_IP_HEADER)
    if reported:
        return reported
    return request.client.host if request.client is not None else "unknown"


async def _read_body(request: Request) -> bytes:
    """The request body, refused as soon as it is known to exceed 16 KB."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise payload_too_large()
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise payload_too_large()
        chunks.append(chunk)
    return b"".join(chunks)


def _job_response(state: JobState) -> JSONResponse:
    """The spec 6 answer for a job state: 200 ready, 202 queued or building, 409 failed."""
    if state.status == "ready":
        body: dict[str, Any] = {
            "status": "ready",
            "generation": state.generation,
            "hash": state.hash,
            "url": state.url,
        }
        return JSONResponse(body, status_code=200, headers=NO_STORE)
    if state.status == "failed":
        body = {
            "status": "failed",
            "error": state.error,
            "attempts": state.attempts,
            "retry": bool(state.retry),
            "details": state.details,
        }
        return JSONResponse(body, status_code=409, headers=NO_STORE)
    body = {
        "status": state.status,
        "generation": state.generation,
        "hash": state.hash,
        "position": state.position,
        "eta_s": state.eta_s,
    }
    return JSONResponse(body, status_code=202, headers=NO_STORE)


def create_app(
    *,
    store: store_mod.Store | None = None,
    clock: Clock | None = None,
    build_fn: Callable[..., object] | None = None,
    start_worker: bool = True,
) -> FastAPI:
    """The service over ``store``; with every default it configures itself from the environment.

    ``clock`` returns epoch seconds and is the limiter's only time source. ``build_fn`` builds
    one tensor for the queue worker (default ``queue.build_job``); ``start_worker=False`` leaves
    that worker paused, so accepted jobs stay queued.
    """
    settings = Settings.from_env()
    the_store = store if store is not None else store_mod.store_from_env()
    now = clock if clock is not None else time.time
    queue = BuildQueue(
        build_fn if build_fn is not None else build_job, the_store, now, start_worker=False
    )
    requests_limiter = RateLimiter(REQUESTS_PER_MINUTE, now)
    posts_limiter = RateLimiter(POSTS_PER_MINUTE, now)
    range_models = RangeModels(the_store)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if start_worker:
            queue.resume()
        yield
        queue.close()

    app = FastAPI(
        title="PortfolioSight build service",
        version=ENGINE_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.queue = queue
    install_handlers(app)

    @app.middleware("http")
    async def _gate_then_limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not gate_open(request.headers.get(GATE_HEADER), settings.gate_secret):
            return forbidden()
        if not requests_limiter.admit(_client_ip(request)):
            return _rate_limited()
        try:
            return await call_next(request)
        except Exception as exc:
            return unexpected_error(exc)

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
            "status": "ok" if generation else "initializing",
            "version": ENGINE_VERSION,
            "generation": generation,
            "asof": asof,
            "asof_trading_days_behind": behind,
            "queue": {"depth": queue.depth, "building": queue.building},
            "nightly": _optional_json(the_store, STATUS_KEY),
        }
        return JSONResponse(body, headers=NO_STORE)

    @app.get("/v1/presets")
    def presets() -> Response:
        generation = current_generation(the_store)
        if generation is None:
            raise _no_generation()
        headers = {"Cache-Control": CACHE_PRESETS}
        try:
            stored = the_store.get(presets_key(generation))
        except KeyError:
            meta = _optional_json(the_store, generation_key(generation)) or {}
            asof = str(meta.get("asof") or generation[:10])
            return JSONResponse(presets_body(generation, asof, the_store), headers=headers)
        return Response(stored, media_type=JSON, headers=headers)

    @app.get("/v1/symbols")
    def symbols() -> Response:
        try:
            stored = the_store.get(manifest_mod.SYMBOLS_KEY)
        except KeyError:
            raise ApiError(503, "no_catalog", "The symbol catalog is not written yet.") from None
        return Response(stored, media_type=JSON, headers={"Cache-Control": CACHE_SYMBOLS})

    def _submit(request: TensorRequest) -> JSONResponse:
        catalog = manifest_mod.load_manifest(the_store).symbols
        unknown = [fund.id for fund in request.funds if fund.id not in catalog]
        if unknown:
            raise ApiError(
                400,
                "unknown_symbols",
                "Some funds are not in the catalog.",
                {"symbols": unknown},
            )
        generation = current_generation(the_store)
        if generation is None:
            raise _no_generation()
        policy = request.policy()
        try:
            state = queue.submit(generation, universe_hash(policy), request.lookback, policy)
        except QueueBusy:
            raise ApiError(
                503, "busy", "The build queue is full; try again in a few minutes."
            ) from None
        return _job_response(state)

    def _menu_max(request: Request) -> int:
        """The caller's menu limit: its tier counts only beside the gate secret (gate.py)."""
        tier = caller_tier(
            request.headers.get(GATE_HEADER), request.headers.get(TIER_HEADER), settings.gate_secret
        )
        return settings.menu_max(tier)

    @app.post("/v1/tensors")
    async def post_tensors(request: Request) -> JSONResponse:
        if not posts_limiter.admit(_client_ip(request)):
            return _rate_limited()
        parsed = parse_tensor_request(await _read_body(request), max_funds=_menu_max(request))
        return await run_in_threadpool(_submit, parsed)

    def _range(request: RangeRequest) -> JSONResponse:
        key = (request.generation, request.hash, request.lookback)
        return JSONResponse(range_body(range_models, key, request.weights), headers=NO_STORE)

    @app.post("/v1/range")
    async def post_range(request: Request) -> JSONResponse:
        parsed = parse_range_request(await _read_body(request), max_funds=_menu_max(request))
        return await run_in_threadpool(_range, parsed)

    @app.get("/v1/tensors/{generation}/{uhash}/{lookback}")
    def get_tensor(
        generation: Annotated[str, Path(pattern=GENERATION_PATTERN)],
        uhash: Annotated[str, Path(pattern=HASH_PATTERN)],
        lookback: LookbackId,
    ) -> Response:
        state = queue.state(generation, uhash, lookback)
        if state is not None:
            return _job_response(state)
        try:
            stored = the_store.get(tensor_key(generation, uhash, lookback))
        except KeyError:
            raise ApiError(
                404, "unknown_tensor", "No tensor was requested under this address."
            ) from None
        etag = f'"{hashlib.sha256(stored).hexdigest()[:32]}"'
        return Response(
            stored, media_type=JSON, headers={"ETag": etag, "Cache-Control": CACHE_TENSOR}
        )

    return app


def __getattr__(name: str) -> Any:
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
