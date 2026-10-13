import { timingSafeEqual as nodeTimingSafeEqual } from "node:crypto";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { decode, encode } from "../src/state/url";

const SITE = "https://portfoliosight.ai";
const GATE = "unit-test-gate-value";
const MAIL_URL = "https://api.mailchannels.net/tx/v1/send";
const SUBJECT = "Someone shared a PortfolioSight view with you";
const LINE_1 = "Someone shared a PortfolioSight view with you:";
const LINE_3 = "PortfolioSight is an educational tool. Historical math, not investment advice.";
const CAPS = { ipMinute: 1, ipDay: 3, globalDay: 50 };
const T0 = Date.parse("2026-10-13T12:00:01Z");
const MINUTE = 60_000;

type Counts = Record<string, unknown>;
type Limiter = (ip: string, exempt: boolean) => Promise<boolean>;
type Mail = {
  personalizations: Array<Record<string, unknown>>;
  from: unknown;
  reply_to: unknown;
  subject: string;
  content: Array<{ type: string; value: string }>;
};
type ShareModule = {
  handleShare(request: Request, env: unknown, limiter: Limiter): Promise<Response>;
  shareLimit(counts: Counts, ip: string, nowMs: number, caps: typeof CAPS, exempt?: boolean): { allowed: boolean; counts: Counts };
  reencodeShareUrl(submitted: unknown): string | null;
  isBareAddress(value: unknown): boolean;
  ShareLimiter: new (state: unknown, env: unknown) => { fetch(request: Request): Promise<Response> };
};

let S: ShareModule;
let sent: Array<{ url: string; headers: Headers; text: string; json: Mail }> = [];
let mailResponse: () => Response = () => new Response("{}", { status: 202 });
let logs: string[] = [];
let compares: Array<[number, number]> = [];

function installTimingSafeEqual() {
  const bytes = (v: ArrayBuffer | ArrayBufferView) =>
    v instanceof ArrayBuffer ? Buffer.from(v) : Buffer.from(v.buffer, v.byteOffset, v.byteLength);
  Object.defineProperty(crypto.subtle, "timingSafeEqual", {
    configurable: true,
    writable: true,
    value: (a: ArrayBuffer | ArrayBufferView, b: ArrayBuffer | ArrayBufferView) => {
      const x = bytes(a);
      const y = bytes(b);
      compares.push([x.byteLength, y.byteLength]);
      if (x.byteLength !== y.byteLength) throw new TypeError("Input buffers must have the same byte length");
      return nodeTimingSafeEqual(x, y);
    },
  });
}

const baseEnv = (overrides: Record<string, unknown> = {}) => ({
  SHARE_FROM: "sender@example.org",
  SHARE_REPLY_TO: "replies@example.org",
  MAILCHANNELS_API_KEY: "unit-test-mail-key",
  MAILCHANNELS_DKIM_PRIVATE_KEY: "unit-test-dkim-key",
  SHARE_CAP_IP_MINUTE: "1",
  SHARE_CAP_IP_DAY: "3",
  SHARE_CAP_GLOBAL_DAY: "50",
  PS_GATE_SECRET: GATE,
  ...overrides,
});

type PostOptions = { headers?: Record<string, string | null>; raw?: string | Uint8Array };
function post(body: unknown, options: PostOptions = {}) {
  const headers = new Headers({ origin: SITE, "content-type": "application/json", "cf-connecting-ip": "203.0.113.7" });
  for (const [name, value] of Object.entries(options.headers ?? {})) {
    if (value === null) headers.delete(name);
    else headers.set(name, value);
  }
  return new Request(`${SITE}/api/share`, { method: "POST", headers, body: options.raw ?? JSON.stringify(body) });
}
const allow: Limiter = async () => true;
const good = { to: "reader@example.org", url: `${SITE}/?u=guide2017&lb=5y&r=19.25&d=auto&t=hud` };
const errorCode = async (res: Response) => ((await res.json()) as { error: { code: string } }).error.code;
const part = (mail: Mail, type: string) => mail.content.find((c) => c.type === type)?.value ?? "";

// Stands in for the Durable Object's SQL storage: one table keyed by day.
function fakeState() {
  const rows = new Map<string, string>();
  const statements: string[] = [];
  const sql = {
    exec(query: string, ...bindings: unknown[]) {
      const q = query.replace(/\s+/g, " ").trim();
      statements.push(q);
      let out: Array<Record<string, unknown>> = [];
      if (/^CREATE TABLE IF NOT EXISTS share_counts/i.test(q)) out = [];
      else if (/^SELECT day, counts FROM share_counts ORDER BY day DESC LIMIT 1$/i.test(q)) {
        const latest = Array.from(rows.keys()).sort().pop();
        out = latest === undefined ? [] : [{ day: latest, counts: rows.get(latest) }];
      } else if (/^INSERT OR REPLACE INTO share_counts \(day, counts\) VALUES \(\?, \?\)$/i.test(q)) {
        rows.set(String(bindings[0]), String(bindings[1]));
      } else if (/^DELETE FROM share_counts WHERE day < \?$/i.test(q)) {
        for (const day of Array.from(rows.keys())) if (day < String(bindings[0])) rows.delete(day);
      } else throw new Error(`unexpected SQL: ${q}`);
      return { toArray: () => out };
    },
  };
  return { state: { storage: { sql } }, rows, statements };
}
async function ask(limiter: { fetch(request: Request): Promise<Response> }, ip: string, exempt = false) {
  const res = await limiter.fetch(new Request("https://share-limiter/check", { method: "POST", body: JSON.stringify({ ip, exempt }) }));
  expect(res.status).toBe(200);
  return ((await res.json()) as { allowed: boolean }).allowed;
}

describe("share by email", () => {
  beforeAll(async () => {
    installTimingSafeEqual();
    S = (await import("../worker/share")) as unknown as ShareModule;
  });
  beforeEach(() => {
    sent = [];
    logs = [];
    compares = [];
    mailResponse = () => new Response("{}", { status: 202 });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | Request, init?: RequestInit) => {
        const request = new Request(input, init);
        const text = await request.text();
        sent.push({ url: request.url, headers: request.headers, text, json: JSON.parse(text) as Mail });
        return mailResponse();
      }),
    );
    for (const level of ["log", "info", "warn", "error", "debug"] as const) {
      vi.spyOn(console, level).mockImplementation((...args: unknown[]) => void logs.push(args.map(String).join(" ")));
    }
  });
  afterEach(() => {
    const all = logs.join("\n");
    for (const hidden of [GATE, "unit-test-mail-key", "unit-test-dkim-key", "reader@example.org"]) expect(all).not.toContain(hidden);
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("sends the fixed template with the re-encoded link and the signing fields", async () => {
    const res = await S.handleShare(post({ ...good, url: `${SITE}/?t=hud&d=auto&r=19.25&lb=5y&u=guide2017` }), baseEnv(), allow);
    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({ ok: true });
    expect(res.headers.get("cache-control")).toBe("no-store");
    expect(sent.length).toBe(1);
    const mail = sent[0];
    expect(mail.url).toBe(MAIL_URL);
    expect(mail.headers.get("x-api-key")).toBe("unit-test-mail-key");
    expect(mail.headers.get("content-type")).toContain("application/json");
    expect(mail.json.personalizations).toEqual([
      { to: [{ email: "reader@example.org" }], dkim_domain: "automateintelligence.ai", dkim_selector: "mailchannels", dkim_private_key: "unit-test-dkim-key" },
    ]);
    expect(mail.json.from).toEqual({ email: "sender@example.org", name: "PortfolioSight" });
    expect(mail.json.reply_to).toEqual({ email: "replies@example.org" });
    expect(mail.json.subject).toBe(SUBJECT);
    expect(mail.json.content.map((c) => c.type)).toEqual(["text/plain", "text/html"]);
    const link = `${SITE}/?u=guide2017&lb=5y&r=19.25&d=auto&t=hud`;
    expect(part(mail.json, "text/plain").split("\n").filter((l) => l !== "")).toEqual([LINE_1, link, LINE_3]);
    const html = part(mail.json, "text/html");
    const escaped = link.replaceAll("&", "&amp;");
    expect(html).toContain(`<a href="${escaped}">${escaped}</a>`);
    expect(html).toContain(LINE_1);
    expect(html).toContain(LINE_3);
    // the HTML part loads nothing: the only URL in it is the link
    expect(html.replaceAll(escaped, "")).not.toMatch(/https?:|src=|<img|<script|<link|<style/i);
    expect(mail.text).not.toContain(GATE);
    expect(Object.keys(mail.json).sort()).toEqual(["content", "from", "personalizations", "reply_to", "subject"]);
  });

  it("re-encodes a valid URL in the contract's key order with the defaults written", () => {
    const cases: Array<[string, string]> = [
      ["?u=guide2017&lb=5y&r=19.25&d=auto&t=hud", "?u=guide2017&lb=5y&r=19.25&d=auto&t=hud"],
      ["?x=1&t=light&d=0.25&r=12.5&lb=3y&u=tsp", "?u=tsp&lb=3y&r=12.5&d=0.25&t=light&x=1"],
      ["", "?lb=5y&d=auto"],
      ["?u=tsp", "?u=tsp&lb=5y&d=auto"],
      ["?unit=pct&u=tsp", "?u=tsp&lb=5y&d=auto"],
      ["?g=1y,10y&x=1&d=0.5&lb=ew&c=VTI::10,BND:5:&unit=shares&f=VTI:60,BND:40,VNQ", "?f=VTI:60,BND:40,VNQ&unit=shares&c=VTI::10,BND:5:&lb=ew&g=1y,10y&d=0.5&x=1"],
      ["?f=VTI%3A60%2CBND%3A40.5&unit=usd", "?f=VTI:60,BND:40.5&unit=usd&lb=5y&d=auto"],
      ["?f=BRK.B:10,BF-B&t=ks-dark&d=1", "?f=BRK.B:10,BF-B&lb=5y&d=1&t=ks-dark"],
    ];
    for (const [submitted, canonical] of cases) {
      expect(S.reencodeShareUrl(`${SITE}/${submitted}`), submitted).toBe(`${SITE}/${canonical}`);
      // re-encoding its own output changes nothing
      expect(S.reencodeShareUrl(`${SITE}/${canonical}`), canonical).toBe(`${SITE}/${canonical}`);
    }
    expect(S.reencodeShareUrl("https://portfoliosight.ai")).toBe(`${SITE}/?lb=5y&d=auto`);
  });

  it("refuses a URL that is not this site's page with only the contract's keys and value shapes", () => {
    const bad = [
      "http://portfoliosight.ai/?u=tsp",
      "https://www.portfoliosight.ai/?u=tsp",
      "https://portfoliosight.ai.example.com/?u=tsp",
      "https://portfoliosight.ai:8443/?u=tsp",
      "https://user@portfoliosight.ai/?u=tsp",
      "https://user:pw@portfoliosight.ai/?u=tsp",
      "https://portfoliosight.ai/admin?u=tsp",
      "https://portfoliosight.ai//example.com?u=tsp",
      "https://portfoliosight.ai/?u=tsp#fragment",
      "//portfoliosight.ai/?u=tsp",
      "/?u=tsp",
      "javascript:alert(1)",
      "",
      `${SITE}/?k=${GATE}`,
      `${SITE}/?u=tsp&zz=1`,
      `${SITE}/?u=tsp&u=guide2017`,
      `${SITE}/?U=tsp`,
      `${SITE}/?u=free-text-goes-here`,
      `${SITE}/?u=tsp&t=<b>`,
      `${SITE}/?t=buy%20now`,
      `${SITE}/?lb=7y`,
      `${SITE}/?unit=euro`,
      `${SITE}/?x=0`,
      `${SITE}/?x=true`,
      `${SITE}/?r=abc`,
      `${SITE}/?r=1e9`,
      `${SITE}/?d=1.5`,
      `${SITE}/?d=-0.1`,
      `${SITE}/?g=1y,7y`,
      `${SITE}/?f=vti:60`,
      `${SITE}/?f=VTI:60:1`,
      `${SITE}/?f=VTI:abc`,
      `${SITE}/?f=VISIT+EXAMPLE+DOT+COM`,
      `${SITE}/?f=${Array.from({ length: 31 }, (_, i) => `F${i}`).join(",")}`,
      `${SITE}/?c=VTI:10`,
      `${SITE}/?c=VTI:a:b`,
      `${SITE}/?c=VTI:1000:1`,
      `${SITE}/?f=`,
    ];
    for (const url of bad) expect(S.reencodeShareUrl(url), url).toBeNull();
    for (const notString of [null, undefined, 7, {}, [], true]) expect(S.reencodeShareUrl(notString)).toBeNull();
    // thirty funds is the limit and is accepted
    const thirty = Array.from({ length: 30 }, (_, i) => `F${i}`).join(",");
    expect(S.reencodeShareUrl(`${SITE}/?f=${thirty}`)).toBe(`${SITE}/?f=${thirty}&lb=5y&d=auto`);
  });

  it("measures the re-encoded link, which stays under 2,048 characters for every accepted view", () => {
    const id = (i: number) => `ABCDEFGHIJ${String(i).padStart(2, "0")}`;
    const funds = Array.from({ length: 30 }, (_, i) => `${id(i)}:123456789012.123456`);
    const caps = Array.from({ length: 30 }, (_, i) => `${id(i)}:100:100`);
    const tail = `&lb=10y&g=1y,2y,3y,5y,10y,ew&r=-1234.${"1".repeat(12)}&d=0.${"1".repeat(12)}&t=ks-dark&x=1`;
    // the longest view the value shapes admit: thirty funds with amounts and caps
    const longest = `${SITE}/?f=${funds.join(",")}&unit=shares&c=${caps.join(",")}${tail}`;
    // the mailed link is the page codec's canonical form (numbers at six decimals), never the input
    const canonical = `${SITE}/${encode(decode(new URL(longest).search))}`;
    expect(S.reencodeShareUrl(longest)).toBe(canonical);
    expect(canonical).toContain("&r=-1234.111111&d=0.111111&");
    expect(canonical.length).toBeLessThanOrEqual(2048);
    // a submitted string over the limit whose re-encoded form is under it is judged on the re-encoded form
    const escape = (list: string[]) => list.join(",").replaceAll("A", "%41").replaceAll(":", "%3A").replaceAll(",", "%2C");
    const escaped = `${SITE}/?f=${escape(funds)}&unit=shares&c=${escape(caps)}${tail}`;
    expect(escaped.length).toBeGreaterThan(2048);
    expect(S.reencodeShareUrl(escaped)).toBe(canonical);
    // one more fund, cap, digit or id character is refused by shape, so no accepted link can pass the limit
    expect(S.reencodeShareUrl(longest.replace("ABCDEFGHIJ00:", "ABCDEFGHIJK00:"))).toBeNull();
    expect(S.reencodeShareUrl(longest.replace(".123456,", ".1234567,"))).toBeNull();
    expect(S.reencodeShareUrl(longest.replace("&unit", ",ZZ:1&unit"))).toBeNull();
  });

  it("accepts one bare address and nothing else", () => {
    const ok = ["reader@example.org", "reader.one+ps@example.org", "a@b.co", "o'neil_x-1@sub.example-host.org", `${"x".repeat(64)}@example.org`];
    for (const address of ok) expect(S.isBareAddress(address), address).toBe(true);
    const long = `${"x".repeat(64)}@${"d".repeat(63)}.${"d".repeat(63)}.${"d".repeat(58)}.org`;
    expect(long.length).toBe(255);
    const bad = [
      "",
      " reader@example.org",
      "reader@example.org ",
      "Reader <reader@example.org>",
      "a@example.org,b@example.org",
      "a@example.org;b@example.org",
      "a@example.org b@example.org",
      "a@example.org\r\nBcc: b@example.org",
      "a@example.org\n",
      "reader",
      "@example.org",
      "reader@",
      "reader@localhost",
      "reader@@example.org",
      "reader@example..org",
      "reader@-example.org",
      "reader@example.org.",
      ".reader@example.org",
      "reader.@example.org",
      "rea..der@example.org",
      '"quoted local"@example.org',
      "reader@[203.0.113.1]",
      "reader(comment)@example.org",
      "réader@example.org",
      `${"x".repeat(65)}@example.org`,
      long,
    ];
    for (const address of bad) expect(S.isBareAddress(address), JSON.stringify(address)).toBe(false);
    for (const notString of [null, undefined, 7, {}, ["reader@example.org"]]) expect(S.isBareAddress(notString)).toBe(false);
  });

  it("refuses bad requests before the limiter or the mail service is consulted", async () => {
    const limiter = vi.fn(allow);
    const cases: Array<[string, Request, number, string]> = [
      ["foreign origin", post(good, { headers: { origin: "https://evil.example.com" } }), 403, "forbidden_origin"],
      ["origin with a trailing slash", post(good, { headers: { origin: `${SITE}/` } }), 403, "forbidden_origin"],
      ["http origin", post(good, { headers: { origin: "http://portfoliosight.ai" } }), 403, "forbidden_origin"],
      ["null origin", post(good, { headers: { origin: "null" } }), 403, "forbidden_origin"],
      ["no origin", post(good, { headers: { origin: null } }), 403, "forbidden_origin"],
      ["form encoding", post(good, { headers: { "content-type": "application/x-www-form-urlencoded" } }), 415, "unsupported_media_type"],
      ["no content type", post(good, { headers: { "content-type": null }, raw: new TextEncoder().encode(JSON.stringify(good)) }), 415, "unsupported_media_type"],
      ["json lookalike type", post(good, { headers: { "content-type": "application/jsonp" } }), 415, "unsupported_media_type"],
      ["2049 bytes", post(null, { raw: JSON.stringify({ ...good, pad: "" }).replace('""', `"${"p".repeat(2049)}"`).slice(0, 2049) }), 413, "payload_too_large"],
      ["declared length over the limit", post(good, { headers: { "content-length": "5000" } }), 413, "payload_too_large"],
      ["multi-byte body over the limit", post(null, { raw: JSON.stringify({ ...good, pad: "é".repeat(1000) }) }), 413, "payload_too_large"],
      ["malformed JSON", post(null, { raw: "{to: reader" }), 400, "invalid_request"],
      ["invalid UTF-8", post(null, { raw: new Uint8Array([0x7b, 0xff, 0xfe, 0x7d]) }), 400, "invalid_request"],
      ["JSON array", post([good]), 400, "invalid_request"],
      ["JSON null", post(null), 400, "invalid_request"],
      ["recipient list", post({ ...good, to: ["reader@example.org"] }), 400, "invalid_recipient"],
      ["missing recipient", post({ url: good.url }), 400, "invalid_recipient"],
      ["missing url", post({ to: good.to }), 400, "invalid_url"],
      ["url with the gate key", post({ ...good, url: `${SITE}/?u=tsp&k=${GATE}` }), 400, "invalid_url"],
    ];
    for (const [name, request, status, code] of cases) {
      const res = await S.handleShare(request, baseEnv(), limiter);
      expect(res.status, name).toBe(status);
      expect(await errorCode(res), name).toBe(code);
      expect(res.headers.get("cache-control"), name).toBe("no-store");
    }
    expect(limiter).not.toHaveBeenCalled();
    expect(sent).toEqual([]);
    // a JSON content type with a charset parameter, at exactly the size limit, is accepted
    const body = JSON.stringify({ ...good, pad: "" });
    const exact = body.replace('""', `"${"p".repeat(2048 - body.length)}"`);
    expect(new TextEncoder().encode(exact).byteLength).toBe(2048);
    const res = await S.handleShare(post(null, { raw: exact, headers: { "content-type": "Application/JSON; charset=utf-8" } }), baseEnv(), limiter);
    expect(res.status).toBe(202);
    expect(sent[0].text).not.toContain("ppp");
  });

  it("a send the mail service refuses is a 502 that has already been counted", async () => {
    const limiter = vi.fn(allow);
    for (const fail of [() => new Response("denied", { status: 401 }), () => new Response("oops", { status: 500 })]) {
      mailResponse = fail;
      const res = await S.handleShare(post(good), baseEnv(), limiter);
      expect(res.status).toBe(502);
      expect(await errorCode(res)).toBe("mail_failed");
    }
    mailResponse = () => {
      throw new Error("socket closed: unit-test-mail-key");
    };
    expect((await S.handleShare(post(good), baseEnv(), limiter)).status).toBe(502);
    // each attempt consumed allowance before the send
    expect(limiter).toHaveBeenCalledTimes(3);
    expect(sent.length).toBe(3);
    // unset mail configuration fails the same way without calling out
    sent = [];
    for (const missing of ["MAILCHANNELS_API_KEY", "MAILCHANNELS_DKIM_PRIVATE_KEY", "SHARE_FROM", "SHARE_REPLY_TO"]) {
      const res = await S.handleShare(post(good), baseEnv({ [missing]: undefined }), allow);
      expect(res.status, missing).toBe(502);
    }
    expect(sent).toEqual([]);
  });

  it("the test key skips the send, after the limiter, with one log line that names nobody", async () => {
    const limiter = vi.fn(allow);
    const res = await S.handleShare(post(good), baseEnv({ MAILCHANNELS_API_KEY: "test" }), limiter);
    expect(res.status).toBe(202);
    expect(sent).toEqual([]);
    expect(limiter).toHaveBeenCalledTimes(1);
    expect(logs.length).toBe(1);
    expect(logs[0]).not.toContain("@");
    expect(logs[0]).not.toContain("portfoliosight.ai/?");
  });

  it("the gate header exempts only when it equals the secret, compared in constant time", async () => {
    const seen: Array<[string, boolean]> = [];
    const limiter: Limiter = async (ip, exempt) => {
      seen.push([ip, exempt]);
      return true;
    };
    const header = (value: string | null) => post(good, { headers: { "x-ps-gate": value, "cf-connecting-ip": "198.51.100.4" } });
    await S.handleShare(header(GATE), baseEnv(), limiter);
    for (const wrong of [null, "", "wrong", `${GATE}x`, GATE.slice(0, -1), GATE.toUpperCase()]) await S.handleShare(header(wrong), baseEnv(), limiter);
    expect(seen.map(([, exempt]) => exempt)).toEqual([true, false, false, false, false, false, false]);
    expect(seen.every(([ip]) => ip === "198.51.100.4")).toBe(true);
    // one comparison per header that was present, always over equal-length digests
    expect(compares.length).toBe(6);
    for (const [a, b] of compares) expect([a, b]).toEqual([32, 32]);
    // an unset secret exempts nobody, an empty header included
    seen.length = 0;
    await S.handleShare(header(""), baseEnv({ PS_GATE_SECRET: "" }), limiter);
    await S.handleShare(header("undefined"), baseEnv({ PS_GATE_SECRET: undefined }), limiter);
    expect(seen.map(([, exempt]) => exempt)).toEqual([false, false]);
  });

  it("requests without a usable visitor address share one bucket", async () => {
    const ips: string[] = [];
    const limiter: Limiter = async (ip) => {
      ips.push(ip);
      return true;
    };
    for (const ip of [null, "", "not an address", "__proto__", "2001:db8::1", "203.0.113.200"]) {
      await S.handleShare(post(good, { headers: { "cf-connecting-ip": ip } }), baseEnv(), limiter);
    }
    expect(ips).toEqual(["unknown", "unknown", "unknown", "unknown", "2001:db8::1", "203.0.113.200"]);
  });

  it("shareLimit counts only allowed sends and never changes the record it was given", () => {
    const first = S.shareLimit({}, "203.0.113.1", T0, CAPS);
    expect(first.allowed).toBe(true);
    const snapshot = JSON.stringify(first.counts);
    const refused = S.shareLimit(first.counts, "203.0.113.1", T0 + 30_000, CAPS);
    expect(refused.allowed).toBe(false);
    expect(JSON.stringify(first.counts)).toBe(snapshot);
    // the refusal did not extend the wait: a minute after the allowed send the next one passes
    const again = S.shareLimit(refused.counts, "203.0.113.1", T0 + MINUTE, CAPS);
    expect(again.allowed).toBe(true);
    // hammering while refused never uses up the day's allowance
    let counts = again.counts;
    for (let i = 1; i <= 40; i++) counts = S.shareLimit(counts, "203.0.113.1", T0 + MINUTE + i * 1000, CAPS).counts;
    const third = S.shareLimit(counts, "203.0.113.1", T0 + 2 * MINUTE, CAPS);
    expect(third.allowed).toBe(true);
    expect(S.shareLimit(third.counts, "203.0.113.1", T0 + 3 * MINUTE, CAPS).allowed).toBe(false);
    // the record survives a JSON round trip (it is stored as text)
    const stored = JSON.parse(JSON.stringify(third.counts)) as Counts;
    expect(S.shareLimit(stored, "203.0.113.1", T0 + 3 * MINUTE, CAPS).allowed).toBe(false);
    expect(S.shareLimit(stored, "203.0.113.2", T0 + 3 * MINUTE, CAPS).allowed).toBe(true);
  });

  it("shareLimit keeps the minute window across midnight and resets the day counts", () => {
    const lateNight = Date.parse("2026-10-13T23:59:50Z");
    let counts: Counts = {};
    for (const at of [lateNight - 4 * MINUTE, lateNight - 2 * MINUTE, lateNight]) {
      const out = S.shareLimit(counts, "203.0.113.1", at, CAPS);
      expect(out.allowed).toBe(true);
      counts = out.counts;
    }
    // ten seconds later it is a new UTC day, but still the same minute
    expect(S.shareLimit(counts, "203.0.113.1", lateNight + 15_000, CAPS).allowed).toBe(false);
    // once the minute has passed, the new day's allowance is whole again
    const fresh = S.shareLimit(counts, "203.0.113.1", lateNight + MINUTE, CAPS);
    expect(fresh.allowed).toBe(true);
    // without the reset this fourth send of the old day would have been refused
    expect(S.shareLimit(counts, "203.0.113.1", lateNight - 1000 + MINUTE, { ...CAPS, ipMinute: 5 }).allowed).toBe(true);
    expect(S.shareLimit(counts, "203.0.113.1", lateNight + 5000 - 15_000, { ...CAPS, ipMinute: 5 }).allowed).toBe(false);
  });

  it("shareLimit honours other cap values and the exemption", () => {
    const caps = { ipMinute: 2, ipDay: 4, globalDay: 5 };
    let counts: Counts = {};
    const verdicts: boolean[] = [];
    for (const at of [0, 1000, 2000, MINUTE + 1000, MINUTE + 2000, 5 * MINUTE]) {
      const out = S.shareLimit(counts, "203.0.113.1", T0 + at, caps);
      verdicts.push(out.allowed);
      counts = out.counts;
    }
    expect(verdicts).toEqual([true, true, false, true, true, false]);
    // four sent; an exempt send takes the fifth global slot, then the global cap binds for everyone
    const exempt = S.shareLimit(counts, "203.0.113.1", T0 + 5 * MINUTE, caps, true);
    expect(exempt.allowed).toBe(true);
    expect(S.shareLimit(exempt.counts, "203.0.113.9", T0 + 6 * MINUTE, caps).allowed).toBe(false);
    expect(S.shareLimit(exempt.counts, "203.0.113.9", T0 + 6 * MINUTE, caps, true).allowed).toBe(false);
    // exempt sends are not held against the address's own allowance
    let mixed: Counts = {};
    for (let i = 0; i < 3; i++) mixed = S.shareLimit(mixed, "203.0.113.5", T0 + i, CAPS, true).counts;
    expect(S.shareLimit(mixed, "203.0.113.5", T0 + 10, CAPS).allowed).toBe(true);
    // a zero cap refuses everything
    expect(S.shareLimit({}, "203.0.113.1", T0, { ...CAPS, globalDay: 0 }, true).allowed).toBe(false);
  });

  it("the Durable Object enforces the caps and keeps its counts in storage", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(T0));
    const storage = fakeState();
    const limiter = new S.ShareLimiter(storage.state, baseEnv());
    expect(await ask(limiter, "203.0.113.1")).toBe(true);
    expect(await ask(limiter, "203.0.113.1")).toBe(false);
    expect(await ask(limiter, "203.0.113.2")).toBe(true);
    expect(Array.from(storage.rows.keys())).toEqual(["2026-10-13"]);

    // a new instance over the same storage (an eviction) remembers
    const revived = new S.ShareLimiter(storage.state, baseEnv());
    expect(await ask(revived, "203.0.113.1")).toBe(false);
    vi.setSystemTime(new Date(T0 + MINUTE));
    expect(await ask(revived, "203.0.113.1")).toBe(true);
    vi.setSystemTime(new Date(T0 + 2 * MINUTE));
    expect(await ask(revived, "203.0.113.1")).toBe(true);
    vi.setSystemTime(new Date(T0 + 3 * MINUTE));
    expect(await ask(revived, "203.0.113.1")).toBe(false);
    expect(await ask(revived, "203.0.113.1", true)).toBe(true);

    // the next UTC day starts over and the old day's row is gone
    vi.setSystemTime(new Date(T0 + 24 * 60 * MINUTE));
    expect(await ask(revived, "203.0.113.1")).toBe(true);
    expect(Array.from(storage.rows.keys())).toEqual(["2026-10-14"]);
  });

  it("the Durable Object takes its caps from its own configuration and applies the global cap", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(T0));
    const storage = fakeState();
    const limiter = new S.ShareLimiter(storage.state, baseEnv({ SHARE_CAP_GLOBAL_DAY: "2", SHARE_CAP_IP_MINUTE: "5", SHARE_CAP_IP_DAY: "5" }));
    expect(await ask(limiter, "203.0.113.1")).toBe(true);
    expect(await ask(limiter, "203.0.113.2", true)).toBe(true);
    expect(await ask(limiter, "203.0.113.3")).toBe(false);
    expect(await ask(limiter, "203.0.113.3", true)).toBe(false);
    // unusable cap values fall back to the specified caps (1 per minute here)
    const defaults = new S.ShareLimiter(fakeState().state, baseEnv({ SHARE_CAP_IP_MINUTE: "lots", SHARE_CAP_IP_DAY: undefined, SHARE_CAP_GLOBAL_DAY: "-4" }));
    expect(await ask(defaults, "203.0.113.1")).toBe(true);
    expect(await ask(defaults, "203.0.113.1")).toBe(false);
  });

  it("the Durable Object refuses anything but a well-formed check", async () => {
    const limiter = new S.ShareLimiter(fakeState().state, baseEnv());
    const bad = [
      new Request("https://share-limiter/check"),
      new Request("https://share-limiter/check", { method: "POST", body: "not json" }),
      new Request("https://share-limiter/check", { method: "POST", body: JSON.stringify({ ip: 7, exempt: false }) }),
      new Request("https://share-limiter/check", { method: "POST", body: JSON.stringify({ ip: "203.0.113.1", exempt: "yes" }) }),
      new Request("https://share-limiter/check", { method: "POST", body: JSON.stringify({ ip: "203.0.113.1" }) }),
    ];
    for (const request of bad) {
      const res = await limiter.fetch(request);
      expect(res.status).toBeGreaterThanOrEqual(400);
      expect(res.ok).toBe(false);
    }
  });

  it("a stored record that cannot be read is treated as today's allowance already spent", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(T0));
    const storage = fakeState();
    storage.rows.set("2026-10-13", "{not json");
    const limiter = new S.ShareLimiter(storage.state, baseEnv());
    expect(await ask(limiter, "203.0.113.1")).toBe(false);
    // the next day it recovers by itself
    vi.setSystemTime(new Date(T0 + 24 * 60 * MINUTE));
    expect(await ask(limiter, "203.0.113.1")).toBe(true);
  });
});
