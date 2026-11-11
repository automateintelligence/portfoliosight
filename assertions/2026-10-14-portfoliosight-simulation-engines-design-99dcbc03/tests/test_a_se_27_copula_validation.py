# ruff: noqa: E501
"""A-SE-27 contract (future Phase 3): real three-engine evidence, GARCH comparator.

Frozen independent coverage, pinball/PIT, stress, Bad/ENLC seed checks. All engines
share source inputs; comparison is by percentiles, never corresponding path IDs.
No report generation may alter defaults. Repeats are deliberately complete.
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
    """Run this frozen file in installed dependencies, importing this run's source."""
    roots = [ROOT]
    if (ROOT / ".git").is_file():
        roots.append(Path((ROOT / ".git").read_text().split(":", 1)[1].strip()).parents[2])
    python = next(
        (p / ".venv/bin/python" for p in roots if (p / ".venv/bin/python").exists()), None
    )
    if python and Path(sys.prefix).resolve() != python.parents[1].resolve():
        result = subprocess.run(
            [str(python), "-m", "pytest", "-q", "--noconftest", "-p", "no:cacheprovider", __file__],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONPATH": str(ROOT),
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
            },
            text=True,
            capture_output=True,
            timeout=21600,
        )
        assert result.returncode == 0, result.stdout[-12000:] + result.stderr[-3000:]
        return False
    return True


def _product(name, attr=None):
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        pytest.fail(f"Required runtime {name} is unavailable: {type(exc).__name__}: {exc}")
    if name.startswith(("portfoliosight", "scripts", "qse")):
        assert Path(module.__file__).resolve().is_relative_to(ROOT), (
            f"Imported foreign source: {module.__file__}"
        )
    if attr is not None:
        if not hasattr(module, attr):
            pytest.fail(f"Missing required runtime interface {name}.{attr}")
        return getattr(module, attr)
    return module


def _seed_evidence():
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
                    "replay,garch,copula",
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
            bad_groups = {}
            models = {}
            points = {}
            unstable = []
            transitions = []
            for row in rows:
                assert row["seed"] in seeds and row["paths"] == 2000 and row["horizon_days"] == 252
                assert row["alpha"] == alpha and row["engine"] in ("replay", "garch", "copula")
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
                    if row["engine"] in ("garch", "copula"):
                        panel = shape.shape_panel(history, row["fund_ids"], row["origin"])
                        fitted = shape.fit_shape(panel)
                        if row["engine"] == "copula":
                            upstream = _module("qse.distributions.joint.copula")
                            recursion = _module("qse.distributions.garch_recursion")
                            fit = upstream.fit_copula(
                                fitted.pool, seed=20261013, num_threads=1, truncation=5
                            )
                            shocks = fit.shock_source()(
                                2000, 252, np.random.default_rng(row["seed"])
                            )
                            logs = recursion.simulate_garch11(
                                shocks,
                                mu=fitted.mu,
                                omega=fitted.omega,
                                alpha=fitted.alpha,
                                beta=fitted.beta,
                                sigma2_init=recursion.garch11_long_run_variance(
                                    fitted.omega, fitted.alpha, fitted.beta
                                ),
                            )
                        else:
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
                if row["engine"] in ("garch", "copula"):
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
                bad = float(np.percentile(years, 2.5))
                assert abs(row["bad"] - bad) < 2e-9
                sigma = float(np.sqrt(w @ np.asarray(model.cov) @ w))
                bad_groups.setdefault(key, []).append((bad, sigma))
                point[row["seed"]] = expected
                points.setdefault(key[:3], set()).add(key[3:])
            required = {
                (menu, lookback, engine)
                for menu in ("guide2017", "tsp")
                for lookback in ("1y", "5y")
                for engine in ("replay", "garch", "copula")
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
            for key, values in bad_groups.items():
                assert (
                    len(values) == 5
                    and np.std([v[0] for v in values]) <= 0.1 * values[0][1] + 1e-12
                ), f"Bad-year instability: {key}"
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


def _module(name):
    return _product(name)


def test_a_se_27_copula_validation(tmp_path):
    if not _runtime():
        return
    _product("qse.distributions.joint.copula")
    import hashlib

    protected = [
        ROOT / "portfoliosight/engine/builder.py",
        ROOT / "portfoliosight/engine/ranges.py",
    ]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
    _coverage_evidence(tmp_path)
    _seed_evidence()
    assert all(
        hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in before.items()
    ), "Report generation changed defaults"


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


def _fixture_store(directory):
    """Frozen nontrivial returns and canonical records; no mutable fixture helper."""
    np, pd = _product("numpy"), _product("pandas")
    sm = _product("portfoliosight.data.store")
    manifest_mod = _product("portfoliosight.data.manifest")
    store = sm.LocalStore(directory)
    ids = [
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
        "TSP-G",
        "TSP-F",
        "TSP-C",
        "TSP-S",
        "TSP-I",
        "SGOV",
    ]
    days = pd.bdate_range("2005-01-03", "2026-10-12", name="date")
    rng = np.random.default_rng(20261013)
    factors = rng.normal(size=(len(days), 3))
    manifest = manifest_mod.Manifest()
    for j, fid in enumerate(ids):
        if fid in ("TSP-G", "SGOV"):
            returns = np.full(len(days), 0.035 / 252)
        else:
            # Correlated funds with distinct level, volatility, idiosyncratic noise and tails.
            vol = 0.035 + 0.007 * (j % 19)
            loading = np.array([0.65, 0.2 * ((j % 3) - 1), 0.15])
            returns = (0.025 + 0.002 * (j % 13)) / 252 + (
                factors @ loading + rng.standard_t(7, len(days)) * 0.45
            ) * vol / np.sqrt(252)
        active = days >= (pd.Timestamp("2020-05-28") if fid == "SGOV" else days[0])
        calendar, daily = days[active], returns[active]
        growth = np.r_[1.0, np.cumprod(1 + daily)]
        stamps = pd.DatetimeIndex([calendar[0] - pd.offsets.BDay(1)]).append(calendar)
        record = pd.DataFrame(
            {
                "date": stamps,
                "close": growth * 100,
                "tr_index": growth,
                "div_cash": np.zeros(len(stamps)),
                "split_factor": np.ones(len(stamps)),
            }
        )
        sm.put_record(store, fid, record)
        manifest.symbols[fid] = manifest_mod.ManifestEntry(
            name="Frozen " + fid,
            kind="tsp" if fid.startswith("TSP-") else "etf",
            tier=1,
            source="tsp" if fid.startswith("TSP-") else "seed",
            status="ok",
            first_date=stamps[0].date(),
            last_date=stamps[-1].date(),
            adjusted_through=stamps[-1].date(),
            fetched_at="2026-10-13T09:05:11Z",
        )
    sm.put_json(store, "meta/manifest.json", manifest.to_json())
    return store


def _years(model, weights):
    """Independent §4.5 oracle from the exact arrays the builder consumed, no range call."""
    np = _product("numpy")
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
        if sd[n] <= 64 * np.finfo(float).eps * max(1.0, abs(mean[n])):
            levelled[:, n] = m[n]
        else:
            levelled[:, n] = np.expm1(
                np.log1p(m[n]) - v[n] / 2 + (flat[:, n] - mean[n]) * np.sqrt(v[n]) / sd[n]
            )
    y = levelled @ w
    spread = y.std(ddof=0)
    sigma = float(np.sqrt(w @ np.asarray(model.cov) @ w)) / np.sqrt(252)
    daily = np.full_like(y, target) if spread <= 1e-15 else target + (y - y.mean()) * sigma / spread
    daily = daily.reshape(2000, 252)
    ruined = (daily <= -1).any(axis=1)
    years = np.full(2000, -1.0)
    years[~ruined] = np.expm1(np.log1p(daily[~ruined]).sum(axis=1))
    return years


def _blocked_run(tmp_path, command):
    """Deny provider access and writes outside this invocation's scratch directory."""
    wrapper = tmp_path / "offline_validation.py"
    wrapper.write_text(r"""import os,pathlib,runpy,socket,sys
allowed=pathlib.Path(os.environ['PS_VALIDATION_SCRATCH']).resolve()
def path_of(value):
    if isinstance(value,int): return None
    return pathlib.Path(os.fsdecode(value)).resolve()
def assert_writable(value):
    path=path_of(value)
    if path is not None and not path.is_relative_to(allowed):
        raise AssertionError('Validation attempted a write outside scratch: '+str(path))
def audit(event,args):
    if event=='open':
        path,mode,flags=args
        writing=(isinstance(mode,str) and any(c in mode for c in 'wax+'))
        writing=writing or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if writing: assert_writable(path)
    elif event in ('os.remove','os.rmdir','os.mkdir','os.chmod','os.utime','os.truncate'):
        assert_writable(args[0])
    elif event in ('os.rename','os.link','os.symlink'):
        assert_writable(args[0]); assert_writable(args[1])
    elif event in ('subprocess.Popen','os.system','os.exec','os.posix_spawn'):
        raise AssertionError('Validation cannot bypass the frozen read-only process boundary')
sys.addaudithook(audit)
def blocked(*a,**k): raise AssertionError('Provider/network access forbidden')
socket.create_connection=blocked
socket.socket.connect=blocked
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
""")
    # Filesystem metadata detects native-extension writes that bypass Python's open audit event.
    marker = command.index("--store-dir")
    source = Path(command[marker + 1])

    def snapshot():
        return {
            str(path.relative_to(source)): (path.stat().st_size, path.stat().st_mtime_ns)
            for path in source.rglob("*")
            if path.is_file()
        }

    before = snapshot()
    try:
        result = subprocess.run(
            [sys.executable, str(wrapper), *command],
            cwd=ROOT,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT),
                "PS_ENGINES": "replay,garch,copula",
                "PS_BUILD_WORKERS": "1",
                "PS_VALIDATION_SCRATCH": str(tmp_path),
                "PS_CACHE_DIR": str(tmp_path / "validation-cache"),
                "XDG_CACHE_HOME": str(tmp_path / "xdg-cache"),
                "TMPDIR": str(tmp_path),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            capture_output=True,
            text=True,
            timeout=1800,
        )
    finally:
        assert snapshot() == before, "Validation modified its input store"
    assert result.returncode == 0, result.stdout[-5000:] + result.stderr[-4000:]


def _audit_rows(rows, store):
    np = _product("numpy")
    sm = _product("portfoliosight.data.store")
    hashes = _product("hashlib")
    metrics = {}
    for row in rows:
        assert row["fit_end"] <= row["origin"]
        assert row["paths"] == 2000 and row["horizon_days"] == 252
        years = np.asarray(row["simulated_years"], float)
        assert years.shape == (2000,) and np.isfinite(years).all()
        expected = np.percentile(years, [2.5, 50, 97.5], method="linear")
        np.testing.assert_allclose(
            [row["predicted"][k] for k in ("bad", "typical", "good")],
            expected,
            atol=2e-10,
            rtol=2e-9,
        )
        future = []
        for record in row["source_records"]:
            assert hashes.sha256(store.get(record["key"])).hexdigest() == record["sha256"]
            data = sm.get_record(store, record["id"]).set_index("date")["tr_index"].sort_index()
            origin = _product("pandas").Timestamp(row["origin"])
            # The approved Phase 6 plan compounds constant-weight daily returns.
            future.append(data.pct_change().loc[data.index > origin].iloc[:252])
        matrix = _product("pandas").concat(future, axis=1, join="inner").dropna().to_numpy()
        assert matrix.shape == (252, len(row["weights"]))
        realized = float(np.expm1(np.log1p(matrix @ np.asarray(row["weights"])).sum()))
        assert row["realized"] == pytest.approx(realized, abs=1e-12)
        group = (row["menu"], row["lookback"], row["engine"])
        record = metrics.setdefault(group, [])
        losses = [
            float((q - (realized < pred)) * (realized - pred))
            for q, pred in zip((0.025, 0.5, 0.975), expected, strict=True)
        ]
        pit = float(np.count_nonzero(years <= realized) / 2000)
        record.append(
            {
                "origin": row["origin"],
                "covered": bool(expected[0] <= realized <= expected[2]),
                "breach": bool(realized < expected[0]),
                "pinball": losses,
                "pit": pit,
            }
        )
    return metrics


def _coverage_evidence(tmp_path):
    if not _runtime():
        return
    script = ROOT / "scripts/backtest_ranges.py"
    if not script.exists():
        pytest.fail("A-SE-27 expected RED: scripts/backtest_ranges.py is not implemented")
    mirror = Path(os.environ.get("PS_ENGINE_VALIDATION_STORE", "/mnt/d/portfoliosight-data"))
    if not mirror.is_dir():
        pytest.fail("A-SE-27 requires the local backup mirror; no provider fallback")
    np = _product("numpy")
    sm = _product("portfoliosight.data.store")
    store = sm.LocalStore(mirror)
    out = tmp_path / "validation"
    common = [
        "--store-dir",
        str(mirror),
        "--menus",
        "guide2017,tsp",
        "--lookbacks",
        "5y,1y",
        "--engines",
        "replay,garch,copula",
        "--out",
        str(out),
    ]
    for subcommand in ("coverage", "compare"):
        _blocked_run(tmp_path, [str(script), subcommand, *common])
    doc = json.loads((out / "coverage.json").read_text())
    rows = doc["rows"]
    assert doc["comparator"] == "garch"
    expected_quarters = {
        f"{year}-{month:02d}"
        for year in range(2015, 2026)
        for month in (3, 6, 9, 12)
        if "2015-12" <= f"{year}-{month:02d}" <= "2025-09"
    }
    assert len(expected_quarters) == 40
    keys = [(r["menu"], r["lookback"], r["origin"], r["mix"], r["engine"]) for r in rows]
    assert len(keys) == len(set(keys)), "Duplicate observations inflate coverage evidence"
    historical = {}
    preset_definitions = _product("portfoliosight.api.presets").preset_definitions()
    pd = _product("pandas")
    for preset in preset_definitions:
        prices = pd.DataFrame(
            {fid: sm.get_record(store, fid).set_index("date")["tr_index"] for fid in preset.funds}
        ).sort_index()
        historical[preset.id] = prices / prices.shift(1) - 1
    for menu in ("guide2017", "tsp"):
        for lb in ("1y", "5y"):
            subset = [r for r in rows if r["menu"] == menu and r["lookback"] == lb]
            assert {r["origin"][:7] for r in subset} == expected_quarters
            assert len({r["origin"] for r in subset}) == 40
            calendar = _product("exchange_calendars").get_calendar("XNYS")
            pd = _product("pandas")
            expected_days = set()
            for quarter in expected_quarters:
                end = pd.Period(quarter, freq="M").end_time.normalize()
                sessions = calendar.sessions_in_range(end - pd.Timedelta(days=10), end)
                expected_days.add(sessions[-1].date().isoformat())
            assert {r["origin"] for r in subset} == expected_days
            assert len({r["origin"] for r in subset if r["origin"][5:7] == "12"}) == 10
            paired = {(r["origin"], r["mix"]) for r in subset if r["engine"] == "replay"}
            assert paired == {(r["origin"], r["mix"]) for r in subset if r["engine"] == "garch"}
            assert paired == {(r["origin"], r["mix"]) for r in subset if r["engine"] == "copula"}
            assert "equal_weight" in {r["mix"] for r in subset}
            definition = next(p for p in preset_definitions if p.id == menu)
            entered = [r for r in subset if r["mix"] == "entered"]
            expected_cases = {(r["origin"], r["engine"]) for r in subset}
            if definition.allocation is None:
                assert not entered, "No allocation was supplied: do not fabricate an entered mix"
                unavailable = [
                    r
                    for r in doc["unavailable_cases"]
                    if r["menu"] == menu and r["lookback"] == lb and r["mix"] == "entered"
                ]
                assert {(r["origin"], r["engine"]) for r in unavailable} == expected_cases
                assert all(
                    r["status"] == "unavailable" and r["reason"] == "no_allocation"
                    for r in unavailable
                )
            else:
                assert {(r["origin"], r["engine"]) for r in entered} == expected_cases
                for record in entered:
                    ids = [item["id"] for item in record["source_records"]]
                    amounts = np.array([definition.allocation.get(fid, 0) for fid in ids], float)
                    assert amounts.sum() > 0
                    np.testing.assert_allclose(
                        record["weights"], amounts / amounts.sum(), atol=1e-12, rtol=0
                    )

            for origin in {r["origin"] for r in subset}:
                mixes = {r["mix"] for r in subset if r["origin"] == origin}
                assert all(
                    any(kind in mix and location in mix for mix in mixes)
                    for kind in ("frontier", "optimized")
                    for location in ("safe", "mid", "max")
                )
                origin_rows = [row for row in subset if row["origin"] == origin]
                included = {item["id"] for item in origin_rows[0]["source_records"]}
                frame = historical[menu].loc[:origin]
                length = 252 if lb == "1y" else 1260
                start = len(frame) - length
                expected_included = set()
                for fid in frame.columns:
                    valid = frame[fid].notna().to_numpy()
                    if valid.any() and 10 * (int(valid.argmax()) - start) <= length:
                        expected_included.add(fid)
                assert included == expected_included, (
                    "Validation omitted or fabricated eligible funds"
                )
                assert {m for m in mixes if m.startswith("single:")} == {
                    "single:" + fid for fid in included
                }
                assert 2 <= len(included) <= (23 if menu == "guide2017" else 5)
    recomputed = _audit_rows(rows, store)
    for metric in doc["metrics"]:
        group = recomputed[metric["menu"], metric["lookback"], metric["engine"]]
        sample = [
            x for x in group if metric["origin_set"] == "quarterly" or x["origin"][5:7] == "12"
        ]
        assert metric["observations"] == len(sample)
        assert metric["coverage"] == pytest.approx(
            np.mean([x["covered"] for x in sample]), abs=1e-12
        )
        assert metric["below_bad"] == sum(x["breach"] for x in sample)
        np.testing.assert_allclose(
            metric["pinball"], np.sum([x["pinball"] for x in sample], axis=0), atol=1e-10
        )
        pits = np.sort([x["pit"] for x in sample])
        n = len(pits)
        ks = max(np.max(np.arange(1, n + 1) / n - pits), np.max(pits - np.arange(n) / n))
        assert metric["pit_ks"] == pytest.approx(ks, abs=1e-12)
    assert len(doc["metrics"]) == 2 * 2 * 3 * 2
    assert {metric["origin_set"] for metric in doc["metrics"]} == {"quarterly", "year_end"}
    # Sample each menu/lookback through the actual builder at its historical origin.
    builder = _product("portfoliosight.engine.builder")
    build = _product("portfoliosight.engine.builder", "build_tensor_full")
    presets = _product("portfoliosight.api.presets").preset_definitions()
    pd = _product("pandas")
    for menu in ("guide2017", "tsp"):
        preset = next(p for p in presets if p.id == menu)
        records = {
            fid: sm.get_record(store, fid).set_index("date")["tr_index"].sort_index()
            for fid in preset.funds
        }
        prices = pd.DataFrame(records).sort_index()
        returns = prices / prices.shift(1) - 1
        for lb in ("1y", "5y"):
            row = next(
                r
                for r in rows
                if r["menu"] == menu
                and r["lookback"] == lb
                and r["engine"] == "garch"
                and r["mix"] == "equal_weight"
            )
            origin = row["origin"]
            funds = [
                builder.FundInput(
                    id=fid,
                    name=fid,
                    kind="tsp" if menu == "tsp" else "etf",
                    source="seed",
                    adjusted_through=origin,
                    fetched_at=origin + "T00:00:00Z",
                )
                for fid in preset.funds
            ]
            rf = {}
            for fid in ("SGOV", "SHV", "TSP-G"):
                if store.exists(sm.record_key(fid)):
                    rf[fid] = (
                        sm.get_record(store, fid)
                        .set_index("date")["tr_index"]
                        .sort_index()
                        .pct_change(fill_method=None)
                    )
            result = build(
                builder.TensorInputs(
                    funds=funds,
                    returns=returns,
                    lookback=lb,
                    asof=origin,
                    universe_name=menu,
                    preset_id=menu,
                    rf_series=rf,
                    engines=("replay", "garch", "copula"),
                ),
                workers=1,
            )
            assert [f["id"] for f in result.tensor["universe"]["funds"]] == [
                f["id"] for f in row["source_records"]
            ]
            np.testing.assert_allclose(row["mu"], result.tensor["mu_s"], atol=1e-12)
            np.testing.assert_allclose(row["cov"], result.tensor["cov"], atol=1e-12)
            for engine in ("replay", "garch", "copula"):
                observed = next(
                    r
                    for r in rows
                    if r["menu"] == menu
                    and r["lookback"] == lb
                    and r["origin"] == origin
                    and r["mix"] == "equal_weight"
                    and r["engine"] == engine
                )
                np.testing.assert_allclose(
                    observed["simulated_years"],
                    _years(result.models[engine], observed["weights"]),
                    atol=2e-10,
                    rtol=2e-9,
                )
    # Synthetic no-leakage control through the same public CLI, using a temporary fixture store.
    fixture = _fixture_store(tmp_path / "synthetic")
    origin = "2020-12-31"
    synthetic_args = [
        "--store-dir",
        str(tmp_path / "synthetic"),
        "--menus",
        "tsp",
        "--lookbacks",
        "1y",
        "--engines",
        "replay,garch,copula",
        "--origins",
        origin,
    ]
    first_out, second_out = tmp_path / "synthetic-a", tmp_path / "synthetic-b"
    _blocked_run(tmp_path, [str(script), "coverage", *synthetic_args, "--out", str(first_out)])
    a = json.loads((first_out / "coverage.json").read_text())["rows"]
    frame = sm.get_record(fixture, "TSP-C")
    later = frame["date"] > _product("pandas").Timestamp(origin)
    frame.loc[later, "tr_index"] *= np.exp(np.arange(later.sum()) * 0.001)
    sm.put_record(fixture, "TSP-C", frame)
    _blocked_run(tmp_path, [str(script), "coverage", *synthetic_args, "--out", str(second_out)])
    b = json.loads((second_out / "coverage.json").read_text())["rows"]
    assert [r["predicted"] for r in a] == [r["predicted"] for r in b], (
        "Future observations leaked into origin prediction"
    )
    assert [r["realized"] for r in a] != [r["realized"] for r in b], (
        "Validation is disconnected from realized prices"
    )
    _audit_rows(
        a,
        _fixture_store(tmp_path / "synthetic-original"),
    )
    _audit_rows(b, fixture)
    constant = [row for row in a if row["mix"] == "single:TSP-G"]
    assert len(constant) == 3
    for row in constant:
        assert row["realized"] == pytest.approx((1 + 0.035 / 252) ** 252 - 1, abs=1e-12)
    compare = json.loads((out / "compare.json").read_text())
    assert {r["menu"] for r in compare["rows"]} == {"guide2017", "tsp"}
    for menu in ("guide2017", "tsp"):
        for engine in ("replay", "garch", "copula"):
            assert {
                r["column"]
                for r in compare["rows"]
                if r["menu"] == menu and r["engine"] == engine and r["point"] == "frontier"
            } == set(range(48))
            assert (
                len(
                    [
                        r
                        for r in compare["stress_rows"]
                        if r["menu"] == menu and r["engine"] == engine
                    ]
                )
                >= 9
            )
    assert compare["invariants"] and all(r["passed"] for r in compare["invariants"])
    # Numeric live/stress evidence cannot be replaced with headings or placeholder rows.
    live_summary, stress_summary = [], []
    windows = {
        "gfc2008": ("2008-09-01", "2009-03-09"),
        "covid2020": ("2020-02-19", "2020-03-23"),
        "rates2022": ("2022-01-03", "2022-10-12"),
    }
    for row in compare["rows"]:
        years = np.asarray(row["simulated_years"], dtype=float)
        assert years.shape == (2000,) and np.isfinite(years).all()
        expected = np.percentile(years, [2.5, 50, 97.5], method="linear")
        np.testing.assert_allclose(
            [row["predicted"][name] for name in ("bad", "typical", "good")],
            expected,
            atol=2e-10,
            rtol=2e-9,
        )
        assert row["point"] in ("frontier", "optimized")
        assert 0 <= row["column"] < 48
        live_summary.append(
            {
                key: row[key]
                for key in ("menu", "lookback", "engine", "point", "column", "predicted")
            }
        )
    for row in compare["stress_rows"]:
        assert row["window"] in windows and row["location"] in ("safe", "mid", "max")
        start, end = windows[row["window"]]
        assert (row["start"], row["end"]) == (start, end)
        weights = np.asarray(row["weights"], dtype=float)
        assert len(weights) == len(row["source_records"])
        assert np.all(weights >= -1e-6) and weights.sum() == pytest.approx(1.0, abs=1e-6)
        gained, covered = 0.0, 0.0
        for weight, record in zip(weights, row["source_records"], strict=True):
            assert (
                _product("hashlib").sha256(store.get(record["key"])).hexdigest() == record["sha256"]
            )
            values = (
                sm.get_record(store, record["id"])
                .set_index("date")["tr_index"]
                .dropna()
                .sort_index()
            )
            left, right = values.loc[:start], values.loc[:end]
            if left.empty or right.empty:
                continue
            left_age = len(calendar.sessions_in_range(left.index[-1], pd.Timestamp(start))) - 1
            right_age = len(calendar.sessions_in_range(right.index[-1], pd.Timestamp(end))) - 1
            if left_age > 3 or right_age > 3:
                continue
            covered += weight
            gained += weight * (float(right.iloc[-1] / left.iloc[-1]) - 1)
        assert row["covered"] == pytest.approx(covered, abs=1e-12)
        if covered < 0.5:
            assert row["loss"] is None and row["pit"] is None
        else:
            loss = gained / covered
            assert row["loss"] == pytest.approx(loss, abs=1e-12)
            years = np.asarray(row["simulated_years"], dtype=float)
            assert years.shape == (2000,) and np.isfinite(years).all()
            assert row["pit"] == pytest.approx(
                float(np.count_nonzero(years <= loss) / 2000), abs=1e-12
            )
        stress_summary.append(
            {
                key: row[key]
                for key in (
                    "menu",
                    "lookback",
                    "engine",
                    "window",
                    "location",
                    "loss",
                    "covered",
                    "pit",
                )
            }
        )
    for menu in ("guide2017", "tsp"):
        for lb in ("1y", "5y"):
            for engine in ("replay", "garch", "copula"):
                scope = [
                    row
                    for row in compare["rows"]
                    if row["menu"] == menu and row["lookback"] == lb and row["engine"] == engine
                ]
                for point in ("frontier", "optimized"):
                    assert {row["column"] for row in scope if row["point"] == point} == set(
                        range(48)
                    )
                stress_scope = [
                    row
                    for row in stress_summary
                    if row["menu"] == menu and row["lookback"] == lb and row["engine"] == engine
                ]
                assert {(row["window"], row["location"]) for row in stress_scope} == {
                    (window, location) for window in windows for location in ("safe", "mid", "max")
                }
    components = []
    # Only explicitly defined components are judged. No new breach aggregation or winner rule.
    for menu in ("guide2017", "tsp"):
        for lb in ("1y", "5y"):
            grouped = {}
            for engine in ("garch", "copula"):
                values = recomputed[menu, lb, engine]
                annual = {}
                for row in values:
                    if row["origin"][5:7] == "12":
                        annual.setdefault(row["origin"], np.zeros(3))
                        annual[row["origin"]] += row["pinball"]
                assert len(annual) == 10
                grouped[engine] = annual
            years = sorted(grouped["garch"])
            assert years == sorted(grouped["copula"])
            a = np.asarray([grouped["garch"][year] for year in years])
            b = np.asarray([grouped["copula"][year] for year in years])
            components.append(
                {
                    "menu": menu,
                    "lookback": lb,
                    "bad_pinball_wins": int(np.count_nonzero(b[:, 0] < a[:, 0])),
                    "nonoverlapping_years": 10,
                    "median_no_worse": bool(b[:, 1].sum() <= a[:, 1].sum()),
                    "good_no_worse": bool(b[:, 2].sum() <= a[:, 2].sum()),
                }
            )
    report = (out / "report.md").read_text()
    assert (
        "overlap" in report.lower() and "weak" in report.lower() and "lower bound" in report.lower()
    )
    # Structured decision criteria prevent changing the rule to match a result.
    assert doc["decision_rule"] == {
        "bad_pinball_wins_required": 8,
        "nonoverlapping_years": 10,
        "median_good_no_worse": True,
        "breaches_allowed": [0, 1],
        "stress_percentile_floor": 0.005,
        "owner_review_required": True,
        "tie_keeps_default": True,
    }
    import re

    summaries = []
    for fence in re.findall(r"```(?:json)?\s*\n(.*?)```", report, re.S):
        try:
            value = json.loads(fence)
        except ValueError:
            continue
        if isinstance(value, dict) and "engine_validation_summary" in value:
            summaries.append(value["engine_validation_summary"])
    assert len(summaries) == 1, "Published report needs one compact verified experiment summary"
    summary = summaries[0]
    for key, expected in {
        "metrics": doc["metrics"],
        "decision_rule": doc["decision_rule"],
        "decision_components": components,
        "live_comparison": live_summary,
        "stress_comparison": stress_summary,
        "invariant_results": compare["invariants"],
        "default_engine": "replay",
        "comparator": "garch",
        "owner_review_required": True,
    }.items():
        assert summary[key] == expected, "Published report detached from evaluated " + key
    # Human-readable metric tables must carry their corresponding verified values too.
    table = [line for line in report.splitlines() if line.strip().startswith("|")]
    for metric in doc["metrics"]:
        labels = (metric["menu"], "Example Portfolio" if metric["menu"] == "guide2017" else "TSP")
        matching = [
            line
            for line in table
            if any(label.lower() in line.lower() for label in labels)
            and metric["lookback"] in line
            and metric["engine"] in line
            and metric["origin_set"].replace("_", " ").lower() in line.replace("_", " ").lower()
        ]
        coverage = (
            str(metric["coverage"]),
            f"{metric['coverage']:.4f}",
            f"{metric['coverage'] * 100:.1f}%",
            f"{metric['coverage'] * 100:.2f}%",
        )
        assert any(
            any(value in line for value in coverage)
            and re.search(r"\b" + str(metric["below_bad"]) + r"\b", line)
            for line in matching
        ), "Published table omits or changes verified coverage/breach values"
    saved_reports = list((ROOT / "docs/reviews").glob("*engine*validation*.md"))
    assert any(path.read_text() == report for path in saved_reports), (
        "Report output was not saved under docs/reviews"
    )
