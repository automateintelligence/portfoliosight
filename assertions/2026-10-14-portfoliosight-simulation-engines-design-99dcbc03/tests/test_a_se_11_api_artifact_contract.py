# ruff: noqa: E501 -- embedded runtime programs retain their native source layout.
"""A-SE-11: public engine dispatch, artifact refusal, persistence and cache contract.
Numerical API tolerance 3e-5 absolute / 3e-4 relative covers only documented float32
panel storage; expected values are independently compounded float64 build draws.
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


def _fixture_store(directory):
    """Frozen nontrivial returns and canonical records; no mutable fixture helper."""
    np, pd = _product("numpy"), _product("pandas")
    sm = _product("portfoliosight.data.store")
    manifest_mod = _product("portfoliosight.data.manifest")
    store = sm.LocalStore(directory)
    ids = [
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
        "TSP-G",
        "TSP-F",
        "TSP-C",
        "TSP-S",
        "TSP-I",
        "SGOV",
    ]
    days = pd.bdate_range("2005-01-03", "2026-10-12", name="date")
    rng = np.random.default_rng(20261013)
    factors = rng.normal(size=(len(days), 3))
    manifest = manifest_mod.Manifest()
    for j, fid in enumerate(ids):
        if fid in ("TSP-G", "SGOV"):
            returns = np.full(len(days), 0.035 / 252)
        else:
            # Correlated funds with distinct level, volatility, idiosyncratic noise and tails.
            vol = 0.035 + 0.007 * (j % 19)
            loading = np.array([0.65, 0.2 * ((j % 3) - 1), 0.15])
            returns = (0.025 + 0.002 * (j % 13)) / 252 + (
                factors @ loading + rng.standard_t(7, len(days)) * 0.45
            ) * vol / np.sqrt(252)
        active = days >= (pd.Timestamp("2020-05-28") if fid == "SGOV" else days[0])
        calendar, daily = days[active], returns[active]
        growth = np.r_[1.0, np.cumprod(1 + daily)]
        stamps = pd.DatetimeIndex([calendar[0] - pd.offsets.BDay(1)]).append(calendar)
        record = pd.DataFrame(
            {
                "date": stamps,
                "close": growth * 100,
                "tr_index": growth,
                "div_cash": np.zeros(len(stamps)),
                "split_factor": np.ones(len(stamps)),
            }
        )
        sm.put_record(store, fid, record)
        manifest.symbols[fid] = manifest_mod.ManifestEntry(
            name="Frozen " + fid,
            kind="tsp" if fid.startswith("TSP-") else "etf",
            tier=1,
            source="tsp" if fid.startswith("TSP-") else "seed",
            status="ok",
            first_date=stamps[0].date(),
            last_date=stamps[-1].date(),
            adjusted_through=stamps[-1].date(),
            fetched_at="2026-10-13T09:05:11Z",
        )
    sm.put_json(store, "meta/manifest.json", manifest.to_json())
    return store


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


def _vitest(tmp_path, source):
    """Compile frozen embedded TS against runroot product; use installed tools only."""
    roots = [ROOT]
    if (ROOT / ".git").is_file():
        roots.append(Path((ROOT / ".git").read_text().split(":", 1)[1].strip()).parents[2])
    modules = next(
        (r / "web/node_modules" for r in roots if (r / "web/node_modules/.bin/vitest").exists()),
        None,
    )
    if modules is None:
        pytest.fail("Local vitest/jsdom prerequisite is missing; no install/network fallback")
    package = json.loads((ROOT / "web/package.json").read_text())
    aliases = {
        name: str(modules / name)
        for name in {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        if (modules / name).exists()
    }
    # NODE/PS_GATE_NODE and PATH work on a normal clone; nvm is optional discovery only.
    import re
    import shutil

    configured = os.environ.get("PS_GATE_NODE") or os.environ.get("NODE")
    candidates = [Path(configured)] if configured else []
    located = shutil.which("node")
    if located:
        candidates.append(Path(located))
    candidates.extend((Path.home() / ".nvm/versions/node").glob("*/bin/node"))

    def supports(version, expression):
        for alternative in expression.split("||"):
            ok = True
            for token in alternative.split():
                match = re.fullmatch(r"(>=|<=|>|<|\^|~|=)?(\d+)(?:\.(\d+))?(?:\.(\d+))?", token)
                if not match:
                    ok = False
                    break
                op, major, minor, patch = match.groups()
                bound = (int(major), int(minor or 0), int(patch or 0))
                check = {
                    ">=": version >= bound,
                    "<=": version <= bound,
                    ">": version > bound,
                    "<": version < bound,
                    "^": bound <= version < (bound[0] + 1, 0, 0),
                    "~": bound <= version < (bound[0], bound[1] + 1, 0),
                    "=": version == bound,
                    None: version == bound,
                }[op]
                ok = ok and check
            if ok:
                return True
        return False

    compatible = []
    requirements = [
        json.loads((modules / pkg / "package.json").read_text())
        .get("engines", {})
        .get("node", ">=0.0.0")
        for pkg in ("vite", "vitest", "jsdom")
    ]
    for candidate in dict.fromkeys(candidates):
        try:
            result = subprocess.run(
                [str(candidate), "-p", "process.versions.node"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = tuple(int(n) for n in result.stdout.strip().split("."))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and all(
            supports(version, requirement) for requirement in requirements
        ):
            compatible.append((version, candidate))
    if not compatible:
        pytest.fail(
            "Compatible installed Node prerequisite missing; required: " + "; ".join(requirements)
        )
    node = max(compatible, key=lambda item: item[0])[1]
    source = source.replace("@RUNROOT@", str(ROOT))
    test = tmp_path / "assertion.test.tsx"
    test.write_text(source)
    config = tmp_path / "vitest.config.mjs"
    config.write_text(
        "export default "
        + json.dumps(
            {
                "root": str(ROOT / "web"),
                "resolve": {"alias": aliases},
                "esbuild": {"jsx": "automatic"},
                "test": {
                    "include": [str(test)],
                    "environment": "jsdom",
                    "testTimeout": 120000,
                    "hookTimeout": 10000,
                    "pool": "forks",
                    "maxWorkers": 1,
                    "minWorkers": 1,
                },
            }
        )
    )
    try:
        result = subprocess.run(
            [str(node), str(modules / "vitest/vitest.mjs"), "run", "--config", str(config)],
            cwd=ROOT / "web",
            capture_output=True,
            text=True,
            timeout=180,
            env={
                **os.environ,
                "CI": "1",
                "NO_COLOR": "1",
                "PATH": str(node.parent) + os.pathsep + os.environ.get("PATH", ""),
            },
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Application runtime gate exceeded 180 seconds")
    assert result.returncode == 0, result.stdout[-14000:] + result.stderr[-6000:]


WORKER_SOURCE = r"""import { it, expect, vi } from 'vitest';
import Worker from '@RUNROOT@/web/worker/index';
it('Worker forwards engine, arbitrary weights, status and body unchanged', async () => {
    for (const engine of [undefined, 'replay', 'garch', 'bogus'])
        for (const status of [200, 409, 422]) {
            const body = { generation: '2026-10-12-0.3.0', hash: '0123456789abcdef', lookback: '1y', weights: [.13, .27, .6], ...(engine ? { engine } : {}) };
            let calls: any[] = [];
            const answer = status === 200 ? { engine: engine ?? 'replay', bad: -.12, typical: .04, good: .22, loss_sources: null } : { error: { code: status === 409 ? 'range_unavailable' : 'invalid_request' } };
            vi.stubGlobal('fetch', async (input: any, init: any) => { calls.push({ url: String(input), body: JSON.parse(new TextDecoder().decode(init.body)) }); return new Response(JSON.stringify(answer), { status, headers: { 'content-type': 'application/json' } }); });
            const response = await Worker.fetch(new Request('https://portfoliosight.ai/api/range', { method: 'POST', headers: { origin: 'https://portfoliosight.ai', 'content-type': 'application/json' }, body: JSON.stringify(body) }), { PS_PRIVATE_PREVIEW: '0', PS_GATE_SECRET: 'inert-local-gate-secret', API_ORIGIN: 'https://origin.invalid', ASSETS: { fetch: async () => { throw Error('asset bypass'); } } } as any, {} as any);
            expect(response.status).toBe(status);
            expect(await response.json()).toEqual(answer);
            expect(calls).toEqual([{ url: 'https://origin.invalid/v1/range', body }]);
        }
    vi.unstubAllGlobals();
});
"""


def test_a_se_11_api_engine_selection_and_artifact_refusals(tmp_path, monkeypatch):
    if not _runtime():
        return
    np, pd = _product("numpy"), _product("pandas")
    mod = _product("portfoliosight.data.store")
    jobs = _product("portfoliosight.jobs.build")
    builder = _product("portfoliosight.engine.builder")
    _product("portfoliosight.engine.builder", "build_tensor_full")
    appmod = _product("portfoliosight.api.app")
    Client = _product("fastapi.testclient", "TestClient")
    version = _product("portfoliosight.engine").ENGINE_VERSION
    store = _fixture_store(tmp_path / "store")
    generation = "2026-10-12-" + version
    mod.put_json(
        store,
        jobs.generation_key(generation),
        {"generation": generation, "asof": "2026-10-12", "engine_version": version},
    )
    mod.put_json(store, "meta/current.json", {"generation": generation})
    for key, value in {
        "PS_GATE_SECRET": "frozen-local-gate-secret-12345",
        "PS_ENGINES": "replay,garch",
        "PS_ENGINES_CUSTOM": "replay,garch",
        "PS_GRID_NX": "4",
        "PS_GRID_NY": "3",
        "PS_GRID_LEVELS": "2",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path / "cache"))
    # Count the actual fit boundary, regardless of direct import at builder/store seam.
    fit = _product("portfoliosight.engine.shape", "fit_shape")
    fit_calls = []

    def counted(*args, **kwargs):
        fit_calls.append(args[0].sample_sha256)
        return fit(*args, **kwargs)

    for module in (builder, jobs):
        if getattr(module, "fit_shape", None) is fit:
            monkeypatch.setattr(module, "fit_shape", counted)
    monkeypatch.setattr(_product("portfoliosight.engine.shape"), "fit_shape", counted)
    tensors = []

    def stored_build(ids, lb="1y", cap=None):
        policy = [{"id": fid, "min": None, "max": cap} for fid in ids]
        t = jobs.build_from_store(
            store,
            generation=generation,
            funds=policy,
            lookback=lb,
            cache_dir=tmp_path / "build-cache",
            nx=4,
            ny=3,
            levels=2,
        )
        key = f"tensors/{generation}/{t['universe']['hash']}/{lb}.json"
        jobs.put_tensor(store, key, t)
        tensors.append((t, key))
        assert (
            t.get("range_default") == "replay"
            and t.get("engines", {}).get("garch", {}).get("status") == "ready"
        ), "Built tensor does not carry both engines"
        return t, key

    first, first_key = stored_build(["VTI", "BND", "VNQ"])
    artifacts_before = {k: store.get(k) for k in store.list(f"models/{generation}/")}
    assert len(artifacts_before) >= 2
    stored_build(["VTI", "BND", "VNQ"], "2y")
    stored_build(["VTI", "BND", "VNQ"], "1y", 0.7)
    assert len(fit_calls) == 1, "Lookback/cap policy must reuse the same shape fit"
    assert {k: store.get(k) for k in artifacts_before} == artifacts_before, (
        "Artifacts mutated after reuse"
    )
    second, _ = stored_build(["VTI", "BND"])
    third, _ = stored_build(["VTV", "BND"])
    assert len(fit_calls) == 3
    headers = {"x-ps-gate": "frozen-local-gate-secret-12345"}
    serial = 0

    def post(t, weights, engine="garch"):
        nonlocal serial
        serial += 1
        monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path / f"request-cache-{serial}"))
        body = {
            "generation": t["generation"],
            "hash": t["universe"]["hash"],
            "lookback": t["lookback"]["id"],
            "weights": weights,
        }
        if engine is not None:
            body["engine"] = engine
        with Client(
            appmod.create_app(store=store, start_worker=False), raise_server_exceptions=False
        ) as client:
            response = client.post("/v1/range", json=body, headers=headers)
            health = client.get("/v1/health", headers=headers)
            assert set(health.json()["engines"]) == {"replay", "garch"}
        return response

    # Obtain the exact persisted artifact, re-simulate its consumed draw and independently compound.
    shape = _product("portfoliosight.engine.shape")
    art_key = f"models/{generation}/{first['shape']['sample_sha256'][:16]}/garch.json"
    pool_key = art_key.rsplit("/", 1)[0] + "/pool.npy"
    artifact = shape.artifact_from_json(
        json.loads(store.get(art_key)), shape.pool_from_bytes(store.get(pool_key))
    )
    ranges = _product("portfoliosight.engine.ranges")
    panel = shape.simulate_panel(artifact)
    gmodel = ranges.garch_range_model(panel, first["mu_s"], first["cov"])
    ids = [x["id"] for x in first["universe"]["funds"]]
    series = {
        fid: mod.get_record(store, fid).set_index("date")["tr_index"].pct_change() for fid in ids
    }
    frame = pd.DataFrame(series).loc[first["lookback"]["start"] : first["lookback"]["end"]].dropna()
    replay = ranges.range_model(frame.to_numpy(), first["mu_s"], first["cov"])
    seen = {}
    for weights in ([0.13, 0.27, 0.6], [0.61, 0.07, 0.32], [0.02, 0.93, 0.05]):
        for engine, model in (("replay", replay), ("garch", gmodel)):
            response = post(first, weights, engine)
            assert response.status_code == 200, response.text
            answer = response.json()
            mix = np.asarray(weights)
            mu = float(mix @ np.asarray(first["mu_s"]))
            sigma = float(np.sqrt(mix @ np.asarray(first["cov"]) @ mix))
            for key, value in (
                ("low", mu - 1.96 * sigma),
                ("mid", mu),
                ("high", mu + 1.96 * sigma),
            ):
                assert answer["normal"][key] == pytest.approx(value, abs=1e-12)
            assert answer["engine"] == engine
            if not first["ladder"].get("loss_sources"):
                assert answer["loss_sources"] is None
            expected = np.percentile(_years(model, weights), [2.5, 50, 97.5], method="linear")
            np.testing.assert_allclose(
                [answer[k] for k in ("bad", "typical", "good")], expected, atol=3e-5, rtol=3e-4
            )
            assert post(first, weights, engine).json() == answer, (
                "Restart does not reproduce persisted model"
            )
            seen[engine, tuple(weights)] = answer
    assert seen["garch", (0.13, 0.27, 0.6)] != seen["replay", (0.13, 0.27, 0.6)]
    assert seen["garch", (0.13, 0.27, 0.6)] != seen["garch", (0.61, 0.07, 0.32)]
    assert (
        post(first, [0.13, 0.27, 0.6], None).json()
        == post(first, [0.13, 0.27, 0.6], "replay").json()
    )
    assert post(first, [0.13, 0.27, 0.6], "typo").status_code == 422

    def refused(response):
        assert response.status_code == 409, response.text
        data = response.json()
        assert data["error"]["code"] == "range_unavailable"
        assert all(k not in data for k in ("bad", "typical", "good", "normal"))

    refused(post(first, [0.13, 0.27, 0.6], "copula"))
    for key in (art_key, pool_key):
        saved = store.get(key)
        store.delete(key)
        refused(post(first, [0.13, 0.27, 0.6]))
        store.put(key, saved)
    for field in ("shape", "lookback"):
        t = json.loads(store.get(first_key))
        t[field]["sample_sha256"] = "0" * 64
        store.put(first_key, json.dumps(t).encode())
        refused(post(first, [0.13, 0.27, 0.6]))
        store.put(first_key, builder.canonical_json(first).encode())
    # Modify a shape-only old price, then a lookback price. Both must refuse fresh loads.
    for date in (first["shape"]["start"], first["lookback"]["start"]):
        record = mod.get_record(store, "VTI")
        saved = record.copy(deep=True)
        index = record.index[record["date"] >= pd.Timestamp(date)][2]
        record.loc[index, "tr_index"] *= 1.01
        mod.put_record(store, "VTI", record)
        refused(post(first, [0.13, 0.27, 0.6]))
        mod.put_record(store, "VTI", saved)
    # Drive the cache itself and inspect the actual retained numpy panels, not claimed counts.
    manager = _product("portfoliosight.api.ranges", "RangeModels")(store)
    assert _product("portfoliosight.api.ranges").MODELS_KEPT == 8

    def get(t):
        try:
            return manager.get(
                t["generation"], t["universe"]["hash"], t["lookback"]["id"], engine="garch"
            )
        except TypeError as exc:
            pytest.fail(f"Engine-aware cache lookup required: {exc}")

    get(first)
    get(second)
    get(first)
    get(third)

    def arrays(value, visited=None):
        visited = set() if visited is None else visited
        if id(value) in visited:
            return []
        visited.add(id(value))
        if isinstance(value, np.ndarray):
            return [value] if value.ndim == 3 else []
        if isinstance(value, dict):
            return sum((arrays(v, visited) for v in value.values()), [])
        if isinstance(value, (tuple, list)):
            return sum((arrays(v, visited) for v in value), [])
        if value.__class__.__module__.startswith("portfoliosight"):
            return (
                sum((arrays(v, visited) for v in vars(value).values()), [])
                if hasattr(value, "__dict__")
                else []
            )
        return []

    # The separate lookback cache is exercised beyond capacity; a constant alone proves nothing.
    cache_tensors = []
    for cap in (0.51, 0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.58, 0.59):
        t, _ = stored_build(["VTI", "BND", "VNQ"], "1y", cap)
        cache_tensors.append(t)
        manager.get(t["generation"], t["universe"]["hash"], "1y", engine="replay")
    if not hasattr(manager, "_models"):
        pytest.fail("Pinned lookback cache interface RangeModels._models is absent")
    assert len(manager._models) == 8, "Lookback model cache failed to evict after its eighth key"
    kept = arrays(manager)
    assert 0 < len(kept) <= 2 and all(
        a.dtype == np.float32 and a.shape[:2] == (2000, 252) for a in kept
    )
    # Reaccessing the LRU victim must re-simulate, not find a third retained panel.
    simulations = []
    actual_simulate = shape.simulate_panel

    def simulated(*a, **kw):
        simulations.append(True)
        return actual_simulate(*a, **kw)

    for module in (jobs, _product("portfoliosight.api.ranges"), shape):
        if getattr(module, "simulate_panel", None) is actual_simulate:
            monkeypatch.setattr(module, "simulate_panel", simulated)
    get(second)
    assert simulations, "Least-recently-used shape was not evicted"
    # Expired generation model artifacts follow the same real pruning boundary as tensors.
    old, pinned = "2020-01-01-" + version, "2021-01-01-" + version
    for gen in (old, pinned):
        mod.put_json(
            store,
            f"meta/{gen}/generation.json",
            {"generation": gen, "asof": gen[:10], "engine_version": version},
        )
        for key, value in artifacts_before.items():
            store.put(key.replace(generation, gen), value)
    mod.put_json(store, "meta/pinned.json", {"generations": [pinned]})
    mod.put_json(store, "meta/previous.json", {"current": generation, "previous": None})
    _product("portfoliosight.jobs.nightly", "prune_generations")(store, generation)
    assert not store.list(f"models/{old}/") and store.list(f"models/{pinned}/")
    _vitest(tmp_path, WORKER_SOURCE)
