"""`scripts/build_presets.py`: every preset tensor of a day from a store it never writes to."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfoliosight.api.hashing import universe_hash
from portfoliosight.api.presets import model_key, preset_definitions, preset_funds, tensor_key
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.engine import ENGINE_VERSION
from portfoliosight.engine.tensor import validate_tensor
from tests.engine.helpers import load_script

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_presets.py"
SMALL_GRID = {"PS_GRID_NX": "12", "PS_GRID_NY": "8", "PS_GRID_LEVELS": "3"}


def _digest(root: Path) -> str:
    """Every path under ``root`` with its kind and modification time, and every file's bytes."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(str(path.stat().st_mtime_ns).encode())
        digest.update(path.read_bytes() if path.is_file() else b"<dir>")
    return digest.hexdigest()


def _tsp_hash() -> str:
    tsp = next(preset for preset in preset_definitions() if preset.id == "tsp")
    return universe_hash(preset_funds(tsp))


def test_builds_every_asked_tensor_and_never_writes_into_the_store(store, d_g, tmp_path):
    before = _digest(store.root)
    out = tmp_path / "out"
    env = {**os.environ, **SMALL_GRID}
    env.pop("PS_ENGINES", None)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--store-dir", str(store.root), "--asof", d_g.isoformat()]
        + ["--out", str(out), "--presets", "tsp", "--lookbacks", "1y,5y"],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert _digest(store.root) == before
    lines = [json.loads(line) for line in proc.stdout.splitlines()]
    header, rows, total = lines[0], lines[1:-1], lines[-1]
    generation = f"{d_g.isoformat()}-{ENGINE_VERSION}"
    assert header["generation"] == generation and header["engines"] == ["replay", "garch"]
    assert header["store"].endswith("(read-only)") and len(header["load"]) == 3
    assert [(row["preset"], row["lookback"]) for row in rows] == [("tsp", "1y"), ("tsp", "5y")]
    first, second = rows
    assert first["reused"] is False and first["fit_seconds"] > 0
    assert second["reused"] is True and second["fit_seconds"] == 0
    assert second["shape16"] == first["shape16"] and first["garch"] == "ready"
    assert first["funds"]["TSP-G"] == "near_constant" and "TSP-G" in first["fallback"]
    assert set(first["funds"]) == {"TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I"}
    assert first["pool_rows"] > 126 and isinstance(first["outliers"], list)
    assert all(row["build_seconds"] > 0 for row in rows)
    assert total == {**total, "tensors": 2, "fits": 1}
    files = sorted(path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file())
    expected = [tensor_key(generation, _tsp_hash(), lookback) for lookback in ("1y", "5y")]
    expected += [model_key(generation, first["shape16"], n) for n in ("garch.json", "pool.npy")]
    assert files == sorted(expected)
    for key in expected[:2]:
        tensor = json.loads((out / key).read_text())
        validate_tensor(tensor)
        assert tensor["shape"]["sample_sha256"][:16] == first["shape16"]
        assert tensor["build_seconds"] in {row["build_seconds"] for row in rows}


@pytest.fixture(scope="module")
def script():
    return load_script("build_presets")


def _seeded_with_a_fall(store, fund: str, day: str) -> None:
    """A seeded record whose provider tail starts ``day`` with an action the seed missed."""
    record = store_mod.get_record(store, fund)
    head = record["date"] < pd.Timestamp(day)
    record.loc[head, ["div_cash", "split_factor"]] = np.nan
    record.loc[~head, "tr_index"] = record.loc[~head, "tr_index"] * 0.7
    store_mod.put_record(store, fund, record)
    catalog = manifest_mod.load_manifest(store)
    catalog.symbols[fund].fetched_at = "2026-10-14T09:00:00+00:00"
    manifest_mod.write_catalog(store, catalog, datetime(2026, 10, 14, tzinfo=UTC))


def test_a_splice_the_guard_refuses_is_printed_with_fund_and_date(
    script, store, d_g, tmp_path, monkeypatch, capsys
):
    for name, value in SMALL_GRID.items():
        monkeypatch.setenv(name, value)
    _seeded_with_a_fall(store, "TSP-C", "2024-03-01")
    before = _digest(store.root)
    out = tmp_path / "out"
    argv = ["--store-dir", str(store.root), "--asof", d_g.isoformat(), "--out", str(out)]
    assert script.main([*argv, "--presets", "tsp", "--lookbacks", "5y"]) == 2
    err = capsys.readouterr().err
    assert "TSP-C" in err and "2024-03-01" in err and "tsp 5y" in err
    assert _digest(store.root) == before
    assert [path for path in out.rglob("*") if path.is_file()] == []


def test_replay_only_builds_fit_nothing(script, store, d_g, tmp_path, monkeypatch, capsys):
    for name, value in SMALL_GRID.items():
        monkeypatch.setenv(name, value)
    out = tmp_path / "out"
    argv = ["--store-dir", str(store.root), "--asof", d_g.isoformat(), "--out", str(out)]
    assert script.main([*argv, "--presets", "tsp", "--lookbacks", "ew", "--engines", "replay"]) == 0
    row = json.loads(capsys.readouterr().out.splitlines()[1])
    assert row["garch"] == "not computed for this menu" and row["reused"] is None
    assert row["fit_seconds"] is None and row["funds"] == {} and row["shape16"] is None
    assert not (out / "models").exists()


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"--presets": "tsp,nosuch"}, "unknown preset 'nosuch'"),
        ({"--lookbacks": "1y,7y"}, "unknown lookback '7y'"),
        ({"--engines": "garch"}, "must name replay"),
        ({"--store-dir": "missing"}, "is not a directory"),
        ({"--out": "store/runs"}, "inside the store"),
        ({"--out": "occupied"}, "new or empty"),
    ],
)
def test_a_run_that_cannot_be_done_writes_nothing(
    script, store, d_g, tmp_path, capsys, change, says
):
    (tmp_path / "occupied").mkdir()
    (tmp_path / "occupied" / "left.txt").write_text("from an earlier run")
    args = {
        "--store-dir": str(store.root),
        "--asof": d_g.isoformat(),
        "--out": str(tmp_path / "out"),
    }
    for flag, value in change.items():
        args[flag] = str(tmp_path / value) if flag in ("--store-dir", "--out") else value
    before = _digest(store.root)
    with pytest.raises(SystemExit) as exited:
        script.main([part for pair in args.items() for part in pair])
    assert exited.value.code == 2 and says in capsys.readouterr().err
    assert _digest(store.root) == before and not (tmp_path / "out").exists()
