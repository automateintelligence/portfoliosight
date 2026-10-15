import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";
import type { Tensor } from "../src/api/tensor";
import { portfolioMath } from "../src/math/portfolio";
import { STRIP_PAD, stripAt, stripPlace, stripScale, tensorBounds } from "../src/math/stripScale";
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
    const scale = stripScale(tensorBounds(T5));
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
    const s = stripScale({ min: 0.02, max: 0.3 });
    const span = 0.3 - 0;
    expect(s.lo).toBeCloseTo(0 - span * STRIP_PAD, 12);
    expect(s.hi).toBeCloseTo(0.3 + span * STRIP_PAD, 12);
    const n = stripScale({ min: -0.4, max: -0.1 });
    expect(n.hi).toBeGreaterThan(0);
    expect(stripAt(n, 0)).toBeLessThan(1);
    expect(stripAt(stripScale(null), 0)).toBeCloseTo(0.5, 12);
  });

  it("is the tensor's own: another window or menu gives another scale only through its own nodes", () => {
    const own = stripScale(tensorBounds(T5));
    // the same nodes under another window or menu name: the same scale
    expect(stripScale(tensorBounds(variant("1y", 0)))).toEqual(own);
    expect(stripScale(tensorBounds(variant("5y", 0, "ffffffffffffffff")))).toEqual(own);
    // a window whose nodes reach further has its own, wider scale
    const wide = stripScale(tensorBounds(variant("1y", -0.1)));
    expect(wide.lo).toBeLessThan(own.lo);
  });
});

describe("a figure outside the scale", () => {
  it("is drawn at the end it runs past, with which end it passed", () => {
    const s = stripScale({ min: -0.2, max: 0.35 });
    expect(stripPlace(s, 0.1)).toEqual({ at: stripAt(s, 0.1), over: null });
    expect(stripPlace(s, s.lo - 0.01)).toEqual({ at: 0, over: "low" });
    expect(stripPlace(s, s.hi + 0.01)).toEqual({ at: 1, over: "high" });
    expect(stripPlace(s, s.lo)).toEqual({ at: 0, over: null });
  });
});
