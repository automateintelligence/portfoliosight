/**
 * The order of the Funds & amounts table (spec 3.3, owner direction 2026-11-11): the six "Sort by"
 * options as one pure comparison, and the choice kept in this browser. Names run A to Z, numbers
 * largest first, blanks last, and equal values keep the entered order.
 */

export const SORT_KEYS = ["entered", "ticker", "name", "amount", "mixEntered", "mixSelected"] as const;
export type SortKey = (typeof SORT_KEYS)[number];
export const DEFAULT_SORT: SortKey = "entered";

export type SortRow = { id: string; name: string; amount: number | null };
/** The two percentage columns by fund id; a fund missing from a map shows no figure there. */
export type SortMixes = { entered: ReadonlyMap<string, number>; selected: ReadonlyMap<string, number> };

const collator = new Intl.Collator("en-US", { sensitivity: "base", numeric: true });

/** The number as the screen shows it, so two values that read the same are a tie (amounts to 2 decimals, percentages to 1). */
const shownAmount = (v: number) => Number(v.toFixed(2));
const shownPercent = (v: number) => Number((v * 100).toFixed(1));

/** What one row is compared on: text, a number, or null for a blank (which goes last). */
type Cell = { text: string } | { num: number } | null;

function cell(row: SortRow, key: Exclude<SortKey, "entered">, mixes: SortMixes): Cell {
  switch (key) {
    case "ticker":
      return row.id.trim() === "" ? null : { text: row.id };
    case "name":
      return row.name.trim() === "" ? null : { text: row.name };
    case "amount":
      return row.amount === null || !Number.isFinite(row.amount) ? null : { num: shownAmount(row.amount) };
    case "mixEntered": {
      const v = mixes.entered.get(row.id);
      return v === undefined || !Number.isFinite(v) ? null : { num: shownPercent(v) };
    }
    case "mixSelected": {
      const v = mixes.selected.get(row.id);
      return v === undefined || !Number.isFinite(v) ? null : { num: shownPercent(v) };
    }
  }
}

function compare(a: Cell, b: Cell): number {
  if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
  if ("text" in a && "text" in b) return collator.compare(a.text, b.text);
  if ("num" in a && "num" in b) return b.num - a.num;
  return 0;
}

/** The rows in the order `key` asks for, as a new array; the rows given are not changed. */
export function sortFunds<T extends SortRow>(rows: readonly T[], key: SortKey, mixes: SortMixes): T[] {
  if (key === "entered") return [...rows];
  const keyed = rows.map((row, at) => ({ row, at, cell: cell(row, key, mixes) }));
  keyed.sort((x, y) => compare(x.cell, y.cell) || x.at - y.at);
  return keyed.map((k) => k.row);
}

export const SORT_STORAGE_KEY = "ps.fundsSort";

const isSortKey = (value: unknown): value is SortKey => (SORT_KEYS as readonly unknown[]).includes(value);

const browserStorage = (): Storage | null => {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
};

/** The choice kept in this browser; As entered when none is kept, when it is not an option, or when storage cannot be read. */
export function readSort(storage: Pick<Storage, "getItem"> | null = browserStorage()): SortKey {
  try {
    const stored = storage?.getItem(SORT_STORAGE_KEY);
    return isSortKey(stored) ? stored : DEFAULT_SORT;
  } catch {
    return DEFAULT_SORT;
  }
}

/** Keeps the choice in this browser; where storage is blocked or full the page simply starts on As entered next time. */
export function writeSort(key: SortKey, storage: Pick<Storage, "setItem"> | null = browserStorage()): void {
  try {
    storage?.setItem(SORT_STORAGE_KEY, key);
  } catch {
    // storage unavailable: the choice holds for this visit only
  }
}
