"""Build one tensor from the canonical store (spec 6, 4.12, 5.3; engines spec 7).

A build reads ``meta/{G}/generation.json`` for ``D_G``, the catalog as it is now and only the
price records it needs, uses rows up to ``D_G``, and never writes over a tensor that exists.

The volatility model is fitted once per fund set and generation, not per lookback: its files
``models/{G}/{shape16}/garch.json`` and ``pool.npy`` (``shape16`` the first 16 hex digits of the
shape panel's digest) are written before the first tensor that uses them, never overwritten,
read back through the scratch cache, and pruned with their generation.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, time
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from portfoliosight.api.presets import model_key
from portfoliosight.data import cache as cache_mod
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.manifest import ManifestEntry
from portfoliosight.data.returns import build_returns, window_sample
from portfoliosight.engine import ENGINE_VERSION
from portfoliosight.engine.caps import CapsError
from portfoliosight.engine.ladder import LEVELS
from portfoliosight.engine.optimize import NX
from portfoliosight.engine.ranges import ENGINES, METHOD, RangeModel, frame_digest, range_model
from portfoliosight.engine.shape import (
    GarchArtifact,
    artifact_from_json,
    artifact_to_json,
    guarded_splice_dates,
    pool_bytes,
    pool_from_bytes,
    qse_commit,
)
from portfoliosight.engine.stats import RISK_FREE_SOURCES
from portfoliosight.engine.surface import NY
from portfoliosight.engine.tensor import (
    BuildResult,
    FundInput,
    TensorInputs,
    WindowUnavailable,
    build_tensor_full,
    canonical_json,
    shape_panel_for,
)

CUSTOM_MENU_NAME = "Custom menu"
GARCH_FILE = "garch.json"  # the fitted volatility model's parameters, statuses and pool digest
POOL_FILE = "pool.npy"  # its re-standardized shock rows; absent when the model is unavailable


class BuildRefused(Exception):
    """A build that would fail the same way on every attempt; ``code`` names why."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details


class GenerationGone(BuildRefused):
    """The generation's metadata is no longer in the store (the nightly pruned it)."""

    def __init__(self, generation: str):
        super().__init__("generation_gone", f"generation {generation} is no longer stored")


class ArtifactConflict(BuildRefused):
    """An immutable model path already belongs to a different artifact."""

    def __init__(self, key: str):
        super().__init__(
            "artifact_conflict",
            f"stored model artifact conflicts with this build: {key}",
            {"key": key},
        )


class KeyExists(Exception):
    """The tensor key is already written; the first tensor of a key is the one served."""


class RangeUnavailable(Exception):
    """A stored tensor's lookback sample can no longer be rebuilt from the price records."""


def generation_key(generation: str) -> str:
    return f"meta/{generation}/generation.json"


def put_tensor(store: store_mod.Store, key: str, tensor: Mapping[str, Any]) -> None:
    """Write a tensor in its stored form, unless the key exists."""
    if store.exists(key):
        raise KeyExists(key)
    store.put(key, canonical_json(tensor).encode("utf-8"))


class _RecordSource:
    """A store that answers any key with one record: lets a versioned cache path be filled."""

    def __init__(self, store: store_mod.Store, key: str):
        self._store, self._key = store, key

    def get(self, key: str) -> bytes:
        return self._store.get(self._key)


def _cached_record(
    store: store_mod.Store, cache_dir: Path, symbol: str, version: str
) -> pd.DataFrame | None:
    """A symbol's record through the scratch cache; ``None`` when the store has none.

    Records change every night, so the cached file's own path carries the catalog's
    ``fetched_at`` (``version``) it was fetched under: ``prices/{SYMBOL}/{digest}.parquet``.
    The catalog is written after the record, so a file is never older than its name says,
    whatever other process fills the cache at the same time. Other versions are dropped.
    """
    key = store_mod.record_key(symbol)
    digest = hashlib.sha256(version.encode("utf-8")).hexdigest()[:16]
    cache_key = f"prices/{symbol}/{digest}.parquet"
    path = cache_mod.cached_path(cache_dir, cache_key)
    new = not path.is_file()
    try:
        source = cast(store_mod.Store, _RecordSource(store, key))
        cached = cache_mod.fetch_into_cache(source, cache_key, cache_dir=cache_dir)
    except KeyError:
        return None
    try:
        data = cached.read_bytes()
    except FileNotFoundError:  # evicted by another process between the fetch and the read
        try:
            data = store.get(key)
        except KeyError:
            return None
    if new:
        for other in path.parent.glob("*.parquet"):
            if other != path:
                other.unlink(missing_ok=True)
    return store_mod.record_from_bytes(data)


def _upto(record: pd.DataFrame, asof: datetime) -> pd.DataFrame:
    return record.loc[pd.to_datetime(record["date"]) <= asof].reset_index(drop=True)


def _tr_series(record: pd.DataFrame) -> pd.Series:
    index = pd.DatetimeIndex(pd.to_datetime(record["date"]), name="date")
    return pd.Series(record["tr_index"].to_numpy(dtype=float), index=index).dropna()


def _close_on(record: pd.DataFrame, asof: datetime) -> float | None:
    """The raw close dated exactly ``asof``; ``None`` when the fund has no price that day."""
    on_day = record.loc[pd.to_datetime(record["date"]) == asof, "close"]
    if on_day.empty or pd.isna(on_day.iloc[-1]):
        return None
    return float(on_day.iloc[-1])


def _fund_input(
    fund: str, entry: ManifestEntry | None, record: pd.DataFrame | None, asof: datetime
) -> FundInput:
    if entry is None:
        return FundInput(
            id=fund,
            name=fund,
            kind="etf",
            source="tiingo",
            adjusted_through="",
            fetched_at="",
            served=False,
        )
    adjusted = entry.adjusted_through.isoformat() if entry.adjusted_through else ""
    return FundInput(
        id=fund,
        name=entry.name or fund,
        kind=entry.kind,
        source=entry.source,
        adjusted_through=adjusted,
        fetched_at=entry.fetched_at or f"{adjusted}T00:00:00Z",
        last_close=None if record is None else _close_on(record, asof),
        served=entry.status == "ok",
        catalog_reason=entry.reason,
    )


def _splice_date(record: pd.DataFrame) -> str | None:
    """The day a seeded record's provider tail starts (engines spec 4.3, the splice guard).

    Seed rows carry no actions and provider rows do, so it is the first row whose
    ``split_factor`` is known while the row before it is not. A record with actions on every row
    (a provider's, or TSP's 0 and 1) or on none (a seed or lake record) has no splice.
    """
    known = record["split_factor"].notna().to_numpy()
    starts = np.flatnonzero(known[1:] & ~known[:-1])
    if starts.size == 0:
        return None
    return pd.Timestamp(record["date"].iloc[int(starts[0]) + 1]).date().isoformat()


def inputs_from_store(
    store: store_mod.Store,
    *,
    funds: Sequence[Mapping[str, Any]],
    lookback: str,
    asof: date,
    cache_dir: str | os.PathLike[str],
    universe_name: str = CUSTOM_MENU_NAME,
    preset_id: str | None = None,
    allocation: Mapping[str, float] | None = None,
    nx: int = NX,
    ny: int = NY,
    levels: int = LEVELS,
    engines: Sequence[str] = ENGINES,
) -> TensorInputs:
    """The inputs of one (menu, lookback) build at ``D_G`` = ``asof``, from the store as it is now.

    ``funds`` is the requested policy, ``[{"id", "min", "max"}]`` in display order;
    ``allocation`` is the entered mix of a preset, amounts by fund id, when it has one. Reads the
    catalog and the records of the menu's served funds (and of the served risk-free funds)
    through the scratch cache, uses rows up to ``asof``, and writes nothing to the store. Each
    seeded fund's splice date goes with the inputs, for the volatility model's splice guard.
    """
    when = datetime.combine(asof, time())
    catalog = manifest_mod.load_manifest(store).symbols
    root = Path(cache_dir)

    def served_record(symbol: str) -> pd.DataFrame | None:
        entry = catalog.get(symbol)
        if entry is None or entry.status != "ok":
            return None
        record = _cached_record(store, root, symbol, entry.fetched_at or "")
        return None if record is None else _upto(record, when)

    ids = [str(fund["id"]) for fund in funds]
    records = {fund: served_record(fund) for fund in ids}
    priced = {fund: record for fund, record in records.items() if record is not None}
    rf_series = {}
    for symbol in RISK_FREE_SOURCES:
        record = priced[symbol] if symbol in priced else served_record(symbol)
        if record is not None:
            rf_series[symbol] = _tr_series(record).pct_change().dropna()
    splices = {fund: _splice_date(record) for fund, record in priced.items()}
    return TensorInputs(
        funds=[_fund_input(fund, catalog.get(fund), records[fund], when) for fund in ids],
        returns=build_returns(priced),
        lookback=lookback,
        asof=asof,
        universe_name=universe_name,
        preset_id=preset_id,
        requested_bounds=[
            {"id": str(fund["id"]), "min": fund.get("min"), "max": fund.get("max")}
            for fund in funds
        ],
        tr_index={fund: _tr_series(record) for fund, record in priced.items()},
        rf_series=rf_series,
        allocation=allocation,
        engine_version=ENGINE_VERSION,
        nx=nx,
        ny=ny,
        levels=levels,
        engines=tuple(engines),
        splice_dates={fund: day for fund, day in splices.items() if day is not None},
    )


def _cached_bytes(store: store_mod.Store, key: str, cache_dir: Path) -> bytes:
    """``store.get(key)`` through the scratch cache, for a key whose value never changes."""
    path = cache_mod.fetch_into_cache(store, key, cache_dir=cache_dir)
    try:
        return path.read_bytes()
    except FileNotFoundError:  # evicted by another process between the fetch and the read
        return store.get(key)


def load_artifact(
    store: store_mod.Store, generation: str, shape16: str, *, cache_dir: str | os.PathLike[str]
) -> GarchArtifact | None:
    """The volatility model stored under ``models/{generation}/{shape16}/``; ``None`` when the
    store has none there. Its files are read through the scratch cache."""
    root = Path(cache_dir)
    try:
        doc = json.loads(_cached_bytes(store, model_key(generation, shape16, GARCH_FILE), root))
        pool = None
        if doc.get("pool_sha256") is not None:
            pool = pool_from_bytes(
                _cached_bytes(store, model_key(generation, shape16, POOL_FILE), root)
            )
    except KeyError:
        return None
    return artifact_from_json(doc, pool)


def put_artifact(store: store_mod.Store, generation: str, artifact: GarchArtifact) -> None:
    """Store a fitted volatility model under its generation and shape digest.

    The pool goes first and the JSON that describes it last, so a reader that finds the JSON
    finds its pool. Existing files must hold the same bytes, even on a cache hit. Check both
    before completing a partial write, then use the store's conditional insert when available:
    another builder's matching write is harmless, a conflicting one refuses this build.
    """
    shape16 = artifact.sample_sha256[:16]
    files = []
    if artifact.pool is not None:
        files.append((POOL_FILE, pool_bytes(artifact)))
    files.append((GARCH_FILE, canonical_json(artifact_to_json(artifact)).encode("utf-8")))
    missing = []
    for name, data in files:
        key = model_key(generation, shape16, name)
        try:
            existing = store.get(key)
        except KeyError:
            missing.append((key, data))
        else:
            if existing != data:
                raise ArtifactConflict(key)
    put_if = getattr(store, "put_if", None)
    for key, data in missing:
        if put_if is not None:
            if put_if(key, data, None):
                continue
        elif not store.exists(key):  # the five-method Store interface, for serial callers
            store.put(key, data)
            continue
        if store.get(key) != data:
            raise ArtifactConflict(key)


def build_with_artifacts(
    store: store_mod.Store,
    generation: str,
    inputs: TensorInputs,
    *,
    cache_dir: str | os.PathLike[str],
    workers: int | None = None,
) -> tuple[BuildResult, bool]:
    """``build_tensor_full`` with the volatility model taken from, and kept in, ``store``.

    When the inputs ask for the volatility model, the fit stored for their shape panel (if any)
    is checked against the full panel identity and fit provenance before reuse. Its files are
    stored or checked before this returns, so a tensor is always written after the model behind
    it. Returns the result and whether a stored fit was used. Invalid or conflicting immutable
    files refuse the build; missing files may be completed by the same deterministic fit.
    """
    offered = None
    if "garch" in inputs.engines:
        try:
            panel = shape_panel_for(inputs)
        except WindowUnavailable:
            panel = None  # the build refuses the window itself, after what it checks first
        if panel is not None:
            key = model_key(generation, panel.sample_sha256[:16], GARCH_FILE)
            try:
                offered = load_artifact(
                    store, generation, panel.sample_sha256[:16], cache_dir=cache_dir
                )
            except (ValueError, TypeError, KeyError, AttributeError, EOFError) as exc:
                raise BuildRefused(
                    "artifact_invalid", f"invalid stored model artifact: {key}", {"key": key}
                ) from exc
            if offered is not None and (
                offered.sample_sha256 != panel.sample_sha256
                or offered.funds != tuple(panel.frame.columns)
                or (offered.rows, offered.start, offered.end)
                != (panel.rows, panel.start, panel.end)
                or offered.splice_dates != guarded_splice_dates(offered.funds, inputs.splice_dates)
                or offered.qse != qse_commit()
                or offered.arch != version("arch")
            ):
                raise ArtifactConflict(key)
            inputs = replace(inputs, garch_artifact=offered)
    result = build_tensor_full(inputs, workers=workers)
    fitted = result.artifacts.get("garch")
    reused = fitted is not None and fitted is offered
    if fitted is not None:
        put_artifact(store, generation, fitted)
    return result, reused


def build_from_store(
    store: store_mod.Store,
    *,
    generation: str,
    funds: Sequence[Mapping[str, Any]],
    lookback: str,
    cache_dir: str | os.PathLike[str],
    universe_name: str = CUSTOM_MENU_NAME,
    preset_id: str | None = None,
    allocation: Mapping[str, float] | None = None,
    nx: int = NX,
    ny: int = NY,
    levels: int = LEVELS,
    engines: Sequence[str] = ENGINES,
) -> dict[str, Any]:
    """The tensor of one (generation, menu, lookback), from the store as it is now.

    ``inputs_from_store`` at the generation's ``D_G``, then ``build_with_artifacts``: the
    volatility model's files are in the store when this returns, the tensor is the caller's to
    write. Raises ``GenerationGone`` when the generation's metadata is absent, and
    ``BuildRefused`` when the window has too little shared history, the caps cannot be met by
    the funds in the window, or the generation belongs to another engine version.
    """
    try:
        meta = store_mod.get_json(store, generation_key(generation))
    except KeyError:
        raise GenerationGone(generation) from None
    if meta.get("engine_version") != ENGINE_VERSION:
        raise BuildRefused(
            "engine_version_mismatch",
            f"generation {generation} belongs to engine {meta.get('engine_version')}, "
            f"this is engine {ENGINE_VERSION}",
        )
    d_g = date.fromisoformat(str(meta["asof"]))
    if f"{d_g.isoformat()}-{ENGINE_VERSION}" != generation:
        raise RuntimeError(f"generation {generation} is not dated {d_g.isoformat()}")
    inputs = inputs_from_store(
        store,
        funds=funds,
        lookback=lookback,
        asof=d_g,
        cache_dir=cache_dir,
        universe_name=universe_name,
        preset_id=preset_id,
        allocation=allocation,
        nx=nx,
        ny=ny,
        levels=levels,
        engines=engines,
    )
    try:
        result, _ = build_with_artifacts(store, generation, inputs, cache_dir=cache_dir)
    except WindowUnavailable as exc:
        details = {"lookback": lookback, "reason": exc.reason, "rows": exc.selection.rows}
        raise BuildRefused("window_unavailable", str(exc), details) from exc
    except CapsError as exc:
        raise BuildRefused("caps_infeasible", str(exc), {"reason": str(exc)}) from exc
    return result.tensor


def range_model_from_store(
    store: store_mod.Store, tensor_key: str, *, cache_dir: str | os.PathLike[str]
) -> RangeModel:
    """The range model (spec 4.9) of a stored tensor, with its lookback sample rebuilt.

    The sample is not in the tensor: fund-level daily returns never leave the service. It is
    read back from the price records, on the same calendar the build used (the menu's served
    funds, the ones a view set aside included), between the window's stored first and last day,
    for the funds the tensor uses; the moments are the tensor's own. Raises ``KeyError`` when
    the store has no tensor under ``tensor_key`` and ``RangeUnavailable`` when a fund's record
    is gone, the window no longer holds two shared days, the tensor was made with another range
    method, or the rebuilt sample is not the build's (its digest, ``lookback.sample_sha256``).
    """
    tensor = json.loads(store.get(tensor_key))
    asof = datetime.combine(date.fromisoformat(tensor["asof"]), time())
    catalog = manifest_mod.load_manifest(store).symbols
    root = Path(cache_dir)
    ids = [fund["id"] for fund in tensor["universe"]["funds"]]
    set_aside = [fund["id"] for fund in tensor["universe"]["excluded"]]

    def stored_record(fund: str, served_only: bool) -> pd.DataFrame | None:
        entry = catalog.get(fund)
        if entry is None or (served_only and entry.status != "ok"):
            return None
        record = _cached_record(store, root, fund, entry.fetched_at or "")
        return None if record is None else _upto(record, asof)

    records: dict[str, pd.DataFrame] = {}
    for fund in ids:
        record = stored_record(fund, served_only=False)
        if record is None:
            raise RangeUnavailable(f"{fund}: its price record is no longer stored")
        records[fund] = record
    for fund in set_aside:
        record = stored_record(fund, served_only=True)
        if record is not None:
            records[fund] = record
    window = tensor["lookback"]
    sample = window_sample(
        build_returns(records),
        ids,
        date.fromisoformat(window["start"]),
        date.fromisoformat(window["end"]),
    )
    if len(sample) < 2:
        raise RangeUnavailable("the window no longer holds two shared days of prices")
    if tensor["range_method"] != dict(METHOD):
        raise RangeUnavailable("this tensor's ranges were made with another method")
    # the very sample of the build, or nothing: a record corrected or a calendar changed since
    # changes the digest, and the endpoint refuses rather than answer from other history
    if frame_digest(sample) != window["sample_sha256"]:
        raise RangeUnavailable("the price history behind this tensor changed after it was built")
    return range_model(sample.to_numpy(), tensor["mu_s"], tensor["cov"])
