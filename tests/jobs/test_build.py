"""One tensor from the store: pinned to D_G, catalog as it is now, never over an existing key."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.engine.tensor import canonical_json, validate_tensor
from portfoliosight.jobs.build import (
    BuildRefused,
    GenerationGone,
    KeyExists,
    build_from_store,
    put_tensor,
)

MENU = ["VTI", "BND", "VNQ", "FIENX"]
GRID = {"nx": 12, "ny": 8}


def _funds(ids, **caps):
    return [
        {"id": i, "min": caps.get(i, (None, None))[0], "max": caps.get(i, (None, None))[1]}
        for i in ids
    ]


def _scrub(tensor: dict) -> dict:
    out = json.loads(json.dumps(tensor))
    out.pop("built_at")
    out.pop("build_seconds")
    for fund in out["universe"]["funds"]:
        fund.pop("fetched_at")
        fund.pop("adjusted_through")
    return out


class _Recording:
    def __init__(self, inner):
        self._inner = inner
        self.gets: list[str] = []

    def get(self, key):
        self.gets.append(key)
        return self._inner.get(key)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _build(store, generation, tmp_path, ids=MENU, lookback="1y", **kwargs):
    return build_from_store(
        store,
        generation=generation,
        funds=kwargs.pop("funds", _funds(ids)),
        lookback=lookback,
        cache_dir=tmp_path / "cache",
        **GRID,
        **kwargs,
    )


def test_tensor_is_pinned_to_the_generation_and_reads_only_what_it_needs(
    store, generation, d_g, tmp_path
):
    recording = _Recording(store)
    tensor = _build(recording, generation, tmp_path)
    validate_tensor(tensor)
    assert tensor["generation"] == generation and tensor["asof"] == d_g.isoformat()
    assert tensor["lookback"]["id"] == "1y" and tensor["lookback"]["end"] == d_g.isoformat()
    assert tensor["universe"]["name"] == "Custom menu" and tensor["universe"]["preset_id"] is None
    assert [fund["id"] for fund in tensor["universe"]["funds"]] == ["VTI", "BND", "VNQ"]
    assert tensor["universe"]["excluded"] == [
        {
            "id": "FIENX",
            "reason": "converted to an ETF; no data since 2024-10-30",
            "last_close": None,
        }
    ]
    assert len(tensor["frontier"]["x"]) == 12 and len(tensor["grid"]["y"]) == 8
    vti = store_mod.get_record(store, "VTI")
    fund = tensor["universe"]["funds"][0]
    assert fund["last_close"] == pytest.approx(float(vti["close"].iloc[-1]), rel=1e-12)
    assert fund["adjusted_through"] == d_g.isoformat() and fund["source"] == "seed+tiingo"
    assert tensor["built_at"].endswith("Z")
    # Only served funds are read, plus the served G Fund for the risk-free rate.
    assert sorted(key for key in recording.gets if key.startswith("prices/")) == [
        "prices/BND.parquet",
        "prices/TSP-G.parquet",
        "prices/VNQ.parquet",
        "prices/VTI.parquet",
    ]
    assert f"meta/{generation}/generation.json" in recording.gets
    assert "meta/manifest.json" in recording.gets


def test_risk_free_rate_comes_from_the_served_g_fund(store, generation, tmp_path):
    with_g = _build(store, generation, tmp_path)
    catalog = manifest_mod.load_manifest(store)
    catalog.symbols["TSP-G"].status = "stale"
    manifest_mod.write_catalog(store, catalog, datetime(2026, 10, 13, tzinfo=UTC))
    without = _build(store, generation, tmp_path)
    assert without["rf"] == 0.04 and with_g["rf"] != 0.04


def test_rows_after_d_g_change_nothing(store, generation, d_g, tmp_path):
    before = _build(store, generation, tmp_path, ids=MENU[:3])
    catalog = manifest_mod.load_manifest(store)
    later = d_g + timedelta(days=1)
    for symbol in MENU[:3]:
        record = store_mod.get_record(store, symbol)
        extra = record.iloc[[-1]].copy()
        extra["date"] = pd.Timestamp(later)
        extra["close"] = record["close"].iloc[-1] * 3.0
        extra["tr_index"] = record["tr_index"].iloc[-1] * 3.0
        store_mod.put_record(store, symbol, pd.concat([record, extra], ignore_index=True))
        entry = catalog.symbols[symbol]
        entry.last_date = entry.adjusted_through = later
        entry.fetched_at = "2026-10-14T09:00:00+00:00"
    manifest_mod.write_catalog(store, catalog, datetime(2026, 10, 14, tzinfo=UTC))
    after = _build(store, generation, tmp_path, ids=MENU[:3])
    assert _scrub(after) == _scrub(before)
    assert after["universe"]["funds"][0]["adjusted_through"] == later.isoformat()


def test_a_cached_record_is_dropped_when_the_catalog_says_it_was_refetched(
    store, generation, d_g, tmp_path
):
    first = _build(store, generation, tmp_path, ids=MENU[:3])
    record = store_mod.get_record(store, "VTI")
    record.loc[record.index[-1], "close"] = 1234.5
    store_mod.put_record(store, "VTI", record)
    cached = _build(store, generation, tmp_path, ids=MENU[:3])
    assert (
        cached["universe"]["funds"][0]["last_close"] == first["universe"]["funds"][0]["last_close"]
    )
    catalog = manifest_mod.load_manifest(store)
    catalog.symbols["VTI"].fetched_at = "2026-10-14T09:00:00+00:00"
    manifest_mod.write_catalog(store, catalog, datetime(2026, 10, 14, tzinfo=UTC))
    fresh = _build(store, generation, tmp_path, ids=MENU[:3])
    assert fresh["universe"]["funds"][0]["last_close"] == 1234.5


def test_a_fund_without_a_price_on_d_g_has_no_last_close(store, generation, tmp_path):
    record = store_mod.get_record(store, "BND")
    store_mod.put_record(store, "BND", record.iloc[:-1])
    tensor = _build(store, generation, tmp_path, ids=MENU[:3])
    closes = {fund["id"]: fund["last_close"] for fund in tensor["universe"]["funds"]}
    assert closes["BND"] is None and closes["VTI"] is not None


def test_requested_caps_and_preset_names_reach_the_tensor(store, generation, tmp_path):
    funds = _funds(MENU[:3], VTI=(0.1, 0.6))
    tensor = _build(
        store, generation, tmp_path, funds=funds, universe_name="A preset", preset_id="p1"
    )
    assert tensor["bounds"]["requested"][0] == {"min": 0.1, "max": 0.6}
    assert tensor["bounds"]["min"][0] == 0.1 and tensor["bounds"]["max"][0] == 0.6
    assert tensor["universe"]["name"] == "A preset" and tensor["universe"]["preset_id"] == "p1"


def test_missing_generation_is_generation_gone(store, generation, tmp_path):
    store.delete(f"meta/{generation}/generation.json")
    with pytest.raises(GenerationGone) as caught:
        _build(store, generation, tmp_path)
    assert caught.value.code == "generation_gone" and caught.value.details is None


def test_generation_of_another_engine_is_refused(store, generation, d_g, tmp_path):
    other = f"{d_g.isoformat()}-9.9.9"
    store_mod.put_json(
        store,
        f"meta/{other}/generation.json",
        {"generation": other, "asof": d_g.isoformat(), "engine_version": "9.9.9"},
    )
    with pytest.raises(BuildRefused) as caught:
        _build(store, other, tmp_path)
    assert caught.value.code == "engine_version_mismatch"


def test_too_little_shared_history_is_refused_with_the_reason(store, generation, tmp_path):
    for symbol in ("VTI", "BND"):
        record = store_mod.get_record(store, symbol)
        short = record.iloc[-100:].reset_index(drop=True)
        short["tr_index"] = short["tr_index"] / short["tr_index"].iloc[0]
        store_mod.put_record(store, symbol, short)
    with pytest.raises(BuildRefused) as caught:
        _build(store, generation, tmp_path, ids=["VTI", "BND"], lookback="5y")
    assert caught.value.code == "window_unavailable"
    assert caught.value.details == {
        "lookback": "5y",
        "reason": "not enough shared history",
        "rows": 0,
    }


def test_caps_the_included_funds_cannot_meet_are_refused(store, generation, tmp_path):
    funds = _funds(["VTI", "BND", "FIENX"], VTI=(None, 0.3), BND=(None, 0.3))
    with pytest.raises(BuildRefused) as caught:
        _build(store, generation, tmp_path, funds=funds)
    assert caught.value.code == "caps_infeasible"
    assert "sum" in (caught.value.details or {})["reason"]


def test_unknown_and_unrecorded_funds_are_left_out(store, generation, tmp_path):
    store.delete("prices/VNQ.parquet")
    tensor = _build(store, generation, tmp_path, ids=["VTI", "BND", "VNQ", "NOSUCH"])
    assert [fund["id"] for fund in tensor["universe"]["funds"]] == ["VTI", "BND"]
    assert {fund["id"]: fund["reason"] for fund in tensor["universe"]["excluded"]} == {
        "VNQ": "no data",
        "NOSUCH": "no data",
    }


def test_put_tensor_never_overwrites(store, generation, tmp_path):
    tensor = _build(store, generation, tmp_path, ids=MENU[:3])
    key = f"tensors/{generation}/{tensor['universe']['hash']}/1y.json"
    put_tensor(store, key, tensor)
    stored = store.get(key)
    assert stored == canonical_json(tensor).encode()
    with pytest.raises(KeyExists):
        put_tensor(store, key, {**tensor, "rf": 0.5})
    assert store.get(key) == stored


def test_a_record_evicted_between_fetch_and_read_is_read_from_the_store(
    store, generation, tmp_path, monkeypatch
):
    from portfoliosight.data import cache as cache_mod

    real_fetch = cache_mod.fetch_into_cache

    def fetch_then_lose(store_, key, *, cache_dir):
        path = real_fetch(store_, key, cache_dir=cache_dir)
        if key == "prices/VTI.parquet":
            path.unlink()
        return path

    monkeypatch.setattr(cache_mod, "fetch_into_cache", fetch_then_lose)
    tensor = _build(store, generation, tmp_path, ids=MENU[:3])
    assert [fund["id"] for fund in tensor["universe"]["funds"]] == MENU[:3]


def test_a_record_deleted_from_the_store_mid_build_is_no_data(
    store, generation, tmp_path, monkeypatch
):
    from portfoliosight.data import cache as cache_mod

    real_fetch = cache_mod.fetch_into_cache

    def fetch_then_delete_everywhere(store_, key, *, cache_dir):
        path = real_fetch(store_, key, cache_dir=cache_dir)
        if key == "prices/VNQ.parquet":
            path.unlink()
            store_.delete(key)
        return path

    monkeypatch.setattr(cache_mod, "fetch_into_cache", fetch_then_delete_everywhere)
    tensor = _build(store, generation, tmp_path, ids=["VTI", "BND", "VNQ"])
    assert [fund["id"] for fund in tensor["universe"]["funds"]] == ["VTI", "BND"]
