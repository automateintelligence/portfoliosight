"""Build one tensor from the canonical store (spec 6, 4.12, 5.3).

A build reads ``meta/{G}/generation.json`` for ``D_G``, the catalog as it is now and only the
price records it needs, uses rows up to ``D_G``, and never writes over a tensor that exists.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, cast

import pandas as pd

from portfoliosight.data import cache as cache_mod
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.manifest import ManifestEntry
from portfoliosight.data.returns import build_returns, window_sample
from portfoliosight.engine import ENGINE_VERSION
from portfoliosight.engine.caps import CapsError
from portfoliosight.engine.ladder import LEVELS
from portfoliosight.engine.optimize import NX
from portfoliosight.engine.ranges import METHOD, RangeModel, frame_digest, range_model
from portfoliosight.engine.stats import RISK_FREE_SOURCES
from portfoliosight.engine.surface import NY
from portfoliosight.engine.tensor import (
    FundInput,
    TensorInputs,
    WindowUnavailable,
    build_tensor,
    canonical_json,
)

CUSTOM_MENU_NAME = "Custom menu"


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
) -> dict[str, Any]:
    """The tensor of one (generation, menu, lookback), from the store as it is now.

    ``funds`` is the requested policy, ``[{"id", "min", "max"}]`` in display order;
    ``allocation`` is the entered mix of a preset, amounts by fund id, when it has one. Raises
    ``GenerationGone`` when the generation's metadata is absent, and ``BuildRefused`` when the
    window has too little shared history, the caps cannot be met by the funds in the window, or
    the generation belongs to another engine version.
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
    asof = datetime.combine(d_g, time())
    catalog = manifest_mod.load_manifest(store).symbols
    root = Path(cache_dir)

    def served_record(symbol: str) -> pd.DataFrame | None:
        entry = catalog.get(symbol)
        if entry is None or entry.status != "ok":
            return None
        record = _cached_record(store, root, symbol, entry.fetched_at or "")
        return None if record is None else _upto(record, asof)

    ids = [str(fund["id"]) for fund in funds]
    records = {fund: served_record(fund) for fund in ids}
    priced = {fund: record for fund, record in records.items() if record is not None}
    rf_series = {}
    for symbol in RISK_FREE_SOURCES:
        record = priced[symbol] if symbol in priced else served_record(symbol)
        if record is not None:
            rf_series[symbol] = _tr_series(record).pct_change().dropna()
    inputs = TensorInputs(
        funds=[_fund_input(fund, catalog.get(fund), records[fund], asof) for fund in ids],
        returns=build_returns(priced),
        lookback=lookback,
        asof=d_g,
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
    )
    try:
        tensor = build_tensor(inputs)
    except WindowUnavailable as exc:
        details = {"lookback": lookback, "reason": exc.reason, "rows": exc.selection.rows}
        raise BuildRefused("window_unavailable", str(exc), details) from exc
    except CapsError as exc:
        raise BuildRefused("caps_infeasible", str(exc), {"reason": str(exc)}) from exc
    if tensor["generation"] != generation:
        raise RuntimeError(f"built {tensor['generation']}, not the requested {generation}")
    return tensor


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
