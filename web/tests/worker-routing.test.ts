import { timingSafeEqual as nodeTimingSafeEqual } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const SECRET = "unit-test-gate-value";
const SITE = "https://portfoliosight.ai";
const API_ORIGIN = "https://api.portfoliosight.ai";
const G = "2026-10-12-0.1.0";
const HASH = "3f9c2a7e1b4d5e60";
const ETAG = "9b2cf535f27731c974343645a3985328";
const PRESETS = JSON.stringify({ generation: G, presets: [{ id: "guide2017", name: "PRESETS-MARKER" }] });
const SYMBOLS = JSON.stringify({ symbols: [{ id: "VTI", name: "SYMBOLS-MARKER" }] });
const TENSOR = JSON.stringify({ schema: 2, marker: "TENSOR-MARKER" });
const PAGE = "<!doctype html><title>site</title>SITE-PAGE";
const SHARE_BODY = JSON.stringify({ to: "reader@example.org", url: `${SITE}/?u=tsp&lb=3y&d=auto` });

type OriginCall = { url: string; method: string; headers: Array<[string, string]>; body: string };
type LimiterCall = { name: string; url: string; body: unknown };
let originCalls: OriginCall[] = [];
let originResponse: () => Response | Promise<Response> = () => new Response("{}");
let logs: string[] = [];

function installTimingSafeEqual() {
  const bytes = (v: ArrayBuffer | ArrayBufferView) =>
    v instanceof ArrayBuffer ? Buffer.from(v) : Buffer.from(v.buffer, v.byteOffset, v.byteLength);
  Object.defineProperty(crypto.subtle, "timingSafeEqual", {
    configurable: true,
    writable: true,
    value: (a: ArrayBuffer | ArrayBufferView, b: ArrayBuffer | ArrayBufferView) => {
      const x = bytes(a);
      const y = bytes(b);
      if (x.byteLength !== y.byteLength) throw new TypeError("Input buffers must have the same byte length");
      return nodeTimingSafeEqual(x, y);
    },
  });
}

function makeEnv(overrides: Record<string, unknown> = {}, limiter: (call: LimiterCall) => Response | Promise<Response> = allowAll) {
  const objects = new Map<string, string>([
    ["meta/current.json", JSON.stringify({ generation: G, published_at: "2026-10-13T09:40:00Z" })],
    [`meta/${G}/presets.json`, PRESETS],
    ["meta/symbols.json", SYMBOLS],
    [`tensors/${G}/${HASH}/5y.json`, TENSOR],
  ]);
  const dataGets: string[] = [];
  const dataHeads: string[] = [];
  const assetCalls: string[] = [];
  const limiterCalls: LimiterCall[] = [];
  const env = {
    PS_GATE_SECRET: SECRET,
    PS_PRIVATE_PREVIEW: "0",
    API_ORIGIN,
    SHARE_FROM: "sender@example.org",
    SHARE_REPLY_TO: "replies@example.org",
    SHARE_CAP_IP_MINUTE: "1",
    SHARE_CAP_IP_DAY: "3",
    SHARE_CAP_GLOBAL_DAY: "50",
    MAILCHANNELS_API_KEY: "test",
    MAILCHANNELS_DKIM_PRIVATE_KEY: "unit-test-dkim",
    DATA: {
      get: async (key: string) => {
        dataGets.push(key);
        const text = objects.get(key);
        if (text === undefined) return null;
        return {
          key,
          etag: ETAG,
          httpEtag: `"${ETAG}"`,
          get body() {
            return new Response(text).body;
          },
          text: async () => text,
          json: async () => JSON.parse(text) as unknown,
        };
      },
      head: async (key: string) => {
        dataHeads.push(key);
        const text = objects.get(key);
        return text === undefined ? null : { key, etag: ETAG, httpEtag: `"${ETAG}"`, size: text.length };
      },
    },
    ASSETS: {
      fetch: async (request: Request) => {
        assetCalls.push(new URL(request.url).pathname);
        return new Response(PAGE, { headers: { "content-type": "text/html" } });
      },
    },
    SHARE_LIMITER: {
      idFromName: (name: string) => ({ name }),
      get: (id: { name: string }) => ({
        fetch: async (input: string | Request, init?: RequestInit) => {
          const request = new Request(input, init);
          const call = { name: id.name, url: request.url, body: (await request.json()) as unknown };
          limiterCalls.push(call);
          return limiter(call);
        },
      }),
    },
    ...overrides,
  };
  return { env, objects, dataGets, dataHeads, assetCalls, limiterCalls };
}
function allowAll() {
  return new Response(JSON.stringify({ allowed: true }), { headers: { "content-type": "application/json" } });
}

type Worker = { fetch(request: Request, env: unknown, ctx: unknown): Promise<Response> };
async function loadWorker(): Promise<Worker> {
  vi.resetModules();
  const mod = (await import("../worker/index")) as unknown as { default: Worker };
  return mod.default;
}
const ctx = { waitUntil: () => undefined, passThroughOnException: () => undefined, props: {} };
const call = (worker: Worker, env: unknown, url: string, init: RequestInit = {}) =>
  worker.fetch(new Request(url, { redirect: "manual", ...init }), env, ctx);
const sharePost = (worker: Worker, env: unknown, headers: Record<string, string> = {}) =>
  call(worker, env, `${SITE}/api/share`, {
    method: "POST",
    headers: { origin: SITE, "content-type": "application/json", "cf-connecting-ip": "203.0.113.9", ...headers },
    body: SHARE_BODY,
  });
const errorCode = async (res: Response) => ((await res.json()) as { error: { code: string } }).error.code;

describe("worker routing", () => {
  beforeEach(() => {
    installTimingSafeEqual();
    originCalls = [];
    logs = [];
    originResponse = () => new Response("{}", { headers: { "content-type": "application/json" } });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | Request, init?: RequestInit) => {
        const request = new Request(input, init);
        originCalls.push({ url: request.url, method: request.method, headers: Array.from(request.headers.entries()), body: await request.text() });
        return originResponse();
      }),
    );
    for (const level of ["log", "info", "warn", "error", "debug"] as const) {
      vi.spyOn(console, level).mockImplementation((...args: unknown[]) => void logs.push(args.map(String).join(" ")));
    }
  });
  afterEach(() => {
    expect(logs.join("\n")).not.toContain(SECRET);
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("the host check runs before the preview gate", async () => {
    const worker = await loadWorker();
    const e = makeEnv({ PS_PRIVATE_PREVIEW: "1" });
    const www = await call(worker, e.env, "https://www.portfoliosight.ai/deep/link?u=tsp&f=VTI:60,BND:40");
    expect(www.status).toBe(301);
    expect(www.headers.get("location")).toBe(`${SITE}/deep/link?u=tsp&f=VTI:60,BND:40`);
    const foreign = await call(worker, e.env, "https://portfoliosight.example.net/");
    expect(foreign.status).toBe(404);
    expect((await foreign.text()).toLowerCase()).not.toContain("private preview");
    // a key on a foreign host is never honoured
    const keyed = await call(worker, e.env, `https://portfoliosight.example.net/?k=${SECRET}`);
    expect(keyed.status).toBe(404);
    expect(keyed.headers.get("set-cookie")).toBeNull();
    expect(e.assetCalls).toEqual([]);
    expect(e.dataGets).toEqual([]);
  });

  it("the current generation is held for 60 seconds, then read again", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-13T12:00:00Z"));
    const worker = await loadWorker();
    const e = makeEnv();
    expect((await call(worker, e.env, `${SITE}/api/presets`)).status).toBe(200);
    vi.setSystemTime(new Date("2026-10-13T12:00:59Z"));
    const second = await call(worker, e.env, `${SITE}/api/presets`);
    expect(await second.text()).toBe(PRESETS);
    expect(e.dataGets).toEqual(["meta/current.json", `meta/${G}/presets.json`, `meta/${G}/presets.json`]);

    // a new generation is picked up once the minute has passed
    const next = "2026-10-13-0.1.0";
    e.objects.set("meta/current.json", JSON.stringify({ generation: next }));
    e.objects.set(`meta/${next}/presets.json`, JSON.stringify({ generation: next }));
    e.dataGets.length = 0;
    vi.setSystemTime(new Date("2026-10-13T12:01:01Z"));
    const third = await call(worker, e.env, `${SITE}/api/presets`);
    expect(JSON.parse(await third.text())).toEqual({ generation: next });
    expect(e.dataGets).toEqual(["meta/current.json", `meta/${next}/presets.json`]);
  });

  it("a missing or malformed generation pointer is a 503 and is never used as a key", async () => {
    for (const current of [null, "not json", JSON.stringify({ generation: "../../secrets" }), JSON.stringify({ generation: 7 }), JSON.stringify([])]) {
      const worker = await loadWorker();
      const e = makeEnv();
      if (current === null) e.objects.delete("meta/current.json");
      else e.objects.set("meta/current.json", current);
      const res = await call(worker, e.env, `${SITE}/api/presets`);
      expect(res.status, String(current)).toBe(503);
      expect(await errorCode(res)).toBe("unavailable");
      expect(res.headers.get("cache-control")).toBe("no-store");
      expect(e.dataGets, String(current)).toEqual(["meta/current.json"]);
    }
    // the pointer names a generation whose presets are not there: 503, and the pointer is re-read next time
    const worker = await loadWorker();
    const e = makeEnv();
    e.objects.delete(`meta/${G}/presets.json`);
    expect((await call(worker, e.env, `${SITE}/api/presets`)).status).toBe(503);
    expect((await call(worker, e.env, `${SITE}/api/presets`)).status).toBe(503);
    expect(e.dataGets.filter((k) => k === "meta/current.json").length).toBe(2);
    e.objects.delete("meta/symbols.json");
    expect((await call(worker, e.env, `${SITE}/api/symbols`)).status).toBe(503);
    expect(originCalls).toEqual([]);
  });

  it("a storage failure is a 503 without detail", async () => {
    const worker = await loadWorker();
    const e = makeEnv({
      DATA: {
        get: async () => {
          throw new Error(`storage exploded near ${SECRET}`);
        },
      },
    });
    const res = await call(worker, e.env, `${SITE}/api/symbols`);
    expect(res.status).toBe(503);
    expect(await res.text()).not.toContain("exploded");
  });

  it("every /api/ response says whether preview is on, and pages do not", async () => {
    const worker = await loadWorker();
    for (const preview of ["0", "1"]) {
      const e = makeEnv({ PS_PRIVATE_PREVIEW: preview });
      const gate = { "x-ps-gate": SECRET };
      const responses = [
        await call(worker, e.env, `${SITE}/api/presets`, { headers: gate }),
        await call(worker, e.env, `${SITE}/api/symbols`, { headers: gate }),
        await call(worker, e.env, `${SITE}/api/tensors/${G}/${HASH}/5y`, { headers: gate }),
        await call(worker, e.env, `${SITE}/api/tensors/${G}/${HASH}/1y`, { headers: gate }),
        await call(worker, e.env, `${SITE}/api/health`, { headers: gate }),
        await call(worker, e.env, `${SITE}/api/nope`, { headers: gate }),
        await call(worker, e.env, `${SITE}/api/tensors/x/y/z`, { headers: gate }),
        await sharePost(worker, e.env, gate),
        await call(worker, e.env, `${SITE}/api/presets`),
      ];
      for (const res of responses) expect(res.headers.get("x-ps-preview"), `${preview} ${res.status}`).toBe(preview);
      expect(responses[8].status).toBe(preview === "1" ? 403 : 200);
      const page = await call(worker, e.env, `${SITE}/`, { headers: gate });
      expect(page.headers.get("x-ps-preview")).toBeNull();
    }
  });

  it("a forwarded request carries only the listed headers and no query", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const visitor = {
      cookie: "cf_clearance=abc; ps_preview=def; session=ghi",
      authorization: "Bearer visitor-token",
      "x-ps-gate": "client-supplied",
      "x-forwarded-for": "198.51.100.1",
      "user-agent": "unit-test-agent",
      referer: `${SITE}/?u=tsp`,
      origin: SITE,
      "cf-connecting-ip": "203.0.113.50",
      "content-type": "application/json; charset=utf-8",
    };
    await call(worker, e.env, `${SITE}/api/tensors?debug=1`, { method: "POST", headers: visitor, body: '{"funds":[],"lookback":"5y"}' });
    await call(worker, e.env, `${SITE}/api/health?x=1`, { headers: visitor });
    await call(worker, e.env, `${SITE}/api/tensors/${G}/${HASH}/10y?y=2`, { headers: visitor });
    expect(originCalls.map((c) => `${c.method} ${c.url}`)).toEqual([
      `POST ${API_ORIGIN}/v1/tensors`,
      `GET ${API_ORIGIN}/v1/health`,
      `GET ${API_ORIGIN}/v1/tensors/${G}/${HASH}/10y`,
    ]);
    const names = (c: OriginCall) => c.headers.map(([name]) => name).sort();
    expect(names(originCalls[0])).toEqual(["accept", "cf-connecting-ip", "content-type", "x-ps-gate"]);
    expect(names(originCalls[1])).toEqual(["accept", "cf-connecting-ip", "x-ps-gate"]);
    expect(names(originCalls[2])).toEqual(["accept", "cf-connecting-ip", "x-ps-gate"]);
    for (const c of originCalls) {
      const headers = new Map(c.headers);
      expect(headers.get("x-ps-gate")).toBe(SECRET);
      expect(headers.get("accept")).toBe("application/json");
      expect(headers.get("cf-connecting-ip")).toBe("203.0.113.50");
    }
    expect(new Map(originCalls[0].headers).get("content-type")).toBe("application/json; charset=utf-8");
    expect(originCalls[0].body).toBe('{"funds":[],"lookback":"5y"}');
  });

  it("an upstream response comes back with its status, body and caching, and nothing else of its headers", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    originResponse = () =>
      new Response('{"error":{"code":"rate_limited"}}', {
        status: 429,
        headers: { "content-type": "application/json", "cache-control": "no-store", "retry-after": "17", "set-cookie": "upstream=1", "x-internal": "host-detail", server: "uvicorn" },
      });
    const res = await call(worker, e.env, `${SITE}/api/health`);
    expect(res.status).toBe(429);
    expect(await res.text()).toBe('{"error":{"code":"rate_limited"}}');
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(res.headers.get("retry-after")).toBe("17");
    expect(res.headers.get("x-ps-source")).toBe("origin");
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("x-internal")).toBeNull();
    expect(res.headers.get("server")).toBeNull();
    // an upstream answer without a caching header is not cacheable
    originResponse = () => new Response("{}", { status: 200 });
    expect((await call(worker, e.env, `${SITE}/api/health`)).headers.get("cache-control")).toBe("no-store");
  });

  it("an unreachable origin is a 502 and an unset gate secret never reaches the origin", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    originResponse = () => {
      throw new Error(`connect failed with ${SECRET}`);
    };
    const res = await call(worker, e.env, `${SITE}/api/health`);
    expect(res.status).toBe(502);
    expect(await errorCode(res)).toBe("origin_unreachable");
    expect(res.headers.get("x-ps-source")).toBe("origin");
    expect(res.headers.get("cache-control")).toBe("no-store");

    originCalls.length = 0;
    const unset = makeEnv({ PS_GATE_SECRET: undefined });
    const refused = await call(worker, unset.env, `${SITE}/api/health`);
    expect(refused.status).toBe(503);
    expect(originCalls).toEqual([]);
  });

  it("an oversized POST /api/tensors body is refused before the origin is called", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const big = JSON.stringify({ funds: [], pad: "p".repeat(17_000) });
    const res = await call(worker, e.env, `${SITE}/api/tensors`, { method: "POST", headers: { "content-type": "application/json" }, body: big });
    expect(res.status).toBe(413);
    expect(await errorCode(res)).toBe("payload_too_large");
    expect(originCalls).toEqual([]);
    const fits = JSON.stringify({ funds: [], pad: "p".repeat(15_000) });
    await call(worker, e.env, `${SITE}/api/tensors`, { method: "POST", headers: { "content-type": "application/json" }, body: fits });
    expect(originCalls.length).toBe(1);
    expect(originCalls[0].body).toBe(fits);
  });

  it("a stored tensor is served with its ETag and the immutable policy", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const res = await call(worker, e.env, `${SITE}/api/tensors/${G}/${HASH}/5y`);
    expect(res.status).toBe(200);
    expect(await res.text()).toBe(TENSOR);
    expect(res.headers.get("etag")).toBe(`"${ETAG}"`);
    expect(res.headers.get("cache-control")).toBe("public, max-age=86400, immutable");
    expect(res.headers.get("content-type")).toContain("application/json");
    expect(res.headers.get("x-ps-source")).toBe("r2");
    expect(e.dataGets).toEqual([`tensors/${G}/${HASH}/5y.json`]);
  });

  it("a stored tensor answers HEAD as it answers GET, without the body and without reading it", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const res = await call(worker, e.env, `${SITE}/api/tensors/${G}/${HASH}/5y`, { method: "HEAD" });
    expect(res.status).toBe(200);
    expect(await res.text()).toBe("");
    expect(res.headers.get("etag")).toBe(`"${ETAG}"`);
    expect(res.headers.get("cache-control")).toBe("public, max-age=86400, immutable");
    expect(res.headers.get("content-type")).toContain("application/json");
    expect(res.headers.get("x-ps-source")).toBe("r2");
    expect(e.dataHeads).toEqual([`tensors/${G}/${HASH}/5y.json`]);
    expect(e.dataGets).toEqual([]);
    expect(originCalls).toEqual([]);
  });

  it("HEAD for a tensor that is not stored asks the origin with GET and passes on its status and listed headers, no body", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    originResponse = () =>
      new Response(JSON.stringify({ status: "building" }), { status: 202, headers: { "content-type": "application/json", "retry-after": "2" } });
    const res = await call(worker, e.env, `${SITE}/api/tensors/${G}/aaaaaaaaaaaaaaaa/5y`, {
      method: "HEAD",
      headers: { "cf-connecting-ip": "203.0.113.9" },
    });
    expect(res.status).toBe(202);
    expect(await res.text()).toBe("");
    expect(res.headers.get("x-ps-source")).toBe("origin");
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(res.headers.get("retry-after")).toBe("2");
    expect(originCalls.map((c) => [c.method, c.url])).toEqual([["GET", `${API_ORIGIN}/v1/tensors/${G}/aaaaaaaaaaaaaaaa/5y`]]);
    expect(Object.fromEntries(originCalls[0].headers)["cf-connecting-ip"]).toBe("203.0.113.9");
    expect(e.dataHeads).toEqual([`tensors/${G}/aaaaaaaaaaaaaaaa/5y.json`]);
    expect(e.dataGets).toEqual([]);
  });

  it("malformed tensor paths and unknown API paths touch neither storage, origin nor assets", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const cases: Array<[string, string, number]> = [
      ["GET", `/api/tensors/${G}/${HASH}/7y`, 400],
      ["GET", `/api/tensors/${G}/${HASH.toUpperCase()}/5y`, 400],
      ["GET", `/api/tensors/..%2F..%2Fmeta/${HASH}/5y`, 400],
      ["GET", `/api/tensors/${G}/${HASH}/5y%00`, 400],
      ["GET", `/api/tensors/${G}/${HASH}`, 404],
      ["GET", `/api/tensors/${G}/${HASH}/5y/`, 404],
      ["HEAD", `/api/tensors/${G}/${HASH}/7y`, 400],
      ["HEAD", `/api/tensors/${G}/${HASH}`, 404],
      ["HEAD", "/api/tensors", 404],
      ["HEAD", "/api/health", 404],
      ["GET", "/api", 404],
      ["GET", "/api/", 404],
      ["GET", "/api/share", 404],
      ["HEAD", "/api/presets", 404],
      ["POST", "/api/symbols", 404],
      ["GET", "/api/Presets", 404],
      ["GET", "/api//presets", 404],
    ];
    for (const [method, path, status] of cases) {
      const res = await call(worker, e.env, SITE + path, { method });
      expect(res.status, `${method} ${path}`).toBe(status);
      expect(res.headers.get("cache-control"), path).toBe("no-store");
      if (method !== "HEAD") expect(typeof (await errorCode(res)), path).toBe("string");
    }
    expect(e.dataGets).toEqual([]);
    expect(e.dataHeads).toEqual([]);
    expect(e.assetCalls).toEqual([]);
    expect(originCalls).toEqual([]);
  });

  it("paths that only look like the API go to the static assets", async () => {
    const worker = await loadWorker();
    for (const path of ["/apix", "/apis/presets", "/API/presets", "/index.html"]) {
      const e = makeEnv();
      const res = await call(worker, e.env, SITE + path);
      expect(await res.text(), path).toBe(PAGE);
      expect(e.assetCalls, path).toEqual([path]);
    }
  });

  it("a share is checked against the one global limiter object, with the visitor address and exemption", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const res = await sharePost(worker, e.env);
    expect(res.status).toBe(202);
    expect(e.limiterCalls).toEqual([{ name: "global", url: expect.any(String) as unknown as string, body: { ip: "203.0.113.9", exempt: false } }]);
    const exempt = await sharePost(worker, e.env, { "x-ps-gate": SECRET });
    expect(exempt.status).toBe(202);
    expect(e.limiterCalls[1].body).toEqual({ ip: "203.0.113.9", exempt: true });
    // the limiter exchange is not an outbound fetch
    expect(originCalls).toEqual([]);
  });

  it("a refusing, failing or malformed limiter answer refuses the share", async () => {
    const worker = await loadWorker();
    const answers: Array<() => Response> = [
      () => new Response(JSON.stringify({ allowed: false })),
      () => new Response(JSON.stringify({ allowed: "yes" })),
      () => new Response("not json"),
      () => new Response(JSON.stringify({ allowed: true }), { status: 500 }),
      () => {
        throw new Error("limiter down");
      },
    ];
    for (const answer of answers) {
      const e = makeEnv({ MAILCHANNELS_API_KEY: "unit-test-mail-key" }, answer);
      const res = await sharePost(worker, e.env);
      expect(res.status).toBe(429);
      expect(await errorCode(res)).toBe("rate_limited");
      expect(e.limiterCalls.length).toBe(1);
      expect(originCalls, "a refused share was mailed").toEqual([]);
    }
  });

  it("exports the limiter class the Durable Object binding names", async () => {
    const mod = (await import("../worker/index")) as unknown as Record<string, unknown>;
    const share = (await import("../worker/share")) as unknown as Record<string, unknown>;
    expect(typeof mod.ShareLimiter).toBe("function");
    expect(mod.ShareLimiter).toBe(share.ShareLimiter);
  });
});
