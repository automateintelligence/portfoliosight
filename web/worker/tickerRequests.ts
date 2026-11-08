// Tickers people ask for that the site does not serve (the CSV upload's skipped tickers and a
// ticker typed into the fund picker that matches nothing). `POST /api/ticker-requests` records
// them, `GET /api/ticker-requests` lists them for an admin: what people want added.
//
// Only a ticker and a count are kept. A visitor address counts a ticker at most once per UTC
// day, and the address is held only as a hash under a salt that is random per day and dropped
// with the day's rows; no address, amount or file content is stored or logged. One address may
// add at most `MAX_NEW_PER_VISITOR_DAY` new tickers a day, so the table cannot be flooded from
// one place. Answers never repeat a ticker.
//
// This module must load in plain Node (unit tests): Workers types are used as ambient types
// only and nothing is imported from `cloudflare:*`.

import { jsonError, jsonResponse, readBodyLimited, SITE_ORIGIN, visitorAddress } from "./share";

export type TickerSource = "csv" | "picker";
export type TickerRequestRow = { ticker: string; count: number; csv: number; picker: number; first_seen: string; last_seen: string };

/** Resolves `true` once the tickers are counted. */
export type TickerRecorderFn = (ip: string, tickers: string[], source: TickerSource) => Promise<boolean>;
/** The ids the site serves, or `null` when they cannot be read (then nothing is left out). */
export type ServedIdsFn = () => Promise<ReadonlySet<string> | null>;

export const TICKER_SHAPE = /^[A-Z0-9.-]{1,10}$/;
export const MAX_TICKER_REQUEST_BODY_BYTES = 4096;
export const MAX_TICKERS_PER_REQUEST = 100;
export const MAX_NEW_TICKERS_PER_VISITOR_DAY = 300;
const MAX_LISTED = 5000;
const SOURCES: ReadonlySet<unknown> = new Set<TickerSource>(["csv", "picker"]);

const utcDay = (ms: number) => new Date(ms).toISOString().slice(0, 10);
const noContent = () => new Response(null, { status: 204, headers: { "cache-control": "no-store" } });

/** The valid, upper-cased, distinct tickers of a request body and its source, or `null` for a body to refuse. */
export function parseTickerRequest(body: unknown): { tickers: string[]; source: TickerSource } | null {
  if (typeof body !== "object" || body === null || Array.isArray(body)) return null;
  const { tickers, source } = body as { tickers?: unknown; source?: unknown };
  if (!SOURCES.has(source) || !Array.isArray(tickers) || tickers.length < 1 || tickers.length > MAX_TICKERS_PER_REQUEST) return null;
  const valid = new Set<string>();
  for (const item of tickers) {
    const ticker = typeof item === "string" ? item.toUpperCase() : "";
    if (TICKER_SHAPE.test(ticker)) valid.add(ticker);
  }
  return valid.size === 0 ? null : { tickers: [...valid], source: source as TickerSource };
}

/**
 * `POST /api/ticker-requests {"tickers": [..], "source": "csv" | "picker"}` → 204. Invalid
 * tickers are dropped; a body with none left, a list outside 1 to 100 or another source is a 400.
 * Tickers the site serves are not counted.
 */
export async function handleTickerRequest(request: Request, record: TickerRecorderFn, served: ServedIdsFn): Promise<Response> {
  if (request.headers.get("origin") !== SITE_ORIGIN) return jsonError(403, "forbidden_origin", "Requests are accepted from the site only");
  const mediaType = (request.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
  if (mediaType !== "application/json") return jsonError(415, "unsupported_media_type", "Send application/json");
  const bytes = await readBodyLimited(request, MAX_TICKER_REQUEST_BODY_BYTES);
  if (bytes === null) return jsonError(413, "payload_too_large", "The request body is over 4 KB");

  let body: unknown;
  try {
    body = JSON.parse(new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(bytes));
  } catch {
    return jsonError(400, "invalid_request", "The body is not valid JSON");
  }
  const parsed = parseTickerRequest(body);
  if (parsed === null) return jsonError(400, "invalid_request", "Send 1 to 100 tickers and a source of csv or picker");

  const ids = await served();
  const wanted = ids === null ? parsed.tickers : parsed.tickers.filter((ticker) => !ids.has(ticker));
  if (wanted.length === 0) return noContent();
  if (!(await record(visitorAddress(request), wanted, parsed.source))) return jsonError(503, "unavailable", "The request could not be recorded right now");
  return noContent();
}

/** `GET /api/ticker-requests` for an admin: the list, most asked first. The caller checks the admin. */
export async function listTickerRequests(namespace: DurableObjectNamespace): Promise<Response> {
  try {
    const stub = namespace.get(namespace.idFromName("global"));
    const res = await stub.fetch("https://ticker-requests/list");
    if (!res.ok) return jsonError(503, "unavailable", "The list is not available right now");
    return new Response(res.body, { status: 200, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
  } catch {
    console.error("ticker requests: store unavailable");
    return jsonError(503, "unavailable", "The list is not available right now");
  }
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * The one global store of requested tickers (SQLite-backed Durable Object, addressed by the name
 * "global").
 *
 * `POST /record {ip, tickers, source}` answers `{recorded}`, the number of tickers counted;
 * `GET /list` answers the rows. The check-and-count runs without an `await`, so two simultaneous
 * requests from one address cannot both count a ticker.
 */
export class TickerRequests {
  private readonly sql: SqlStorage;

  constructor(state: DurableObjectState, _env: unknown) {
    this.sql = state.storage.sql;
    this.sql.exec(
      "CREATE TABLE IF NOT EXISTS ticker_requests (ticker TEXT PRIMARY KEY, csv INTEGER NOT NULL DEFAULT 0, picker INTEGER NOT NULL DEFAULT 0, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)",
    );
    this.sql.exec("CREATE TABLE IF NOT EXISTS ticker_seen (day TEXT NOT NULL, visitor TEXT NOT NULL, ticker TEXT NOT NULL, PRIMARY KEY (day, visitor, ticker))");
    this.sql.exec("CREATE TABLE IF NOT EXISTS day_salt (day TEXT PRIMARY KEY, salt TEXT NOT NULL)");
  }

  async fetch(request: Request): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (request.method === "GET" && pathname === "/list") return jsonResponse(200, this.list());
    if (request.method !== "POST" || pathname !== "/record") return jsonError(404, "not_found", "No such path");
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return jsonError(400, "invalid_request", "The body is not JSON");
    }
    const { ip, tickers, source } = (typeof body === "object" && body !== null ? body : {}) as { ip?: unknown; tickers?: unknown; source?: unknown };
    if (typeof ip !== "string" || ip.length === 0 || ip.length > 45 || !SOURCES.has(source) || !Array.isArray(tickers)) {
      return jsonError(400, "invalid_request", "ip, tickers and source are required");
    }
    const valid = tickers.filter((t): t is string => typeof t === "string" && TICKER_SHAPE.test(t));
    const day = utcDay(Date.now());
    // the day's salt is read or made without an await; only the hashing waits, and the count follows without one
    const visitor = await sha256Hex(`${this.saltFor(day)}|${ip}`);
    return jsonResponse(200, { recorded: this.record(day, visitor, valid, source as TickerSource) });
  }

  private saltFor(day: string): string {
    const rows = this.sql.exec("SELECT salt FROM day_salt WHERE day = ?", day).toArray();
    if (rows.length > 0) return String(rows[0].salt);
    const salt = Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, "0")).join("");
    this.sql.exec("INSERT INTO day_salt (day, salt) VALUES (?, ?)", day, salt);
    return salt;
  }

  private record(day: string, visitor: string, tickers: string[], source: TickerSource): number {
    // yesterday's keys and salt go: a visitor is only ever known within one UTC day
    this.sql.exec("DELETE FROM ticker_seen WHERE day < ?", day);
    this.sql.exec("DELETE FROM day_salt WHERE day < ?", day);
    let used = Number(this.sql.exec("SELECT COUNT(*) AS n FROM ticker_seen WHERE day = ? AND visitor = ?", day, visitor).toArray()[0].n);
    let recorded = 0;
    for (const ticker of new Set(tickers)) {
      if (used >= MAX_NEW_TICKERS_PER_VISITOR_DAY) break;
      if (this.sql.exec("SELECT 1 AS seen FROM ticker_seen WHERE day = ? AND visitor = ? AND ticker = ?", day, visitor, ticker).toArray().length > 0) continue;
      this.sql.exec("INSERT INTO ticker_seen (day, visitor, ticker) VALUES (?, ?, ?)", day, visitor, ticker);
      this.sql.exec(
        "INSERT INTO ticker_requests (ticker, csv, picker, first_seen, last_seen) VALUES (?, ?, ?, ?, ?) " +
          "ON CONFLICT(ticker) DO UPDATE SET csv = csv + excluded.csv, picker = picker + excluded.picker, last_seen = excluded.last_seen",
        ticker,
        source === "csv" ? 1 : 0,
        source === "picker" ? 1 : 0,
        day,
        day,
      );
      used += 1;
      recorded += 1;
    }
    return recorded;
  }

  private list(): TickerRequestRow[] {
    return this.sql
      .exec("SELECT ticker, csv + picker AS count, csv, picker, first_seen, last_seen FROM ticker_requests ORDER BY count DESC, ticker ASC LIMIT ?", MAX_LISTED)
      .toArray()
      .map((row) => ({
        ticker: String(row.ticker),
        count: Number(row.count),
        csv: Number(row.csv),
        picker: Number(row.picker),
        first_seen: String(row.first_seen),
        last_seen: String(row.last_seen),
      }));
  }
}
