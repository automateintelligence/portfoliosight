import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";
import type { Tensor } from "../src/api/tensor";
import { portfolioMath } from "../src/math/portfolio";
import { STRIP_PAD, stripAt, stripScale, tensorBounds, widenBy, widenSeen } from "../src/math/stripScale";
import { deriveView } from "../src/math/view";

const RAW = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8"));
const T5 = parseTensor(RAW);

/** A copy of the fixture as another window (or menu) whose every range is moved by `shift`. */
function variant(lookback: string, shift: number, hash = T5.universe.hash): Tensor {
  const t = structuredClone(T5);
  const move = (xs: number[]) => xs.map((x) => x + shift);
  t.lookback = { ...t.lookback, id: lookback as Tensor["lookback"]["id"] };
  t.universe = { ...t.universe, hash };
  t.frontier.range = { ...t.frontier.range, bad: move(t.frontier.range.bad), good: move(t.frontier.range.good) };
  t.ladder.range = { ...t.ladder.range, bad: t.ladder.range.bad.map(move), good: t.ladder.range.good.map(move) };
  if (t.entered) t.entered = { ...t.entered, range: { ...t.entered.range, bad: t.entered.range.bad + shift, good: t.entered.range.good + shift } };
  return t;
}

describe("the strip's fixed scale", () => {
  it("bounds a tensor by the lowest Bad and highest Good of its frontier nodes, ladder nodes (peaks included) and entered mix", () => {
    const b = tensorBounds(T5);
    const bads = [...T5.frontier.range.bad, ...T5.ladder.range.bad.flat(), ...(T5.entered ? [T5.entered.range.bad] : [])];
    const goods = [...T5.frontier.range.good, ...T5.ladder.range.good.flat(), ...(T5.entered ? [T5.entered.range.good] : [])];
    expect(b.min).toBe(Math.min(...bads));
    expect(b.max).toBe(Math.max(...goods));
    // The top ladder level (the most diversified mix at each risk) is inside.
    const peaks = T5.ladder.range.good.map((col) => col[col.length - 1]);
    for (const g of peaks) expect(g).toBeLessThanOrEqual(b.max);
    // An entered mix beyond every node widens the bounds.
    const far = structuredClone(T5);
    far.entered = { w: T5.frontier.w[0], set_aside: 0, range: { bad: -0.9, typical: 0, good: 0.95, normal: { low: -0.5, mid: 0, high: 0.5 } } };
    expect(tensorBounds(far)).toEqual({ min: -0.9, max: 0.95 });
  });

  it("holds every mix the sliders can reach, so no marker leaves the bar", () => {
    const math = portfolioMath(T5);
    const scale = stripScale(tensorBounds(T5), []);
    const { s_safe, s_max } = math.riskSliderDomain();
    for (let i = 0; i <= 20; i++) {
      for (const t of [0, 0.25, 0.5, 0.75, 1]) {
        const v = deriveView(T5, math, s_safe + ((s_max - s_safe) * i) / 20, t);
        for (const x of [v.range.low, v.range.typical, v.range.high]) {
          expect(stripAt(scale, x)).toBeGreaterThan(0);
          expect(stripAt(scale, x)).toBeLessThan(1);
        }
      }
    }
  });

  it("keeps 0% on the bar and pads each end by a share of the span", () => {
    const s = stripScale({ min: 0.02, max: 0.3 }, []);
    const span = 0.3 - 0;
    expect(s.lo).toBeCloseTo(0 - span * STRIP_PAD, 12);
    expect(s.hi).toBeCloseTo(0.3 + span * STRIP_PAD, 12);
    const n = stripScale({ min: -0.4, max: -0.1 }, []);
    expect(n.hi).toBeGreaterThan(0);
    expect(stripAt(n, 0)).toBeLessThan(1);
    expect(stripAt(stripScale(null, []), 0)).toBeCloseTo(0.5, 12);
  });

  it("does not move with the shown values while they lie inside, and widens only for one outside", () => {
    const bounds = { min: -0.2, max: 0.35 };
    const a = stripScale(bounds, [-0.1, 0.05, 0.2]);
    const b = stripScale(bounds, [-0.18, 0.08, 0.33]);
    expect(a).toEqual(b);
    const c = stripScale(bounds, [-0.25, 0.05, 0.2]);
    expect(c.lo).toBeLessThan(a.lo);
    expect(c.hi).toBeCloseTo(a.hi + (0.05 * STRIP_PAD), 12);
  });

  it("widens over every window loaded for the menu, never narrows, and starts over for another menu", () => {
    const first = widenSeen(null, [T5]);
    expect(first?.bounds).toEqual(tensorBounds(T5));
    // the same tensor again: the very same object comes back
    expect(widenSeen(first, [T5])).toBe(first);
    expect(widenSeen(first, [])).toBe(first);
    // a ghost window reaching further widens; switching back to the 5y window keeps that width
    const wide = widenSeen(first, [T5, variant("1y", -0.1)]);
    expect(wide!.bounds.min).toBeCloseTo(tensorBounds(T5).min - 0.1, 12);
    expect(wide!.bounds.max).toBe(tensorBounds(T5).max);
    const back = widenSeen(wide, [T5]);
    expect(back).toBe(wide);
    const later = widenSeen(back, [variant("10y", 0.2)]);
    expect(later!.bounds.min).toBe(wide!.bounds.min);
    expect(later!.bounds.max).toBeCloseTo(tensorBounds(T5).max + 0.2, 12);
    // a narrower window changes nothing
    expect(widenSeen(later, [variant("3y", 0)])!.bounds).toEqual(later!.bounds);
    // another menu starts over, and a leftover tensor of the old menu is not counted
    const other = widenSeen(later, [variant("5y", 0.01, "ffffffffffffffff"), variant("2y", 5)]);
    expect(other!.hash).toBe("ffffffffffffffff");
    expect(other!.bounds.min).toBeCloseTo(tensorBounds(T5).min + 0.01, 12);
    expect(other!.bounds.max).toBeCloseTo(tensorBounds(T5).max + 0.01, 12);
  });
});

describe("figures shown outside the bounds", () => {
  it("widen what was seen and it stays widened", () => {
    const seen = widenSeen(null, [T5])!;
    expect(widenBy(seen, [seen.bounds.min + 0.01, seen.bounds.max - 0.01])).toBe(seen);
    const wider = widenBy(seen, [seen.bounds.min - 0.05, 0.1])!;
    expect(wider.bounds.min).toBeCloseTo(seen.bounds.min - 0.05, 12);
    expect(wider.bounds.max).toBe(seen.bounds.max);
    // a later figure inside, or the same tensor again, does not shrink it back
    expect(widenBy(widenSeen(wider, [T5]), [0])).toBe(wider);
    expect(widenBy(null, [1])).toBeNull();
  });
});
