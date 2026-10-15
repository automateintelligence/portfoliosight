"""The mutable symbol catalog: ``meta/manifest.json`` and its view ``meta/symbols.json``."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from portfoliosight.data import store as store_mod
from portfoliosight.data.calendar import session_back
from portfoliosight.data.refresh import as_date

MANIFEST_KEY = "meta/manifest.json"
SYMBOLS_KEY = "meta/symbols.json"
SERVED_WITHIN_SESSIONS = 3

# Fixed reason templates of spec 5.6.
REASON_NO_DATA = "no data"
REASON_NO_DATA_SINCE = "no data since {date}"
REASON_UNVERIFIED = "corporate actions not yet verified after {date}"
_NOTED_RE = re.compile(r"^(.+); no data since \d{4}-\d{2}-\d{2}$")


class ManifestEntry(BaseModel):
    """One symbol of the catalog; dates serialize as ISO strings."""

    model_config = ConfigDict(extra="ignore")

    name: str
    kind: str  # etf | mutual_fund | stock | tsp
    tier: int
    income: bool = False
    source: str  # seed | tiingo | tsp | seed+tiingo | lake
    first_date: date | None = None
    last_date: date | None = None
    adjusted_through: date | None = None
    status: str  # ok | pending | stale | unavailable
    reason: str | None = None
    fetched_at: str | None = None
    # True when the record's dividend or split rows after 2026-03-20 include one from yfinance
    # (lake symbols only, spec 5.4); to be reviewed before public launch.
    relies_on_yfinance: bool = False


class Manifest(BaseModel):
    symbols: dict[str, ManifestEntry] = {}

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def load_manifest(store: store_mod.Store) -> Manifest:
    """The stored manifest, or an empty one when the store has none yet."""
    try:
        return Manifest.model_validate(store_mod.get_json(store, MANIFEST_KEY))
    except KeyError:
        return Manifest()


def _field(entry: Any, name: str) -> Any:
    return entry.get(name) if isinstance(entry, Mapping) else getattr(entry, name, None)


def status_for(entry: Any, d_g: date) -> str:
    """The status the entry's source and dates give against ``d_g`` (spec 5.2).

    ``pending`` for a seed never tail-refreshed; ``ok`` when prices and corporate actions both
    reach the session three sessions before ``d_g``; ``stale`` when either is older; and
    ``unavailable`` when the entry has no data at all.
    """
    if _field(entry, "source") == "seed":
        return "pending"
    last = as_date(_field(entry, "last_date"))
    adjusted = as_date(_field(entry, "adjusted_through"))
    if last is None or adjusted is None:
        return "unavailable"
    floor = session_back(d_g, SERVED_WITHIN_SESSIONS)
    return "ok" if last >= floor and adjusted >= floor else "stale"


def reason_for(entry: ManifestEntry, status: str, d_g: date, note: str | None = None) -> str | None:
    """The fixed reason string that goes with a status, ``None`` for a served symbol.

    ``note`` is the universe's remark on a fund whose data has ended ("converted to an ETF"); it
    prefixes the "no data since" reason. Without one, a note already in the entry is kept.
    """
    if status == "ok":
        return None
    if entry.last_date is None or entry.adjusted_through is None:
        return REASON_NO_DATA
    floor = session_back(d_g, SERVED_WITHIN_SESSIONS)
    if status == "unavailable" or (status == "stale" and entry.last_date < floor):
        since = REASON_NO_DATA_SINCE.format(date=entry.last_date.isoformat())
        if note is None:
            kept = _NOTED_RE.match(entry.reason or "")
            note = kept.group(1) if kept else None
        return f"{note}; {since}" if note else since
    return REASON_UNVERIFIED.format(date=entry.adjusted_through.isoformat())


def restatus(manifest: Manifest, d_g: date) -> None:
    """Recompute every entry's status against ``d_g``; ``unavailable`` entries are kept as is.

    A ``stale`` entry whose dates are inside the served rule was marked after a failed fetch
    (``mark_fetch_failed``); it stays ``stale`` until a fetch that succeeds settles it.
    """
    for entry in manifest.symbols.values():
        if entry.status == "unavailable":
            continue
        status = status_for(entry, d_g)
        if entry.status == "stale" and status == "ok":
            continue
        entry.status = status
        entry.reason = reason_for(entry, entry.status, d_g)


def mark_fetch_failed(entry: ManifestEntry, d_g: date, note: str | None = None) -> None:
    """A served entry whose due refresh failed is ``stale``, not served, until a fetch succeeds."""
    if entry.status == "ok":
        entry.status = "stale"
        entry.reason = reason_for(entry, "stale", d_g, note)


def symbols_view(manifest: Manifest, catalog_at: datetime) -> dict[str, Any]:
    """The body of ``GET /api/symbols`` (spec 6): the ``ok`` symbols only."""
    served = sorted(
        (symbol, entry) for symbol, entry in manifest.symbols.items() if entry.status == "ok"
    )
    return {
        "catalog_at": catalog_at.isoformat(),
        "tiers_served": sorted({entry.tier for _, entry in served}),
        "symbols": [
            {
                "id": symbol,
                "name": entry.name,
                "kind": entry.kind,
                "tier": entry.tier,
                "first_date": entry.first_date.isoformat() if entry.first_date else None,
            }
            for symbol, entry in served
        ],
    }


def write_catalog(store: store_mod.Store, manifest: Manifest, catalog_at: datetime) -> None:
    """Rewrite the manifest and the symbols view derived from it (each key replaced whole)."""
    store_mod.put_json(store, MANIFEST_KEY, manifest.to_json())
    store_mod.put_json(store, SYMBOLS_KEY, symbols_view(manifest, catalog_at))
