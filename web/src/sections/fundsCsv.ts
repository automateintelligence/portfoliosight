// The fund list as a CSV file, read in the browser (nothing of the file is sent anywhere): the
// template, the parser, and the choice of which amount column fills the table. Pure functions;
// the page (Funds.tsx) only hands them the file's text and the served catalog.
import Papa from "papaparse";
import {
  menuFull,
  menuNeedsMore,
  uploadBadNumber,
  uploadMismatch,
  uploadNegative,
  uploadNoCommonColumn,
  uploadNoFunds,
  uploadNoTicker,
  uploadNoTickerOnRow,
  uploadTooManyValues,
  uploadTwoColumns,
  uploadUnreadable,
} from "../copy";
import type { Row, Unit } from "../state/store";

export const TEMPLATE_FILENAME = "portfoliosight-template.csv";
export const TEMPLATE_CSV = "ticker,shares,dollars,percent\nVTI,,10000,40\nVXUS,,5000,20\nBND,,7500,30\nVNQ,,2500,10\n";
/** A fund list is a few thousand bytes; a bigger file is not one and is not read. */
export const MAX_FILE_BYTES = 1_000_000;

/** The amount columns, best first: the first one filled for every fund with an amount is used. */
export const COLUMNS = ["shares", "dollars", "percent"] as const;
export type Column = (typeof COLUMNS)[number];
const UNIT_OF: Record<Column, Unit> = { shares: "shares", dollars: "usd", percent: "pct" };

/** Percentage points two shares of a total may differ by before the columns are said to disagree. */
export const PERCENT_TOLERANCE_PP = 0.5;
/** The fraction of a fund's dollars its shares at the latest price may differ by. */
export const DOLLARS_TOLERANCE = 0.02;
const EPSILON = 1e-9; // 0.505 - 0.5 is a hair over 0.005 in doubles: a difference of exactly 0.5 points is within

export type FundLine = { ticker: string; shares: number | null; dollars: number | null; percent: number | null };
export type Parsed = { ok: true; lines: FundLine[] } | { ok: false; error: string };

type Cell = { ok: true; value: number | null } | { ok: false; reason: "number" | "negative" };

// digits with optional thousands commas, then an optional fraction; "1,00" and "1e3" are not numbers
const PLAIN_NUMBER = /^(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d+)?$/;

/** A cell as a number: `$`, `%`, thousands commas and spaces are allowed; blank is no amount. */
export function parseNumber(text: string): Cell {
  if (text.trim() === "") return { ok: true, value: null };
  let body = text.replace(/[$%\s]/g, "");
  let negative = false;
  if (/^\(.*\)$/.test(body)) {
    negative = true;
    body = body.slice(1, -1);
  }
  if (/^[-−]/.test(body)) {
    negative = true;
    body = body.slice(1);
  }
  if (!PLAIN_NUMBER.test(body) || !/\d/.test(body)) return { ok: false, reason: "number" };
  const value = Number(body.replace(/,/g, ""));
  if (!Number.isFinite(value)) return { ok: false, reason: "number" };
  return negative && value > 0 ? { ok: false, reason: "negative" } : { ok: true, value };
}

/** The delimiter of the header line: comma, tab or semicolon, whichever it holds most of (comma when none). */
function delimiterOf(text: string): string {
  const head = text.split(/\r?\n/).find((l) => l.trim() !== "") ?? "";
  const count = (d: string) => head.split(d).length - 1;
  return [",", "\t", ";"].reduce((best, d) => (count(d) > count(best) ? d : best));
}

const add = (a: number | null, b: number | null) => (a === null ? b : b === null ? a : a + b);

/**
 * The funds of a CSV file. The header names a `ticker` column and any of `shares`, `dollars` and
 * `percent` (case and surrounding spaces do not matter; other columns are ignored). A fund named
 * on two rows has its amounts added column by column. A number that is not one, or is negative,
 * or a row with more cells than the header, refuses the whole file and names the row (as the file
 * shows it, blank lines counted).
 */
export function parseFundsCsv(text: string): Parsed {
  const clean = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text; // a byte order mark, as Excel writes
  const read = Papa.parse<string[]>(clean, { delimiter: delimiterOf(clean), skipEmptyLines: false });
  if (read.errors.some((e) => e.type === "Quotes")) return { ok: false, error: uploadUnreadable };
  const [header = [], ...body] = read.data;

  const at = new Map<string, number>();
  for (const [i, name] of header.entries()) {
    const key = name.trim().toLowerCase();
    if (key !== "ticker" && !(COLUMNS as readonly string[]).includes(key)) continue;
    if (at.has(key)) return { ok: false, error: uploadTwoColumns(key) };
    at.set(key, i);
  }
  const tickerAt = at.get("ticker");
  if (tickerAt === undefined) return { ok: false, error: uploadNoTicker };

  const merged = new Map<string, FundLine>();
  for (const [i, cells] of body.entries()) {
    const row = i + 2; // the header is row 1
    if (cells.every((cell) => cell.trim() === "")) continue;
    // an unquoted 1,000 is two cells and would shift every column after it; a row may not outrun the header
    if (cells.length > header.length) return { ok: false, error: uploadTooManyValues(row) };
    const ticker = (cells[tickerAt] ?? "").trim().toUpperCase();
    const amounts: Record<Column, number | null> = { shares: null, dollars: null, percent: null };
    for (const column of COLUMNS) {
      const index = at.get(column);
      if (index === undefined) continue;
      const raw = cells[index] ?? "";
      const cell = parseNumber(raw);
      if (!cell.ok) return { ok: false, error: cell.reason === "negative" ? uploadNegative(row, ticker || "no ticker", column) : uploadBadNumber(row, ticker || "no ticker", column, raw.trim()) };
      amounts[column] = cell.value;
    }
    if (ticker === "") {
      if (COLUMNS.some((column) => amounts[column] !== null)) return { ok: false, error: uploadNoTickerOnRow(row) };
      continue;
    }
    const seen = merged.get(ticker);
    merged.set(ticker, {
      ticker,
      shares: add(seen?.shares ?? null, amounts.shares),
      dollars: add(seen?.dollars ?? null, amounts.dollars),
      percent: add(seen?.percent ?? null, amounts.percent),
    });
  }
  return merged.size === 0 ? { ok: false, error: uploadNoFunds } : { ok: true, lines: [...merged.values()] };
}

// ---------------------------------------------------------------- columns that disagree

/** The most funds the "who has what" sentence names. */
const NAMED_MAX = 6;

/** How many funds' share of the dollars differs from their share of the percent by more than 0.5 points. */
export function percentVsDollars(entries: { dollars: number; percent: number }[]): number {
  const dollars = entries.reduce((sum, e) => sum + e.dollars, 0);
  const percent = entries.reduce((sum, e) => sum + e.percent, 0);
  if (!(dollars > 0) || !(percent > 0)) return 0;
  return entries.filter((e) => Math.abs(e.dollars / dollars - e.percent / percent) * 100 > PERCENT_TOLERANCE_PP + EPSILON).length;
}

/** How many funds' shares at the latest price differ from their dollars by more than 2% of the dollars. Funds with no price are not compared. */
export function dollarsVsShares(entries: { shares: number; dollars: number; lastClose: number | null }[]): number {
  return entries.filter((e) => e.lastClose !== null && Math.abs(e.shares * e.lastClose - e.dollars) > DOLLARS_TOLERANCE * e.dollars + EPSILON).length;
}

/**
 * How many funds' share of the shares' value (at the latest price) differs from their share of the
 * percent by more than 0.5 points, over the funds that have a price.
 */
export function percentVsShares(entries: { shares: number; percent: number; lastClose: number | null }[]): number {
  const priced = entries.flatMap((e) => (e.lastClose === null ? [] : [{ value: e.shares * e.lastClose, percent: e.percent }]));
  const value = priced.reduce((sum, e) => sum + e.value, 0);
  const percent = priced.reduce((sum, e) => sum + e.percent, 0);
  if (!(value > 0) || !(percent > 0)) return 0;
  return priced.filter((e) => Math.abs(e.value / value - e.percent / percent) * 100 > PERCENT_TOLERANCE_PP + EPSILON).length;
}

/** A check that needs the new menu's prices: the shares of each fund against the other column's figure for it. */
export type PendingCheck = { against: "dollars" | "percent"; entries: { id: string; shares: number; value: number }[] };

/** The notes for the pending checks, once the new menu's funds (with their latest closes) are known. */
export function settlePending(pending: PendingCheck[], funds: { id: string; last_close?: number | null }[]): string[] {
  const close = new Map(funds.map((f) => [f.id, f.last_close ?? null]));
  const notes: string[] = [];
  for (const check of pending) {
    const entries = check.entries.map((e) => ({ shares: e.shares, value: e.value, lastClose: close.get(e.id) ?? null }));
    if (check.against === "dollars") {
      const n = dollarsVsShares(entries.map((e) => ({ shares: e.shares, dollars: e.value, lastClose: e.lastClose })));
      if (n > 0) notes.push(uploadMismatch.dollarsShares(n));
    } else {
      const n = percentVsShares(entries.map((e) => ({ shares: e.shares, percent: e.value, lastClose: e.lastClose })));
      if (n > 0) notes.push(uploadMismatch.percentShares(n));
    }
  }
  return notes;
}

// ---------------------------------------------------------------- the list the file makes

export type UploadPlan = {
  /** The served funds of the file, in file order, with their amounts in `unit`. */
  rows: Row[];
  /** The unit of the amounts, or null when no fund has one (the table's unit stays). */
  unit: Unit | null;
  /** Tickers of the file the catalog does not serve, once each, in file order. */
  skipped: string[];
  /** Notes about columns that were not used because they disagree with the one that was. */
  notes: string[];
  /** Checks that wait for the new menu's prices. */
  pending: PendingCheck[];
  /**
   * Price per share (the fund's dollars over its shares), by ticker, when shares are the unit and
   * every fund with shares has dollars: the shares are then valued at the file's own dollars.
   * Empty otherwise, and the shares are valued at the service's latest closes.
   */
  prices: Record<string, number>;
};
export type Resolution = { ok: true; plan: UploadPlan } | { ok: false; error: string; skipped: string[] };

const filled = (line: FundLine, column: Column) => line[column] !== null;

function whoHasWhat(withAmount: FundLine[]): string {
  const count = (column: Column) => withAmount.filter((l) => filled(l, column)).length;
  const commonest = COLUMNS.reduce((best, column) => (count(column) > count(best) ? column : best));
  const describe = (l: FundLine) => {
    const has = COLUMNS.filter((column) => filled(l, column));
    return has.length === COLUMNS.length ? `${l.ticker} has ${has.slice(0, -1).join(", ")} and ${has[has.length - 1]}` : `${l.ticker} has only ${has.join(" and ")}`;
  };
  // A long file names the funds that lack the column most of them have, those first.
  const ordered = withAmount.length <= NAMED_MAX ? withAmount : [...withAmount.filter((l) => !filled(l, commonest)), ...withAmount.filter((l) => filled(l, commonest))];
  const named = ordered.slice(0, NAMED_MAX).map(describe);
  const rest = withAmount.length - named.length;
  return rest > 0 ? `${named.join("; ")}; and ${rest} more.` : `${named.join("; ")}.`;
}

/**
 * The table a file makes. Tickers the catalog does not serve are skipped (and listed). Of the
 * served funds that have any amount, the best column filled for all of them is used (shares, then
 * dollars, then percent); funds with only a ticker load without an amount. When shares are used and
 * every fund with shares also has dollars, the dollars give each fund's price (`prices`). A file with fewer than
 * `limits.min` or more than `limits.max` served funds, or whose funds with amounts share no column,
 * is refused whole, and what it skipped is still reported.
 */
export function resolveUpload(lines: FundLine[], catalog: ReadonlyArray<{ id: string; name?: string | null }>, limits: { min: number; max: number }): Resolution {
  const names = new Map(catalog.map((s) => [s.id, s.name ?? s.id]));
  const served = lines.filter((l) => names.has(l.ticker));
  const skipped = lines.filter((l) => !names.has(l.ticker)).map((l) => l.ticker);
  const refuse = (error: string): Resolution => ({ ok: false, error, skipped });
  if (served.length < limits.min) return refuse(menuNeedsMore(limits.min));
  if (served.length > limits.max) return refuse(menuFull(limits.max));

  const withAmount = served.filter((l) => COLUMNS.some((column) => filled(l, column)));
  const chosen = withAmount.length === 0 ? null : (COLUMNS.find((column) => withAmount.every((l) => filled(l, column))) ?? null);
  if (withAmount.length > 0 && chosen === null) return refuse(uploadNoCommonColumn(whoHasWhat(withAmount)));

  const rows = served.map((l): Row => ({ id: l.ticker, name: names.get(l.ticker) ?? l.ticker, amount: chosen === null ? null : l[chosen] }));
  const notes: string[] = [];
  const pending: PendingCheck[] = [];
  const held = chosen === "shares" ? withAmount.filter((l) => (l.shares ?? 0) > 0) : [];
  const dollarsPrice = held.length > 0 && held.every((l) => (l.dollars ?? 0) > 0);
  const prices: Record<string, number> = dollarsPrice ? Object.fromEntries(held.map((l) => [l.ticker, (l.dollars as number) / (l.shares as number)])) : {};
  if (chosen === "dollars" || dollarsPrice) {
    const both = withAmount.flatMap((l) => (l.dollars !== null && l.percent !== null ? [{ dollars: l.dollars, percent: l.percent }] : []));
    const n = percentVsDollars(both);
    if (n > 0) notes.push(uploadMismatch.percentDollars(n));
  } else if (chosen === "shares") {
    for (const against of ["dollars", "percent"] as const) {
      const entries = withAmount.flatMap((l) => (l.shares !== null && l[against] !== null ? [{ id: l.ticker, shares: l.shares, value: l[against] as number }] : []));
      if (entries.length > 0) pending.push({ against, entries });
    }
  }
  return { ok: true, plan: { rows, unit: chosen === null ? null : UNIT_OF[chosen], skipped, notes, pending, prices } };
}
