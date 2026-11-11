# ruff: noqa: E501
"""A-SE-22 contract: run the real paired measures experiment and recompute metrics.

Extends the plan's backtest CLI with `measures --measures enb,dr2`; --out is an
output directory containing measures.json and report.md. Rows expose input record
keys/hashes and evaluated tensor/weights, not just final scores. This observability
contract is necessary for independently checking §10.7, not a new product API.
The report has a machine-readable JSON fenced block with the actual comparisons.
Aggregation norm is disclosed and checked, never selected by this gate.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _runtime():
    """Use project dependencies while importing product exclusively from this run checkout."""
    try:
        importlib.import_module("numpy")
        importlib.import_module("pandas")
    except ImportError:
        main = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--git-common-dir"], cwd=ROOT, text=True
            ).strip()
        )
        if not main.is_absolute():
            main = ROOT / main
        python = main.resolve().parent / ".venv/bin/python"
        assert python.exists(), (
            "Project runtime missing; this gate cannot pass without its dependencies"
        )
        assert not os.environ.get("A_SE_REEXEC"), (
            "Project runtime still lacks required dependencies"
        )
        result = subprocess.run(
            [
                str(python),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                str(Path(__file__).resolve()),
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONPATH": str(ROOT),
                "A_SE_REEXEC": "1",
            },
            capture_output=True,
            text=True,
            timeout=21600,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return False
    package = importlib.import_module("portfoliosight")
    assert Path(package.__file__).resolve().is_relative_to(ROOT), (
        "Imported another editable checkout"
    )
    return True


def _module(name):
    try:
        module = importlib.import_module(name)
    except ImportError as exc:
        raise AssertionError(f"Required implementation {name} is unavailable: {exc}") from exc
    assert Path(module.__file__).resolve().is_relative_to(ROOT), (
        f"{name} came from another checkout"
    )
    return module


def test_a_se_22_measures_evidence(tmp_path):
    if not _runtime():
        return
    import hashlib
    import io
    import math
    import re

    import exchange_calendars as xcals
    import numpy as np
    import pandas as pd

    _phase_two_budget(tmp_path)
    script = ROOT / "scripts/backtest_ranges.py"
    assert script.exists(), "Phase 2 comparison script is not implemented"
    backup = Path("/mnt/d/portfoliosight-data")
    assert backup.is_dir(), "Required historical backup is unavailable; no passing skip"
    # No provider or network access, including attempts hidden behind another client.
    runner = _offline_program()
    before = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (
            ROOT / "portfoliosight/engine/builder.py",
            ROOT / "portfoliosight/engine/ranges.py",
        )
    }
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                runner,
                str(script),
                "measures",
                "--store-dir",
                str(backup),
                "--menus",
                "guide2017,tsp",
                "--lookbacks",
                "5y,1y",
                "--engines",
                "replay,garch",
                "--measures",
                "enb,dr2",
                "--out",
                str(out),
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=7200,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        evidence = out / "measures.json"
        report = out / "report.md"
        assert evidence.is_file() and report.is_file(), (
            "The actual experiment must export its measured inputs and report"
        )
        data = json.loads(evidence.read_text())
        rows = data["rows"]
        assert rows and data["default_measure"] == "enb" and data["range_default"] == "replay"
        assert data["aggregation"], "Aggregation choices cannot be tuned invisibly"
        grouped = {}
        reference_cache = {}
        paired = {}
        actual_values = []
        for row in rows:
            assert row["menu"] in ("guide2017", "tsp") and row["lookback"] in ("1y", "5y")
            assert row["measure"] in ("enb", "dr2") and row["point"] in ("optimized", "peak")
            assert row["paths"] == 2000 and row["horizon_days"] == 252
            origin = pd.Timestamp(row["origin"])
            assert pd.Timestamp(row["fit_end"]) <= origin
            records = []
            for source in row["source_records"]:
                path = (backup / source["key"]).resolve()
                assert path.is_relative_to(backup.resolve())
                raw = path.read_bytes()
                assert hashlib.sha256(raw).hexdigest() == source["sha256"]
                frame = pd.read_parquet(io.BytesIO(raw))
                records.append(
                    pd.Series(
                        frame["tr_index"].to_numpy(),
                        index=pd.to_datetime(frame["date"]),
                        name=source["id"],
                    )
                )
            prices = pd.concat(records, axis=1).sort_index()
            returns = prices.pct_change(fill_method=None).loc[prices.index > origin].iloc[:252]
            assert len(returns) == 252 and not returns.isna().any().any(), (
                "Missing future observations must be counted explicitly, never filled"
            )
            assert list(prices.columns) == row["fund_ids"]
            w = np.array(row["weights"])
            fw = np.array(row["frontier_weights"])
            cov = np.array(row["cov"])
            assert len(w) == len(records) and abs(w.sum() - 1) < 1e-6
            daily = returns.to_numpy() @ w
            frontier_daily = returns.to_numpy() @ fw
            predicted = float(np.sqrt(w @ cov @ w))
            realized = float(np.std(daily, ddof=1) * np.sqrt(252))
            total = float(np.prod(1 + daily) - 1)
            given = float(np.prod(1 + frontier_daily) - 1 - total)
            assert abs(row["predicted_sigma"] - predicted) < 1e-9
            metrics = row["metrics"]
            assert abs(metrics["realized_sigma"] - realized) < 1e-9
            assert abs(metrics["absolute_risk_error"] - abs(realized - predicted)) < 1e-9
            assert metrics["risk_exceeded_25pct"] == (realized > 1.25 * predicted)
            assert abs(metrics["realized_return"] - total) < 1e-9
            assert abs(metrics["return_given_up"] - given) < 1e-9
            assert row["alpha"] in (0.05, 0.10)
            tail = np.argsort(daily)[: math.ceil(row["alpha"] * len(daily))]
            losses = -(returns.to_numpy()[tail] * w).mean(axis=0)
            losses = np.maximum(losses, 0)
            share = losses[losses > 0] / losses.sum() if losses.sum() > 0 else np.array([])
            expected = float(np.exp(-sum(share * np.log(share)))) if len(share) else None
            if expected is None:
                assert metrics["realized_enlc"] is None
            else:
                assert abs(metrics["realized_enlc"] - expected) < 1e-9
            assert len(row["stress"]) == 3
            for stress in row["stress"]:
                start = pd.Timestamp(stress["start"])
                end = pd.Timestamp(stress["end"])
                window = prices.loc[start:end].dropna()
                assert len(window) > 1
                fund_returns = window.iloc[-1].to_numpy() / window.iloc[0].to_numpy() - 1
                assert abs(stress["loss"] - float(w @ fund_returns)) < 1e-9
            for stability in row["stability"]:
                current_ids = row["fund_ids"]
                other_ids = stability["other_fund_ids"]
                assert len(current_ids) == len(set(current_ids)) and len(other_ids) == len(
                    set(other_ids)
                )
                assert len(other_ids) == len(stability["other_weights"])
                union = sorted(set(current_ids) | set(other_ids))
                current = dict(zip(current_ids, w, strict=True))
                other = dict(zip(other_ids, stability["other_weights"], strict=True))
                delta = np.array([current.get(fid, 0) - other.get(fid, 0) for fid in union])
                assert stability["relation"] in ("consecutive_origin", "same_origin_lookback")
                norm = stability["norm"]
                assert norm in ("l1", "l2", "linf"), (
                    "Undisclosed/unsupported aggregation requires review"
                )
                distance = float(
                    np.linalg.norm(delta, ord={"l1": 1, "l2": 2, "linf": np.inf}[norm])
                )
                assert abs(stability["distance"] - distance) < 1e-10
            tensor = _reference_tensor(row, backup, reference_cache)
            assert row["tensor"]["ladder"]["w"] == tensor["ladder"]["w"]
            assert tensor["ladder"]["measure"] == row["measure"]
            column = row["column"]
            levels = tensor["ladder"]["w"][column]
            level = (
                len(levels) - 1
                if row["point"] == "peak"
                else round(tensor["ladder"]["t_suggested"][column] * (len(levels) - 1))
            )
            assert np.allclose(w, levels[level], atol=1e-12, rtol=0)
            assert np.allclose(fw, tensor["frontier"]["w"][column], atol=1e-12, rtol=0)
            key = (row["menu"], row["lookback"], row["origin"], column, row["point"])
            paired.setdefault(key, {})[row["measure"]] = w
            grouped.setdefault(
                (row["menu"], row["lookback"], row["measure"], column, row["point"]), []
            ).append(total)
            actual_values.append(metrics)
        all_keys = [
            (r["menu"], r["lookback"], r["origin"], r["column"], r["point"], r["measure"])
            for r in rows
        ]
        assert len(all_keys) == len(set(all_keys)), "Duplicate comparison rows"
        # Independently derive the actual last XNYS session of every prescribed quarter.
        expected_quarters = {
            f"{year}-{month:02d}"
            for year in range(2015, 2026)
            for month in (3, 6, 9, 12)
            if "2015-12" <= f"{year}-{month:02d}" <= "2025-09"
        }
        calendar = xcals.get_calendar("XNYS")
        expected_origins = set()
        for quarter in expected_quarters:
            end = pd.Period(quarter, freq="M").end_time.normalize()
            sessions = calendar.sessions_in_range(end - pd.Timedelta(days=10), end)
            expected_origins.add(sessions[-1].date().isoformat())
        assert len(expected_quarters) == len(expected_origins) == 40
        for menu in ("guide2017", "tsp"):
            for lookback in ("1y", "5y"):
                origins = {
                    r["origin"] for r in rows if r["menu"] == menu and r["lookback"] == lookback
                }
                assert origins == expected_origins, "Comparison used incorrect quarter-end sessions"
                expected = {
                    (menu, lookback, origin, column, point, measure)
                    for origin in expected_origins
                    for column in range(48)
                    for point in ("optimized", "peak")
                    for measure in ("enb", "dr2")
                }
                actual = {key for key in all_keys if key[:2] == (menu, lookback)}
                assert actual == expected, "Comparison omitted columns/points/objectives"
        lookup = {key: r for key, r in zip(all_keys, rows, strict=True)}
        for row in rows:
            scope_origins = sorted(
                {
                    r["origin"]
                    for r in rows
                    if (r["menu"], r["lookback"]) == (row["menu"], row["lookback"])
                }
            )
            index = scope_origins.index(row["origin"])
            partners = {
                (row["origin"], "5y" if row["lookback"] == "1y" else "1y", "same_origin_lookback")
            }
            if index > 0:
                partners.add((scope_origins[index - 1], row["lookback"], "consecutive_origin"))
            actual_partners = {
                (x["other_origin"], x["other_lookback"], x["relation"]) for x in row["stability"]
            }
            assert actual_partners == partners, "Missing or unrelated stability partners"
            for item in row["stability"]:
                key = (
                    row["menu"],
                    item["other_lookback"],
                    item["other_origin"],
                    row["column"],
                    row["point"],
                    row["measure"],
                )
                partner = lookup[key]
                assert item["other_weights"] == partner["weights"]
                assert item["other_fund_ids"] == partner["fund_ids"]
        assert all(set(pair) == {"enb", "dr2"} for pair in paired.values())
        assert any(
            not np.allclose(pair["enb"], pair["dr2"], atol=1e-7) for pair in paired.values()
        ), "One ladder relabelled twice is not a comparison"
        for row in rows:
            key = (row["menu"], row["lookback"], row["measure"], row["column"], row["point"])
            assert abs(row["metrics"]["worst_year_loss"] - min(grouped[key])) < 1e-9
        # Auxiliary sections are bound to numerical rows, not satisfied by headings.
        for check in data["single_fund_checks"]:
            assert abs(check["dr2"] - 1) <= 1e-9
            assert check["enlc"] is None or check["enlc"] == 1
            assert "enb" in check
        assert {x["menu"] for x in data["single_fund_checks"]} == {"guide2017", "tsp"}
        for check in data["bound_checks"]:
            if check["min_held_correlation"] >= 0:
                assert check["dr2"] <= check["held_1e6"] + 1e-9
            assert check["enlc"] is None or check["enlc"] <= check["held_1e6"] + 1e-9
            assert check["held_005"] <= check["held_1e6"]
        assert data["off_line_counts"] and data["word_distribution"]
        measurement = data["dr2_100_fund_measurement"]
        assert (
            measurement["funds"] == 100
            and measurement["seconds"] > 0
            and measurement["paths"] == 2000
        )
        text = report.read_text()
        blocks = re.findall(r"```json\s*(.*?)```", text, re.S)
        rendered = [json.loads(block) for block in blocks]
        assert any(
            block.get("rows") == rows and block.get("aggregation") == data["aggregation"]
            for block in rendered
        ), "Report tables are not bound to the verified measured rows"
        assert data["tie_default"] == "enb" and data["owner_review_required"] is True
        assert all(
            hashlib.sha256(path.read_bytes()).hexdigest() == digest
            for path, digest in before.items()
        ), "Generating a report changed product defaults"

    # Hand-computable metric control through the same script. Alter only future
    # prices: the selected ladders must stay fixed while their realized metrics move.
    sm = _module("portfoliosight.data.store")
    synthetic_root = tmp_path / "metric-fixture"
    synthetic = _frozen_store(synthetic_root)
    baseline = {
        fid: sm.get_record(synthetic, fid) for fid in ("TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I")
    }
    snapshots = []
    for case, daily in enumerate((np.full(252, 0.001), np.tile([-0.01, 0.011], 126))):
        for fid, source_frame in baseline.items():
            record = source_frame.copy(deep=True)
            dates = pd.to_datetime(record["date"])
            past = record.index[dates <= pd.Timestamp("2020-12-31")]
            future = record.index[dates > pd.Timestamp("2020-12-31")][:252]
            assert len(past) and len(future) == 252
            origin_price = float(record.loc[past[-1], "tr_index"])
            record.loc[future, "tr_index"] = origin_price * np.cumprod(1 + daily)
            sm.put_record(synthetic, fid, record)
        case_out = tmp_path / f"metric-case-{case}"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                runner,
                str(script),
                "measures",
                "--store-dir",
                str(synthetic_root),
                "--menus",
                "tsp",
                "--lookbacks",
                "1y",
                "--engines",
                "replay,garch",
                "--measures",
                "enb,dr2",
                "--origins",
                "2020-12-31",
                "--out",
                str(case_out),
            ],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=1800,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        samples = json.loads((case_out / "measures.json").read_text())["rows"]
        assert samples and {row["measure"] for row in samples} == {"enb", "dr2"}
        snapshots.append(samples)
        for row in samples:
            own_daily = daily * sum(row["weights"])
            assert (
                abs(row["metrics"]["realized_sigma"] - np.std(own_daily, ddof=1) * np.sqrt(252))
                < 1e-9
            )
            assert abs(row["metrics"]["realized_return"] - (np.prod(1 + own_daily) - 1)) < 1e-9

    def key(row):
        return row["measure"], row["column"], row["point"]

    earlier = {key(row): row for row in snapshots[0]}
    later = {key(row): row for row in snapshots[1]}
    assert set(earlier) == set(later)
    for point in earlier:
        assert earlier[point]["weights"] == later[point]["weights"], (
            "Future prices leaked into optimized weights"
        )
        assert (
            earlier[point]["metrics"]["realized_return"]
            != later[point]["metrics"]["realized_return"]
        ), "Fixed report numbers ignored changed future prices"


def _reference_tensor(row, backup, cache):
    """Rebuild the actual preset at the recorded origin from the independent backup."""
    from unittest.mock import patch

    import numpy as np
    import pandas as pd

    builder = _module("portfoliosight.engine.builder")
    jobs = _module("portfoliosight.jobs.build")
    sm = _module("portfoliosight.data.store")
    manifest_module = _module("portfoliosight.data.manifest")
    returns_module = _module("portfoliosight.data.returns")
    measure = row.get("measure", "enb")
    key = (row["menu"], row["lookback"], row["origin"], measure)
    if key not in cache:
        store = sm.LocalStore(backup)
        catalog = manifest_module.load_manifest(store).symbols
        definitions = json.loads((ROOT / "data/presets.json").read_text())["presets"]
        preset = next(x for x in definitions if x["id"] == row["menu"])
        asof = pd.Timestamp(row["origin"]).to_pydatetime()
        records = {fid: jobs._upto(sm.get_record(store, fid), asof) for fid in preset["funds"]}
        rf = {}
        for fid in ("SGOV", "TSP-G"):
            if fid in catalog and catalog[fid].status == "ok" and store.exists(sm.record_key(fid)):
                record = jobs._upto(sm.get_record(store, fid), asof)
                rf[fid] = jobs._tr_series(record).pct_change(fill_method=None).dropna()
        inputs = builder.TensorInputs(
            funds=[
                jobs._fund_input(fid, catalog.get(fid), records[fid], asof)
                for fid in preset["funds"]
            ],
            returns=returns_module.build_returns(records),
            lookback=row["lookback"],
            asof=row["origin"],
            universe_name=preset["name"],
            preset_id=row["menu"],
            requested_bounds=[{"id": fid, "min": None, "max": None} for fid in preset["funds"]],
            tr_index={fid: jobs._tr_series(record) for fid, record in records.items()},
            rf_series=rf,
            nx=48,
            ny=32,
            levels=12,
            engines=("replay", "garch"),
        )
        with patch.object(builder, "LADDER_MEASURE", measure):
            cache[key] = builder.build_tensor_full(inputs, workers=1).tensor
    tensor = cache[key]
    assert row["fund_ids"] == [f["id"] for f in tensor["universe"]["funds"]]
    assert np.allclose(row["cov"], tensor["cov"], rtol=0, atol=2e-12)
    if "mu" in row:
        assert np.allclose(row["mu"], tensor["mu_s"], rtol=0, atol=2e-12)
    column = row["column"]
    assert 0 <= column < len(tensor["frontier"]["w"]) == 48
    levels = tensor["ladder"]["w"][column]
    if row["point"] == "frontier":
        expected = tensor["frontier"]["w"][column]
    elif row["point"] == "peak":
        expected = levels[-1]
    else:
        assert row["point"] == "optimized"
        index = int(round(tensor["ladder"]["t_suggested"][column] * (len(levels) - 1)))
        expected = levels[index]
    assert np.allclose(row["weights"], expected, rtol=0, atol=2e-9), (
        "Reported mix is not the actual selected optimization point"
    )
    return tensor


def _frozen_store(directory):
    """Frozen deterministic preset histories; only canonical store writers are product code."""
    from datetime import UTC, datetime

    import numpy as np
    import pandas as pd

    sm = _module("portfoliosight.data.store")
    mm = _module("portfoliosight.data.manifest")
    guide = [
        "VTI",
        "VTV",
        "VOE",
        "VB",
        "VBR",
        "VEA",
        "SCHF",
        "VWO",
        "VNQ",
        "VBIAX",
        "SCHO",
        "BND",
        "AGG",
        "TIP",
        "VTIP",
        "LQD",
        "VWOB",
        "PCY",
        "EFA",
        "LTPZ",
        "EDV",
        "VGSTX",
        "DBJP",
    ]
    tsp = ["TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I"]
    ids = guide + tsp + ["SGOV"]
    days = pd.bdate_range(end="2026-10-13", periods=6000)
    rng = np.random.default_rng(170019)
    market = rng.normal(size=(len(days), 1))
    noise = 0.55 * market + 0.84 * rng.normal(size=(len(days), len(ids)))
    values = 0.0002 + noise * np.linspace(0.003, 0.018, len(ids))
    values[:, ids.index("TSP-G")] = 0.035 / 252
    values[:, ids.index("SGOV")] = 0.03 / 252
    assert np.std(values[:, 0]) > 0.001 and np.all(values > -1)
    store = sm.LocalStore(directory)
    store.check()
    manifest = mm.Manifest()
    for i, fid in enumerate(ids):
        index = pd.DatetimeIndex([days[0] - pd.offsets.BDay(1)]).append(days)
        growth = np.concatenate(([1.0], np.cumprod(1 + values[:, i])))
        record = pd.DataFrame(
            {
                "date": index,
                "close": 100 * growth / growth[-1],
                "tr_index": growth,
                "div_cash": 0.0,
                "split_factor": 1.0,
            }
        )
        sm.put_record(store, fid, record)
        manifest.symbols[fid] = mm.ManifestEntry(
            name=fid,
            kind="tsp" if fid in tsp else "etf",
            tier=1,
            source="tsp" if fid in tsp else "tiingo",
            first_date=index[0].date(),
            last_date=index[-1].date(),
            adjusted_through=index[-1].date(),
            status="ok",
            fetched_at="2026-10-13T09:05:11+00:00",
        )
    mm.write_catalog(store, manifest, datetime(2026, 10, 13, 9, 5, 11, tzinfo=UTC))
    assert len(manifest.symbols) == 29
    return store


def _offline_program():
    # Python audit hooks run before filesystem mutations, including writes attempted
    # through pathlib/open/os helpers. Children cannot escape through subprocess.
    return r"""import os,pathlib,runpy,socket,sys
args=sys.argv[1:]
mirror=pathlib.Path(args[args.index('--store-dir')+1]).resolve()
def inside(value):
    if not isinstance(value,(str,bytes,os.PathLike)):return False
    return pathlib.Path(os.fsdecode(value)).resolve().is_relative_to(mirror)
def audit(event,args):
    if event=='open':
        mode=args[1];flags=args[2]
        writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)))
        if writing and inside(args[0]):raise AssertionError('Validation cannot mutate the backup mirror')
    if event in ('os.remove','os.rmdir','os.mkdir','os.chmod','os.chown','os.truncate','os.utime') and inside(args[0]):raise AssertionError('Validation cannot mutate the backup mirror')
    if event in ('os.rename','os.link','os.symlink') and any(inside(v) for v in args[:2]):raise AssertionError('Validation cannot mutate the backup mirror')
    if event in ('subprocess.Popen','os.system','os.exec','os.posix_spawn'):raise AssertionError('Validation subprocess escape forbidden')
sys.addaudithook(audit)
def blocked(*a,**k):raise AssertionError('Provider/network access forbidden')
socket.socket.connect=blocked;socket.create_connection=blocked
sys.argv=args
runpy.run_path(args[0],run_name='__main__')
"""


REMOTE_SOURCE = r'''

import hashlib,json,os,pathlib,subprocess,sys,tempfile,time,socket
root=pathlib.Path(sys.argv[1]).resolve();sys.path.insert(0,str(root));source=pathlib.Path(sys.argv[2]);expected=json.loads(sys.argv[3]);revision=sys.argv[4];expected_inputs=json.loads(sys.argv[5])
measured_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
for name,digest in expected.items(): assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest, 'Target source differs: '+name
quota,period=pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().split();memory=int(pathlib.Path('/sys/fs/cgroup/memory.max').read_text())
assert quota!='max' and int(quota)/int(period)==4 and memory==1536*1024*1024,'Benchmark requires actual four-vCPU/1536MB container'
def blocked(*a,**k):raise AssertionError('No provider/network calls in target benchmark')
socket.create_connection=blocked;socket.socket.connect=blocked
os.environ.update(PS_ENGINES='replay,garch',PS_ENGINES_CUSTOM='replay,garch',PS_GATE_SECRET='frozen-target-benchmark-local-gate',PS_BUILD_WORKERS='4',PS_GRID_NX='48',PS_GRID_NY='32',PS_GRID_LEVELS='12')
import numpy as np
import pandas as pd
from portfoliosight.data import store as sm
from portfoliosight.engine import ENGINE_VERSION
from portfoliosight.engine import builder
from portfoliosight.jobs import build as jobs,nightly
from portfoliosight.api import queue,presets
from portfoliosight.api.app import create_app
from fastapi.testclient import TestClient
for module in (sm,builder,jobs,nightly):assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
assert hasattr(builder,'build_tensor_full'),'Engine-aware builder absent'
original=sm.LocalStore(source);pointer=sm.get_json(original,'meta/current.json');input_generation=pointer['generation'];meta=sm.get_json(original,jobs.generation_key(input_generation));generation=meta['asof']+'-'+ENGINE_VERSION
assert source.is_dir();definitions=presets.preset_definitions();assert {p.id for p in definitions}=={'guide2017','tsp'}
ids={f for p in definitions for f in p.funds}|{'SGOV','SHV','TSP-G'}
input_keys=list(expected_inputs);assert set(input_keys)>={'meta/manifest.json','meta/current.json',jobs.generation_key(input_generation)}|{sm.record_key(fid) for fid in ids if fid not in {'SGOV','SHV'}}
inputs={k:hashlib.sha256(original.get(k)).hexdigest() for k in input_keys};assert inputs==expected_inputs,'Target records differ from attested local backup'
consumed=[];cold_models={};observation_ns=0;real_full=builder.build_tensor_full
# Observe models at the actual builder seam; never replace its calculation.
def observed(*a,**kw):
 global observation_ns
 result=real_full(*a,**kw)
 assert result.tensor['ladder']['measure'] in ('enb','dr2') and set(result.tensor['ladder']['loss_sources'])>={'replay','garch'}
 assert all(k in result.tensor['ladder'] for k in ('dr2','enb','on_line'))
 observer_start=time.perf_counter_ns()
 if not cold_models:cold_models.update(result.models)
 for e,m in result.models.items():
  if e=='garch':assert m.panel.shape[:2]==(2000,252);descriptor={'engine':e,'shape':list(m.panel.shape),'dtype':str(m.panel.dtype),'sha256':hashlib.sha256(np.ascontiguousarray(m.panel).tobytes()).hexdigest()}
  else:assert m.counts.shape[0]==2000 and np.all(m.counts.sum(axis=1)==252);descriptor={'engine':e,'shape':[2000,252,len(m.mu_s)],'counts_shape':list(m.counts.shape),'sha256':hashlib.sha256(np.ascontiguousarray(m.counts).tobytes()).hexdigest()}
  if e=='garch':
   artifact=result.artifacts[e];funds=list(artifact.funds)
   prices=pd.DataFrame({fid:sm.get_record(original,fid).set_index('date')['tr_index'] for fid in funds}).sort_index()
   returns=(prices/prices.shift(1)-1).loc[:meta['asof']];panel=returns.loc[returns.notna().any(axis=1)].tail(2520)
   assert artifact.rows==len(panel) and list(artifact.n_obs)==panel.notna().sum().tolist()
   digest=hashlib.sha256();digest.update('\x1f'.join(funds).encode());digest.update(b'\x1e');digest.update('\x1f'.join(stamp.date().isoformat() for stamp in panel.index).encode());digest.update(b'\x1e');digest.update(np.ascontiguousarray(panel.to_numpy(),dtype='<f8').tobytes())
   assert artifact.sample_sha256==digest.hexdigest()
   descriptor.update(shape_rows=len(panel),fund_ids=funds,n_obs=list(artifact.n_obs),statuses=list(artifact.status))
  consumed.append(descriptor)
 observation_ns+=time.perf_counter_ns()-observer_start
 return result
builder.build_tensor_full=observed
for module in (jobs,):
 if getattr(module,'build_tensor_full',None) is real_full:module.build_tensor_full=observed
def _years(model, weights):
    """Independent §4.5 oracle from the exact arrays the builder consumed, no range call."""
    w = np.asarray(weights, dtype=float)
    target = float(np.asarray(model.mu_s) @ w) / 252
    if getattr(model, "engine", "replay") == "replay":
        daily = np.asarray(model.sample) @ w
        growth = 1 + daily - daily.mean() + target
        assert np.all(growth > 0)
        assert model.counts.shape[0] == 2000
        np.testing.assert_array_equal(model.counts.sum(axis=1), np.full(2000, 252))
        return np.expm1(np.asarray(model.counts) @ np.log(growth))
    panel = np.asarray(model.panel, dtype=float)
    assert panel.shape[:2] == (2000, 252)
    flat = panel.reshape(-1, panel.shape[-1])
    mean, sd = flat.mean(axis=0), flat.std(axis=0, ddof=0)
    m = np.asarray(model.mu_s) / 252
    v = np.log1p(np.diag(model.cov) / 252 / (1 + m) ** 2)
    levelled = np.empty_like(flat)
    for n in range(flat.shape[1]):
        if sd[n] <= 64 * np.finfo(float).eps * max(1., abs(mean[n])):
            levelled[:, n] = m[n]
        else:
            levelled[:, n] = np.expm1(np.log1p(m[n]) - v[n] / 2 + (flat[:, n] - mean[n]) * np.sqrt(v[n]) / sd[n])
    y = levelled @ w
    spread = y.std(ddof=0)
    sigma = float(np.sqrt(w @ np.asarray(model.cov) @ w)) / np.sqrt(252)
    daily = np.full_like(y, target) if spread <= 1e-15 else target + (y - y.mean()) * sigma / spread
    daily = daily.reshape(2000, 252)
    ruined = (daily <= -1).any(axis=1)
    years = np.full(2000, -1.)
    years[~ruined] = np.expm1(np.log1p(daily[~ruined]).sum(axis=1))
    return years


with tempfile.TemporaryDirectory(prefix='frozen-engine-benchmark-') as temp:
 temp=pathlib.Path(temp)
 def fresh_store(path):
  target=sm.LocalStore(path)
  for key in input_keys:target.put(key,original.get(key))
  sm.put_json(target,jobs.generation_key(generation),{'generation':generation,'asof':meta['asof'],'engine_version':ENGINE_VERSION})
  sm.put_json(target,'meta/current.json',{'generation':generation})
  return target
 store=fresh_store(temp/'cold-store');os.environ['PS_CACHE_DIR']=str(temp/'cold-cache')
 guide=next(p for p in definitions if p.id=='guide2017');assert len(guide.funds)==23
 policy=presets.preset_funds(guide);uhash=presets.universe_hash(policy)
 assert not store.list('models/'),'Cold-fit measurement cannot start with artifact hits'
 fit_calls=[];real_fit=builder.fit_shape
 def fit(*a,**kw):fit_calls.append(True);return real_fit(*a,**kw)
 builder.fit_shape=fit
 observed_before=observation_ns;started=time.perf_counter_ns();cold=jobs.build_from_store(store,generation=generation,funds=policy,lookback='5y',cache_dir=temp/'cold-cache',universe_name=guide.name,preset_id=guide.id,nx=48,ny=32,levels=12);cold_ns=time.perf_counter_ns()-started-(observation_ns-observed_before);cold_fit_calls=len(fit_calls)
 assert fit_calls and set(cold['frontier']['ranges'])>={'replay','garch'}
 # Use the real two-preset/six-lookback nightly build loop with empty tensor keys.
 store=fresh_store(temp/'nightly-store');os.environ['PS_CACHE_DIR']=str(temp/'nightly-cache');assert not store.list('models/') and not store.list('tensors/');observed_before=observation_ns
 errors=[];started=time.perf_counter_ns();seconds,built,complete=nightly._build_presets(store,generation,queue.build_job,errors);nightly_ns=time.perf_counter_ns()-started-(observation_ns-observed_before);nightly_fit_calls=len(fit_calls)-cold_fit_calls;assert nightly_fit_calls>0
 assert complete and not errors and built=={'guide2017':6,'tsp':6},(built,errors)
 assert len(store.list('tensors/'+generation+'/'))==12
 tensor_evidence=[]
 for key in store.list('tensors/'+generation+'/'):
  item=sm.get_json(store,key);assert set(item['frontier']['ranges'])>={'replay','garch'} and len(item['frontier']['w'])==48
  tensor_evidence.append({'menu':item['universe']['preset_id'],'lookback':item['lookback']['id'],'fund_ids':[fund['id'] for fund in item['universe']['funds']],'shape_rows':item['shape']['rows'],'funds':item['shape']['funds']})
 assert consumed and {d['engine'] for d in consumed}=={'replay','garch'},'No actual full-path model consumption observed'
 tensor=sm.get_json(store,presets.tensor_key(generation,uhash,'5y'))
 request={'generation':generation,'hash':uhash,'lookback':'5y','weights':(np.arange(1,24)/np.arange(1,24).sum()).tolist()}
 header={'x-ps-gate':os.environ['PS_GATE_SECRET']};warm=[]
 with TestClient(create_app(store=store,start_worker=False),raise_server_exceptions=False) as client:
  assert not client.app.state.queue._running if hasattr(client.app.state.queue,'_running') else True
  for e in ('replay','garch'):
   initial=client.post('/v1/range',json={**request,'engine':e},headers=header);assert initial.status_code==200,initial.text
   for shift in (0,1,2):
    w=np.roll(np.array(request['weights']),shift);started=time.perf_counter_ns();answer=client.post('/v1/range',json={**request,'weights':w.tolist(),'engine':e},headers=header);elapsed=time.perf_counter_ns()-started
    assert answer.status_code==200 and answer.json()['engine']==e and answer.json()['bad']<answer.json()['typical']<answer.json()['good'];expected_quantiles=np.percentile(_years(cold_models[e],w),[2.5,50,97.5],method='linear');assert np.allclose([answer.json()[k] for k in ('bad','typical','good')],expected_quantiles,atol=3e-5,rtol=3e-4);warm.append({'expected':expected_quantiles.tolist(),'engine':e,'elapsed_ns':elapsed,'answer':answer.json(),'weights':w.tolist()})
 fallback=[{'id':f['id'],'status':f['status']} for f in cold['shape']['funds'] if f['status']!='garch']
 from portfoliosight.data.manifest import load_manifest
 hundred_ids=sorted(fid for fid,entry in load_manifest(original).symbols.items() if entry.status=='ok' and original.exists(sm.record_key(fid)))[:100]
 assert len(hundred_ids)==100
 builder.LADDER_MEASURE='dr2'
 hundred_store=fresh_store(temp/'hundred-store');observed_before=observation_ns;started=time.perf_counter_ns();hundred=jobs.build_from_store(hundred_store,generation=generation,funds=[{'id':fid,'min':None,'max':None} for fid in hundred_ids],lookback='1y',cache_dir=temp/'hundred-cache',universe_name='100-fund DR2 measurement',nx=48,ny=32,levels=12);hundred_ns=time.perf_counter_ns()-started-(observation_ns-observed_before)
 assert hundred['ladder']['measure']=='dr2' and len(hundred['universe']['funds'])==100
 assert all(hashlib.sha256(original.get(k)).hexdigest()==v for k,v in inputs.items()),'Benchmark modified original input store'
 print('FROZEN_BENCHMARK='+json.dumps({'revision':measured_revision,'source_tree_sha256':hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'cpu_quota':4,'memory_bytes':memory,'input_sha256':inputs,'cold_fit_calls':cold_fit_calls,'nightly_fit_calls':nightly_fit_calls,'tensors':tensor_evidence,'hundred_ns':hundred_ns,'hundred_funds':hundred_ids,'cold_ns':cold_ns,'nightly_ns':nightly_ns,'built':built,'warm':warm,'consumed':consumed,'fallbacks':fallback,'cache':'cold fit then nightly shared artifacts; warm HTTP after first engine request'},allow_nan=False))

'''


def _phase_two_budget(tmp_path):
    if not _runtime():
        return
    import hashlib
    import re
    import shlex
    import time

    required = (
        "PS_KS001_SSH_HOST",
        "PS_KS001_BENCH_CONTAINER",
        "PS_KS001_REPO_DIR",
        "PS_KS001_INPUT_STORE",
    )
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        pytest.fail("A-SE-22 requires explicit target benchmark context: " + ", ".join(missing))
    host, container, remote_root, source = [os.environ[k] for k in required]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    files = [
        p for parent in ("portfoliosight", "qse", "scripts") for p in (ROOT / parent).rglob("*.py")
    ]
    files += [
        ROOT / name
        for name in (
            "pyproject.toml",
            "uv.lock",
            "requirements.lock",
            "deploy/Dockerfile",
            "data/presets.json",
            "qse/qse.lock.json",
            "data/universes/tiers.json",
        )
        if (ROOT / name).exists()
    ]
    digests = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    source_tree = hashlib.sha256(
        json.dumps(digests, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    mirror = Path(os.environ.get("PS_ENGINE_VALIDATION_STORE", "/mnt/d/portfoliosight-data"))
    if not mirror.is_dir():
        pytest.fail(
            "Budget proof needs the attested local real-data backup, not synthetic timing inputs"
        )
    sm = _module("portfoliosight.data.store")
    local_store = sm.LocalStore(mirror)
    pointer = sm.get_json(local_store, "meta/current.json")
    presets = _module("portfoliosight.api.presets").preset_definitions()
    funds = {fid for preset in presets for fid in preset.funds}
    manifest = _module("portfoliosight.data.manifest").load_manifest(local_store)
    hundred_ids = sorted(
        fid
        for fid, entry in manifest.symbols.items()
        if entry.status == "ok" and local_store.exists(sm.record_key(fid))
    )[:100]
    assert len(hundred_ids) == 100, "100 served real source funds required"
    funds.update(hundred_ids)
    keys = [
        "meta/current.json",
        "meta/manifest.json",
        "meta/" + pointer["generation"] + "/generation.json",
    ]
    keys += [
        sm.record_key(fid)
        for fid in sorted(funds | {"SGOV", "SHV", "TSP-G"})
        if local_store.exists(sm.record_key(fid))
    ]
    assert {sm.record_key(fid) for fid in funds} <= set(keys)
    input_sha256 = {key: hashlib.sha256(local_store.get(key)).hexdigest() for key in keys}
    # The remote hostname comes from SSH's actual host, then the cgroup limits are read in-container.
    remote_command = (
        "hostname; exec docker exec -i "
        + shlex.quote(container)
        + " python -c "
        + shlex.quote(REMOTE_SOURCE)
        + " "
        + " ".join(
            shlex.quote(v)
            for v in (remote_root, source, json.dumps(digests), revision, json.dumps(input_sha256))
        )
    )
    started = time.perf_counter()
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--", host, remote_command],
        input="",
        text=True,
        capture_output=True,
        timeout=21600,
    )
    elapsed = time.perf_counter() - started
    assert result.returncode == 0, result.stdout[-8000:] + result.stderr[-5000:]
    lines = result.stdout.splitlines()
    assert lines and lines[0].strip().lower() == "ks-001", "Benchmark ran on another host"
    markers = [line.split("=", 1)[1] for line in lines if line.startswith("FROZEN_BENCHMARK=")]
    assert len(markers) == 1, "No uniquely completed frozen target workload"
    data = json.loads(markers[0])
    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", data["revision"], revision],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
    ), "Measured target revision is not an ancestor of this run"
    assert data["source_tree_sha256"] == source_tree
    assert data["cpu_quota"] == 4 and data["memory_bytes"] == 1536 * 1024 * 1024
    assert data["input_sha256"] == input_sha256 and data["cold_fit_calls"] >= 1
    assert data["nightly_fit_calls"] >= 1
    assert {(t["menu"], t["lookback"]) for t in data["tensors"]} == {
        (menu, lookback)
        for menu in ("guide2017", "tsp")
        for lookback in ("1y", "2y", "3y", "5y", "10y", "ew")
    }
    for descriptor in data["consumed"]:
        if descriptor["engine"] == "garch":
            assert 126 <= descriptor["shape_rows"] <= 2520
            assert (
                len(descriptor["fund_ids"])
                == len(descriptor["n_obs"])
                == len(descriptor["statuses"])
            )
            assert all(0 < n <= descriptor["shape_rows"] for n in descriptor["n_obs"])
    assert 0 < data["cold_ns"] <= 30_000_000_000
    assert 0 < data["nightly_ns"] <= 600_000_000_000
    assert data["built"] == {"guide2017": 6, "tsp": 6}
    assert len(data["warm"]) == 6 and {r["engine"] for r in data["warm"]} == {"replay", "garch"}
    assert all(0 < r["elapsed_ns"] < 1_000_000_000 for r in data["warm"])
    assert data["hundred_ns"] > 0 and len(data["hundred_funds"]) == 100
    total_ns = (
        data["hundred_ns"]
        + data["cold_ns"]
        + data["nightly_ns"]
        + sum(r["elapsed_ns"] for r in data["warm"])
    )
    assert total_ns / 1e9 <= elapsed + 1, (
        "Recorded operation times exceed externally measured execution"
    )
    assert len(data["consumed"]) >= 24 and all(
        d["shape"][:2] == [2000, 252] for d in data["consumed"]
    )
    runbooks = list((ROOT / "docs").rglob("*runbook*.md"))
    text = "\n".join(p.read_text() for p in runbooks)
    assert "KS-001" in text and source_tree in text
    # Documentation commits may follow measurement. Verify recorded revision/source independently.
    candidates = re.findall(r"\b[0-9a-f]{7,40}\b", text)
    matched_revision = False
    for recorded in candidates:
        resolved = subprocess.run(
            ["git", "rev-parse", "--verify", recorded + "^{commit}"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if resolved.returncode:
            continue
        measured = resolved.stdout.strip()
        if subprocess.run(
            ["git", "merge-base", "--is-ancestor", measured, revision],
            cwd=ROOT,
            capture_output=True,
        ).returncode:
            continue
        bound = True
        for name, digest in digests.items():
            historical = subprocess.run(
                ["git", "show", measured + ":" + name],
                cwd=ROOT,
                capture_output=True,
            )
            if historical.returncode or hashlib.sha256(historical.stdout).hexdigest() != digest:
                bound = False
                break
        if bound:
            matched_revision = True
            break
    assert matched_revision, (
        "No recorded measured revision binds to the verified product source tree"
    )
    assert re.search(r"(?:2,000|2000).*(?:252)|252.*(?:2,000|2000)", text)
    assert re.search(r"warm|after (?:the )?first", text, re.I) and re.search(
        r"cold|fit", text, re.I
    )
    assert re.search(r"(?:build|nightly|range)[^\n]*\d+(?:\.\d+)?\s*(?:s|seconds)", text, re.I)
    for fallback in data["fallbacks"]:
        assert fallback["id"] in text, "Named fallback omitted from measured runbook evidence"
    (tmp_path / "ks001_measured_budget.json").write_text(json.dumps(data, allow_nan=False))
