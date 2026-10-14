// Amounts to weights in the three units, the 100% rule and trade deltas (spec 3.3).
import { describe, expect, it } from "vitest";
import { amountsToWeights, percentTotal, tradeDeltas } from "../src/math/amounts";

const CLOSES = [100, 200, 50];
const sum = (a: number[]) => a.reduce((acc, v) => acc + v, 0);

describe("amountsToWeights", () => {
  it("values share quantities at the last close", () => {
    expect(amountsToWeights([10, 5, null], "shares", CLOSES)).toEqual({ status: "ok", weights: [0.5, 0.5, 0], unknownPrice: [] });
    expect(amountsToWeights([1, 1, 1], "shares", CLOSES).weights).toEqual([100 / 350, 200 / 350, 50 / 350]);
  });

  it("divides dollar amounts and percentages by their total", () => {
    expect(amountsToWeights([300, null, 100], "usd", CLOSES)).toEqual({ status: "ok", weights: [0.75, 0, 0.25], unknownPrice: [] });
    expect(amountsToWeights([60, 40, null], "pct", CLOSES).weights).toEqual([0.6, 0.4, 0]);
    // 99.98% is inside the band: the weights are shares of the total entered and still sum to 1
    const near = amountsToWeights([59.98, 40, 0], "pct", CLOSES);
    expect(near.status).toBe("ok");
    expect(near.weights?.[0]).toBeCloseTo(59.98 / 99.98, 15);
    expect(sum(near.weights as number[])).toBeCloseTo(1, 15);
  });

  it("reads the same numbers differently in each unit", () => {
    const amounts = [10, 10, null];
    expect(amountsToWeights(amounts, "usd", CLOSES).weights).toEqual([0.5, 0.5, 0]);
    expect(amountsToWeights(amounts, "shares", CLOSES).weights).toEqual([1000 / 3000, 2000 / 3000, 0]);
    expect(amountsToWeights(amounts, "pct", CLOSES).status).toBe("invalid_total");
  });

  it("has no allocation when nothing is entered, in every unit", () => {
    for (const unit of ["shares", "pct", "usd"] as const) {
      expect(amountsToWeights([null, null, null], unit, CLOSES), unit).toEqual({ status: "empty", weights: null, unknownPrice: [] });
      expect(amountsToWeights([], unit, []), unit).toEqual({ status: "empty", weights: null, unknownPrice: [] });
    }
    // amounts that add up to nothing are no allocation either, never a division by zero
    expect(amountsToWeights([0, null, 0], "usd", CLOSES)).toEqual({ status: "empty", weights: null, unknownPrice: [] });
    expect(amountsToWeights([0, 0, 0], "shares", CLOSES)).toEqual({ status: "empty", weights: null, unknownPrice: [] });
    expect(amountsToWeights([0, 0, 0], "pct", CLOSES).status).toBe("invalid_total");
    expect(amountsToWeights([null, 5, null], "usd", CLOSES).weights).toEqual([0, 1, 0]);
  });

  it("accepts a percent total only within 100 +- 0.05", () => {
    const verdict = (total: number) => amountsToWeights([60, total - 60, null], "pct", CLOSES).status;
    expect([99.9, 99.94, 100.06, 100.1].map(verdict)).toEqual(["invalid_total", "invalid_total", "invalid_total", "invalid_total"]);
    expect([99.96, 100, 100.04].map(verdict)).toEqual(["ok", "ok", "ok"]);
    expect(amountsToWeights([60, 39.9, null], "pct", CLOSES)).toEqual({ status: "invalid_total", weights: null, unknownPrice: [] });
  });

  it("cannot value shares of a fund without a last close, and says which", () => {
    const closes = [100, null, 50, null];
    expect(amountsToWeights([10, 10, 10, 2], "shares", closes)).toEqual({ status: "unknown_price", weights: null, unknownPrice: [1, 3] });
    // dollars need no price
    expect(amountsToWeights([10, 10, 10, 2], "usd", closes).status).toBe("ok");
    // a fund that is not held needs none either
    expect(amountsToWeights([10, null, 10, 0], "shares", closes)).toEqual({ status: "ok", weights: [1000 / 1500, 0, 500 / 1500, 0], unknownPrice: [] });
  });
});

describe("percentTotal", () => {
  it("reads the running total and what is left", () => {
    expect(percentTotal([60, 32, null])).toEqual({ total: 92, ok: false, message: "Adds up to 92%: 8% to go" });
    expect(percentTotal([25, 12.5]).message).toBe("Adds up to 37.5%: 62.5% to go");
    expect(percentTotal([null, null]).message).toBe("Adds up to 0%: 100% to go");
  });

  it("prints sums without floating-point noise or trailing zeros", () => {
    expect(0.1 + 0.2).not.toBe(0.3);
    expect(percentTotal([60, 39.9]).message).toBe("Adds up to 99.9%: 0.1% to go");
    expect(percentTotal([33.33, 33.33, 33.33]).message).toBe("Adds up to 99.99%: 0.01% to go");
    expect(percentTotal([0.1, 0.2]).message).toBe("Adds up to 0.3%: 99.7% to go");
  });

  it("says when the total is over, and when it is there", () => {
    expect(percentTotal([80, 43])).toEqual({ total: 123, ok: false, message: "Adds up to 123%: 23% over" });
    expect(percentTotal([60, 40])).toEqual({ total: 100, ok: true, message: "Adds up to 100%" });
    expect(percentTotal([60, 40.1]).message).toBe("Adds up to 100.1%: 0.1% over");
  });

  it("is ok exactly within 100 +- 0.05", () => {
    const ok = (total: number) => percentTotal([60, total - 60]).ok;
    expect([99.9, 99.94, 99.96, 100, 100.04, 100.06, 100.1].map(ok)).toEqual([false, false, true, true, true, false, false]);
    expect(percentTotal([60, 39.96]).message).toBe("Adds up to 99.96%: 0.04% to go");
  });

  it("keeps the edges of the band in, whatever the floating-point sum does", () => {
    // 49.98 + 49.97 is 99.94999999999999 and 3 * 33.35 is 100.05000000000001 in doubles
    expect(Math.abs(49.98 + 49.97 - 100)).toBeGreaterThan(0.05);
    expect(percentTotal([49.98, 49.97])).toEqual({ total: 49.98 + 49.97, ok: true, message: "Adds up to 99.95%: 0.05% to go" });
    expect(percentTotal([33.35, 33.35, 33.35])).toMatchObject({ ok: true, message: "Adds up to 100.05%: 0.05% over" });
    expect(amountsToWeights([49.98, 49.97], "pct", [1, 1]).status).toBe("ok");
    expect(percentTotal([49.98, 49.96]).ok).toBe(false);
    expect(percentTotal([50.02, 50.04]).ok).toBe(false);
  });
});

describe("tradeDeltas", () => {
  const wSel = [0.4, 0.6, 0];

  it("gives percentage points, dollars and whole shares in Shares mode", () => {
    const amounts = [10, 10, 10];
    const lastClose = [100, 50, 50];
    const wNow = amountsToWeights(amounts, "shares", lastClose).weights as number[];
    expect(wNow).toEqual([0.5, 0.25, 0.25]);
    const d = tradeDeltas({ wNow, wSel, unit: "shares", amounts, lastClose });
    expect(d.value).toBe(2000);
    expect(d.rows.map((row) => row.dpp)).toEqual([expect.closeTo(-0.1, 15), expect.closeTo(0.35, 15), -0.25]);
    expect(d.rows.map((row) => row.dUsd)).toEqual([expect.closeTo(-200, 10), expect.closeTo(700, 10), -500]);
    expect(d.rows.map((row) => row.dShares)).toEqual([-2, 14, -10]);
    expect(d.rows.every((row) => row.unknownPrice === false)).toBe(true);
    expect(d.turnover).toBeCloseTo(0.35, 15);
  });

  it("rounds share trades to the nearest whole share", () => {
    const d = tradeDeltas({ wNow: [0.5, 0.5], wSel: [0.513, 0.487], unit: "shares", amounts: [10, 10], lastClose: [30, 30] });
    // 1.3% of $600 is $7.80: a quarter of a share, which is no trade
    expect(d.rows.map((row) => row.dShares)).toEqual([0, 0]);
    const bigger = tradeDeltas({ wNow: [0.5, 0.5], wSel: [0.58, 0.42], unit: "shares", amounts: [10, 10], lastClose: [30, 30] });
    expect(bigger.rows.map((row) => row.dShares)).toEqual([2, -2]);
    expect(bigger.rows[0].dUsd).toBeCloseTo(48, 10);
  });

  it("gives dollars but no shares in $ mode", () => {
    const amounts = [500, null, 1500];
    const wNow = amountsToWeights(amounts, "usd", CLOSES).weights as number[];
    const d = tradeDeltas({ wNow, wSel, unit: "usd", amounts, lastClose: CLOSES });
    expect(d.value).toBe(2000);
    expect(d.rows.map((row) => row.dUsd)).toEqual([expect.closeTo(300, 10), expect.closeTo(1200, 10), -1500]);
    expect(d.rows.map((row) => row.dShares)).toEqual([null, null, null]);
    expect(d.turnover).toBeCloseTo(0.75, 15);
  });

  it("gives percentage points only in % mode", () => {
    const d = tradeDeltas({ wNow: [0.6, 0.4, 0], wSel, unit: "pct", amounts: [60, 40, null], lastClose: CLOSES });
    expect(d.value).toBeNull();
    expect(d.rows).toEqual([
      { dpp: expect.closeTo(-0.2, 15), dUsd: null, dShares: null, unknownPrice: false },
      { dpp: expect.closeTo(0.2, 15), dUsd: null, dShares: null, unknownPrice: false },
      { dpp: 0, dUsd: null, dShares: null, unknownPrice: false },
    ]);
    expect(d.turnover).toBeCloseTo(0.2, 15);
  });

  it("counts turnover one way: buys only, which equal the sells", () => {
    const wNow = [0.1, 0.2, 0.3, 0.4];
    const to = [0.4, 0.3, 0.2, 0.1];
    const d = tradeDeltas({ wNow, wSel: to, unit: "pct", amounts: [10, 20, 30, 40], lastClose: [1, 1, 1, 1] });
    expect(d.turnover).toBeCloseTo(0.4, 15);
    expect(d.turnover).toBeCloseTo(sum(d.rows.map((row) => Math.abs(row.dpp))) / 2, 15);
    expect(tradeDeltas({ wNow, wSel: wNow, unit: "pct", amounts: [10, 20, 30, 40], lastClose: [1, 1, 1, 1] }).turnover).toBe(0);
  });

  it("has no share number for a fund without a last close", () => {
    const amounts = [10, null, 10];
    const lastClose = [100, null, 100];
    const wNow = amountsToWeights(amounts, "shares", lastClose).weights as number[];
    const d = tradeDeltas({ wNow, wSel: [0.25, 0.5, 0.25], unit: "shares", amounts, lastClose });
    expect(d.value).toBe(2000);
    expect(d.rows[1]).toEqual({ dpp: 0.5, dUsd: 1000, dShares: null, unknownPrice: true });
    expect(d.rows[0]).toEqual({ dpp: -0.25, dUsd: -500, dShares: -5, unknownPrice: false });
    // in dollars the price is not needed, so nothing is unknown
    const usd = tradeDeltas({ wNow, wSel: [0.25, 0.5, 0.25], unit: "usd", amounts: [1000, null, 1000], lastClose });
    expect(usd.rows[1]).toEqual({ dpp: 0.5, dUsd: 1000, dShares: null, unknownPrice: false });
  });
});
