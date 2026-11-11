# ruff: noqa: E501
"""A-SE-26 contract: render the actual App with real copula builds and API values.

The DOM environment emulates layout and HTTP transport only; numerical data come
from genuine build/store/API code. Nonzero-margin dependence summaries are checked
independently. Zero-margin matrix cells and contradictory legacy copy are not frozen.
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


UI_SOURCE = r"""
// Frozen harness: only application imports, deterministic local transport, no product tests.
import React from 'react';
import fs from 'node:fs';
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
import App from '@RUNROOT@/web/src/App';
import {encode,decode} from '@RUNROOT@/web/src/state/url';
import {reencodeShareUrl,handleShare} from '@RUNROOT@/web/worker/share';
import {signedPct} from '@RUNROOT@/web/src/format';
const BASE=JSON.parse(fs.readFileSync('@RUNROOT@/web/fixtures/guide2017_5y.json','utf8'));
const NAMES={replay:'History replay',garch:'Volatility model',copula:'Copula'};
const LBS=['1y','2y','3y','5y','10y','ew'];
let requests:any[]=[], fixture:any, paint:any[]=[], pending:any[]=[];
function platform(phone=false){
 Object.defineProperty(HTMLElement.prototype,'clientWidth',{configurable:true,get(){return phone?390:1100}});
 Object.defineProperty(HTMLElement.prototype,'clientHeight',{configurable:true,get(){return 520}});
 vi.stubGlobal('matchMedia',(q:string)=>({matches:q.includes('max-width')?phone:false,media:q,addEventListener(){},removeEventListener(){}}));
 vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}unobserve(){}});
 const ctx:any={fillStyle:'#000',save(){},restore(){},beginPath(){},moveTo(){},lineTo(){},closePath(){},clip(){},stroke(){},setTransform(){},setLineDash(){},clearRect(){paint=[]},fillRect(...args:any[]){paint.push([this.fillStyle,...args])}};
 Object.defineProperty(HTMLCanvasElement.prototype,'getContext',{configurable:true,value(){return ctx}});
 document.documentElement.style.setProperty('--heat-0','#000000');document.documentElement.style.setProperty('--heat-1','#224466');document.documentElement.style.setProperty('--heat-2','#4488aa');document.documentElement.style.setProperty('--heat-3','#66bbcc');document.documentElement.style.setProperty('--heat-4','#ffffff');
}
function transport(delayed=false){
 vi.stubGlobal('fetch',vi.fn(async(input:any,init:any={})=>{const url=String(input),method=init.method??'GET',body=init.body?JSON.parse(init.body):null;requests.push({url,method,body});const reply=(v:any,s=200)=>new Response(JSON.stringify(v),{status:s,headers:{'content-type':'application/json'}});
 if(url.endsWith('/api/presets'))return reply({generation:fixture.generation,asof:fixture.asof,presets:[{id:fixture.universe.preset_id,name:fixture.universe.name,hash:fixture.universe.hash,funds:fixture.universe.funds,allocation:null,allocation_unit:null,lookbacks:Object.fromEntries(LBS.map(lb=>[lb,{status:'ready',url:`/api/tensors/${fixture.generation}/${fixture.universe.hash}/${lb}`}]))}]});
 if(url.includes('/api/tensors/'))return reply(fixture);
 if(url.endsWith('/api/tensors') && method==='POST')return reply({status:'ready',url:`/api/tensors/${fixture.generation}/${fixture.universe.hash}/1y`});
 if(url.endsWith('/api/tier'))return reply({tier:'public',menu_max:30});
 if(url.endsWith('/api/range')){if(delayed)return new Promise(resolve=>pending.push({body,resolve:(value:any)=>resolve(reply(value))}));throw Error('Unexpected range network request for precomputed selection');}
 return reply({error:{code:'not_found'}},404);
 }));
}
async function open(t:any,search:string,phone=false,delayed=false,keepStorage=false){cleanup();requests=[];pending=[];paint=[];fixture=t;platform(phone);transport(delayed);if(!keepStorage)localStorage.clear();history.replaceState(null,'','/'+search);render(<App/>);await waitFor(()=>expect(screen.getByTestId('range-bar')).toBeTruthy(),{timeout:10000});fireEvent.click(screen.getByTestId('chip-settings'));await act(async()=>{await new Promise(r=>setTimeout(r,450))});}
const text=(id:string)=>screen.getByTestId(id).textContent??'';
function geometry(){return [...document.querySelectorAll('svg path,svg circle,svg line')].map(el=>[el.tagName,...['d','cx','cy','x1','y1','x2','y2'].map(k=>el.getAttribute(k))]);}
async function share(url:string){let mailed:any=null;const old=globalThis.fetch;vi.stubGlobal('fetch',async(input:any,init:any)=>{expect(String(input)).toBe('https://api.mailchannels.net/tx/v1/send');mailed=JSON.parse(init.body);return new Response('{}',{status:202});});try {const response=await handleShare(new Request('https://portfoliosight.ai/api/share',{method:'POST',headers:{origin:'https://portfoliosight.ai','content-type':'application/json','cf-connecting-ip':'192.0.2.1'},body:JSON.stringify({to:'frozen-gate@example.invalid',url})}),{SHARE_FROM:'gate@example.invalid',MAILCHANNELS_API_KEY:'inert',MAILCHANNELS_DKIM_PRIVATE_KEY:'inert'},async()=>true);expect(response.status).toBe(202);expect(mailed).not.toBeNull();const sent=mailed.content.find((x:any)=>x.type==='text/plain').value;expect(sent).toContain(url);return url;}finally{vi.stubGlobal('fetch',old);}}

it('both actual presets expose copula consistently, preserve node figures, and round-trip',async()=>{
 const data=__DATA__;
 for(const t of data.tensors){
  const j=t.frontier.ranges.copula.s_safe;
  await open(t,`?u=${t.universe.preset_id}&lb=1y&r=${j}&d=0`);
  const beforeGeometry=geometry();const beforePaint=JSON.stringify(paint);
  fireEvent.click(screen.getByTestId('engine-copula'));
  await waitFor(()=>{const tags=screen.getAllByTestId('engine-tag');expect(tags.length).toBeGreaterThan(0);tags.forEach(tag=>expect(tag.textContent).toContain('Copula'));});
  for(const [id,field] of [['range-low','bad'],['range-typical','typical'],['range-high','good']] as const)
   expect(text(id)).toContain(signedPct(t.ladder.ranges.copula[field][j][0]));
  expect(text('risk-readout-bad')).toContain(signedPct(t.frontier.ranges.copula.bad[j]));
  expect(text('risk-readout-typical')).toContain(signedPct(t.frontier.ranges.copula.typical[j]));
  expect(geometry()).toEqual(beforeGeometry);expect(JSON.stringify(paint)).toBe(beforePaint);
  expect(requests.filter(x=>x.method==='POST')).toHaveLength(0);
  fireEvent.click(screen.getByTestId('details-toggle'));
  expect(text('details-method').toLowerCase()).toContain('empirical');
  expect(text('details-method')).not.toMatch(/Student.t margins/i);
  const loss=t.ladder.loss_sources.copula;
  for(const hedge of loss.hedges[j][0])expect(document.body.textContent).toContain(hedge);
  const score=loss.n_eff[j][0];
  if(score===null)expect(document.body.textContent).toContain('no losses to share out');
  else expect(document.body.textContent).toMatch(new RegExp(score.toFixed(2).replace('.','\.')));
  fireEvent.click(screen.getByTestId('measure-enlc'));
  await waitFor(()=>expect(new URL(location.href).searchParams.get('m')).toBe('enlc'));
  await waitFor(()=>expect(new URL(location.href).searchParams.get('e')).toBe('copula'));
  const url=reencodeShareUrl('https://portfoliosight.ai'+location.pathname+location.search);
  expect(new URL(url).searchParams.get('e')).toBe('copula');
  await open(t,new URL(url).search);
  expect((screen.getByTestId('engine-copula') as HTMLInputElement).checked).toBe(true);
  for(const [id,field] of [['range-low','bad'],['range-typical','typical'],['range-high','good']] as const)
   expect(text(id)).toContain(signedPct(t.ladder.ranges.copula[field][j][0]));
  const selection=data.pending[t.universe.preset_id];
  await open(t,`?u=${t.universe.preset_id}&lb=1y&r=${selection.s}&d=${selection.t}&e=copula&m=enlc`,false,true);
  await waitFor(()=>expect(pending.length).toBeGreaterThan(0));
  const initial=text('range-low');expect(initial).not.toBe('');
  expect(screen.getByTestId('range-bar')).toBeTruthy();
  expect(pending.at(-1).body.engine).toBe('copula');
  pending.at(-1).body.weights.forEach((w:number,i:number)=>expect(w).toBeCloseTo(selection.weights[i],9));
  await act(async()=>pending.at(-1).resolve(selection.answer));
  await waitFor(()=>expect(text('range-low')).toContain(signedPct(selection.answer.bad)));
  expect(text('range-typical')).toContain(signedPct(selection.answer.typical));
  expect(text('range-high')).toContain(signedPct(selection.answer.good));
 }
 const t=data.custom;await open(t,'?f=VTI:34,BND:33,VNQ:33&unit=pct&lb=1y&r=1&d=0');
 expect((screen.getByTestId('engine-copula') as HTMLInputElement).disabled).toBe(true);
 expect(document.body.textContent).toContain('not computed for custom menus');
});

"""


def test_a_se_26_copula_preset_page(tmp_path):
    if not _runtime():
        return
    import io
    from unittest.mock import patch

    import numpy as np
    from fastapi.testclient import TestClient
    from scipy.stats import rankdata

    _module("qse.distributions.joint.copula")
    jobs = _module("portfoliosight.jobs.build")
    storemod = _module("portfoliosight.data.store")
    engine = _module("portfoliosight.engine")
    api = _module("portfoliosight.api.app")
    import pyvinecopulib as pv

    definitions = json.loads((ROOT / "data/presets.json").read_text())["presets"]
    assert {(x["id"], len(x["funds"])) for x in definitions} == {("guide2017", 23), ("tsp", 5)}
    assert len(definitions) == 2
    store = _frozen_store(tmp_path / "store")
    generation = f"2026-10-13-{engine.ENGINE_VERSION}"
    storemod.put_json(
        store,
        jobs.generation_key(generation),
        {"generation": generation, "asof": "2026-10-13", "engine_version": engine.ENGINE_VERSION},
    )
    storemod.put_json(store, "meta/current.json", {"generation": generation})
    tensors = []
    pending = {}
    with patch.dict(
        os.environ,
        {
            "PS_ENGINES": "replay,garch,copula",
            "PS_ENGINES_CUSTOM": "replay,garch",
            "PS_GATE_SECRET": "gate26-secret-0123456789",
            "PS_CACHE_DIR": str(tmp_path / "cache"),
        },
    ):
        for preset in definitions:
            tensor = jobs.build_from_store(
                store,
                generation=generation,
                funds=[{"id": i, "min": None, "max": None} for i in preset["funds"]],
                lookback="1y",
                cache_dir=tmp_path / "cache",
                universe_name=preset["name"],
                preset_id=preset["id"],
                nx=5,
                ny=5,
                levels=2,
            )
            assert all(
                tensor["engines"][e]["status"] == "ready" for e in ("replay", "garch", "copula")
            )
            prefix = f"models/{generation}/{tensor['shape']['sample_sha256'][:16]}"
            z = np.load(io.BytesIO(store.get(prefix + "/copula_shocks.npy")), allow_pickle=False)
            pool = np.load(io.BytesIO(store.get(prefix + "/pool.npy")), allow_pickle=False)
            assert z.shape[:2] == (2000, 252)
            active = np.flatnonzero(np.ptp(pool, axis=0) > 1e-12)
            flat = z.reshape(-1, z.shape[-1])
            low = flat[:, active] <= np.quantile(flat[:, active], 0.05, axis=0)
            expected = (low.astype(float).T @ low) / low.sum(axis=0)[None, :]
            actual = np.array(tensor["shape"]["lower_tail_5pct"], dtype=float)
            assert np.allclose(actual[np.ix_(active, active)], expected, atol=2 / 25200, rtol=0)
            artifact = json.loads(store.get(prefix + "/copula.json"))
            u = np.column_stack([rankdata(pool[:, i]) / (len(pool) + 1) for i in active])
            loglik = []
            trees = min(5, len(active) - 1)
            for count in range(1, trees + 1):
                vine = pv.Vinecop.from_json(artifact["vine"])
                vine.truncate(count)
                loglik.append(vine.loglik(u))
            increments = np.diff([0, *loglik])
            shares = increments / sum(increments)
            observed = tensor["shape"]["tree_loglik_share"]
            assert np.allclose(observed[:trees], shares, atol=1e-9, rtol=1e-9)
            assert not observed[trees:] or np.all(np.array(observed[trees:]) == 0)
            key = f"tensors/{generation}/{tensor['universe']['hash']}/1y.json"
            storemod.put_json(store, key, tensor)
            # A fractional position inside the engine's risk domain, with an actual endpoint answer.
            j = min(
                tensor["frontier"]["ranges"]["copula"]["s_safe"], len(tensor["frontier"]["w"]) - 2
            )
            s = j + 0.25
            t = 0.4
            columns = []
            for column in (j, j + 1):
                levels = tensor["ladder"]["w"][column]
                pos = t * (len(levels) - 1)
                level = min(int(pos), len(levels) - 2)
                f = pos - level
                if tensor["ladder"]["hop"][column][level]:
                    f = 0 if f < 0.5 else 1
                columns.append((1 - f) * np.array(levels[level]) + f * np.array(levels[level + 1]))
            w = 0.75 * columns[0] + 0.25 * columns[1]
            with TestClient(api.create_app(store=store, start_worker=False)) as client:
                response = client.post(
                    "/v1/range",
                    json={
                        "generation": generation,
                        "hash": tensor["universe"]["hash"],
                        "lookback": "1y",
                        "engine": "copula",
                        "weights": w.tolist(),
                    },
                    headers={
                        "x-ps-gate": "gate26-secret-0123456789",
                        "cf-connecting-ip": "10.26.0.1",
                    },
                )
                assert response.status_code == 200, response.text
                pending[preset["id"]] = {
                    "s": s,
                    "t": t,
                    "weights": w.tolist(),
                    "answer": response.json(),
                }
            tensors.append(tensor)
        custom = jobs.build_from_store(
            store,
            generation=generation,
            funds=[{"id": i, "min": None, "max": None} for i in ("VTI", "BND", "VNQ")],
            lookback="1y",
            cache_dir=tmp_path / "cache",
            universe_name="custom",
            nx=3,
            ny=3,
            levels=2,
        )
        assert custom["engines"]["copula"]["status"] == "unavailable"
        assert custom["engines"]["copula"]["reason"] == "not computed for custom menus"
        custom["universe"]["preset_id"] = "custom"  # Local transport label only; data unchanged.
    payload = {"tensors": tensors, "pending": pending, "custom": custom}
    _vitest(tmp_path, UI_SOURCE.replace("__DATA__", json.dumps(payload)))


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
