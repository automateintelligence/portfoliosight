# ruff: noqa: E501
"""A-PS-40 — the Worker's routing surface is exactly spec §9.3.

Vitest leg run from pytest (stdlib only). The embedded spec runs in vitest's plain node
environment (Node 20 globals `fetch`, `Request`, `Response`, `Headers`, `URL`, `crypto.subtle`; no
jsdom, no Cloudflare test pool). `web/worker/index.ts` and `web/worker/share.ts` must import cleanly
under plain vitest: no `cloudflare:*` import at module top level.

Pinned interface
- `web/worker/index.ts`: the standard module Worker, `export default { fetch(request, env, ctx) }`;
  the host is read from `new URL(request.url).hostname`.
- `env`: `PS_GATE_SECRET`, `PS_PRIVATE_PREVIEW` (`"0"` here), `API_ORIGIN`, the share vars, `DATA`
  (R2: `get(key)` resolves an object with `body`, `httpEtag`, `etag`, `text()`, `json()`,
  `arrayBuffer()`, `writeHttpMetadata(headers)`, or `null` on a miss), `ASSETS` (`fetch(request)`),
  `SHARE_LIMITER` (a Durable Object namespace; the mock answers any call permissively).
- R2 keys: `meta/current.json`, `meta/{G}/presets.json`, `meta/symbols.json`,
  `tensors/{G}/{hash}/{lookback}.json` (spec §5.3). The Worker module is imported fresh for each
  test, so the 60 s in-memory copy of `meta/current.json` starts empty.
- Origin calls use the global `fetch` to `API_ORIGIN + "/v1/..."` with `x-ps-gate` (always the
  Worker's secret, never a client-supplied value), `accept: application/json`, `CF-Connecting-IP`,
  and the request's `content-type` on a POST; the upstream status, body and `Cache-Control` are
  returned with `x-ps-source: origin`.
- Tensor segments: `G` = `\\d{4}-\\d{2}-\\d{2}-[0-9.]+`, `hash` = 16 lowercase hex, `lookback` in
  `1y, 2y, 3y, 5y, 10y, ew`; anything else is a 4xx with no `DATA.get` and no origin fetch.
- Unknown `/api/` paths answer `404`; a known path with another method answers 4xx; neither is
  forwarded nor sent to `ASSETS`. `POST /api/share` validates its input before it consults
  `SHARE_LIMITER`, and errors use the envelope `{"error": {"code"}}`.
- The test installs a stand-in for `crypto.subtle.timingSafeEqual` (the Workers primitive).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"

SPEC_TS = r"""
import { timingSafeEqual as nodeTimingSafeEqual } from "node:crypto";
import { inspect } from "node:util";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const SECRET = "ZZ-SENTINEL-ZZ";
const SITE = "https://portfoliosight.ai";
const API_ORIGIN = "https://api.portfoliosight.ai";
const G = "2026-10-12-0.1.0";
const HASH = "3f9c2a7e1b4d5e60";
const ETAG = "9b2cf535f27731c974343645a3985328";
const TENSOR_PATH = `/api/tensors/${G}/${HASH}/5y`;
const PRESETS = {
  generation: G,
  asof: "2026-10-12",
  presets: [
    { id: "guide2017", name: "PRESETS-MARKER The 2017 guide portfolio", hash: HASH, funds: [{ id: "VTI", name: "Vanguard Total Stock Market ETF" }], allocation: { VTI: 10840 }, allocation_unit: "$", lookbacks: { "5y": { status: "ready", url: TENSOR_PATH } } },
  ],
};
const SYMBOLS = { catalog_at: "2026-10-13T09:00:00Z", tiers_served: [1, 2, 3], symbols: [{ id: "VTI", name: "SYMBOLS-MARKER Vanguard Total Stock Market ETF", kind: "etf", tier: 1, first_date: "2001-05-31" }] };
const TENSOR_TEXT = JSON.stringify({ schema: 2, generation: G, marker: "TENSOR-MARKER", universe: { hash: HASH } });
const MARKER_PAGE = '<!doctype html><html><head><title>PortfolioSight</title></head><body><div id="root">ASSETS-MARKER</div></body></html>';
const DATA_MARKERS = ["PRESETS-MARKER", "SYMBOLS-MARKER", "TENSOR-MARKER", "ASSETS-MARKER"];

type OriginCall = { url: string; method: string; headers: Headers; body: string };
type Seen = { label: string; status: number; headers: Array<[string, string]>; text: string };
let compares = 0;
let originCalls: OriginCall[] = [];
let originResponse: (call: OriginCall) => Response = () => new Response("{}", { status: 200 });
let seen: Seen[] = [];
let logs: string[] = [];

// crypto.subtle.timingSafeEqual is the Workers primitive (absent in Node): a counting stand-in
// with the Workers behaviour (throws when the two inputs differ in length).
function installTimingSafeEqual() {
  const bytes = (v: any) => (v instanceof ArrayBuffer ? Buffer.from(v) : Buffer.from(v.buffer, v.byteOffset, v.byteLength));
  Object.defineProperty(globalThis.crypto.subtle, "timingSafeEqual", {
    configurable: true,
    writable: true,
    value: (a: any, b: any) => {
      compares += 1;
      const x = bytes(a);
      const y = bytes(b);
      if (x.byteLength !== y.byteLength) throw new TypeError("Input buffers must have the same byte length");
      return nodeTimingSafeEqual(x, y);
    },
  });
}

function r2Object(key: string, text: string) {
  return {
    key,
    size: new TextEncoder().encode(text).byteLength,
    etag: ETAG,
    httpEtag: `"${ETAG}"`,
    uploaded: new Date("2026-10-13T09:31:02Z"),
    httpMetadata: { contentType: "application/json" },
    customMetadata: {},
    bodyUsed: false,
    get body() {
      return new Response(text).body;
    },
    text: async () => text,
    json: async () => JSON.parse(text),
    arrayBuffer: async () => new TextEncoder().encode(text).buffer,
    blob: async () => new Blob([text]),
    writeHttpMetadata(headers: Headers) {
      headers.set("content-type", "application/json");
    },
  };
}

function makeEnv(preview: "0" | "1") {
  const objects = new Map<string, string>([
    ["meta/current.json", JSON.stringify({ generation: G, published_at: "2026-10-13T09:40:00Z" })],
    [`meta/${G}/presets.json`, JSON.stringify(PRESETS)],
    ["meta/symbols.json", JSON.stringify(SYMBOLS)],
    [`tensors/${G}/${HASH}/5y.json`, TENSOR_TEXT],
  ]);
  const dataGets: string[] = [];
  const assetCalls: string[] = [];
  const limiterCalls: string[] = [];
  const limiterStub = new Proxy(
    {},
    {
      get: (_target, prop) => {
        if (prop === "then") return undefined;
        return (..._args: unknown[]) => {
          limiterCalls.push(String(prop));
          const res = new Response(JSON.stringify({ ok: true, allowed: true }), { headers: { "content-type": "application/json" } });
          return Promise.resolve(Object.assign(res, { allowed: true }));
        };
      },
    },
  );
  const env = {
    PS_GATE_SECRET: SECRET,
    PS_PRIVATE_PREVIEW: preview,
    API_ORIGIN,
    SHARE_FROM: "portfoliosight@automateintelligence.ai",
    SHARE_REPLY_TO: "support@automateintelligence.ai",
    SHARE_CAP_IP_MINUTE: "1",
    SHARE_CAP_IP_DAY: "3",
    SHARE_CAP_GLOBAL_DAY: "50",
    MAILCHANNELS_API_KEY: "test",
    MAILCHANNELS_DKIM_PRIVATE_KEY: "DKIM-KEY",
    DATA: {
      get: async (key: string) => {
        dataGets.push(String(key));
        const text = objects.get(String(key));
        return text === undefined ? null : r2Object(String(key), text);
      },
    },
    ASSETS: {
      fetch: async (input: any, init?: any) => {
        const req = input instanceof Request ? input : new Request(input, init);
        assetCalls.push(new URL(req.url).pathname);
        return new Response(MARKER_PAGE, { status: 200, headers: { "content-type": "text/html; charset=utf-8" } });
      },
    },
    SHARE_LIMITER: {
      idFromName: (name: string) => ({ name, toString: () => name }),
      newUniqueId: () => ({ toString: () => "unique" }),
      get: () => limiterStub,
      getByName: () => limiterStub,
    },
  };
  return { env, dataGets, assetCalls, limiterCalls };
}
const ctx = () => ({ waitUntil: (_p: unknown) => undefined, passThroughOnException: () => undefined, props: {} });

async function loadWorker() {
  installTimingSafeEqual();
  vi.resetModules();
  const mod: any = await import("../../worker/index");
  expect(typeof mod.default?.fetch, "worker/index.ts must `export default { fetch(request, env, ctx) }`").toBe("function");
  return mod.default;
}

async function call(worker: any, env: any, url: string, init: RequestInit = {}) {
  const res: Response = await worker.fetch(new Request(url, { redirect: "manual", ...init }), env, ctx());
  expect(res instanceof Response, `${init.method ?? "GET"} ${url} did not return a Response`).toBe(true);
  const text = await res.clone().text();
  const headers = Array.from(res.headers.entries());
  seen.push({ label: `${init.method ?? "GET"} ${url}`, status: res.status, headers, text });
  return { status: res.status, headers: res.headers, text };
}

function expectNoSecretAnywhere() {
  for (const r of seen) {
    expect(r.text.includes(SECRET), `the secret is in the body of ${r.label.replaceAll(SECRET, "<secret>")}`).toBe(false);
    for (const [name, value] of r.headers) {
      expect(`${name}: ${value}`.includes(SECRET), `the secret is in the response header ${name}`).toBe(false);
    }
  }
  expect(logs.join("\n")).not.toContain(SECRET);
}

function harnessSetup() {
  beforeEach(() => {
    compares = 0;
    originCalls = [];
    seen = [];
    logs = [];
    originResponse = () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: any, init?: any) => {
        const req = input instanceof Request ? input : new Request(input, init);
        const callInfo: OriginCall = { url: req.url, method: req.method, headers: req.headers, body: await req.text() };
        originCalls.push(callInfo);
        return originResponse(callInfo);
      }),
    );
    for (const level of ["log", "info", "warn", "error", "debug"] as const) {
      vi.spyOn(console, level).mockImplementation((...args: any[]) => {
        logs.push(args.map((a) => (typeof a === "string" ? a : inspect(a, { depth: 6 }))).join(" "));
      });
    }
  });
  afterEach(() => {
    expectNoSecretAnywhere();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
}

const GATE = { "x-ps-gate": SECRET };
const IP = "203.0.113.77";

describe("A-PS-40", () => {
  harnessSetup();

  it("www redirects to the apex and any other host is a 404", async () => {
    const worker = await loadWorker();
    const e = makeEnv("0");
    for (const [from, to] of [
      ["https://www.portfoliosight.ai/?u=tsp&lb=5y", `${SITE}/?u=tsp&lb=5y`],
      ["https://www.portfoliosight.ai/some/deep/link?u=tsp&lb=5y", `${SITE}/some/deep/link?u=tsp&lb=5y`],
      ["https://www.portfoliosight.ai/api/presets", `${SITE}/api/presets`],
    ]) {
      const r = await call(worker, e.env, from, { headers: GATE });
      expect(r.status, from).toBe(301);
      expect(r.headers.get("location"), from).toBe(to);
    }
    for (const url of ["https://evil.example.com/", "https://portfoliosight.ingage-bd0.workers.dev/api/presets", "https://api.portfoliosight.ai/", "https://portfoliosight.ai.example.com/", "https://wwww.portfoliosight.ai/"]) {
      const r = await call(worker, e.env, url, { headers: GATE });
      expect(r.status, url).toBe(404);
      for (const marker of DATA_MARKERS) expect(r.text, url).not.toContain(marker);
    }
    expect(e.dataGets).toEqual([]);
    expect(e.assetCalls).toEqual([]);
    expect(originCalls.length).toBe(0);
  });

  it("presets and symbols are read from R2", async () => {
    const worker = await loadWorker();
    const e = makeEnv("0");
    const presets = await call(worker, e.env, `${SITE}/api/presets`, { headers: GATE });
    expect(presets.status).toBe(200);
    expect(JSON.parse(presets.text)).toEqual(PRESETS);
    expect(presets.headers.get("cache-control")).toBe("public, max-age=300");
    expect(presets.headers.get("x-ps-source")).toBe("r2");
    expect(e.dataGets).toEqual(["meta/current.json", `meta/${G}/presets.json`]);
    e.dataGets.length = 0;
    const symbols = await call(worker, e.env, `${SITE}/api/symbols`, { headers: GATE });
    expect(symbols.status).toBe(200);
    expect(JSON.parse(symbols.text)).toEqual(SYMBOLS);
    expect(symbols.headers.get("cache-control")).toBe("public, max-age=300");
    expect(symbols.headers.get("x-ps-source")).toBe("r2");
    expect(e.dataGets).toEqual(["meta/symbols.json"]);
    expect(e.assetCalls).toEqual([]);
    expect(originCalls.length, "a read was sent to the origin").toBe(0);
  });

  it("a tensor is served from R2 on a hit and forwarded to the origin on a miss", async () => {
    const worker = await loadWorker();
    const e = makeEnv("0");
    const hit = await call(worker, e.env, SITE + TENSOR_PATH, { headers: GATE });
    expect(hit.status).toBe(200);
    expect(hit.text).toBe(TENSOR_TEXT);
    expect(hit.headers.get("cache-control")).toBe("public, max-age=86400, immutable");
    expect((hit.headers.get("etag") ?? "").replace(/^W\//, "").replaceAll('"', "")).toBe(ETAG);
    expect(hit.headers.get("x-ps-source")).toBe("r2");
    expect(e.dataGets).toEqual([`tensors/${G}/${HASH}/5y.json`]);
    expect(originCalls.length).toBe(0);

    e.dataGets.length = 0;
    const upstream = JSON.stringify({ status: "building", generation: G, hash: HASH, position: 1, eta_s: 30 });
    originResponse = () => new Response(upstream, { status: 202, headers: { "content-type": "application/json", "cache-control": "no-store" } });
    const miss = await call(worker, e.env, `${SITE}/api/tensors/${G}/${HASH}/3y`, { headers: { ...GATE, "cf-connecting-ip": IP } });
    expect(e.dataGets).toEqual([`tensors/${G}/${HASH}/3y.json`]);
    expect(originCalls.length).toBe(1);
    expect(originCalls[0].url).toBe(`${API_ORIGIN}/v1/tensors/${G}/${HASH}/3y`);
    expect(originCalls[0].method).toBe("GET");
    expect(originCalls[0].headers.get("x-ps-gate")).toBe(SECRET);
    expect(originCalls[0].headers.get("accept")).toBe("application/json");
    expect(originCalls[0].headers.get("cf-connecting-ip")).toBe(IP);
    expect(miss.status).toBe(202);
    expect(miss.text).toBe(upstream);
    expect(miss.headers.get("cache-control")).toBe("no-store");
    expect(miss.headers.get("x-ps-source")).toBe("origin");
    expect(miss.headers.get("x-ps-source")).not.toBe("r2");
    expect(e.assetCalls).toEqual([]);
  });

  it("POST /api/tensors and GET /api/health are forwarded with the four headers", async () => {
    const worker = await loadWorker();
    const e = makeEnv("0");
    const body = JSON.stringify({ funds: [{ id: "VTI", min: null, max: 0.1 }, { id: "BND", min: null, max: null }], lookback: "5y" });
    const ready = JSON.stringify({ status: "ready", generation: G, hash: HASH, url: TENSOR_PATH });
    originResponse = () => new Response(ready, { status: 200, headers: { "content-type": "application/json", "cache-control": "no-store, private" } });
    const post = await call(worker, e.env, `${SITE}/api/tensors`, { method: "POST", headers: { ...GATE, "content-type": "application/json", "cf-connecting-ip": IP }, body });
    expect(originCalls.length).toBe(1);
    expect(originCalls[0].url).toBe(`${API_ORIGIN}/v1/tensors`);
    expect(originCalls[0].method).toBe("POST");
    expect(originCalls[0].body).toBe(body);
    expect(originCalls[0].headers.get("x-ps-gate")).toBe(SECRET);
    expect(originCalls[0].headers.get("content-type")).toBe("application/json");
    expect(originCalls[0].headers.get("accept")).toBe("application/json");
    expect(originCalls[0].headers.get("cf-connecting-ip")).toBe(IP);
    expect(post.status).toBe(200);
    expect(post.text).toBe(ready);
    expect(post.headers.get("cache-control")).toBe("no-store, private");
    expect(post.headers.get("x-ps-source")).toBe("origin");

    originCalls.length = 0;
    const health = JSON.stringify({ status: "ok", version: "0.1.0", generation: G });
    originResponse = () => new Response(health, { status: 200, headers: { "content-type": "application/json", "cache-control": "no-store, max-age=0" } });
    const got = await call(worker, e.env, `${SITE}/api/health`, { headers: { ...GATE, "cf-connecting-ip": "198.51.100.9" } });
    expect(originCalls.length).toBe(1);
    expect(originCalls[0].url).toBe(`${API_ORIGIN}/v1/health`);
    expect(originCalls[0].method).toBe("GET");
    expect(originCalls[0].headers.get("x-ps-gate")).toBe(SECRET);
    expect(originCalls[0].headers.get("accept")).toBe("application/json");
    expect(originCalls[0].headers.get("cf-connecting-ip")).toBe("198.51.100.9");
    expect(got.status).toBe(200);
    expect(got.text).toBe(health);
    expect(got.headers.get("cache-control")).toBe("no-store, max-age=0");
    expect(got.headers.get("x-ps-source")).toBe("origin");
    // an upstream failure is passed on as it is
    originCalls.length = 0;
    originResponse = () => new Response('{"error":{"code":"busy","message":"busy","details":null}}', { status: 503, headers: { "content-type": "application/json", "cache-control": "no-store" } });
    const busy = await call(worker, e.env, `${SITE}/api/tensors`, { method: "POST", headers: { ...GATE, "content-type": "application/json", "cf-connecting-ip": IP }, body });
    expect(busy.status).toBe(503);
    expect(busy.headers.get("x-ps-source")).toBe("origin");
    expect(e.dataGets).toEqual([]);
    expect(e.assetCalls).toEqual([]);
  });

  it("malformed tensor segments are refused without a DATA read or an origin fetch", async () => {
    const worker = await loadWorker();
    const e = makeEnv("0");
    const bad = [
      "/api/tensors/x/y/z",
      `/api/tensors/${G}/${HASH}/7y`,
      `/api/tensors/${G}/${HASH.toUpperCase()}/5y`,
      `/api/tensors/${G}/${HASH.slice(0, 15)}/5y`,
      `/api/tensors/${G}/${HASH}0/5y`,
      `/api/tensors/${G}/zzzzzzzzzzzzzzzz/5y`,
      `/api/tensors/latest/${HASH}/5y`,
      `/api/tensors/2026-10-12/${HASH}/5y`,
      `/api/tensors/${G}x/${HASH}/5y`,
      `/api/tensors/${G}/${HASH}/5y.json`,
      `/api/tensors/${G}/${HASH}/5y/extra`,
      `/api/tensors/..%2F..%2Fmeta/${HASH}/5y`,
      `/api/tensors/${G}/${HASH}`,
    ];
    for (const path of bad) {
      const r = await call(worker, e.env, SITE + path, { headers: GATE });
      expect(r.status, path).toBeGreaterThanOrEqual(400);
      expect(r.status, path).toBeLessThan(500);
      for (const marker of DATA_MARKERS) expect(r.text, path).not.toContain(marker);
    }
    expect(e.dataGets, "DATA was read for a malformed key").toEqual([]);
    expect(originCalls.map((c) => c.url), "a malformed key was forwarded").toEqual([]);
    expect(e.assetCalls).toEqual([]);
    // control: the well-formed neighbour of these paths is served
    expect((await call(worker, e.env, SITE + TENSOR_PATH, { headers: GATE })).status).toBe(200);
    expect(e.dataGets.length).toBe(1);
  });

  it("no other /api/ path exists and the share route stays in the Worker", async () => {
    const worker = await loadWorker();
    const e = makeEnv("0");
    const none: Array<[string, string]> = [
      ["GET", "/api/anything-else"],
      ["GET", "/api/login"],
      ["POST", "/api/login"],
      ["GET", "/api/"],
      ["GET", "/api/v1/health"],
      ["GET", "/api/presets/extra"],
      ["GET", "/api/health/extra"],
      ["GET", "/api/share"],
    ];
    for (const [method, path] of none) {
      const r = await call(worker, e.env, SITE + path, { method, headers: { ...GATE, "content-type": "application/json" }, body: method === "POST" ? "{}" : undefined });
      expect(r.status, `${method} ${path}`).toBe(404);
      expect(r.text, `${method} ${path}`).not.toContain("ASSETS-MARKER");
    }
    // the right paths with the wrong method are not forwarded either
    const wrongMethod: Array<[string, string]> = [["POST", "/api/health"], ["DELETE", "/api/tensors"], ["GET", "/api/tensors"], ["PUT", `${TENSOR_PATH}`], ["POST", "/api/presets"]];
    for (const [method, path] of wrongMethod) {
      const r = await call(worker, e.env, SITE + path, { method, headers: { ...GATE, "content-type": "application/json" }, body: method === "GET" ? undefined : "{}" });
      expect(r.status, `${method} ${path}`).toBeGreaterThanOrEqual(400);
      expect(r.status, `${method} ${path}`).toBeLessThan(500);
      expect(r.text).not.toContain("ASSETS-MARKER");
    }
    expect(originCalls.map((c) => `${c.method} ${c.url}`), "a path outside the three forwarded ones reached the origin").toEqual([]);
    expect(e.assetCalls, "an /api/ path fell through to the static assets").toEqual([]);
    expect(e.dataGets).toEqual([]);

    // POST /api/share is answered by the Worker itself (an invalid recipient is refused before any limiter or mail call)
    const share = await call(worker, e.env, `${SITE}/api/share`, {
      method: "POST",
      headers: { ...GATE, origin: SITE, "content-type": "application/json", "cf-connecting-ip": IP },
      body: JSON.stringify({ to: "Jeff <a@b.c>", url: `${SITE}/?u=guide2017&lb=5y&d=auto` }),
    });
    expect(share.status).toBe(400);
    expect(JSON.parse(share.text).error.code).toBe("invalid_recipient");
    expect(originCalls.length, "the share request was forwarded or mailed").toBe(0);
    expect(e.assetCalls).toEqual([]);
  });

  it("every other path goes to ASSETS", async () => {
    const worker = await loadWorker();
    let checked = 0;
    for (const path of ["/", "/some/deep/link", "/assets/x.js", "/?u=tsp&lb=5y", "/apix", "/favicon.ico"]) {
      const e = makeEnv("0");
      const r = await call(worker, e.env, SITE + path, { headers: GATE });
      expect(r.status, path).toBe(200);
      expect(r.text, path).toBe(MARKER_PAGE);
      expect(e.assetCalls, path).toEqual([new URL(SITE + path).pathname]);
      expect(e.dataGets, path).toEqual([]);
      expect(originCalls.length, path).toBe(0);
      expect(r.headers.get("x-ps-source"), path).not.toBe("origin");
      checked += 1;
    }
    expect(checked).toBe(6);
  });

  it("no origin fetch leaves without x-ps-gate", async () => {
    const worker = await loadWorker();
    const e = makeEnv("0");
    const all: OriginCall[] = [];
    const requests: Array<[string, RequestInit]> = [
      [`${SITE}/api/health`, {}],
      [`${SITE}/api/tensors`, { method: "POST", headers: { "content-type": "application/json" }, body: '{"funds":[],"lookback":"5y"}' }],
      [`${SITE}/api/tensors/${G}/${HASH}/1y`, {}],
      [`${SITE}/api/tensors/${G}/${HASH}/ew`, { headers: { "x-ps-gate": "client-supplied-value" } }],
    ];
    for (const [url, init] of requests) {
      originCalls.length = 0;
      await call(worker, e.env, url, init);
      expect(originCalls.length, url).toBe(1);
      all.push(...originCalls);
    }
    expect(all.length).toBe(4);
    for (const c of all) {
      expect(c.headers.get("x-ps-gate"), c.url).toBe(SECRET);
      expect(c.headers.get("x-ps-gate"), c.url).not.toBe("client-supplied-value");
      expect(c.url.startsWith(`${API_ORIGIN}/v1/`), c.url).toBe(true);
    }
  });
});
"""
EXPECTED_TITLES = {
    "www redirects to the apex and any other host is a 404",
    "presets and symbols are read from R2",
    "a tensor is served from R2 on a hit and forwarded to the origin on a miss",
    "POST /api/tensors and GET /api/health are forwarded with the four headers",
    "malformed tensor segments are refused without a DATA read or an origin fetch",
    "no other /api/ path exists and the share route stays in the Worker",
    "every other path goes to ASSETS",
    "no origin fetch leaves without x-ps-gate",
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


def test_a_ps_40_vitest():
    statuses = _run_vitest("a_ps_40", SPEC_TS)
    assert set(statuses) == EXPECTED_TITLES, (
        f"vitest ran a different set of tests: {sorted(statuses)}"
    )
    not_passed = {title: status for title, status in statuses.items() if status != "passed"}
    assert not not_passed, f"vitest legs not passed (failed, skipped or todo): {not_passed}"
