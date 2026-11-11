"""A-SE-09 (property): actual engine dispatch absorbs simulation ruin, rejects bad history.
Controlled daily values isolate compounding boundaries; a separate real log-level pipeline
creates ruin without replacing the transform, and actual builder aggregation checks max count.
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


def test_a_se_09_ruin_absorption_and_invalid_history(monkeypatch):
    if _inner():
        return
    np, pd = _need("numpy"), _need("pandas")
    ranges, shape = (
        _need("portfoliosight.engine.ranges"),
        _need("portfoliosight.engine.shape"),
    )
    make = _attr(ranges, "garch_range_model")
    dispatch = _attr(ranges, "simulated_years")
    daily = np.full((2000, 252, 1), 0.0003)
    daily[1, 10, 0] = -1.0
    daily[2, 20, 0] = -1.2
    daily[3, [0, 2], 0] = [-1.3, -1.5]
    daily[4, 5, 0] = -1.0
    daily[4, 6:, 0] = 0.25
    original_daily = daily.copy()
    model = make(np.zeros_like(daily), np.array([0.03]), np.array([[0.04]]))
    real_levelled, real_terms = ranges._levelled, ranges._garch_terms

    def levelled(rows, step, out):
        assert len(rows) == 2000 * 252, "This isolated boundary fixture must remain full size"
        np.copyto(out, daily.reshape(-1, 1))
        return out

    monkeypatch.setattr(ranges, "_levelled", levelled)
    monkeypatch.setattr(
        ranges, "_garch_terms", lambda model, weights: (weights, np.zeros(len(weights)))
    )
    expected = np.prod(1 + daily[:, :, 0], axis=1) - 1
    lost = np.any(daily[:, :, 0] <= -1, axis=1)
    expected[lost] = -1
    actual = dispatch(model, [1.0])[:, 0]
    assert not np.any((actual < -1) | ~np.isfinite(actual)), (
        "Absorbed paths cannot compound below total loss or become nonfinite"
    )
    np.testing.assert_allclose(actual, expected, atol=1e-12)
    assert np.all(actual[[1, 2, 3, 4]] == -1.0)
    assert actual[0] > 0 and actual[5] > 0
    reported = ranges.one_year_ranges(model, [1.0])
    assert reported["ruined"].tolist() == [4], "Ruin counts paths once, not failed days"
    np.testing.assert_array_equal(daily, original_daily)
    monkeypatch.setattr(ranges, "_levelled", real_levelled)
    monkeypatch.setattr(ranges, "_garch_terms", real_terms)

    # A valid finite log panel acquires <= -100% days only at the mix-rescaling step.
    panel = np.zeros((2000, 252, 3))
    panel[:, :, 1] = np.random.default_rng(901).normal(0, 0.01, (2000, 252))
    panel[1, 4, 0] = -100000.0
    panel[2, [1, 8], 0] = -100000.0
    saved = panel.copy()
    mu, cov = np.array([0.05, 0.03, 0.02]), np.diag([0.04, 0.01, 0.0])
    actual_model = make(panel, mu, cov)
    weights = np.array([[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.8, 0.2, 0.0], [0.0, 1.0, 0.0]])
    flat = panel.reshape(-1, 3)
    m = mu / 252
    sd = flat.std(axis=0)
    constant = np.ptp(flat, axis=0) == 0
    sd[constant] = 0
    lv = np.log1p(np.diag(cov) / 252 / (1 + m) ** 2)
    a = np.divide(np.sqrt(lv), sd, out=np.zeros(3), where=sd > 0)
    fund = np.expm1(np.log1p(m) - lv / 2 + (flat - flat.mean(axis=0)) * a)
    fund[:, constant] = m[constant]
    oracle_years, counts = [], []
    for w in weights:
        y = fund @ w
        spread = y.std()
        # A constant source is the exact constant branch, not accumulated-roundoff noise.
        k = np.sqrt(w @ cov @ w / 252) / spread if np.ptp(y) > 0 else 0
        y = m @ w + k * (y - y.mean())
        y = y.reshape(2000, 252)
        ruined = (y <= -1).any(axis=1)
        values = np.prod(1 + y, axis=1) - 1
        values[ruined] = -1
        oracle_years.append(values)
        counts.append(int(ruined.sum()))
    assert counts[0] == 0 and max(counts[1:]) > 0
    actual_years = dispatch(actual_model, weights)
    assert not np.any((actual_years < -1) | ~np.isfinite(actual_years)), (
        "Real level transformation must preserve finite, total-loss-bounded years"
    )
    np.testing.assert_allclose(
        actual_years,
        np.column_stack(oracle_years),
        atol=1e-10,
        rtol=1e-10,
    )
    np.testing.assert_array_equal(ranges.one_year_ranges(actual_model, weights)["ruined"], counts)
    np.testing.assert_array_equal(panel, saved)

    builder = _need("portfoliosight.engine.builder")
    build = _attr(builder, "build_tensor_full")
    dates = pd.bdate_range(end="2026-10-13", periods=700)
    rng = np.random.default_rng(12)
    frame = pd.DataFrame(
        np.expm1(rng.normal([0.0003, 0.0002, 0.0001], [0.012, 0.006, 0.00001], (700, 3))),
        index=dates,
        columns=["RISK", "BOND", "CASH"],
    )
    frame["CASH"] = 0.0001
    inputs = builder.TensorInputs(
        funds=[
            builder.FundInput(
                id=i,
                name=i,
                kind="etf",
                source="tiingo",
                adjusted_through="2026-10-13",
                fetched_at="2026-10-13T00:00:00Z",
            )
            for i in frame
        ],
        returns=frame,
        lookback="1y",
        asof=dates[-1],
        universe_name="Ruin gate",
        nx=4,
        ny=4,
        levels=3,
        allocation={"RISK": 0.98, "BOND": 0.02, "CASH": 0.0},
        requested_bounds=[{"id": i, "min": 0.0, "max": 1.0} for i in frame],
        engines=("replay", "garch"),
    )
    consumed = []
    real_range = builder.one_year_ranges

    def capture(model, mixes):
        output = real_range(model, mixes)
        if model.engine == "garch":
            consumed.extend(int(n) for n in output["ruined"])
        return output

    monkeypatch.setattr(builder, "simulate_panel", lambda artifact: panel)
    monkeypatch.setattr(builder, "one_year_ranges", capture)
    result = build(inputs, workers=1)
    assert consumed and max(consumed) > consumed[0], (
        "Fixture must put the maximum away from the first carried mix"
    )
    assert result.tensor["engines"]["garch"]["ruin_paths"] == max(consumed)
    method = result.tensor["engines"]["garch"]["method"]
    assert {k: method[k] for k in ("returns", "scale", "ruin")} == {
        "returns": "log",
        "scale": "sd",
        "ruin": "absorb",
    }
    assert result.models["garch"].panel.shape == (2000, 252, 3)
    np.testing.assert_array_equal(result.models["garch"].panel, saved)
    for invalid in (-1.0, -1.01):
        bad = frame.copy()
        bad.iloc[100, 0] = invalid
        with pytest.raises(shape.ShapeError) as failure:
            shape.fit_shape(shape.shape_panel(bad, list(bad), dates[-1]))
        assert failure.value.fund == "RISK" and failure.value.date == dates[100].date().isoformat()
        assert bad.iloc[100, 0] == invalid
        history = np.full((300, 2), 0.02)
        history[80, 0] = invalid
        replay = ranges.range_model(history, np.array([0.0, 0.0]), np.eye(2) * 0.04)
        with pytest.raises(ValueError):
            dispatch(replay, [1.0, 0.0])
