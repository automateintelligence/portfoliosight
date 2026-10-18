# ruff: noqa: E501
"""A-SE-19 property: independent attribution on actual shared engine paths.

Pins engine.loss_sources.loss_sources(model,weights,fund_ids,alpha=.05)->{n_eff,top,hedges}
for a vector, beside existing one_year_ranges. GARCH models use the feature's
existing garch_range_model(log_panel,mu,cov,seed) interface. No tied ruined tails
are tested: their attribution/tie semantics remain deliberately unresolved.
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


def test_a_se_19_enlc_attribution():
    if not _runtime():
        return
    import math
    from unittest.mock import patch

    import numpy as np
    from fastapi.testclient import TestClient

    ranges = _module("portfoliosight.engine.ranges")
    loss_module = _module("portfoliosight.engine.loss_sources")
    assert callable(getattr(loss_module, "loss_sources", None)), (
        "Phase 2 loss_sources(model,weights,fund_ids,alpha) is not implemented"
    )
    assert callable(getattr(ranges, "garch_range_model", None)), (
        "The real log-panel range model is required"
    )
    ids = ["loser-a", "loser-b", "loser-c", "loser-d", "hedge", "unheld"]
    rng = np.random.default_rng(192026)
    mu = np.array([-0.06, -0.08, -0.04, -0.09, 0.20, 0.02])
    cov = np.diag(np.array([0.13, 0.19, 0.10, 0.17, 0.005, 0.3]) ** 2)
    raw = rng.normal(size=(2000, 252, 6)) * 0.014
    # Finite non-Gaussian marginals deliberately make Rbar' differ from m.
    raw[:, :, 1] += rng.exponential(0.02, (2000, 252))
    raw[:, :, 3] += rng.exponential(0.03, (2000, 252))
    sample = rng.normal(size=(756, 6)) * 0.01
    sample[:, 4] = 0.20 / 252
    sample[:, 0] -= 0.0003

    def oracle(model, w, fund_ids, alpha=0.05):
        w = np.asarray(w)
        m = np.asarray(model.mu_s) / 252
        if hasattr(model, "panel"):
            logs = np.asarray(model.panel, dtype=float)
            assert logs.shape[:2] == (2000, 252)
            mean = logs.mean(axis=(0, 1))
            sd = logs.std(axis=(0, 1), ddof=0)
            s = np.sqrt(np.diag(model.cov) / 252)
            lv = np.log1p(s * s / (1 + m) ** 2)
            lm = np.log1p(m) - lv / 2
            scaled = np.empty_like(logs)
            varying = sd > 1e-12
            scaled[:, :, varying] = np.expm1(
                lm[varying]
                + (logs[:, :, varying] - mean[varying]) * np.sqrt(lv[varying]) / sd[varying]
            )
            scaled[:, :, ~varying] = m[~varying]
            mean_r = scaled.mean(axis=(0, 1))
            daily = scaled @ w
            observed = daily.std(ddof=0)
            k = math.sqrt(w @ np.asarray(model.cov) @ w / 252) / observed if observed > 1e-12 else 0
            mix = m @ w + k * (daily - mean_r @ w)
            contribution = w * (252 * m + k * (scaled.sum(axis=1) - 252 * mean_r))
        else:
            values = np.asarray(model.sample)
            count = np.asarray(model.counts)
            assert count.shape == (2000, len(values)) and np.all(count.sum(axis=1) == 252)
            centered = values - values.mean(axis=0) + m
            mix_days = centered @ w
            assert np.all(mix_days > -1)
            years = np.expm1(count @ np.log1p(mix_days))
            contribution = (count @ centered) * w
            additive = count @ mix_days
            assert np.allclose(contribution.sum(axis=1), additive, atol=1e-12, rtol=1e-12)
            mix = None
        if mix is not None:
            assert np.all(mix > -1), "Fixture unintentionally introduced unresolved ruined tails"
            years = np.expm1(np.log1p(mix).sum(axis=1))
            assert np.allclose(contribution.sum(axis=1), mix.sum(axis=1), atol=1e-12, rtol=1e-12)
        tail = np.argsort(years, kind="stable")[: math.ceil(alpha * len(years))]
        loss = -contribution[tail].mean(axis=0)
        positive = np.maximum(loss, 0)
        shares = positive / positive.sum() if positive.sum() > 0 else np.zeros(len(w))
        nonzero = shares > 0
        neff = (
            float(np.exp(-np.sum(shares[nonzero] * np.log(shares[nonzero]))))
            if nonzero.any()
            else None
        )
        return {
            "n_eff": neff,
            "shares": dict(zip(fund_ids, shares, strict=True)),
            "hedges": [i for i, level in zip(fund_ids, loss, strict=True) if level < 0],
            "tail": tail,
            "years": years,
            "additive": contribution.sum(axis=1),
            "positive": int(nonzero.sum()),
            "center_error": float(np.max(np.abs(mean_r - m))) if hasattr(model, "panel") else 0.0,
        }

    def compare(block, expected, w, atol=2e-9):
        assert set(block) >= {"n_eff", "top", "hedges"}
        if expected["n_eff"] is None:
            assert block["n_eff"] is None and block["top"] == []
        else:
            assert abs(block["n_eff"] - expected["n_eff"]) <= atol
            assert 1 - 1e-10 <= block["n_eff"] <= expected["positive"] + 1e-9
            assert block["n_eff"] <= np.count_nonzero(np.asarray(w) > 1e-6) + 1e-9
            wanted = sorted(
                [(i, s) for i, s in expected["shares"].items() if s > 0], key=lambda item: -item[1]
            )[:3]
            assert len(block["top"]) == len(wanted)
            for actual, (fund, share) in zip(block["top"], wanted, strict=True):
                assert actual["id"] == fund and abs(actual["share"] - share) <= atol
        assert set(block["hedges"]) == set(expected["hedges"])
        assert all(expected["shares"][i] == 0 for i in block["hedges"])

    models = [ranges.range_model(sample, mu, cov), ranges.garch_range_model(raw, mu, cov)]
    rankings_differ = False
    centering_matters = False
    outcomes = []
    for model in models:
        for w in (
            np.array([0.2, 0.2, 0.2, 0.2, 0.2, 0]),
            np.array([0.4, 0.15, 0.1, 0.1, 0.25, 0]),
            *np.eye(6),
        ):
            expected = oracle(model, w, ids)
            centering_matters |= expected["center_error"] > 1e-10
            actual = loss_module.loss_sources(model, w, fund_ids=ids, alpha=0.05)
            compare(actual, expected, w)
            outcomes.append(actual)
            if np.count_nonzero(w) == 1 and expected["n_eff"] is not None:
                assert actual["n_eff"] == 1
            if w[-1] == 0:
                assert expected["shares"][ids[-1]] == 0 and ids[-1] not in actual["hedges"]
            rankings_differ |= not np.array_equal(
                expected["tail"], np.argsort(expected["additive"])[:100]
            )
        no_loss = ranges.range_model(np.full((252, 6), 0.001), np.full(6, 0.252), np.zeros((6, 6)))
        compare(
            loss_module.loss_sources(no_loss, np.eye(6)[0], fund_ids=ids, alpha=0.05),
            oracle(no_loss, np.eye(6)[0], ids),
            np.eye(6)[0],
        )
    assert rankings_differ, (
        "Fixture must distinguish compounded tail ordering from additive ordering"
    )
    assert len({json.dumps(x, sort_keys=True) for x in outcomes}) > 8, (
        "A fixed loss-sources block cannot pass"
    )
    assert centering_matters, "Fixture must distinguish Rbar-prime from target m"

    # Production builder and real HTTP dispatch must use those same models and weights.
    builder = _module("portfoliosight.engine.builder")
    jobs = _module("portfoliosight.jobs.build")
    engine = _module("portfoliosight.engine")
    api = _module("portfoliosight.api.app")
    presets = json.loads((ROOT / "data/presets.json").read_text())["presets"]
    assert {(x["id"], len(x["funds"])) for x in presets} == {("guide2017", 23), ("tsp", 5)}
    assert len(presets) == 2
    integration_builds = 0
    integration_requests = 0
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        with patch.dict(
            os.environ,
            {
                "PS_ENGINES": "replay,garch",
                "PS_ENGINES_CUSTOM": "replay,garch",
                "PS_GATE_SECRET": "gate-19-secret-0123456789",
                "PS_CACHE_DIR": str(base / "cache"),
            },
        ):
            store = _frozen_store(base / "store")
            generation = f"2026-10-13-{engine.ENGINE_VERSION}"
            store.put(
                jobs.generation_key(generation),
                json.dumps(
                    {
                        "generation": generation,
                        "asof": "2026-10-13",
                        "engine_version": engine.ENGINE_VERSION,
                    }
                ).encode(),
            )
            store.put("meta/current.json", json.dumps({"generation": generation}).encode())
            for preset in presets:
                captured = {}
                real = builder.one_year_ranges

                def observe(model, weights, *args, _captured=captured, _real=real, **kwargs):
                    _captured["garch" if hasattr(model, "panel") else "replay"] = model
                    return _real(model, weights, *args, **kwargs)

                with patch.object(builder, "one_year_ranges", observe):
                    tensor = jobs.build_from_store(
                        store,
                        generation=generation,
                        funds=[{"id": i, "min": None, "max": None} for i in preset["funds"]],
                        lookback="1y",
                        cache_dir=base / "cache",
                        universe_name=preset["name"],
                        preset_id=preset["id"],
                        allocation={i: 1 for i in preset["funds"]},
                        nx=3,
                        ny=3,
                        levels=2,
                    )
                integration_builds += 1
                key = f"tensors/{generation}/{tensor['universe']['hash']}/1y.json"
                store.put(key, json.dumps(tensor).encode())
                fund_ids = [x["id"] for x in tensor["universe"]["funds"]]
                assert set(captured) == {"replay", "garch"}, (
                    "Builder did not execute both real engines"
                )
                with TestClient(api.create_app(store=store, start_worker=False)) as client:
                    for engine_id, model in captured.items():
                        for j, col in enumerate(tensor["ladder"]["w"]):
                            for level, w in enumerate(col):
                                expected = oracle(model, w, fund_ids)
                                stored = {
                                    k: tensor["ladder"]["loss_sources"][engine_id][k][j][level]
                                    for k in ("n_eff", "top", "hedges")
                                }
                                compare(stored, expected, w)
                        compare(
                            tensor["entered"]["loss_sources"][engine_id],
                            oracle(model, tensor["entered"]["w"], fund_ids),
                            tensor["entered"]["w"],
                        )
                        for w in (
                            np.full(len(fund_ids), 1 / len(fund_ids)),
                            np.arange(1, len(fund_ids) + 1) / sum(range(1, len(fund_ids) + 1)),
                            np.eye(len(fund_ids))[0],
                        ):
                            response = client.post(
                                "/v1/range",
                                json={
                                    "generation": generation,
                                    "hash": tensor["universe"]["hash"],
                                    "lookback": "1y",
                                    "weights": w.tolist(),
                                    "engine": engine_id,
                                },
                                headers={
                                    "x-ps-gate": "gate-19-secret-0123456789",
                                    "cf-connecting-ip": f"10.19.{len(fund_ids)}.{len(outcomes)}",
                                },
                            )
                            integration_requests += 1
                            assert response.status_code == 200, response.text
                            body = response.json()
                            assert body["engine"] == engine_id
                            compare(body["loss_sources"], oracle(model, w, fund_ids), w, atol=3e-5)
                            outcomes.append(body)

    assert integration_builds == 2 and integration_requests == 12


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
