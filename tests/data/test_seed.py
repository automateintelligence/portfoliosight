"""The one-time seed from the lake (spec 5.4; A-PS-04)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfoliosight.data import store as store_mod
from portfoliosight.data.store import LocalStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_LAKE = ROOT / "tests" / "fixtures" / "lake"
THROUGH = "2026-02-27"
LAKE_COLUMNS = ["date", "open", "high", "low", "close", "adj_close", "volume"]
EXPECTED_LATEST = {"VTI": "2025-12-19", "AAPL": "2026-02-06", "SGOV": "2026-01-30"}


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


seed = _load_script("seed_r2_from_lake")
make_lake_fixture = _load_script("make_lake_fixture")


def _snapshot(lake: Path) -> dict[str, str]:
    return {
        str(path.relative_to(lake)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(lake.rglob("*"))
        if path.is_file()
    }


def _build_lake(root: Path, n_files: int) -> Path:
    """The three fixture files plus short slices of them, a csv and an empty folder."""
    root.mkdir(parents=True)
    frames = {}
    for path in sorted(FIXTURE_LAKE.glob("*.parquet")):
        shutil.copyfile(path, root / path.name)
        frames[path.stem] = pd.read_parquet(path)
    names = sorted(frames)
    for i in range(1, n_files - len(names) + 1):
        frames[names[i % 3]].iloc[262:312].to_parquet(root / f"ZZF{i:04d}.parquet", index=False)
    (root / "NOTES.csv").write_text("date,close\n2026-01-02,1.0\n")
    (root / "dividends").mkdir()
    return root


@pytest.fixture
def lake(tmp_path, monkeypatch) -> Path:
    """A ten-file lake; the 1,000-file floor is lowered for these tests only (it has its own)."""
    monkeypatch.setattr(seed, "MIN_FILES", 10)
    return _build_lake(tmp_path / "eod_history", 10)


@pytest.fixture
def store_env(tmp_path, monkeypatch) -> LocalStore:
    monkeypatch.setenv("PS_STORE", "local")
    monkeypatch.setenv("PS_LOCAL_STORE_DIR", str(tmp_path / "store"))
    return LocalStore(tmp_path / "store")


def _run(lake: Path, *extra: str, through: str = THROUGH) -> int:
    before = _snapshot(lake) if lake.is_dir() else {}
    code = seed.main(["--lake", str(lake), "--adjusted-through", through, *extra])
    assert (_snapshot(lake) if lake.is_dir() else {}) == before, "the seed changed the lake"
    return code


def test_fixture_lake_is_what_the_generator_writes():
    assert sorted(p.stem for p in FIXTURE_LAKE.glob("*.parquet")) == ["AAPL", "SGOV", "VTI"]
    for symbol, latest in EXPECTED_LATEST.items():
        committed = pd.read_parquet(FIXTURE_LAKE / f"{symbol}.parquet")
        pd.testing.assert_frame_equal(committed, make_lake_fixture.build(symbol))
        assert list(committed.columns) == [
            "date",
            "open",
            "high",
            "low",
            "close",
            "adj_close",
            "volume",
        ]
        differs = committed["adj_close"] != committed["close"]
        assert str(committed.loc[differs, "date"].iloc[-1])[:10] == latest
        assert len(committed) == 312 and str(committed["date"].iloc[-1])[:10] == "2026-03-13"


def test_seed_converts_the_lake_and_resumes(lake, store_env, capsys):
    assert _run(lake) == 0
    out = capsys.readouterr().out
    assert "10 symbols checked, 10 to seed" in out and "seeded 10 symbols (0 already" in out
    assert len(store_env.list("prices/")) == 10 and "prices/NOTES.parquet" not in store_env.list()
    entries = json.loads(store_env.get("meta/manifest.json"))["symbols"]
    assert len(entries) == 10 and not store_env.exists("meta/symbols.json")

    for symbol in EXPECTED_LATEST:
        source = pd.read_parquet(FIXTURE_LAKE / f"{symbol}.parquet")
        record = store_mod.get_record(store_env, symbol)
        assert list(record.columns) == ["date", "close", "tr_index", "div_cash", "split_factor"]
        assert [str(d)[:10] for d in record["date"]] == [str(d)[:10] for d in source["date"]]
        np.testing.assert_array_equal(record["close"].to_numpy(), source["close"].to_numpy())
        inside = (record["date"] <= pd.Timestamp(THROUGH)).to_numpy()
        tr = record["tr_index"].to_numpy()
        adj = source["adj_close"].to_numpy()
        assert tr[0] == 1.0 and (~inside).sum() == 10
        np.testing.assert_allclose(tr[inside], adj[inside] / adj[0], rtol=1e-15)
        assert np.isnan(tr[~inside]).all()
        assert np.isnan(record[["div_cash", "split_factor"]].to_numpy()).all()
        raw = source["close"].to_numpy()
        assert bool(np.abs(tr[inside] - raw[inside] / raw[0]).max() > 1e-6)
    assert entries["VTI"] == {
        "name": "VTI",
        "kind": "etf",
        "tier": 1,
        "income": False,
        "source": "seed",
        "first_date": "2025-01-02",
        "last_date": "2026-03-13",
        "adjusted_through": THROUGH,
        "status": "pending",
        "reason": "corporate actions not yet verified after 2026-02-27",
        "fetched_at": None,
    }
    assert (entries["SGOV"]["tier"], entries["SGOV"]["income"]) == (2, True)
    assert (entries["AAPL"]["tier"], entries["AAPL"]["kind"]) == (3, "stock")
    assert (entries["ZZF0001"]["tier"], entries["ZZF0001"]["kind"]) == (3, "stock")

    # A rerun skips what is already there with the same size, and never overwrites a symbol the
    # provider has filled since.
    entries["VTI"].update(source="seed+tiingo", status="ok", adjusted_through="2026-03-13")
    store_env.put("meta/manifest.json", json.dumps({"symbols": entries}).encode())
    store_env.put("prices/VTI.parquet", b"the provider's record")
    store_env.delete("prices/AAPL.parquet")
    assert _run(lake) == 0
    assert "seeded 9 symbols (8 already" in capsys.readouterr().out
    assert store_env.get("prices/VTI.parquet") == b"the provider's record"
    assert store_env.exists("prices/AAPL.parquet")
    after = json.loads(store_env.get("meta/manifest.json"))["symbols"]
    assert after["VTI"]["source"] == "seed+tiingo" and after["AAPL"]["status"] == "pending"


def test_dry_run_reports_and_writes_nothing(lake, store_env, capsys):
    assert _run(lake, "--dry-run") == 0
    out = capsys.readouterr().out
    for symbol, latest in EXPECTED_LATEST.items():
        assert f"{symbol}: latest adjustment {latest}" in out.splitlines()
    assert (
        "0 with adj_close != close after 2026-02-27; latest adjustment in the lake: 2026-02-06"
        in out
    )
    assert "dry run: nothing written" in out
    assert store_env.list() == []


def test_drift_after_adjusted_through_uploads_nothing(lake, store_env, capsys, tmp_path):
    drifted = tmp_path / "drifted"
    shutil.copytree(lake, drifted)
    frame = pd.read_parquet(drifted / "ZZF0007.parquet")
    row = len(frame) - 1
    frame.loc[row, "adj_close"] = frame.loc[row, "close"] * 1.01
    frame.to_parquet(drifted / "ZZF0007.parquet", index=False)
    day = str(frame.loc[row, "date"])[:10]
    assert day > THROUGH
    for extra in ((), ("--dry-run",)):
        assert _run(drifted, *extra) == 1
        err = capsys.readouterr().err
        assert f"ZZF0007: adj_close != close on {day}" in err and "seed refused" in err
        assert store_env.list() == []
    # The same row is fine when the adjustments are declared to reach that far.
    assert _run(drifted, "--dry-run", through=day) == 0


def test_missing_or_small_lake_is_refused(store_env, capsys, tmp_path):
    missing = tmp_path / "no_such_lake"
    assert _run(missing) == 1
    assert f"the lake path {missing} does not exist" in capsys.readouterr().err
    assert not missing.exists()
    assert _run(FIXTURE_LAKE) == 1
    assert f"the lake path {FIXTURE_LAKE} holds 3 parquet files, fewer than 1,000" in (
        capsys.readouterr().err
    )
    assert store_env.list() == []


def test_the_floor_is_exactly_1000_parquet_files(store_env, capsys, tmp_path):
    assert seed.MIN_FILES == 1_000
    full = _build_lake(tmp_path / "full", 1_000)
    assert len(list(full.glob("*.parquet"))) == 1_000 and len(list(full.iterdir())) == 1_002
    assert _run(full, "--dry-run") == 0
    assert "1000 symbols checked, 1000 to seed" in capsys.readouterr().out
    (full / "ZZF0500.parquet").unlink()
    for extra in ((), ("--dry-run",)):
        assert _run(full, *extra) == 1
        assert f"the lake path {full} holds 999 parquet files" in capsys.readouterr().err
    assert store_env.list() == []


def test_unusable_files_are_reported_and_left_out(lake, store_env, capsys, tmp_path):
    odd = tmp_path / "odd"
    shutil.copytree(lake, odd)
    late = pd.read_parquet(odd / "ZZF0001.parquet")
    late = late[late["date"] > pd.Timestamp(THROUGH)]
    late = late.assign(adj_close=late["close"])
    late.to_parquet(odd / "ZZF0001.parquet", index=False)
    broken = pd.read_parquet(odd / "ZZF0002.parquet")
    broken.loc[0, "adj_close"] = np.nan
    broken.to_parquet(odd / "ZZF0002.parquet", index=False)
    zero = pd.read_parquet(odd / "ZZF0003.parquet")
    zero.loc[len(zero) - 1, ["close", "adj_close"]] = 0.0
    zero.to_parquet(odd / "ZZF0003.parquet", index=False)
    assert _run(odd) == 0
    out = capsys.readouterr().out
    assert "ZZF0001: latest adjustment none  NOT SEEDED: no row on or before 2026-02-27" in out
    assert "NOT SEEDED: adj_close is missing or not positive" in out
    assert "NOT SEEDED: close is missing or not positive" in out
    assert "7 to seed, 3 not seedable" in out and len(store_env.list("prices/")) == 7


def test_store_configuration_error_is_a_refusal(lake, monkeypatch, capsys):
    monkeypatch.setenv("PS_STORE", "local")
    monkeypatch.delenv("PS_LOCAL_STORE_DIR", raising=False)
    assert _run(lake) == 1
    assert "PS_LOCAL_STORE_DIR" in capsys.readouterr().err


def test_default_lake_is_the_wsl_working_copy_not_the_mirror():
    assert (
        seed.DEFAULT_LAKE.startswith("~/tft-quantile-forecaster/")
        and "/mnt/" not in seed.DEFAULT_LAKE
    )
    assert (
        seed.check(FIXTURE_LAKE / "VTI.parquet", date(2026, 2, 27)).latest_adjustment
        == "2025-12-19"
    )
