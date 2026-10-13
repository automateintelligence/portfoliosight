"""The presets body (spec 6): two presets, the guide's dollar allocation, public tensor URLs."""

from __future__ import annotations

import csv

from portfoliosight.api.hashing import universe_hash
from portfoliosight.api.presets import (
    LOOKBACKS,
    preset_definitions,
    preset_funds,
    presets_body,
    tensor_key,
    tensor_url,
)
from portfoliosight.data.universe import REPO_ROOT

HOLDINGS = REPO_ROOT / "data" / "holdings" / "holdings_guide2017_step2.csv"


def test_definitions_come_from_the_presets_file_and_the_holdings_csv():
    guide, tsp = preset_definitions()
    with HOLDINGS.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {row["Symbol"]: round(float(row["Qty"]) * float(row["Price"]), 2) for row in rows}
    assert guide.id == "guide2017" and guide.name == "The 2017 guide portfolio"
    assert len(guide.funds) == 23 and guide.allocation == expected
    assert sum(1 for amount in expected.values() if amount != 0) == 18
    assert guide.allocation_unit == "$"
    assert tsp.id == "tsp" and tsp.funds == ("TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I")
    assert tsp.allocation is None and tsp.allocation_unit is None


def test_preset_funds_are_the_all_default_policy():
    _, tsp = preset_definitions()
    funds = preset_funds(tsp)
    assert funds == [{"id": fund, "min": None, "max": None} for fund in tsp.funds]


def test_body_has_the_spec_shape(store, generation, d_g):
    guide, tsp = preset_definitions()
    guide_hash = universe_hash(preset_funds(guide))
    for lookback in LOOKBACKS:
        store.put(tensor_key(generation, guide_hash, lookback), b"{}")
    body = presets_body(generation, d_g.isoformat(), store)
    assert body["generation"] == generation and body["asof"] == d_g.isoformat()
    first, second = body["presets"]
    assert set(first) == {
        "id",
        "name",
        "hash",
        "funds",
        "allocation",
        "allocation_unit",
        "lookbacks",
    }
    assert first["hash"] == guide_hash and second["hash"] == universe_hash(preset_funds(tsp))
    assert [fund["id"] for fund in first["funds"]] == list(guide.funds)
    names = {fund["id"]: fund["name"] for fund in first["funds"]}
    assert names["VTI"] == "Vanguard Total Stock Market ETF"
    assert [fund["name"] for fund in second["funds"]] == [
        "G Fund",
        "F Fund",
        "C Fund",
        "S Fund",
        "I Fund",
    ]
    assert first["allocation"] == guide.allocation and first["allocation_unit"] == "$"
    assert second["allocation"] is None and second["allocation_unit"] is None
    assert set(first["lookbacks"]) == set(LOOKBACKS) == {"1y", "2y", "3y", "5y", "10y", "ew"}
    for lookback in LOOKBACKS:
        url = f"/api/tensors/{generation}/{guide_hash}/{lookback}"
        assert tensor_url(generation, guide_hash, lookback) == url
        assert first["lookbacks"][lookback] == {"status": "ready", "url": url}
        # A tensor the store does not hold is not offered as ready.
        assert second["lookbacks"][lookback] == {"status": "unavailable", "url": None}


def test_a_fund_the_catalog_does_not_know_is_named_by_its_id(store, generation, d_g):
    store.delete("meta/manifest.json")
    body = presets_body(generation, d_g.isoformat(), store)
    assert body["presets"][0]["funds"][0] == {"id": "VTI", "name": "VTI"}
    assert body["presets"][1]["funds"][0] == {"id": "TSP-G", "name": "G Fund"}
