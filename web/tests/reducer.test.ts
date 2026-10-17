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
let tierRoute: () => Response;
let presetsAsof = RAW.asof as string;

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
const lookbacks = (hash: string) => Object.fromEntries(LBS.map((lb) => [lb, { status: "ready", url: `/api/tensors/${G}/${hash}/${lb}` }]));
const allocation = Object.fromEntries(IDS.slice(0, 6).map((id, i) => [id, 1000 * (i + 1)]));
const presetsBody = () => ({
  generation: G,
  asof: presetsAsof,
  presets: [
    { id: "guide2017", name: "Example Portfolio", hash: H1, funds: RAW.universe.funds.map((f: { id: string; name: string }) => ({ id: f.id, name: f.name })), allocation, allocation_unit: "$", lookbacks: lookbacks(H1) },
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
  tierRoute = () => json(404, {});
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
    if (url.pathname === "/api/tier") return tierRoute();
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

describe("store: menu size by access tier (engines spec 6.2)", () => {
  const link = (n: number) => `?f=${Array.from({ length: n }, (_, i) => `${IDS[i % IDS.length]}${i < IDS.length ? "" : `X${i}`}`).join(",")}&lb=5y&r=20&d=0.3`;
  const posted = () => tensorCalls().filter((c) => c.method === "POST").map((c) => (JSON.parse(c.body as string) as { funds: unknown[] }).funds.length);
  const admin = () => json(200, { tier: "admin", menu_max: 100 });

  it("is public with 30 funds until /api/tier says otherwise, and whenever it cannot answer", async () => {
    const store = await boot("");
    expect(store.getState().tier).toEqual({ tier: "public", menuMax: 30 });
    tierRoute = () => json(200, { tier: "admin", menu_max: "lots" });
    expect((await boot("")).getState().tier).toEqual({ tier: "public", menuMax: 30 });
    tierRoute = admin;
    expect((await boot("")).getState().tier).toEqual({ tier: "admin", menuMax: 100 });
  });

  it("a public visitor's link with 31 funds is refused whole: the default view and the message, no request for it", async () => {
    const store = await boot(link(31));
    const s = store.getState();
    expect(s.linkError).toBe("This menu has more funds than this site allows (30).");
    expect(posted()).toEqual([]);
    expect(s.preset).toBe("guide2017");
    expect(s.rows.length).toBe(IDS.length);
    expect(s.build.status).toBe("ready");
    expect(tensorCalls().map((c) => `${c.method} ${c.path}`)).toEqual([`GET /api/tensors/${G}/${H1}/5y`]);
    // the refused link's position is not carried over to the default view
    expect(s.t).toBe("auto");
    // choosing a menu clears the message
    store.dispatch({ type: "selectPreset", id: "tsp" });
    await flush();
    expect(store.getState().linkError).toBeNull();
  });

  it("a link with 30 funds opens for a public visitor", async () => {
    const store = await boot(link(30));
    expect(store.getState().linkError).toBeNull();
    expect(posted()).toEqual([30]);
  });

  it("an admin opens a 31- and a 100-fund link, and a 101-fund link is refused with the admin limit", async () => {
    tierRoute = admin;
    expect((await boot(link(31))).getState().linkError).toBeNull();
    expect((await boot(link(100))).getState().linkError).toBeNull();
    expect(posted()).toEqual([31, 100]);
    const refused = await boot(link(101));
    expect(refused.getState().linkError).toBe("This menu has more funds than this site allows (100).");
    expect(posted()).toEqual([31, 100]);
  });

  it("a menu over the tier's limit is never sent, and is not cut down either", async () => {
    const store = await boot("");
    const rows = (n: number) => Array.from({ length: n }, (_, i) => ({ id: `F${i}`, name: `F${i}`, amount: null }));
    store.dispatch({ type: "useMenu", rows: rows(31) });
    await flush();
    expect(posted()).toEqual([]);
    store.dispatch({ type: "useMenu", rows: rows(30) });
    await flush();
    expect(posted()).toEqual([30]);
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

describe("store: the simulation engine (engines spec 6)", () => {
  const OLD = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "tests/tensor-schema2.json"), "utf8"));
  // A tensor whose two engines have different slider domains whatever the fixture's numbers are.
  const domains = (t: typeof RAW) => {
    t.frontier.s_safe = 3;
    t.frontier.ranges.replay.s_safe = 3;
    t.frontier.ranges.garch.s_safe = 1;
  };
  const withoutGarch = (t: typeof RAW) => {
    t.engines.garch = { status: "unavailable", reason: "not enough shared history for the volatility model", method: null };
    delete t.frontier.ranges.garch;
    delete t.ladder.ranges.garch;
    delete t.entered.ranges.garch;
  };
  const serve = (patch: (t: typeof RAW) => void) => {
    tensorRoute = (call) =>
      call.method === "POST" ? json(200, { status: "ready", url: `/api/tensors/${G}/${H1}/${JSON.parse(call.body as string).lookback}` }) : json(200, tensorFor(call.path.split("/").pop() as string, patch));
  };
  const lastUrl = () => decode(new URL(replaced[replaced.length - 1], "https://portfoliosight.ai").search);

  it("starts on replay, and an address that names an engine opens on it", async () => {
    expect((await boot("")).getState().engine).toBe("replay");
    expect((await boot("?u=guide2017&e=garch")).getState().engine).toBe("garch");
    expect((await boot("?u=guide2017&e=foo")).getState().engine).toBe("replay");
  });

  it("setEngine writes e to the address, leaves it out for replay, and makes no request of any kind", async () => {
    const store = await boot("?u=guide2017&r=30");
    await advance(500);
    const before = calls.length;
    store.dispatch({ type: "setEngine", engine: "garch" });
    expect(store.getState().engine).toBe("garch");
    await advance(500);
    expect(calls.length, "no request on an engine change").toBe(before);
    expect(lastUrl().engine).toBe("garch");
    expect(new URL(replaced[replaced.length - 1], "https://portfoliosight.ai").search).toMatch(/&e=garch$/);
    store.dispatch({ type: "setEngine", engine: "replay" });
    await advance(500);
    expect(calls.length).toBe(before);
    expect(new URL(replaced[replaced.length - 1], "https://portfoliosight.ai").searchParams.has("e")).toBe(false);
  });

  it("a reload reproduces the engine: the address of one store opens the next on the same engine and position", async () => {
    const first = await boot("?u=guide2017&r=30.5&d=0.25");
    first.dispatch({ type: "setEngine", engine: "garch" });
    await advance(500);
    const search = new URL(replaced[replaced.length - 1], "https://portfoliosight.ai").search;
    const second = await boot(search);
    expect(second.getState().engine).toBe("garch");
    expect(second.getState().s).toBe(30.5);
    expect(second.getState().t).toBe(0.25);
  });

  it("ignores an engine the page does not know, and one the tensor on screen does not carry", async () => {
    const store = await boot("?u=guide2017");
    store.dispatch({ type: "setEngine", engine: "copula" });
    expect(store.getState().engine, "the fixture's copula is unavailable").toBe("replay");
    store.dispatch({ type: "setEngine", engine: "vine" as never });
    expect(store.getState().engine).toBe("replay");
    serve(withoutGarch);
    const bare = await boot("?u=guide2017");
    bare.dispatch({ type: "setEngine", engine: "garch" });
    expect(bare.getState().engine).toBe("replay");
  });

  it("a tensor that does not carry the engine puts the default back, and the address says so", async () => {
    serve(withoutGarch);
    const store = await boot("?u=guide2017&e=garch&r=30");
    expect(store.getState().tensor).not.toBeNull();
    expect(store.getState().engine).toBe("replay");
    await advance(500);
    expect(new URL(replaced[replaced.length - 1], "https://portfoliosight.ai").searchParams.has("e")).toBe(false);
  });

  it("a schema 2 tensor (a rollback generation) answers the default for every engine", async () => {
    tensorRoute = (call) => (call.method === "POST" ? json(200, { status: "ready", url: `/api/tensors/${G}/${H1}/5y` }) : json(200, OLD));
    for (const e of ["garch", "copula"]) {
      const store = await boot(`?u=guide2017&e=${e}`);
      expect(store.getState().tensor!.schema).toBe(2);
      expect(store.getState().engine).toBe("replay");
    }
    const store = await boot("?u=guide2017");
    store.dispatch({ type: "setEngine", engine: "garch" });
    expect(store.getState().engine).toBe("replay");
  });

  it("switching lookback to a window whose tensor lacks the engine puts the default back", async () => {
    const store = await boot("?u=guide2017&e=garch&r=30");
    expect(store.getState().engine).toBe("garch");
    serve(withoutGarch);
    store.dispatch({ type: "setLookback", lookback: "1y" });
    await flush();
    await advance(500);
    expect(store.getState().tensor!.lookback.id).toBe("1y");
    expect(store.getState().engine).toBe("replay");
  });

  it("an engine switch clamps s into the engine's domain and sends t back to auto only when the clamp moved it", async () => {
    serve(domains);
    const store = await boot("?u=guide2017&e=garch&r=1.5&d=0.4");
    expect(store.getState().s, "garch reaches further left").toBe(1.5);
    expect(store.getState().t).toBe(0.4);
    store.dispatch({ type: "setEngine", engine: "replay" });
    expect(store.getState().s, "replay starts at 3").toBe(3);
    expect(store.getState().t).toBe("auto");
    store.dispatch({ type: "divSlider", t: 0.7 });
    store.dispatch({ type: "setEngine", engine: "garch" });
    expect(store.getState().s, "a wider domain moves nothing").toBe(3);
    expect(store.getState().t).toBe(0.7);
    store.dispatch({ type: "riskSlider", s: 20 });
    store.dispatch({ type: "setEngine", engine: "replay" });
    expect(store.getState().s).toBe(20);
    expect(store.getState().t).toBe(0.7);
  });

  it("a shared link keeps the position the engine allows: r below replay's left end survives under garch", async () => {
    serve(domains);
    expect((await boot("?u=guide2017&e=garch&r=1.2")).getState().s).toBe(1.2);
    expect((await boot("?u=guide2017&r=1.2")).getState().s).toBe(3);
  });

  it("an engine chosen before the tensor arrives is kept while it loads and judged when it lands", async () => {
    const store = createStore({ search: "?u=guide2017" });
    store.dispatch({ type: "setEngine", engine: "garch" });
    expect(store.getState().engine).toBe("garch");
    store.dispatch({ type: "start" });
    await flush();
    await advance(500);
    expect(store.getState().engine).toBe("garch");
  });
});
