/**
 * The picker's search over the served symbols (spec 3.3): which entries match what was typed, best
 * first. Groups, in order: (1) the ticker is the query, (2) the ticker starts with it, (3) a word of
 * the name starts with it, (4) the ticker contains it, (5) the name contains it. Within a group,
 * shorter tickers come first, then alphabetical order. Tickers are compared without case and
 * without punctuation or spaces ("brk b" finds BRK-B); names without case.
 */

export type Searchable = { id: string; name?: string | null };

export const PICKER_LIMIT = 8;

const tickerKey = (text: string) => text.toLowerCase().replace(/[^a-z0-9]/g, "");
const isWordChar = (ch: string) => /[\p{L}\p{N}]/u.test(ch);

/** True when ``query`` starts a word of ``name`` (both lower case). */
function startsAWord(name: string, query: string): boolean {
  for (let at = name.indexOf(query); at !== -1; at = name.indexOf(query, at + 1)) {
    if (at === 0 || !isWordChar(name[at - 1])) return true;
  }
  return false;
}

/** The group of one entry for the query (1 to 5), or 0 when it does not match. */
export function matchGroup(entry: Searchable, query: string): number {
  const q = query.trim().toLowerCase().replace(/\s+/g, " ");
  if (!q) return 0;
  const key = tickerKey(q);
  const ticker = tickerKey(entry.id);
  const name = (entry.name ?? "").toLowerCase();
  if (key && ticker === key) return 1;
  if (key && ticker.startsWith(key)) return 2;
  if (name && startsAWord(name, q)) return 3;
  if (key && ticker.includes(key)) return 4;
  if (name.includes(q)) return 5;
  return 0;
}

/** The entries matching ``query``, best first, at most ``limit`` of them. */
export function rankSymbols<T extends Searchable>(symbols: readonly T[], query: string, limit = PICKER_LIMIT): T[] {
  const ranked: { entry: T; group: number }[] = [];
  for (const entry of symbols) {
    const group = matchGroup(entry, query);
    if (group > 0) ranked.push({ entry, group });
  }
  ranked.sort((a, b) => a.group - b.group || a.entry.id.length - b.entry.id.length || (a.entry.id < b.entry.id ? -1 : a.entry.id > b.entry.id ? 1 : 0));
  return ranked.slice(0, limit).map((r) => r.entry);
}
