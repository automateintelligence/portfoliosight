"""A-SE-15: actual 2,000-path simulations at all five seeds, both presets/lookbacks.
Independent population standard deviation across the fixed five-run experiment.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
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
            timeout=1800,
        )
        assert result.returncode == 0, result.stdout[-12000:] + result.stderr[-3000:]
        return False
    return True


def _product(name, attr=None):
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        pytest.fail(f"Required runtime {name} is unavailable: {type(exc).__name__}: {exc}")
    if name.startswith(("portfoliosight", "scripts")):
        assert Path(module.__file__).resolve().is_relative_to(ROOT), (
            f"Imported foreign source: {module.__file__}"
        )
    if attr is not None:
        if not hasattr(module, attr):
            pytest.fail(f"Missing required runtime interface {name}.{attr}")
        return getattr(module, attr)
    return module


def _inputs(menu, lookback, directory):
    np, pd = _product("numpy"), _product("pandas")
    builder = _product("portfoliosight.engine.builder")
    if menu == "guide2017":
        frame = pd.read_parquet(ROOT / "tests/fixtures/synthetic_23.parquet")
    else:
        # Deterministic five-fund TSP fixture: constant G plus correlated risky funds.
        calendar = pd.read_parquet(ROOT / "tests/fixtures/synthetic_23.parquet", columns=[]).index
        rng = np.random.default_rng(20261013)
        market = rng.normal(0, 1, (len(calendar), 1))
        values = np.array([0.035, 0.03, 0.085, 0.09, 0.06]) / 252 + (
            market * 0.6 + rng.normal(0, 0.8, (len(calendar), 5))
        ) * np.array([0, 0.045, 0.16, 0.20, 0.17]) / np.sqrt(252)
        frame = pd.DataFrame(
            values, index=calendar, columns=["TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I"]
        )
    asof = frame.index[-1].date().isoformat()
    funds = [
        builder.FundInput(
            id=fid,
            name=fid,
            kind="tsp" if menu == "tsp" else "etf",
            source="seed",
            adjusted_through=asof,
            fetched_at=asof + "T00:00:00Z",
            last_close=100.0,
        )
        for fid in frame.columns
    ]
    try:
        return builder.TensorInputs(
            funds=funds,
            returns=frame,
            lookback=lookback,
            asof=asof,
            universe_name=menu,
            preset_id=menu,
            allocation={fid: 1.0 for fid in frame.columns},
            nx=4,
            ny=3,
            levels=2,
            engines=("replay", "garch"),
        )
    except TypeError as exc:
        pytest.fail(f"Engine-aware TensorInputs not implemented: {exc}")


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


def test_a_se_15_bad_year_seed_stability(tmp_path):
    if not _runtime():
        return
    np = _product("numpy")
    replace = _product("dataclasses", "replace")
    build = _product("portfoliosight.engine.builder", "build_tensor_full")
    ranges = _product("portfoliosight.engine.ranges")
    shape = _product("portfoliosight.engine.shape")
    seeds = list(range(20261013, 20261018))
    measurements = []
    failures = []
    for menu in ("guide2017", "tsp"):
        for lb in ("1y", "5y"):
            result = build(replace(_inputs(menu, lb, tmp_path), nx=48, ny=32, levels=12), workers=1)
            t = result.tensor
            front = np.asarray(t["frontier"]["w"])
            ladder = np.asarray(t["ladder"]["w"])
            assert len(front) == 48
            points = [("frontier", j, w) for j, w in enumerate(front)]
            for j in range(48):
                k = int(round(t["ladder"]["t_suggested"][j] * (len(ladder[j]) - 1)))
                points.append(("optimized", j, ladder[j, k]))
            for engine in ("replay", "garch"):
                all_bad = []
                draw_hashes = []
                for seed in seeds:
                    if engine == "replay":
                        original = result.models[engine]
                        try:
                            model = ranges.range_model(
                                original.sample, original.mu_s, original.cov, seed=seed
                            )
                        except TypeError as exc:
                            pytest.fail(f"Seedable replay model required: {exc}")
                        raw = np.asarray(model.counts)
                        assert raw.shape[0] == 2000
                        np.testing.assert_array_equal(raw.sum(axis=1), np.full(2000, 252))
                    else:
                        raw = shape.simulate_panel(
                            result.artifacts["garch"], paths=2000, horizon=252, seed=seed
                        )
                        assert raw.shape[:2] == (2000, 252)
                        model = ranges.garch_range_model(raw, t["mu_s"], t["cov"], seed=seed)
                    draw_hashes.append(
                        _product("hashlib").sha256(np.ascontiguousarray(raw).tobytes()).hexdigest()
                    )
                    bad = []
                    for kind, column, w in points:
                        years = _years(model, w)
                        assert years.shape == (2000,) and np.isfinite(years).all()
                        value = float(np.percentile(years, 2.5, method="linear"))
                        reported = float(ranges.one_year_ranges(model, w)["bad"][0])
                        assert reported == pytest.approx(value, abs=2e-10, rel=2e-9)
                        sigma = float(np.sqrt(w @ np.asarray(t["cov"]) @ w))
                        measurements.append(
                            {
                                "menu": menu,
                                "lookback": lb,
                                "engine": engine,
                                "seed": seed,
                                "point": kind,
                                "column": column,
                                "bad": value,
                                "sigma": sigma,
                                "paths": 2000,
                                "horizon_days": 252,
                                "draw_sha256": draw_hashes[-1],
                            }
                        )
                        bad.append(value)
                    all_bad.append(bad)
                assert len(set(draw_hashes)) == 5, "Seeds reused one copied simulation draw"
                spread = np.asarray(all_bad).std(axis=0, ddof=0)
                for index, (kind, column, w) in enumerate(points):
                    sigma = float(np.sqrt(w @ np.asarray(t["cov"]) @ w))
                    if spread[index] > 0.1 * sigma + 1e-12:
                        failures.append(
                            (menu, lb, engine, kind, column, float(spread[index]), sigma)
                        )
    assert len(measurements) == 2 * 2 * 2 * 5 * 96
    (tmp_path / "bad_seed_measurements.json").write_text(json.dumps(measurements, allow_nan=False))
    assert not failures, f"Bad seed-stability exceeded 0.10 sigma; all points retained: {failures}"
