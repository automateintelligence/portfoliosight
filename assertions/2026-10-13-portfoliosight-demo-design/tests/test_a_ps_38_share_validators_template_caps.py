# ruff: noqa: E501
"""A-PS-38 — share validators, the fixed template and the caps.

Vitest leg run from pytest (stdlib only). The embedded spec runs in vitest's plain node
environment (Node 20 globals `fetch`, `Request`, `Response`; no jsdom, no Cloudflare test pool).
`web/worker/share.ts` (and whatever it imports, `web/src/state/url.ts` included) must import
cleanly there: no `cloudflare:workers` import at module top level.

Pinned interface
- `web/worker/share.ts`:
  - `handleShare(request: Request, env, limiter: (ip: string, exempt: boolean) =>
    Promise<boolean>) -> Promise<Response>`; `limiter` resolves `true` when the send is allowed (the
    Worker passes one backed by the `ShareLimiter` Durable Object) and is called with the
    `CF-Connecting-IP` value and `exempt`, which is `true` exactly when the request carries an
    `x-ps-gate` header equal to `env.PS_GATE_SECRET` (compared with
    `crypto.subtle.timingSafeEqual`, for which the test installs a stand-in). `env` carries
    `SHARE_FROM`, `SHARE_REPLY_TO`, `MAILCHANNELS_API_KEY`, `MAILCHANNELS_DKIM_PRIVATE_KEY`,
    `PS_GATE_SECRET`. Answers: `202 {"ok": true}`; errors use the envelope
    `{"error": {"code", ...}}` with `400 invalid_recipient | invalid_url`, `413`, `415`,
    `403` (or `400`) for a missing or foreign `Origin`, `429 rate_limited`. The body size is
    measured on the body itself (no `Content-Length` is sent here).
  - `shareLimit(counts, ip: string, nowMs: number, caps: {ipMinute: number, ipDay: number,
    globalDay: number}, exempt?: boolean) -> {allowed: boolean, counts}`: the pure counting
    logic; `counts` starts as `{}` and is otherwise opaque (the caller threads the returned
    record); days are UTC days.
- Coordinator decision (2026-10-13, beyond the spec text): a request with the valid `x-ps-gate`
  header is exempt from the two per-IP caps (1 per minute, 3 per day); the global daily cap (50)
  still applies to it and it still counts toward that cap. A wrong header value gets no exemption.
- MailChannels request: `POST https://api.mailchannels.net/tx/v1/send` through the global `fetch`,
  header `X-API-Key`, JSON `{personalizations: [{to: [{email}], dkim_domain, dkim_selector,
  dkim_private_key}], from: {email, name}, reply_to: {email}, subject, content: [{type:
  "text/plain", value}, {type: "text/html", value}]}`. The link is
  `"https://portfoliosight.ai/" + encode(decode(search))` with the codec of `web/src/state/url.ts`.
- Themes (spec 8.1, four themes since 2026-10-13): a link with `t` equal to any of `ks-dark`,
  `light`, `hud`, `grid` is sent with that theme in the link; any other `t` value is refused with
  `400 invalid_url` and nothing is sent.
- `web/src/controls/ShareDialog.tsx`: `ShareDialog` with props `{open: boolean, url: string,
  privatePreview: boolean, onClose: () => void}`, renderable with `react-dom/server` when `open`
  (no portal); the notice mentions "private preview" when `privatePreview` is true.

Accepted in two ways (the spec leaves it open): a `url` with a non-§8.1 key (`zz`, `k`) is either
refused with `400 invalid_url` or sent with the key dropped; an unexpected JSON field is either
refused or ignored. In both cases nothing of it may reach the message.
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
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const SITE = "https://portfoliosight.ai";
const MAIL_URL = "https://api.mailchannels.net/tx/v1/send";
const SUBJECT = "Someone shared a PortfolioSight view with you";
const LINE_1 = "Someone shared a PortfolioSight view with you:";
const LINE_3 = "PortfolioSight is an educational tool. Historical math, not investment advice.";
const CANONICAL = "?u=guide2017&lb=5y&r=19.25&d=auto&t=hud";
const SHUFFLED = `${SITE}/?t=hud&d=auto&r=19.25&lb=5y&u=guide2017`;
const CAPS = { ipMinute: 1, ipDay: 3, globalDay: 50 };
const T0 = Date.parse("2026-10-13T12:00:01Z");

const baseEnv = () => ({
  SHARE_FROM: "sender-under-test@automateintelligence.ai",
  SHARE_REPLY_TO: "replies-under-test@automateintelligence.ai",
  MAILCHANNELS_API_KEY: "mc-key-under-test",
  MAILCHANNELS_DKIM_PRIVATE_KEY: "DKIM-PRIVATE-KEY-UNDER-TEST",
  SHARE_CAP_IP_MINUTE: "1",
  SHARE_CAP_IP_DAY: "3",
  SHARE_CAP_GLOBAL_DAY: "50",
  PS_GATE_SECRET: "ZZ-SENTINEL-ZZ",
  PS_PRIVATE_PREVIEW: "0",
  API_ORIGIN: "https://api.portfoliosight.ai",
});

type Sent = { url: string; method: string; headers: Headers; text: string; json: any };
let sent: Sent[] = [];
let outbound = 0;
let S: any;
let codec: any;
let logs: any[][] = [];

function stubFetch(status = 202) {
  sent = [];
  outbound = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: any, init?: any) => {
      outbound += 1;
      const req = new Request(input, init);
      const text = await req.text();
      let parsed: any = null;
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = null;
      }
      sent.push({ url: req.url, method: req.method, headers: req.headers, text, json: parsed });
      return new Response(JSON.stringify({ ok: true }), { status, headers: { "content-type": "application/json" } });
    }),
  );
}

// crypto.subtle.timingSafeEqual is the Workers primitive (absent in Node); same behaviour as there
function installTimingSafeEqual() {
  const bytes = (v: any) => (v instanceof ArrayBuffer ? Buffer.from(v) : Buffer.from(v.buffer, v.byteOffset, v.byteLength));
  Object.defineProperty(globalThis.crypto.subtle, "timingSafeEqual", {
    configurable: true,
    writable: true,
    value: (a: any, b: any) => {
      const x = bytes(a);
      const y = bytes(b);
      if (x.byteLength !== y.byteLength) throw new TypeError("Input buffers must have the same byte length");
      return nodeTimingSafeEqual(x, y);
    },
  });
}

function post(body: unknown, opts: { origin?: string | null; contentType?: string | null; ip?: string; raw?: string; gate?: string } = {}) {
  const headers: Record<string, string> = {};
  const origin = opts.origin === undefined ? SITE : opts.origin;
  if (origin !== null) headers.origin = origin;
  const contentType = opts.contentType === undefined ? "application/json" : opts.contentType;
  if (contentType !== null) headers["content-type"] = contentType;
  headers["cf-connecting-ip"] = opts.ip ?? "203.0.113.7";
  if (opts.gate !== undefined) headers["x-ps-gate"] = opts.gate;
  return new Request(`${SITE}/api/share`, { method: "POST", headers, body: opts.raw ?? JSON.stringify(body) });
}
const allow = async (_ip: string, _exempt?: boolean) => true;
async function codeOf(res: Response): Promise<string | undefined> {
  const data: any = await res.json().catch(() => null);
  return data?.error?.code;
}
const textPart = (m: any): string => m.content.find((c: any) => c.type === "text/plain")?.value ?? "";
const htmlPart = (m: any): string => m.content.find((c: any) => c.type === "text/html")?.value ?? "";
const lines = (text: string) => text.split(/\r?\n/).map((l) => l.trim()).filter((l) => l.length > 0);

describe("A-PS-38", () => {
  beforeAll(async () => {
    installTimingSafeEqual();
    S = await import("../../worker/share");
    codec = await import("../../src/state/url");
    expect(typeof S.handleShare, "worker/share.ts must export handleShare").toBe("function");
    expect(typeof S.shareLimit, "worker/share.ts must export shareLimit").toBe("function");
    expect(codec.encode(codec.decode(CANONICAL))).toBe(CANONICAL);
  });
  beforeEach(() => {
    stubFetch();
    logs = [];
    for (const level of ["log", "info", "warn", "error", "debug"] as const) {
      vi.spyOn(console, level).mockImplementation((...args: any[]) => void logs.push(args));
    }
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("a valid share sends one fixed-template message carrying the re-encoded link", async () => {
    const to = "reader.one+ps@example.org";
    const ips: string[] = [];
    const exemptions: unknown[] = [];
    const res: Response = await S.handleShare(post({ to, url: SHUFFLED }, { ip: "198.51.100.23" }), baseEnv(), async (ip: string, exempt: boolean) => {
      ips.push(ip);
      exemptions.push(exempt);
      return true;
    });
    expect(exemptions).toEqual([false]);
    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({ ok: true });
    expect(ips).toEqual(["198.51.100.23"]);
    expect(sent.length).toBe(1);
    const m = sent[0];
    expect(m.url).toBe(MAIL_URL);
    expect(m.method).toBe("POST");
    expect(m.headers.get("x-api-key")).toBe("mc-key-under-test");
    expect(m.json.personalizations.length).toBe(1);
    const p = m.json.personalizations[0];
    expect(p.to.length).toBe(1);
    expect(p.to[0].email).toBe(to);
    expect(p.dkim_domain).toBe("automateintelligence.ai");
    expect(p.dkim_selector).toBe("mailchannels");
    expect(p.dkim_private_key).toBe("DKIM-PRIVATE-KEY-UNDER-TEST");
    expect(m.json.from).toEqual({ email: "sender-under-test@automateintelligence.ai", name: "PortfolioSight" });
    expect(m.json.reply_to.email).toBe("replies-under-test@automateintelligence.ai");
    expect(m.json.subject).toBe(SUBJECT);
    const link = `${SITE}/` + codec.encode(codec.decode(new URL(SHUFFLED).search));
    expect(link).toBe(`${SITE}/${CANONICAL}`);
    expect(lines(textPart(m.json))).toEqual([LINE_1, link, LINE_3]);
    const html = htmlPart(m.json);
    expect(html.includes(link) || html.includes(link.replaceAll("&", "&amp;")), "the HTML part must carry the re-encoded link").toBe(true);
    // the submitted string differs from the re-encoded one and must not be in the message
    expect(SHUFFLED).not.toBe(link);
    expect(m.text).not.toContain(SHUFFLED);
    expect(m.text).not.toContain(SHUFFLED.replaceAll("&", "&amp;"));
    expect(m.text).not.toContain("t=hud&d=auto");
    expect(m.text).not.toContain("ZZ-SENTINEL-ZZ");
    // the link follows the submitted state (it is not a constant)
    stubFetch();
    const other = `${SITE}/?x=1&t=light&d=0.25&r=12.5&lb=3y&u=tsp`;
    const res2: Response = await S.handleShare(post({ to, url: other }), baseEnv(), allow);
    expect(res2.status).toBe(202);
    expect(lines(textPart(sent[0].json))[1]).toBe(`${SITE}/?u=tsp&lb=3y&r=12.5&d=0.25&t=light&x=1`);
  });

  it("every invalid input is refused with its code and nothing is sent", async () => {
    const good = { to: "reader@example.org", url: `${SITE}/${CANONICAL}` };
    const long = "x".repeat(243) + "@example.com";
    expect(long.length).toBe(255);
    const cases: Array<{ name: string; req: () => Request; status: number[]; code?: string }> = [
      { name: "display-name recipient", req: () => post({ ...good, to: "Jeff <a@b.c>" }), status: [400], code: "invalid_recipient" },
      { name: "two addresses (comma)", req: () => post({ ...good, to: "a@example.org, b@example.org" }), status: [400], code: "invalid_recipient" },
      { name: "two addresses (semicolon)", req: () => post({ ...good, to: "a@example.org;b@example.org" }), status: [400], code: "invalid_recipient" },
      { name: "255-char address", req: () => post({ ...good, to: long }), status: [400], code: "invalid_recipient" },
      { name: "no at sign", req: () => post({ ...good, to: "not-an-address" }), status: [400], code: "invalid_recipient" },
      { name: "header injection", req: () => post({ ...good, to: "a@example.org\r\nBcc: b@example.org" }), status: [400], code: "invalid_recipient" },
      { name: "empty recipient", req: () => post({ ...good, to: "" }), status: [400], code: "invalid_recipient" },
      { name: "url on example.com", req: () => post({ ...good, url: `https://example.com/${CANONICAL}` }), status: [400], code: "invalid_url" },
      { name: "javascript: url", req: () => post({ ...good, url: "javascript:alert(1)//portfoliosight.ai/?u=tsp" }), status: [400], code: "invalid_url" },
      { name: "http url", req: () => post({ ...good, url: `http://portfoliosight.ai/${CANONICAL}` }), status: [400], code: "invalid_url" },
      { name: "lookalike host", req: () => post({ ...good, url: `https://portfoliosight.ai.example.com/${CANONICAL}` }), status: [400], code: "invalid_url" },
      { name: "other path", req: () => post({ ...good, url: `${SITE}/admin${CANONICAL}` }), status: [400], code: "invalid_url" },
      { name: "not a url", req: () => post({ ...good, url: "see my portfolio" }), status: [400], code: "invalid_url" },
      { name: "3 KB body", req: () => post({ ...good, pad: "p".repeat(3000) }), status: [413] },
      { name: "not JSON (text/plain)", req: () => post(null, { contentType: "text/plain", raw: JSON.stringify(good) }), status: [415] },
      { name: "malformed JSON", req: () => post(null, { raw: "{to: reader@example.org" }), status: [400, 415] },
      { name: "foreign Origin", req: () => post(good, { origin: "https://evil.example.com" }), status: [400, 403] },
      { name: "no Origin", req: () => post(good, { origin: null }), status: [400, 403] },
    ];
    let checked = 0;
    for (const c of cases) {
      stubFetch();
      const res: Response = await S.handleShare(c.req(), baseEnv(), allow);
      expect(c.status, `${c.name}: status ${res.status}`).toContain(res.status);
      expect(res.status, c.name).not.toBe(202);
      if (c.code) expect(await codeOf(res), c.name).toBe(c.code);
      expect(outbound, `${c.name}: something was sent`).toBe(0);
      checked += 1;
    }
    expect(checked).toBe(18);
    // control: the base input of these cases is itself accepted
    stubFetch();
    expect((await S.handleShare(post(good), baseEnv(), allow)).status).toBe(202);
    expect(sent.length).toBe(1);
  });

  it("keys outside the URL contract and visitor text never reach the message", async () => {
    const to = "reader@example.org";
    const dirty = [`${SITE}/?u=tsp&zz=1&lb=3y&d=auto`, `${SITE}/?u=tsp&lb=3y&d=auto&k=ZZ-SENTINEL-ZZ`, `${SITE}/?k=ZZ-SENTINEL-ZZ&zz=VISITOR-MARKER&u=tsp&lb=3y&d=auto`];
    let checked = 0;
    for (const url of dirty) {
      stubFetch();
      const res: Response = await S.handleShare(post({ to, url }), baseEnv(), allow);
      if (res.status === 202) {
        expect(sent.length).toBe(1);
        const link = lines(textPart(sent[0].json))[1];
        expect(link).toBe(`${SITE}/` + codec.encode(codec.decode(new URL(url).search)));
        expect(Array.from(new URL(link).searchParams.keys())).not.toContain("zz");
        expect(Array.from(new URL(link).searchParams.keys())).not.toContain("k");
      } else {
        expect(res.status).toBe(400);
        expect(await codeOf(res)).toBe("invalid_url");
        expect(outbound).toBe(0);
      }
      for (const m of sent) {
        expect(m.text).not.toContain("zz=");
        expect(m.text).not.toContain("k=ZZ");
        expect(m.text).not.toContain("ZZ-SENTINEL-ZZ");
        expect(m.text).not.toContain("VISITOR-MARKER");
      }
      checked += 1;
    }
    expect(checked).toBe(3);
    stubFetch();
    const extra = { to, url: `${SITE}/${CANONICAL}`, subject: "VISITOR-MARKER subject", text: "VISITOR-MARKER text", name: "VISITOR-MARKER" };
    const res: Response = await S.handleShare(post(extra), baseEnv(), allow);
    if (res.status === 202) {
      expect(sent.length).toBe(1);
      expect(sent[0].json.subject).toBe(SUBJECT);
      expect(lines(textPart(sent[0].json))).toEqual([LINE_1, `${SITE}/${CANONICAL}`, LINE_3]);
    } else {
      expect(res.status).toBeGreaterThanOrEqual(400);
      expect(res.status).toBeLessThan(500);
      expect(outbound).toBe(0);
    }
    for (const m of sent) expect(m.text).not.toContain("VISITOR-MARKER");
  });

  it("a link in any of the four themes is sent and an unknown theme is refused", async () => {
    const to = "reader@example.org";
    let checked = 0;
    for (const theme of ["ks-dark", "light", "hud", "grid"]) {
      stubFetch();
      const url = `${SITE}/?t=${theme}&d=auto&lb=5y&u=tsp`;
      const res: Response = await S.handleShare(post({ to, url }), baseEnv(), allow);
      expect(res.status, `t=${theme}`).toBe(202);
      expect(sent.length, `t=${theme}`).toBe(1);
      const link = lines(textPart(sent[0].json))[1];
      expect(link, `t=${theme}`).toBe(`${SITE}/` + codec.encode(codec.decode(new URL(url).search)));
      expect(new URL(link).searchParams.get("t"), `t=${theme}`).toBe(theme);
      checked += 1;
    }
    expect(checked).toBe(4);
    for (const theme of ["neon", "dark", "HUD", "Grid", "grid2", "hud,grid", ""]) {
      stubFetch();
      const res: Response = await S.handleShare(post({ to, url: `${SITE}/?u=tsp&lb=5y&d=auto&t=${theme}` }), baseEnv(), allow);
      expect(res.status, `t=${theme}`).toBe(400);
      expect(await codeOf(res), `t=${theme}`).toBe("invalid_url");
      expect(outbound, `t=${theme}: something was sent`).toBe(0);
      checked += 1;
    }
    expect(checked).toBe(11);
  });

  it("the caps refuse the 2nd per IP per minute, the 4th per IP per day and the 51st per day", async () => {
    // the per-IP sequences below carry no x-ps-gate header
    vi.useFakeTimers({ toFake: ["Date"] });
    let counts: any = {};
    let verdicts: boolean[] = [];
    const limiter = async (ip: string, exempt: boolean) => {
      expect(typeof exempt, "handleShare must tell the limiter whether the request is exempt").toBe("boolean");
      const out = S.shareLimit(counts, ip, Date.now(), CAPS, exempt);
      expect(typeof out.allowed).toBe("boolean");
      counts = out.counts;
      verdicts.push(out.allowed);
      return out.allowed;
    };
    const reset = () => {
      counts = {};
      verdicts = [];
      stubFetch();
    };
    const good = { to: "reader@example.org", url: `${SITE}/${CANONICAL}` };
    const share = async (ip: string, atMs: number, gate?: string) => {
      vi.setSystemTime(new Date(atMs));
      const before = sent.length;
      const res: Response = await S.handleShare(post(good, { ip, gate }), baseEnv(), limiter);
      const code = res.status === 202 ? "sent" : await codeOf(res);
      // a refusal sends nothing; an acceptance sends exactly one message
      expect(sent.length - before).toBe(res.status === 202 ? 1 : 0);
      return `${res.status} ${code}`;
    };
    const A = "203.0.113.1";
    const B = "203.0.113.2";
    const OK = "202 sent";
    const NO = "429 rate_limited";

    // per IP per minute, two IPs independent
    reset();
    expect(await share(A, T0)).toBe(OK);
    expect(await share(A, T0 + 10_000)).toBe(NO);
    expect(await share(B, T0 + 10_000)).toBe(OK);
    expect(await share(B, T0 + 20_000)).toBe(NO);
    expect(await share(A, T0 + 61_000)).toBe(OK);
    expect(verdicts).toEqual([true, false, true, false, true]);

    // per IP per day, another IP unaffected, a new UTC day starts over
    reset();
    expect(await share(A, T0)).toBe(OK);
    expect(await share(A, T0 + 61_000)).toBe(OK);
    expect(await share(A, T0 + 122_000)).toBe(OK);
    expect(await share(A, T0 + 183_000)).toBe(NO);
    expect(await share(A, T0 + 3_600_000)).toBe(NO);
    expect(await share(B, T0 + 183_000)).toBe(OK);
    expect(await share(A, T0 + 86_400_000)).toBe(OK);

    // global per day, shared by all IPs
    reset();
    for (let i = 0; i < 50; i++) expect(await share(`198.51.100.${i + 1}`, T0 + i * 1000), `global send ${i + 1}`).toBe(OK);
    expect(sent.length).toBe(50);
    expect(await share("198.51.100.200", T0 + 60_000)).toBe(NO);
    expect(await share("198.51.100.201", T0 + 7_200_000)).toBe(NO);
    expect(sent.length).not.toBeGreaterThan(50);
    expect(await share("198.51.100.202", T0 + 86_400_000)).toBe(OK);

    // the valid gate header lifts the two per-IP caps (2nd in a minute, 4th in a day)
    reset();
    const GATE = "ZZ-SENTINEL-ZZ";
    expect(await share(A, T0, GATE)).toBe(OK);
    expect(await share(A, T0 + 10_000, GATE)).toBe(OK);
    expect(await share(A, T0 + 20_000, GATE)).toBe(OK);
    expect(await share(A, T0 + 30_000, GATE)).toBe(OK);
    expect(await share(A, T0 + 40_000, GATE)).toBe(OK);
    expect(verdicts).toEqual([true, true, true, true, true]);
    expect(sent.length).toBe(5);

    // a wrong header value gets no exemption
    for (const wrong of ["wrong", "ZZ-SENTINEL-ZY", "", "ZZ-SENTINEL-ZZx", "zz-sentinel-zz"]) {
      reset();
      expect(await share(A, T0, wrong), `x-ps-gate "${wrong}"`).toBe(OK);
      expect(await share(A, T0 + 10_000, wrong), `x-ps-gate "${wrong}" was exempted`).toBe(NO);
      expect(await share(A, T0 + 10_000, wrong)).not.toBe(OK);
    }

    // the global cap still binds with the header, and headered sends count toward it
    reset();
    for (let i = 0; i < 50; i++) expect(await share(A, T0 + i * 1000, GATE), `headered global send ${i + 1}`).toBe(OK);
    expect(sent.length).toBe(50);
    expect(await share(A, T0 + 60_000, GATE), "the 51st global send was accepted with the header").toBe(NO);
    expect(await share(B, T0 + 60_000)).toBe(NO);
    expect(await share(B, T0 + 61_000, GATE)).toBe(NO);
    expect(sent.length).not.toBeGreaterThan(50);
    reset();
    for (let i = 0; i < 49; i++) expect(await share(`198.51.100.${i + 1}`, T0 + i * 1000)).toBe(OK);
    expect(await share(A, T0 + 50_000, GATE)).toBe(OK);
    expect(await share(B, T0 + 51_000)).toBe(NO);

    // the handler obeys whatever limiter it is given
    reset();
    const refused: Response = await S.handleShare(post(good), baseEnv(), async () => false);
    expect(refused.status).toBe(429);
    expect(await codeOf(refused)).toBe("rate_limited");
    expect(outbound).toBe(0);
  });

  it("the test key is a logged no-op", async () => {
    const env = { ...baseEnv(), MAILCHANNELS_API_KEY: "test" };
    const res: Response = await S.handleShare(post({ to: "reader@example.org", url: SHUFFLED }), env, allow);
    expect(res.status).toBe(202);
    expect(await res.json()).toEqual({ ok: true });
    expect(outbound, "the test key must not reach MailChannels").toBe(0);
    expect(logs.length, "exactly one log line").toBe(1);
    expect(JSON.stringify(logs)).not.toContain("DKIM-PRIVATE-KEY-UNDER-TEST");
    // with a real key the same request does send, and logs nothing about a no-op send
    stubFetch();
    const res2: Response = await S.handleShare(post({ to: "reader@example.org", url: SHUFFLED }), baseEnv(), allow);
    expect(res2.status).toBe(202);
    expect(outbound).toBe(1);
  });

  it("the dialog shows the preview notice only while preview is on", async () => {
    const mod: any = await import("../../src/controls/ShareDialog");
    expect(typeof mod.ShareDialog, "ShareDialog.tsx must export ShareDialog").toBe("function");
    const render = (privatePreview: boolean) =>
      renderToStaticMarkup(createElement(mod.ShareDialog, { open: true, url: `${SITE}/${CANONICAL}`, privatePreview, onClose: () => undefined }));
    const on = render(true);
    const off = render(false);
    for (const html of [on, off]) {
      for (const id of ["share-copy", "share-email", "share-send"]) expect(html, `data-testid ${id}`).toContain(`data-testid="${id}"`);
    }
    expect(on.toLowerCase()).toContain("private preview");
    expect(off.toLowerCase()).not.toContain("private preview");
    expect(on.length).toBeGreaterThan(off.length);
  });
});
"""
EXPECTED_TITLES = {
    "a valid share sends one fixed-template message carrying the re-encoded link",
    "every invalid input is refused with its code and nothing is sent",
    "keys outside the URL contract and visitor text never reach the message",
    "a link in any of the four themes is sent and an unknown theme is refused",
    "the caps refuse the 2nd per IP per minute, the 4th per IP per day and the 51st per day",
    "the test key is a logged no-op",
    "the dialog shows the preview notice only while preview is on",
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


def test_a_ps_38_vitest():
    statuses = _run_vitest("a_ps_38", SPEC_TS)
    assert set(statuses) == EXPECTED_TITLES, (
        f"vitest ran a different set of tests: {sorted(statuses)}"
    )
    not_passed = {title: status for title, status in statuses.items() if status != "passed"}
    assert not not_passed, f"vitest legs not passed (failed, skipped or todo): {not_passed}"
