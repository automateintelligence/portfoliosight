# ruff: noqa: E501 -- embedded runtime programs retain their native source layout.
"""A-SE-20: frozen runtime app gate; standalone embedded TS, local transport only."""

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
    report_path = tmp_path / "vitest-results.json"
    runtime_path = tmp_path / "vitest-runtime.json"
    runtime_reporter = tmp_path / "vitest-runtime-reporter.mjs"
    # Vitest 3.2's built-in JSON reporter omits unhandled errors; observe its run-end hook.
    runtime_reporter.write_text(
        "import {writeFileSync} from 'node:fs';\n"
        "export default class {onTestRunEnd(_modules, errors, reason) {"
        "writeFileSync("
        + json.dumps(str(runtime_path))
        + ", JSON.stringify({reason, unhandledErrors: errors.map(error => "
        "({name: error.name, message: error.message, stack: error.stack}))}));}}\n"
    )
    config = tmp_path / "vitest.config.mjs"
    config.write_text(
        "export default "
        + json.dumps(
            {
                "root": str(ROOT / "web"),
                "resolve": {"alias": aliases},
                "esbuild": {"jsx": "automatic"},
                "test": {
                    "reporters": [
                        "default",
                        ["json", {"outputFile": str(report_path)}],
                        str(runtime_reporter),
                    ],
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
                "FORCE_COLOR": "0",
                "DEBUG_PRINT_LIMIT": "1000",
                "PATH": str(node.parent) + os.pathsep + os.environ.get("PATH", ""),
            },
        )
    except subprocess.TimeoutExpired:
        pytest.fail("Application runtime gate exceeded 180 seconds")
    assert result.returncode == 0, (
        result.stdout[:6000] + result.stderr[:4000] + result.stderr[-1000:]
    )
    report = json.loads(report_path.read_text())
    runtime = json.loads(runtime_path.read_text())
    assert report["numTotalTests"] > 0, "No runtime observations executed"
    assert report["numPassedTests"] == report["numTotalTests"]
    assert not report["numFailedTests"], "Runtime assertions failed"
    assert not report["numFailedTestSuites"], "Runtime test suites failed"
    assert not report["numPendingTests"], "Skipped or pending runtime observations"
    assert not report["numPendingTestSuites"], "Pending runtime test suites"
    assert not report["numTodoTests"], "Runtime observations left as todo"
    assert report["success"] is True and report["testResults"]
    observations = [
        observation for suite in report["testResults"] for observation in suite["assertionResults"]
    ]
    assert len(observations) == report["numTotalTests"]
    assert not [suite for suite in report["testResults"] if suite["status"] != "passed"]
    assert not [observation for observation in observations if observation["status"] != "passed"]
    assert not [observation for observation in observations if observation["failureMessages"]]
    assert not runtime["unhandledErrors"], "Unhandled runtime errors invalidate UI evidence"
    assert runtime["reason"] == "passed", "Runtime was interrupted or failed"


SOURCE = r"""import {parseTensor} from '@RUNROOT@/web/src/api/client';
// Frozen harness: only application imports, deterministic local transport, no product tests.
import React from 'react';
import fs from 'node:fs';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import App from '@RUNROOT@/web/src/App';
import { encode, decode } from '@RUNROOT@/web/src/state/url';
import { reencodeShareUrl, handleShare } from '@RUNROOT@/web/worker/share';
import { signedPct } from '@RUNROOT@/web/src/format';
const BASE = JSON.parse(fs.readFileSync('@RUNROOT@/web/fixtures/guide2017_5y.json', 'utf8'));
const NAMES = { replay: 'History replay', garch: 'Volatility model', copula: 'Copula' };
const LBS = ['1y', '2y', '3y', '5y', '10y', 'ew'];
let requests: any[] = [], fixture: any, paint: any[] = [], pending: any[] = [];
function sentinel(menu = 'guide2017', lb = '5y', measures = false) {
    const t = structuredClone(BASE);
    t.schema = 3;
    t.engine_version = measures ? '0.4.0' : '0.3.0';
    t.generation = t.asof + '-' + t.engine_version;
    t.lookback.id = lb;
    t.universe.preset_id = menu;
    t.range_default = 'replay';
    t.engines = { replay: { status: 'ready', reason: null, method: t.range_method }, garch: { status: 'ready', reason: null, ruin_paths: 0, method: { name: 'garch_t_fhs', paths: 2000, horizon_days: 252, seed: 20261013, start: 'long_run', shape_rows: 2520, returns: 'log', scale: 'sd', ruin: 'absorb', qse: 'ca8c0445a56712c92dc028e68845b94963fdd590', arch: '8.0.0' } }, copula: { status: 'unavailable', reason: 'not computed for this menu', method: null } };
    t.shape = { rows: 2520, start: '2016-10-01', end: t.asof, sample_sha256: 'a'.repeat(64), pool_rows: 1500, funds: t.universe.funds.map((f: any, i: number) => ({ id: f.id, status: i === 0 ? 'near_constant' : 'garch', rows: 2520, mu: 0, omega: .000001, alpha: .05, beta: .9, nu: 7, long_run_sigma_annual: .12, margin: null })), outliers: [], lower_tail_5pct: null, tree_loglik_share: null };
    const make = (obj: any, engine: string) => {
        let offset = engine === 'garch' ? .113 : 0;
        let deep = (v: any, k: number): any => Array.isArray(v) ? v.map(x => deep(x, k)) : k + offset;
        return { bad: deep(obj.range.bad, -.187), typical: deep(obj.range.typical, .041), good: deep(obj.range.good, .263) };
    };
    for (const block of ['frontier', 'ladder', 'entered'])
        if (t[block]) {
            t[block].ranges = { replay: make(t[block], 'replay'), garch: make(t[block], 'garch') };
            Object.assign(t[block].range, t[block].ranges.replay);
        }
    t.frontier.s_safe = 0;
    t.frontier.ranges.replay.s_safe = 0;
    t.frontier.ranges.garch.s_safe = 2;
    if (!measures)
        return t;
    t.ladder.measure = 'enb';
    t.ladder.enb = t.ladder.z.map((c: any[]) => c.map(() => 2.137));
    t.ladder.dr2 = t.ladder.z.map((c: any[]) => c.map(() => 1.419));
    t.ladder.z = t.ladder.enb;
    t.grid.enb = t.grid.z.map((c: any[]) => c.map(v => v === null ? null : 2.137));
    t.grid.dr2 = t.grid.z.map((c: any[]) => c.map(v => v === null ? null : 1.419));
    t.grid.z = t.grid.enb;
    t.refs = { enb: 8.731, dr2: 2.101, enlc: { replay: 6.2, garch: 4.3 } };
    t.enb_ref = t.refs.enb;
    t.ladder.on_line = t.ladder.w.map((c: any[]) => c.map(() => true));
    t.ladder.loss_sources = {};
    for (const e of ['replay', 'garch']) {
        const n = e === 'replay' ? 1.317 : 3.271;
        const hedge = e === 'replay' ? t.universe.funds[0].id : t.universe.funds[1].id;
        t.ladder.loss_sources[e] = { n_eff: t.ladder.w.map((c: any[]) => c.map(() => n)), top: t.ladder.w.map((c: any[]) => c.map(() => [{ id: t.universe.funds[2].id, share: .73 }])), hedges: t.ladder.w.map((c: any[]) => c.map(() => [hedge])) };
        if (t.entered)
            t.entered.loss_sources = { ...t.entered.loss_sources, [e]: { n_eff: n, top: [{ id: t.universe.funds[2].id, share: .73 }], hedges: [hedge] } };
    }
    t.min_pair_correlation = .1;
    return t;
}
function platform(phone = false) {
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get() { return phone ? 390 : 1100; } });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get() { return 520; } });
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('max-width') ? phone : false, media: q, addEventListener() { }, removeEventListener() { } }));
    vi.stubGlobal('ResizeObserver', class {
        observe() { }
        disconnect() { }
        unobserve() { }
    });
    const ctx: any = { fillStyle: '#000', save() { }, restore() { }, beginPath() { }, moveTo() { }, lineTo() { }, closePath() { }, clip() { }, stroke() { }, setTransform() { }, setLineDash() { }, clearRect() { paint = []; }, fillRect(...args: any[]) { paint.push([this.fillStyle, ...args]); } };
    Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', { configurable: true, value() { return ctx; } });
    document.documentElement.style.setProperty('--heat-0', '#000000');
    document.documentElement.style.setProperty('--heat-1', '#224466');
    document.documentElement.style.setProperty('--heat-2', '#4488aa');
    document.documentElement.style.setProperty('--heat-3', '#66bbcc');
    document.documentElement.style.setProperty('--heat-4', '#ffffff');
}
function transport(delayed = false) {
    vi.stubGlobal('fetch', vi.fn(async (input: any, init: any = {}) => {
        const url = String(input), method = init.method ?? 'GET', body = init.body ? JSON.parse(init.body) : null;
        requests.push({ url, method, body });
        const reply = (v: any, s = 200) => new Response(JSON.stringify(v), { status: s, headers: { 'content-type': 'application/json' } });
        if (url.endsWith('/api/presets'))
            return reply({ generation: fixture.generation, asof: fixture.asof, presets: [{ id: fixture.universe.preset_id, name: fixture.universe.name, hash: fixture.universe.hash, funds: fixture.universe.funds, allocation: Object.fromEntries(fixture.universe.funds.map((f: any, i: number) => [f.id, (fixture.entered?.w[i] ?? 1 / fixture.universe.funds.length) * 100])), allocation_unit: 'pct', lookbacks: Object.fromEntries(LBS.map(lb => [lb, { status: 'ready', url: `/api/tensors/${fixture.generation}/${fixture.universe.hash}/${lb}` }])) }] });
        if (url.includes('/api/tensors/'))
            return reply(fixture);
        if (url.endsWith('/api/tier'))
            return reply({ tier: 'public', menu_max: 30 });
        if (url.endsWith('/api/range')) {
            if (delayed)
                return new Promise(resolve => pending.push({ body, resolve: (value: any) => resolve(reply(value)) }));
            throw Error('Unexpected range network request for precomputed selection');
        }
        return reply({ error: { code: 'not_found' } }, 404);
    }));
}
async function open(t: any, search: string, phone = false, delayed = false, keepStorage = false) { parseTensor(t); cleanup(); requests = []; pending = []; paint = []; fixture = t; platform(phone); transport(delayed); if (!keepStorage)
    localStorage.clear(); history.replaceState(null, '', '/' + search); render(<App />); await waitFor(() => expect(screen.getByTestId('range-bar')).toBeTruthy(), { timeout: 10000 }); fireEvent.click(screen.getByTestId('chip-settings')); await act(async () => { await new Promise(r => setTimeout(r, 450)); }); }
const text = (id: string) => screen.getByTestId(id).textContent ?? '';
function expectFigures(e: 'replay' | 'garch') { const offset = e === 'garch' ? .113 : 0; for (const [id, v] of [['range-low', -.187], ['range-typical', .041], ['range-high', .263]] as const)
    expect(text(id)).toContain(signedPct(v + offset)); }
function geometry() { return [...document.querySelectorAll('svg path,svg circle,svg line,svg [data-mark]')].map(el => [el.tagName, ...['d', 'cx', 'cy', 'x1', 'y1', 'x2', 'y2', 'transform'].map(k => el.getAttribute(k))]); }
async function share(url: string) { let mailed: any = null; const old = globalThis.fetch; vi.stubGlobal('fetch', async (input: any, init: any) => { expect(String(input)).toBe('https://api.mailchannels.net/tx/v1/send'); mailed = JSON.parse(init.body); return new Response('{}', { status: 202 }); }); try {
    const response = await handleShare(new Request('https://portfoliosight.ai/api/share', { method: 'POST', headers: { origin: 'https://portfoliosight.ai', 'content-type': 'application/json', 'cf-connecting-ip': '192.0.2.1' }, body: JSON.stringify({ to: 'frozen-gate@example.invalid', url }) }), { SHARE_FROM: 'gate@example.invalid', MAILCHANNELS_API_KEY: 'inert', MAILCHANNELS_DKIM_PRIVATE_KEY: 'inert' }, async () => true);
    expect(response.status).toBe(202);
    expect(mailed).not.toBeNull();
    const sent = mailed.content.find((x: any) => x.type === 'text/plain').value;
    expect(sent).toContain(url);
    return url;
}
finally {
    vi.stubGlobal('fetch', old);
} }
it('A-SE-20 all measures read their own fields and retain state', async () => {
    for (const e of ['replay', 'garch'] as const)
        for (const d of [0, 1, .5]) {
            const t = sentinel('guide2017', '5y', true);
            await open(t, `?u=guide2017&lb=5y&r=20&d=${d}&e=${e}`);
            expect(screen.queryByTestId('measure-enb')).toBeNull();
            fireEvent.click(screen.getByTestId('details-toggle'));
            const geo = geometry();
            let colors: any = null;
            let enbColors: any = null;
            for (const m of ['dr2', 'enb', 'enlc'] as const) {
                const before = requests.length;
                fireEvent.click(screen.getByTestId(`measure-${m}`));
                expect(geometry()).toEqual(geo);
                expect(screen.getByTestId(`measure-${m}`).getAttribute('aria-checked') ?? String((screen.getByTestId(`measure-${m}`) as HTMLInputElement).checked)).toBe('true');
                const legend = text('chart-legend');
                const detail = document.querySelector('.details-panel')?.textContent ?? '';
                if (m === 'dr2') {
                    expect(legend).toMatch(/diversification ratio/i);
                    expect(detail).toContain('2.1');
                    colors = structuredClone(paint);
                    expect(colors.length).toBeGreaterThan(10);
                    expect(text('div-word')).toBe('Fair');
                }
                if (m === 'enb') {
                    expect(legend).toMatch(/torsion|minimum|spread/i);
                    expect(detail).toContain('8.7');
                    expect(paint).not.toEqual(colors);
                    enbColors = structuredClone(paint);
                    expect(text('div-word')).toBe('Poor');
                }
                if (m === 'enlc') {
                    expect(paint).toEqual(enbColors);
                    expect(legend).toMatch(/map:.*(torsion|diversification)/i);
                    expect(detail).toContain(e === 'replay' ? '1.3' : '3.3');
                    expect(detail).toContain(t.universe.funds[e === 'replay' ? 0 : 1].id);
                    expect(detail).not.toContain(t.universe.funds[e === 'replay' ? 1 : 0].id + ': gained');
                }
                await act(async () => { await new Promise(r => setTimeout(r, 500)); });
                expect(requests.length).toBe(before);
                const query = location.search;
                const p = new URLSearchParams(query);
                expect(p.get('m')).toBe(m === 'enb' ? null : m);
                if (p.has('m'))
                    expect([...p.keys()].at(-1)).toBe('m');
                expect(reencodeShareUrl('https://portfoliosight.ai/' + query)).toBe('https://portfoliosight.ai/' + query);
                await share('https://portfoliosight.ai/' + query);
                const selectedWord = text('div-word');
                await open(t, query);
                expect(text('div-word')).toBe(selectedWord);
                expectFigures(e);
                expect((screen.getByTestId(`measure-${m}`) as HTMLInputElement).checked).toBe(true);
            }
        }
    // Independent shifted normalization and every boundary, including equality.
    for (const m of ['dr2', 'enb'] as const)
        for (const boundary of [.30, .50, .75])
            for (const epsilon of [-1e-8, 0, 1e-8]) {
                const t = sentinel('guide2017', '5y', true);
                const q = boundary + epsilon, ref = m === 'dr2' ? 5 : 9, value = 1 + q * (ref - 1);
                t.refs[m] = ref;
                if (m === 'enb')
                    t.enb_ref = ref;
                t.ladder[m] = t.ladder.w.map((c: any[]) => c.map(() => value));
                t.grid[m] = t.grid.z.map((c: any[]) => c.map(x => x === null ? null : value));
                if (t.ladder.measure === m) {
                    t.ladder.z = t.ladder[m];
                    t.grid.z = t.grid[m];
                }
                await open(t, `?u=guide2017&lb=5y&r=20&d=0&x=1&m=${m}`);
                const expected = q >= .75 ? 'Good' : q >= .50 ? 'Average' : q >= .30 ? 'Fair' : 'Poor';
                expect(text('div-word'), `${m} q=${q}`).toBe(expected);
            }
    const defaultDR2 = sentinel('guide2017', '5y', true);
    defaultDR2.ladder.measure = 'dr2';
    defaultDR2.ladder.z = defaultDR2.ladder.dr2;
    defaultDR2.grid.z = defaultDR2.grid.dr2;
    await open(defaultDR2, '?u=guide2017&lb=5y&r=20&d=0&x=1');
    expect((screen.getByTestId('measure-dr2') as HTMLInputElement).checked).toBe(true);
    expect(new URLSearchParams(location.search).has('m')).toBe(false);
    // No-loss ENLC has a named state and obtains its word from DR2, not an invented zero.
    const noLoss = sentinel('guide2017', '5y', true);
    for (const e of ['replay', 'garch']) {
        noLoss.ladder.loss_sources[e].n_eff = noLoss.ladder.w.map((c: any[]) => c.map(() => null));
        noLoss.ladder.loss_sources[e].top = noLoss.ladder.w.map((c: any[]) => c.map(() => []));
        noLoss.ladder.loss_sources[e].hedges = noLoss.ladder.w.map((c: any[]) => c.map(() => []));
    }
    await open(noLoss, '?u=guide2017&lb=5y&r=20&d=0&x=1&m=enlc');
    expect(document.body.textContent).toContain('no losses to share out');
    const fallbackWord = text('div-word');
    fireEvent.click(screen.getByTestId('measure-dr2'));
    expect(text('div-word')).toBe(fallbackWord);
    // An old delayed response cannot overwrite the selected engine's nearer-level placeholder.
    await open(sentinel('guide2017', '5y', true), '?u=guide2017&lb=5y&r=20.3&d=.37&x=1&m=enlc', false, true);
    await waitFor(() => expect(pending.length).toBeGreaterThan(0));
    const old = pending[0];
    fireEvent.click(screen.getByTestId('engine-garch'));
    await waitFor(() => expect(pending.some(p => p.body.engine === 'garch')).toBe(true));
    const current = pending.find(p => p.body.engine === 'garch');
    expect(document.querySelector('.details-panel')?.textContent).toContain('3.3');
    expect(document.querySelector('.details-panel')?.textContent).toContain(fixture.universe.funds[1].id);
    await act(async () => old.resolve({ engine: 'replay', bad: -.999, typical: -.888, good: -.777, loss_sources: { n_eff: 99, top: [], hedges: ['OLD-ENGINE'] } }));
    expect(document.body.textContent).not.toContain('OLD-ENGINE');
    expect(document.body.textContent).not.toContain('99.0');
    await act(async () => current.resolve({ engine: 'garch', bad: -.219, typical: .087, good: .429, loss_sources: { n_eff: 2.731, top: [{ id: fixture.universe.funds[3].id, share: .9 }], hedges: ['ACTIVE-HEDGE'] } }));
    await waitFor(() => expect(document.body.textContent).toContain('ACTIVE-HEDGE'));
    expect(text('range-low')).toContain(signedPct(-.219));
    expect(document.body.textContent).not.toContain('OLD-ENGINE');
    cleanup();
    vi.unstubAllGlobals();
});
"""


def test_a_se_20_measure_shared_state(tmp_path):
    if not _runtime():
        return
    _vitest(tmp_path, SOURCE)
