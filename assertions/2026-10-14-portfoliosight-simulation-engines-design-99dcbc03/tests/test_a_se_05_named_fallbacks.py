"""A-SE-05 (property): weak/failed upstream fits remain named constant-volatility funds.
Pins QSE GarchTFitter adapter controls, actual build_tensor_full and actual App rendering.
The test does not edit vendored source; monkeypatch controls optimizer outcomes in memory.
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


from types import SimpleNamespace


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


def test_a_se_05_named_constant_volatility_fallbacks(monkeypatch, tmp_path):
    if _inner():
        return
    np, pd = _need("numpy"), _need("pandas")
    _need("portfoliosight.engine.shape")
    panel_module = _need("qse.distributions.joint.panel_fit")
    builder = _need("portfoliosight.engine.builder")
    build = _attr(builder, "build_tensor_full")
    mode = {"parameters": {}, "converged": True, "raises": False, "bad_sigma": False}

    class ControlledFitter:
        def fit(self, x):
            self.x = np.array(x)
            if mode["raises"]:
                # Raise the precise upstream error type without requiring an out-of-surface import.
                raise panel_module.DistributionFitError("controlled optimizer failure")
            return SimpleNamespace(warnings=[])

        def original_scale_params(self):
            return {
                "mu": 0.0002,
                "omega": 2e-6,
                "alpha": 0.07,
                "beta": 0.88,
                "nu": 7.0,
                **mode["parameters"],
            }

        def conditional_volatility(self):
            result = np.full_like(self.x, self.x.std(ddof=1))
            if mode["bad_sigma"]:
                result[0] = np.nan
            return result

        def standardized_residuals(self):
            return (self.x - 0.0002) / self.x.std(ddof=1)

        def optimizer_converged(self):
            return mode["converged"]

    monkeypatch.setattr(panel_module, "GarchTFitter", ControlledFitter)
    rng = np.random.default_rng(87)
    x = rng.normal(0.0002, 0.008, 600)
    conditions = [
        ({"raises": True}, "fit_failed"),
        ({"converged": False}, "fit_failed"),
        ({"parameters": {"mu": np.nan}}, "fit_failed"),
        ({"parameters": {"omega": -1e-6}}, "fit_failed"),
        ({"parameters": {"alpha": -0.01}}, "fit_failed"),
        ({"parameters": {"beta": -0.01}}, "fit_failed"),
        ({"parameters": {"nu": 2.0}}, "fit_failed"),
        ({"bad_sigma": True}, "fit_failed"),
        ({"parameters": {"alpha": 0.1, "beta": 0.8999}}, "non_stationary"),
        ({"parameters": {"alpha": 0.1, "beta": 0.89991}}, "non_stationary"),
        ({"parameters": {"alpha": 0.1, "beta": 0.89989}}, "garch"),
        ({}, "garch"),
    ]
    for changes, status in conditions:
        mode.update(parameters={}, converged=True, raises=False, bad_sigma=False)
        mode.update(changes)
        fit = panel_module.fit_garch_t_panel(pd.DataFrame({"CONTROL": x}))
        assert fit.status == (status,)
        if status != "garch":
            assert fit.alpha[0] == fit.beta[0] == 0
            assert fit.omega[0] == pytest.approx(x.var(ddof=1), rel=1e-12)
            assert fit.mu[0] == pytest.approx(x.mean(), rel=1e-12)
            np.testing.assert_allclose(
                fit.std_residuals[:, 0], (x - x.mean()) / x.std(ddof=1), atol=1e-12
            )
            assert np.isnan(fit.nu[0]) and fit.messages[0]
        else:
            assert fit.alpha[0] == mode["parameters"].get("alpha", 0.07)
            assert fit.beta[0] == mode["parameters"].get("beta", 0.88)
            assert fit.alpha[0] + fit.beta[0] < 1 - 1e-4
    mode.update(parameters={}, converged=True, raises=False, bad_sigma=False)
    # Exact series standard deviation makes the near-constant boundary independent of RNG luck.
    standardized = (x - x.mean()) / x.std(ddof=1)
    for sd, expected in [
        (3e-4 * (1 - 1e-6), "near_constant"),
        (3e-4 * (1 + 1e-6), "garch"),
    ]:
        fit = panel_module.fit_garch_t_panel(pd.DataFrame({"BOUNDARY": standardized * sd}))
        assert fit.status == (expected,)
    for values, status in [
        (np.full(600, 0.00012), "near_constant"),
        (0.00012 + standardized * 0.00002, "near_constant"),
        (x[:200], "insufficient_history"),
    ]:
        fit = panel_module.fit_garch_t_panel(pd.DataFrame({"FUND": values}))
        assert fit.status == (status,) and fit.alpha[0] == fit.beta[0] == 0
        expected_var = 0.0 if np.std(values, ddof=1) <= 1e-12 else np.var(values, ddof=1)
        assert fit.omega[0] == pytest.approx(expected_var, rel=1e-12, abs=1e-30)
        expected = (
            np.zeros(len(values))
            if expected_var == 0
            else (values - values.mean()) / np.sqrt(expected_var)
        )
        np.testing.assert_allclose(fit.std_residuals[:, 0], expected, atol=1e-12)
    days = pd.bdate_range(end="2026-10-13", periods=1500)
    base = pd.DataFrame(
        np.expm1(rng.normal([0.0003, 0.0002, 0.00012], [0.012, 0.006, 0.00002], (1500, 3))),
        index=days,
        columns=["VALID", "BOND", "TSP-G"],
    )
    funds = [
        builder.FundInput(
            id=i,
            name=i,
            kind="etf",
            source="tiingo",
            adjusted_through="2026-10-13",
            fetched_at="2026-10-13T00:00:00Z",
        )
        for i in [*base, "YOUNG"]
    ]
    tensors = []
    for young_rows in (227, 240, 251):
        frame = base.copy()
        frame["YOUNG"] = np.nan
        frame.iloc[-young_rows:, -1] = np.expm1(rng.normal(0.0002, 0.01, young_rows))
        inputs = builder.TensorInputs(
            funds=funds,
            returns=frame,
            lookback="1y",
            asof=days[-1],
            universe_name="Fallback gate",
            preset_id="guide2017",
            nx=4,
            ny=4,
            levels=3,
            engines=("replay", "garch"),
        )
        result = build(inputs, workers=1)
        artifact = result.artifacts["garch"]
        assert "YOUNG" in artifact.funds and "YOUNG" not in [
            f["id"] for f in result.tensor["universe"]["excluded"]
        ]
        young_idx = artifact.funds.index("YOUNG")
        assert artifact.status[young_idx] == "insufficient_history"
        assert artifact.n_obs[young_idx] == young_rows
        assert artifact.alpha[young_idx] == artifact.beta[young_idx] == 0
        assert result.models["garch"].panel.shape == (2000, 252, 4)
        declared = {f["id"]: f["status"] for f in result.tensor["shape"]["funds"]}
        assert declared["TSP-G"] == "near_constant" and declared["YOUNG"] == "insufficient_history"
        assert declared["VALID"] == "garch"
        tensors.append(result.tensor)
    tensor_path = tmp_path / "fallback-tensors.json"
    tensor_path.write_text(json.dumps(tensors))
    source = (
        UI
        + "\nit('names every fallback without calling the valid fund constant',async()=>{const tensors=JSON.parse(fs.readFileSync("
        + json.dumps(str(tensor_path))
        + ", 'utf8'));for(const t of tensors){await open(t,'?u=guide2017&lb=1y&e=garch');fireEvent.click(screen.getByTestId('details-toggle'));await waitFor(()=>expect(screen.getByTestId('details-held-constant').textContent).toContain('YOUNG'));const text=screen.getByTestId('details-held-constant').textContent??'';expect(text).toContain('TSP-G');expect(text).not.toContain('VALID');expect(text).toMatch(/volatility held constant/i);}});"
    )
    _vitest(tmp_path, source)
