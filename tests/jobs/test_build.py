"""One tensor from the store: pinned to D_G, catalog as it is now, never over an existing key."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import cast

import numpy as np
import pandas as pd
import pytest

from portfoliosight.api.hashing import universe_hash
from portfoliosight.api.presets import model_key, tensor_key
from portfoliosight.api.queue import build_job
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import returns as returns_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.providers import tiingo
from portfoliosight.engine import ENGINE_VERSION, builder
from portfoliosight.engine.ranges import one_year_ranges
from portfoliosight.engine.shape import ShapeError, artifact_from_json, pool_from_bytes
from portfoliosight.engine.tensor import build_tensor, canonical_json, validate_tensor
from portfoliosight.jobs.build import (
    BuildRefused,
    GenerationGone,
    KeyExists,
    RangeUnavailable,
    build_from_store,
    inputs_from_store,
    load_artifact,
    put_tensor,
    range_model_from_store,
)
from tests.data.test_splice import CUT, SEAM, VTI, _seed_record

MENU = ["VTI", "BND", "VNQ", "FIENX"]
GRID = {"nx": 12, "ny": 8, "levels": 3}


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


def _refetched(store, symbol: str, at: str) -> None:
    catalog = manifest_mod.load_manifest(store)
    catalog.symbols[symbol].fetched_at = at
    manifest_mod.write_catalog(store, catalog, datetime(2026, 10, 14, tzinfo=UTC))


def test_a_cached_record_is_used_until_the_catalog_says_it_was_refetched(
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
    folder = tmp_path / "cache" / "prices" / "VTI"
    before = list(folder.iterdir())
    assert len(before) == 1
    _refetched(store, "VTI", "2026-10-14T09:00:00+00:00")
    fresh = _build(store, generation, tmp_path, ids=MENU[:3])
    assert fresh["universe"]["funds"][0]["last_close"] == 1234.5
    after = list(folder.iterdir())
    assert len(after) == 1 and after != before  # the old version is dropped, not kept beside


def test_a_file_cached_under_an_old_version_never_serves_a_newer_catalog(
    store, generation, tmp_path, monkeypatch
):
    """Two processes share the cache: one still holds yesterday's catalog and yesterday's bytes.

    Whatever it writes lands under yesterday's version, so a build that reads today's catalog
    cannot pick it up, in any interleaving.
    """
    from portfoliosight.data import cache as cache_mod

    old_bytes = store.get("prices/VTI.parquet")
    record = store_mod.get_record(store, "VTI")
    record.loc[record.index[-1], "close"] = 1234.5
    store_mod.put_record(store, "VTI", record)
    _refetched(store, "VTI", "2026-10-14T09:00:00+00:00")
    real_fetch = cache_mod.fetch_into_cache
    late_writes: list = []

    def fetch_while_the_other_process_writes(store_, key, *, cache_dir):
        if key.startswith("prices/VTI/") and not late_writes:
            # The slow process finishes now: yesterday's bytes under yesterday's version.
            stale = cache_mod.cached_path(cache_dir, "prices/VTI/0000000000000000.parquet")
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_bytes(old_bytes)
            late_writes.append(stale)
        return real_fetch(store_, key, cache_dir=cache_dir)

    monkeypatch.setattr(cache_mod, "fetch_into_cache", fetch_while_the_other_process_writes)
    tensor = _build(store, generation, tmp_path, ids=MENU[:3])
    assert late_writes and tensor["universe"]["funds"][0]["last_close"] == 1234.5
    again = _build(store, generation, tmp_path, ids=MENU[:3])
    assert again["universe"]["funds"][0]["last_close"] == 1234.5


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


def test_an_allocation_becomes_the_entered_mix(store, generation, tmp_path):
    assert _build(store, generation, tmp_path)["entered"] is None
    held = {"VTI": 300.0, "BND": 100.0, "FIENX": 100.0}  # FIENX is set aside by every view
    entered = _build(store, generation, tmp_path, allocation=held)["entered"]
    assert entered["w"] == [0.75, 0.25, 0.0] and entered["set_aside"] == 0.2
    assert entered["range"]["bad"] < entered["range"]["typical"] < entered["range"]["good"]


def _stored(store, generation, tmp_path, ids=MENU, lookback="1y") -> tuple[str, dict]:
    tensor = _build(store, generation, tmp_path, ids=ids, lookback=lookback)
    key = tensor_key(generation, tensor["universe"]["hash"], lookback)
    put_tensor(store, key, tensor)
    return key, tensor


def test_range_model_of_a_stored_tensor_repeats_the_tensor_s_own_ranges(
    store, generation, tmp_path
):
    """The sample is read back from the price records: the same ranges as at build time."""
    for ids, lookback in ((MENU, "1y"), (["VTI", "BND", "VNQ", "TSP-C"], "5y")):
        key, tensor = _stored(store, generation, tmp_path, ids=ids, lookback=lookback)
        recording = _Recording(store)
        scratch = tmp_path / f"fresh-{lookback}"
        model = range_model_from_store(cast(store_mod.Store, recording), key, cache_dir=scratch)
        funds = [fund["id"] for fund in tensor["universe"]["funds"]]
        assert model.sample.shape == (tensor["lookback"]["rows"], len(funds))
        assert model.mu_s.tolist() == tensor["mu_s"] and model.cov.tolist() == tensor["cov"]
        again = one_year_ranges(model, tensor["frontier"]["w"])
        stored = tensor["frontier"]["range"]
        for name in ("bad", "typical", "good"):
            assert again[name] == pytest.approx(stored[name], rel=1e-12, abs=1e-15)
        assert again["normal"]["low"] == pytest.approx(stored["normal"]["low"], rel=1e-12)
        # only the tensor, the catalog and the records of its own funds were read
        prices = sorted(k for k in recording.gets if k.startswith("prices/"))
        assert prices == sorted(f"prices/{fund}.parquet" for fund in funds)
        assert key in recording.gets


def test_range_model_uses_the_funds_a_view_set_aside_for_its_calendar(store, generation, tmp_path):
    """A fund too young for the view is priced, so its days are on the build's calendar."""
    young = store_mod.get_record(store, "VNQ")
    recent = young.loc[young["date"] >= pd.Timestamp("2023-01-03")].reset_index(drop=True)
    recent["tr_index"] = recent["tr_index"] / recent["tr_index"].iloc[0]
    store_mod.put_record(store, "VNQ", recent)
    key, tensor = _stored(store, generation, tmp_path, ids=["VTI", "BND", "VNQ"], lookback="5y")
    assert [entry["id"] for entry in tensor["universe"]["excluded"]] == ["VNQ"]
    recording = _Recording(store)
    scratch = tmp_path / "fresh"
    model = range_model_from_store(cast(store_mod.Store, recording), key, cache_dir=scratch)
    assert "prices/VNQ.parquet" in recording.gets and model.sample.shape == (1260, 2)
    again = one_year_ranges(model, tensor["frontier"]["w"])
    assert again["bad"] == pytest.approx(tensor["frontier"]["range"]["bad"], rel=1e-12)


def test_range_model_needs_the_tensor_and_its_records(store, generation, tmp_path):
    with pytest.raises(KeyError):
        range_model_from_store(store, "tensors/none/0/1y.json", cache_dir=tmp_path / "cache")
    key, _ = _stored(store, generation, tmp_path)
    store.delete("prices/BND.parquet")
    with pytest.raises(RangeUnavailable, match="BND: its price record is no longer stored"):
        range_model_from_store(store, key, cache_dir=tmp_path / "other-cache")
    manifest = manifest_mod.load_manifest(store)
    del manifest.symbols["VTI"]
    manifest_mod.write_catalog(store, manifest, datetime.now(UTC))
    with pytest.raises(RangeUnavailable, match="VTI"):
        range_model_from_store(store, key, cache_dir=tmp_path / "other-cache")


def test_range_model_refuses_a_window_with_no_shared_days_left(store, generation, tmp_path):
    key, _ = _stored(store, generation, tmp_path)
    record = store_mod.get_record(store, "BND")
    store_mod.put_record(store, "BND", record.iloc[:3].reset_index(drop=True))
    manifest = manifest_mod.load_manifest(store)
    manifest.symbols["BND"].fetched_at = "2026-10-14T00:00:00+00:00"  # a newer record
    manifest_mod.write_catalog(store, manifest, datetime.now(UTC))
    with pytest.raises(RangeUnavailable, match="no longer holds two shared days"):
        range_model_from_store(store, key, cache_dir=tmp_path / "cache")


def test_range_model_of_an_ew_tensor_repeats_its_ranges(store, generation, tmp_path):
    key, tensor = _stored(store, generation, tmp_path, lookback="ew")
    assert tensor["lookback"]["ew_halflife_days"] is not None
    model = range_model_from_store(store, key, cache_dir=tmp_path / "cache")
    again = one_year_ranges(model, tensor["frontier"]["w"])
    assert again["bad"] == pytest.approx(tensor["frontier"]["range"]["bad"], rel=1e-12)


def _corrected(store, fund: str, day: str, by: float) -> None:
    """Restate one day of a fund's history, as a provider correction would."""
    record = store_mod.get_record(store, fund)
    later = record["date"] >= pd.Timestamp(day)
    record.loc[later, "tr_index"] = record.loc[later, "tr_index"] * (1.0 + by)
    store_mod.put_record(store, fund, record)
    manifest = manifest_mod.load_manifest(store)
    manifest.symbols[fund].fetched_at = "2026-10-14T00:00:00+00:00"  # a newer record
    manifest_mod.write_catalog(store, manifest, datetime.now(UTC))


def test_range_model_refuses_history_that_changed_after_the_build(store, generation, tmp_path):
    """The endpoint answers from the build's own sample or not at all."""
    key, tensor = _stored(store, generation, tmp_path)
    start = date.fromisoformat(tensor["lookback"]["start"])
    _corrected(store, "BND", (start + timedelta(days=180)).isoformat(), 1e-4)  # one restated day
    with pytest.raises(RangeUnavailable, match="changed after it was built"):
        range_model_from_store(store, key, cache_dir=tmp_path / "cache")


def test_a_restatement_that_keeps_every_mean_is_still_refused(store, generation, tmp_path):
    """Two opposite restatements leave the fund's mean where it was; the digest still moves."""
    key, tensor = _stored(store, generation, tmp_path)
    start = date.fromisoformat(tensor["lookback"]["start"])
    _corrected(store, "VTI", (start + timedelta(days=90)).isoformat(), 2e-3)
    _corrected(store, "VTI", (start + timedelta(days=95)).isoformat(), 1 / (1 + 2e-3) - 1)
    with pytest.raises(RangeUnavailable, match="changed after it was built"):
        range_model_from_store(store, key, cache_dir=tmp_path / "cache")


def test_range_model_refuses_a_tensor_made_with_another_method(store, generation, tmp_path):
    key, tensor = _stored(store, generation, tmp_path)
    put_tensor(
        store, key + ".other", {**tensor, "range_method": {**tensor["range_method"], "paths": 500}}
    )
    with pytest.raises(RangeUnavailable, match="another method"):
        range_model_from_store(store, key + ".other", cache_dir=tmp_path / "cache")
    other = {**tensor, "lookback": {**tensor["lookback"], "sample_sha256": "0" * 64}}
    put_tensor(store, key + ".other-sample", other)
    with pytest.raises(RangeUnavailable, match="changed after it was built"):
        range_model_from_store(store, key + ".other-sample", cache_dir=tmp_path / "cache")


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
        if key.startswith("prices/VTI/"):
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
        if key.startswith("prices/VNQ/"):
            path.unlink()
            store.delete("prices/VNQ.parquet")
        return path

    monkeypatch.setattr(cache_mod, "fetch_into_cache", fetch_then_delete_everywhere)
    tensor = _build(store, generation, tmp_path, ids=["VTI", "BND", "VNQ"])
    assert [fund["id"] for fund in tensor["universe"]["funds"]] == ["VTI", "BND"]


# --- inputs from the store, splice dates, and the volatility model's files (plan Phase 3) ---


def _inputs(store, d_g, tmp_path, ids=MENU, lookback="1y", **kwargs):
    return inputs_from_store(
        store,
        funds=_funds(ids),
        lookback=lookback,
        asof=d_g,
        cache_dir=tmp_path / "cache",
        **GRID,
        **kwargs,
    )


def test_inputs_from_store_are_the_inputs_of_a_build(store, generation, d_g, tmp_path):
    held = {"VTI": 300.0, "BND": 100.0, "FIENX": 100.0}
    inputs = _inputs(store, d_g, tmp_path, allocation=held)
    assert [fund.id for fund in inputs.funds] == MENU and inputs.lookback == "1y"
    assert inputs.asof == d_g and inputs.engines == ("replay", "garch")
    assert inputs.universe_name == "Custom menu" and inputs.preset_id is None
    assert inputs.allocation == held and inputs.garch_artifact is None
    assert (inputs.nx, inputs.ny, inputs.levels) == (12, 8, 3)
    assert inputs.requested_bounds == _funds(MENU)
    # only served funds are priced; rows after D_G are never read
    served = {fund: store_mod.get_record(store, fund) for fund in MENU[:3]}
    expected = returns_mod.build_returns(served).loc[: pd.Timestamp(d_g)]
    pd.testing.assert_frame_equal(inputs.returns, expected, check_freq=False)
    assert sorted(inputs.tr_index or {}) == sorted(MENU[:3])
    assert sorted(inputs.rf_series or {}) == ["TSP-G"]
    # the fixture's records carry their actions on every row: nothing was spliced
    assert inputs.splice_dates == {}
    built = _build(store, generation, tmp_path, allocation=held)
    assert _scrub(build_tensor(inputs)) == _scrub(built)
    replay_only = _inputs(store, d_g, tmp_path, engines=("replay",))
    assert replay_only.engines == ("replay",)


def _with_catalog_version(store, symbol: str, at: str) -> None:
    catalog = manifest_mod.load_manifest(store)
    catalog.symbols[symbol].fetched_at = at
    manifest_mod.write_catalog(store, catalog, datetime(2026, 10, 14, tzinfo=UTC))


def test_splice_dates_mark_where_a_seeded_record_s_provider_tail_starts(store, d_g, tmp_path):
    """Seed rows carry no actions, provider rows do (tests/data/test_splice.py's records)."""
    rows = json.loads(VTI.read_text())
    seeded, _ = returns_mod.splice_tail(_seed_record(rows), tiingo.rows_to_frame(rows), CUT)
    store_mod.put_record(store, "VTI", seeded)
    _with_catalog_version(store, "VTI", "2026-10-14T09:00:00+00:00")
    lake = store_mod.get_record(store, "BND")  # a lake record: no actions on any row
    lake["div_cash"] = lake["split_factor"] = np.nan
    store_mod.put_record(store, "BND", lake)
    _with_catalog_version(store, "BND", "2026-10-14T09:00:00+00:00")
    inputs = _inputs(store, d_g, tmp_path, ids=["VTI", "BND", "VNQ", "TSP-C"])
    # the provider-only VNQ and the TSP fund carry actions on every row: no splice either
    assert inputs.splice_dates == {"VTI": SEAM}


def _seeded_before(store, fund: str, day: str, drop: float = 0.0) -> None:
    """Make a fixture record look seeded up to ``day`` (no actions), optionally with a fall."""
    record = store_mod.get_record(store, fund)
    head = record["date"] < pd.Timestamp(day)
    record.loc[head, ["div_cash", "split_factor"]] = np.nan
    record.loc[~head, "tr_index"] = record.loc[~head, "tr_index"] * (1.0 + drop)
    store_mod.put_record(store, fund, record)
    _with_catalog_version(store, fund, "2026-10-14T09:00:00+00:00")


def test_a_corporate_action_missed_at_the_splice_fails_the_build_naming_fund_and_date(
    store, generation, tmp_path
):
    day = "2024-03-01"
    _seeded_before(store, "VTI", day, drop=-0.3)
    with pytest.raises(ShapeError) as caught:
        _build(store, generation, tmp_path, ids=["VTI", "BND", "VNQ"], lookback="5y")
    assert (caught.value.fund, caught.value.date) == ("VTI", day)
    assert store.list("models/") == []


def test_the_same_fall_away_from_the_splice_is_an_outlier(store, generation, tmp_path):
    _seeded_before(store, "VTI", "2024-03-01")
    record = store_mod.get_record(store, "VTI")
    later = record["date"] >= pd.Timestamp("2025-06-02")
    record.loc[later, "tr_index"] = record.loc[later, "tr_index"] * 0.7
    store_mod.put_record(store, "VTI", record)
    _with_catalog_version(store, "VTI", "2026-10-15T09:00:00+00:00")
    tensor = _build(store, generation, tmp_path, ids=["VTI", "BND", "VNQ"], lookback="5y")
    outliers = [(entry["id"], entry["date"]) for entry in tensor["shape"]["outliers"]]
    assert ("VTI", "2025-06-02") in outliers


@pytest.fixture
def job_env(monkeypatch, tmp_path):
    """What ``build_job`` reads: a scratch cache, a small grid, both engines everywhere."""
    monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PS_CACHE_MAX_MB", "300")
    monkeypatch.setenv("PS_GRID_NX", "12")
    monkeypatch.setenv("PS_GRID_NY", "8")
    monkeypatch.setenv("PS_GRID_LEVELS", "3")
    monkeypatch.delenv("PS_ENGINES", raising=False)
    monkeypatch.delenv("PS_ENGINES_CUSTOM", raising=False)
    return monkeypatch


class _Writes:
    """A store that records every key written, in order."""

    def __init__(self, inner):
        self._inner = inner
        self.puts: list[str] = []
        self.gets: list[str] = []

    def put(self, key, data):
        self.puts.append(key)
        return self._inner.put(key, data)

    def get(self, key):
        self.gets.append(key)
        return self._inner.get(key)

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture
def fits(monkeypatch):
    """The panels the volatility model was fitted to, in order."""
    seen: list = []
    real = builder.fit_shape

    def counted(panel, splice_dates=None):
        seen.append(panel)
        return real(panel, splice_dates)

    monkeypatch.setattr(builder, "fit_shape", counted)
    return seen


def _job(store, generation, lookback, ids=("VTI", "BND", "VNQ"), **names):
    funds = _funds(ids)
    uhash = universe_hash(funds)
    build_job(store, generation, uhash, lookback, funds, **names)
    return json.loads(store.get(tensor_key(generation, uhash, lookback)))


def test_a_build_stores_its_fit_before_its_tensor_and_other_lookbacks_reuse_it(
    store, generation, job_env, fits
):
    writes = _Writes(store)
    first = _job(writes, generation, "1y")
    shape16 = first["shape"]["sample_sha256"][:16]
    files = [model_key(generation, shape16, name) for name in ("pool.npy", "garch.json")]
    tensor = tensor_key(generation, first["universe"]["hash"], "1y")
    assert writes.puts == [*files, tensor]  # the pool, its description, then the tensor
    assert len(fits) == 1 and first["engines"]["garch"]["status"] == "ready"
    doc = json.loads(store.get(files[1]))
    stored = artifact_from_json(doc, pool_from_bytes(store.get(files[0])))
    assert stored.sample_sha256 == first["shape"]["sample_sha256"]
    assert stored.funds == ("VTI", "BND", "VNQ") and stored.pool_rows == first["shape"]["pool_rows"]
    writes.puts.clear()
    for lookback in ("5y", "ew"):
        again = _job(writes, generation, lookback)
        assert again["shape"] == first["shape"] and again["engines"] == first["engines"]
    assert len(fits) == 1  # one fit for the fund set, whatever the lookback
    assert [key for key in writes.puts if key.startswith("models/")] == []


def test_a_lookback_that_admits_another_fund_fits_and_stores_its_own_model(
    store, generation, job_env, fits
):
    young = store_mod.get_record(store, "VNQ")
    recent = young.loc[young["date"] >= pd.Timestamp("2023-01-03")].reset_index(drop=True)
    recent["tr_index"] = recent["tr_index"] / recent["tr_index"].iloc[0]
    store_mod.put_record(store, "VNQ", recent)
    five = _job(store, generation, "5y")
    one = _job(store, generation, "1y")
    assert [f["id"] for f in five["shape"]["funds"]] == ["VTI", "BND"]
    assert [f["id"] for f in one["shape"]["funds"]] == ["VTI", "BND", "VNQ"]
    assert len(fits) == 2
    folders = {key.split("/")[2] for key in store.list(f"models/{generation}/")}
    assert folders == {five["shape"]["sample_sha256"][:16], one["shape"]["sample_sha256"][:16]}
    two = _job(store, generation, "2y")  # VNQ is in this view too: the 1y fit serves it
    assert two["shape"] == one["shape"] and len(fits) == 2


def test_a_stored_model_is_never_overwritten(store, generation, job_env, fits, tmp_path):
    first = _job(store, generation, "1y")
    shape16 = first["shape"]["sample_sha256"][:16]
    key = model_key(generation, shape16, "garch.json")
    # A model stored under this folder that is not this panel's (another digest with the same
    # first 16 digits): the build fits its own and leaves the stored files as they are.
    doc = json.loads(store.get(key))
    doc["sample_sha256"] = shape16 + "0" * 48
    foreign = canonical_json(doc).encode()
    store.put(key, foreign)
    pool = store.get(model_key(generation, shape16, "pool.npy"))
    assert not (tmp_path / "cache" / "models").exists()  # so the next build reads the store's
    again = _job(store, generation, "5y")
    assert len(fits) == 2 and again["shape"] == first["shape"]
    assert store.get(key) == foreign
    assert store.get(model_key(generation, shape16, "pool.npy")) == pool


def test_model_files_are_read_through_the_scratch_cache_within_its_cap(
    store, generation, job_env, tmp_path
):
    first = _job(store, generation, "1y")
    shape16 = first["shape"]["sample_sha256"][:16]
    cache = tmp_path / "cache"
    assert not (cache / "models").exists()  # written to the store, not to the cache
    _job(store, generation, "5y")
    for name in ("garch.json", "pool.npy"):
        assert (cache / "models" / generation / shape16 / name).is_file()
    reads = _Writes(store)
    loaded = load_artifact(cast(store_mod.Store, reads), generation, shape16, cache_dir=cache)
    assert loaded is not None and loaded.sample_sha256 == first["shape"]["sample_sha256"]
    assert [key for key in reads.gets if key.startswith("models/")] == []  # a cache hit
    assert load_artifact(store, generation, "f" * 16, cache_dir=cache) is None
    job_env.setenv("PS_CACHE_MAX_MB", "0.05")
    _job(store, generation, "ew")
    cached = [path for path in cache.rglob("*") if path.is_file()]
    assert sum(path.stat().st_size for path in cached) <= 50_000


def test_an_unavailable_model_is_stored_without_a_pool_and_reused(
    store, generation, job_env, fits, monkeypatch
):
    from portfoliosight.engine import shape as shape_mod

    monkeypatch.setattr(shape_mod, "MIN_POOL_ROWS", 10_000)  # no fund set has that many days
    first = _job(store, generation, "1y")
    assert first["engines"]["garch"]["status"] == "unavailable"
    shape16 = first["shape"]["sample_sha256"][:16]
    assert store.list(f"models/{generation}/") == [model_key(generation, shape16, "garch.json")]
    again = _job(store, generation, "5y")
    assert again["engines"]["garch"] == first["engines"]["garch"] and len(fits) == 1


def test_a_generation_whose_name_and_day_disagree_is_not_built(store, d_g, tmp_path):
    named = f"{(d_g - timedelta(days=1)).isoformat()}-{ENGINE_VERSION}"
    store_mod.put_json(
        store,
        f"meta/{named}/generation.json",
        {"generation": named, "asof": d_g.isoformat(), "engine_version": ENGINE_VERSION},
    )
    with pytest.raises(RuntimeError, match="is not dated"):
        _build(store, named, tmp_path)
    assert store.list("models/") == []
