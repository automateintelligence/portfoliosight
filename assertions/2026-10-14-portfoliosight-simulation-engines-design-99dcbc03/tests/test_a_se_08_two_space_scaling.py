"""A-SE-08 (property): independent log-fund/simple-mix daily-level oracle.
Pins range-model construction, its production transformation intermediates, and public
simulated_years dispatch. All comparisons use full 2,000 x 252 paths; 1e-11 absolute
roundoff tolerance is independent of observed product output.
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


def test_a_se_08_two_space_daily_levels():
    if _inner():
        return
    np = _need("numpy")
    ranges = _need("portfoliosight.engine.ranges")
    make = _attr(ranges, "garch_range_model")
    years = _attr(ranges, "simulated_years")
    # An enumerable asymmetric five-row alphabet, with path/day phase changes and a constant fund.
    alphabet = np.array(
        [
            [-0.10, 0.015, 0.002],
            [-0.01, -0.08, 0.002],
            [0.003, 0.006, 0.002],
            [0.02, 0.035, 0.002],
            [0.16, -0.013, 0.002],
        ]
    )
    index = (np.arange(2000)[:, None] * 7 + np.arange(252)[None, :]) % len(alphabet)
    panel = alphabet[index]
    saved = panel.copy()
    weights = np.array([[1.0, 0.0, 0.0], [0.2, 0.7, 0.1], [0.61, 0.29, 0.1], [0.0, 0.0, 1.0]])
    levels = [
        (
            "1y",
            np.array([0.08, 0.03, 0.015]),
            np.array([[0.04, 0.003, 0], [0.003, 0.012, 0], [0, 0, 0]]),
        ),
        (
            "ew",
            np.array([0.04, 0.09, 0.021]),
            np.array([[0.018, -0.001, 0], [-0.001, 0.06, 0], [0, 0, 0]]),
        ),
    ]
    outputs = []
    for lookback, mu, cov in levels:
        flat = panel.reshape(-1, 3)
        center, sd = flat.mean(axis=0), flat.std(axis=0, ddof=0)
        constant = np.ptp(flat, axis=0) == 0
        sd[constant] = 0
        m = mu / 252
        target_var = np.log1p(np.diag(cov) / 252 / (1 + m) ** 2)
        target_mean = np.log1p(m) - target_var / 2
        a = np.divide(np.sqrt(target_var), sd, out=np.zeros(3), where=sd > 0)
        fund = np.expm1(target_mean + (flat - center) * a)
        fund[:, constant] = m[constant]
        fund_mean = fund.mean(axis=0)
        fund_mean[constant] = m[constant]
        centered = fund - fund_mean
        fund_cov = centered.T @ centered / len(flat)
        fund_cov[constant, :] = 0
        fund_cov[:, constant] = 0
        daily = []
        scales = []
        for w in weights:
            mix = fund @ w
            spread = np.sqrt(w @ fund_cov @ w)
            k = np.sqrt(w @ cov @ w / 252) / spread if spread > 0 else 0
            scales.append(k)
            daily.append(m @ w + k * (mix - w @ fund_mean))
        expected = np.column_stack(daily).reshape(2000, 252, -1)
        assert abs(scales[1] - 1) > 0.01, "Fixture must discriminate mix rescaling"
        assert np.max(np.abs(fund_mean[:2] - m[:2])) > 1e-9, (
            "Fixture must distinguish obsolete centering"
        )
        model = make(panel, mu, cov)
        np.testing.assert_allclose(model.level_mean, fund_mean, atol=1e-12, rtol=1e-10)
        np.testing.assert_allclose(model.level_cov, fund_cov, atol=1e-12, rtol=1e-10)
        step = _attr(ranges, "_step_one")(model.mu_s, model.cov, model.mean, model.sd)
        actual_funds = _attr(ranges, "_levelled")(flat, step, np.empty_like(flat))
        coefficients, intercept = _attr(ranges, "_garch_terms")(model, weights)
        actual_daily = (actual_funds @ coefficients.T + intercept).reshape(expected.shape)
        np.testing.assert_allclose(actual_daily, expected, atol=1e-11, rtol=1e-10)
        np.testing.assert_allclose(actual_daily.mean(axis=(0, 1)), weights @ mu / 252, atol=1e-11)
        np.testing.assert_allclose(
            actual_daily.std(axis=(0, 1)),
            np.sqrt(np.einsum("ij,jk,ik->i", weights, cov, weights) / 252),
            atol=1e-11,
        )
        expected_years = np.prod(1 + expected, axis=1) - 1
        np.testing.assert_allclose(years(model, weights), expected_years, atol=1e-10, rtol=1e-10)
        outputs.append(actual_daily)
        raw_mix = flat @ weights[1]
        obsolete = (
            mu @ weights[1] / 252
            + (raw_mix - raw_mix.mean())
            * np.sqrt(weights[1] @ cov @ weights[1] / 252)
            / raw_mix.std()
        )
        assert not np.allclose(expected[:, :, 1].ravel(), obsolete, atol=1e-8), (
            "One-step raw scaling is not the two-space rule"
        )
        np.testing.assert_array_equal(panel, saved)
    assert not np.array_equal(outputs[0], outputs[1]), (
        "Changing lookback targets must change daily levels"
    )
    constant_panel = np.full((2000, 252, 3), 0.002)
    mu, cov = levels[0][1:]
    constant_model = make(constant_panel, mu, cov)
    np.testing.assert_allclose(
        years(constant_model, weights),
        np.tile((1 + weights @ mu / 252) ** 252 - 1, (2000, 1)),
        atol=1e-11,
    )
