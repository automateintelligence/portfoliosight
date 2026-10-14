import { describe, expect, it } from "vitest";
import { percentShown, scaleTo100 } from "../src/math/amounts";

// Hundredths, as the amount fields show them.
const hundredths = (xs: (number | null)[]) => xs.reduce<number>((acc, x) => acc + Math.round((x ?? 0) * 100), 0);

describe("Scale to 100%", () => {
  it("sums to exactly 100 at the fields' precision, whatever the entries", () => {
    const cases: (number | null)[][] = [
      [1, 1, 1],
      [60, 32],
      [33.33, 33.33, 33.33],
      [10, 20, 30, 41.5],
      [7, 7, 7, 7, 7, 7, 7],
      [0.01, 0.01, 0.01],
      [1e-6, 2e-6, 3e-6],
      [123456, 1, 0.5],
      [50.005, 50.005],
    ];
    for (const amounts of cases) {
      const out = scaleTo100(amounts);
      expect(hundredths(out), JSON.stringify(amounts)).toBe(10000);
      for (const v of out) if (v !== null) expect(Math.round(v * 100), `${v} is on the fields' step`).toBeCloseTo(v * 100, 9);
    }
  });

  it("is proportional: each entry lands within one hundredth of its exact share", () => {
    const amounts = [12.5, 30, 7.25, 50.1, 3];
    const total = amounts.reduce((a, b) => a + b, 0);
    const out = scaleTo100(amounts);
    amounts.forEach((a, i) => expect(Math.abs(out[i]! - (a / total) * 100)).toBeLessThan(0.01 + 1e-9));
    // and the order of the entries is kept
    const rank = (xs: number[]) => xs.map((_, i) => i).sort((a, b) => xs[a] - xs[b]);
    expect(rank(out as number[])).toEqual(rank(amounts));
  });

  it("hands the leftover hundredths to the largest remainders", () => {
    expect(scaleTo100([1, 1, 1])).toEqual([33.34, 33.33, 33.33]);
    expect(scaleTo100([2, 1, 1])).toEqual([50, 25, 25]);
    expect(scaleTo100([1, 2])).toEqual([33.33, 66.67]);
    expect(scaleTo100([60, 32])).toEqual([65.22, 34.78]);
  });

  it("keeps zeros at zero and blanks blank", () => {
    expect(scaleTo100([0, 30, null, 10, 0])).toEqual([0, 75, null, 25, 0]);
    const many = scaleTo100([1, 0, 1, 0, 1, null]);
    expect(many[1]).toBe(0);
    expect(many[3]).toBe(0);
    expect(many[5]).toBeNull();
    expect(hundredths(many)).toBe(10000);
  });

  it("a single entry becomes 100", () => {
    expect(scaleTo100([42])).toEqual([100]);
    expect(scaleTo100([null, 0.37, null])).toEqual([null, 100, null]);
  });

  it("entries already at 100 stay as they are", () => {
    expect(scaleTo100([60, 40])).toEqual([60, 40]);
    expect(scaleTo100([33.33, 33.33, 33.34])).toEqual([33.33, 33.33, 33.34]);
    expect(scaleTo100([0.5, 99.5])).toEqual([0.5, 99.5]);
  });

  it("tiny values still reach 100 and none of them is lost", () => {
    const out = scaleTo100([0.001, 0.002, 0.003, 0.004]);
    expect(out).toEqual([10, 20, 30, 40]);
    const odd = scaleTo100([1e-9, 3e-9]);
    expect(odd).toEqual([25, 75]);
  });

  it("entries that add up to nothing come back unchanged", () => {
    expect(scaleTo100([null, null])).toEqual([null, null]);
    expect(scaleTo100([0, 0, null])).toEqual([0, 0, null]);
  });
});

describe("the percentages as the fields show them", () => {
  it("reads the total to the hundredth and says when it is exactly 100", () => {
    expect(percentShown([60, 38.9])).toEqual({ total: 98.9, exact: false, entered: true });
    expect(percentShown([33.33, 33.33, 33.34])).toEqual({ total: 100, exact: true, entered: true });
    // 49.98 + 49.97 is 99.94999999999999 in doubles and the fields show 99.95
    expect(percentShown([49.98, 49.97, null])).toEqual({ total: 99.95, exact: false, entered: true });
    // inside the 100 +- 0.05 rule the mix is drawn, but it is not exactly 100
    expect(percentShown([99.97]).exact).toBe(false);
    expect(percentShown([100.004]).exact).toBe(true);
    expect(percentShown([null, null])).toEqual({ total: 0, exact: false, entered: false });
    expect(percentShown([0, 0]).entered).toBe(false);
  });
});

describe("the fields and the amounts agree on exactly 100", () => {
  it("rounds each entry the way its field shows it", () => {
    // 1.335 shows as 1.33 (toFixed), so the fields read 99.99: not exact
    expect(percentShown([1.335, 98.66])).toEqual({ total: 99.99, exact: false, entered: true });
  });

  it("is not exact when the fields read 100 but the amounts add up to more", () => {
    const twenty = Array.from({ length: 20 }, () => 5.004);
    const shown = percentShown(twenty);
    expect(shown.exact).toBe(false);
    expect(shown.total).toBe(100.08);
    // and Scale to 100% brings both to exactly 100
    const scaled = scaleTo100(twenty);
    expect(scaled.every((v) => v === 5)).toBe(true);
    expect(percentShown(scaled).exact).toBe(true);
  });
});
