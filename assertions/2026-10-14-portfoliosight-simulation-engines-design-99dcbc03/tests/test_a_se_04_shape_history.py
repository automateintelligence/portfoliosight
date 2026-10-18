"""A-SE-04 (property): real builder fit input, independent digest and exact common pool.
Pins build_tensor_full(TensorInputs(...)), shape_panel/fit_shape, and the QSE fitter seam.
Controlled missing residuals isolate the 126-row simulation floor from replay eligibility.
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


def _inner():
    """Reexecute this frozen file with project dependencies, never a sibling product tree."""
    roots = [ROOT]
    dotgit = ROOT / ".git"
    if dotgit.is_file():
        roots.append(Path(dotgit.read_text().split(":", 1)[1].strip()).parents[2])
    interpreter = next(
        (r / ".venv/bin/python" for r in roots if (r / ".venv/bin/python").exists()),
        None,
    )
    if interpreter and Path(sys.prefix).resolve() != interpreter.parents[1].resolve():
        result = subprocess.run(
            [
                str(interpreter),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                str(Path(__file__).resolve()),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=900,
            env={
                **os.environ,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONPATH": str(ROOT),
                "PYTHONNOUSERSITE": "1",
            },
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return True
    return False


def _need(name):
    # An editable install in the shared venv can point at another feature worktree.
    top = name.split(".")[0]
    if top in {"portfoliosight", "qse"}:
        for key in list(sys.modules):
            if key == top or key.startswith(top + "."):
                module = sys.modules[key]
                origins = list(getattr(module, "__path__", []))
                if getattr(module, "__file__", None):
                    origins.append(module.__file__)
                if any(not Path(p).resolve().is_relative_to(ROOT) for p in origins):
                    for stale in list(sys.modules):
                        if stale == top or stale.startswith(top + "."):
                            del sys.modules[stale]
                    break
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        pytest.fail(
            f"Required product interface {name} is unavailable: {type(exc).__name__}: {exc}"
        )
    if top in {"portfoliosight", "qse"}:
        assert Path(module.__file__).resolve().is_relative_to(ROOT), (
            "Product imported from a different checkout"
        )
    return module


def _attr(module, name):
    if not hasattr(module, name):
        pytest.fail(f"Required product interface {module.__name__}.{name} is missing")
    return getattr(module, name)


import hashlib
from dataclasses import replace


def _digest(frame):
    import numpy as np

    values = np.array(frame, dtype="<f8", order="C")
    values[np.isnan(values)] = np.array([0x7FF8000000000000], dtype="<u8").view("<f8")[0]
    prefix = (
        "\x1f".join(frame.columns).encode()
        + b"\x1e"
        + "\x1f".join(t.date().isoformat() for t in frame.index).encode()
        + b"\x1e"
    )
    return hashlib.sha256(prefix + values.tobytes()).hexdigest()


def test_a_se_04_shape_history_and_pool(monkeypatch):
    if _inner():
        return
    np, pd = _need("numpy"), _need("pandas")
    builder, shape = (
        _need("portfoliosight.engine.builder"),
        _need("portfoliosight.engine.shape"),
    )
    build = _attr(builder, "build_tensor_full")
    dates = pd.bdate_range(end="2026-11-30", periods=2900)
    asof = pd.Timestamp("2026-10-13")
    rng = np.random.default_rng(42)
    frame = pd.DataFrame(
        np.expm1(rng.normal([0.0003, 0.00015, 0.00005], [0.012, 0.007, 0.00001], (2900, 3))),
        index=dates,
        columns=["A", "B", "ZERO"],
    )
    frame["ZERO"] = 0.00005
    frame.loc[dates[:200], "B"] = np.nan
    frame.iloc[210:2700:119, 0] = np.nan
    frame.iloc[251:2700:127, 1] = np.nan
    frame.loc[dates > asof] = 99.0
    funds = [
        builder.FundInput(
            id=i,
            name=i,
            kind="etf",
            source="tiingo",
            adjusted_through="2026-10-13",
            fetched_at="2026-10-13T00:00:00Z",
        )
        for i in frame
    ]
    inputs = builder.TensorInputs(
        funds=funds,
        returns=frame,
        lookback="1y",
        asof=asof,
        universe_name="Shape gate",
        nx=4,
        ny=4,
        levels=3,
        engines=("replay", "garch"),
        requested_bounds=[{"id": i, "min": 0.0, "max": 1.0} for i in frame],
    )
    expected = frame.loc[:asof].dropna(how="all").iloc[-2520:]
    captured = []
    real_fit = shape.fit_garch_t_panel

    def spy(values):
        captured.append(values.copy(deep=True))
        return real_fit(values)

    monkeypatch.setattr(shape, "fit_garch_t_panel", spy)
    results = [
        build(replace(inputs, lookback=lookback), workers=1) for lookback in ("1y", "5y", "ew")
    ]
    assert len(captured) == 3
    for actual, result in zip(captured, results, strict=True):
        pd.testing.assert_frame_equal(actual, np.log1p(expected))
        artifact = result.artifacts["garch"]
        assert artifact.sample_sha256 == _digest(expected)
        assert (
            artifact.unavailable_reason is None
            and result.tensor["engines"]["garch"]["status"] == "ready"
        )
        assert result.models["garch"].panel.shape == (2000, 252, 3)
        fit = real_fit(np.log1p(expected))
        common = fit.std_residuals[np.isfinite(fit.std_residuals).all(axis=1)]
        zero = np.all(common == 0, axis=0)
        oracle = np.zeros_like(common)
        oracle[:, ~zero] = (common[:, ~zero] - common[:, ~zero].mean(axis=0)) / common[
            :, ~zero
        ].std(axis=0, ddof=0)
        np.testing.assert_allclose(artifact.pool, oracle, atol=1e-12)
        np.testing.assert_allclose(artifact.pool[:, ~zero].mean(axis=0), 0, atol=1e-12)
        np.testing.assert_allclose(artifact.pool[:, ~zero].var(axis=0), 1, atol=1e-12)
        assert np.all(artifact.pool[:, zero] == 0)
        assert actual.isna().sum().sum() == expected.isna().sum().sum() > 0
        assert actual.index[-1] <= asof and actual.max().max() < 1
    changed = frame.copy()
    changed.iloc[-1000, 0] += 0.000123
    altered = build(replace(inputs, returns=changed), workers=1)
    assert altered.artifacts["garch"].sample_sha256 != results[0].artifacts["garch"].sample_sha256
    young = frame.copy()
    young["YOUNG"] = np.nan
    last_rows = young.loc[:asof].index[-240:]
    young.loc[last_rows, "YOUNG"] = rng.normal(0.0001, 0.009, 240)
    yf = builder.FundInput(
        id="YOUNG",
        name="Young fund",
        kind="etf",
        source="tiingo",
        adjusted_through="2026-10-13",
        fetched_at="2026-10-13T00:00:00Z",
    )
    young_inputs = replace(inputs, funds=[*funds, yf], returns=young, requested_bounds=None)
    short = build(young_inputs, workers=1)
    long = build(replace(young_inputs, lookback="5y"), workers=1)
    assert "YOUNG" in short.artifacts["garch"].funds
    assert "YOUNG" not in long.artifacts["garch"].funds
    assert short.artifacts["garch"].sample_sha256 != long.artifacts["garch"].sample_sha256
    for rows in (125, 126, 127):

        def overlap(values, rows=rows):
            fit = real_fit(values)
            residuals = fit.std_residuals.copy()
            valid = np.flatnonzero(np.isfinite(residuals).all(axis=1))
            residuals[valid[:-rows], 0] = np.nan
            return replace(fit, std_residuals=residuals)

        monkeypatch.setattr(shape, "fit_garch_t_panel", overlap)
        result = build(inputs, workers=1)
        artifact = result.artifacts["garch"]
        assert artifact.pool_rows == rows
        if rows < 126:
            assert result.tensor["engines"]["garch"]["status"] == "unavailable"
            assert (
                result.tensor["engines"]["garch"]["reason"]
                == "not enough shared history for the volatility model"
            )
            assert "garch" not in result.models
            assert "garch" not in result.tensor["ladder"]["ranges"]
            with pytest.raises(ValueError):
                shape.simulate_panel(artifact)
        else:
            assert result.tensor["engines"]["garch"]["status"] == "ready"
            assert result.models["garch"].panel.shape == (2000, 252, 3)
