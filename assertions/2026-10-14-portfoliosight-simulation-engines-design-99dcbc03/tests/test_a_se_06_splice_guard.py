"""A-SE-06 (property): exact strict splice boundaries through real shape construction.
Controlled residuals replace only the upstream fitter result; the production guard, pool,
artifact and outlier reporting run unchanged. A separate 30% drop uses the actual fit.
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


from dataclasses import replace


def test_a_se_06_splice_thresholds_and_retained_extremes(monkeypatch):
    if _inner():
        return
    np, pd = _need("numpy"), _need("pandas")
    shape = _need("portfoliosight.engine.shape")
    rng = np.random.default_rng(641)
    days = pd.bdate_range(end="2026-10-13", periods=700)
    base = rng.normal(0.0002, 0.006, len(days))
    frame = pd.DataFrame(
        {
            "A": base,
            "B": base + rng.normal(0, 0.001, len(days)),
            "C": base + rng.normal(0, 0.001, len(days)),
        },
        index=days,
    )
    panel = shape.shape_panel(frame, list(frame.columns), days[-1])
    actual_fit = shape.fit_garch_t_panel(np.log1p(frame))
    fit_real = shape.fit_garch_t_panel
    row, day = 400, days[400].date().isoformat()
    # Cases straddle each independent strict > 6 comparison, including exactly 6.
    cases = [
        (5.999, -1.0, False),
        (6.0, -1.0, False),
        (6.001, 0.0, True),
        (7.0, 1.001, False),
        (7.0, 1.0, False),
        (7.0, 0.999, True),
        (-7.0, -1.0, False),
        (-7.0, -0.999, True),
        (-8.0, -8.0, False),
    ]
    for own, peer, rejected in cases:
        z = actual_fit.std_residuals.copy()
        z[row] = [own, peer, peer]
        controlled = replace(actual_fit, std_residuals=z)
        monkeypatch.setattr(shape, "fit_garch_t_panel", lambda values, fit=controlled: fit)
        before = panel.frame.copy(deep=True)
        if rejected:
            with pytest.raises(shape.ShapeError) as failure:
                shape.fit_shape(panel, {"A": day})
            assert failure.value.fund == "A" and failure.value.date == day
        else:
            artifact = shape.fit_shape(panel, {"A": day})
            records = {(item["id"], item["date"]): item["z"] for item in artifact.outliers}
            if abs(own) > 6:
                assert records[("A", day)] == own
            else:
                assert ("A", day) not in records
            expected = z[np.isfinite(z).all(axis=1)]
            expected = (expected - expected.mean(axis=0)) / expected.std(axis=0, ddof=0)
            np.testing.assert_allclose(artifact.pool, expected, atol=1e-12)
        pd.testing.assert_frame_equal(panel.frame, before)
        np.testing.assert_array_equal(controlled.std_residuals, z)
    z = actual_fit.std_residuals.copy()
    z[row] = [-9.0, 0.2, -0.2]
    monkeypatch.setattr(
        shape, "fit_garch_t_panel", lambda values: replace(actual_fit, std_residuals=z)
    )
    away = shape.fit_shape(panel, {"A": days[row - 1].date().isoformat()})
    assert {"id": "A", "date": day, "z": -9.0} in away.outliers
    expected = (z - z.mean(axis=0)) / z.std(axis=0, ddof=0)
    np.testing.assert_allclose(away.pool, expected, atol=1e-12)
    assert away.pool.min() < -6, "Outliers must not be clipped or dropped before resampling"
    monkeypatch.setattr(shape, "fit_garch_t_panel", fit_real)
    broken = frame.copy()
    broken.loc[days[row], "A"] = -0.30
    with pytest.raises(shape.ShapeError) as failure:
        shape.fit_shape(shape.shape_panel(broken, list(broken), days[-1]), {"A": day})
    assert failure.value.fund == "A" and failure.value.date == day
    assert broken.loc[days[row], "A"] == -0.30
