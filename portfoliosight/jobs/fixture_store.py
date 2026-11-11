"""A small local store for tests and the local container run (plan task 4.8).

It turns the synthetic returns fixture ``tests/fixtures/synthetic_23.parquet`` into canonical
records for the 23 guide funds, adds five synthetic TSP funds, the funds of the research menu
that the guide menu does not already hold, and the catalog's one converted fund (FIENX, whose
data ended on 2024-10-30 and which is not served), and writes the catalog as it stands on the
fixture's last day. Every fund of every preset is in it, so a nightly run builds each preset
tensor. Nothing in it is market data.
"""

from __future__ import annotations

import json
import os
import zlib
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.manifest import Manifest, ManifestEntry
from portfoliosight.data.universe import REPO_ROOT, TSP_FUNDS, load_presets, load_tiers

FIXTURE_RETURNS = REPO_ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
METADATA_KEY = b"portfoliosight"
TSP_CORE = ("TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I")
# The tier 2 fund whose data has ended (spec 5.1): in the catalog with its reason, never served.
CONVERTED_FUND = "FIENX"
CONVERTED_NAME = "Fidelity International Enhanced Index Fund"
CONVERTED_LAST_DAY = date(2024, 10, 30)
CATALOG_AT = datetime(2026, 10, 13, 9, 5, 11, tzinfo=UTC)
# Annual drift and volatility of the synthetic funds this module adds; the G Fund never falls.
_MOMENTS = {
    "TSP-G": (0.035, 0.0),
    "TSP-F": (0.030, 0.045),
    "TSP-C": (0.085, 0.160),
    "TSP-S": (0.090, 0.200),
    "TSP-I": (0.060, 0.170),
    CONVERTED_FUND: (0.060, 0.170),
}
# The research menu's funds that the guide menu lacks, with the name, kind, annual drift and
# annual volatility of the synthetic record each gets (the seeds are the symbols themselves, so
# a fund's record never depends on another's).
_PRESET_FUNDS: dict[str, tuple[str, str, float, float]] = {
    "SPY": ("SPDR S&P 500 ETF Trust", "etf", 0.080, 0.165),
    "IWM": ("iShares Russell 2000 ETF", "etf", 0.085, 0.215),
    "IWD": ("iShares Russell 1000 Value ETF", "etf", 0.075, 0.170),
    "EEM": ("iShares MSCI Emerging Markets ETF", "etf", 0.070, 0.230),
    "IYR": ("iShares U.S. Real Estate ETF", "etf", 0.070, 0.220),
    "TLT": ("iShares 20+ Year Treasury Bond ETF", "etf", 0.035, 0.140),
    "IEF": ("iShares 7-10 Year Treasury Bond ETF", "etf", 0.030, 0.065),
    "SHY": ("iShares 1-3 Year Treasury Bond ETF", "etf", 0.020, 0.015),
    "VIPSX": (
        "Vanguard Inflation-Protected Securities Fund Investor Shares",
        "mutual_fund",
        0.030,
        0.055,
    ),
    "GE": ("General Electric Co", "stock", 0.050, 0.290),
    "MSFT": ("Microsoft Corp", "stock", 0.130, 0.260),
    "XOM": ("Exxon Mobil Corp", "stock", 0.070, 0.230),
    "PFE": ("Pfizer Inc", "stock", 0.050, 0.210),
    "C": ("Citigroup Inc", "stock", 0.040, 0.340),
    "WMT": ("Walmart Inc", "stock", 0.090, 0.180),
    "AIG": ("American International Group Inc", "stock", 0.040, 0.330),
    "INTC": ("Intel Corp", "stock", 0.060, 0.300),
}
_MOMENTS.update({symbol: (drift, vol) for symbol, (_, _, drift, vol) in _PRESET_FUNDS.items()})
_TRADING_DAYS = 252
_DEFAULT_CLOSE = 100.0


def _day(value: object) -> date:
    return date.fromisoformat(str(value)[:10])


def fixture_asof(returns_file: Path = FIXTURE_RETURNS) -> date:
    """The fixture's last day: the ``D_G`` its catalog is written for."""
    return _day(pd.read_parquet(returns_file, columns=[]).index.max())


def _record(calendar: pd.DatetimeIndex, returns: np.ndarray, last_close: float | None):
    """The canonical record of one fund: rows from the day before its first return on."""
    known = np.nonzero(~np.isnan(returns))[0]
    first, last = int(known[0]), int(known[-1])
    if np.isnan(returns[first : last + 1]).any():
        raise ValueError("the fixture has a fund with a gap inside its history")
    growth = np.concatenate(([1.0], np.cumprod(1.0 + returns[first : last + 1])))
    if first > 0:
        opening = calendar[first - 1]
    else:  # the weekday before the calendar starts carries the index value 1.0
        opening = calendar[0] - pd.offsets.BDay(1)
    dates = pd.DatetimeIndex([opening]).append(calendar[first : last + 1])
    scale = (last_close if last_close is not None else _DEFAULT_CLOSE) / growth[-1]
    return pd.DataFrame(
        {
            "date": dates.to_numpy().astype("datetime64[ns]"),
            "close": growth * scale,
            "tr_index": growth,
            "div_cash": 0.0,
            "split_factor": 1.0,
        }
    )


def _seeded_returns(symbol: str, rows: int) -> np.ndarray:
    drift, vol = _MOMENTS[symbol]
    rng = np.random.default_rng(zlib.crc32(symbol.encode()))
    noise = rng.normal(0.0, vol / np.sqrt(_TRADING_DAYS), size=rows)
    return drift / _TRADING_DAYS + noise


def write_fixture_store(
    directory: str | os.PathLike[str], *, returns_file: Path = FIXTURE_RETURNS
) -> store_mod.LocalStore:
    """Write records and an ``ok`` catalog at the fixture's ``D_G`` into ``directory``.

    No generation is published: ``meta/current.json`` is absent until a nightly run writes it.
    """
    store = store_mod.LocalStore(directory)
    store.check()
    frame = pd.read_parquet(returns_file)
    calendar = pd.DatetimeIndex(frame.index)
    raw = (pq.read_schema(returns_file).metadata or {}).get(METADATA_KEY)
    facts = json.loads(raw)["funds"] if raw else {}
    manifest = Manifest()
    for symbol in frame.columns:
        fact = facts.get(symbol, {})
        record = _record(calendar, frame[symbol].to_numpy(dtype=float), fact.get("last_close"))
        store_mod.put_record(store, symbol, record)
        last = _day(record["date"].iloc[-1])
        served = fact.get("served", True)
        manifest.symbols[symbol] = ManifestEntry(
            name=fact.get("name", symbol),
            kind=fact.get("kind", "etf"),
            tier=1,
            source=fact.get("source", "seed+tiingo"),
            first_date=_day(record["date"].iloc[0]),
            last_date=last,
            adjusted_through=last,
            status="ok" if served else "unavailable",
            reason=fact.get("catalog_reason"),
            fetched_at=fact.get("fetched_at", CATALOG_AT.isoformat()),
        )
    for symbol in TSP_CORE:
        record = _record(calendar, _seeded_returns(symbol, len(calendar)), None)
        store_mod.put_record(store, symbol, record)
        manifest.symbols[symbol] = ManifestEntry(
            name=TSP_FUNDS[symbol],
            kind="tsp",
            tier=1,
            source="tsp",
            first_date=_day(record["date"].iloc[0]),
            last_date=_day(calendar[-1]),
            adjusted_through=_day(calendar[-1]),
            status="ok",
            fetched_at=CATALOG_AT.isoformat(),
        )
    tiers = load_tiers().info()
    for symbol, (name, kind, _, _) in _PRESET_FUNDS.items():
        if symbol in manifest.symbols:  # a fund the synthetic file already holds
            continue
        record = _record(calendar, _seeded_returns(symbol, len(calendar)), None)
        store_mod.put_record(store, symbol, record)
        manifest.symbols[symbol] = ManifestEntry(
            name=name,
            kind=kind,
            tier=tiers[symbol].tier,
            source="tiingo",  # a lake source needs a lake overlay, which this store has none of
            first_date=_day(record["date"].iloc[0]),
            last_date=_day(calendar[-1]),
            adjusted_through=_day(calendar[-1]),
            status="ok",
            fetched_at=CATALOG_AT.isoformat(),
        )
    ended = pd.DatetimeIndex(calendar[calendar <= pd.Timestamp(CONVERTED_LAST_DAY)])
    record = _record(ended, _seeded_returns(CONVERTED_FUND, len(ended)), None)
    store_mod.put_record(store, CONVERTED_FUND, record)
    known = load_tiers().info()[CONVERTED_FUND]  # its tier and the note that explains the end
    converted = ManifestEntry(
        name=CONVERTED_NAME,
        kind="mutual_fund",
        tier=known.tier,
        source="tiingo",
        first_date=_day(record["date"].iloc[0]),
        last_date=CONVERTED_LAST_DAY,
        adjusted_through=CONVERTED_LAST_DAY,
        status="unavailable",
        fetched_at=CATALOG_AT.isoformat(),
    )
    converted.reason = manifest_mod.reason_for(
        converted, converted.status, _day(calendar[-1]), known.note
    )
    manifest.symbols[CONVERTED_FUND] = converted
    absent = sorted({f for preset in load_presets() for f in preset.funds} - set(manifest.symbols))
    if absent:
        raise ValueError(f"the fixture store has no record for preset fund(s) {absent}")
    manifest_mod.write_catalog(store, manifest, CATALOG_AT)
    return store
