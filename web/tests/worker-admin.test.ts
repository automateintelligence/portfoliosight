import { createHmac, timingSafeEqual as nodeTimingSafeEqual } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Access tiers (engines spec 6.2): the admin link, its cookie, the tier the page reads, and the
// tier header the Worker sends to the API.
const GATE = "unit-test-gate-value";
const ADMIN = "a".repeat(16) + "unit-test-admin-secret-value-0123456789";
const SITE = "https://portfoliosight.ai";
const API_ORIGIN = "https://api.portfoliosight.ai";
const PAGE = "<!doctype html><title>site</title>SITE-PAGE";
const MAX_AGE_180_DAYS = 180 * 24 * 60 * 60;

type OriginCall = { url: string; method: string; headers: Map<string, string> };
let originCalls: OriginCall[] = [];
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

function makeEnv(overrides: Record<string, unknown> = {}) {
  const assetCalls: string[] = [];
  const env = {
    PS_GATE_SECRET: GATE,
    PS_ADMIN_SECRET: ADMIN,
    PS_PRIVATE_PREVIEW: "0",
    PS_MENU_MAX_PUBLIC: "30",
    PS_MENU_MAX_ADMIN: "100",
    API_ORIGIN,
    MAILCHANNELS_API_KEY: "test",
    DATA: { get: async () => null, head: async () => null },
    ASSETS: {
      fetch: async (request: Request) => {
        assetCalls.push(new URL(request.url).pathname + new URL(request.url).search);
        return new Response(PAGE, { headers: { "content-type": "text/html" } });
      },
    },
    SHARE_LIMITER: {
      idFromName: (name: string) => ({ name }),
      get: () => ({ fetch: async () => new Response(JSON.stringify({ allowed: true })) }),
    },
    ...overrides,
  };
  return { env, assetCalls };
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
const proof = (secret: string, label: string) => createHmac("sha256", secret).update(label).digest("hex");
const adminCookie = `ps_admin=${proof(ADMIN, "ps_admin")}`;
const tierOf = async (res: Response) => (await res.json()) as { tier: string; menu_max: number };

describe("admin link and tier", () => {
  beforeEach(() => {
    installTimingSafeEqual();
    originCalls = [];
    logs = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | Request, init?: RequestInit) => {
        const request = new Request(input, init);
        originCalls.push({ url: request.url, method: request.method, headers: new Map(request.headers.entries()) });
        return new Response("{}", { status: 202, headers: { "content-type": "application/json" } });
      }),
    );
    for (const level of ["log", "info", "warn", "error", "debug"] as const) {
      vi.spyOn(console, level).mockImplementation((...args: unknown[]) => void logs.push(args.map(String).join(" ")));
    }
  });
  afterEach(() => {
    expect(logs.join("\n")).not.toContain(ADMIN);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("?admin=<secret> sets an HttpOnly, Secure, SameSite=Strict proof cookie and redirects without the parameter", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const res = await call(worker, e.env, `${SITE}/deep/link?u=tsp&admin=${ADMIN}&lb=5y`);
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe(`${SITE}/deep/link?u=tsp&lb=5y`);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const cookie = res.headers.get("set-cookie") ?? "";
    const parts = cookie.split(";").map((p) => p.trim());
    expect(parts[0]).toBe(adminCookie);
    expect(parts).toEqual(expect.arrayContaining(["HttpOnly", "Secure", "SameSite=Strict", "Path=/", `Max-Age=${MAX_AGE_180_DAYS}`]));
    // the cookie proves the secret without carrying it, and is not the preview cookie
    expect(cookie).not.toContain(ADMIN);
    expect(cookie).not.toContain(Buffer.from(ADMIN).toString("base64"));
    expect(parts[0]).not.toBe(`ps_admin=${proof(GATE, "ps_preview")}`);
    expect(await res.text()).not.toContain(ADMIN);
    expect(e.assetCalls).toEqual([]);
  });

  it("a wrong value gets the same redirect and no cookie: nothing tells it apart", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const right = await call(worker, e.env, `${SITE}/?admin=${ADMIN}`);
    for (const wrong of ["", "nope", ADMIN.slice(0, -1), `${ADMIN}0`, ADMIN.toUpperCase(), GATE, proof(ADMIN, "ps_admin")]) {
      const res = await call(worker, e.env, `${SITE}/?admin=${encodeURIComponent(wrong)}`);
      expect(res.status, wrong).toBe(302);
      expect(res.headers.get("location")).toBe(right.headers.get("location"));
      expect(res.headers.get("set-cookie"), wrong).toBeNull();
      expect(await res.text()).toBe("");
    }
    expect(e.assetCalls).toEqual([]);
  });

  it("duplicates, a bare or encoded name and HEAD: the first value decides and every copy is stripped", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const cookieOf = (res: Response) => (res.headers.get("set-cookie") ?? "").split(";")[0];
    const offFirst = await call(worker, e.env, `${SITE}/?admin=off&u=tsp&admin=${ADMIN}`);
    expect(offFirst.headers.get("location")).toBe(`${SITE}/?u=tsp`);
    expect(cookieOf(offFirst)).toBe("ps_admin=");
    const secretFirst = await call(worker, e.env, `${SITE}/?admin=${ADMIN}&admin=x`);
    expect(secretFirst.headers.get("location")).toBe(`${SITE}/`);
    expect(cookieOf(secretFirst)).toBe(adminCookie);
    const bare = await call(worker, e.env, `${SITE}/?u=tsp&admin`);
    expect(bare.status).toBe(302);
    expect(bare.headers.get("location")).toBe(`${SITE}/?u=tsp`);
    expect(bare.headers.get("set-cookie")).toBeNull();
    const encoded = await call(worker, e.env, `${SITE}/?%61dmin=${ADMIN}&lb=5y`);
    expect(encoded.headers.get("location")).toBe(`${SITE}/?lb=5y`);
    expect(cookieOf(encoded)).toBe(adminCookie);
    const head = await call(worker, e.env, `${SITE}/?admin=${ADMIN}`, { method: "HEAD" });
    expect(head.status).toBe(302);
    expect(cookieOf(head)).toBe(adminCookie);
    expect(e.assetCalls).toEqual([]);
  });

  it("?admin=off clears the cookie", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const res = await call(worker, e.env, `${SITE}/?u=tsp&admin=off`, { headers: { cookie: adminCookie } });
    expect(res.status).toBe(302);
    expect(res.headers.get("location")).toBe(`${SITE}/?u=tsp`);
    const parts = (res.headers.get("set-cookie") ?? "").split(";").map((p) => p.trim());
    expect(parts[0]).toBe("ps_admin=");
    expect(parts).toEqual(expect.arrayContaining(["HttpOnly", "Secure", "SameSite=Strict", "Path=/", "Max-Age=0"]));
  });

  it("GET /api/tier: public and 30 without the cookie, admin and 100 with it", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const plain = await call(worker, e.env, `${SITE}/api/tier`);
    expect(plain.status).toBe(200);
    expect(plain.headers.get("cache-control")).toBe("no-store");
    expect(await tierOf(plain)).toEqual({ tier: "public", menu_max: 30 });
    const admin = await call(worker, e.env, `${SITE}/api/tier`, { headers: { cookie: `cf_clearance=x; ${adminCookie}` } });
    expect(await tierOf(admin)).toEqual({ tier: "admin", menu_max: 100 });
    // the numbers are the vars'
    const custom = makeEnv({ PS_MENU_MAX_PUBLIC: "12", PS_MENU_MAX_ADMIN: "50" });
    expect(await tierOf(await call(worker, custom.env, `${SITE}/api/tier`))).toEqual({ tier: "public", menu_max: 12 });
    expect(await tierOf(await call(worker, custom.env, `${SITE}/api/tier`, { headers: { cookie: adminCookie } }))).toEqual({ tier: "admin", menu_max: 50 });
    // malformed vars fall back to 30 and 100
    const broken = makeEnv({ PS_MENU_MAX_PUBLIC: "lots", PS_MENU_MAX_ADMIN: "1" });
    expect(await tierOf(await call(worker, broken.env, `${SITE}/api/tier`))).toEqual({ tier: "public", menu_max: 30 });
    expect(await tierOf(await call(worker, broken.env, `${SITE}/api/tier`, { headers: { cookie: adminCookie } }))).toEqual({ tier: "admin", menu_max: 100 });
  });

  it("a forged or stale cookie, or a client x-ps-tier header, is public", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const forged = [
      `ps_admin=${ADMIN}`,
      `ps_admin=${proof(GATE, "ps_preview")}`,
      `ps_admin=${proof(ADMIN, "ps_preview")}`,
      `ps_admin=${proof("an-older-admin-secret-value-0123456789", "ps_admin")}`,
      `ps_admin=${"0".repeat(64)}`,
      `ps_preview=${proof(GATE, "ps_preview")}`,
      "ps_admin=",
    ];
    for (const cookie of forged) {
      const res = await call(worker, e.env, `${SITE}/api/tier`, { headers: { cookie, "x-ps-tier": "admin" } });
      expect(await tierOf(res), cookie).toEqual({ tier: "public", menu_max: 30 });
    }
  });

  it("admin is off when its secret is unset, short, or the gate secret's value", async () => {
    const worker = await loadWorker();
    // the last case: an admin secret that equals the gate secret
    const cases: Array<[string | undefined, string]> = [[undefined, GATE], ["", GATE], ["short-admin-secret", GATE], [ADMIN, ADMIN]];
    for (const [secret, gate] of cases) {
      const e = makeEnv({ PS_ADMIN_SECRET: secret, PS_GATE_SECRET: gate });
      const link = await call(worker, e.env, `${SITE}/?admin=${encodeURIComponent(secret ?? "")}`);
      expect(link.status).toBe(302);
      expect(link.headers.get("set-cookie"), String(secret)).toBeNull();
      const cookie = secret ? `ps_admin=${proof(secret, "ps_admin")}` : "ps_admin=";
      expect(await tierOf(await call(worker, e.env, `${SITE}/api/tier`, { headers: { cookie } }))).toEqual({ tier: "public", menu_max: 30 });
    }
  });

  it("forwards x-ps-tier: admin only for a verified cookie and never passes the visitor's own", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const post = (path: string, headers: Record<string, string>) =>
      call(worker, e.env, `${SITE}${path}`, { method: "POST", headers: { "content-type": "application/json", ...headers }, body: "{}" });
    await post("/api/tensors", { cookie: adminCookie });
    await post("/api/range", { cookie: adminCookie });
    await post("/api/tensors", { "x-ps-tier": "admin" });
    await post("/api/range", { "x-ps-tier": "admin", cookie: `ps_admin=${ADMIN}` });
    await call(worker, e.env, `${SITE}/api/health`, { headers: { "x-ps-tier": "admin" } });
    expect(originCalls.map((c) => `${c.method} ${c.url}`)).toEqual([
      `POST ${API_ORIGIN}/v1/tensors`,
      `POST ${API_ORIGIN}/v1/range`,
      `POST ${API_ORIGIN}/v1/tensors`,
      `POST ${API_ORIGIN}/v1/range`,
      `GET ${API_ORIGIN}/v1/health`,
    ]);
    expect(originCalls.map((c) => c.headers.get("x-ps-tier") ?? null)).toEqual(["admin", "admin", null, null, null]);
    for (const c of originCalls) {
      expect(c.headers.get("x-ps-gate")).toBe(GATE);
      expect(c.headers.has("cookie")).toBe(false);
    }
  });

  it("the preview gate still comes first: ?admin= without a preview credential gets the preview page", async () => {
    const worker = await loadWorker();
    const e = makeEnv({ PS_PRIVATE_PREVIEW: "1" });
    const blocked = await call(worker, e.env, `${SITE}/?admin=${ADMIN}`);
    expect(blocked.status).toBe(403);
    expect(blocked.headers.get("set-cookie")).toBeNull();
    const previewCookie = `ps_preview=${proof(GATE, "ps_preview")}`;
    const opened = await call(worker, e.env, `${SITE}/?admin=${ADMIN}`, { headers: { cookie: previewCookie } });
    expect(opened.status).toBe(302);
    expect(opened.headers.get("set-cookie")?.startsWith(adminCookie)).toBe(true);
    // the two keys at once: the preview key goes first, the admin key stays for the next request
    const both = await call(worker, e.env, `${SITE}/?k=${GATE}&admin=${ADMIN}`);
    expect(both.status).toBe(302);
    expect(both.headers.get("location")).toBe(`${SITE}/?admin=${ADMIN}`);
  });

  it("a page without ?admin= is served as before, and an API path ignores it", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const page = await call(worker, e.env, `${SITE}/?u=tsp`);
    expect(page.status).toBe(200);
    expect(await page.text()).toBe(PAGE);
    const api = await call(worker, e.env, `${SITE}/api/tier?admin=${ADMIN}`);
    expect(api.status).toBe(200);
    expect(api.headers.get("set-cookie")).toBeNull();
    expect(await tierOf(api)).toEqual({ tier: "public", menu_max: 30 });
  });

  it("an emailed link may carry the sender's own limit of funds", async () => {
    const worker = await loadWorker();
    const e = makeEnv();
    const funds = (n: number) => Array.from({ length: n }, (_, i) => `F${i}`).join(",");
    const share = (n: number, cookie?: string) =>
      call(worker, e.env, `${SITE}/api/share`, {
        method: "POST",
        headers: { origin: SITE, "content-type": "application/json", "cf-connecting-ip": "203.0.113.9", ...(cookie ? { cookie } : {}) },
        body: JSON.stringify({ to: "reader@example.org", url: `${SITE}/?f=${funds(n)}` }),
      });
    expect((await share(30)).status).toBe(202);
    expect((await share(31)).status).toBe(400);
    expect((await share(31, adminCookie)).status).toBe(202);
    expect((await share(101, adminCookie)).status).toBe(400);
  });
});
