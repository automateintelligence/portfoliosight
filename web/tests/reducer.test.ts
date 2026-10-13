import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { portfolioMath } from "../src/math/portfolio";
import { ceilingAt } from "../src/math/view";
import { parseTensor } from "../src/api/client";
import { createStore, currentMix, type Store } from "../src/state/store";
import { decode } from "../src/state/url";

const RAW = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8"));
const TENSOR = parseTensor(structuredClone(RAW));
const G = RAW.generation as string;
const H1 = RAW.universe.hash as string;
const H2 = "00000000000000aa";
const IDS: string[] = RAW.universe.funds.map((f: { id: string }) => f.id);
const LBS = ["1y", "2y", "3y", "5y", "10y", "ew"];
const DOMAIN = portfolioMath(TENSOR).riskSliderDomain();

type Call = { method: string; path: string; body: string | null };
let calls: Call[] = [];
let replaced: string[] = [];
let health: () => Response;
let tensorRoute: (call: Call) => Response;
let presetsAsof = RAW.asof as string;

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
const lookbacks = (hash: string) => Object.fromEntries(LBS.map((lb) => [lb, { status: "ready", url: `/api/tensors/${G}/${hash}/${lb}` }]));
const allocation = Object.fromEntries(IDS.slice(0, 6).map((id, i) => [id, 1000 * (i + 1)]));
const presetsBody = () => ({
  generation: G,
  asof: presetsAsof,
  presets: [
    { id: "guide2017", name: "The 2017 guide portfolio", hash: H1, funds: RAW.universe.funds.map((f: { id: string; name: string }) => ({ id: f.id, name: f.name })), allocation, allocation_unit: "$", lookbacks: lookbacks(H1) },
    { id: "tsp", name: "TSP (G, F, C, S, I)", hash: H2, funds: RAW.universe.funds.slice(0, 5).map((f: { id: string; name: string }) => ({ id: f.id, name: f.name })), allocation: null, allocation_unit: null, lookbacks: lookbacks(H2) },
  ],
});
const tensorFor = (lookback: string, patch: (t: typeof RAW) => void = () => undefined) => {
  const t = structuredClone(RAW);
  t.lookback.id = lookback;
  patch(t);
  return t;
};

async function flush() {
  for (let i = 0; i < 12; i++) await new Promise((resolve) => setImmediate(resolve));
}
async function advance(ms: number) {
  for (let done = 0; done < ms; done += 250) {
    await vi.advanceTimersByTimeAsync(250);
    await flush();
  }
}
async function boot(search: string): Promise<Store> {
  const store = createStore({ search });
  store.dispatch({ type: "start" });
  await flush();
  await advance(500);
  return store;
}
const tensorCalls = () => calls.filter((c) => c.path.startsWith("/api/tensors"));

beforeEach(() => {
  calls = [];
  replaced = [];
  presetsAsof = RAW.asof;
  health = () => json(200, { asof: RAW.asof, asof_trading_days_behind: 0 });
  tensorRoute = (call) => (call.method === "POST" ? json(200, { status: "ready", url: `/api/tensors/${G}/${H1}/${JSON.parse(call.body as string).lookback}` }) : json(200, tensorFor(call.path.split("/").pop() as string)));
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  vi.setSystemTime(new Date(`${RAW.asof}T20:00:00Z`));
  vi.stubGlobal("fetch", async (input: string, init?: RequestInit) => {
    const url = new URL(input, "https://portfoliosight.ai");
    const call = { method: (init?.method ?? "GET").toUpperCase(), path: url.pathname, body: typeof init?.body === "string" ? init.body : null };
    calls.push(call);
    if (url.pathname === "/api/presets") return json(200, presetsBody(), { "x-ps-preview": "1" });
    if (url.pathname === "/api/symbols") return json(200, { symbols: IDS.map((id) => ({ id, name: id })) });
    if (url.pathname === "/api/health") return health();
    if (url.pathname.startsWith("/api/tensors")) return tensorRoute(call);
    return json(404, {});
  });
  vi.stubGlobal("history", { state: null, replaceState: (_s: unknown, _t: unknown, url: string) => void replaced.push(String(url)) });
  vi.stubGlobal("location", { pathname: "/", search: "", reload: vi.fn() });
  const memory = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (k: string) => memory.get(k) ?? null, setItem: (k: string, v: string) => void memory.set(k, v) });
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("store: default view", () => {
  it("with no query loads the first preset's declared 5y tensor and nothing else", async () => {
    const store = await boot("");
    const s = store.getState();
    expect(s.build.status).toBe("ready");
    expect(s.preset).toBe("guide2017");
    expect(s.unit).toBe("usd");
    expect(s.rows.length).toBe(IDS.length);
    expect(tensorCalls().map((c) => `${c.method} ${c.path}`)).toEqual([`GET /api/tensors/${G}/${H1}/5y`]);
    expect(s.previewOn).toBe(true);
  });

  it("starts where the ceiling equals the entered mix's risk, and a URL r wins over that", async () => {
    const store = await boot("");
    const s = store.getState();
    const mix = currentMix(s, TENSOR);
    expect(mix.weights).not.toBeNull();
    const sigma = portfolioMath(TENSOR).stats(mix.weights as number[]).sigma;
    const want = Math.min(DOMAIN.s_max, Math.max(DOMAIN.s_safe, s.s));
    expect(s.s).toBe(want);
    if (sigma > ceilingAt(TENSOR, DOMAIN.s_safe) && sigma < ceilingAt(TENSOR, DOMAIN.s_max)) expect(ceilingAt(TENSOR, s.s)).toBeCloseTo(sigma, 12);
    expect(s.t).toBe("auto");

    const withR = await boot("?u=guide2017&r=30.5&d=0.25");
    expect(withR.getState().s).toBe(30.5);
    expect(withR.getState().t).toBe(0.25);
  });

  it("without an allocation starts at the middle of the domain", async () => {
    const store = await boot("?u=tsp");
    expect(store.getState().s).toBeCloseTo((DOMAIN.s_safe + DOMAIN.s_max) / 2, 12);
    expect(currentMix(store.getState(), TENSOR).status).toBe("empty");
  });

  it("writes the view to the address after it loads, with only spec 8.1 keys", async () => {
    await boot("");
    expect(replaced.length).toBeGreaterThanOrEqual(1);
    const last = new URL(replaced[replaced.length - 1], "https://portfoliosight.ai");
    const state = decode(last.search);
    expect(state.preset).toBe("guide2017");
    expect(state.unit).toBe("usd");
    expect(state.d).toBe("auto");
    expect(state.theme).toBe("ks-dark");
    expect(typeof state.r).toBe("number");
  });
});

describe("store: transitions", () => {
  it("a position outside the tensor's domain is clamped and the diversification position returns to suggested", async () => {
    expect(DOMAIN.s_safe).toBeGreaterThan(0.1);
    const outside = await boot("?u=guide2017&r=0.1&d=0.5");
    expect(outside.getState().s).toBe(DOMAIN.s_safe);
    expect(outside.getState().t).toBe("auto");
    const above = await boot("?u=guide2017&r=99&d=0.5");
    expect(above.getState().s).toBe(DOMAIN.s_max);
    expect(above.getState().t).toBe("auto");
    // inside the domain both are kept, also across a lookback switch (clamped on every tensor load)
    const inside = await boot("?u=guide2017&r=20&d=0.5");
    inside.dispatch({ type: "setLookback", lookback: "1y" });
    await flush();
    await advance(500);
    expect(inside.getState().lookback).toBe("1y");
    expect(inside.getState().tensor!.lookback.id).toBe("1y");
    expect(inside.getState().s).toBe(20);
    expect(inside.getState().t).toBe(0.5);
  });

  it("a 422 for one window marks only that window and keeps the view", async () => {
    const store = await boot("?f=" + IDS.slice(0, 3).join(","));
    const before = store.getState().tensor;
    tensorRoute = (call) =>
      call.method === "POST" && JSON.parse(call.body as string).lookback === "10y"
        ? json(422, { error: { code: "invalid_request", message: "x", details: { reason: "not enough shared history" } } })
        : call.method === "POST"
          ? json(200, { status: "ready", url: `/api/tensors/${G}/${H1}/${JSON.parse(call.body as string).lookback}` })
          : json(200, tensorFor(call.path.split("/").pop() as string));
    store.dispatch({ type: "setLookback", lookback: "10y" });
    await flush();
    let s = store.getState();
    expect(s.unavailable).toEqual({ "10y": "not enough shared history" });
    expect(s.lookback).toBe("5y");
    expect(s.tensor).toBe(before);
    expect(s.build.status).toBe("ready");
    const n = calls.length;
    store.dispatch({ type: "setLookback", lookback: "10y" });
    await flush();
    expect(calls.length, "an unavailable window is not requested again").toBe(n);
    store.dispatch({ type: "setLookback", lookback: "1y" });
    await flush();
    await advance(500);
    s = store.getState();
    expect(s.lookback).toBe("1y");
    expect(s.tensor!.lookback.id).toBe("1y");
  });

  it("generation_gone ends the build at once with the server's code", async () => {
    tensorRoute = () => json(409, { status: "failed", error: "generation_gone", attempts: 1, retry: false });
    const store = await boot("?f=" + IDS.slice(0, 2).join(","));
    expect(store.getState().build).toMatchObject({ status: "build-failed-final", error: "generation_gone" });
    const n = calls.length;
    store.dispatch({ type: "retryBuild" });
    await flush();
    expect(calls.length).toBe(n);
  });

  it("unknown symbols are named and nothing is drawn for them", async () => {
    tensorRoute = () => json(400, { error: { code: "unknown_symbols", message: "unknown", details: { symbols: ["QQQQ"] } } });
    const store = await boot("?f=" + IDS.slice(0, 2).join(","));
    expect(store.getState().menuError).toContain("QQQQ");
    expect(store.getState().tensor).toBeNull();
  });

  it("every fund of the menu is sent; the service decides which it cannot use", async () => {
    await boot("?f=" + [IDS[0], IDS[1], "FIENX"].join(","));
    const body = JSON.parse(calls.find((c) => c.method === "POST")!.body as string);
    expect(body.funds.map((f: { id: string }) => f.id)).toEqual([IDS[0], IDS[1], "FIENX"]);
  });

  it("a window the service reports as unavailable (409 on the poll) is disabled and the view carries on", async () => {
    const store = await boot("?f=" + IDS.slice(0, 3).join(","));
    const before = store.getState().tensor;
    const gone = { status: "failed", error: "window_unavailable", attempts: 1, retry: false, details: { lookback: "10y", reason: "not enough shared history", rows: 40 } };
    tensorRoute = (call) => {
      const lb = call.method === "POST" ? JSON.parse(call.body as string).lookback : (call.path.split("/").pop() as string);
      if (lb !== "10y") return call.method === "POST" ? json(200, { status: "ready", url: `/api/tensors/${G}/${H1}/${lb}` }) : json(200, tensorFor(lb));
      return call.method === "POST" ? json(202, { status: "queued", generation: G, hash: H1, position: 1, eta_s: 30 }) : json(409, gone);
    };
    store.dispatch({ type: "setLookback", lookback: "10y" });
    await flush();
    expect(store.getState().build.status).toBe("building");
    await advance(2500);
    const s = store.getState();
    expect(s.unavailable).toEqual({ "10y": "not enough shared history" });
    expect(s.lookback).toBe("5y");
    expect(s.tensor).toBe(before);
    expect(s.build.status).toBe("ready");
    expect(vi.getTimerCount(), "no poll is left running").toBe(0);
    store.dispatch({ type: "setLookback", lookback: "2y" });
    await flush();
    await advance(500);
    expect(store.getState().tensor!.lookback.id).toBe("2y");
  });

  it("limits that cannot be met keep the view and say so, without a retry prompt", async () => {
    const store = await boot("");
    const before = store.getState().tensor;
    tensorRoute = () => json(409, { status: "failed", error: "caps_infeasible", attempts: 1, retry: false, details: null });
    store.dispatch({ type: "setCaps", caps: [{ id: IDS[0], min: 90, max: null }] });
    await flush();
    await advance(500);
    expect(store.getState().build.status).toBe("ready");
    expect(store.getState().menuError).toContain("limits");
    expect(store.getState().tensor).toBe(before);
  });

  it("limits that cannot be met for a newly chosen window leave the shown window selected", async () => {
    const store = await boot("?f=" + IDS.slice(0, 3).join(",") + "&c=" + IDS[0] + "::50");
    tensorRoute = () => json(409, { status: "failed", error: "caps_infeasible", attempts: 1, retry: false, details: null });
    store.dispatch({ type: "setLookback", lookback: "10y" });
    await flush();
    await advance(500);
    expect(store.getState().lookback).toBe("5y");
    expect(store.getState().tensor!.lookback.id).toBe("5y");
    expect(decode(new URL(replaced[replaced.length - 1], "https://portfoliosight.ai").search).lookback).toBe("5y");
  });

  it("an explicit percent unit on a dollar preset reopens in percent", async () => {
    const store = await boot("?u=guide2017&unit=pct");
    expect(store.getState().unit).toBe("pct");
    const search = new URL(replaced[replaced.length - 1], "https://portfoliosight.ai").search;
    expect((await boot(search)).getState().unit).toBe("pct");
  });

  it("a challenge reported by another request writes the address once and reloads once", async () => {
    const store = await boot("");
    await advance(500);
    const writes = replaced.length;
    store.dispatch({ type: "challenged" });
    store.dispatch({ type: "challenged" });
    expect(replaced.length).toBe(writes + 1);
    expect((location.reload as ReturnType<typeof vi.fn>).mock.calls.length).toBe(1);
  });

  it("percentages at the edge of the 100% rule give a mix, as the Funds table says they do", () => {
    const rows = [
      { id: IDS[0], name: "a", amount: 49.98 },
      { id: IDS[1], name: "b", amount: 49.97 },
    ];
    expect(currentMix({ rows, unit: "pct" }, TENSOR).status).toBe("ok");
    expect(currentMix({ rows: [rows[0], { ...rows[1], amount: 49.9 }], unit: "pct" }, TENSOR).status).toBe("invalid_total");
  });

  it("a window the presets body declares unavailable settles the build status even mid-load", async () => {
    const body = presetsBody();
    (body.presets[0].lookbacks as Record<string, { status: string; url?: string }>)["10y"] = { status: "unavailable" };
    const realFetch = globalThis.fetch;
    vi.stubGlobal("fetch", async (input: string, init?: RequestInit) => (input === "/api/presets" ? json(200, body) : realFetch(input, init)));
    const store = await boot("");
    tensorRoute = (call) => (call.method === "GET" ? json(202, { status: "building", generation: G, hash: H1, position: 0, eta_s: 5 }) : json(500, {}));
    store.dispatch({ type: "setLookback", lookback: "1y" });
    await flush();
    expect(store.getState().build.status).toBe("building");
    store.dispatch({ type: "setLookback", lookback: "10y" });
    await flush();
    await advance(5000);
    expect(store.getState().build.status).toBe("ready");
    expect(store.getState().unavailable["10y"]).toBe("not enough shared history");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("before the first generation the store reports that data is not loaded yet", async () => {
    vi.stubGlobal("fetch", async (input: string) =>
      input === "/api/health"
        ? json(200, { status: "initializing", generation: null, asof: null, asof_trading_days_behind: null })
        : json(503, { error: { code: "no_generation", message: "No generation has been published yet.", details: null } }),
    );
    const store = await boot("");
    expect(store.getState().loadError).toContain("not loaded yet");
    expect(store.getState().build.status).toBe("idle");
    expect(store.getState().staleness).toBeNull();
  });

  it("a cap edit posts the policy as fractions, and a reset posts the all-default policy", async () => {
    const store = await boot("");
    store.dispatch({ type: "setCaps", caps: [{ id: IDS[0], min: null, max: 10 }] });
    await flush();
    await advance(500);
    let post = JSON.parse(calls.filter((c) => c.method === "POST").pop()!.body as string);
    expect(post.funds.find((f: { id: string }) => f.id === IDS[0])).toEqual({ id: IDS[0], min: null, max: 0.1 });
    store.dispatch({ type: "setCaps", caps: [] });
    await flush();
    await advance(500);
    post = JSON.parse(calls.filter((c) => c.method === "POST").pop()!.body as string);
    expect(post.funds.every((f: { min: unknown; max: unknown }) => f.min === null && f.max === null)).toBe(true);
    expect(calls.filter((c) => c.method === "POST").length).toBe(2);
  });

  it("editing an amount turns a preset into a custom menu without a request", async () => {
    const store = await boot("");
    const n = calls.length;
    store.dispatch({ type: "setAmount", id: IDS[0], amount: 5 });
    await advance(500);
    expect(calls.length).toBe(n);
    expect(store.getState().preset).toBeNull();
    const state = decode(new URL(replaced[replaced.length - 1], "https://portfoliosight.ai").search);
    expect(state.funds.find((f) => f.id === IDS[0])?.amount).toBe(5);
  });

  it("ghosts load only when asked, toggle both ways, and the primary window is never its own ghost", async () => {
    const store = await boot("?u=guide2017&g=1y");
    expect(tensorCalls().length).toBe(1);
    store.dispatch({ type: "loadGhosts" });
    await flush();
    expect(Object.keys(store.getState().ghostTensors)).toEqual(["1y"]);
    store.dispatch({ type: "toggleGhost", lookback: "1y" });
    expect(store.getState().ghosts).toEqual([]);
    store.dispatch({ type: "toggleGhost", lookback: "5y" });
    expect(store.getState().ghosts).toEqual([]);
  });

  it("a ghost that is still building is polled until its tensor arrives", async () => {
    const store = await boot("?f=" + IDS.slice(0, 3).join(","));
    let polls = 0;
    tensorRoute = (call) => {
      if (call.method === "POST") return json(202, { status: "queued", generation: G, hash: H1, position: 1, eta_s: 4 });
      polls += 1;
      return polls < 2 ? json(202, { status: "building", generation: G, hash: H1, position: 0, eta_s: 2 }) : json(200, tensorFor("1y"));
    };
    store.dispatch({ type: "toggleGhost", lookback: "1y" });
    await flush();
    expect(store.getState().ghosts).toEqual(["1y"]);
    expect(store.getState().ghostTensors["1y"]).toBeUndefined();
    await advance(4500);
    expect(polls).toBe(2);
    expect(store.getState().ghostTensors["1y"]?.lookback.id).toBe("1y");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("switching a dollar preset to percent stays percent after a reload of its address", async () => {
    const store = await boot("");
    store.dispatch({ type: "setUnit", unit: "pct" });
    await advance(500);
    const search = new URL(replaced[replaced.length - 1], "https://portfoliosight.ai").search;
    const again = await boot(search);
    expect(again.getState().unit).toBe("pct");
    expect(again.getState().rows.find((r) => r.id === IDS[0])?.amount).toBe(1000);
    // shares survive as a preset, because the address carries unit=shares
    const shares = await boot("");
    shares.dispatch({ type: "setUnit", unit: "shares" });
    expect(shares.getState().preset).toBe("guide2017");
  });

  it("theme and details are kept and stored", async () => {
    const store = await boot("?t=hud&x=1");
    expect(store.getState().theme).toBe("hud");
    expect(store.getState().details).toBe(true);
    store.dispatch({ type: "setTheme", theme: "light" });
    expect(localStorage.getItem("ps.theme")).toBe("light");
    const again = createStore({ search: "" });
    expect(again.getState().theme).toBe("light");
  });
});

describe("store: staleness (expectation F13)", () => {
  it("is set when health reports two or more trading days behind, and clear otherwise", async () => {
    health = () => json(200, { asof: "2026-10-07", asof_trading_days_behind: 3 });
    expect((await boot("")).getState().staleness).toEqual({ asof: "2026-10-07" });
    health = () => json(200, { asof: RAW.asof, asof_trading_days_behind: 1 });
    expect((await boot("")).getState().staleness).toBeNull();
  });

  it("falls back to the age of the presets date when health is unreachable", async () => {
    health = () => json(503, {});
    presetsAsof = "2026-10-01";
    expect((await boot("")).getState().staleness).toEqual({ asof: "2026-10-01" });
    presetsAsof = RAW.asof;
    expect((await boot("")).getState().staleness).toBeNull();
  });
});
