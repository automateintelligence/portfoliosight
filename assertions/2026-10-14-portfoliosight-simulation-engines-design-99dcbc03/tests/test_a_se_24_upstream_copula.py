# ruff: noqa: E501
"""A-SE-24 contract (future Phase 3): real upstream vine, empirical margins, seam.

Proposed upstream interface, to be settled in QSE before implementation:
fit_copula(pool,seed,num_threads=1,truncation=5) -> object exposing vine,
pseudo_observations, active_columns, margins, controls and shock_source().
`vine` is an actual pyvinecopulib.Vinecop and controls a FitControlsVinecop;
no local/mocked substitute can satisfy source and type checks. The PortfolioSight
builder's existing BuildResult.models and QSE simulate_fhs_panel seam are observed.
The reviewed upstream attestation must be frozen at Phase 3 unpark; routine runs
never require a private checkout, credentials, or a GitHub connection.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
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


def test_a_se_24_upstream_copula():
    if not _runtime():
        return
    import hashlib
    import importlib.metadata
    import stat
    import tomllib
    from contextlib import ExitStack
    from unittest.mock import patch

    import numpy as np
    import pandas as pd
    from scipy.stats import rankdata

    copula = _module("qse.distributions.joint.copula")
    lockpath = ROOT / "qse/qse.lock.json"
    assert lockpath.exists(), "Actual upstream copula pin is required"
    lock = json.loads(lockpath.read_text())
    # Deliberately empty until the owner-approved Phase 3 upstream review. Updating
    # this literal requires a reviewed gate refreeze; self-reported qse.lock is not trust.
    approved_copula_pins = {}
    assert lock["commit"] in approved_copula_pins, (
        "No reviewed upstream copula source attestation is frozen yet"
    )
    approved = approved_copula_pins[lock["commit"]]
    assert lock["files"] == approved
    assert "qse/distributions/joint/copula.py" in approved or any(
        k.startswith("qse/distributions/joint/copula/") for k in approved
    )
    for name, digest in approved.items():
        path = ROOT / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        assert not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    actual = {str(path.relative_to(ROOT)) for path in (ROOT / "qse").rglob("*.py")}
    assert actual == set(approved), "Unattested local QSE implementation is forbidden"
    try:
        import pyvinecopulib as pv
    except ImportError as exc:
        raise AssertionError("Real pyvinecopulib dependency is required") from exc
    version = importlib.metadata.version("pyvinecopulib")
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert f"pyvinecopulib=={version}" in deps
    assert callable(getattr(copula, "fit_copula", None)), (
        "Await the reviewed upstream fit_copula API; no mock facade"
    )
    rng = np.random.default_rng(242026)
    base = rng.standard_t(5, size=1260)
    second = 0.95 * base + 0.05 * rng.normal(size=len(base))
    pool = np.column_stack([base, second, np.zeros(len(base))])
    pool[:, :2] -= pool[:, :2].mean(axis=0)
    pool[:, :2] /= pool[:, :2].std(axis=0)
    altered = pool.copy()
    altered[:, 1] = altered[rng.permutation(len(pool)), 1]
    fits = []
    draws = []
    for fixture in (pool, altered):
        fitted = copula.fit_copula(fixture, seed=20261013, num_threads=1, truncation=5)
        assert isinstance(fitted.vine, pv.Vinecop), "An empirical bootstrap is not a fitted vine"
        assert isinstance(fitted.controls, pv.FitControlsVinecop)
        assert list(fitted.active_columns) == [0, 1]
        expected = np.column_stack(
            [rankdata(fixture[:, i], method="average") / (len(fixture) + 1) for i in (0, 1)]
        )
        assert np.array_equal(fitted.pseudo_observations, expected)
        assert fitted.controls.selection_criterion == "bic" and fitted.controls.num_threads == 1
        families = {str(f).split(".")[-1].lower() for f in fitted.controls.family_set}
        assert families == {
            "gaussian",
            "student",
            "clayton",
            "gumbel",
            "frank",
            "joe",
            "bb1",
            "bb7",
        }
        assert fitted.controls.allow_rotations
        assert fitted.controls.trunc_lvl == 5
        source = fitted.shock_source()
        z = source(2000, 252, np.random.default_rng(20261013))
        assert z.shape == (2000, 252, 3) and np.all(z[:, :, 2] == 0)
        assert np.isfinite(z).all()
        # Linear empirical transforms are inspected at non-grid quantiles.
        for i in (0, 1):
            for u in (0.001, 0.073, 0.401, 0.83, 0.997):
                expected = float(np.quantile(fixture[:, i], u, method="linear"))
                assert abs(fitted.margins[i].quantile(u) - expected) < 1e-12
        assert np.array_equal(z, source(2000, 252, np.random.default_rng(20261013)))
        assert not np.array_equal(z, source(2000, 252, np.random.default_rng(20261014)))
        assert np.count_nonzero(~np.isin(z[:, :, 0].ravel()[:10000], fixture[:, 0])) > 9900, (
            "Fixed empirical rows cannot pass the continuous empirical quantile draw"
        )
        fits.append(fitted)
        draws.append(z)
    assert np.array_equal(np.sort(pool, axis=0), np.sort(altered, axis=0))
    for i in (0, 1):
        assert np.array_equal(fits[0].margins[i].values, fits[1].margins[i].values)
    assert (
        abs(
            np.corrcoef(draws[0][:, :, :2].reshape(-1, 2).T)[0, 1]
            - np.corrcoef(draws[1][:, :, :2].reshape(-1, 2).T)[0, 1]
        )
        > 0.5
    ), "Dependence changes must change the fit with identical margins"
    assert fits[0].vine.to_json() != fits[1].vine.to_json()

    builder = _module("portfoliosight.engine.builder")
    fhs = _module("qse.distributions.joint.fhs")
    ranges = _module("portfoliosight.engine.ranges")
    assert callable(getattr(builder, "build_tensor_full", None)), "Full engine builder is required"
    ids = ["VTI", "BND", "VNQ"]
    days = pd.bdate_range(end="2026-10-13", periods=1260)
    returns = pd.DataFrame(np.expm1(pool * 0.009 + 0.0001), index=days, columns=ids)
    funds = [
        builder.FundInput(i, i, "etf", "tiingo", "2026-10-13", "2026-10-13T00:00:00Z") for i in ids
    ]
    captured = []
    real = fhs.simulate_fhs_panel

    def observe(fit, n_paths, n_steps, *args, **kwargs):
        source = kwargs.get("shock_source")
        if source is not None:

            def draw(p, h, rng):
                z = source(p, h, rng)
                captured.append((fit, np.array(z, copy=True)))
                return z

            kwargs["shock_source"] = draw
        return real(fit, n_paths, n_steps, *args, **kwargs)

    # Observe aliases of this exact upstream function, including its public
    # re-export; every call still executes the genuine pinned implementation.
    with ExitStack() as stack:
        aliases = [
            module
            for name, module in tuple(sys.modules.items())
            if name.startswith(("portfoliosight", "qse"))
            and getattr(module, "simulate_fhs_panel", None) is real
        ]
        assert aliases
        for module in aliases:
            stack.enter_context(patch.object(module, "simulate_fhs_panel", observe))
        result = builder.build_tensor_full(
            builder.TensorInputs(
                funds=funds,
                returns=returns,
                lookback="1y",
                asof="2026-10-13",
                universe_name="copula-seam",
                engines=("replay", "garch", "copula"),
                nx=3,
                ny=3,
                levels=2,
            ),
            workers=1,
        )
    assert captured, "Actual engine dispatch did not consume upstream ShockSource"
    tensor = result.tensor
    model = result.models["copula"]
    assert tensor["engines"]["copula"]["status"] == "ready"
    fit, z = captured[-1]
    assert z.shape == (2000, 252, 3)
    replay = real(fit, 2000, 252, start="long_run", shock_source=lambda p, h, rng: z.copy())
    assert np.array_equal(replay, model.panel), "Copula changed the shared GARCH recursion"
    replay_model = ranges.garch_range_model(
        replay, np.array(tensor["mu_s"]), np.array(tensor["cov"])
    )
    for j, col in enumerate(tensor["ladder"]["w"]):
        answer = ranges.one_year_ranges(replay_model, np.array(col))
        for name in ("bad", "typical", "good"):
            assert np.allclose(
                answer[name], tensor["ladder"]["ranges"]["copula"][name][j], rtol=0, atol=1e-12
            )
    assert tensor["engines"]["copula"]["method"]["margins"] == "empirical"
    assert tensor["engines"]["copula"]["method"]["pyvinecopulib"] == version
