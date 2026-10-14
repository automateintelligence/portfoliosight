// Number formatting for the page. A real minus sign (U+2212) is used so figures align in mono.

const MINUS = "−";

/** Signed percent with one decimal: 0.0314 -> "+3.1%", -0.094 -> "−9.4%". */
export function signedPct(fraction: number, digits = 1): string {
  const v = fraction * 100;
  const rounded = Number(v.toFixed(digits));
  const body = Math.abs(rounded).toFixed(digits);
  if (rounded === 0) return `${body}%`;
  return `${rounded < 0 ? MINUS : "+"}${body}%`;
}

/** Unsigned percent: 0.25 -> "25%", 0.1364 -> "13.6%". */
export function pct(fraction: number, digits = 1): string {
  const v = fraction * 100;
  const text = v.toFixed(digits);
  return `${text.replace("-", MINUS)}%`;
}

/** Percent without trailing zeros, for inputs and the cap sentence: 0.25 -> "25", 0.136 -> "13.6". */
export function pctPlain(fraction: number, digits = 1): string {
  return String(Number((fraction * 100).toFixed(digits)));
}

export function money(value: number): string {
  const sign = value < 0 ? MINUS : "";
  return `${sign}$${Math.abs(value).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function signedMoney(value: number): string {
  const rounded = Math.round(value);
  if (rounded === 0) return "$0";
  return `${rounded < 0 ? MINUS : "+"}$${Math.abs(rounded).toLocaleString("en-US")}`;
}

export function signedInt(value: number): string {
  if (value === 0) return "0";
  return `${value < 0 ? MINUS : "+"}${Math.abs(value).toLocaleString("en-US")}`;
}

/** Percentage points with a sign: 0.031 -> "+3.1 pp". */
export function signedPp(fraction: number): string {
  const rounded = Number((fraction * 100).toFixed(1));
  if (rounded === 0) return "0.0 pp";
  return `${rounded < 0 ? MINUS : "+"}${Math.abs(rounded).toFixed(1)} pp`;
}

/** Amount as typed into a field: plain digits, up to two decimals, blank for null. */
export function amountText(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "";
  return String(Number(value.toFixed(2)));
}

/** Parses "$10,840.50" / "10840" / "" -> number | null (null for blank or not a number). */
export function parseAmount(text: string): number | null {
  const cleaned = text.replace(/[$,%\s]/g, "");
  if (cleaned === "") return null;
  const value = Number(cleaned);
  return Number.isFinite(value) && value >= 0 ? value : null;
}
