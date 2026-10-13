# ruff: noqa: E501
"""A-PS-39 — the private-preview gate.

Vitest leg run from pytest (stdlib only). The embedded spec runs in vitest's plain node
environment (Node 20 globals `fetch`, `Request`, `Response`, `Headers`, `URL`, `crypto.subtle`; no
jsdom, no Cloudflare test pool). `web/worker/index.ts` and `web/worker/share.ts` must import cleanly
under plain vitest: no `cloudflare:*` import at module top level.

Pinned interface
- `web/worker/index.ts`: the standard module Worker, `export default { fetch(request, env, ctx) }`.
- `env`: `PS_GATE_SECRET`, `PS_PRIVATE_PREVIEW` (`"1"` on, `"0"` off), `API_ORIGIN`, the share vars,
  `DATA` (R2: `get(key)` resolves an object with `body`, `httpEtag`, `etag`, `text()`, `json()`,
  `arrayBuffer()`, `writeHttpMetadata(headers)`, or `null`), `ASSETS` (`fetch(request)`),
  `SHARE_LIMITER` (a Durable Object namespace).
- Secret comparisons go through `crypto.subtle.timingSafeEqual(a, b)` (the Workers primitive; it
  throws when the inputs differ in length, so hash or pad first). The test installs a counting
  stand-in before importing the Worker and requires it to be called on every keyed request
  (header, cookie or `?k=`, right or wrong).
- Cookie: `Set-Cookie: ps_preview=<value>; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000` on a
  `302` whose `Location` is the same URL without `k`; `<value>` is derived from the secret and is
  not the secret (nor its base64 or hex form). The preview page is `403`, `text/html`, and says
  "private preview".
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

const PATHS = ["/", "/?u=tsp", "/api/presets", TENSOR_PATH, "/assets/x.js"];
const ATTRIBUTES = ["httponly", "secure", "samesite=lax", "max-age=2592000"];

function parseSetCookie(header: string) {
  const parts = header.split(";").map((p) => p.trim());
  const eq = parts[0].indexOf("=");
  return { name: parts[0].slice(0, eq), value: parts[0].slice(eq + 1), attributes: parts.slice(1).map((p) => p.toLowerCase()) };
}
async function issueCookie(worker: any): Promise<string> {
  const { env } = makeEnv("1");
  const r = await call(worker, env, `${SITE}/?k=${SECRET}&u=tsp`);
  expect(r.status).toBe(302);
  const header = r.headers.get("set-cookie");
  expect(header, "no Set-Cookie on the keyed redirect").not.toBeNull();
  return parseSetCookie(header as string).value;
}
function expectBlocked(label: string, r: { status: number; headers: Headers; text: string }, e: ReturnType<typeof makeEnv>) {
  expect(r.status, label).toBe(403);
  expect((r.headers.get("content-type") ?? "").toLowerCase(), label).toContain("text/html");
  expect(r.text.toLowerCase(), label).toContain("private preview");
  expect(r.headers.get("x-ps-source"), label).toBeNull();
  expect(r.headers.get("set-cookie"), label).toBeNull();
  for (const marker of DATA_MARKERS) expect(r.text, `${label}: data leaked`).not.toContain(marker);
  expect(e.dataGets, `${label}: DATA was read`).toEqual([]);
  expect(e.assetCalls, `${label}: ASSETS was called`).toEqual([]);
  expect(originCalls.length, `${label}: the origin was called`).toBe(0);
}
function expectPassed(label: string, path: string, r: { status: number; headers: Headers; text: string }, e: ReturnType<typeof makeEnv>) {
  expect(r.status, label).toBe(200);
  expect(r.text.toLowerCase(), label).not.toContain("private preview");
  if (path === "/api/presets") {
    expect(JSON.parse(r.text), label).toEqual(PRESETS);
    expect(r.headers.get("x-ps-source"), label).toBe("r2");
    expect(e.assetCalls).toEqual([]);
  } else if (path === TENSOR_PATH) {
    expect(r.text, label).toBe(TENSOR_TEXT);
    expect(r.headers.get("x-ps-source"), label).toBe("r2");
    expect(e.assetCalls).toEqual([]);
  } else {
    expect(r.text, label).toBe(MARKER_PAGE);
    expect(e.assetCalls.length, label).toBe(1);
    expect(e.dataGets).toEqual([]);
  }
}
const withQuery = (path: string, extra: string) => path + (path.includes("?") ? "&" : "?") + extra;

describe("A-PS-39", () => {
  harnessSetup();

  it("preview on: five paths x four credentials", async () => {
    const worker = await loadWorker();
    const cookie = await issueCookie(worker);
    const tampered = cookie.slice(0, -1) + (cookie.endsWith("a") ? "b" : "a");
    const sameLength = SECRET.slice(0, -1) + "Y";
    expect(sameLength.length).toBe(SECRET.length);
    type Cred = { name: string; pass: boolean; keyed: boolean; headers?: Record<string, string>; query?: string };
    const creds: Cred[] = [
      { name: "none", pass: false, keyed: false },
      { name: "header", pass: true, keyed: true, headers: { "x-ps-gate": SECRET } },
      { name: "cookie", pass: true, keyed: true, headers: { cookie: `theme=hud; ps_preview=${cookie}; cf_clearance=abc.def-123` } },
      { name: "wrong header", pass: false, keyed: true, headers: { "x-ps-gate": "wrong" } },
      { name: "wrong header of the secret's length", pass: false, keyed: true, headers: { "x-ps-gate": sameLength } },
      { name: "wrong cookie", pass: false, keyed: true, headers: { cookie: "ps_preview=wrong" } },
      { name: "tampered cookie", pass: false, keyed: true, headers: { cookie: `ps_preview=${tampered}` } },
      { name: "wrong k", pass: false, keyed: true, query: "k=wrong" },
    ];
    let cells = 0;
    let passed = 0;
    for (const path of PATHS) {
      for (const cred of creds) {
        const e = makeEnv("1");
        const label = `preview on, ${path}, ${cred.name}`;
        const before = compares;
        originCalls.length = 0;
        const r = await call(worker, e.env, SITE + (cred.query ? withQuery(path, cred.query) : path), { headers: cred.headers ?? {} });
        if (cred.pass) {
          expectPassed(label, path, r, e);
          passed += 1;
        } else expectBlocked(label, r, e);
        if (cred.keyed) expect(compares, `${label}: the constant-time compare was not used`).toBeGreaterThan(before);
        cells += 1;
      }
    }
    expect(cells).toBe(40);
    expect(passed).toBe(10);
    // a lone ps_preview cookie works too
    const lone = makeEnv("1");
    expectPassed("lone cookie", "/", await call(worker, lone.env, `${SITE}/`, { headers: { cookie: `ps_preview=${cookie}` } }), lone);
  });

  it("preview off: every request passes through", async () => {
    const worker = await loadWorker();
    const cookie = await issueCookie(worker);
    const creds: Array<{ name: string; headers: Record<string, string> }> = [
      { name: "none", headers: {} },
      { name: "header", headers: { "x-ps-gate": SECRET } },
      { name: "cookie", headers: { cookie: `ps_preview=${cookie}` } },
      { name: "wrong", headers: { "x-ps-gate": "wrong", cookie: "ps_preview=wrong" } },
    ];
    let cells = 0;
    for (const path of PATHS) {
      for (const cred of creds) {
        const e = makeEnv("0");
        const r = await call(worker, e.env, SITE + path, { headers: cred.headers });
        expectPassed(`preview off, ${path}, ${cred.name}`, path, r, e);
        expect(r.status).not.toBe(403);
        cells += 1;
      }
    }
    expect(cells).toBe(20);
  });

  it("the key in ?k= sets the cookie and redirects to the clean URL", async () => {
    const worker = await loadWorker();
    const routes: Array<[string, string]> = [
      [`/?k=${SECRET}&u=tsp`, "/?u=tsp"],
      [`/?u=tsp&k=${SECRET}&lb=5y`, "/?u=tsp&lb=5y"],
      [`/?k=${SECRET}`, "/"],
    ];
    const values = new Set<string>();
    for (const [from, to] of routes) {
      const e = makeEnv("1");
      const before = compares;
      const r = await call(worker, e.env, SITE + from);
      expect(r.status, from.replaceAll(SECRET, "<secret>")).toBe(302);
      const location = r.headers.get("location") as string;
      expect(location).not.toBeNull();
      expect(new URL(location, `${SITE}/`).href).toBe(SITE + to);
      expect(location).not.toContain("k=");
      const header = r.headers.get("set-cookie") as string;
      expect(header, "Set-Cookie").not.toBeNull();
      const parsed = parseSetCookie(header);
      expect(parsed.name).toBe("ps_preview");
      for (const attribute of ATTRIBUTES) expect(parsed.attributes, `cookie attribute ${attribute}`).toContain(attribute);
      expect(parsed.value.length).toBeGreaterThan(0);
      expect(parsed.value).not.toBe(SECRET);
      expect(decodeURIComponent(parsed.value)).not.toContain(SECRET);
      expect(parsed.value).not.toContain(Buffer.from(SECRET).toString("base64").replace(/=+$/, ""));
      expect(parsed.value).not.toContain(Buffer.from(SECRET).toString("base64url"));
      expect(parsed.value.toLowerCase()).not.toContain(Buffer.from(SECRET).toString("hex"));
      expect(header).not.toContain(SECRET);
      expect(r.text).not.toContain(SECRET);
      for (const marker of DATA_MARKERS) expect(r.text).not.toContain(marker);
      expect(e.dataGets).toEqual([]);
      expect(e.assetCalls).toEqual([]);
      expect(compares).toBeGreaterThan(before);
      values.add(parsed.value);
    }
    expect(values.size).toBeGreaterThanOrEqual(1);
    for (const bad of ["/?k=wrong", "/?k=", `/?k=${SECRET}x`, `/?k=${SECRET.toLowerCase()}`, "/?u=tsp&k=wrong", `/?k=${"w".repeat(40)}`, `/?k=${SECRET}${SECRET}`]) {
      const e = makeEnv("1");
      const r = await call(worker, e.env, SITE + bad);
      expect(r.status, bad).toBe(403);
      expect(r.status, bad).not.toBe(302);
      expect(r.headers.get("set-cookie"), `${bad}: a cookie was issued for a wrong key`).toBeNull();
      expect(r.text.toLowerCase()).toContain("private preview");
      expect(e.assetCalls).toEqual([]);
    }
  });

  it("the secret is in no response header, body or log line", async () => {
    const worker = await loadWorker();
    const cookie = await issueCookie(worker);
    const requests: Array<[string, RequestInit]> = [
      [`${SITE}/`, {}],
      [`${SITE}/api/presets`, {}],
      [`${SITE}/?k=wrong`, {}],
      [`${SITE}/?k=${SECRET}&u=tsp`, {}],
      [`${SITE}/api/presets`, { headers: { "x-ps-gate": SECRET } }],
      [`${SITE}${TENSOR_PATH}`, { headers: { "x-ps-gate": SECRET } }],
      [`${SITE}/`, { headers: { "x-ps-gate": "wrong" } }],
      [`${SITE}/`, { headers: { cookie: `ps_preview=${cookie}` } }],
      [`${SITE}/api/nope`, { headers: { "x-ps-gate": SECRET } }],
    ];
    for (const mode of ["1", "0"] as const) {
      for (const [url, init] of requests) await call(worker, makeEnv(mode).env, url, init);
    }
    expect(seen.length).toBe(1 + 2 * requests.length);
    expectNoSecretAnywhere();
    // the scan can see a leak: the same scan fails on a planted one
    seen.push({ label: "planted", status: 200, headers: [], text: `echo ${SECRET}` });
    expect(() => expectNoSecretAnywhere()).toThrow();
    seen.pop();
  });
});
"""
EXPECTED_TITLES = {
    "preview on: five paths x four credentials",
    "preview off: every request passes through",
    "the key in ?k= sets the cookie and redirects to the clean URL",
    "the secret is in no response header, body or log line",
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


def test_a_ps_39_vitest():
    statuses = _run_vitest("a_ps_39", SPEC_TS)
    assert set(statuses) == EXPECTED_TITLES, (
        f"vitest ran a different set of tests: {sorted(statuses)}"
    )
    not_passed = {title: status for title, status in statuses.items() if status != "passed"}
    assert not not_passed, f"vitest legs not passed (failed, skipped or todo): {not_passed}"
