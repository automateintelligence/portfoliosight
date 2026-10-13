// Amounts typed into the Funds table become the current mix, and the way from it to the selected
// mix becomes trades (spec 3.3). Arrays are in `universe.funds` order; a blank amount is `null`.

export type Unit = "shares" | "pct" | "usd";
export type Amount = number | null;
export type Price = number | null;

export type Allocation =
  | { status: "ok"; weights: number[]; unknownPrice: number[] }
  | { status: "empty" | "invalid_total" | "unknown_price"; weights: null; unknownPrice: number[] };

export type TradeRow = { dpp: number; dUsd: number | null; dShares: number | null; unknownPrice: boolean };
export type Trades = { rows: TradeRow[]; turnover: number; value: number | null };

const PERCENT_BAND = 0.05;
const SUM_NOISE = 1e-9; // 49.98 + 49.97 is 99.94999999999999 in doubles and still reads 99.95

const sum = (xs: number[]) => xs.reduce((acc, x) => acc + x, 0);
const cents = (x: number) => Math.round(x * 100) / 100;

/** What each fund's amount is worth: shares at the last close, percentages and dollars as entered. */
const worth = (amounts: Amount[], unit: Unit, lastClose: Price[]) =>
  amounts.map((amount, i) => (amount ?? 0) * (unit === "shares" ? (lastClose[i] ?? 0) : 1));

/**
 * The running total of percentages. `ok` is true exactly within 100 +- 0.05; `message` reads the
 * total and what is left ("Adds up to 92%: 8% to go"), to two decimals without trailing zeros.
 */
export function percentTotal(amounts: Amount[]): { total: number; ok: boolean; message: string } {
  const total = sum(amounts.map((amount) => amount ?? 0));
  const shown = cents(total);
  const gap = cents(Math.abs(100 - shown));
  const rest = shown < 100 ? `: ${gap}% to go` : shown > 100 ? `: ${gap}% over` : "";
  return { total, ok: Math.abs(total - 100) <= PERCENT_BAND + SUM_NOISE, message: `Adds up to ${shown}%${rest}` };
}

/**
 * The current mix from entered amounts. `empty`: nothing entered, or it adds up to nothing.
 * `invalid_total`: percentages outside 100 +- 0.05. `unknown_price`: shares of a fund without a
 * last close, whose indices are in `unknownPrice`. Otherwise `ok` with weights summing to 1.
 */
export function amountsToWeights(amounts: Amount[], unit: Unit, lastClose: Price[]): Allocation {
  const none = (status: "empty" | "invalid_total"): Allocation => ({ status, weights: null, unknownPrice: [] });
  if (amounts.every((amount) => amount === null)) return none("empty");
  if (unit === "pct" && !percentTotal(amounts).ok) return none("invalid_total");
  const unknownPrice = unit === "shares" ? amounts.flatMap((amount, i) => ((amount ?? 0) > 0 && (lastClose[i] ?? null) === null ? [i] : [])) : [];
  if (unknownPrice.length > 0) return { status: "unknown_price", weights: null, unknownPrice };
  const values = worth(amounts, unit, lastClose);
  const total = sum(values);
  if (!(total > 0)) return none("empty");
  return { status: "ok", weights: values.map((value) => value / total), unknownPrice: [] };
}

/**
 * Moves from the mix entered (`wNow`) to the selected mix (`wSel`). Per fund: `dpp` the change as
 * a fraction of the portfolio, `dUsd = dpp * value` (not in % mode), `dShares` whole shares (Shares
 * mode only; `null` with `unknownPrice` for a fund without a last close). `value` is the
 * portfolio's worth (`null` in % mode) and `turnover` the one-way total, `sum(max(dpp, 0))`.
 */
export function tradeDeltas(input: { wNow: ArrayLike<number>; wSel: ArrayLike<number>; unit: Unit; amounts: Amount[]; lastClose: Price[] }): Trades {
  const { wNow, wSel, unit, amounts, lastClose } = input;
  const value = unit === "pct" ? null : sum(worth(amounts, unit, lastClose));
  const rows = Array.from(wSel, (selected, i): TradeRow => {
    const dpp = selected - wNow[i];
    const dUsd = value === null ? null : dpp * value;
    const close = lastClose[i] ?? null;
    // `+ 0` turns a rounded -0 into 0
    const dShares = unit === "shares" && dUsd !== null && close !== null ? Math.round(dUsd / close) + 0 : null;
    return { dpp, dUsd, dShares, unknownPrice: unit === "shares" && close === null };
  });
  return { rows, turnover: sum(rows.map((row) => Math.max(row.dpp, 0))), value };
}
