"""A-SE-07 (property): full shared draws, independent GARCH recursion, builder and API use.
Pins build_tensor_full, simulated_years, stored artifact loading and actual /v1/range.
No draw/mix shrink: every simulation and replay index panel is 2,000 x 252.
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


def _store(tmp_path, monkeypatch):
    stores = _need("portfoliosight.data.store")
    fixture = _need("portfoliosight.jobs.fixture_store")
    version = _need("portfoliosight.engine").ENGINE_VERSION
    store = fixture.write_fixture_store(tmp_path / "store")
    asof = fixture.fixture_asof()
    generation = f"{asof.isoformat()}-{version}"
    stores.put_json(
        store,
        f"meta/{generation}/generation.json",
        {"generation": generation, "asof": asof.isoformat(), "engine_version": version},
    )
    stores.put_json(
        store,
        f"meta/{generation}/presets.json",
        {"generation": generation, "asof": asof.isoformat(), "presets": []},
    )
    stores.put_json(
        store,
        "meta/current.json",
        {"generation": generation, "published_at": "2026-10-13T09:30:00+00:00"},
    )
    monkeypatch.setenv("PS_GATE_SECRET", "frozen-gate-local-0123456789")
    monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PS_BUILD_WORKERS", "1")
    return store, asof, generation


def _api_percentiles(panel32, mu, cov, weights, np):
    """Independent §4.5 calculation after the API's mandated float32 quantization."""
    # Quantization is already accounted for; all level moments/reductions use float64.
    flat = panel32.astype(np.float64).reshape(-1, panel32.shape[-1])
    center, sd = flat.mean(axis=0), flat.std(axis=0, ddof=0)
    constant = np.ptp(flat, axis=0) == 0
    sd[constant] = 0
    daily_mean = mu / 252
    log_variance = np.log1p(np.diag(cov) / 252 / (1 + daily_mean) ** 2)
    log_mean = np.log1p(daily_mean) - log_variance / 2
    scale = np.divide(np.sqrt(log_variance), sd, out=np.zeros_like(sd), where=sd > 0)
    levelled = np.expm1(log_mean + (flat - center) * scale)
    levelled[:, constant] = daily_mean[constant]
    fund_mean = levelled.mean(axis=0)
    fund_mean[constant] = daily_mean[constant]
    centered = levelled - fund_mean
    fund_cov = centered.T @ centered / len(flat)
    fund_cov[constant, :] = 0
    fund_cov[:, constant] = 0
    quantiles = []
    for w in weights:
        spread = np.sqrt(w @ fund_cov @ w)
        k = np.sqrt(w @ cov @ w / 252) / spread if spread > 0 else 0
        daily = (daily_mean @ w + k * (levelled @ w - w @ fund_mean)).reshape(2000, 252)
        ruined = np.any(daily <= -1, axis=1)
        years = np.full(2000, -1.0)
        years[~ruined] = np.prod(1 + daily[~ruined], axis=1) - 1
        quantiles.append(np.quantile(years, [0.025, 0.5, 0.975], method="linear"))
    return np.asarray(quantiles)


def test_a_se_07_shared_long_run_draws(monkeypatch, tmp_path):
    if _inner():
        return
    np = _need("numpy")
    shape, builder = (
        _need("portfoliosight.engine.shape"),
        _need("portfoliosight.engine.builder"),
    )
    build = _attr(builder, "build_tensor_full")
    jobs, ranges = (
        _need("portfoliosight.jobs.build"),
        _need("portfoliosight.engine.ranges"),
    )
    store, asof, generation = _store(tmp_path, monkeypatch)
    inputs = jobs.inputs_from_store(
        store,
        funds=[{"id": i, "min": 0.0, "max": 1.0} for i in ("VTI", "BND", "VNQ")],
        lookback="1y",
        asof=asof,
        cache_dir=tmp_path / "cache",
        nx=4,
        ny=4,
        levels=3,
        allocation={"VTI": 0.23, "BND": 0.37, "VNQ": 0.4},
        engines=("replay", "garch"),
    )
    fitted, draws, consumed = [], [], []
    real_fit, real_simulate, real_ranges = (
        shape.fit_garch_t_panel,
        builder.simulate_panel,
        builder.one_year_ranges,
    )

    def fit(values):
        result = real_fit(values)
        fitted.append(result)
        return result

    def simulate(artifact, *args, **kwargs):
        result = real_simulate(artifact, *args, **kwargs)
        draws.append(result)
        return result

    def consume(model, weights):
        consumed.append((model, np.array(weights)))
        return real_ranges(model, weights)

    monkeypatch.setattr(shape, "fit_garch_t_panel", fit)
    monkeypatch.setattr(builder, "simulate_panel", simulate)
    monkeypatch.setattr(builder, "one_year_ranges", consume)
    result = build(inputs, workers=1)
    artifact = result.artifacts["garch"]
    assert len(fitted) == 1 and len(draws) == 1
    panel = draws[0]
    assert panel.shape == (2000, 252, 3)
    assert panel.dtype == np.dtype("float64")
    assert all(model.seed == 20261013 for model, _ in consumed)
    used = [model for model, _ in consumed if model.engine == "garch"]
    assert len(used) >= 2 and all(np.shares_memory(model.panel, panel) for model in used)
    # Whole residual rows from an independent RNG drive an independently written recursion.
    indices = np.random.default_rng(20261013).integers(0, artifact.pool_rows, (2000, 252))
    z = artifact.pool[indices]
    variance = np.broadcast_to(
        artifact.omega / (1 - artifact.alpha - artifact.beta), (2000, 3)
    ).copy()
    oracle = np.empty_like(panel)
    for day in range(252):
        epsilon = np.sqrt(variance) * z[:, day, :]
        oracle[:, day, :] = artifact.mu + epsilon
        variance = artifact.omega + artifact.alpha * epsilon**2 + artifact.beta * variance
    np.testing.assert_allclose(panel, oracle, atol=1e-13, rtol=1e-12)
    assert not np.allclose(
        fitted[0].next_variance,
        artifact.omega / (1 - artifact.alpha - artifact.beta),
        atol=1e-16,
        rtol=1e-10,
    ), "Fixture must distinguish last-state from long-run starts"
    assert not np.array_equal(shape.simulate_panel(artifact, seed=20261014), panel)
    np.testing.assert_array_equal(shape.simulate_panel(artifact), panel)
    replay = result.models["replay"]
    assert ranges.bootstrap_index(len(replay.sample)).shape == (2000, 252)
    assert replay.counts.shape == (2000, len(replay.sample))
    assert np.all(replay.counts.sum(axis=1) == 252)
    weights = np.vstack(
        [
            result.tensor["frontier"]["w"],
            np.asarray(result.tensor["ladder"]["w"]).reshape(-1, 3),
            [[0.23, 0.37, 0.4], [0.51, 0.19, 0.30]],
        ]
    )
    for model in result.models.values():
        together = ranges.simulated_years(model, weights)
        assert together.shape == (2000, len(weights))
        backward = ranges.simulated_years(model, weights[::-1])
        np.testing.assert_allclose(together, backward[:, ::-1], atol=1e-13, rtol=1e-12)
        for i in (0, 3, len(weights) - 2, len(weights) - 1):
            np.testing.assert_allclose(
                together[:, i],
                ranges.simulated_years(model, weights[i])[:, 0],
                atol=1e-13,
                rtol=1e-12,
            )
        assert not np.allclose(together[:, 0], together[:, -1])
    jobs.put_artifact(store, generation, artifact)
    tensor = result.tensor
    jobs.put_tensor(store, f"tensors/{generation}/{tensor['universe']['hash']}/1y.json", tensor)
    # §7 / decision 14: serving regenerates this draw, then caches float32 values.
    # Independently quantize the verified build draw rather than comparing API to float64.
    expected_api_panel = panel.astype(np.float32)
    expected_api_ranges = _api_percentiles(
        expected_api_panel,
        np.asarray(tensor["mu_s"], dtype=np.float64),
        np.asarray(tensor["cov"], dtype=np.float64),
        weights,
        np,
    )
    api_ranges = _need("portfoliosight.api.ranges")
    api_consumed = []
    api_real = api_ranges.one_year_ranges

    def api_spy(model, w):
        api_consumed.append(model)
        return api_real(model, w)

    monkeypatch.setattr(api_ranges, "one_year_ranges", api_spy)
    TestClient = _need("fastapi.testclient").TestClient
    make_app = _need("portfoliosight.api.app").create_app
    with TestClient(make_app(store=store, start_worker=False)) as client:
        answers = {}
        for i in (len(weights) - 1, 0, len(weights) - 2, 0, len(weights) - 1):
            response = client.post(
                "/v1/range",
                json={
                    "generation": generation,
                    "hash": tensor["universe"]["hash"],
                    "lookback": "1y",
                    "engine": "garch",
                    "weights": weights[i].tolist(),
                },
                headers={
                    "x-ps-gate": "frozen-gate-local-0123456789",
                    "cf-connecting-ip": "192.0.2.7",
                },
            )
            assert response.status_code == 200, response.text
            answer = response.json()
            assert answer["engine"] == "garch"
            # Only float64 reduction order and product-vs-log compounding roundoff remain;
            # the 1e-10 bound does not cover or hide float32 panel quantization error.
            for j, name in enumerate(("bad", "typical", "good")):
                assert answer[name] == pytest.approx(
                    float(expected_api_ranges[i, j]), abs=1e-10, rel=1e-10
                )
            if i in answers:
                assert answer == answers[i]
            answers[i] = answer
    assert len(api_consumed) == 5
    for model in api_consumed:
        assert model.panel.shape == (2000, 252, 3)
        assert model.panel.dtype == np.dtype("float32")
        np.testing.assert_array_equal(model.panel, expected_api_panel)
        assert model.panel.tobytes() == expected_api_panel.tobytes()
    assert len(draws) == 1, "Range serving must not rerun the tensor build"
