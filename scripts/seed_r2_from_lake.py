#!/usr/bin/env python3
"""Seed the canonical store from the QSE lake, once, from the laptop (spec 5.4).

    python scripts/seed_r2_from_lake.py [--lake PATH] --adjusted-through 2026-02-27 [--dry-run]

Each ``<SYMBOL>.parquet`` of the lake becomes ``prices/<SYMBOL>.parquet``: every row kept,
``close`` unchanged, ``tr_index = adj_close / adj_close[0]`` up to ``--adjusted-through`` and
price-only after it, with a manifest entry ``source: seed``, ``status: pending``. Before anything
is written, every file is checked: a row after ``--adjusted-through`` whose ``adj_close`` differs
from ``close`` stops the run. The lake is only ever read. The target store comes from the
environment (``PS_STORE``, ``PS_LOCAL_STORE_DIR``, or the R2 variables).
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from portfoliosight.data import manifest as manifest_mod  # noqa: E402
from portfoliosight.data import store as store_mod  # noqa: E402
from portfoliosight.data.manifest import ManifestEntry  # noqa: E402
from portfoliosight.data.universe import load_tiers  # noqa: E402

DEFAULT_LAKE = "~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core/eod_history"
MIN_FILES = 1_000
UPLOAD_THREADS = 8
LAKE_COLUMNS = ["date", "close", "adj_close"]


@dataclass
class Checked:
    symbol: str
    path: Path
    rows: int
    latest_adjustment: str | None  # last date with adj_close != close
    drift: str | None  # first date after --adjusted-through with adj_close != close
    unusable: str | None  # why the file cannot be seeded at all


def _read(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path, columns=LAKE_COLUMNS)
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    return frame.sort_values("date").reset_index(drop=True)


def _iso(values: Any) -> list[str]:
    return [str(value)[:10] for value in values]


def check(path: Path, through: date) -> Checked:
    """Read one lake file and find its latest adjustment and any drift after ``through``."""
    frame = _read(path)
    days = _iso(frame["date"])
    close = frame["close"].to_numpy(dtype=float)
    adj = frame["adj_close"].to_numpy(dtype=float)
    differs = ~((adj == close) | (np.isnan(adj) & np.isnan(close)))
    inside = np.array([day <= through.isoformat() for day in days], dtype=bool)
    adjusted = [day for day, flag in zip(days, differs, strict=True) if flag]
    drift = [day for day, flag in zip(days, differs & ~inside, strict=True) if flag]
    unusable = None
    if not inside.any():
        unusable = f"no row on or before {through.isoformat()}"
    elif not (np.isfinite(adj[inside]).all() and (adj[inside] > 0).all()):
        unusable = "adj_close is missing or not positive in the adjusted range"
    elif not (np.isfinite(close).all() and (close > 0).all()):
        unusable = "close is missing or not positive"
    return Checked(
        symbol=path.stem.upper(),
        path=path,
        rows=len(frame),
        latest_adjustment=adjusted[-1] if adjusted else None,
        drift=drift[0] if drift else None,
        unusable=unusable,
    )


def to_record(path: Path, through: date) -> pd.DataFrame:
    """The canonical record of one lake file: price-only after ``through``."""
    frame = _read(path)
    adj = frame["adj_close"].to_numpy(dtype=float)
    tr_index = adj / adj[0]
    tr_index[(frame["date"] > pd.Timestamp(through)).to_numpy()] = np.nan
    return pd.DataFrame(
        {
            "date": frame["date"],
            "close": frame["close"].to_numpy(dtype=float),
            "tr_index": tr_index,
            "div_cash": np.nan,
            "split_factor": np.nan,
        }
    )


def _fail(message: str) -> int:
    print(f"seed refused: {message}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the canonical store from the QSE lake.")
    parser.add_argument("--lake", default=DEFAULT_LAKE, help="directory of <SYMBOL>.parquet files")
    parser.add_argument("--adjusted-through", required=True, type=date.fromisoformat)
    parser.add_argument("--dry-run", action="store_true", help="check and report, write nothing")
    args = parser.parse_args(argv)
    through: date = args.adjusted_through

    lake = Path(args.lake).expanduser()
    if not lake.is_dir():
        return _fail(f"the lake path {lake} does not exist")
    files = sorted(lake.glob("*.parquet"))
    if len(files) < MIN_FILES:
        return _fail(
            f"the lake path {lake} holds {len(files)} parquet files, fewer than {MIN_FILES:,}"
        )

    with ThreadPoolExecutor(UPLOAD_THREADS) as pool:
        checked = list(pool.map(lambda path: check(path, through), files))

    print(f"lake {lake}: {len(checked)} parquet files, adjusted through {through.isoformat()}")
    for item in checked:
        note = f"  NOT SEEDED: {item.unusable}" if item.unusable else ""
        print(f"{item.symbol}: latest adjustment {item.latest_adjustment or 'none'}{note}")
    drifted = [item for item in checked if item.drift]
    usable = [item for item in checked if not item.unusable]
    latest = max(
        (item.latest_adjustment for item in checked if item.latest_adjustment), default=None
    )
    print(
        f"assertion report: {len(checked)} symbols checked, {len(usable)} to seed, "
        f"{len(checked) - len(usable)} not seedable, {len(drifted)} with adj_close != close "
        f"after {through.isoformat()}; latest adjustment in the lake: {latest or 'none'}"
    )
    if drifted:
        for item in drifted:
            print(
                f"{item.symbol}: adj_close != close on {item.drift}, after --adjusted-through "
                f"{through.isoformat()}",
                file=sys.stderr,
            )
        return _fail(f"{len(drifted)} file(s) carry adjustments after {through.isoformat()}")
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    try:
        store = store_mod.store_from_env()
    except store_mod.StoreConfigError as exc:
        return _fail(str(exc))
    manifest = manifest_mod.load_manifest(store)
    # A symbol the provider already filled or refreshed is never overwritten by its seed.
    kept = {s for s, entry in manifest.symbols.items() if entry.source != "seed"}
    todo = [item for item in usable if item.symbol not in kept]
    size_of = getattr(store, "size", None)

    def upload(item: Checked) -> tuple[str, str, str, bool]:
        record = to_record(item.path, through)
        data = store_mod.record_to_bytes(record)
        key = store_mod.record_key(item.symbol)
        resumed = size_of is not None and size_of(key) == len(data)
        if not resumed:
            store.put(key, data)
        return (
            item.symbol,
            str(record["date"].iloc[0])[:10],
            str(record["date"].iloc[-1])[:10],
            resumed,
        )

    with ThreadPoolExecutor(UPLOAD_THREADS) as pool:
        uploaded = list(pool.map(upload, todo))

    universe = load_tiers().info()
    for symbol, first_day, last_day, _ in uploaded:
        known = universe.get(symbol)
        entry = ManifestEntry(
            name=symbol,
            kind=(known.kind if known and known.kind else "etf" if known else "stock"),
            tier=known.tier if known else 3,
            income=known.income if known else False,
            source="seed",
            first_date=date.fromisoformat(first_day),
            last_date=date.fromisoformat(last_day),
            adjusted_through=through,
            status="pending",
            reason=manifest_mod.REASON_UNVERIFIED.format(date=through.isoformat()),
        )
        manifest.symbols[symbol] = entry
    store_mod.put_json(store, manifest_mod.MANIFEST_KEY, manifest.to_json())
    skipped = sum(1 for *_, resumed in uploaded if resumed)
    print(
        f"seeded {len(uploaded)} symbols ({skipped} already in the store with the same size, "
        f"{len(usable) - len(todo)} left to the provider's record)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
