// The view in the address (spec 8.1): ten query keys, written in one canonical order.
// `decode` reads those keys and nothing else, and keeps a value only if it has the key's shape.
// This file imports nothing and touches no browser object when loaded: the Worker and plain-node
// tests import it too.

export const LOOKBACKS = ["1y", "2y", "3y", "5y", "10y", "ew"] as const;
export type Lookback = (typeof LOOKBACKS)[number];

const PRESETS = ["guide2017", "tsp"] as const;
const UNITS = ["pct", "usd", "shares"] as const;
const THEMES = ["ks-dark", "light", "hud", "grid"] as const;
/** The simulation engines (engines spec 4); `replay` is the default and is never written to the address. */
export const ENGINES = ["replay", "garch", "copula"] as const;
export type EngineId = (typeof ENGINES)[number];

export type UrlState = {
  /** `u`; `null` is a custom menu. */
  preset: (typeof PRESETS)[number] | null;
  /** `f` as `ID:amount`, the amount optional; always `[]` with a preset. */
  funds: { id: string; amount: number | null }[];
  /** `unit`; left out of the address when `pct`. */
  unit: (typeof UNITS)[number];
  /** `c` as `ID:min:max` in whole percent; blank is `null`, the default rule. */
  caps: { id: string; min: number | null; max: number | null }[];
  /** `lb`; always written. */
  lookback: Lookback;
  /** `g`. */
  ghosts: Lookback[];
  /** `r`, the risk position `s`; `null` when the address has none. */
  r: number | null;
  /** `d`, the diversification position in [0, 1]; always written. */
  d: "auto" | number;
  /** `t`; `null` when the address has none, so the stored preference applies. */
  theme: (typeof THEMES)[number] | null;
  /** `x=1`. */
  details: boolean;
};

type Domain = { s_safe: number; s_max: number };

const DECIMAL = /^-?(\d+\.?\d*|\.\d+)$/;
const WHOLE_PERCENT = /^(\d{1,2}|100)$/;

const oneOf = <T extends string>(allowed: readonly T[], value: string | null): T | null => allowed.find((item) => item === value) ?? null;
const readDecimal = (text: string | null | undefined): number | null => (typeof text === "string" && DECIMAL.test(text) ? Number(text) : null);
const readPercent = (text: string | undefined): number | null => (text !== undefined && WHOLE_PERCENT.test(text) ? Number(text) : null);
const list = (value: string | null): string[] => (value ?? "").split(",").map((item) => item.trim()).filter((item) => item !== "");
/** `[ID, field, field]` of one `ID:field:field` item, or nothing when the id is blank. */
const fields = (item: string): string[][] => {
  const [id, ...rest] = item.split(":");
  return id.trim() === "" ? [] : [[id.trim().toUpperCase(), ...rest]];
};
/** A plain decimal with six places at most: no exponent, no trailing zeros. */
const writeDecimal = (x: number): string => String(Number(x.toFixed(6)));

/** Reads the query string into a state; with `domain`, `r` is clamped into it. */
export function decode(search: string, domain?: Domain): UrlState {
  const params = new URLSearchParams(search);
  const preset = oneOf(PRESETS, params.get("u"));
  const d = readDecimal(params.get("d"));
  const state: UrlState = {
    preset,
    funds: preset
      ? []
      : list(params.get("f")).flatMap(fields).map(([id, amount]) => {
          const value = readDecimal(amount);
          return { id, amount: value !== null && value >= 0 ? value : null };
        }),
    unit: oneOf(UNITS, params.get("unit")) ?? "pct",
    caps: list(params.get("c")).flatMap(fields).map(([id, min, max]) => ({ id, min: readPercent(min), max: readPercent(max) })),
    lookback: oneOf(LOOKBACKS, params.get("lb")) ?? "5y",
    ghosts: [...new Set(list(params.get("g")))].flatMap((id) => oneOf(LOOKBACKS, id) ?? []),
    r: readDecimal(params.get("r")),
    d: d === null ? "auto" : Math.min(Math.max(d, 0), 1),
    theme: oneOf(THEMES, params.get("t")),
    details: params.get("x") === "1",
  };
  return domain ? clampR(state, domain) : state;
}

/** The query string of a state, with its leading `?`, in the order `u f unit c lb g r d t x`. */
export function encode(state: UrlState): string {
  const id = encodeURIComponent;
  const pairs: string[] = [];
  if (state.preset) pairs.push(`u=${state.preset}`);
  else if (state.funds.length > 0) pairs.push(`f=${state.funds.map((fund) => id(fund.id) + (fund.amount === null ? "" : `:${writeDecimal(fund.amount)}`)).join(",")}`);
  if (state.unit !== "pct") pairs.push(`unit=${state.unit}`);
  if (state.caps.length > 0) pairs.push(`c=${state.caps.map((cap) => `${id(cap.id)}:${cap.min ?? ""}:${cap.max ?? ""}`).join(",")}`);
  pairs.push(`lb=${state.lookback}`);
  if (state.ghosts.length > 0) pairs.push(`g=${state.ghosts.join(",")}`);
  if (state.r !== null) pairs.push(`r=${writeDecimal(state.r)}`);
  pairs.push(`d=${state.d === "auto" ? "auto" : writeDecimal(state.d)}`);
  if (state.theme) pairs.push(`t=${state.theme}`);
  if (state.details) pairs.push("x=1");
  return `?${pairs.join("&")}`;
}

/** `state` with `r` moved into `[s_safe, s_max]`; the same object when `r` is unset or already inside. */
export function clampR(state: UrlState, domain: Domain): UrlState {
  if (state.r === null) return state;
  const r = Math.min(Math.max(state.r, domain.s_safe), domain.s_max);
  return r === state.r ? state : { ...state, r };
}

const WRITE_DELAY_MS = 250;
let pending: ReturnType<typeof setTimeout> | undefined;

type Page = {
  history: { state: unknown; replaceState(data: unknown, unused: string, url: string): void };
  location: { pathname: string; hash?: string };
};

/** Puts `state` in the address now (`history.replaceState`) and drops any scheduled write. */
export function writeUrl(state: UrlState): void {
  clearTimeout(pending);
  pending = undefined;
  const { history, location } = globalThis as unknown as Page;
  history.replaceState(history.state, "", `${location.pathname}${encode(state)}${location.hash ?? ""}`);
}

/** Puts `state` in the address 250 ms after the last call, so a drag writes once. */
export function scheduleUrlWrite(state: UrlState): void {
  clearTimeout(pending);
  pending = setTimeout(() => writeUrl(state), WRITE_DELAY_MS);
}
