# ruff: noqa: E501
"""A-SE-25 contract: persisted build shocks, fresh service, real refusal/cache paths.

Uses existing jobs.build_from_store and TestClient(create_app), extending engine
selection as required by §7. RangeModels._panels is the two-panel LRU, distinct
from the eight lookback models. A subprocess starts with no parent fit objects.
The genuine upstream CopulaFit.shock_source factory is forbidden during reload;
this is a negative control, never a substitute dependence model.
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


def _api_probe(config):
    from unittest.mock import patch

    import numpy as np
    from fastapi.testclient import TestClient

    storemod = _module("portfoliosight.data.store")
    api_ranges = _module("portfoliosight.api.ranges")
    copula = _module("qse.distributions.joint.copula")
    api = _module("portfoliosight.api.app")
    assert hasattr(copula, "CopulaFit"), "Pinned upstream serialization/factory contract is missing"
    seen = []
    models = []

    class Store(storemod.LocalStore):
        def get(self, key):
            seen.append(key)
            return super().get(key)

    original = api_ranges.RangeModels.__init__

    def observe(self, *a, **k):
        original(self, *a, **k)
        models.append(self)

    def forbidden(*a, **k):
        raise AssertionError("Artifact-backed API must not fit or draw new copula shocks")

    responses = []
    with (
        patch.object(api_ranges.RangeModels, "__init__", observe),
        patch.object(copula, "fit_copula", forbidden),
        patch.object(copula.CopulaFit, "shock_source", forbidden),
    ):
        with TestClient(api.create_app(store=Store(config["store"]), start_worker=False)) as client:
            for index, body in enumerate(config["requests"]):
                result = client.post(
                    "/v1/range",
                    json=body,
                    headers={
                        "x-ps-gate": os.environ["PS_GATE_SECRET"],
                        "cf-connecting-ip": f"10.25.0.{index + 1}",
                    },
                )
                panels = models[0]._panels
                assert len(panels) <= 2
                snapshots = []
                for key, value in panels.items():
                    panel = value if isinstance(value, np.ndarray) else value.panel
                    assert panel.dtype == np.float32 and panel.shape[:2] == (2000, 252)
                    snapshots.append(
                        {"key": list(key), "id": id(panel), "shape": list(panel.shape)}
                    )
                responses.append(
                    {
                        "status": result.status_code,
                        "body": result.json(),
                        "panels": snapshots,
                        "reads": list(seen),
                    }
                )
    print(json.dumps(responses))


def test_a_se_25_copula_artifacts():
    if not _runtime():
        return
    import io
    from unittest.mock import patch

    import numpy as np

    _module("qse.distributions.joint.copula")
    jobs = _module("portfoliosight.jobs.build")
    engine = _module("portfoliosight.engine")
    storemod = _module("portfoliosight.data.store")
    builder = _module("portfoliosight.engine.builder")
    ranges = _module("portfoliosight.engine.ranges")
    menus = json.loads((ROOT / "data/presets.json").read_text())["presets"]
    assert {(x["id"], len(x["funds"])) for x in menus} == {("guide2017", 23), ("tsp", 5)}
    assert len(menus) == 2
    menus.append({"id": "third", "name": "Third shape", "funds": ["VTI", "BND", "VNQ"]})
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        store = _frozen_store(base / "store")
        generation = f"2026-10-13-{engine.ENGINE_VERSION}"
        storemod.put_json(
            store,
            jobs.generation_key(generation),
            {
                "generation": generation,
                "asof": "2026-10-13",
                "engine_version": engine.ENGINE_VERSION,
            },
        )
        storemod.put_json(store, "meta/current.json", {"generation": generation})
        tensors = []
        expected = []
        with patch.dict(
            os.environ,
            {"PS_ENGINES": "replay,garch,copula", "PS_ENGINES_CUSTOM": "replay,garch,copula"},
        ):
            for menu in menus:
                models = []
                real = builder.one_year_ranges

                def observe(model, w, *a, _models=models, _real=real, **kw):
                    if hasattr(model, "panel"):
                        _models.append(model)
                    return _real(model, w, *a, **kw)

                with patch.object(builder, "one_year_ranges", observe):
                    tensor = jobs.build_from_store(
                        store,
                        generation=generation,
                        funds=[{"id": i, "min": None, "max": None} for i in menu["funds"]],
                        lookback="1y",
                        cache_dir=base / "build-cache",
                        universe_name=menu["name"],
                        preset_id=menu["id"],
                        nx=3,
                        ny=3,
                        levels=2,
                    )
                assert tensor["engines"]["copula"]["status"] == "ready"
                key = f"tensors/{generation}/{tensor['universe']['hash']}/1y.json"
                storemod.put_json(store, key, tensor)
                shape = tensor["shape"]["sample_sha256"]
                artifact_key = f"models/{generation}/{shape[:16]}/copula.json"
                shock_key = f"models/{generation}/{shape[:16]}/copula_shocks.npy"
                assert store.exists(artifact_key) and store.exists(shock_key)
                z = np.load(io.BytesIO(store.get(shock_key)), allow_pickle=False)
                assert z.dtype == np.float32 and z.shape == (
                    2000,
                    252,
                    len(tensor["universe"]["funds"]),
                )
                # Store must serialize a real vine and empirical margins, not a fitted object id.
                artifact = json.loads(store.get(artifact_key))
                assert artifact["shape_sha256"] == shape and artifact["margins"]
                import pyvinecopulib as pv

                vine = pv.Vinecop.from_json(artifact["vine"])
                assert vine.dim >= 2
                tensors.append(tensor)
                # Novel unequal weights exercise artifact reconstruction outside cached levels.
                w = np.arange(1, len(z[0, 0]) + 1, dtype=float)
                w /= w.sum()
                # Capture build model by matching its own carried copula percentiles, with
                # a uniqueness check so an unrelated GARCH model cannot masquerade as it.
                matches = []
                for model in models:
                    answer = ranges.one_year_ranges(model, tensor["ladder"]["w"][1])
                    if all(
                        np.allclose(
                            answer[k],
                            tensor["ladder"]["ranges"]["copula"][k][1],
                            rtol=0,
                            atol=1e-12,
                        )
                        for k in ("bad", "typical", "good")
                    ):
                        matches.append(model)
                assert matches, "No actual build model explains its copula tensor"
                answer = ranges.one_year_ranges(matches[-1], w)
                expected.append({k: float(answer[k][0]) for k in ("bad", "typical", "good")})
            # Same shape with a different lookback and caps reuses exactly the same model key.
            old_keys = store.list(f"models/{generation}/")
            old_bytes = {k: store.get(k) for k in old_keys}
            first = menus[0]
            again = jobs.build_from_store(
                store,
                generation=generation,
                funds=[{"id": i, "min": 0, "max": 0.5} for i in first["funds"]],
                lookback="2y",
                cache_dir=base / "build-cache",
                universe_name=first["name"],
                preset_id=first["id"],
                nx=3,
                ny=3,
                levels=2,
            )
            if [f["id"] for f in again["universe"]["funds"]] == [
                f["id"] for f in tensors[0]["universe"]["funds"]
            ]:
                assert again["shape"]["sample_sha256"] == tensors[0]["shape"]["sample_sha256"]
                assert store.list(f"models/{generation}/") == old_keys
                assert all(store.get(k) == v for k, v in old_bytes.items())

        def body(t):
            n = len(t["universe"]["funds"])
            w = np.arange(1, n + 1, dtype=float)
            w /= w.sum()
            return {
                "generation": generation,
                "hash": t["universe"]["hash"],
                "lookback": "1y",
                "engine": "copula",
                "weights": w.tolist(),
            }

        requests = [body(tensors[i]) for i in (0, 0, 1, 2, 0)]
        counter = 0

        def restart(requests):
            nonlocal counter
            counter += 1
            env = {
                **os.environ,
                "PYTHONPATH": str(ROOT),
                "PS_GATE_SECRET": "gate25-secret-0123456789",
                "PS_CACHE_DIR": str(base / f"fresh-cache-{counter}"),
                "PS_ENGINES": "replay,garch,copula",
            }
            config = {"store": str(base / "store"), "requests": requests}
            code = "import json,runpy,sys;ns=runpy.run_path(sys.argv[1]);ns['_api_probe'](json.loads(sys.argv[2]))"
            result = subprocess.run(
                [sys.executable, "-c", code, str(Path(__file__).resolve()), json.dumps(config)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            return json.loads(result.stdout.strip().splitlines()[-1])

        responses = restart(requests)
        for row, i in zip(responses, (0, 0, 1, 2, 0), strict=True):
            assert row["status"] == 200 and row["body"]["engine"] == "copula"
            for metric in ("bad", "typical", "good"):
                assert abs(row["body"][metric] - expected[i][metric]) <= 5e-4
        firstkey = [tensors[0]["shape"]["sample_sha256"], "copula"]
        assert any(p["key"] == firstkey for p in responses[0]["panels"])
        assert not any(p["key"] == firstkey for p in responses[3]["panels"])
        assert any(p["key"] == firstkey for p in responses[4]["panels"])
        assert responses[0]["body"] == responses[1]["body"] == responses[4]["body"]
        assert any(k.endswith("copula_shocks.npy") for k in responses[0]["reads"])
        tensor = tensors[0]
        shock = f"models/{generation}/{tensor['shape']['sample_sha256'][:16]}/copula_shocks.npy"
        original = store.get(shock)
        store.delete(shock)
        refused = restart([requests[0]])[0]
        assert refused["status"] == 409 and refused["body"]["error"]["code"] == "range_unavailable"
        store.put(shock, original)
        key = f"tensors/{generation}/{tensor['universe']['hash']}/1y.json"
        for field in ("shape", "lookback"):
            corrupt = json.loads(json.dumps(tensor))
            corrupt[field]["sample_sha256"] = "0" * 64
            storemod.put_json(store, key, corrupt)
            refused = restart([requests[0]])[0]
            assert (
                refused["status"] == 409 and refused["body"]["error"]["code"] == "range_unavailable"
            )
            storemod.put_json(store, key, tensor)
        record = storemod.get_record(store, tensor["universe"]["funds"][0]["id"])
        record.loc[len(record) // 2, "tr_index"] *= 1.01
        storemod.put_record(store, tensor["universe"]["funds"][0]["id"], record)
        refused = restart([requests[0]])[0]
        assert refused["status"] == 409 and refused["body"]["error"]["code"] == "range_unavailable"


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
