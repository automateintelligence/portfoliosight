// One engine at a time (engines spec 6, 7): the browser math reads the engine's own range
// blocks, a schema 2 tensor answers the default for every engine, and the slider's left end
// follows the engine. Fixture numbers are read, never copied.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor, type Tensor } from "../src/api/client";
import { carriedEngines, carries, defaultEngine, engineReason, NOT_COMPUTED, resolveEngine } from "../src/math/engines";
import { portfolioMath } from "../src/math/portfolio";
import { deriveView } from "../src/math/view";

const read = (file: string) => JSON.parse(fs.readFileSync(path.resolve(process.cwd(), file), "utf-8"));
const RAW = read("fixtures/guide2017_5y.json");
const OLD = read("tests/tensor-schema2.json");
const NX: number = RAW.frontier.x.length;
const L: number = RAW.ladder.w[0].length;

/** The fixture with the two engines' slider domains pinned apart: replay starts at 3, garch at 1. */
const apart = () => {
  const copy = structuredClone(RAW);
  copy.frontier.s_safe = 3;
  copy.frontier.ranges.replay.s_safe = 3;
  copy.frontier.ranges.garch.s_safe = 1;
  return copy;
};

describe("which engines a tensor carries", () => {
  it("reads the engines block: replay and the volatility model are ready on the fixture, the copula is not", () => {
    const T = parseTensor(RAW);
    expect(defaultEngine(T)).toBe(RAW.range_default);
    expect(carriedEngines(T)).toEqual(["replay", "garch"]);
    expect(carries(T, "garch")).toBe(true);
    expect(carries(T, "copula")).toBe(false);
    expect(engineReason(T, "garch")).toBeNull();
    expect(engineReason(T, "copula")).toBe(RAW.engines.copula.reason);
    expect(RAW.engines.copula.reason).toBeTruthy();
  });

  it("gives the tensor's own reason for an engine it does not carry", () => {
    const raw = structuredClone(RAW);
    raw.engines.garch = { status: "unavailable", reason: "not enough shared history for the volatility model", method: null };
    delete raw.frontier.ranges.garch;
    delete raw.ladder.ranges.garch;
    delete raw.entered.ranges.garch;
    const T = parseTensor(raw);
    expect(carries(T, "garch")).toBe(false);
    expect(engineReason(T, "garch")).toBe("not enough shared history for the volatility model");
    expect(resolveEngine(T, "garch")).toBe(defaultEngine(T));
    expect(resolveEngine(T, "replay")).toBe("replay");
  });

  it("a schema 2 tensor carries History replay only and says 'not computed for this menu' for the others", () => {
    const T = parseTensor(OLD);
    expect(T.schema).toBe(2);
    expect(defaultEngine(T)).toBe("replay");
    expect(carriedEngines(T)).toEqual(["replay"]);
    expect(engineReason(T, "garch")).toBe(NOT_COMPUTED);
    expect(engineReason(T, "copula")).toBe(NOT_COMPUTED);
    for (const wanted of ["replay", "garch", "copula"] as const) expect(resolveEngine(T, wanted)).toBe("replay");
  });
});

describe("yearRange for an engine", () => {
  const T = parseTensor(RAW);
  const M = portfolioMath(T);

  it("at a column and a level is that engine's own figure in ladder.ranges, exactly", () => {
    for (const engine of ["replay", "garch"] as const) {
      const R = RAW.ladder.ranges[engine];
      for (const j of [0, 2, 17, NX - 1]) {
        for (let l = 0; l < L; l++) {
          const r = M.yearRange(j, l / (L - 1), engine);
          expect(r.low, `${engine} bad (${j}, ${l})`).toBeCloseTo(R.bad[j][l], 14);
          expect(r.typical, `${engine} typical (${j}, ${l})`).toBeCloseTo(R.typical[j][l], 14);
          expect(r.high, `${engine} good (${j}, ${l})`).toBeCloseTo(R.good[j][l], 14);
        }
      }
    }
  });

  it("the volatility model's figures are not the replay's, and no engine argument is the tensor's default", () => {
    const g = M.yearRange(20, 0.3, "garch");
    const r = M.yearRange(20, 0.3, "replay");
    expect([g.low, g.typical, g.high]).not.toEqual([r.low, r.typical, r.high]);
    expect(M.yearRange(20, 0.3)).toEqual(M.yearRange(20, 0.3, defaultEngine(T)));
  });

  it("blends two columns and two levels of one engine like the mixes, never of two engines", () => {
    const s = 20.25;
    const t = 4.5 / (L - 1);
    const R = RAW.ladder.ranges.garch;
    const at = (rows: number[][], j: number) => 0.5 * rows[j][4] + 0.5 * rows[j][5];
    expect(M.yearRange(s, t, "garch").low).toBeCloseTo(0.75 * at(R.bad, 20) + 0.25 * at(R.bad, 21), 14);
    expect(M.yearRange(s, t, "garch").high).toBeCloseTo(0.75 * at(R.good, 20) + 0.25 * at(R.good, 21), 14);
  });

  it("reads the kept ladder.range for the default engine and ladder.ranges for every other", () => {
    const raw = structuredClone(RAW);
    const L0 = raw.ladder.range.bad.map((row: number[]) => row.map(() => -0.5));
    raw.ladder.range.bad = L0;
    raw.ladder.ranges.garch.bad = raw.ladder.ranges.garch.bad.map((row: number[]) => row.map(() => -0.25));
    const m = portfolioMath(parseTensor(raw));
    expect(m.yearRange(10, 0.5).low).toBeCloseTo(-0.5, 14);
    expect(m.yearRange(10, 0.5, "replay").low).toBeCloseTo(-0.5, 14);
    expect(m.yearRange(10, 0.5, "garch").low).toBeCloseTo(-0.25, 14);
  });

  it("a schema 2 tensor answers the default for every engine; so does an engine the tensor does not carry", () => {
    const old = portfolioMath(parseTensor(OLD));
    for (const engine of ["garch", "copula"] as const) {
      expect(old.yearRange(1.5, 0.4, engine)).toEqual(old.yearRange(1.5, 0.4));
      expect(old.riskSliderDomain(engine)).toEqual(old.riskSliderDomain());
    }
    expect(M.yearRange(20, 0.3, "copula")).toEqual(M.yearRange(20, 0.3));
    expect(M.riskSliderDomain("copula")).toBe(M.riskSliderDomain());
  });
});

describe("riskSliderDomain for an engine", () => {
  it("is frontier.ranges[engine].s_safe, and frontier.s_safe for the default and without an engine", () => {
    const raw = apart();
    const T = parseTensor(raw);
    const M = portfolioMath(T);
    expect(M.riskSliderDomain("garch")).toEqual({ s_safe: 1, s_max: NX - 1 });
    expect(M.riskSliderDomain("replay")).toEqual({ s_safe: 3, s_max: NX - 1 });
    expect(M.riskSliderDomain()).toEqual({ s_safe: raw.frontier.s_safe, s_max: NX - 1 });
    expect(M.riskSliderDomain("garch")).toBe(M.riskSliderDomain("garch"));
  });

  it("the fixture's own engines read their own s_safe", () => {
    const M = portfolioMath(parseTensor(RAW));
    expect(M.riskSliderDomain("garch").s_safe).toBe(RAW.frontier.ranges.garch.s_safe);
    expect(M.riskSliderDomain("replay").s_safe).toBe(RAW.frontier.ranges.replay.s_safe);
    expect(RAW.frontier.s_safe).toBe(RAW.frontier.ranges[RAW.range_default].s_safe);
  });
});

describe("deriveView for an engine", () => {
  const T: Tensor = parseTensor(apart());
  const M = portfolioMath(T);

  it("reads the engine's ranges, its domain and its clamp; the mixes are the same for every engine", () => {
    const garch = deriveView(T, M, 2, 0.5, "garch");
    const replay = deriveView(T, M, 2, 0.5, "replay");
    expect(garch.s, "garch reaches 1").toBe(2);
    expect(replay.s, "replay starts at 3").toBe(3);
    expect(garch.domain).toEqual({ s_safe: 1, s_max: NX - 1 });
    expect(replay.domain).toEqual({ s_safe: 3, s_max: NX - 1 });
    expect(garch.range).toEqual(M.yearRange(2, 0.5, "garch"));
    expect(garch.frontRange).toEqual(M.yearRange(2, 0, "garch"));
    expect(replay.range).toEqual(M.yearRange(3, 0.5, "replay"));
    const same = deriveView(T, M, 10, "auto", "garch");
    const base = deriveView(T, M, 10, "auto", "replay");
    expect(same.weights).toEqual(base.weights);
    expect(same.selected).toEqual(base.selected);
    expect(same.optimized).toEqual(base.optimized);
    expect(same.word).toBe(base.word);
    expect(same.range).not.toEqual(base.range);
    expect(same.optRange).toEqual(M.yearRange(10, same.tAuto, "garch"));
  });

  it("without an engine it is the tensor's default, as before", () => {
    expect(deriveView(T, M, 10, 0.3)).toEqual(deriveView(T, M, 10, 0.3, defaultEngine(T)));
  });
});
