// The Trades export: columns per unit, plain numbers, quoting and the filename.
import { describe, expect, it } from "vitest";
import { tradesCsv, tradesFilename } from "../src/sections/tradesCsv";

const funds = [
  { id: "AAA", last_close: 50 },
  { id: "BBB", last_close: 20 },
  { id: "CCC", last_close: null },
  { id: "DDD", last_close: 10 },
];
const wSel = [0.25, 0.75, 0, 0];
const rowsOf = (csv: string) => csv.trimEnd().split("\r\n").map((line) => line.split(","));

describe("tradesCsv", () => {
  it("writes fund, now %, selected % and the change in percentage points in percent mode", () => {
    const csv = tradesCsv({ funds, wNow: [0.5, 0.5, 0, 0], wSel, unit: "pct", amounts: [50, 50, null, null] });
    expect(rowsOf(csv)).toEqual([
      ["Fund", "Now %", "Selected %", "Change (percentage points)"],
      ["AAA", "50", "25", "-25"],
      ["BBB", "50", "75", "25"],
    ]);
    expect(csv.endsWith("\r\n")).toBe(true);
  });

  it("adds the dollar change in dollar mode", () => {
    const csv = tradesCsv({ funds, wNow: [0.5, 0.5, 0, 0], wSel, unit: "usd", amounts: [1000, 1000, null, null] });
    expect(rowsOf(csv)).toEqual([
      ["Fund", "Now %", "Selected %", "Change (percentage points)", "Change ($)"],
      ["AAA", "50", "25", "-25", "-500"],
      ["BBB", "50", "75", "25", "500"],
    ]);
  });

  it("adds dollars and whole shares in share mode, and leaves a fund without a price blank", () => {
    // 10 AAA at 50 and 25 BBB at 20: 500 each, 1000 in all.
    const csv = tradesCsv({ funds, wNow: [0.5, 0.5, 0, 0], wSel: [0.25, 0.65, 0.1, 0], unit: "shares", amounts: [10, 25, null, null] });
    expect(rowsOf(csv)).toEqual([
      ["Fund", "Now %", "Selected %", "Change (percentage points)", "Change ($)", "Change (shares)"],
      ["AAA", "50", "25", "-25", "-250", "-5"],
      ["BBB", "50", "65", "15", "150", "8"],
      ["CCC", "0", "10", "10", "100", ""],
    ]);
  });

  it("leaves out funds held in neither mix and rounds to two decimals", () => {
    const csv = tradesCsv({ funds, wNow: [1 / 3, 2 / 3, 0, 0], wSel: [0.5, 0.5, 0, 0], unit: "pct", amounts: [1, 2, null, null] });
    const rows = rowsOf(csv);
    expect(rows.map((r) => r[0])).toEqual(["Fund", "AAA", "BBB"]);
    expect(rows[1]).toEqual(["AAA", "33.33", "50", "16.67"]);
  });

  it("keeps a trade too small to show as a percentage when it is worth dollars", () => {
    // 0.04% of $1,000,000 moves from AAA into DDD: $400 each way.
    const csv = tradesCsv({ funds, wNow: [0.5, 0.5, 0, 0], wSel: [0.4996, 0.5, 0, 0.0004], unit: "usd", amounts: [500000, 500000, null, null] });
    const rows = rowsOf(csv);
    expect(rows.map((r) => r[0])).toEqual(["Fund", "AAA", "BBB", "DDD"]);
    expect(rows[1]).toEqual(["AAA", "50", "49.96", "-0.04", "-400"]);
    expect(rows[3]).toEqual(["DDD", "0", "0.04", "0.04", "400"]);
  });

  it("quotes a field that holds a comma or a quote", () => {
    const csv = tradesCsv({ funds: [{ id: 'A,"B' }, { id: "C" }], wNow: [0.5, 0.5], wSel: [0.5, 0.5], unit: "pct", amounts: [50, 50] });
    expect(csv.split("\r\n")[1]).toBe('"A,""B",50,50,0');
  });
});

describe("tradesFilename", () => {
  it("names the file after the prices' date", () => {
    expect(tradesFilename("2026-10-12")).toBe("portfoliosight-trades-2026-10-12.csv");
  });
  it("never puts an unexpected string in the name", () => {
    expect(tradesFilename("../../x")).toBe("portfoliosight-trades-export.csv");
  });
});
