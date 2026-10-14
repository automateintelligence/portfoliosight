// The Trades table as a CSV file, built and downloaded in the browser (nothing is sent anywhere).
import { tradeDeltas, type Unit } from "../math/amounts";

type Input = {
  funds: { id: string; last_close?: number | null }[];
  wNow: ArrayLike<number>;
  wSel: ArrayLike<number>;
  unit: Unit;
  /** Amounts in the funds' order. */
  amounts: (number | null)[];
};

const field = (value: string | number | null): string => {
  if (value === null) return "";
  const text = typeof value === "number" ? String(value) : value;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};
const round = (value: number, digits: number) => Number(value.toFixed(digits)) + 0;

/**
 * One row per fund with any non-zero figure (held now, held in the selected mix, or traded): fund, now %, selected %, change in
 * percentage points, then the change in dollars (dollar and share units) and in whole shares
 * (share unit). Plain numbers, a full stop as the decimal mark, CRLF line ends (RFC 4180).
 */
export function tradesCsv({ funds, wNow, wSel, unit, amounts }: Input): string {
  const { rows } = tradeDeltas({ wNow, wSel, unit, amounts, lastClose: funds.map((f) => f.last_close ?? null) });
  const head = ["Fund", "Now %", "Selected %", "Change (percentage points)"];
  if (unit !== "pct") head.push("Change ($)");
  if (unit === "shares") head.push("Change (shares)");
  const lines = [head.map(field).join(",")];
  funds.forEach((f, i) => {
    const cells: (string | number | null)[] = [f.id, round(wNow[i] * 100, 2), round(wSel[i] * 100, 2), round(rows[i].dpp * 100, 2)];
    if (unit !== "pct") cells.push(rows[i].dUsd === null ? null : round(rows[i].dUsd as number, 2));
    if (unit === "shares") cells.push(rows[i].dShares);
    // A fund is left out only when every figure of its row would read zero: a small holding of a
    // large portfolio is still a trade.
    if (cells.slice(1).every((cell) => cell === null || cell === 0)) return;
    lines.push(cells.map(field).join(","));
  });
  return `${lines.join("\r\n")}\r\n`;
}

/** "portfoliosight-trades-2026-10-12.csv": the date is the prices' date, so a file names its data. */
export const tradesFilename = (asof: string): string => `portfoliosight-trades-${/^\d{4}-\d{2}-\d{2}$/.test(asof) ? asof : "export"}.csv`;

/** Hands `text` to the browser as a file download. */
export function downloadCsv(text: string, filename: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
