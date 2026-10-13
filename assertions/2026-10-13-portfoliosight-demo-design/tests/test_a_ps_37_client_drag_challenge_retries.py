# ruff: noqa: E501
"""A-PS-37 — no request during a drag, reload on an expired challenge, stop after three failures.

Vitest leg run from pytest (stdlib only). The embedded spec runs in vitest's plain node
environment (no jsdom) with fake timers; `fetch`, `history`, `location` and `localStorage` are
stubbed with `vi.stubGlobal`. `web/src/state/store.ts`, `web/src/state/url.ts` and
`web/src/api/client.ts` must import and run there: no `window`, no `document`.

Pinned interface
- `web/src/state/store.ts`: `createStore({search: string})` returns `{getState(), dispatch(action),
  subscribe(listener)}`; creating a store performs no I/O. `search` is the page's query string
  (spec §8.1), read through `decode` of `web/src/state/url.ts` (pinned by A-PS-36).
- Actions: `{type: "start"}` (load the menu named by the URL state; for a custom menu, `f=...`,
  this is one `POST /api/tensors`), `{type: "riskSlider", s}`, `{type: "divSlider", t}`,
  `{type: "setLookback", lookback}` (requests that lookback's tensor), `{type: "retryBuild"}`.
- State fields read here: `s: number`, `t: number | "auto"`, `lookback`, and
  `build: {status: "idle" | "building" | "ready" | "build-retry" | "build-failed-final",
  error: string | null}` (`error` is the server's `error` string of the `409` body).
- Network: the global `fetch(input, init)` with site-relative URLs; the `POST /api/tensors` body is
  a string in `init.body`, the JSON of spec §6 (`{"funds": [{"id", "min", "max"}], "lookback"}`).
  `POST` answers: `200 {"status": "ready", "url"}` (then `GET url` returns the tensor), `202
  {"status", "generation", "hash", ...}` (then `GET /api/tensors/{generation}/{hash}/{lookback}`
  every 2 s; polling uses that GET, never a re-POST), `409 {"status": "failed", "error",
  "attempts", "retry"}`. The same three answers are honoured on the polling GET.
- Timers: `setTimeout`/`setInterval` only (the test fakes them and `Date`).
- Challenge: a response with `cf-mitigated: challenge` leads to exactly one
  `history.replaceState(_, _, url)` whose query decodes to the current state, then exactly one
  `location.reload()`, and no further `fetch`.

Ambient requests (`GET /api/presets`, `/api/symbols`, `/api/health`) are answered and are not
counted as polls. "Exactly three polls at 0, 2, 4 s" is accepted in both readings: requests at
0 (the POST), 2 and 4 s, or the POST followed by GETs at 0, 2 and 4 s.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"

SPEC_TS = r"""
import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const ORIGIN = "https://portfoliosight.ai";
const G = "2026-10-12-0.1.0";
const HASH = "0123456789abcdef";
const fixturePath = path.resolve(process.cwd(), "fixtures/guide2017_5y.json");
let TENSOR: any;
let IDS: string[] = [];
let DOMAIN = { s_safe: 0, s_max: 0 };
let SEARCH = "";
let R0 = 0;

type Call = { method: string; path: string; body: string | null; at: number };
type Event = { kind: "fetch" | "challenge" | "replace" | "reload"; detail: string };
let calls: Call[] = [];
let events: Event[] = [];
let tensorRoute: (call: Call) => Response = () => json(500, {});
let replaceState: any;
let reload: any;

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
const challenge = () =>
  new Response("<!doctype html><title>Just a moment...</title>", { status: 403, headers: { "content-type": "text/html", "cf-mitigated": "challenge" } });
const tensorFor = (lookback: string) => {
  const t = structuredClone(TENSOR);
  t.lookback.id = lookback;
  return t;
};
const tensorCalls = () => calls.filter((c) => c.path.startsWith("/api/tensors"));
const posts = () => calls.filter((c) => c.method === "POST" && c.path === "/api/tensors");
const lookbackOf = (p: string) => p.split("/").pop() as string;

// real macrotask turns: fake timers leave setImmediate alone, so this never moves the fake clock
async function flush() {
  for (let i = 0; i < 12; i++) await new Promise((resolve) => setImmediate(resolve));
}
async function advance(ms: number, step = 250) {
  for (let done = 0; done < ms; done += step) {
    await vi.advanceTimersByTimeAsync(Math.min(step, ms - done));
    await flush();
  }
}

function installGlobals(search: string) {
  calls = [];
  events = [];
  const fetchMock = vi.fn(async (input: any, init?: any) => {
    const href = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(href, ORIGIN);
    const method = String(init?.method ?? (typeof input === "object" && "method" in input ? input.method : "GET")).toUpperCase();
    const call: Call = { method, path: url.pathname, body: typeof init?.body === "string" ? init.body : null, at: Date.now() };
    calls.push(call);
    events.push({ kind: "fetch", detail: `${method} ${url.pathname}` });
    let res: Response;
    if (url.pathname.startsWith("/api/tensors")) res = tensorRoute(call);
    else if (url.pathname === "/api/presets") res = json(200, { generation: G, asof: TENSOR.asof, presets: [] });
    else if (url.pathname === "/api/symbols") res = json(200, { catalog_at: "2026-10-13T09:00:00Z", tiers_served: [1, 2, 3], symbols: TENSOR.universe.funds.map((f: any) => ({ id: f.id, name: f.name, kind: "etf", tier: 1, first_date: "2010-01-04" })) });
    else if (url.pathname === "/api/health") res = json(200, { status: "ok", version: "0.1.0", generation: G, asof: TENSOR.asof, asof_trading_days_behind: 0, queue: { depth: 0, building: false }, nightly: {} });
    else res = json(404, { error: { code: "not_found", message: "not found", details: null } });
    if (res.headers.get("cf-mitigated") === "challenge") events.push({ kind: "challenge", detail: url.pathname });
    return res;
  });
  replaceState = vi.fn((_state: unknown, _title: unknown, url?: unknown) => {
    events.push({ kind: "replace", detail: String(url) });
  });
  reload = vi.fn(() => {
    events.push({ kind: "reload", detail: "" });
  });
  const memory = new Map<string, string>();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("history", { replaceState, pushState: vi.fn(), state: null, length: 1 });
  vi.stubGlobal("location", { href: `${ORIGIN}/${search}`, origin: ORIGIN, protocol: "https:", host: "portfoliosight.ai", hostname: "portfoliosight.ai", pathname: "/", search, hash: "", reload, assign: vi.fn(), replace: vi.fn() });
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => (memory.has(k) ? (memory.get(k) as string) : null),
    setItem: (k: string, v: string) => void memory.set(k, String(v)),
    removeItem: (k: string) => void memory.delete(k),
    clear: () => memory.clear(),
  });
}

async function boot(search: string) {
  installGlobals(search);
  vi.resetModules();
  const mod: any = await import("../../src/state/store");
  expect(typeof mod.createStore, "store.ts must export createStore").toBe("function");
  const store = mod.createStore({ search });
  await flush();
  expect(calls.length, "creating a store must not touch the network").toBe(0);
  return store;
}

// server behaviours for the /api/tensors routes
const readyRoute = (call: Call): Response =>
  call.method === "POST"
    ? json(200, { status: "ready", generation: G, hash: HASH, url: `/api/tensors/${G}/${HASH}/${JSON.parse(call.body as string).lookback}` })
    : json(200, tensorFor(lookbackOf(call.path)));
const building = () => json(202, { status: "building", generation: G, hash: HASH, position: 0, eta_s: 4 });
function failingRoute(mode: "post" | "poll") {
  let failures = 0;
  return (call: Call): Response => {
    if (call.method === "POST" && mode === "poll") return building();
    failures += 1;
    return json(409, { status: "failed", error: "solver_failed", attempts: failures, retry: failures < 3 });
  };
}

async function loadReady() {
  tensorRoute = readyRoute;
  const store = await boot(SEARCH);
  store.dispatch({ type: "start" });
  await flush();
  await advance(500);
  expect(store.getState().build.status).toBe("ready");
  return store;
}

async function decodedUrl(detail: string) {
  const url = new URL(detail, `${ORIGIN}/`);
  expect(url.origin).toBe(ORIGIN);
  expect(url.pathname).toBe("/");
  const codec: any = await import("../../src/state/url");
  return { search: url.search, state: codec.decode(url.search) };
}
function expectSameState(got: any, want: any) {
  const strip = (s: any) => ({ ...s, r: null, d: null });
  expect(strip(got)).toEqual(strip(want));
  expect(typeof got.r).toBe("number");
  expect(Math.abs(got.r - want.r)).toBeLessThanOrEqual(1e-9);
  expect(typeof got.d).toBe("number");
  expect(Math.abs(got.d - want.d)).toBeLessThanOrEqual(1e-9);
}

describe("A-PS-37", () => {
  beforeAll(() => {
    expect(fs.existsSync(fixturePath), "web/fixtures/guide2017_5y.json is missing").toBe(true);
    TENSOR = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));
    IDS = TENSOR.universe.funds.map((f: any) => f.id);
    DOMAIN = { s_safe: TENSOR.frontier.s_safe, s_max: TENSOR.frontier.x.length - 1 };
    R0 = Math.round(((DOMAIN.s_safe + DOMAIN.s_max) / 2) * 1000) / 1000;
    SEARCH = `?f=${IDS[0]}:60,${IDS[1]}:40&c=${IDS[0]}::50&lb=3y&g=10y&r=${R0}&d=0.4&t=hud&x=1`;
  });
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"] });
    vi.setSystemTime(new Date("2026-10-13T12:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("50 slider actions cause no request", async () => {
    const store = await loadReady();
    expect(posts().length).toBe(1);
    const body = JSON.parse(posts()[0].body as string);
    expect(body.lookback).toBe("3y");
    expect(body.funds.map((f: any) => f.id).sort()).toEqual([IDS[0], IDS[1]].sort());
    await advance(1000);
    const before = calls.length;
    const span = DOMAIN.s_max - DOMAIN.s_safe;
    let lastS = NaN;
    let lastT = NaN;
    let moved = 0;
    for (let i = 0; i < 50; i++) {
      if (i % 2 === 0) {
        lastS = DOMAIN.s_safe + (span * (i + 1)) / 60;
        store.dispatch({ type: "riskSlider", s: lastS });
        expect(Math.abs(store.getState().s - lastS), "riskSlider must move s").toBeLessThanOrEqual(1e-12);
      } else {
        lastT = (i + 1) / 60;
        store.dispatch({ type: "divSlider", t: lastT });
        expect(Math.abs(store.getState().t - lastT), "divSlider must move t").toBeLessThanOrEqual(1e-12);
      }
      moved += 1;
      expect(calls.length, `a request was made during the drag (action ${i})`).toBe(before);
      if (i % 10 === 9) await advance(300, 100);
    }
    await advance(5000);
    expect(moved).toBe(50);
    expect(calls.length).toBe(before);
    expect(calls.slice(before).map((c) => `${c.method} ${c.path}`)).toEqual([]);
    expect(store.getState().build.status).toBe("ready");
  });

  it("a 202 is polled every 2 s until 200", async () => {
    let t0 = 0;
    tensorRoute = (call) => {
      if (call.method === "POST") return building();
      return call.at - t0 < 4000 ? building() : json(200, tensorFor(lookbackOf(call.path)));
    };
    const store = await boot(SEARCH);
    t0 = Date.now();
    store.dispatch({ type: "start" });
    await flush();
    await advance(1000);
    expect(store.getState().build.status).toBe("building");
    expect(store.getState().build.status).not.toBe("ready");
    await advance(7000);
    const seen = tensorCalls();
    expect(seen[0].method).toBe("POST");
    expect(seen[0].path).toBe("/api/tensors");
    expect(seen[0].at - t0).toBe(0);
    const gets = seen.slice(1);
    for (const g of gets) {
      expect(g.method, "polling must use the GET, never a re-POST").toBe("GET");
      expect(g.path).toBe(`/api/tensors/${G}/${HASH}/3y`);
    }
    const times = gets.map((g) => g.at - t0);
    const threeRequests = JSON.stringify(times) === JSON.stringify([2000, 4000]);
    const threeGets = JSON.stringify(times) === JSON.stringify([0, 2000, 4000]);
    expect(threeRequests || threeGets, `poll times after the POST: ${JSON.stringify(times)}`).toBe(true);
    expect(posts().length).toBe(1);
    expect(store.getState().build.status).toBe("ready");
    const settled = tensorCalls().length;
    await advance(20000, 500);
    expect(tensorCalls().length, "polling went on after the 200").toBe(settled);
  });

  it("a 409 gives build-retry with the server's code and Retry re-POSTs the identical body", async () => {
    tensorRoute = failingRoute("poll");
    const store = await boot(SEARCH);
    store.dispatch({ type: "start" });
    await flush();
    await advance(4000);
    expect(store.getState().build.status).toBe("build-retry");
    expect(store.getState().build.error).toBe("solver_failed");
    expect(posts().length).toBe(1);
    const quiet = tensorCalls().length;
    await advance(10000, 500);
    expect(tensorCalls().length, "polling went on after the 409").toBe(quiet);
    store.dispatch({ type: "retryBuild" });
    await flush();
    expect(posts().length).toBe(2);
    expect(typeof posts()[0].body).toBe("string");
    expect(posts()[1].body).toBe(posts()[0].body);
    expect(JSON.parse(posts()[1].body as string).lookback).toBe("3y");
    expect(store.getState().build.status).not.toBe("build-failed-final");
  });

  for (const mode of ["post", "poll"] as const) {
    it(`three 409s (${mode}) end in build-failed-final with no fourth POST`, async () => {
      tensorRoute = failingRoute(mode);
      const store = await boot(SEARCH);
      store.dispatch({ type: "start" });
      await flush();
      await advance(4000);
      for (let attempt = 1; attempt <= 2; attempt++) {
        expect(store.getState().build.status, `after failure ${attempt}`).toBe("build-retry");
        expect(posts().length).toBe(attempt);
        store.dispatch({ type: "retryBuild" });
        await flush();
        await advance(4000);
      }
      expect(posts().length).toBe(3);
      expect(store.getState().build.status).toBe("build-failed-final");
      expect(new Set(posts().map((p) => p.body)).size, "the three POST bodies differ").toBe(1);
      const quiet = calls.length;
      await advance(60000, 1000);
      expect(calls.length, "requests continued after the final failure").toBe(quiet);
      expect(vi.getTimerCount(), "a polling timer is still scheduled after the final failure").toBe(0);
      store.dispatch({ type: "retryBuild" });
      await flush();
      store.dispatch({ type: "retryBuild" });
      await advance(10000, 1000);
      expect(posts().length, "a fourth POST was sent").toBe(3);
      expect(posts().length).not.toBeGreaterThan(3);
      expect(tensorCalls().length).toBe(tensorCalls().filter((c) => c.at <= calls[quiet - 1].at).length);
      expect(store.getState().build.status).toBe("build-failed-final");
    });
  }

  for (const where of ["on the POST", "on a poll", "after the sliders moved and the lookback changed"] as const) {
    it(`a challenge ${where} writes the state to the URL, reloads once and resumes the same build`, async () => {
      const codec: any = await import("../../src/state/url");
      const want = codec.decode(SEARCH);
      let store: any;
      if (where === "on the POST") {
        tensorRoute = (call) => (call.method === "POST" ? challenge() : building());
        store = await boot(SEARCH);
        store.dispatch({ type: "start" });
      } else if (where === "on a poll") {
        tensorRoute = (call) => (call.method === "POST" ? building() : challenge());
        store = await boot(SEARCH);
        store.dispatch({ type: "start" });
      } else {
        store = await loadReady();
        const s1 = Math.round((DOMAIN.s_safe + (DOMAIN.s_max - DOMAIN.s_safe) * 0.8) * 1000) / 1000;
        store.dispatch({ type: "riskSlider", s: s1 });
        store.dispatch({ type: "divSlider", t: 0.125 });
        await advance(1000);
        want.r = s1;
        want.d = 0.125;
        want.lookback = "1y";
        tensorRoute = (call) => (call.method === "POST" ? challenge() : json(200, tensorFor(lookbackOf(call.path))));
        store.dispatch({ type: "setLookback", lookback: "1y" });
      }
      await flush();
      await advance(4000);
      const at = events.findIndex((e) => e.kind === "challenge");
      expect(at, "the challenge response was never served").toBeGreaterThanOrEqual(0);
      const reloadAt = events.findIndex((e) => e.kind === "reload");
      expect(reloadAt, "location.reload was not called after the challenge").toBeGreaterThan(at);
      const between = events.slice(at + 1, reloadAt);
      expect(between.filter((e) => e.kind === "replace").length, "replaceState must be called once between the challenge and the reload").toBe(1);
      expect(between.filter((e) => e.kind === "fetch")).toEqual([]);
      const written = await decodedUrl(between.filter((e) => e.kind === "replace")[0].detail);
      expectSameState(written.state, want);
      const lastPost = posts()[posts().length - 1];
      expect(JSON.parse(lastPost.body as string).lookback).toBe(want.lookback);
      await advance(30000, 1000);
      const after = events.slice(reloadAt + 1);
      expect(after.filter((e) => e.kind === "fetch").map((e) => e.detail), "the client kept requesting after the reload (a retry loop)").toEqual([]);
      expect(reload).toHaveBeenCalledTimes(1);
      expect(events.filter((e) => e.kind === "reload").length).not.toBeGreaterThan(1);

      // the reloaded page, opened on the URL that was written, asks for the same build
      vi.clearAllTimers();
      tensorRoute = () => building();
      const resumed = await boot(written.search);
      resumed.dispatch({ type: "start" });
      await flush();
      expect(posts().length).toBe(1);
      expect(posts()[0].body, "the resumed POST body differs from the interrupted one").toBe(lastPost.body);
      await advance(2000);
      const poll = tensorCalls().find((c) => c.method === "GET");
      expect(poll?.path).toBe(`/api/tensors/${G}/${HASH}/${want.lookback}`);
    });
  }
});
"""
EXPECTED_TITLES = {
    "50 slider actions cause no request",
    "a 202 is polled every 2 s until 200",
    "a 409 gives build-retry with the server's code and Retry re-POSTs the identical body",
    "three 409s (post) end in build-failed-final with no fourth POST",
    "three 409s (poll) end in build-failed-final with no fourth POST",
    "a challenge on the POST writes the state to the URL, reloads once and resumes the same build",
    "a challenge on a poll writes the state to the URL, reloads once and resumes the same build",
    "a challenge after the sliders moved and the lookback changed writes the state to the URL, reloads once and resumes the same build",
}


def _run_vitest(name: str, source: str, timeout: int = 300) -> dict[str, str]:
    """Run one embedded vitest file inside web/ and return {test title: status}."""
    assert (WEB / "package.json").is_file(), (
        "web/package.json is missing: the front end is not built yet"
    )
    vitest = WEB / "node_modules" / ".bin" / "vitest"
    assert vitest.exists(), "web/node_modules/.bin/vitest is missing: run `npm ci` in web/"
    gate_dir = WEB / "tests" / "__gate__"
    spec = gate_dir / f"{name}.test.ts"
    report = None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.json"
        try:
            gate_dir.mkdir(parents=True, exist_ok=True)
            spec.write_text(source, encoding="utf-8")
            proc = subprocess.run(
                [
                    str(vitest),
                    "run",
                    f"tests/__gate__/{name}.test.ts",
                    "--reporter=json",
                    f"--outputFile={out}",
                ],
                cwd=WEB,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if out.exists():
                report = json.loads(out.read_text(encoding="utf-8"))
        finally:
            spec.unlink(missing_ok=True)
            if gate_dir.is_dir() and not any(gate_dir.iterdir()):
                gate_dir.rmdir()
    tail = proc.stdout[-6000:] + proc.stderr[-3000:]
    assert report is not None, f"vitest wrote no JSON report:\n{tail}"
    statuses: dict[str, str] = {}
    for file_result in report.get("testResults", []):
        for case in file_result.get("assertionResults", []):
            statuses[case["title"]] = case["status"]
            if case["status"] != "passed":
                print(case["title"], "\n".join(case.get("failureMessages") or [])[:3000])
        if file_result.get("status") != "passed":
            print(file_result.get("message", ""))
    print(tail)
    return statuses


def test_a_ps_37_vitest():
    statuses = _run_vitest("a_ps_37", SPEC_TS)
    assert set(statuses) == EXPECTED_TITLES, (
        f"vitest ran a different set of tests: {sorted(statuses)}"
    )
    not_passed = {title: status for title, status in statuses.items() if status != "passed"}
    assert not not_passed, f"vitest legs not passed (failed, skipped or todo): {not_passed}"
