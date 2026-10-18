"""A-SE-10 property: independently built/reused tensors serialize identically and every
carried range equals compounded consumed draws. Floating-point oracle tolerance 2e-10 absolute,
2e-9 relative accommodates independently ordered sums, never serialized-build differences.
Pinned runtime: builder.build_tensor_full, TensorInputs.garch_artifact,
and BuildResult models/artifacts.
"""

from __future__ import annotations

import importlib
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
            timeout=1200,
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


def test_a_se_10_deterministic_tensor_and_range_contract(tmp_path):
    if not _runtime():
        return
    np = _product("numpy")
    builder = _product("portfoliosight.engine.builder")
    build = _product("portfoliosight.engine.builder", "build_tensor_full")
    replace = _product("dataclasses", "replace")
    for menu in ("guide2017", "tsp"):
        for lb in ("1y", "2y", "3y", "5y", "10y", "ew"):
            inputs = _inputs(menu, lb, tmp_path)
            a, b = build(inputs, workers=1), build(inputs, workers=1)
            reused = build(replace(inputs, garch_artifact=a.artifacts["garch"]), workers=1)
            assert (
                builder.canonical_json(a.tensor)
                == builder.canonical_json(b.tensor)
                == builder.canonical_json(reused.tensor)
            )
            t = a.tensor
            assert t["schema"] >= 3 and tuple(map(int, t["engine_version"].split("."))) >= (0, 3, 0)
            assert t["range_default"] == "replay"
            artifact = a.artifacts["garch"]
            assert t["shape"]["sample_sha256"] == artifact.sample_sha256
            assert [f["status"] for f in t["shape"]["funds"]] == list(artifact.status)
            assert t["range_method"] == t["engines"]["replay"]["method"]
            assert t["engines"]["garch"]["method"]["qse"] == artifact.qse
            assert t["engines"]["garch"]["method"]["arch"] == artifact.arch
            for engine in ("replay", "garch"):
                method = t["engines"][engine]["method"]
                assert method["paths"] == 2000 and method["horizon_days"] == 252
                assert method["seed"] == getattr(a.models[engine], "seed", 20261013)
                for block in ("frontier", "ladder", "entered"):
                    obj = t[block]
                    weights = np.asarray(obj["w"]).reshape(-1, len(t["mu_s"]))
                    consumed_years = np.column_stack([_years(a.models[engine], w) for w in weights])
                    expected = np.percentile(
                        consumed_years, [2.5, 50, 97.5], axis=0, method="linear"
                    )
                    variation = np.ptp(consumed_years, axis=0)
                    nondegenerate = variation > 64 * np.finfo(float).eps * np.maximum(
                        1.0, np.max(np.abs(consumed_years), axis=0)
                    )
                    for k, name in enumerate(("bad", "typical", "good")):
                        actual = np.asarray(obj["ranges"][engine][name]).reshape(-1)
                        np.testing.assert_allclose(actual, expected[k], atol=2e-10, rtol=2e-9)
                        if engine == "replay":
                            np.testing.assert_array_equal(
                                obj["range"][name], obj["ranges"][engine][name]
                            )
                    assert np.all(expected[0, nondegenerate] < expected[1, nondegenerate])
                    assert np.all(expected[1, nondegenerate] < expected[2, nondegenerate])
                    mu = weights @ np.asarray(t["mu_s"])
                    sigma = np.sqrt(
                        np.einsum("ij,jk,ik->i", weights, np.asarray(t["cov"]), weights)
                    )
                    assert np.all(
                        np.abs(
                            expected[1, nondegenerate]
                            - np.expm1(mu[nondegenerate] - sigma[nondegenerate] ** 2 / 2)
                        )
                        <= 0.25 * sigma[nondegenerate] + 1e-12
                    )
                    if np.any(~nondegenerate):
                        constant = np.expm1(252 * np.log1p(mu[~nondegenerate] / 252))
                        for percentile in expected[:, ~nondegenerate]:
                            np.testing.assert_allclose(percentile, constant, atol=1e-12, rtol=1e-12)
                    normal = obj["range"]["normal"]
                    for key, values in (
                        ("low", mu - 1.96 * sigma),
                        ("mid", mu),
                        ("high", mu + 1.96 * sigma),
                    ):
                        np.testing.assert_allclose(
                            np.asarray(normal[key]).reshape(-1), values, atol=1e-12
                        )
                    for name in ("bad", "typical", "good"):
                        np.testing.assert_array_equal(
                            np.asarray(t["ladder"]["ranges"][engine][name])[:, 0],
                            t["frontier"]["ranges"][engine][name],
                        )
                bad = np.asarray(t["frontier"]["ranges"][engine]["bad"])
                expected_safe = int(np.flatnonzero(bad == bad.max())[-1])
                assert t["frontier"]["ranges"][engine]["s_safe"] == expected_safe
            changed = inputs.returns.copy()
            changed.iloc[-100:, 1] *= 1.6
            altered = build(replace(inputs, returns=changed), workers=1)
            assert altered.tensor["shape"]["sample_sha256"] != t["shape"]["sample_sha256"]
            assert (
                altered.tensor["frontier"]["ranges"]["garch"] != t["frontier"]["ranges"]["garch"]
            ), "Hard-coded tensor ignores changed nonconstant returns"
    ranges = _product("portfoliosight.engine.ranges")
    mu, cov = np.array([0.03, 0.06]), np.zeros((2, 2))
    for model in (
        ranges.range_model(np.tile(mu / 252, (300, 1)), mu, cov),
        ranges.garch_range_model(np.tile(np.log1p(mu / 252), (2000, 252, 1)), mu, cov),
    ):
        for w in ([1.0, 0.0], [0.0, 1.0], [0.4, 0.6]):
            actual = ranges.one_year_ranges(model, w)
            expected = (1 + mu @ w / 252) ** 252 - 1
            for name in ("bad", "typical", "good"):
                np.testing.assert_allclose(actual[name], [expected], atol=1e-12, rtol=1e-12)
