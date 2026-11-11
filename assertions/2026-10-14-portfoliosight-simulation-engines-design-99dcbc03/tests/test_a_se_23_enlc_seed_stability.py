# ruff: noqa: E501
"""A-SE-23 property: all five seeds, complete tail-level rerun, no null coercion.

Uses plan `backtest_ranges.py seeds` with --alpha and --out directory. Each row
names menu/lookback/engine/column/point, model inputs, source-record digests and
simulation {path,sha256,kind}. Real models are reconstructed from those records;
ENLC is independently recomputed. These are audit exports, not alternate engines.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

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


def test_a_se_23_enlc_seed_stability():
    if not _runtime():
        return
    import hashlib
    import io
    import math

    import numpy as np
    import pandas as pd

    script = ROOT / "scripts/backtest_ranges.py"
    assert script.exists(), "The required ENLC five-seed experiment is not implemented"
    backup = Path("/mnt/d/portfoliosight-data")
    assert backup.is_dir(), "Required backup is missing; seed validation cannot pass"
    ranges = _module("portfoliosight.engine.ranges")
    shape = _module("portfoliosight.engine.shape")
    seeds = set(range(20261013, 20261018))
    runner = _offline_program()
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        attempts = []
        for alpha in (0.05, 0.10):
            out = base / str(alpha)
            out.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    runner,
                    str(script),
                    "seeds",
                    "--store-dir",
                    str(backup),
                    "--menus",
                    "guide2017,tsp",
                    "--lookbacks",
                    "5y,1y",
                    "--engines",
                    "replay,garch",
                    "--alpha",
                    str(alpha),
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
            data = json.loads((out / "seeds.json").read_text())
            rows = sorted(
                data["rows"],
                key=lambda r: (
                    r["menu"],
                    r["lookback"],
                    r["engine"],
                    r["seed"],
                    r["column"],
                    r["point"],
                ),
            )
            assert data["alpha"] == alpha and rows
            grouped = {}
            reference_cache = {}
            signatures = {}
            models = {}
            points = {}
            unstable = []
            transitions = []
            for row in rows:
                assert row["seed"] in seeds and row["paths"] == 2000 and row["horizon_days"] == 252
                assert row["alpha"] == alpha and row["engine"] in ("replay", "garch")
                assert row["point"] in ("frontier", "optimized")
                key = (row["menu"], row["lookback"], row["engine"], row["column"], row["point"])
                point = grouped.setdefault(key, {})
                assert row["seed"] not in point, "Duplicate seed cannot replace a missing seed"
                modelkey = key[:3] + (row["seed"],)
                if modelkey not in models:
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
                    history = prices.pct_change(fill_method=None).loc[: row["origin"]]
                    sample = history.loc[row["lookback_start"] : row["origin"]].dropna().to_numpy()
                    mu = np.array(row["mu"])
                    cov = np.array(row["cov"])
                    if row["engine"] == "garch":
                        panel = shape.shape_panel(history, row["fund_ids"], row["origin"])
                        fitted = shape.fit_shape(panel)
                        logs = shape.simulate_panel(
                            fitted, paths=2000, horizon=252, seed=row["seed"]
                        )
                        model = ranges.garch_range_model(logs, mu, cov, seed=row["seed"])
                        mean = logs.mean(axis=(0, 1))
                        sd = logs.std(axis=(0, 1), ddof=0)
                        m = mu / 252
                        vol = np.sqrt(np.diag(cov) / 252)
                        lv = np.log1p(vol**2 / (1 + m) ** 2)
                        lm = np.log1p(m) - lv / 2
                        scaled = np.empty_like(logs)
                        varying = sd > 1e-12
                        scaled[:, :, varying] = np.expm1(
                            lm[varying]
                            + (logs[:, :, varying] - mean[varying])
                            * np.sqrt(lv[varying])
                            / sd[varying]
                        )
                        scaled[:, :, ~varying] = m[~varying]
                        source_array = logs
                    else:
                        model = ranges.range_model(sample, mu, cov, seed=row["seed"])
                        count = np.asarray(model.counts)
                        assert count.shape == (2000, len(sample))
                        assert np.all(count.sum(axis=1) == 252)
                        scaled = sample - sample.mean(axis=0) + mu / 252
                        source_array = count
                    descriptor = row["simulation"]
                    artifact = (out / descriptor["path"]).resolve()
                    assert artifact.is_relative_to(out.resolve())
                    raw = artifact.read_bytes()
                    assert hashlib.sha256(raw).hexdigest() == descriptor["sha256"]
                    observed = np.load(io.BytesIO(raw), allow_pickle=False)
                    assert np.array_equal(observed, source_array), (
                        "Exported simulation differs from actual engine draw"
                    )
                    if len(models) >= 2:
                        models.pop(next(iter(models)))
                    models[modelkey] = (model, scaled)
                reference = _reference_tensor(row, backup, reference_cache)
                assert row["lookback_start"] == reference["lookback"]["start"]
                signature = json.dumps(
                    {k: row[k] for k in ("origin", "fund_ids", "mu", "cov", "weights")},
                    sort_keys=True,
                )
                assert signatures.setdefault(key, signature) == signature, (
                    "Seeds changed the evaluated mix or moments"
                )
                model, scaled = models[modelkey]
                w = np.array(row["weights"])
                assert abs(w.sum() - 1) < 1e-6 and len(w) == len(row["fund_ids"])
                m = np.array(model.mu_s) / 252
                if row["engine"] == "garch":
                    mean = scaled.mean(axis=(0, 1))
                    daily = scaled @ w
                    sd = daily.std(ddof=0)
                    target = np.sqrt(w @ model.cov @ w / 252)
                    k = target / sd if sd > 1e-12 else 0
                    mix = m @ w + k * (daily - mean @ w)
                    assert np.all(mix > -1), (
                        "Ruined-tail tie/post-ruin policy remains unresolved, cannot certify"
                    )
                    years = np.expm1(np.log1p(mix).sum(axis=1))
                    contributions = w * (252 * m + k * (scaled.sum(axis=1) - 252 * mean))
                else:
                    daily = scaled @ w
                    assert np.all(daily > -1)
                    years = np.expm1(model.counts @ np.log1p(daily))
                    contributions = (model.counts @ scaled) * w
                tail = np.argsort(years)[: math.ceil(alpha * 2000)]
                boundary = np.sort(years)[len(tail) - 1]
                tied = contributions[years == boundary]
                if np.count_nonzero(years <= boundary) > len(tail):
                    assert np.allclose(tied, tied[0], rtol=0, atol=1e-12), (
                        "Boundary ties have distinct contributions: unresolved tail policy"
                    )
                positive = np.maximum(-contributions[tail].mean(axis=0), 0)
                shares = (
                    positive[positive > 0] / positive.sum() if positive.sum() > 0 else np.array([])
                )
                expected = float(np.exp(-np.sum(shares * np.log(shares)))) if len(shares) else None
                if expected is None:
                    assert row["enlc"] is None and row["no_loss"] is True
                else:
                    assert row["enlc"] is not None and abs(row["enlc"] - expected) < 2e-9
                point[row["seed"]] = expected
                points.setdefault(key[:3], set()).add(key[3:])
            required = {
                (menu, lookback, engine)
                for menu in ("guide2017", "tsp")
                for lookback in ("1y", "5y")
                for engine in ("replay", "garch")
            }
            assert set(points) == required
            for actual in points.values():
                assert actual == {
                    (column, point) for column in range(48) for point in ("frontier", "optimized")
                }
            for key, values in grouped.items():
                assert set(values) == seeds, f"Missing seeds at {key}"
                numeric = [v for v in values.values() if v is not None]
                if numeric and len(numeric) != 5:
                    transitions.append(key)
                elif numeric and np.std(numeric, ddof=0) > 0.3:
                    unstable.append(key)
            attempts.append(
                {"alpha": alpha, "unstable": unstable, "transitions": transitions, "rows": rows}
            )
            assert data["null_transitions"] == [list(k) for k in transitions]
            assert not transitions, f"Numeric/null transitions unresolved: {transitions[:5]}"
            if not unstable:
                assert data["selected_alpha"] == alpha
                report = (out / "report.md").read_text()
                assert str(alpha) in report and data["method"]["loss_alpha"] == alpha
                if alpha == 0.10:
                    assert attempts[0]["unstable"], (
                        "10% requires preserving the failed 5% experiment"
                    )
                    assert data["prior_5pct_failure"] == attempts[0]
                break
            assert alpha == 0.05, f"Final ENLC standard deviation exceeds 0.3: {unstable[:5]}"


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
    if "column" not in row:
        return tensor
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
