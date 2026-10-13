import { createHmac, timingSafeEqual as nodeTimingSafeEqual } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const SECRET = "unit-test-gate-value";
const SITE = "https://portfoliosight.ai";
const PAGE = "<!doctype html><title>site</title>SITE-PAGE";

type Compare = { a: number; b: number };
let compares: Compare[] = [];
let logs: string[] = [];

// The Workers primitive is absent in Node: a recording stand-in with the same contract
// (it throws when the two inputs differ in length).
function installTimingSafeEqual() {
  const bytes = (v: ArrayBuffer | ArrayBufferView) =>
    v instanceof ArrayBuffer ? Buffer.from(v) : Buffer.from(v.buffer, v.byteOffset, v.byteLength);
  Object.defineProperty(crypto.subtle, "timingSafeEqual", {
    configurable: true,
    writable: true,
    value: (a: ArrayBuffer | ArrayBufferView, b: ArrayBuffer | ArrayBufferView) => {
      const x = bytes(a);
      const y = bytes(b);
      compares.push({ a: x.byteLength, b: y.byteLength });
      if (x.byteLength !== y.byteLength) throw new TypeError("Input buffers must have the same byte length");
      return nodeTimingSafeEqual(x, y);
    },
  });
}

function makeEnv(overrides: Record<string, unknown> = {}) {
  const assetCalls: string[] = [];
  const dataGets: string[] = [];
  const env = {
    PS_GATE_SECRET: SECRET,
    PS_PRIVATE_PREVIEW: "1",
    API_ORIGIN: "https://api.portfoliosight.ai",
    DATA: {
      get: async (key: string) => {
        dataGets.push(key);
        return null;
      },
    },
    ASSETS: {
      fetch: async (request: Request) => {
        assetCalls.push(new URL(request.url).pathname + new URL(request.url).search);
        return new Response(PAGE, { headers: { "content-type": "text/html" } });
      },
    },
    ...overrides,
  };
  return { env, assetCalls, dataGets };
}

type Worker = { fetch(request: Request, env: unknown, ctx: unknown): Promise<Response> };
async function loadWorker(): Promise<Worker> {
  vi.resetModules();
  const mod = (await import("../worker/index")) as unknown as { default: Worker };
  return mod.default;
}
const ctx = { waitUntil: () => undefined, passThroughOnException: () => undefined, props: {} };
const get = (worker: Worker, env: unknown, url: string, headers: Record<string, string> = {}, method = "GET") =>
  worker.fetch(new Request(url, { method, headers, redirect: "manual" }), env, ctx);
const expectedCookie = (secret: string) => createHmac("sha256", secret).update("ps_preview").digest("hex");

describe("private preview gate", () => {
  beforeEach(() => {
    installTimingSafeEqual();
    compares = [];
    logs = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("no network in unit tests");
      }),
    );
    for (const level of ["log", "info", "warn", "error", "debug"] as const) {
      vi.spyOn(console, level).mockImplementation((...args: unknown[]) => void logs.push(args.map(String).join(" ")));
    }
  });
  afterEach(() => {
    expect(logs.join("\n")).not.toContain(SECRET);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("serves a self-contained 403 page with no data to a request without a credential", async () => {
    const worker = await loadWorker();
    for (const path of ["/", "/assets/app.js", "/api/presets", "/api/share"]) {
      const e = makeEnv();
      const res = await get(worker, e.env, SITE + path);
      const html = await res.text();
      expect(res.status, path).toBe(403);
      expect(res.headers.get("content-type"), path).toContain("text/html");
      expect(res.headers.get("cache-control"), path).toBe("no-store");
      expect(html).toContain("PortfolioSight is in private preview");
      // nothing is loaded from anywhere: no URL, no script, no stylesheet link, no image
      expect(html).not.toMatch(/https?:|\/\/|<script|<link|<img|src=|href=/i);
      expect(html).not.toContain("SITE-PAGE");
      expect(e.assetCalls).toEqual([]);
      expect(e.dataGets).toEqual([]);
    }
  });

  it("the key in the query sets the derived cookie and redirects to the URL without it", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const res = await get(worker, e.env, `${SITE}/?f=VTI:60,BND:40&k=${SECRET}&lb=5y`);
    expect(res.status).toBe(302);
    // the rest of the query is kept byte for byte
    expect(res.headers.get("location")).toBe(`${SITE}/?f=VTI:60,BND:40&lb=5y`);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const cookie = res.headers.get("set-cookie") ?? "";
    expect(cookie).toBe(`ps_preview=${expectedCookie(SECRET)}; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000; Path=/`);
    expect(cookie).not.toContain(SECRET);
    expect(await res.text()).not.toContain(SECRET);
    expect(e.assetCalls).toEqual([]);

    // a percent-encoded key name is validated and stripped too
    const encoded = await get(worker, e.env, `${SITE}/?%6B=${SECRET}&u=tsp`);
    expect(encoded.status).toBe(302);
    expect(encoded.headers.get("location")).toBe(`${SITE}/?u=tsp`);
  });

  it("the cookie value depends on the secret", async () => {
    const worker = await loadWorker();
    const other = makeEnv({ PS_GATE_SECRET: "another-unit-test-value" });
    const res = await get(worker, other.env, `${SITE}/?k=another-unit-test-value`);
    expect(res.status).toBe(302);
    expect(res.headers.get("set-cookie")).toContain(`ps_preview=${expectedCookie("another-unit-test-value")};`);
    // a cookie minted under one secret is refused under another
    const e = makeEnv();
    const refused = await get(worker, e.env, `${SITE}/`, { cookie: `ps_preview=${expectedCookie("another-unit-test-value")}` });
    expect(refused.status).toBe(403);
  });

  it("a wrong key gets the 403 page and no cookie", async () => {
    const worker = await loadWorker();
    for (const k of ["wrong", "", `${SECRET}x`, SECRET.toUpperCase(), expectedCookie(SECRET)]) {
      const e = makeEnv();
      const res = await get(worker, e.env, `${SITE}/?k=${k}`);
      expect(res.status, k).toBe(403);
      expect(res.headers.get("set-cookie"), k).toBeNull();
      expect(res.headers.get("location"), k).toBeNull();
      expect(e.assetCalls).toEqual([]);
    }
  });

  it("the header or the cookie lets pages and API calls through", async () => {
    const worker = await loadWorker();
    const cookie = expectedCookie(SECRET);
    const credentials: Array<Record<string, string>> = [{ "x-ps-gate": SECRET }, { cookie: `a=1; ps_preview=${cookie}; b=2` }, { cookie: `ps_preview=${cookie}` }];
    for (const headers of credentials) {
      const e = makeEnv();
      const page = await get(worker, e.env, `${SITE}/?u=tsp`, headers);
      expect(page.status).toBe(200);
      expect(await page.text()).toBe(PAGE);
      expect(e.assetCalls).toEqual(["/?u=tsp"]);
      const api = await get(worker, e.env, `${SITE}/api/nope`, headers);
      expect(api.status).toBe(404);
    }
    // the secret itself is not a cookie value, and the cookie value is not a header value
    const e = makeEnv();
    expect((await get(worker, e.env, `${SITE}/`, { cookie: `ps_preview=${SECRET}` })).status).toBe(403);
    expect((await get(worker, e.env, `${SITE}/`, { "x-ps-gate": cookie })).status).toBe(403);
    expect((await get(worker, e.env, `${SITE}/`, { cookie: `xps_preview=${cookie}` })).status).toBe(403);
  });

  it("a valid credential still passes when a wrong key is in the query", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const res = await get(worker, e.env, `${SITE}/?k=wrong`, { "x-ps-gate": SECRET });
    expect(res.status).toBe(200);
    expect(res.headers.get("set-cookie")).toBeNull();
  });

  it("every comparison is constant-time over equal-length digests", async () => {
    const worker = await loadWorker();
    const attempts: Array<[string, Record<string, string>]> = [
      [`${SITE}/?k=w`, {}],
      [`${SITE}/?k=${"w".repeat(500)}`, {}],
      [`${SITE}/`, { "x-ps-gate": "w" }],
      [`${SITE}/`, { "x-ps-gate": SECRET }],
      [`${SITE}/`, { cookie: "ps_preview=w" }],
      [`${SITE}/`, { cookie: `ps_preview=${expectedCookie(SECRET)}` }],
    ];
    for (const [url, headers] of attempts) {
      const before = compares.length;
      await get(worker, makeEnv().env, url, headers);
      expect(compares.length, url).toBeGreaterThan(before);
    }
    // input length never reaches the primitive: both sides are always 32-byte digests
    for (const c of compares) expect(c).toEqual({ a: 32, b: 32 });
  });

  it("preview off passes every request through and ignores credentials", async () => {
    const worker = await loadWorker();
    const ignored: Array<Record<string, string>> = [{}, { "x-ps-gate": "wrong" }, { cookie: "ps_preview=wrong" }];
    for (const headers of ignored) {
      const e = makeEnv({ PS_PRIVATE_PREVIEW: "0" });
      const res = await get(worker, e.env, `${SITE}/`, headers);
      expect(res.status).toBe(200);
      expect(await res.text()).toBe(PAGE);
    }
    const e = makeEnv({ PS_PRIVATE_PREVIEW: "0" });
    const keyed = await get(worker, e.env, `${SITE}/?k=anything`);
    expect(keyed.status).toBe(200);
    expect(keyed.headers.get("set-cookie")).toBeNull();
  });

  it("fails closed: preview stays on unless the var is exactly 0, and an unset secret admits nobody", async () => {
    const worker = await loadWorker();
    for (const value of [undefined, "", "1", "true", "off", "00"]) {
      const e = makeEnv({ PS_PRIVATE_PREVIEW: value });
      expect((await get(worker, e.env, `${SITE}/`)).status, String(value)).toBe(403);
    }
    for (const secret of [undefined, ""]) {
      const e = makeEnv({ PS_GATE_SECRET: secret });
      const empty = createHmac("sha256", "").update("ps_preview").digest("hex");
      for (const [url, headers] of [
        [`${SITE}/`, { "x-ps-gate": "" }],
        [`${SITE}/?k=`, {}],
        [`${SITE}/?k=undefined`, {}],
        [`${SITE}/`, { "x-ps-gate": "undefined" }],
        [`${SITE}/`, { cookie: `ps_preview=${empty}` }],
        [`${SITE}/`, { cookie: "ps_preview=" }],
      ] as Array<[string, Record<string, string>]>) {
        const res = await get(worker, e.env, url, headers);
        expect(res.status, `${String(secret)} ${url}`).toBe(403);
        expect(res.headers.get("set-cookie")).toBeNull();
      }
      expect(e.assetCalls).toEqual([]);
    }
  });

  it("the gate applies to every method", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    for (const method of ["POST", "PUT", "DELETE", "HEAD", "OPTIONS"]) {
      const res = await get(worker, e.env, `${SITE}/api/tensors`, {}, method);
      expect(res.status, method).toBe(403);
    }
    expect(e.assetCalls).toEqual([]);
  });
});
