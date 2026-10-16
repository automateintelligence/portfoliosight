"""The QSE lake as a price source (spec 5.2, 5.4): its files, and its overlay of the catalog.

The lake is only ever read, and only on the owner's laptop (the seed and ``scripts/sync_lake.py``).
What the sync takes from it is recorded in ``meta/lake.json``, which only the sync writes. Every
writer of ``meta/manifest.json`` applies that overlay with ``apply_lake`` just before it writes,
so neither the sync nor the nightly can drop the other's entries.

Names come from the lake too: ``General.Name`` of the symbol's EODHD fundamentals file, else
the name EODHD's US symbol list gives it (``LakeNames``).
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.manifest import Manifest, ManifestEntry
from portfoliosight.data.refresh import LAKE_SOURCE

LAKE_KEY = "meta/lake.json"
DEFAULT_LAKE = "~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core"
FUNDAMENTALS_DIR = "fundamentals_full"
LISTING_FILE = "symbols/US_active.csv"

RELEASED_SOURCE = "seed"
EOD_COLUMNS = ["date", "close", "adj_close"]


def read_eod(path: Path) -> pd.DataFrame:
    """One ``eod_history`` file: ``date`` (tz-naive), ``close``, ``adj_close``, sorted by date."""
    frame = pd.read_parquet(path, columns=EOD_COLUMNS)
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    return frame.sort_values("date").reset_index(drop=True)


def eod_to_record(frame: pd.DataFrame, through: date) -> pd.DataFrame:
    """The canonical record of a lake frame: ``tr_index = adj_close / adj_close[0]``.

    Rows after ``through`` are price-only (``tr_index`` NaN): their adjustment is not vouched.
    """
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


def unusable_reason(frame: pd.DataFrame) -> str | None:
    """Why a lake frame cannot become a served record, or ``None`` when it can."""
    if frame.empty:
        return "no rows"
    close = frame["close"].to_numpy(dtype=float)
    adj = frame["adj_close"].to_numpy(dtype=float)
    if not (np.isfinite(adj).all() and (adj > 0).all()):
        return "adj_close is missing or not positive"
    if not (np.isfinite(close).all() and (close > 0).all()):
        return "close is missing or not positive"
    return None


def clean_name(value: Any) -> str | None:
    """A name as the issuer gives it, with surrounding whitespace removed; ``None`` for none."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def fundamentals_name(lake: Path, symbol: str) -> str | None:
    """``General.Name`` of ``fundamentals_full/{symbol}.json``.

    ``None`` when the file is missing, empty or unreadable, or has no ``General.Name``.
    """
    path = lake / FUNDAMENTALS_DIR / f"{symbol}.json"
    try:
        doc = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    general = doc.get("General") if isinstance(doc, dict) else None
    return clean_name(general.get("Name")) if isinstance(general, dict) else None


def listing_names(lake: Path) -> dict[str, str]:
    """Code to name from EODHD's US symbol list in the lake (empty when it cannot be read).

    A code listed under two different names is left out rather than guessed.
    """
    names: dict[str, str | None] = {}
    try:
        with (lake / LISTING_FILE).open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                code = (row.get("Code") or "").strip().upper()
                name = clean_name(row.get("Name"))
                if not code or name is None:
                    continue
                if code in names and names[code] != name:
                    names[code] = None
                else:
                    names.setdefault(code, name)
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}
    return {code: name for code, name in names.items() if name is not None}


class LakeNames:
    """The lake's name of a symbol: its fundamentals file first, then the US symbol list."""

    def __init__(self, lake: Path):
        self.lake = lake
        self.listing = listing_names(lake)

    def name(self, symbol: str) -> str | None:
        """The name, or ``None`` when the lake has none other than the ticker itself."""
        found = fundamentals_name(self.lake, symbol) or self.listing.get(symbol)
        return None if found is None or manifest_mod.unnamed(symbol, found) else found


class LakeEntry(ManifestEntry):
    """A catalog entry the sync took from the lake, with the digest of the files it came from."""

    digest: str


class LakeOverlay(BaseModel):
    """``meta/lake.json``: the lake run synced (its ``generated_at``) and the entries taken."""

    model_config = ConfigDict(extra="ignore")

    generated_at: str | None = None
    synced_at: str | None = None
    symbols: dict[str, LakeEntry] = {}

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def load_lake(store: store_mod.Store) -> LakeOverlay:
    """The stored overlay, or an empty one when the sync has not run."""
    try:
        return LakeOverlay.model_validate(store_mod.get_json(store, LAKE_KEY))
    except KeyError:
        return LakeOverlay()


def catalog_entry(entry: LakeEntry) -> ManifestEntry:
    """The manifest entry of an overlay entry (the digest stays in ``meta/lake.json``)."""
    return ManifestEntry.model_validate(entry.model_dump(exclude={"digest"}))


def apply_lake(manifest: Manifest, overlay: LakeOverlay, d_g: date) -> list[str]:
    """Make ``manifest`` carry ``overlay``; returns the symbols released from the lake.

    Every overlay entry replaces the manifest's, with its status and reason against ``d_g``. An
    entry still marked ``lake`` that the overlay no longer holds is released: it becomes a seed
    (``pending``) whose record is verified through its ``adjusted_through``, so a provider's tail
    refresh can take it over from there.
    """
    for symbol, lake_entry in overlay.symbols.items():
        entry = catalog_entry(lake_entry)
        entry.status = manifest_mod.status_for(entry, d_g)
        entry.reason = manifest_mod.reason_for(entry, entry.status, d_g)
        manifest.symbols[symbol] = entry
    released: list[str] = []
    for symbol, entry in manifest.symbols.items():
        if entry.source == LAKE_SOURCE and symbol not in overlay.symbols:
            entry.source = RELEASED_SOURCE
            entry.status = manifest_mod.status_for(entry, d_g)
            entry.reason = (
                manifest_mod.REASON_UNVERIFIED.format(date=entry.adjusted_through.isoformat())
                if entry.adjusted_through is not None
                else manifest_mod.REASON_NO_DATA
            )
            released.append(symbol)
    return sorted(released)
