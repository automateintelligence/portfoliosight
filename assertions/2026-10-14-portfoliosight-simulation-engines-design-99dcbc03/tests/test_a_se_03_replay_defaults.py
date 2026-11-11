"""A-SE-03 (property): enabling GARCH preserves the frozen pre-engine replay algorithm.
Independent oracle transcribed from pre-engine ranges.py (20b292e); it retains stationary
blocks and sample volatility, never rescales replay to chart covariance. Actual builders,
HTTP omitted-engine requests and rendered App defaults cover both menus and 1y/5y/ew.
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
        for name in {
            **package.get("dependencies", {}),
            **package.get("devDependencies", {}),
        }
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
            [
                str(node),
                str(modules / "vitest/vitest.mjs"),
                "run",
                "--config",
                str(config),
            ],
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


UI = "// Frozen harness: only application imports, deterministic local transport, no product tests.\nimport React from 'react';\nimport fs from 'node:fs';\nimport {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';\nimport {expect,it,vi} from 'vitest';\nimport App from '@RUNROOT@/web/src/App';\nimport {encode,decode} from '@RUNROOT@/web/src/state/url';\nimport {signedPct} from '@RUNROOT@/web/src/format';\nconst BASE=JSON.parse(fs.readFileSync('@RUNROOT@/web/fixtures/guide2017_5y.json','utf8'));\nconst NAMES={replay:'History replay',garch:'Volatility model',copula:'Copula'};\nconst LBS=['1y','2y','3y','5y','10y','ew'];\nlet requests:any[]=[], fixture:any, paint:any[]=[], pending:any[]=[];\nfunction sentinel(menu='guide2017',lb='5y') {\n const t=structuredClone(BASE); t.schema=3;t.engine_version='0.4.0';t.generation=t.asof+'-0.4.0';t.lookback.id=lb;t.universe.preset_id=menu;t.range_default='replay';\n t.engines={replay:{status:'ready',method:t.range_method},garch:{status:'ready',reason:null,ruin_paths:0,method:{name:'garch_t_fhs',paths:2000,horizon_days:252,seed:20261013,start:'long_run',shape_rows:2520,returns:'log',scale:'sd',ruin:'absorb',qse:'ca8c0445a56712c92dc028e68845b94963fdd590',arch:'8.0.0'}},copula:{status:'unavailable',reason:'not computed for this menu',method:null}};\n t.shape={rows:2520,start:'2016-10-01',end:t.asof,sample_sha256:'a'.repeat(64),pool_rows:1500,funds:t.universe.funds.map((f:any,i:number)=>({id:f.id,status:i===0?'near_constant':'ok',rows:2520,mu:0,omega:.000001,alpha:.05,beta:.9,nu:7,long_run_sigma_annual:.12,margin:null})),outliers:[],lower_tail_5pct:null,tree_loglik_share:null};\n const make=(obj:any,engine:string)=>{let offset=engine==='garch'?.113:0;let deep=(v:any,k:number):any=>Array.isArray(v)?v.map(x=>deep(x,k)):k+offset;\n return {bad:deep(obj.range.bad,-.187),typical:deep(obj.range.typical,.041),good:deep(obj.range.good,.263)};};\n for(const block of ['frontier','ladder','entered'])if(t[block]) {t[block].ranges={replay:make(t[block],'replay'),garch:make(t[block],'garch')};Object.assign(t[block].range,t[block].ranges.replay);}\n t.frontier.s_safe=0;t.frontier.ranges.replay.s_safe=0;t.frontier.ranges.garch.s_safe=2;\n t.ladder.measure='enb';t.ladder.enb=t.ladder.z.map((c:any[])=>c.map(()=>2.137));t.ladder.dr2=t.ladder.z.map((c:any[])=>c.map(()=>1.419));t.ladder.z=t.ladder.enb;\n t.grid.enb=t.grid.z.map((c:any[])=>c.map(v=>v===null?null:2.137));t.grid.dr2=t.grid.z.map((c:any[])=>c.map(v=>v===null?null:1.419));t.grid.z=t.grid.enb;t.refs={enb:8.731,dr2:2.101,enlc:{replay:6.2,garch:4.3}};t.enb_ref=t.refs.enb;\n t.ladder.on_line=t.ladder.w.map((c:any[])=>c.map(()=>true));\n t.ladder.loss_sources={};\n for(const e of ['replay','garch']){const n=e==='replay'?1.317:3.271;const hedge=e==='replay'?t.universe.funds[0].id:t.universe.funds[1].id;\n t.ladder.loss_sources[e]={n_eff:t.ladder.w.map((c:any[])=>c.map(()=>n)),top:t.ladder.w.map((c:any[])=>c.map(()=>[{id:t.universe.funds[2].id,share:.73}])),hedges:t.ladder.w.map((c:any[])=>c.map(()=>[hedge]))};\n if(t.entered)t.entered.loss_sources={...t.entered.loss_sources,[e]:{n_eff:n,top:[{id:t.universe.funds[2].id,share:.73}],hedges:[hedge]}};}\n t.min_pair_correlation=.1;return t;\n}\nfunction platform(phone=false){\n Object.defineProperty(HTMLElement.prototype,'clientWidth',{configurable:true,get(){return phone?390:1100}});\n Object.defineProperty(HTMLElement.prototype,'clientHeight',{configurable:true,get(){return 520}});\n vi.stubGlobal('matchMedia',(q:string)=>({matches:q.includes('max-width')?phone:false,media:q,addEventListener(){},removeEventListener(){}}));\n vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}unobserve(){}});\n const ctx:any={fillStyle:'#000',save(){},restore(){},beginPath(){},moveTo(){},lineTo(){},closePath(){},clip(){},stroke(){},setTransform(){},setLineDash(){},clearRect(){paint=[]},fillRect(...args:any[]){paint.push([this.fillStyle,...args])}};\n Object.defineProperty(HTMLCanvasElement.prototype,'getContext',{configurable:true,value(){return ctx}});\n document.documentElement.style.setProperty('--heat-0','#000000');document.documentElement.style.setProperty('--heat-1','#224466');document.documentElement.style.setProperty('--heat-2','#4488aa');document.documentElement.style.setProperty('--heat-3','#66bbcc');document.documentElement.style.setProperty('--heat-4','#ffffff');\n}\nfunction transport(delayed=false){\n vi.stubGlobal('fetch',vi.fn(async(input:any,init:any={})=>{const url=String(input),method=init.method??'GET',body=init.body?JSON.parse(init.body):null;requests.push({url,method,body});const reply=(v:any,s=200)=>new Response(JSON.stringify(v),{status:s,headers:{'content-type':'application/json'}});\n if(url.endsWith('/api/presets'))return reply({generation:fixture.generation,asof:fixture.asof,presets:[{id:fixture.universe.preset_id,name:fixture.universe.name,hash:fixture.universe.hash,funds:fixture.universe.funds,allocation:null,allocation_unit:null,lookbacks:Object.fromEntries(LBS.map(lb=>[lb,{status:'ready',url:`/api/tensors/${fixture.generation}/${fixture.universe.hash}/${lb}`}]))}]});\n if(url.includes('/api/tensors/'))return reply(fixture);\n if(url.endsWith('/api/tier'))return reply({tier:'public',menu_max:30});\n if(url.endsWith('/api/range')){if(delayed)return new Promise(resolve=>pending.push({body,resolve:(value:any)=>resolve(reply(value))}));throw Error('Unexpected range network request for precomputed selection');}\n return reply({error:{code:'not_found'}},404);\n }));\n}\nasync function open(t:any,search:string,phone=false,delayed=false){cleanup();requests=[];pending=[];paint=[];fixture=t;platform(phone);transport(delayed);localStorage.clear();const intended=decode(search);expect(intended.preset).toBe(t.universe.preset_id);expect(intended.lookback).toBe(t.lookback.id);history.replaceState(null,'','/'+search);render(<App/>);await waitFor(()=>expect(screen.getByTestId('range-bar')).toBeTruthy(),{timeout:10000});fireEvent.click(screen.getByTestId('chip-settings'));await act(async()=>{await new Promise(r=>setTimeout(r,450))});expect(screen.getByTestId('preset-menu').getAttribute('aria-label')).toBe('Portfolio: '+t.universe.name);expect((screen.getByTestId('lookback-'+t.lookback.id) as HTMLInputElement).checked).toBe(true);expect(decode(location.search).preset).toBe(t.universe.preset_id);expect(decode(location.search).lookback).toBe(t.lookback.id);expect(requests.some(r=>r.method==='GET'&&r.url===`/api/tensors/${t.generation}/${t.universe.hash}/${t.lookback.id}`)).toBe(true);}\n"


def _legacy(sample, mu, cov, weights, np):
    # Frozen RNG call ordering and formula from the pre-engine implementation.
    rng = np.random.default_rng(20261013)
    rows = len(sample)
    starts = rng.integers(0, rows, size=(2000, 252))
    fresh = rng.random((2000, 252)) < 1 / 21
    fresh[:, 0] = True
    day = np.broadcast_to(np.arange(252), (2000, 252))
    origin = np.maximum.accumulate(np.where(fresh, day, 0), axis=1)
    indices = (np.take_along_axis(starts, origin, axis=1) + day - origin) % rows
    result = []
    for w in weights:
        actual = sample @ w
        daily = actual - actual.mean() + w @ mu / 252
        assert np.all(daily > -1)
        years = np.expm1(np.log1p(daily)[indices].sum(axis=1))
        q = np.quantile(years, [0.025, 0.5, 0.975], method="linear")
        sigma = np.sqrt(w @ cov @ w)
        result.append([*q, w @ mu - 1.96 * sigma, w @ mu, w @ mu + 1.96 * sigma])
    return np.array(result)


def test_a_se_03_replay_and_defaults(monkeypatch, tmp_path):
    if _inner():
        return
    np = _need("numpy")
    builder = _need("portfoliosight.engine.builder")
    build = _attr(builder, "build_tensor_full")
    jobs = _need("portfoliosight.jobs.build")
    _attr(jobs, "put_artifact")
    ranges = _need("portfoliosight.engine.ranges")
    store, asof, generation = _store(tmp_path, monkeypatch)
    presets = _need("portfoliosight.data.universe").load_presets()
    assert sorted(preset.id for preset in presets) == ["guide2017", "tsp"]
    expected_views = {
        (preset, lookback) for preset in ("guide2017", "tsp") for lookback in ("1y", "5y", "ew")
    }
    http_observations = []
    TestClient = _need("fastapi.testclient").TestClient
    make_app = _need("portfoliosight.api.app").create_app
    tensors = []
    for preset in presets:
        for lookback in ("1y", "5y", "ew"):
            policy = [
                {"id": i, "min": 0.0, "max": 0.6 if lookback == "ew" else 1.0} for i in preset.funds
            ]
            inputs = jobs.inputs_from_store(
                store,
                funds=policy,
                lookback=lookback,
                asof=asof,
                cache_dir=tmp_path / "cache",
                universe_name=preset.name,
                preset_id=preset.id,
                allocation=preset.allocation,
                nx=4,
                ny=4,
                levels=3,
                engines=("replay", "garch"),
            )
            replay = build(replace(inputs, engines=("replay",)), workers=1)
            both = build(inputs, workers=1)
            tensor = both.tensor
            tensors.append(tensor)
            assert tensor["range_default"] == "replay" and tensor["ladder"]["measure"] == "enb"
            assert tensor["range_method"] == replay.tensor["range_method"]
            for block in ("frontier", "ladder", "entered"):
                if tensor.get(block) is not None:
                    assert tensor[block]["range"] == replay.tensor[block]["range"]
                    for name in ("bad", "typical", "good"):
                        assert (
                            tensor[block]["ranges"]["replay"][name] == tensor[block]["range"][name]
                        )
            ids = [f["id"] for f in tensor["universe"]["funds"]]
            count = len(ids)
            sample = (
                inputs.returns.loc[: str(asof), ids]
                .iloc[-({"1y": 252, "5y": 1260, "ew": 1260}[lookback]) :]
                .dropna()
                .to_numpy()
            )
            weights = np.vstack(
                [
                    np.eye(count)[0],
                    np.ones(count) / count,
                    np.arange(1, count + 1) / sum(range(1, count + 1)),
                    tensor["frontier"]["w"],
                    np.asarray(tensor["ladder"]["w"]).reshape(-1, count),
                ]
            )
            mu, cov = np.array(tensor["mu_s"]), np.array(tensor["cov"])
            expected = _legacy(sample, mu, cov, weights, np)
            for model in (replay.models["replay"], both.models["replay"]):
                observed = ranges.one_year_ranges(model, weights)
                actual = np.column_stack(
                    [observed[n] for n in ("bad", "typical", "good")]
                    + [observed["normal"][n] for n in ("low", "mid", "high")]
                )
                np.testing.assert_allclose(actual, expected, atol=1e-11, rtol=1e-11)
            # Covariance affects the normal detail but must not resize replay's empirical spread.
            changed = ranges.range_model(sample, mu, cov * 2.7)
            control = ranges.one_year_ranges(changed, weights)
            np.testing.assert_allclose(control["bad"], expected[:, 0], atol=1e-11)
            assert not np.allclose(control["normal"]["low"], expected[:, 3])
            jobs.put_artifact(store, generation, both.artifacts["garch"])
            key = f"tensors/{generation}/{tensor['universe']['hash']}/{lookback}.json"
            jobs.put_tensor(store, key, tensor)
            with TestClient(make_app(store=store, start_worker=False)) as client:
                for index, w in enumerate(weights[:3]):
                    body = {
                        "generation": generation,
                        "hash": tensor["universe"]["hash"],
                        "lookback": lookback,
                        "weights": w.tolist(),
                    }
                    response = client.post(
                        "/v1/range",
                        json=body,
                        headers={
                            "x-ps-gate": "frozen-gate-local-0123456789",
                            "cf-connecting-ip": "192.0.2.3",
                        },
                    )
                    assert response.status_code == 200, response.text
                    answer = response.json()
                    assert answer["engine"] == "replay"
                    np.testing.assert_allclose(
                        [answer[n] for n in ("bad", "typical", "good")],
                        expected[index, :3],
                        atol=1e-11,
                    )
                    http_observations.append((preset.id, lookback, index))
    assert len(tensors) == 6
    assert {
        (tensor["universe"]["preset_id"], tensor["lookback"]["id"]) for tensor in tensors
    } == expected_views
    assert len(http_observations) == 18
    assert set(http_observations) == {
        (preset, lookback, index) for preset, lookback in expected_views for index in range(3)
    }
    path = tmp_path / "tensors.json"
    path.write_text(json.dumps(tensors))
    source = (
        UI
        + "\nit('omitted engine and measure preserve owner defaults on both menus',async()=>{const ts=JSON.parse(fs.readFileSync("
        + json.dumps(str(path))
        + ", 'utf8'));expect(ts).toHaveLength(6);expect(ts.map((t:any)=>t.universe.preset_id+'/'+t.lookback.id).sort()).toEqual(['guide2017/1y','guide2017/5y','guide2017/ew','tsp/1y','tsp/5y','tsp/ew']);let defaultViews=0,explicitViews=0;for(const t of ts){const query='?u='+t.universe.preset_id+'&lb='+t.lookback.id+'&x=1';await open(t,query);expect((screen.getByTestId('engine-replay') as HTMLInputElement).checked).toBe(true);expect((screen.getByTestId('engine-garch') as HTMLInputElement).checked).toBe(false);expect((screen.getByTestId('measure-enb') as HTMLInputElement).checked).toBe(true);defaultViews++;const values=['range-low','range-typical','range-high'].map(id=>screen.getByTestId(id).textContent);await open(t,query+'&e=replay&m=enb');expect(['range-low','range-typical','range-high'].map(id=>screen.getByTestId(id).textContent)).toEqual(values);const tags=screen.getAllByTestId('engine-tag');expect(tags.length).toBeGreaterThan(0);expect(tags.every(e=>e.textContent==='History replay')).toBe(true);explicitViews++;}expect(defaultViews).toBe(6);expect(explicitViews).toBe(6);});"
    )
    _vitest(tmp_path, source)
