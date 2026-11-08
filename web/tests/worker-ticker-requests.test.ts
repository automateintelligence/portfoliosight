import { createHmac, timingSafeEqual as nodeTimingSafeEqual } from "node:crypto";
import initSqlJs, { type Database, type SqlValue } from "sql.js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Tickers people ask for that the site does not serve: POST /api/ticker-requests records them
// (one count per visitor address per UTC day), GET reads the list for an admin only. The Durable
// Object runs here against a real SQLite (sql.js) behind the SqlStorage interface.
const SITE = "https://portfoliosight.ai";
const GATE = "unit-test-gate-value";
const ADMIN = "a".repeat(16) + "unit-test-admin-secret-value-0123456789";
const IP = "203.0.113.9";
const OTHER_IP = "198.51.100.4";
const DAY1 = "2026-11-08T12:00:00Z";
const DAY2 = "2026-11-09T00:00:05Z";
const URL_ = `${SITE}/api/ticker-requests`;

let logs: string[] = [];

function installTimingSafeEqual() {
  const bytes = (v: ArrayBuffer | ArrayBufferView) => (v instanceof ArrayBuffer ? Buffer.from(v) : Buffer.from(v.buffer, v.byteOffset, v.byteLength));
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

type Row = Record<string, unknown>;
type Worker = { fetch(request: Request, env: unknown, ctx: unknown): Promise<Response> };
type RecorderClass = new (state: unknown, env: unknown) => { fetch(request: Request): Promise<Response> };

/** SqlStorage over sql.js: `exec(query, ...bindings)` returning a cursor with `toArray()`. */
async function openStorage(): Promise<{ db: Database; state: unknown }> {
  const SQL = await initSqlJs();
  const db = new SQL.Database();
  const sql = {
    exec(query: string, ...bindings: unknown[]) {
      const statement = db.prepare(query);
      try {
        statement.bind(bindings as SqlValue[]);
        const rows: Row[] = [];
        while (statement.step()) rows.push(statement.getAsObject());
        return { toArray: () => rows, one: () => rows[0] };
      } finally {
        statement.free();
      }
    },
  };
  return { db, state: { storage: { sql } } };
}
const dump = (db: Database): string => {
  const tables = db.exec("SELECT name FROM sqlite_master WHERE type = 'table'")[0]?.values.map((r) => String(r[0])) ?? [];
  return tables.map((t) => JSON.stringify(db.exec(`SELECT * FROM ${t}`))).join("\n");
};

type Options = { symbols?: string[] | "missing" | "broken"; recorderDown?: boolean };
async function makeEnv(options: Options = {}) {
  const { db, state } = await openStorage();
  vi.resetModules();
  const mod = (await import("../worker/index")) as unknown as { default: Worker; TickerRequests: RecorderClass };
  const recorder = new mod.TickerRequests(state, {});
  const reads: string[] = [];
  const env = {
    PS_GATE_SECRET: GATE,
    PS_ADMIN_SECRET: ADMIN,
    PS_PRIVATE_PREVIEW: "0",
    API_ORIGIN: "https://api.portfoliosight.ai",
    DATA: {
      get: async (key: string) => {
        reads.push(key);
        if (key !== "meta/symbols.json" || options.symbols === undefined || options.symbols === "missing") return null;
        if (options.symbols === "broken") throw new Error("r2 down");
        return { json: async () => ({ symbols: options.symbols === undefined ? [] : (options.symbols as string[]).map((id) => ({ id })) }) };
      },
      head: async () => null,
    },
    ASSETS: { fetch: async () => new Response("page") },
    SHARE_LIMITER: { idFromName: (n: string) => ({ name: n }), get: () => ({ fetch: async () => new Response(JSON.stringify({ allowed: true })) }) },
    TICKER_REQUESTS: {
      idFromName: (name: string) => ({ name }),
      get: () => ({
        fetch: async (input: string | Request, init?: RequestInit) => {
          if (options.recorderDown) throw new Error("object unavailable");
          return recorder.fetch(new Request(input, init));
        },
      }),
    },
  };
  return { worker: mod.default, env, db, reads };
}

const ctx = { waitUntil: () => undefined, passThroughOnException: () => undefined, props: {} };
const proof = (secret: string, label: string) => createHmac("sha256", secret).update(label).digest("hex");
const adminCookie = `ps_admin=${proof(ADMIN, "ps_admin")}`;

type Made = Awaited<ReturnType<typeof makeEnv>>;
const post = (m: Made, body: unknown, headers: Record<string, string | null> = {}, raw?: string) => {
  const h = new Headers({ origin: SITE, "content-type": "application/json", "cf-connecting-ip": IP });
  for (const [name, value] of Object.entries(headers)) {
    if (value === null) h.delete(name);
    else h.set(name, value);
  }
  return m.worker.fetch(new Request(URL_, { method: "POST", headers: h, body: raw ?? JSON.stringify(body) }), m.env, ctx);
};
const send = (m: Made, tickers: unknown, source: unknown = "csv", headers: Record<string, string | null> = {}) => post(m, { tickers, source }, headers);
const read = (m: Made, headers: Record<string, string> = { cookie: adminCookie }, method = "GET") =>
  m.worker.fetch(new Request(URL_, { method, headers }), m.env, ctx);
type Listed = { ticker: string; count: number; csv: number; picker: number; first_seen: string; last_seen: string };
const listed = async (m: Made) => {
  const res = await read(m);
  expect(res.status).toBe(200);
  return (await res.json()) as Listed[];
};
const counts = async (m: Made) => Object.fromEntries((await listed(m)).map((r) => [r.ticker, r.count]));
const errorCode = async (res: Response) => ((await res.json()) as { error: { code: string } }).error.code;

describe("ticker requests", () => {
  beforeEach(() => {
    installTimingSafeEqual();
    logs = [];
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(DAY1));
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("no network in these tests");
      }),
    );
    for (const level of ["log", "info", "warn", "error", "debug"] as const) {
      vi.spyOn(console, level).mockImplementation((...args: unknown[]) => void logs.push(args.map(String).join(" ")));
    }
  });
  afterEach(() => {
    const all = logs.join("\n");
    for (const hidden of [GATE, ADMIN, IP, OTHER_IP, "ZQXJ"]) expect(all).not.toContain(hidden);
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  describe("recording", () => {
    it("records the tickers of a valid request, upper-cased, and answers 204 with nothing in the body", async () => {
      const m = await makeEnv();
      const res = await send(m, ["zqxj", "ABC.D", "BRK-B"], "csv");
      expect(res.status).toBe(204);
      expect(await res.text()).toBe("");
      expect(res.headers.get("cache-control")).toBe("no-store");
      expect(await listed(m)).toEqual([
        { ticker: "ABC.D", count: 1, csv: 1, picker: 0, first_seen: "2026-11-08", last_seen: "2026-11-08" },
        { ticker: "BRK-B", count: 1, csv: 1, picker: 0, first_seen: "2026-11-08", last_seen: "2026-11-08" },
        { ticker: "ZQXJ", count: 1, csv: 1, picker: 0, first_seen: "2026-11-08", last_seen: "2026-11-08" },
      ]);
    });
    it("counts each source apart", async () => {
      const m = await makeEnv();
      expect((await send(m, ["ZQXJ"], "csv")).status).toBe(204);
      expect((await send(m, ["ZQXJ"], "picker", { "cf-connecting-ip": OTHER_IP })).status).toBe(204);
      expect(await listed(m)).toEqual([{ ticker: "ZQXJ", count: 2, csv: 1, picker: 1, first_seen: "2026-11-08", last_seen: "2026-11-08" }]);
    });
    it("drops tickers of the wrong shape and keeps the rest", async () => {
      const m = await makeEnv();
      const bad = ["VTI!", "ABCDEFGHIJK", "", "a b", "DROP;TABLE", "ü", "<b>", "A/B", 5, null, { id: "X" }, "x\n", " VTI"];
      const res = await send(m, [...bad, "OKAY", "a-b.c", "ABCDEFGHIJ"]);
      expect(res.status).toBe(204);
      expect(Object.keys(await counts(m)).sort()).toEqual(["A-B.C", "ABCDEFGHIJ", "OKAY"]);
    });
    it("counts a ticker named twice in one request once", async () => {
      const m = await makeEnv();
      await send(m, ["ZQXJ", "zqxj", "ZQXJ"]);
      expect(await counts(m)).toEqual({ ZQXJ: 1 });
    });
    it("refuses a request with no valid ticker, and a list of 0 or more than 100", async () => {
      const m = await makeEnv();
      for (const tickers of [[], ["!!"], [5], Array.from({ length: 101 }, (_, i) => `T${i}`), "ZQXJ", { 0: "ZQXJ" }, null]) {
        const res = await send(m, tickers);
        expect(res.status, JSON.stringify(tickers)).toBe(400);
        expect(await errorCode(res)).toBe("invalid_request");
      }
      expect((await send(m, Array.from({ length: 100 }, (_, i) => `T${i}`))).status).toBe(204);
      expect(Object.keys(await counts(m))).toHaveLength(100);
    });
    it("refuses a missing or unknown source", async () => {
      const m = await makeEnv();
      expect((await post(m, { tickers: ["ZQXJ"] })).status, "no source").toBe(400);
      for (const source of ["", "file", "CSV", 1, null]) expect((await send(m, ["ZQXJ"], source)).status, String(source)).toBe(400);
      expect(await listed(m)).toEqual([]);
    });
    it("refuses a body that is not a JSON object, one over 4 KB, another media type and another origin", async () => {
      const m = await makeEnv();
      expect((await post(m, null, {}, "not json")).status).toBe(400);
      expect((await post(m, null, {}, '["ZQXJ"]')).status).toBe(400);
      expect((await post(m, null, {}, "")).status).toBe(400);
      const big = JSON.stringify({ tickers: ["ZQXJ"], source: "csv", pad: "x".repeat(4096) });
      expect(big.length).toBeGreaterThan(4096);
      const tooBig = await post(m, null, {}, big);
      expect(tooBig.status).toBe(413);
      expect(await errorCode(tooBig)).toBe("payload_too_large");
      expect((await post(m, { tickers: ["ZQXJ"], source: "csv" }, { "content-type": "text/plain" })).status).toBe(415);
      for (const origin of ["https://evil.example.com", "http://portfoliosight.ai", `${SITE}/`, "null", null]) {
        const res = await send(m, ["ZQXJ"], "csv", { origin });
        expect(res.status, String(origin)).toBe(403);
        expect(await errorCode(res)).toBe("forbidden_origin");
      }
      expect(await listed(m)).toEqual([]);
    });
    it("never echoes a ticker back, on success or failure", async () => {
      const m = await makeEnv();
      for (const res of [await send(m, ["ZQXJ"]), await send(m, ["ZQXJ", "!"], "nope"), await post(m, null, {}, '{"tickers":["ZQXJ"')]) {
        expect(await res.text()).not.toContain("ZQXJ");
      }
    });
    it("takes only POST: other methods are the unknown-route 404", async () => {
      const m = await makeEnv();
      const unknown = await m.worker.fetch(new Request(`${SITE}/api/no-such-thing`, { method: "PUT" }), m.env, ctx);
      for (const method of ["PUT", "DELETE", "PATCH", "HEAD"]) {
        const res = await m.worker.fetch(new Request(URL_, { method, headers: { origin: SITE, cookie: adminCookie } }), m.env, ctx);
        expect(res.status, method).toBe(404);
        if (method !== "HEAD") expect(await res.text()).toBe(await unknown.clone().text());
      }
    });
  });

  describe("one count per visitor per UTC day", () => {
    it("counts a visitor's repeat of a ticker once, and another visitor's request on top", async () => {
      const m = await makeEnv();
      await send(m, ["ZQXJ"]);
      await send(m, ["ZQXJ"]);
      await send(m, ["ZQXJ"], "picker");
      expect(await counts(m)).toEqual({ ZQXJ: 1 });
      await send(m, ["ZQXJ"], "csv", { "cf-connecting-ip": OTHER_IP });
      expect(await counts(m)).toEqual({ ZQXJ: 2 });
    });
    it("counts a visitor's different tickers each once", async () => {
      const m = await makeEnv();
      await send(m, ["AAA"]);
      await send(m, ["AAA", "BBB"]);
      await send(m, ["BBB", "CCC"]);
      expect(await counts(m)).toEqual({ AAA: 1, BBB: 1, CCC: 1 });
    });
    it("counts the same visitor and ticker again on the next UTC day, and keeps when it was first seen", async () => {
      const m = await makeEnv();
      await send(m, ["ZQXJ"]);
      vi.setSystemTime(new Date("2026-11-08T23:59:59Z"));
      await send(m, ["ZQXJ"]);
      expect(await counts(m)).toEqual({ ZQXJ: 1 });
      vi.setSystemTime(new Date(DAY2));
      await send(m, ["ZQXJ"]);
      expect(await listed(m)).toEqual([{ ticker: "ZQXJ", count: 2, csv: 2, picker: 0, first_seen: "2026-11-08", last_seen: "2026-11-09" }]);
    });
    it("keeps no address: only a salted hash of it, and none of yesterday's keys after the day turns", async () => {
      const m = await makeEnv();
      await send(m, ["ZQXJ"]);
      const first = dump(m.db);
      expect(first).not.toContain(IP);
      expect(first).not.toContain(IP.replaceAll(".", ""));
      const keyOf = () => (m.db.exec("SELECT visitor FROM ticker_seen")[0]?.values ?? []).map((r) => String(r[0]));
      const day1 = keyOf();
      expect(day1).toHaveLength(1);
      expect(day1[0]).toMatch(/^[0-9a-f]{64}$/);
      vi.setSystemTime(new Date(DAY2));
      await send(m, ["ZQXJ"]);
      const day2 = keyOf();
      // yesterday's rows are gone, and the same visitor has a different key under the new day's salt
      expect(day2).toHaveLength(1);
      expect(day2[0]).not.toBe(day1[0]);
      expect(m.db.exec("SELECT COUNT(*) FROM ticker_seen WHERE day < '2026-11-09'")[0].values[0][0]).toBe(0);
      expect(m.db.exec("SELECT COUNT(*) FROM day_salt")[0].values[0][0]).toBe(1);
      expect(dump(m.db)).not.toContain(IP);
    });
    it("lets one visitor add at most 300 new tickers a day, silently, and others and the next day are unaffected", async () => {
      const m = await makeEnv();
      const batch = (from: number) => Array.from({ length: 100 }, (_, i) => `T${from + i}`);
      for (const from of [0, 100, 200, 300]) expect((await send(m, batch(from))).status).toBe(204);
      const table = await counts(m);
      expect(Object.keys(table)).toHaveLength(300);
      expect(table.T299).toBe(1);
      expect(table.T300).toBeUndefined();
      expect((await send(m, batch(300), "csv", { "cf-connecting-ip": OTHER_IP })).status).toBe(204);
      expect((await counts(m)).T300).toBe(1);
      vi.setSystemTime(new Date(DAY2));
      await send(m, batch(300));
      expect((await counts(m)).T300).toBe(2);
    });
    it("treats a missing or malformed address as one visitor", async () => {
      const m = await makeEnv();
      await send(m, ["ZQXJ"], "csv", { "cf-connecting-ip": null });
      await send(m, ["ZQXJ"], "csv", { "cf-connecting-ip": "not an address!" });
      expect(await counts(m)).toEqual({ ZQXJ: 1 });
    });
  });

  describe("tickers the site already serves", () => {
    it("are not counted, and a request of only served tickers is a quiet 204", async () => {
      const m = await makeEnv({ symbols: ["VTI", "BND"] });
      expect((await send(m, ["VTI", "ZQXJ", "bnd"])).status).toBe(204);
      expect(await counts(m)).toEqual({ ZQXJ: 1 });
      expect((await send(m, ["VTI", "BND"], "picker", { "cf-connecting-ip": OTHER_IP })).status).toBe(204);
      expect(await counts(m)).toEqual({ ZQXJ: 1 });
      expect(m.reads).toContain("meta/symbols.json");
    });
    it("reads the catalog once a minute, not for every request", async () => {
      const m = await makeEnv({ symbols: ["VTI"] });
      await send(m, ["AAA"]);
      await send(m, ["BBB"]);
      expect(m.reads.filter((k) => k === "meta/symbols.json")).toHaveLength(1);
      vi.setSystemTime(new Date(Date.parse(DAY1) + 61_000));
      await send(m, ["CCC"]);
      expect(m.reads.filter((k) => k === "meta/symbols.json")).toHaveLength(2);
    });
    it("counts everything when the catalog cannot be read", async () => {
      for (const symbols of ["missing", "broken"] as const) {
        const m = await makeEnv({ symbols });
        expect((await send(m, ["VTI", "ZQXJ"])).status, symbols).toBe(204);
        expect(await counts(m)).toEqual({ VTI: 1, ZQXJ: 1 });
      }
    });
  });

  describe("reading the list", () => {
    it("is for an admin only: anyone else gets the unknown-route 404, with nothing to tell the two apart", async () => {
      const m = await makeEnv();
      await send(m, ["ZQXJ"]);
      const unknown = await m.worker.fetch(new Request(`${SITE}/api/no-such-thing`), m.env, ctx);
      const unknownBody = await unknown.text();
      expect(unknown.status).toBe(404);
      const strangers: Record<string, string>[] = [{}, { cookie: "ps_admin=" + "0".repeat(64) }, { cookie: adminCookie.replace("ps_admin", "other") }, { "x-ps-gate": GATE }, { "x-ps-tier": "admin" }, { authorization: `Bearer ${ADMIN}` }];
      for (const headers of strangers) {
        const res = await read(m, headers);
        expect(res.status, JSON.stringify(headers)).toBe(404);
        expect(await res.text()).toBe(unknownBody);
        expect(res.headers.get("content-type")).toBe(unknown.headers.get("content-type"));
      }
    });
    it("stays closed while no admin secret is configured", async () => {
      const m = await makeEnv();
      (m.env as { PS_ADMIN_SECRET?: string }).PS_ADMIN_SECRET = undefined;
      expect((await read(m)).status).toBe(404);
    });
    it("gives an admin the list as JSON, never cached", async () => {
      const m = await makeEnv();
      await send(m, ["ZQXJ"]);
      const res = await read(m);
      expect(res.status).toBe(200);
      expect(res.headers.get("cache-control")).toBe("no-store");
      expect(res.headers.get("content-type")).toContain("application/json");
      expect(await res.json()).toEqual([{ ticker: "ZQXJ", count: 1, csv: 1, picker: 0, first_seen: "2026-11-08", last_seen: "2026-11-08" }]);
    });
    it("is an empty list before anyone has asked", async () => {
      const m = await makeEnv();
      expect(await listed(m)).toEqual([]);
    });
    it("sorts by count, highest first, then by ticker", async () => {
      const m = await makeEnv();
      await send(m, ["MMM", "AAA", "ZZZ", "BBB"]);
      await send(m, ["MMM", "ZZZ"], "picker", { "cf-connecting-ip": OTHER_IP });
      await send(m, ["ZZZ"], "csv", { "cf-connecting-ip": "192.0.2.77" });
      expect((await listed(m)).map((r) => [r.ticker, r.count])).toEqual([["ZZZ", 3], ["MMM", 2], ["AAA", 1], ["BBB", 1]]);
    });
  });

  describe("when the store is down", () => {
    it("answers 503 to a request and does not throw", async () => {
      const m = await makeEnv({ recorderDown: true });
      const res = await send(m, ["ZQXJ"]);
      expect(res.status).toBe(503);
      expect(await res.text()).not.toContain("ZQXJ");
      expect((await read(m)).status).toBe(503);
    });
  });
});
