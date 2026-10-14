// Share by email (spec §9.3): the only place the site sends anything outward.
//
// The endpoint is reachable by anyone who can load the page, so every input is checked before
// anything is counted or sent: same-origin only, a small JSON body, one bare recipient address,
// and a link that is rebuilt here from the spec §8.1 keys (the submitted string is never
// mailed). The message is a fixed template. Sends are capped per address and globally by the
// `ShareLimiter` Durable Object; allowance is taken before the send, so a failed send still
// counts and a refused one changes nothing.
//
// This module must load in plain Node (unit tests): Workers types are used as ambient types
// only and nothing is imported from `cloudflare:*`.

import { secretEquals } from "./preview";
import { decode, encode } from "../src/state/url";

export interface ShareEnv {
  SHARE_FROM?: string;
  SHARE_REPLY_TO?: string;
  SHARE_CAP_IP_MINUTE?: string;
  SHARE_CAP_IP_DAY?: string;
  SHARE_CAP_GLOBAL_DAY?: string;
  MAILCHANNELS_API_KEY?: string;
  MAILCHANNELS_DKIM_PRIVATE_KEY?: string;
  PS_GATE_SECRET?: string;
}

/** Resolves `true` when the send may go ahead; `exempt` lifts the per-address caps only. */
export type ShareLimiterFn = (ip: string, exempt: boolean) => Promise<boolean>;

const SITE_ORIGIN = "https://portfoliosight.ai";
const MAIL_URL = "https://api.mailchannels.net/tx/v1/send";
const DKIM_DOMAIN = "automateintelligence.ai";
const DKIM_SELECTOR = "mailchannels";
const SENDER_NAME = "PortfolioSight";
const SUBJECT = "Someone shared a PortfolioSight view with you";
const LINE_INTRO = "Someone shared a PortfolioSight view with you:";
const LINE_DISCLAIMER = "PortfolioSight is an educational tool. Historical math, not investment advice.";

export const MAX_SHARE_BODY_BYTES = 2048;
const MAX_SHARE_URL_CHARS = 2048;
const MAX_ADDRESS_CHARS = 254;
const MAX_LOCAL_PART_CHARS = 64;
const MAX_FUNDS = 30;

// ---------------------------------------------------------------- responses

export function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...headers },
  });
}

export function jsonError(status: number, code: string, message: string, headers: Record<string, string> = {}): Response {
  return jsonResponse(status, { error: { code, message, details: null } }, headers);
}

/** The request body, or `null` once it exceeds `maxBytes` (measured on the bytes, not a header). */
export async function readBodyLimited(request: Request, maxBytes: number): Promise<Uint8Array | null> {
  const declared = Number(request.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > maxBytes) return null;
  if (request.body === null) return new Uint8Array(0);
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

// ---------------------------------------------------------------- validators

// RFC 5322 addr-spec restricted to the dot-atom forms: no quoted local part, no domain literal,
// no comments, no display name. The domain needs at least two labels.
const LOCAL_PART = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/;
const DOMAIN = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/;

export function isBareAddress(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > MAX_ADDRESS_CHARS) return false;
  const at = value.lastIndexOf("@");
  if (at < 1) return false;
  const local = value.slice(0, at);
  return local.length <= MAX_LOCAL_PART_CHARS && LOCAL_PART.test(local) && DOMAIN.test(value.slice(at + 1));
}

const LOOKBACK = "(?:1y|2y|3y|5y|10y|ew)";
const FUND_ID = "[A-Z0-9][A-Z0-9.-]{0,11}";
const listOf = (item: string, max: number) => new RegExp(`^${item}(?:,${item}){0,${max - 1}}$`);

type Shape = (value: string) => boolean;
const matching = (pattern: RegExp): Shape => (value) => pattern.test(value);
// a theme is one the page's own codec keeps, so the mailed themes cannot drift from the page's
const pageTheme: Shape = (value) => decode(new URLSearchParams([["t", value]]).toString()).theme === value;

// The spec §8.1 keys in the order the page writes them, each with the only value shape it may
// take. A value is mailed only if it matches, so a link cannot carry free text.
const URL_KEYS: ReadonlyArray<readonly [string, Shape]> = [
  ["u", matching(/^(?:guide2017|tsp)$/)],
  ["f", matching(listOf(`${FUND_ID}(?::\\d{1,12}(?:\\.\\d{1,6})?)?`, MAX_FUNDS))],
  ["unit", matching(/^(?:pct|usd|shares)$/)],
  ["c", matching(listOf(`${FUND_ID}:(?:\\d{1,3})?:(?:\\d{1,3})?`, MAX_FUNDS))],
  ["lb", matching(new RegExp(`^${LOOKBACK}$`))],
  ["g", matching(listOf(LOOKBACK, 6))],
  ["r", matching(/^-?\d{1,4}(?:\.\d{1,12})?$/)],
  ["d", matching(/^(?:auto|0(?:\.\d{1,12})?|1(?:\.0{1,12})?)$/)],
  ["t", pageTheme],
  ["x", matching(/^1$/)],
];
// Written by the page even at their defaults; `unit=pct` is the default the page leaves out.

/**
 * Rebuilds a submitted link from the spec §8.1 keys, or returns `null` when it is not a link to
 * this site's page, carries any other key (the preview key `k` included), repeats a key, has a
 * value outside its shape, or is longer than 2,048 characters once rebuilt.
 */
export function reencodeShareUrl(submitted: unknown): string | null {
  if (typeof submitted !== "string" || !submitted.startsWith(SITE_ORIGIN)) return null;
  let url: URL;
  try {
    url = new URL(submitted);
  } catch {
    return null;
  }
  if (url.origin !== SITE_ORIGIN || url.username !== "" || url.password !== "") return null;
  if (url.pathname !== "/" || url.hash !== "" || submitted.includes("#")) return null;

  const shapes = new Map(URL_KEYS);
  const values = new Map<string, string>();
  for (const [key, value] of url.searchParams) {
    const shape = shapes.get(key);
    if (shape === undefined || values.has(key) || !shape(value)) return null;
    values.set(key, value);
  }
  // The mailed link is the page's own canonical form of the view (the codec of spec 8.1), so it
  // is byte-equal to what the address bar would show; the submitted string itself is never sent.
  const link = `${SITE_ORIGIN}/${encode(decode(url.search))}`;
  return link.length <= MAX_SHARE_URL_CHARS ? link : null;
}

// ---------------------------------------------------------------- caps

export interface ShareCaps {
  ipMinute: number;
  ipDay: number;
  globalDay: number;
}

/** Opaque to callers: thread the returned record into the next call. Holds allowed sends only. */
export interface ShareCounts {
  day?: string;
  global?: number;
  perIp?: Record<string, number>;
  recent?: Record<string, number[]>;
}

const MINUTE_MS = 60_000;
const utcDay = (ms: number) => new Date(ms).toISOString().slice(0, 10);

/**
 * The counting rule, free of I/O. A send is allowed while the global count for the UTC day is
 * under `globalDay` and, unless `exempt`, the address has fewer than `ipDay` sends that day and
 * fewer than `ipMinute` in the last 60 seconds. Only an allowed send is recorded, so refusals
 * neither use up allowance nor extend a wait. Exempt sends count toward the global cap only.
 */
export function shareLimit(counts: ShareCounts, ip: string, nowMs: number, caps: ShareCaps, exempt = false): { allowed: boolean; counts: ShareCounts } {
  const day = utcDay(nowMs);
  const sameDay = counts.day === day;
  const global = sameDay ? (counts.global ?? 0) : 0;
  const perIp: Record<string, number> = sameDay ? { ...counts.perIp } : {};
  // the minute window is kept across a day change
  const recent: Record<string, number[]> = {};
  for (const [address, times] of Object.entries(counts.recent ?? {})) {
    const kept = times.filter((at) => at > nowMs - MINUTE_MS);
    if (kept.length > 0) recent[address] = kept;
  }
  const next: ShareCounts = { day, global, perIp, recent };

  if (global >= caps.globalDay) return { allowed: false, counts: next };
  if (!exempt) {
    if ((perIp[ip] ?? 0) >= caps.ipDay) return { allowed: false, counts: next };
    if ((recent[ip]?.length ?? 0) >= caps.ipMinute) return { allowed: false, counts: next };
    perIp[ip] = (perIp[ip] ?? 0) + 1;
    recent[ip] = [...(recent[ip] ?? []), nowMs];
  }
  next.global = global + 1;
  return { allowed: true, counts: next };
}

function capFrom(value: string | undefined, fallback: number): number {
  return value !== undefined && /^\d{1,6}$/.test(value) ? Number(value) : fallback;
}

export function capsFromEnv(env: ShareEnv): ShareCaps {
  return {
    ipMinute: capFrom(env.SHARE_CAP_IP_MINUTE, 1),
    ipDay: capFrom(env.SHARE_CAP_IP_DAY, 3),
    globalDay: capFrom(env.SHARE_CAP_GLOBAL_DAY, 50),
  };
}

function isShareCounts(value: unknown): value is ShareCounts {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const c = value as Record<string, unknown>;
  const isRecord = (v: unknown, item: (x: unknown) => boolean) =>
    typeof v === "object" && v !== null && !Array.isArray(v) && Object.values(v).every(item);
  return (
    typeof c.day === "string" &&
    typeof c.global === "number" &&
    isRecord(c.perIp, (n) => typeof n === "number") &&
    isRecord(c.recent, (list) => Array.isArray(list) && list.every((at) => typeof at === "number"))
  );
}

/**
 * The one global share limiter (SQLite-backed Durable Object, addressed by the name "global").
 * It holds a single small record per UTC day: only allowed sends are recorded and the global
 * cap bounds them, so the record never grows past `globalDay` addresses.
 *
 * `POST {ip, exempt}` answers `{allowed}`. The read-check-write runs without an `await`, so two
 * simultaneous requests cannot both take the last slot.
 */
export class ShareLimiter {
  private readonly sql: SqlStorage;
  private readonly caps: ShareCaps;

  constructor(state: DurableObjectState, env: ShareEnv) {
    this.sql = state.storage.sql;
    this.caps = capsFromEnv(env);
    this.sql.exec("CREATE TABLE IF NOT EXISTS share_counts (day TEXT PRIMARY KEY, counts TEXT NOT NULL)");
  }

  async fetch(request: Request): Promise<Response> {
    if (request.method !== "POST") return jsonError(405, "method_not_allowed", "POST only");
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return jsonError(400, "invalid_request", "The body is not JSON");
    }
    const { ip, exempt } = (typeof body === "object" && body !== null ? body : {}) as { ip?: unknown; exempt?: unknown };
    if (typeof ip !== "string" || typeof exempt !== "boolean") return jsonError(400, "invalid_request", "ip and exempt are required");
    return jsonResponse(200, { allowed: this.check(ip, exempt, Date.now()) });
  }

  private check(ip: string, exempt: boolean, nowMs: number): boolean {
    const rows = this.sql.exec("SELECT day, counts FROM share_counts ORDER BY day DESC LIMIT 1").toArray();
    let counts: ShareCounts = {};
    if (rows.length > 0) {
      let stored: unknown = null;
      try {
        stored = JSON.parse(String(rows[0].counts));
      } catch {
        stored = null;
      }
      if (isShareCounts(stored)) counts = stored;
      // an unreadable record for today cannot be trusted to be under the caps: refuse until the day turns
      else if (String(rows[0].day) >= utcDay(nowMs)) return false;
    }
    const verdict = shareLimit(counts, ip, nowMs, this.caps, exempt);
    if (verdict.allowed) {
      const day = verdict.counts.day as string;
      this.sql.exec("INSERT OR REPLACE INTO share_counts (day, counts) VALUES (?, ?)", day, JSON.stringify(verdict.counts));
      this.sql.exec("DELETE FROM share_counts WHERE day < ?", day);
    }
    return verdict.allowed;
  }
}

// ---------------------------------------------------------------- sending

const escapeHtml = (text: string) => text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

async function sendShareMail(env: ShareEnv, to: string, link: string): Promise<boolean> {
  const { MAILCHANNELS_API_KEY: apiKey, MAILCHANNELS_DKIM_PRIVATE_KEY: dkimKey, SHARE_FROM: from, SHARE_REPLY_TO: replyTo } = env;
  if (apiKey === "test") {
    // local development only: nothing is sent, and the line names neither recipient nor link
    console.log("share: test key, send skipped");
    return true;
  }
  if (!apiKey || !dkimKey || !from || !replyTo) {
    console.error("share: mail is not configured");
    return false;
  }
  const href = escapeHtml(link);
  const message = {
    personalizations: [{ to: [{ email: to }], dkim_domain: DKIM_DOMAIN, dkim_selector: DKIM_SELECTOR, dkim_private_key: dkimKey }],
    from: { email: from, name: SENDER_NAME },
    reply_to: { email: replyTo },
    subject: SUBJECT,
    content: [
      { type: "text/plain", value: `${LINE_INTRO}\n\n${link}\n\n${LINE_DISCLAIMER}\n` },
      { type: "text/html", value: `<p>${LINE_INTRO}</p><p><a href="${href}">${href}</a></p><p>${LINE_DISCLAIMER}</p>` },
    ],
  };
  try {
    const res = await fetch(MAIL_URL, {
      method: "POST",
      headers: { "content-type": "application/json", "X-API-Key": apiKey },
      body: JSON.stringify(message),
    });
    if (!res.ok) console.error(`share: mail service answered ${res.status}`);
    return res.ok;
  } catch {
    console.error("share: mail service unreachable");
    return false;
  }
}

const IP_SHAPE = /^[0-9A-Fa-f:.]{2,45}$/;

/** `POST /api/share {"to", "url"}`. Validation comes first; the limiter is asked only for a sendable request. */
export async function handleShare(request: Request, env: ShareEnv, limiter: ShareLimiterFn): Promise<Response> {
  if (request.headers.get("origin") !== SITE_ORIGIN) return jsonError(403, "forbidden_origin", "Shares are accepted from the site only");
  const mediaType = (request.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (mediaType !== "application/json") return jsonError(415, "unsupported_media_type", "Send application/json");
  const bytes = await readBodyLimited(request, MAX_SHARE_BODY_BYTES);
  if (bytes === null) return jsonError(413, "payload_too_large", "The request body is over 2 KB");

  let body: unknown;
  try {
    body = JSON.parse(new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes));
  } catch {
    return jsonError(400, "invalid_request", "The body is not valid JSON");
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) return jsonError(400, "invalid_request", "The body must be a JSON object");
  // only these two fields are read; anything else in the body is ignored and never mailed
  const { to, url } = body as { to?: unknown; url?: unknown };
  if (!isBareAddress(to)) return jsonError(400, "invalid_recipient", "Enter one email address");
  const link = reencodeShareUrl(url);
  if (link === null) return jsonError(400, "invalid_url", "This view cannot be emailed; copy the link instead");

  const exempt = await secretEquals(request.headers.get("x-ps-gate"), env.PS_GATE_SECRET);
  const claimed = request.headers.get("cf-connecting-ip") ?? "";
  const ip = IP_SHAPE.test(claimed) ? claimed : "unknown";
  if (!(await limiter(ip, exempt))) return jsonError(429, "rate_limited", "Too many shares; try again later");

  if (!(await sendShareMail(env, to, link))) return jsonError(502, "mail_failed", "The message could not be sent");
  return jsonResponse(202, { ok: true });
}
