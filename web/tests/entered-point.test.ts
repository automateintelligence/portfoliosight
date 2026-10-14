// The square for "the mix you entered" (spec 3.3, 4.6, 4.10): it is plotted at the statistics of
// the entered weights, recomputed from the tensor's own moments (`mu_s`, `cov`) with every amount
// matched to its fund by id, whatever the order of the rows and whatever the ids look like; the
// stress cards read the same weights; and a mix the limits allow is never drawn above the frontier
// line or the dashed No limits line. Oracles: sums written out here over the tensor by fund id.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor, type Tensor } from "../src/api/client";
import { portfolioMath, stressReturn } from "../src/math/portfolio";
import { currentMix, type Row } from "../src/state/store";

const RAW = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8"));

// The same tensor with ids shaped like the TSP preset's ("TSP-G"): a hyphen, a shared prefix.
function relabelled(): Tensor {
  const copy = structuredClone(RAW);
  copy.universe.funds = copy.universe.funds.map((f: { id: string }, i: number) => ({ ...f, id: `TSP-${String.fromCharCode(65 + i)}` }));
  return parseTensor(copy);
}
const MENUS: [string, Tensor][] = [
  ["Example Portfolio ids", parseTensor(structuredClone(RAW))],
  ["TSP-style ids", relabelled()],
];

function seeded(seed: number) {
  let a = seed;
  return () => {
    a = (Math.imul(a, 1664525) + 1013904223) >>> 0;
    return a / 4294967296;
  };
}

/** A random mix inside the tensor's bounds, as a weight per fund id: funds in random order each take a random share of what is left, up to their maximum; about a third fill every fund they reach to its cap. */
function feasibleMix(t: Tensor, rnd: () => number): Map<string, number> {
  const ids = t.universe.funds.map((f) => f.id);
  const order = ids.map((id, i) => ({ id, i, key: rnd() })).sort((a, b) => a.key - b.key);
  const greedy = rnd() < 0.35;
  const w = new Map<string, number>(ids.map((id, i) => [id, t.bounds.min[i]]));
  let left = 1 - t.bounds.min.reduce((a, b) => a + b, 0);
  for (const { id, i } of order) {
    const take = Math.min(t.bounds.max[i] - t.bounds.min[i], left) * (greedy ? 1 : rnd());
    w.set(id, (w.get(id) ?? 0) + take);
    left -= take;
  }
  // what is left goes to the funds with room, in the same order
  for (const { id, i } of order) {
    const take = Math.min(t.bounds.max[i] - (w.get(id) ?? 0), left);
    w.set(id, (w.get(id) ?? 0) + take);
    left -= take;
  }
  if (left > 1e-12) throw new Error("the bounds leave no room for a whole mix");
  return w;
}

/** Rows as the Funds table holds them: in a shuffled order, amounts in the unit, blanks for zero. */
function rowsOf(w: Map<string, number>, unit: "pct" | "usd", rnd: () => number): Row[] {
  const scale = unit === "pct" ? 100 : 250_000;
  const rows = [...w].map(([id, v]) => ({ id, name: id, amount: v > 0 ? v * scale : null, key: rnd() }));
  return rows.sort((a, b) => a.key - b.key).map(({ id, name, amount }) => ({ id, name, amount }));
}

/** sqrt(w' cov w) and mu_s' w, summed by fund id. */
function oracle(t: Tensor, w: Map<string, number>): { sigma: number; mu: number } {
  const ids = t.universe.funds.map((f) => f.id);
  let variance = 0;
  let mu = 0;
  ids.forEach((a, i) => {
    mu += t.mu_s[i] * (w.get(a) ?? 0);
    ids.forEach((b, k) => (variance += (w.get(a) ?? 0) * t.cov[i][k] * (w.get(b) ?? 0)));
  });
  return { sigma: Math.sqrt(variance), mu };
}

/** The return of a drawn line at risk `sigma`: straight between its points, flat past its last one (no mix earns more than the line's top). */
function lineAt(curve: { sigma: number[]; mu: number[] }, sigma: number): number {
  const last = curve.sigma.length - 1;
  if (sigma >= curve.sigma[last]) return Math.max(...curve.mu);
  let i = 1;
  while (curve.sigma[i] < sigma) i++;
  const f = (sigma - curve.sigma[i - 1]) / (curve.sigma[i] - curve.sigma[i - 1]);
  return curve.mu[i - 1] + f * (curve.mu[i] - curve.mu[i - 1]);
}

// The drawn lines join mixes the engine computed with straight segments, so between those points
// they run a hair under the true frontier, most where it is nearly vertical at its low-risk end:
// there a mix the limits allow can be a few basis points of return above the line yet a hundredth
// of a point of risk from it. A point counts as on the line within 2 basis points of risk and of
// return, about a pixel at the chart's scales; a square drawn with other inputs than the line is
// off by tens of basis points.
const SLACK = 2e-4;
/** How far `(sigma, mu)` is above a drawn line, after the slack in risk; at most `SLACK` means on or under it. */
const above = (curve: { sigma: number[]; mu: number[] }, sigma: number, mu: number) => mu - lineAt(curve, sigma + SLACK);

describe.each(MENUS)("the square for the mix you entered (%s)", (_name, T) => {
  const M = portfolioMath(T);

  it("sits at sqrt(w' cov w), mu_s' w of the entered amounts, each matched to its fund by id", () => {
    const rnd = seeded(69);
    for (let n = 0; n < 300; n++) {
      const w = feasibleMix(T, rnd);
      const want = oracle(T, w);
      for (const unit of ["pct", "usd"] as const) {
        const mix = currentMix({ rows: rowsOf(w, unit, rnd), unit }, T);
        expect(mix.status, `mix ${n} in ${unit}`).toBe("ok");
        const weights = mix.weights as number[];
        T.universe.funds.forEach((f, i) => expect(weights[i], `${f.id} in mix ${n}`).toBeCloseTo(w.get(f.id) ?? 0, 12));
        const got = M.stats(weights);
        expect(got.sigma, `risk of mix ${n} in ${unit}`).toBeCloseTo(want.sigma, 12);
        expect(got.mu, `return of mix ${n} in ${unit}`).toBeCloseTo(want.mu, 12);
      }
    }
  });

  it("is never above the frontier line or the No limits line for a mix inside the limits", () => {
    const rnd = seeded(2026);
    let closest = -Infinity;
    for (let n = 0; n < 4000; n++) {
      const w = feasibleMix(T, rnd);
      const weights = currentMix({ rows: rowsOf(w, "pct", rnd), unit: "pct" }, T).weights as number[];
      const { sigma, mu } = M.stats(weights);
      const where = `mix ${n} at risk ${sigma}, return ${mu}`;
      // the line starts at the minimum-variance mix, which is the solver's to the 4.11 tolerance
      expect(sigma, where).toBeGreaterThanOrEqual(T.frontier_curve.sigma[0] - 1e-6);
      expect(above(T.frontier_curve, sigma, mu), `${where}, above the frontier line`).toBeLessThanOrEqual(SLACK);
      expect(above(T.frontier_uncapped, sigma, mu), `${where}, above the No limits line`).toBeLessThanOrEqual(SLACK);
      closest = Math.max(closest, mu - lineAt(T.frontier_curve, sigma));
    }
    // the sample reaches the line, so the check above has something to bite on
    expect(closest).toBeGreaterThan(-5e-3);
  });

  it("feeds the stress cards the same weights, matched by id", () => {
    const rnd = seeded(2008);
    for (let n = 0; n < 50; n++) {
      const w = feasibleMix(T, rnd);
      const weights = currentMix({ rows: rowsOf(w, "pct", rnd), unit: "pct" }, T).weights as number[];
      for (const win of Object.values(T.stress)) {
        let held = 0;
        let gained = 0;
        T.universe.funds.forEach((f, i) => {
          const r = win.r[i];
          if (r === null) return;
          held += w.get(f.id) ?? 0;
          gained += (w.get(f.id) ?? 0) * r;
        });
        const got = stressReturn(weights, win.r).value;
        if (held >= 0.5) expect(got, `${win.label}, mix ${n}`).toBeCloseTo(gained / held, 12);
        else expect(got, `${win.label}, mix ${n}`).toBeNull();
      }
    }
  });
});
