"""The presets body (spec 6): three presets, the guide's dollar allocation, public tensor URLs."""

from __future__ import annotations

import csv
import json

import pytest

from portfoliosight.api.hashing import universe_hash
from portfoliosight.api.models import parse_tensor_request
from portfoliosight.api.presets import (
    LOOKBACKS,
    model_key,
    preset_definitions,
    preset_funds,
    presets_body,
    tensor_key,
    tensor_url,
)
from portfoliosight.data.universe import REPO_ROOT, load_presets

HOLDINGS = REPO_ROOT / "data" / "holdings" / "holdings_guide2017_step2.csv"
# The universe hashes the two older presets had before presets could declare limits. A preset
# without limits must keep its hash, or every stored tensor and shared link of it is orphaned.
GUIDE2017_HASH = "217cb8f5b0e890f3"
TSP_HASH = "63643e52f0386317"


def _by_id():
    return {preset.id: preset for preset in preset_definitions()}


def test_definitions_come_from_the_presets_file_and_the_holdings_csv():
    guide, tsp, research = preset_definitions()
    with HOLDINGS.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected = {row["Symbol"]: round(float(row["Qty"]) * float(row["Price"]), 2) for row in rows}
    assert guide.id == "guide2017" and guide.name == "Example Portfolio"
    assert len(guide.funds) == 23 and guide.allocation == expected
    assert sum(1 for amount in expected.values() if amount != 0) == 18
    assert guide.allocation_unit == "$"
    assert tsp.id == "tsp" and tsp.funds == ("TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I")
    assert tsp.allocation is None and tsp.allocation_unit is None
    assert research.id == "research2003" and research.name == "Example Portfolio 2"
    assert research.allocation_unit == "%" and len(research.funds) == 19
    assert research.allocation is not None
    assert round(sum(research.allocation.values()) * 100) == 10000


def test_preset_funds_are_the_all_default_policy_when_the_preset_declares_no_limits():
    tsp = _by_id()["tsp"]
    funds = preset_funds(tsp)
    assert funds == [{"id": fund, "min": None, "max": None} for fund in tsp.funds]


def test_a_preset_without_limits_keeps_the_hash_it_had_before_presets_could_declare_them():
    presets = _by_id()
    assert universe_hash(preset_funds(presets["guide2017"])) == GUIDE2017_HASH
    assert universe_hash(preset_funds(presets["tsp"])) == TSP_HASH


def test_preset_funds_carry_the_declared_limits_in_menu_order_and_nothing_else():
    research = _by_id()["research2003"]
    funds = preset_funds(research)
    assert [fund["id"] for fund in funds] == list(research.funds)
    assert {fund["id"]: (fund["min"], fund["max"]) for fund in funds} == {
        **{fund: (None, 0.4) for fund in research.funds[:11]},
        **{fund: (None, 0.1) for fund in research.funds[11:]},
    }
    assert universe_hash(funds) not in {GUIDE2017_HASH, TSP_HASH}


def test_the_hash_of_a_preset_is_the_hash_of_the_request_the_page_sends_for_its_limits():
    """The page asks for a menu with these limits by POST: its body must name the preset's key."""
    research = _by_id()["research2003"]
    body = {
        "funds": [
            {"id": fund["id"], "min": None, "max": round(fund["max"] * 100) / 100}
            for fund in preset_funds(research)
        ],
        "lookback": "5y",
    }
    posted = parse_tensor_request(json.dumps(body).encode(), max_funds=30)
    assert universe_hash(posted.policy()) == universe_hash(preset_funds(research))


def test_a_cap_written_as_a_whole_number_hashes_as_the_request_that_sends_it(tmp_path):
    """JSON 1 and 1.0 are two texts: the file's bound is read as a float, as the API reads one."""
    path = tmp_path / "data" / "presets.json"
    path.parent.mkdir()
    path.write_text(
        json.dumps(
            {
                "presets": [
                    {
                        "id": "p",
                        "name": "P",
                        "funds": ["VTI", "BND"],
                        "caps": {"VTI": {"min": 0, "max": 1}},
                        "allocation": None,
                    }
                ]
            }
        )
    )
    (preset,) = load_presets(path)
    request = {"funds": [{"id": "VTI", "min": 0, "max": 1}, {"id": "BND"}], "lookback": "5y"}
    posted = parse_tensor_request(json.dumps(request).encode(), max_funds=30)
    assert universe_hash(preset_funds(preset)) == universe_hash(posted.policy())


def test_body_has_the_spec_shape(store, generation, d_g):
    guide, tsp, research = preset_definitions()
    guide_hash = universe_hash(preset_funds(guide))
    for lookback in LOOKBACKS:
        store.put(tensor_key(generation, guide_hash, lookback), b"{}")
    body = presets_body(generation, d_g.isoformat(), store)
    assert body["generation"] == generation and body["asof"] == d_g.isoformat()
    first, second, third = body["presets"]
    assert [preset["id"] for preset in body["presets"]] == ["guide2017", "tsp", "research2003"]
    assert set(first) == {
        "id",
        "name",
        "hash",
        "funds",
        "caps",
        "allocation",
        "allocation_unit",
        "lookbacks",
    }
    assert first["hash"] == guide_hash and second["hash"] == universe_hash(preset_funds(tsp))
    assert third["hash"] == universe_hash(preset_funds(research))
    # limits: none declared for the two older presets, the declared ones for the third, in the
    # shape of a request's funds so a request with them hashes to the preset's key
    assert first["caps"] == [] and second["caps"] == []
    assert third["caps"] == [
        {"id": fund, "min": None, "max": 0.4 if i < 11 else 0.1}
        for i, fund in enumerate(research.funds)
    ]
    assert third["allocation_unit"] == "%" and third["allocation"] == research.allocation
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


def test_model_files_live_under_their_generation_and_shape_digest():
    """Engines spec 7: `models/{G}/{shape_sha256[:16]}/garch.json` and `pool.npy`."""
    generation, shape16 = "2026-10-15-0.3.0", "0123456789abcdef"
    assert model_key(generation, shape16, "garch.json") == (
        "models/2026-10-15-0.3.0/0123456789abcdef/garch.json"
    )
    assert model_key(generation, shape16, "pool.npy").endswith("/0123456789abcdef/pool.npy")
    for bad in ("0123456789abcde", "0123456789ABCDEF", "../../../../meta"):
        with pytest.raises(ValueError, match="16 hex"):
            model_key(generation, bad, "garch.json")
