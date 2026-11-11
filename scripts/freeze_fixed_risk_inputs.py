"""Freeze the fixed-risk experiment's inputs as a private immutable snapshot (protocol v2 §3a, §8).

Usage, from the repo root:
    .venv/bin/python scripts/freeze_fixed_risk_inputs.py [--mirror DIR] [--root DIR] [--repo DIR]
        [--d-star YYYY-MM-DD] [--calendar-end YYYY-MM-DD]
    .venv/bin/python scripts/freeze_fixed_risk_inputs.py --verify SNAPSHOT_DIR

Same immutability, hash and verification rules as `scripts/freeze_research_inputs.py` (which this
script imports and reuses: the mirror is only read, the destination lies outside the mirror and
the repository, a dirty repository is refused, the snapshot is `<root>/<D*>-<sha12>/`, every file
and directory ends `chmod a-w`, and `--verify` is that script's `verify_snapshot`).

Inputs frozen:
- the 25 price records of both menus (research2003 and TSP) plus SGOV, each truncated at D* (rows
  dated after D* are dropped). WMT's mirror record has NaN `tr_index` from 2026-03-30 and ends
  2026-10-12: it is repaired from Tiingo daily `adjClose` (2026-02-01 through D*). Before any row
  is spliced, the adjClose daily returns must match the mirror's `tr_index` returns on the days
  they share to 1e-6 (otherwise the freeze stops); the `tr_index` then continues from the last
  good value by adjClose ratios, and `close`, `div_cash`, `split_factor` of the new rows come from
  Tiingo. Source, overlap check and row counts go into the manifest under `repairs`.
- `meta/manifest.json` and `meta/lake.json`, the XNYS calendar, the dependency lock;
- `data/research/ft_global500_2004_top10.csv` as committed at HEAD (stock rule of §3a);
- FRED `CPIAUCNS` and `DGS10` as CSV, truncated at D* (raw download digest and download time in
  the manifest);
- `reports/corporate_action_check.json`: for each stock and VIPSX, every day with |close return|
  above 25% or close and tr_index returns more than 10 percentage points apart, with the tr_index
  return, and the calendar-year comparison of the pipeline's tr_index with Tiingo's adjClose
  (years differing by more than 50 bp are flagged). Reconciliation of flagged years is a human
  decision recorded in the report, not done by this script.

Exit codes as the v1 script: 0 done, 2 bad argument or unsafe destination, 3 missing/invalid
input or dirty repository, 4 hash mismatch while copying, 5 existing snapshot with other
contents, 6 verification failure.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import io
import json
import os
import platform
import re
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from portfoliosight.research.fixedrisk.menus import (  # noqa: E402
    ALL_SYMBOLS,
    MENUS,
    STOCKS_2003,
)


def _load_v1() -> ModuleType:
    path = Path(__file__).resolve().parent / "freeze_research_inputs.py"
    name = "freeze_research_inputs"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v1 = _load_v1()
FreezeError = v1.FreezeError
verify_snapshot = v1.verify_snapshot

D_STAR = v1.D_STAR
DEFAULT_MIRROR = v1.DEFAULT_MIRROR
DEFAULT_ROOT = v1.DEFAULT_ROOT
MIN_CALENDAR_END = v1.MIN_CALENDAR_END
SCHEMA_VERSION = 2
SNAPSHOT_KIND = "fixed_risk"
MARKET_CAP_FILE = "data/research/ft_global500_2004_top10.csv"
CORPORATE_ACTION_FILE = "reports/corporate_action_check.json"
FRED_SERIES = ("CPIAUCNS", "DGS10")
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FRED_FILE = "macro/{series}.csv"
REPAIRED = {"WMT": date(2026, 2, 1)}  # symbol -> first Tiingo date fetched for the repair
CHECKED = (*STOCKS_2003, "VIPSX")
OVERLAP_TOLERANCE = 1e-6
DIVIDEND_DAY_TOLERANCE = 1e-4
BIG_MOVE = 0.25
RETURN_GAP = 0.10
YEAR_FLAG = 0.005  # 50 bp
WINDOW_FIRST_YEAR = 2003  # the earliest training window starts 2003-04 (EEM)
TIINGO_START = date(1990, 1, 1)

TiingoFetch = Callable[[str, date, date], pd.DataFrame]  # provider frame: close, adj_close, ...
FredFetch = Callable[[str], bytes]


# ----------------------------------------------------------------------------- live fetchers


def _tiingo_key() -> str:
    key = os.environ.get("TIINGO_API_KEY", "")
    if key:
        return key
    secrets = Path.home() / ".secrets" / "portfoliosight.env"
    if secrets.is_file():
        for line in secrets.read_text().splitlines():
            found = re.match(r"\s*(?:export\s+)?TIINGO_API_KEY=(.*)", line)
            if found:
                return found.group(1).strip().strip("\"'")
    raise FreezeError("TIINGO_API_KEY is not set (environment or ~/.secrets/portfoliosight.env)", 3)


def tiingo_fetch(symbol: str, start: date, end: date) -> pd.DataFrame:
    from portfoliosight.data.providers.tiingo import TiingoProvider

    provider = TiingoProvider(api_key=_tiingo_key())
    frame = provider.fetch_daily(symbol, start, end)
    if frame.empty:
        raise FreezeError(f"Tiingo returned no rows for {symbol} {start}..{end}", 3)
    return frame


def fred_fetch(series: str) -> bytes:
    import requests

    response = requests.get(FRED_URL.format(series=series), timeout=60)
    if response.status_code != 200:
        raise FreezeError(f"FRED answered {response.status_code} for {series}", 3)
    return response.content


class CachedTiingo:
    """One full-history Tiingo request per symbol (through D*); windows are slices of it.

    ``cache_dir`` keeps the responses as pickles between runs (Tiingo rate-limits the key).
    """

    def __init__(self, fetch: TiingoFetch, cache_dir: Path | None = None) -> None:
        self.fetch, self.cache_dir = fetch, cache_dir
        self._memory: dict[tuple[str, date], pd.DataFrame] = {}

    def __call__(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        key = (symbol, end)
        if key not in self._memory:
            path = None if self.cache_dir is None else self.cache_dir / f"{symbol}_{end}.pkl"
            if path is not None and path.is_file():
                self._memory[key] = pd.read_pickle(path)
            else:
                frame = self.fetch(symbol, TIINGO_START, end)
                if path is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    frame.to_pickle(path)
                self._memory[key] = frame
        frame = self._memory[key]
        return frame[(frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))]


# --------------------------------------------------------------------------------- the repair


def _returns_by_date(dates: pd.DatetimeIndex, values: np.ndarray) -> pd.Series:
    """Return on each date from the previous row, keyed by date, with the previous row's date."""
    out = pd.Series(values[1:] / values[:-1] - 1.0, index=dates[1:])
    return out


def repair_record(
    record: pd.DataFrame, provider: pd.DataFrame, d_star: date
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Splice a record's missing `tr_index` tail from the provider's `adj_close` (module doc).

    ``record`` is the mirror record cut at D*; ``provider`` the Tiingo frame (DatetimeIndex,
    close, adj_close, div_cash, split_factor) for the repair window through D*.
    """
    record = record.sort_values("date").reset_index(drop=True)
    dates = pd.DatetimeIndex(record["date"])
    tr = record["tr_index"].to_numpy(dtype=float)
    good = np.isfinite(tr) & (tr > 0)
    if not good.any():
        raise FreezeError("repair: the record has no good tr_index value", 3)
    last_good = int(np.flatnonzero(good)[-1])
    last_date = dates[last_good]
    if not good[: last_good + 1].all():
        raise FreezeError(
            "repair: tr_index has NaN before its last good value; the splice needs a clean prefix",
            3,
        )
    provider = provider.sort_index()
    adj = provider["adj_close"]
    if last_date not in adj.index:
        raise FreezeError(
            f"repair: the provider has no row on the last good day {last_date.date()}", 3
        )

    # Overlap check: returns on days both series have, with the same previous day.
    rec_ret = _returns_by_date(dates[: last_good + 1], tr[: last_good + 1])
    prov_ret = _returns_by_date(pd.DatetimeIndex(adj.index), adj.to_numpy(dtype=float))
    rec_prev = pd.Series(dates[: last_good + 1][:-1], index=dates[1 : last_good + 1])
    prov_prev = pd.Series(pd.DatetimeIndex(adj.index)[:-1], index=pd.DatetimeIndex(adj.index)[1:])
    shared = rec_ret.index.intersection(prov_ret.index)
    shared = shared[(rec_prev.loc[shared] == prov_prev.loc[shared]).to_numpy()]
    if len(shared) < 20:
        raise FreezeError(f"repair: only {len(shared)} overlapping return days to check", 3)
    gaps = (rec_ret.loc[shared] - prov_ret.loc[shared]).abs()
    on_dividend = (provider["div_cash"].reindex(shared).fillna(0.0) > 0).to_numpy()
    plain = gaps[~on_dividend]
    worst = float(plain.max()) if len(plain) else 0.0
    if worst > OVERLAP_TOLERANCE:
        day = plain.idxmax().date()
        raise FreezeError(
            f"repair: adjClose returns differ from tr_index returns by {worst:.3e} on {day} "
            f"(tolerance {OVERLAP_TOLERANCE:g}); not splicing",
            3,
        )
    # An ex-dividend day may differ by the dividend-basis convention (dividend over the previous
    # or the same day's close, a few tenths of a basis point); bounded and reported separately.
    worst_dividend = float(gaps[on_dividend].max()) if on_dividend.any() else 0.0
    if worst_dividend > DIVIDEND_DAY_TOLERANCE:
        raise FreezeError(
            f"repair: adjClose and tr_index returns differ by {worst_dividend:.3e} on an "
            f"ex-dividend day (tolerance {DIVIDEND_DAY_TOLERANCE:g}); not splicing",
            3,
        )

    new = provider.loc[(provider.index > last_date) & (provider.index <= pd.Timestamp(d_star))]
    mirror_tail = record.iloc[last_good + 1 :]
    only_mirror = sorted(set(pd.DatetimeIndex(mirror_tail["date"])) - set(new.index))
    only_provider = sorted(set(new.index) - set(pd.DatetimeIndex(mirror_tail["date"])))
    close_gap = 0.0
    both = pd.DatetimeIndex(mirror_tail["date"]).intersection(new.index)
    if len(both):
        mirror_close = mirror_tail.set_index(pd.DatetimeIndex(mirror_tail["date"])).loc[
            both, "close"
        ]
        close_gap = float((mirror_close - new.loc[both, "close"]).abs().max())
    base = float(tr[last_good])
    scale = base / float(adj.loc[last_date])
    spliced = pd.DataFrame(
        {
            "date": new.index,
            "close": new["close"].to_numpy(dtype=float),
            "tr_index": new["adj_close"].to_numpy(dtype=float) * scale,
            "div_cash": new["div_cash"].to_numpy(dtype=float),
            "split_factor": new["split_factor"].to_numpy(dtype=float),
        }
    )
    repaired = pd.concat([record.iloc[: last_good + 1], spliced], ignore_index=True)
    repaired["date"] = pd.to_datetime(repaired["date"])
    report = {
        "source": "tiingo daily adjClose",
        "window": [
            provider.index.min().date().isoformat(),
            provider.index.max().date().isoformat(),
        ],
        "last_good_date": last_date.date().isoformat(),
        "last_good_tr_index": base,
        "overlap_days_checked": int(len(shared)),
        "overlap_first": shared.min().date().isoformat(),
        "overlap_last": shared.max().date().isoformat(),
        "overlap_days_checked_plain": int(len(plain)),
        "overlap_max_abs_return_difference": worst,
        "overlap_dividend_days": [d.date().isoformat() for d in shared[on_dividend]],
        "overlap_dividend_day_max_abs_difference": worst_dividend,
        "overlap_dividend_day_tolerance": DIVIDEND_DAY_TOLERANCE,
        "overlap_tolerance": OVERLAP_TOLERANCE,
        "mirror_rows_replaced": int(len(mirror_tail)),
        "rows_spliced": int(len(spliced)),
        "first_spliced_date": spliced["date"].min().date().isoformat() if len(spliced) else None,
        "last_spliced_date": spliced["date"].max().date().isoformat() if len(spliced) else None,
        "dates_only_in_mirror": [d.date().isoformat() for d in only_mirror],
        "dates_only_in_provider": [d.date().isoformat() for d in only_provider],
        "close_max_abs_difference_on_shared_dates": close_gap,
        "rows_after": int(len(repaired)),
    }
    return repaired, report


# ------------------------------------------------------------------ corporate-action check


def action_days(record: pd.DataFrame) -> list[dict[str, Any]]:
    """Days with |close return| > 25% or close and tr_index returns > 10 pp apart."""
    frame = record.sort_values("date").reset_index(drop=True)
    close = frame["close"].to_numpy(dtype=float)
    tr = frame["tr_index"].to_numpy(dtype=float)
    out = []
    with np.errstate(divide="ignore", invalid="ignore"):
        c_ret = close[1:] / close[:-1] - 1.0
        t_ret = tr[1:] / tr[:-1] - 1.0
    for k in np.flatnonzero((np.abs(c_ret) > BIG_MOVE) | (np.abs(c_ret - t_ret) > RETURN_GAP)):
        row = frame.iloc[k + 1]
        out.append(
            {
                "date": pd.Timestamp(row["date"]).date().isoformat(),
                "close_return": float(c_ret[k]),
                "tr_index_return": float(t_ret[k]),
                "div_cash": None if pd.isna(row["div_cash"]) else float(row["div_cash"]),
                "split_factor": None
                if pd.isna(row["split_factor"])
                else float(row["split_factor"]),
            }
        )
    return out


def yearly_comparison(record: pd.DataFrame, adj: pd.Series) -> list[dict[str, Any]]:
    """Calendar-year return of tr_index against Tiingo's adjClose, on the days both have."""
    frame = record.set_index(pd.DatetimeIndex(record["date"]))["tr_index"].sort_index()
    both = frame.index.intersection(adj.index)
    tr, ad = frame.loc[both], adj.loc[both]
    rows = []
    years = sorted(set(both.year))
    previous: pd.Timestamp | None = None
    for year in years:
        in_year = both[both.year == year]
        end = in_year.max()
        start = previous if previous is not None else in_year.min()
        if end == start:
            previous = end
            continue
        ret_tr = float(tr.loc[end] / tr.loc[start] - 1.0)
        ret_adj = float(ad.loc[end] / ad.loc[start] - 1.0)
        rows.append(
            {
                "year": int(year),
                "from": start.date().isoformat(),
                "to": end.date().isoformat(),
                "tr_index_return": ret_tr,
                "adj_close_return": ret_adj,
                "difference_bp": 1e4 * (ret_tr - ret_adj),
                "flag": abs(ret_tr - ret_adj) > YEAR_FLAG,
            }
        )
        previous = end
    return rows


def corporate_action_report(
    records: dict[str, pd.DataFrame], tiingo: TiingoFetch, d_star: date
) -> dict[str, Any]:
    symbols: dict[str, Any] = {}
    for symbol in CHECKED:
        entry: dict[str, Any] = {"action_days": action_days(records[symbol])}
        try:
            provider = tiingo(symbol, TIINGO_START, d_star)
            adj = provider["adj_close"].astype(float)
            adj = adj[adj.index <= pd.Timestamp(d_star)]
            years = yearly_comparison(records[symbol], adj)
            entry["adj_close_available"] = True
            entry["years"] = years
            entry["flagged_years"] = [y["year"] for y in years if y["flag"]]
            entry["max_abs_difference_bp"] = max(
                (abs(y["difference_bp"]) for y in years), default=0.0
            )
            window = [y for y in years if y["year"] >= WINDOW_FIRST_YEAR]
            entry["flagged_years_from_2003"] = [y["year"] for y in window if y["flag"]]
            entry["max_abs_difference_bp_from_2003"] = max(
                (abs(y["difference_bp"]) for y in window), default=0.0
            )
        except Exception as exc:  # noqa: BLE001 - recorded, never silent
            entry["adj_close_available"] = False
            entry["reason"] = f"{type(exc).__name__}: {exc}"
        symbols[symbol] = entry
    return {
        "rules": {
            "big_close_move": BIG_MOVE,
            "close_vs_tr_index_return_gap": RETURN_GAP,
            "year_flag": YEAR_FLAG,
            "adj_close_source": "tiingo",
        },
        "d_star": d_star.isoformat(),
        "symbols": symbols,
        "summary": {
            symbol: {
                "action_days": len(entry["action_days"]),
                "flagged_years": entry.get("flagged_years"),
                "max_abs_difference_bp": entry.get("max_abs_difference_bp"),
                "flagged_years_from_2003": entry.get("flagged_years_from_2003"),
                "max_abs_difference_bp_from_2003": entry.get("max_abs_difference_bp_from_2003"),
            }
            for symbol, entry in symbols.items()
        },
    }


# ---------------------------------------------------------------------------------- FRED


def fred_truncated(raw: bytes, d_star: date, series: str) -> tuple[bytes, dict[str, Any]]:
    """The CSV cut at D* (header kept), with the vintage facts for the manifest."""
    lines = raw.decode("utf-8").splitlines()
    if len(lines) < 2 or "," not in lines[0] or series not in lines[0]:
        raise FreezeError(f"FRED {series}: unexpected header {lines[:1]}", 3)
    kept = [lines[0]]
    last_value = None
    for line in lines[1:]:
        day, _, value = line.partition(",")
        if date.fromisoformat(day) > d_star:
            continue
        kept.append(line)
        if value.strip() not in ("", "."):
            last_value = day
    if len(kept) < 2 or last_value is None:
        raise FreezeError(f"FRED {series}: no observation on or before D*", 3)
    data = ("\n".join(kept) + "\n").encode()
    return data, {
        "series": series,
        "url": FRED_URL.format(series=series),
        "downloaded_utc": datetime.now(UTC).isoformat(),
        "raw_sha256": v1._digest(raw),
        "raw_rows": len(lines) - 1,
        "rows": len(kept) - 1,
        "first_observation": kept[1].partition(",")[0],
        "last_observation": kept[-1].partition(",")[0],
        "last_non_missing": last_value,
        "truncated_at": d_star.isoformat(),
    }


# ---------------------------------------------------------------------------------- freezing


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


def prepare_records(
    mirror: Path, d_star: date, tiingo: TiingoFetch
) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict[str, Any]]:
    """Mirror records cut at D* (repaired where needed), raw mirror digests, repair reports."""
    records: dict[str, pd.DataFrame] = {}
    raw_digest: dict[str, str] = {}
    repairs: dict[str, Any] = {}
    stamp = pd.Timestamp(d_star)
    for symbol in ALL_SYMBOLS:
        path = mirror / v1.price_path(symbol)
        if not path.is_file():
            raise FreezeError(f"required input missing from the mirror {mirror}: {path.name}", 3)
        raw = path.read_bytes()
        raw_digest[v1.price_path(symbol)] = v1._digest(raw)
        frame = pd.read_parquet(io.BytesIO(raw))
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame[frame["date"] <= stamp].reset_index(drop=True)
        if symbol in REPAIRED:
            provider = tiingo(symbol, REPAIRED[symbol], d_star)
            frame, report = repair_record(frame, provider, d_star)
            repairs[symbol] = report
        records[symbol] = frame
    return records, raw_digest, repairs


def build_snapshot(
    work: Path,
    *,
    records: dict[str, pd.DataFrame],
    raw_digest: dict[str, str],
    repairs: dict[str, Any],
    action_report: dict[str, Any],
    fred: dict[str, bytes],
    market_caps: bytes,
    mirror: Path,
    head: str,
    d_star: date,
    calendar_end: date,
) -> str:
    """Write the snapshot into ``work``; returns the SHA-256 of its canonical manifest."""
    files: list[dict[str, Any]] = []
    catalog = v1._catalog((mirror / "meta" / "manifest.json").read_bytes())
    menu_symbols = {h for menu in MENUS for h in menu.holdings}
    for relative in v1.META_FILES:
        data = (mirror / relative).read_bytes()
        raw_digest[relative] = v1._digest(data)
        (work / relative).parent.mkdir(parents=True, exist_ok=True)
        (work / relative).write_bytes(data)
        files.append(v1._file_record(relative, data, "mirror", relative))

    for symbol, frame in records.items():
        relative = v1.price_path(symbol)
        data = _parquet_bytes(frame)
        if symbol not in catalog:
            raise FreezeError(f"meta/manifest.json has no entry for {symbol}", 3)
        record = v1.price_record(symbol, data, catalog[symbol], d_star, symbol in menu_symbols)
        (work / relative).parent.mkdir(parents=True, exist_ok=True)
        (work / relative).write_bytes(data)
        entry = v1._file_record(
            relative, data, "mirror_repaired" if symbol in repairs else "mirror_truncated", relative
        )
        entry["record"] = record
        entry["mirror_sha256"] = raw_digest[relative]
        files.append(entry)

    fred_meta = {}
    for series, raw in fred.items():
        data, meta = fred_truncated(raw, d_star, series)
        relative = FRED_FILE.format(series=series)
        (work / relative).parent.mkdir(parents=True, exist_ok=True)
        (work / relative).write_bytes(data)
        files.append(v1._file_record(relative, data, "fred", meta["url"]))
        fred_meta[series] = meta

    extras: list[tuple[str, bytes, str, str | None]] = [
        (MARKET_CAP_FILE, market_caps, "repo_head", MARKET_CAP_FILE),
        (
            CORPORATE_ACTION_FILE,
            (json.dumps(action_report, indent=2, sort_keys=True) + "\n").encode(),
            "generated",
            None,
        ),
    ]
    stamp_start = date(min(frame["date"].min().year for frame in records.values()), 1, 1)
    sessions = v1.xnys_sessions(stamp_start, calendar_end)
    calendar_csv = ("session\n" + "".join(f"{day}\n" for day in sessions)).encode()
    packages = v1.freeze_requirements()
    version_string = f"Python {platform.python_version()}"
    lock = "".join(
        f"{line}\n" for line in (f"# python: {version_string}", f"# git HEAD: {head}", *packages)
    ).encode()
    extras += [
        (v1.CALENDAR_FILE, calendar_csv, "generated", None),
        (v1.LOCK_FILE, lock, "generated", None),
    ]
    for relative, data, origin, source in extras:
        (work / relative).parent.mkdir(parents=True, exist_ok=True)
        (work / relative).write_bytes(data)
        files.append(v1._file_record(relative, data, origin, source))

    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": SNAPSHOT_KIND,
        "d_star": d_star.isoformat(),
        "source_root": str(mirror),
        "repo_head": head,
        "repo_dirty": False,
        "menus": {
            menu.name: {
                "preset": menu.name,
                "funds": list(menu.holdings),
                "lower": list(menu.lower),
                "upper": list(menu.upper),
            }
            for menu in MENUS
        },
        "files": sorted(files, key=lambda entry: entry["path"]),
        "truncation": {
            "d_star": d_star.isoformat(),
            "rule": "every price record and FRED series is cut to rows dated on or before D*",
        },
        "repairs": repairs,
        "mirror_inputs_sha256": dict(sorted(raw_digest.items())),
        "risk_free": {
            "order": v1.RISK_FREE_ORDER,
            "sgov": v1._risk_free_entry({s: files_record(files, s) for s in ("SGOV",)}, "SGOV"),
            "tsp_g": v1._risk_free_entry({s: files_record(files, s) for s in ("TSP-G",)}, "TSP-G"),
        },
        "fred": fred_meta,
        "market_caps": {
            "file": MARKET_CAP_FILE,
            "rule": "US-domiciled companies among the ten largest by market value, FT Global 500 "
            "2004 (values at 2004-03-31), Wikipedia table read 2026-10-23",
        },
        "corporate_action_check": {
            "file": CORPORATE_ACTION_FILE,
            "summary": action_report["summary"],
        },
        "calendar": {
            "name": v1.EXCHANGE,
            "library": "exchange_calendars",
            "library_version": importlib.metadata.version("exchange_calendars"),
            "start": stamp_start.isoformat(),
            "end": calendar_end.isoformat(),
            "first_session": sessions[0],
            "last_session": sessions[-1],
            "sessions": len(sessions),
            "file": v1.CALENDAR_FILE,
        },
        "python": {
            "version": platform.python_version(),
            "version_string": version_string,
            "implementation": platform.python_implementation(),
        },
        "dependency_lock": {"file": v1.LOCK_FILE, "packages": len(packages)},
    }
    digest = v1._digest(v1._canonical(body))
    manifest = {**body, "created_utc": datetime.now(UTC).isoformat(), "manifest_sha256": digest}
    (work / v1.SNAPSHOT_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return digest


def files_record(files: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    for entry in files:
        if entry["path"] == v1.price_path(symbol):
            return entry["record"]
    raise FreezeError(f"no price record for {symbol}", 3)


def freeze(
    *,
    mirror: Path,
    root: Path,
    repo: Path = REPO,
    d_star: date = D_STAR,
    calendar_end: date = MIN_CALENDAR_END,
    tiingo: TiingoFetch = tiingo_fetch,
    fred: FredFetch = fred_fetch,
    tiingo_cache: Path | None = None,
) -> Path:
    """Build, verify and close the snapshot; returns its directory."""
    if calendar_end < MIN_CALENDAR_END:
        raise FreezeError(f"--calendar-end {calendar_end} is before {MIN_CALENDAR_END}", 2)
    mirror = Path(mirror).expanduser().resolve()
    if not mirror.is_dir():
        raise FreezeError(f"the mirror {mirror} is not a directory", 3)
    root = v1.guard_destination(Path(root), mirror, repo)
    head = v1.repo_head(repo)
    dirty = v1.dirty_paths(repo)
    if dirty:
        raise FreezeError(
            f"refusing: {repo} has uncommitted changes to tracked files ({', '.join(dirty)}); "
            f"the snapshot names the code by its HEAD {head}",
            3,
        )
    market_caps = v1.repo_blob(repo, head, MARKET_CAP_FILE)
    tiingo = CachedTiingo(tiingo, tiingo_cache)
    records, raw_digest, repairs = prepare_records(mirror, d_star, tiingo)
    action_report = corporate_action_report(records, tiingo, d_star)
    fetched = {series: fred(series) for series in FRED_SERIES}

    root.mkdir(parents=True, exist_ok=True)
    work = root / f".{d_star.isoformat()}-{uuid.uuid4().hex}.tmp"
    work.mkdir()
    try:
        digest = build_snapshot(
            work,
            records=records,
            raw_digest=raw_digest,
            repairs=repairs,
            action_report=action_report,
            fred=fetched,
            market_caps=market_caps,
            mirror=mirror,
            head=head,
            d_star=d_star,
            calendar_end=calendar_end,
        )
        # The mirror files must be unchanged since they were read.
        for relative, before in raw_digest.items():
            if v1._digest((mirror / relative).read_bytes()) != before:
                raise FreezeError(f"{relative}: the source changed while the snapshot was built", 4)
        final = root / f"{d_star.isoformat()}-{digest[:12]}"
        if os.path.lexists(final):
            problems = v1.differences(work, final)
            if problems:
                raise FreezeError(
                    f"{final} exists with different contents: {'; '.join(problems)}", 5
                )
            print(f"{final} already exists with identical contents (verified)", file=sys.stderr)
            return final
        v1._close_tree(work)
        work.rename(final)
        return final
    finally:
        if work.exists():
            v1._remove_tree(work)


def _iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{text!r} is not an ISO date") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze the fixed-risk experiment's inputs.")
    parser.add_argument("--verify", type=Path, metavar="SNAPSHOT_DIR")
    parser.add_argument("--mirror", type=Path, default=DEFAULT_MIRROR)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--tiingo-cache", type=Path, help="keep Tiingo responses between runs")
    parser.add_argument("--d-star", type=_iso_date, default=D_STAR)
    parser.add_argument("--calendar-end", type=_iso_date, default=MIN_CALENDAR_END)
    args = parser.parse_args(argv)
    try:
        if args.verify is not None:
            manifest = verify_snapshot(args.verify)
            print(f"verified {len(manifest['files']) + 1} files", file=sys.stderr)
            print(args.verify.resolve())
            return 0
        snapshot = freeze(
            mirror=args.mirror,
            root=args.root,
            repo=args.repo,
            d_star=args.d_star,
            calendar_end=args.calendar_end,
            tiingo_cache=args.tiingo_cache,
        )
    except FreezeError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    print(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
