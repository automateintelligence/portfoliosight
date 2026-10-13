// Stress aggregation with partial coverage (spec 4.10): sum(w_i R_i) / sum(w_i) over covered funds.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";
import { stressReturn } from "../src/math/portfolio";

describe("stressReturn", () => {
  it("averages over the covered funds only and reports the covered share", () => {
    const got = stressReturn([0.6, 0.3, 0.1], [-0.3, null, 0.1]);
    expect(got.covered).toBeCloseTo(0.7, 15);
    expect(got.value).toBeCloseTo((0.6 * -0.3 + 0.1 * 0.1) / 0.7, 15);
    // a fund that did not exist is left out, not counted as a 0% return
    expect(got.value).not.toBeCloseTo(0.6 * -0.3 + 0.1 * 0.1, 3);
  });

  it("is the plain weighted return when every fund is covered", () => {
    expect(stressReturn([0.25, 0.75], [-0.4, 0.2])).toEqual({ value: expect.closeTo(0.05, 15), covered: 1 });
    expect(stressReturn([1, 0], [-0.31, 0.9])).toEqual({ value: -0.31, covered: 1 });
  });

  it("gives a number at exactly half covered and none below it", () => {
    expect(stressReturn([0.5, 0.5], [0.1, null])).toEqual({ value: 0.1, covered: 0.5 });
    const below = stressReturn([0.4999, 0.5001], [0.1, null]);
    expect(below.covered).toBeCloseTo(0.4999, 15);
    expect(below.value).toBeNull();
    expect(stressReturn([0.5, 0.5], [null, null])).toEqual({ value: null, covered: 0 });
  });

  it("ignores the price history of funds the mix does not hold", () => {
    expect(stressReturn([0, 0.5, 0.5], [null, -0.2, -0.4])).toEqual({ value: expect.closeTo(-0.3, 15), covered: 1 });
    expect(stressReturn([1, 0, 0], [null, -0.2, -0.4])).toEqual({ value: null, covered: 0 });
  });

  it("divides by the weights it is given, so an unnormalized mix reads the same", () => {
    const unit = stressReturn([0.2, 0.3, 0.5], [0.1, null, -0.2]);
    const scaled = stressReturn([2, 3, 5], [0.1, null, -0.2]);
    expect(scaled.covered).toBeCloseTo(unit.covered, 15);
    expect(scaled.value).toBeCloseTo(unit.value as number, 15);
    expect(unit.value).toBeCloseTo((0.02 - 0.1) / 0.7, 15);
  });

  it("has no number for a mix with no weight at all", () => {
    expect(stressReturn([0, 0], [0.1, 0.2])).toEqual({ value: null, covered: 0 });
  });

  it("matches a direct sum over the fixture's 2008 window, where six funds have no history", () => {
    const tensor = parseTensor(JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf-8")));
    const r = tensor.stress.gfc2008.r;
    expect(r.filter((v) => v === null)).toHaveLength(6);
    let partial = 0;
    for (const w of [...tensor.frontier.w, ...tensor.grid.w_div]) {
      let covered = 0;
      let numerator = 0;
      w.forEach((wi, i) => {
        const ri = r[i];
        if (ri !== null) {
          covered += wi;
          numerator += wi * ri;
        }
      });
      const total = w.reduce((acc, v) => acc + v, 0);
      const got = stressReturn(w, r);
      expect(got.covered).toBeCloseTo(covered / total, 12);
      if (covered / total >= 0.5) expect(got.value).toBeCloseTo(numerator / covered, 12);
      else expect(got.value).toBeNull();
      if (got.covered < 0.995 && got.value !== null) partial += 1;
    }
    expect(partial, "mixes that are partly covered and still get a number").toBeGreaterThan(0);
  });
});
