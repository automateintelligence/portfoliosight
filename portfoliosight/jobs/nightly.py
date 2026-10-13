"""The nightly run (spec 5.4): refresh, build the preset tensors, publish, prune.

    python -m portfoliosight.jobs.nightly

Steps: (1) ``D_G`` and ``G``; a generation already published skips to step 4. (2) Refresh
tier 1. (3) Write ``meta/{G}/generation.json`` if absent, build every preset tensor whose key is
missing, and only when all twelve exist write ``meta/{G}/presets.json`` and switch
``meta/current.json``. (4) Refresh tiers 2 and 3 within the provider budget. (5) Delete every
generation older than the one before the current. (6) Write ``meta/status.json``. (7) Evict the
scratch cache. A rerun after an interruption resumes at the first missing tensor; nothing under
``meta/{G}/`` is ever rewritten.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from portfoliosight.api.hashing import universe_hash
from portfoliosight.api.presets import (
    LOOKBACKS,
    preset_definitions,
    preset_funds,
    presets_body,
    tensor_key,
)
from portfoliosight.api.queue import BUILD_FAILED, build_job
from portfoliosight.data import cache as cache_mod
from portfoliosight.data import download
from portfoliosight.data import store as store_mod
from portfoliosight.data.calendar import generation_date, generation_id
from portfoliosight.data.secrets import RedactingFilter, install_redaction
from portfoliosight.engine import ENGINE_VERSION
from portfoliosight.engine.caps import RULE
from portfoliosight.engine.stats import EW_HALFLIFE_DAYS
from portfoliosight.engine.windows import LOOKBACK_ROWS
from portfoliosight.jobs.build import BuildRefused, generation_key

logger = logging.getLogger(__name__)
install_redaction([logger.name])

CURRENT_KEY = "meta/current.json"
STATUS_KEY = "meta/status.json"
PROVIDERS_ENV = "PS_NIGHTLY_PROVIDERS"
FIXTURE_DIR_ENV = "PS_FIXTURE_DIR"
FIXED_NOW_ENV = "PS_FIXED_NOW"
MAX_STATUS_ERRORS = 200
_GENERATION_RE = re.compile(r"(\d{4}-\d{2}-\d{2})-([0-9.]+)")

BuildFn = Callable[..., object]


def presets_key(generation: str) -> str:
    return f"meta/{generation}/presets.json"


def _current(store: store_mod.Store) -> str | None:
    try:
        pointer = store_mod.get_json(store, CURRENT_KEY)
    except KeyError:
        return None
    return pointer.get("generation") if isinstance(pointer, dict) else None


def _order(generation: str) -> tuple[str, tuple[int, ...]]:
    """Sort key of a generation id: its date, then its engine version."""
    day, version = generation[:10], generation[11:]
    return day, tuple(int(part) for part in version.split(".") if part)


def stored_generations(store: store_mod.Store) -> list[str]:
    """Every generation with a key under ``meta/`` or ``tensors/``, oldest first."""
    found: set[str] = set()
    for prefix in ("meta/", "tensors/"):
        for key in store.list(prefix):
            parts = key.split("/")
            if len(parts) >= 3 and _GENERATION_RE.fullmatch(parts[1]):
                found.add(parts[1])
    return sorted(found, key=_order)


def prune_generations(store: store_mod.Store, current: str) -> list[str]:
    """Delete every generation older than the one before ``current``; returns those deleted."""
    older = [g for g in stored_generations(store) if _order(g) < _order(current)]
    doomed = older[:-1]
    for generation in doomed:
        for key in store.list(f"meta/{generation}/") + store.list(f"tensors/{generation}/"):
            store.delete(key)
    return doomed


def _generation_meta(generation: str, d_g: date, created_at: datetime) -> dict[str, Any]:
    return {
        "generation": generation,
        "asof": d_g.isoformat(),
        "engine_version": ENGINE_VERSION,
        "bounds_rule": RULE,
        "lookbacks": {
            lookback: {
                "rows": rows,
                "ew_halflife_days": EW_HALFLIFE_DAYS if lookback == "ew" else None,
            }
            for lookback, rows in LOOKBACK_ROWS.items()
        },
        "created_at": created_at.isoformat(),
    }


def _error_text(exc: BaseException) -> str:
    return RedactingFilter().redact(f"{type(exc).__name__}: {exc}")[: download.MAX_ERROR_CHARS]


def _build_presets(
    store: store_mod.Store, generation: str, build: BuildFn, errors: list[dict[str, str]]
) -> tuple[dict[str, float], dict[str, int], bool]:
    """Build every missing preset tensor; ``(seconds, built, complete)`` per preset id.

    A build that raises is recorded and the run goes on to the next key: publication needs all
    of them anyway. An interruption that is not an ``Exception`` ends the run here.
    """
    seconds: dict[str, float] = {}
    built: dict[str, int] = {}
    complete = True
    for preset in preset_definitions():
        funds = preset_funds(preset)
        uhash = universe_hash(funds)
        started = time.perf_counter()
        built[preset.id] = 0
        for lookback in LOOKBACKS:
            key = tensor_key(generation, uhash, lookback)
            if store.exists(key):
                continue
            try:
                build(
                    store,
                    generation,
                    uhash,
                    lookback,
                    funds,
                    universe_name=preset.name,
                    preset_id=preset.id,
                )
            except Exception as exc:
                code = exc.code if isinstance(exc, BuildRefused) else BUILD_FAILED
                logger.error("preset %s %s: %s: %s", preset.id, lookback, code, _error_text(exc))
                errors.append(
                    {
                        "step": "build",
                        "preset": preset.id,
                        "lookback": lookback,
                        "error": f"{code}: {_error_text(exc)}",
                    }
                )
            if store.exists(key):
                built[preset.id] += 1
            else:
                complete = False
        seconds[preset.id] = round(time.perf_counter() - started, 3)
    return seconds, built, complete


def run(
    *,
    store: store_mod.Store,
    now: datetime,
    providers: Mapping[str, Any],
    build_fn: BuildFn | None = None,
) -> dict[str, Any]:
    """One nightly run against ``store``; returns what it wrote to ``meta/status.json``.

    ``now`` is the timezone-aware start of the run; ``D_G`` and ``G`` derive from it.
    ``providers`` maps ``"tiingo"`` and ``"tsp"`` to price providers. ``build_fn`` builds and
    writes one tensor (default ``portfoliosight.api.queue.build_job``).
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    build = build_fn if build_fn is not None else build_job
    begun = time.monotonic()

    def clock() -> datetime:
        return (now + timedelta(seconds=time.monotonic() - begun)).astimezone(UTC)

    d_g = generation_date(now)
    generation = generation_id(d_g, ENGINE_VERSION)
    errors: list[dict[str, str]] = []
    refreshed: dict[str, int] = {}
    status: dict[str, Any] = {
        "started": now.astimezone(UTC).isoformat(),
        "finished": None,
        "D_G": d_g.isoformat(),
        "generation": generation,
        "published": _current(store) == generation,
        "refreshed_per_tier": refreshed,
        "preset_build_seconds": {},
        "preset_tensors_built": {},
        "pruned": [],
        "errors": errors,
        "error_count": 0,
    }

    def refresh(tiers: tuple[int, ...]) -> None:
        report = download.RunReport()
        download.run(
            "refresh",
            store=store,
            providers=providers,
            clock=clock,
            sleep=time.sleep,
            tiers=tiers,
            report=report,
        )
        for tier, count in report.refreshed.items():
            refreshed[str(tier)] = refreshed.get(str(tier), 0) + count
        errors.extend({"step": "refresh", **error} for error in report.errors)
        if report.stopped:
            errors.append({"step": "refresh", "error": report.stopped})

    def write_status() -> None:
        status["error_count"] = len(errors)
        status["errors"] = errors[:MAX_STATUS_ERRORS]
        store_mod.put_json(store, STATUS_KEY, status)

    try:
        if not status["published"]:
            refresh((1,))
            if not store.exists(generation_key(generation)):
                store_mod.put_json(
                    store, generation_key(generation), _generation_meta(generation, d_g, clock())
                )
            seconds, built, complete = _build_presets(store, generation, build, errors)
            status["preset_build_seconds"] = seconds
            status["preset_tensors_built"] = built
            if complete:
                if not store.exists(presets_key(generation)):
                    body = presets_body(generation, d_g.isoformat(), store)
                    store_mod.put_json(store, presets_key(generation), body)
                pointer = {"generation": generation, "published_at": clock().isoformat()}
                store_mod.put_json(store, CURRENT_KEY, pointer)
                status["published"] = True
                logger.info("published generation %s", generation)
            else:
                errors.append(
                    {"step": "publish", "error": "not every preset tensor exists; not published"}
                )
                logger.error("generation %s is incomplete and was not published", generation)
        refresh((2, 3))
        current = _current(store)
        if current is not None:
            status["pruned"] = prune_generations(store, current)
    except Exception as exc:
        errors.append({"step": "run", "error": _error_text(exc)})
        write_status()
        raise
    status["finished"] = clock().isoformat()
    write_status()
    cache_mod.evict(cache_dir=cache_mod.cache_dir_from_env())
    return status


def _providers_from_env() -> dict[str, Any]:
    """The real providers, or the offline one when ``PS_NIGHTLY_PROVIDERS=fixture``."""
    kind = os.environ.get(PROVIDERS_ENV, "").strip().lower()
    if kind == "fixture":
        from portfoliosight.data.providers.fixture import FixtureProvider

        offline = FixtureProvider(os.environ.get(FIXTURE_DIR_ENV) or "")
        return {download.BUDGETED_PROVIDER: offline, download.TSP_PROVIDER: offline}
    if kind:
        raise ValueError(f"{PROVIDERS_ENV} must be 'fixture' or unset, not {kind!r}")
    from portfoliosight.data.providers.tiingo import TiingoProvider
    from portfoliosight.data.providers.tsp import TspProvider

    return {download.BUDGETED_PROVIDER: TiingoProvider(), download.TSP_PROVIDER: TspProvider()}


def _now_from_env() -> datetime:
    """The run's start: the wall clock, or ``PS_FIXED_NOW`` (ISO, timezone-aware) offline."""
    fixed = os.environ.get(FIXED_NOW_ENV, "").strip()
    if not fixed:
        return datetime.now(UTC)
    moment = datetime.fromisoformat(fixed)
    if moment.tzinfo is None:
        raise ValueError(f"{FIXED_NOW_ENV} must carry a UTC offset")
    return moment


def main() -> int:
    """The container entry point: 0 when the run's generation is published, else 1."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        store = store_mod.store_from_env()
        providers = _providers_from_env()
        now = _now_from_env()
    except (store_mod.StoreConfigError, download.ProviderError, ValueError, OSError) as exc:
        print(f"nightly not run: {exc}", file=sys.stderr)
        return 2
    status = run(store=store, now=now, providers=providers)
    return 0 if status["published"] else 1


if __name__ == "__main__":
    from portfoliosight.data.secrets import load_env

    load_env()
    raise SystemExit(main())
