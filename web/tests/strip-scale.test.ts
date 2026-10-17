import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";
import type { Tensor } from "../src/api/tensor";
import { portfolioMath } from "../src/math/portfolio";
import { STRIP_PAD, stripAt, stripPlace, stripScale, tensorBounds } from "../src/math/stripScale";
import { carriedEngines } from "../src/math/engines";
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
  // every engine's own blocks move with the kept ones
  for (const id of ["replay", "garch", "copula"] as const) {
    const front = t.frontier.ranges?.[id];
    if (front) t.frontier.ranges![id] = { ...front, bad: move(front.bad), good: move(front.good) };
    const ladder = t.ladder.ranges?.[id];
    if (ladder) t.ladder.ranges![id] = { ...ladder, bad: ladder.bad.map(move), good: ladder.good.map(move) };
    const entered = t.entered?.ranges?.[id];
    if (entered) t.entered!.ranges![id] = { ...entered, bad: entered.bad + shift, good: entered.good + shift };
  }
  return t;
}

describe("the strip's fixed scale", () => {
  it("bounds a tensor by the lowest Bad and highest Good over every engine it carries: frontier nodes, ladder nodes (peaks included) and entered mix", () => {
    const b = tensorBounds(T5);
    const bads: number[] = [...T5.frontier.range.bad, ...T5.ladder.range.bad.flat(), ...(T5.entered ? [T5.entered.range.bad] : [])];
    const goods: number[] = [...T5.frontier.range.good, ...T5.ladder.range.good.flat(), ...(T5.entered ? [T5.entered.range.good] : [])];
    const engines = carriedEngines(T5);
    expect(engines.length).toBeGreaterThan(1);
    for (const id of engines) {
      bads.push(...T5.frontier.ranges![id]!.bad, ...T5.ladder.ranges![id]!.bad.flat(), ...(T5.entered ? [T5.entered.ranges![id]!.bad] : []));
      goods.push(...T5.frontier.ranges![id]!.good, ...T5.ladder.ranges![id]!.good.flat(), ...(T5.entered ? [T5.entered.ranges![id]!.good] : []));
    }
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

  it("spans every engine: the volatility model's wider year moves the bar's ends even when History replay is the default", () => {
    const own = tensorBounds(T5);
    const wide = structuredClone(T5);
    wide.ladder.ranges!.garch!.bad[3][2] = own.min - 0.2;
    wide.frontier.ranges!.garch!.good[5] = own.max + 0.3;
    expect(tensorBounds(wide)).toEqual({ min: own.min - 0.2, max: own.max + 0.3 });
    // and the kept default blocks alone would not have seen it
    expect(Math.min(...wide.ladder.range.bad.flat())).toBeGreaterThan(own.min - 0.2);
  });

  it("holds every mix the sliders can reach under every carried engine, so no marker leaves the bar", () => {
    const math = portfolioMath(T5);
    const scale = stripScale(tensorBounds(T5));
    for (const engine of carriedEngines(T5)) {
      const { s_safe, s_max } = math.riskSliderDomain(engine);
      for (let i = 0; i <= 20; i++) {
        for (const t of [0, 0.25, 0.5, 0.75, 1]) {
          const v = deriveView(T5, math, s_safe + ((s_max - s_safe) * i) / 20, t, engine);
          for (const x of [v.range.low, v.range.typical, v.range.high]) {
            expect(stripAt(scale, x), `${engine} ${x}`).toBeGreaterThan(0);
            expect(stripAt(scale, x), `${engine} ${x}`).toBeLessThan(1);
          }
        }
      }
    }
  });

  it("a schema 2 tensor is bounded by its kept blocks", () => {
    const old = parseTensor(JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "tests/tensor-schema2.json"), "utf8")));
    const b = tensorBounds(old);
    expect(b.min).toBe(Math.min(...old.frontier.range.bad, ...old.ladder.range.bad.flat(), ...(old.entered ? [old.entered.range.bad] : [])));
    expect(b.max).toBe(Math.max(...old.frontier.range.good, ...old.ladder.range.good.flat(), ...(old.entered ? [old.entered.range.good] : [])));
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
