"""Manifest shape, the served rule and the symbols view (spec 5.2, 5.3; A-PS-07 rule legs)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data.calendar import session_back
from portfoliosight.data.store import LocalStore

D = date(2026, 3, 9)  # a Monday: D-3 sessions is Wednesday 2026-03-04
ENTRY_KEYS = {
    "name",
    "kind",
    "tier",
    "income",
    "source",
    "first_date",
    "last_date",
    "adjusted_through",
    "status",
    "reason",
    "fetched_at",
}


def _entry(**over) -> manifest_mod.ManifestEntry:
    base = {
        "name": "Fund",
        "kind": "etf",
        "tier": 2,
        "source": "tiingo",
        "first_date": date(2001, 5, 31),
        "last_date": D,
        "adjusted_through": D,
        "status": "ok",
        "fetched_at": "2026-03-10T10:00:00+00:00",
    }
    base.update(over)
    return manifest_mod.ManifestEntry(**base)


def test_manifest_serializes_to_the_pinned_shape():
    manifest = manifest_mod.Manifest(
        symbols={
            "VTI": _entry(),
            "GONE": _entry(
                first_date=None,
                last_date=None,
                adjusted_through=None,
                status="unavailable",
                reason="no data",
                fetched_at=None,
            ),
        }
    )
    doc = json.loads(json.dumps(manifest.to_json()))
    assert set(doc) == {"symbols"} and set(doc["symbols"]) == {"VTI", "GONE"}
    assert set(doc["symbols"]["VTI"]) == ENTRY_KEYS
    assert doc["symbols"]["VTI"]["first_date"] == "2001-05-31"
    assert doc["symbols"]["VTI"]["last_date"] == "2026-03-09"
    assert doc["symbols"]["VTI"]["income"] is False and doc["symbols"]["VTI"]["reason"] is None
    assert doc["symbols"]["GONE"]["last_date"] is None
    again = manifest_mod.Manifest.model_validate(doc)
    assert again == manifest
    tolerant = manifest_mod.Manifest.model_validate(
        {"symbols": {"X": {**doc["symbols"]["VTI"], "unknown_field": 1}}}
    )
    assert tolerant.symbols["X"].last_date == D


@pytest.mark.parametrize(
    ("last_back", "adjusted_back", "expected"),
    [(0, 0, "ok"), (3, 0, "ok"), (0, 3, "ok"), (3, 3, "ok"), (4, 0, "stale"), (0, 4, "stale")],
)
def test_served_rule_boundary(last_back, adjusted_back, expected):
    entry = _entry(
        last_date=session_back(D, last_back), adjusted_through=session_back(D, adjusted_back)
    )
    assert manifest_mod.status_for(entry, D) == expected
    as_dict = json.loads(json.dumps(entry.model_dump(mode="json")))
    assert manifest_mod.status_for(as_dict, D) == expected
    assert session_back(D, 3) == date(2026, 3, 4)


def test_seed_is_pending_and_missing_dates_are_unavailable():
    seed = _entry(source="seed", status="pending", fetched_at=None)
    assert manifest_mod.status_for(seed, D) == "pending"
    assert manifest_mod.status_for(_entry(source="seed+tiingo"), D) == "ok"
    gone = _entry(last_date=None, adjusted_through=None, status="unavailable")
    assert manifest_mod.status_for(gone, D) == "unavailable"


def test_reasons_use_the_fixed_templates():
    ok = _entry()
    assert manifest_mod.reason_for(ok, "ok", D) is None
    behind = _entry(last_date=date(2024, 10, 30), adjusted_through=date(2024, 10, 30))
    assert manifest_mod.reason_for(behind, "stale", D) == "no data since 2024-10-30"
    unverified = _entry(adjusted_through=date(2026, 2, 27))
    expected = "corporate actions not yet verified after 2026-02-27"
    assert manifest_mod.reason_for(unverified, "stale", D) == expected
    assert (
        manifest_mod.reason_for(
            _entry(source="seed", adjusted_through=date(2026, 2, 27)), "pending", D
        )
        == expected
    )
    assert manifest_mod.reason_for(behind, "unavailable", D) == "no data since 2024-10-30"
    empty = _entry(last_date=None, adjusted_through=None)
    assert manifest_mod.reason_for(empty, "unavailable", D) == "no data"


def test_restatus_moves_ok_to_stale_and_keeps_unavailable():
    manifest = manifest_mod.Manifest(
        symbols={
            "OK": _entry(),
            "LAG": _entry(last_date=session_back(D, 4), adjusted_through=session_back(D, 4)),
            "SEED": _entry(source="seed", status="pending", adjusted_through=date(2026, 2, 27)),
            "GONE": _entry(status="unavailable", reason="no data since 2026-03-09"),
        }
    )
    manifest_mod.restatus(manifest, D)
    got = {symbol: entry.status for symbol, entry in manifest.symbols.items()}
    assert got == {"OK": "ok", "LAG": "stale", "SEED": "pending", "GONE": "unavailable"}
    assert manifest.symbols["LAG"].reason == "no data since 2026-03-03"
    assert manifest.symbols["GONE"].reason == "no data since 2026-03-09"
    assert manifest.symbols["OK"].reason is None


def test_symbols_view_lists_exactly_the_ok_symbols(tmp_path):
    manifest = manifest_mod.Manifest(
        symbols={
            "VTI": _entry(name="Vanguard Total Stock Market ETF", tier=1),
            "TSP-G": _entry(name="G Fund", kind="tsp", tier=1, source="tsp"),
            "ZZZ": _entry(tier=3, kind="stock"),
            "LAG": _entry(status="stale", tier=2),
            "SEED": _entry(status="pending", source="seed", tier=2),
            "GONE": _entry(status="unavailable", tier=2),
        }
    )
    at = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
    view = manifest_mod.symbols_view(manifest, at)
    assert set(view) == {"catalog_at", "tiers_served", "symbols"}
    assert view["catalog_at"] == "2026-03-10T09:00:00+00:00"
    assert [row["id"] for row in view["symbols"]] == ["TSP-G", "VTI", "ZZZ"]
    assert view["tiers_served"] == [1, 3]
    assert view["symbols"][1] == {
        "id": "VTI",
        "name": "Vanguard Total Stock Market ETF",
        "kind": "etf",
        "tier": 1,
        "first_date": "2001-05-31",
    }

    store = LocalStore(tmp_path)
    assert manifest_mod.load_manifest(store).symbols == {}
    manifest_mod.write_catalog(store, manifest, at)
    assert store.list() == ["meta/manifest.json", "meta/symbols.json"]
    assert json.loads(store.get("meta/symbols.json")) == view
    assert json.loads(store.get("meta/manifest.json")) == manifest.to_json()
    assert manifest_mod.load_manifest(store) == manifest
