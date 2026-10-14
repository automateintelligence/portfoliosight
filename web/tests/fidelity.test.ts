// Tensor loader and browser math (spec 4.6, 4.9, 4.11, 7). The oracles here are hand-computed
// values on a two-fund tensor, the JSON Schema, the fixture's own fields, and checksums from the
// Python reference `portfoliosight.engine.surface.interpolate`.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor, type Tensor } from "../src/api/client";
import { portfolioMath } from "../src/math/portfolio";

const read = (file: string) => JSON.parse(fs.readFileSync(path.resolve(process.cwd(), file), "utf-8"));
const RAW = read("fixtures/guide2017_5y.json");
const SCHEMA = read("../portfoliosight/engine/tensor.schema.json");
const N: number = RAW.universe.funds.length;
const NX: number = RAW.frontier.x.length;
const NY: number = RAW.grid.y.length;

type Path = (string | number)[];
type Node = Record<string | number, unknown>;
const clone = () => structuredClone(RAW);
// The fixture's menu sets no fund aside. The loader checks start from the fixture with the one
// entry the service writes for a menu that holds FIENX, so every object of the schema is there.
const ASIDE = { id: "FIENX", reason: "converted to an ETF; no data since 2024-10-30", last_close: null };
const withAside = () => {
  const copy = clone();
  copy.universe.excluded = [{ ...ASIDE }];
  return copy;
};
const walk = (root: unknown, at: Path) => at.reduce((node, key) => (node as Node)[key], root);
const parent = (root: unknown, at: Path) => walk(root, at.slice(0, -1)) as Node;
function patched(at: Path, value: unknown): unknown {
  const copy = withAside();
  parent(copy, at)[at[at.length - 1]] = value;
  return copy;
}
function without(at: Path): unknown {
  const copy = withAside();
  delete parent(copy, at)[at[at.length - 1]];
  return copy;
}

const sum = (a: number[]) => a.reduce((acc, v) => acc + v, 0);
const dot = (a: number[], b: number[]) => a.reduce((acc, v, i) => acc + v * b[i], 0);
const mix = (a: number[], b: number[], f: number) => a.map((v, i) => (1 - f) * v + f * b[i]);
const maxDiff = (a: number[], b: number[]) => a.reduce((acc, v, i) => Math.max(acc, Math.abs(v - b[i])), a.length === b.length ? 0 : Infinity);
const rel = (a: number, b: number) => Math.abs(a - b) / Math.max(Math.abs(a), Math.abs(b), 1e-300);
function expectMix(got: number[], want: number[], digits = 12) {
  expect(got).toHaveLength(want.length);
  got.forEach((v, i) => expect(v, `weight ${i} of [${got}]`).toBeCloseTo(want[i], digits));
}
function seeded(seed: number) {
  let a = seed;
  return () => {
    a = (Math.imul(a, 1664525) + 1013904223) >>> 0;
    return a / 4294967296;
  };
}

// ---- a two-fund tensor small enough to work out by hand ------------------------------------
// Funds A and B are uncorrelated with volatilities 10% and 20% and returns 2% and 10%, so the
// torsion is the identity and a mix [a, 1 - a] returns 10% - 8% * a.
const FLOORS = [0.02, 0.06, 0.1];
// A column's ladder of three levels (at t = 0, 0.5 and 1): the frontier mix first, the peak last.
type Column = { levels: number[][]; hop?: boolean[]; collapsed?: boolean; tSug?: number };
const FULL: Column = { levels: [[0, 1], [0.5, 0.5], [1, 0]], tSug: 0.5 };
const SHORT: Column = { levels: [[0.25, 0.75], [0.375, 0.625], [0.5, 0.5]], tSug: 1 };
const COLLAPSED: Column = { levels: [[0.5, 0.5], [0.5, 0.5], [0.5, 0.5]], collapsed: true };
// the first step is a hop: its two levels must not be blended
const HOP: Column = { levels: [[0, 1], [0.5, 0.5], [1, 0]], hop: [true, false] };
// the peak was reached one level early: the last two levels are the same mix
const PLATEAU: Column = { levels: [[0, 1], [0.2, 0.8], [0.2, 0.8]] };

const muOf = (w: number[]) => 0.02 * w[0] + 0.1 * w[1];
// a range block of the right shape; the browser math does not read it
const rangeOf = <T>(value: T) => ({ bad: value, typical: value, good: value, normal: { low: value, mid: value, high: value } });

function tiny(columns: Column[], sSafe = 0) {
  const nx = columns.length;
  const fund = (id: string) => ({ id, name: `Fund ${id}`, kind: "etf", source: "tiingo", adjusted_through: "2026-10-12", fetched_at: "2026-10-13T09:05:11Z", last_close: 100 });
  const stale = Array(8 * (nx - 1) + 1).fill(0.5);
  const window = { label: "A window", start: "2008-09-01", end: "2009-03-09", r: [0.1, null] };
  const fronts = columns.map((c) => c.levels[0]);
  const peaks = columns.map((c) => c.levels[c.levels.length - 1]);
  const yFront = fronts.map(muOf);
  // the raster is only drawn, never read by the math: every row holds the column's peak
  const kDiv = columns.map((c) => (c.collapsed ? -1 : 0));
  return {
    schema: 2, engine_version: "0.1.0", generation: "2026-10-12-0.1.0", built_at: "2026-10-13T09:31:02Z", build_seconds: 0.1, asof: "2026-10-12",
    frontier_curve: { sigma: stale, mu: stale },
    universe: { hash: "0123456789abcdef", name: "Two funds", preset_id: null, funds: [fund("AAA"), fund("BBB")], excluded: [] },
    lookback: { id: "5y", start: "2021-10-13", end: "2026-10-12", rows: 1257, t_eff: 1257, ew_halflife_days: null, sample_sha256: "0".repeat(64) },
    rf: 0.04, mu_s: [0.02, 0.1], mu_sample: [0.02, 0.1], sigma: [0.1, 0.2], cov: [[0.01, 0], [0, 0.04]],
    torsion: [[1, 0], [0, 1]], torsion_inv_t: [[1, 0], [0, 1]], torsion_lambda: [0.01, 0.04],
    bounds: { requested: [{ min: null, max: null }, { min: null, max: null }], min: [0, 0], max: [1, 1], rule: "max(0.25, 3/N)" },
    frontier_uncapped: { sigma: Array(nx).fill(0.5), mu: Array(nx).fill(0.5) },
    frontier: { x: columns.map((_, j) => 0.1 + (0.1 * j) / (nx - 1)), y: yFront, w: fronts, s_safe: sSafe, range: rangeOf(Array(nx).fill(0)) },
    ladder: {
      y: columns.map((c) => c.levels.map(muOf)),
      z: columns.map((c) => c.levels.map(() => 1.5)),
      w: columns.map((c) => c.levels),
      hop: columns.map((c) => c.hop ?? [false, false]),
      collapsed: columns.map((c) => c.collapsed ?? false),
      t_balanced: columns.map((c) => c.tSug ?? 0),
      y_balanced: columns.map((c, j) => (c.tSug === undefined ? yFront[j] : muOf(c.levels[2 * c.tSug]))),
      default_point: "balanced",
      t_suggested: columns.map((c) => c.tSug ?? 0),
      y_suggested: columns.map((c, j) => (c.tSug === undefined ? yFront[j] : muOf(c.levels[2 * c.tSug]))),
      range: rangeOf(columns.map(() => [0, 0, 0])),
    },
    grid: {
      y: FLOORS,
      z: columns.map(() => FLOORS.map(() => 1.5)),
      w: peaks.map((peak) => FLOORS.map(() => peak)),
      k_div: kDiv,
      y_div: columns.map((_, j) => (kDiv[j] < 0 ? yFront[j] : FLOORS[0])),
      w_div: peaks,
      y_sug: yFront,
    },
    entered: null,
    range_method: RAW.range_method,
    enb_ref: 2,
    stress: { gfc2008: window, covid2020: window, rates2022: window },
    notes: [],
  };
}
const tinyMath = (...columns: Column[]) => portfolioMath(parseTensor(tiny(columns)));
const peaksOf = (T: { ladder: { w: number[][][] } }) => T.ladder.w.map((levels) => levels[levels.length - 1]);

// the test's own statistics of a mix on the fixture (spec 4.6)
function ownStats(T: Pick<Tensor, "mu_s" | "cov" | "torsion_inv_t" | "torsion_lambda">, w: number[]) {
  const variance = dot(w, T.cov.map((row) => dot(row, w)));
  let entropy = 0;
  T.torsion_inv_t.forEach((row, i) => {
    const p = (T.torsion_lambda[i] * dot(row, w) ** 2) / variance;
    if (p > 0) entropy -= p * Math.log(p);
  });
  return { mu: dot(w, T.mu_s), sigma: Math.sqrt(variance), enb: Math.exp(entropy) };
}
const nodeMix = (rows: number[][], s: number) => {
  const j = Math.min(Math.floor(s), rows.length - 2);
  return mix(rows[j], rows[j + 1], s - j);
};

describe("parseTensor", () => {
  // every object of the JSON Schema, located at one place in a tensor
  type SchemaNode = { $ref?: string; type?: string; required?: string[]; properties?: Record<string, SchemaNode>; items?: SchemaNode; additionalProperties?: boolean };
  function objects(node: SchemaNode, at: Path = [], out: { at: Path; required: string[] }[] = []) {
    const resolved: SchemaNode = node.$ref ? SCHEMA.$defs[node.$ref.split("/").pop() as string] : node;
    if (resolved.type === "object") {
      expect(resolved.additionalProperties, `schema object at ${at.join(".")}`).toBe(false);
      out.push({ at, required: resolved.required ?? [] });
      for (const [key, child] of Object.entries(resolved.properties ?? {})) objects(child, [...at, key], out);
    } else if (resolved.type === "array" && resolved.items) {
      objects(resolved.items, [...at, 0], out);
    }
    return out;
  }
  const OBJECTS = objects(SCHEMA);

  it("returns the fixture unchanged and leaves its input alone", () => {
    const input = clone();
    const tensor = parseTensor(input);
    expect(tensor).toEqual(RAW);
    expect(input).toEqual(RAW);
    expect(tensor.universe.funds).toHaveLength(23);
    expect(tensor.universe.excluded).toEqual([]);
  });

  it("keeps a fund the service set aside, with its reason", () => {
    const tensor = parseTensor(withAside());
    expect(tensor.universe.excluded).toEqual([ASIDE]);
    expect(tensor.universe.funds).toEqual(RAW.universe.funds);
    expect(walk(withAside(), ["universe", "excluded", 0, "reason"])).toBe(ASIDE.reason);
  });

  it("refuses a tensor that lacks any key the JSON Schema requires", () => {
    let checked = 0;
    for (const { at, required } of OBJECTS) {
      for (const key of required) {
        expect(() => parseTensor(without([...at, key])), `without ${[...at, key].join(".")}`).toThrow();
        checked += 1;
      }
    }
    expect(OBJECTS.length).toBe(21);
    expect(checked).toBeGreaterThan(70);
  });

  it("refuses a key the JSON Schema does not know, at every level", () => {
    for (const { at } of OBJECTS) expect(() => parseTensor(patched([...at, "zz"], 1)), `zz in ${at.join(".") || "the tensor"}`).toThrow();
  });

  it("refuses values outside the JSON Schema's types, enums, patterns and limits", () => {
    const bad: [Path, unknown][] = [
      [["schema"], 3],
      [["engine_version"], "v0.1"],
      [["generation"], "2026-10-12"],
      [["built_at"], "2026-10-13 12:18:20"],
      [["build_seconds"], -1],
      [["asof"], "10/12/2026"],
      [["universe", "hash"], "7F3A0C5E9B1D2468"],
      [["universe", "name"], ""],
      [["universe", "preset_id"], 7],
      [["universe", "funds", 0, "kind"], "bond"],
      [["universe", "funds", 0, "source"], "yahoo"],
      [["universe", "funds", 0, "last_close"], "162.07"],
      [["universe", "funds", 0, "adjusted_through"], "yesterday"],
      [["universe", "excluded", 0, "reason"], ""],
      [["lookback", "id"], "7y"],
      [["lookback", "rows"], 125],
      [["lookback", "rows"], 1260.5],
      [["lookback", "t_eff"], 0],
      [["lookback", "ew_halflife_days"], 252.5],
      [["lookback", "sample_sha256"], "4E5EFE"],
      [["rf"], "0.04"],
      [["mu_s", 0], "0.1"],
      [["cov", 0, 0], null],
      [["bounds", "rule"], "max(0.3, 3/N)"],
      [["bounds", "requested", 0, "max"], "25%"],
      [["frontier", "s_safe"], -0.125],
      [["frontier", "w", 3, 0], null],
      [["grid", "k_div", 0], -2],
      [["grid", "k_div", 0], 0.5],
      [["grid", "z", 0, 0], "high"],
      [["grid", "w", 5, NY - 1], 0],
      [["ladder", "t_suggested", 3], 1.5],
      [["ladder", "default_point"], "knee"],
      [["ladder", "hop", 3, 0], 1],
      [["ladder", "collapsed", 3], "no"],
      [["frontier", "range", "bad", 3], null],
      [["entered", "set_aside"], 2],
      [["range_method", "percentile_method"], "nearest"],
      [["enb_ref"], 0.5],
      [["stress", "covid2020", "r", 0], "n/a"],
      [["stress", "covid2020", "label"], ""],
      [["notes"], [""]],
      [["notes"], "none"],
    ];
    for (const [at, value] of bad) expect(() => parseTensor(patched(at, value)), `${at.join(".")} = ${JSON.stringify(value)}`).toThrow();
    for (const junk of [null, undefined, 7, "tensor", [], {}]) expect(() => parseTensor(junk)).toThrow();
  });

  it("refuses arrays whose lengths disagree with n, nx and ny (spec 7)", () => {
    const short = (at: Path) => patched(at, (walk(RAW, at) as unknown[]).slice(1));
    const vectors: Path[] = [
      ["universe", "funds"], ["frontier", "x"], ["grid", "y"],
      ["mu_s"], ["mu_sample"], ["sigma"], ["torsion_lambda"], ["cov"], ["cov", 4], ["torsion"], ["torsion", 0], ["torsion_inv_t"], ["torsion_inv_t", 9],
      ["bounds", "requested"], ["bounds", "min"], ["bounds", "max"],
      ["frontier", "y"], ["frontier", "w"], ["frontier", "w", 3],
      ["grid", "z"], ["grid", "z", 2], ["grid", "w"], ["grid", "w", 2], ["grid", "w", 2, 0], ["grid", "k_div"], ["grid", "y_div"], ["grid", "w_div"], ["grid", "w_div", 7], ["grid", "y_sug"],
      ["frontier_curve", "sigma"], ["frontier_curve", "mu"], ["frontier_uncapped", "sigma"], ["frontier_uncapped", "mu"],
      ["frontier", "range", "bad"], ["frontier", "range", "normal", "high"],
      ["ladder", "y"], ["ladder", "y", 3], ["ladder", "z", 3], ["ladder", "w"], ["ladder", "w", 3], ["ladder", "w", 3, 2], ["ladder", "hop"], ["ladder", "hop", 3],
      ["ladder", "collapsed"], ["ladder", "t_balanced"], ["ladder", "y_balanced"], ["ladder", "t_suggested"], ["ladder", "y_suggested"],
      ["ladder", "range", "typical", 4], ["ladder", "range", "normal", "low", 4], ["entered", "w"],
      ["stress", "gfc2008", "r"], ["stress", "covid2020", "r"], ["stress", "rates2022", "r"],
    ];
    for (const at of vectors) expect(() => parseTensor(short(at)), `${at.join(".")} one entry short`).toThrow();
    expect(() => parseTensor(patched(["grid", "k_div", 5], NY)), "k_div beyond the last row").toThrow();
    expect(() => parseTensor(patched(["grid", "w", 5, RAW.grid.k_div[5]], null)), "k_div on an empty cell").toThrow();
    expect(() => parseTensor(patched(["grid", "z", 5, RAW.grid.k_div[5]], null)), "a mix without its ENB").toThrow();
    expect(() => parseTensor(patched(["frontier", "s_safe"], NX)), "s_safe beyond the last column").toThrow();
  });

  it("accepts what the 4.11 tolerances allow: weights summing to 1 + 5e-7 and a stale curve", () => {
    const T = clone();
    T.frontier.w[10] = T.frontier.w[10].map((v: number) => (v * (1 + 5e-7)) / sum(T.frontier.w[10]));
    T.frontier_curve.sigma[80] *= 1.01;
    T.universe.funds[0].last_close = null;
    T.lookback.ew_halflife_days = 252;
    expect(parseTensor(T).frontier.w[10]).toEqual(T.frontier.w[10]);
    expect(() => parseTensor(tiny([FULL, SHORT, COLLAPSED, HOP, PLATEAU]))).not.toThrow();
  });
});

describe("stats and range6m", () => {
  const M = portfolioMath(parseTensor(clone()));

  it("reproduces the spec 4.6 identities on two uncorrelated funds", () => {
    const m = tinyMath(FULL, SHORT);
    const half = m.stats([0.5, 0.5]);
    expect(half.mu).toBeCloseTo(0.06, 14);
    expect(half.sigma).toBeCloseTo(Math.sqrt(0.0125), 14);
    expect(half.enb).toBeCloseTo(Math.exp(-(0.2 * Math.log(0.2) + 0.8 * Math.log(0.8))), 12);
    expect(half.enb).toBeCloseTo(1.649, 3);
    expect(m.stats([1, 0])).toEqual({ mu: 0.02, sigma: 0.1, enb: 1 });
    expect(m.stats([2 / 3, 1 / 3]).enb, "inverse-volatility weights spread the risk evenly").toBeCloseTo(2, 12);
    expect(m.stats(Float64Array.of(0.5, 0.5))).toEqual(half);
  });

  it("equals the tensor at every frontier node, ladder level and grid cell to 1e-9 relative", () => {
    let cells = 0;
    let levels = 0;
    for (let j = 0; j < NX; j++) {
      const st = M.stats(RAW.frontier.w[j]);
      expect(rel(st.mu, RAW.frontier.y[j]), `mu of frontier ${j}`).toBeLessThanOrEqual(1e-9);
      expect(rel(st.sigma, RAW.frontier_curve.sigma[8 * j]), `sigma of frontier ${j}`).toBeLessThanOrEqual(1e-9);
      expect(st.sigma, `frontier ${j} against its ceiling`).toBeLessThanOrEqual(RAW.frontier.x[j] + 1e-6);
      for (let k = 0; k < NY; k++) {
        const w = RAW.grid.w[j][k];
        if (w === null) continue;
        const cell = M.stats(w);
        const own = ownStats(RAW, w);
        expect(rel(cell.enb, RAW.grid.z[j][k]), `ENB of cell (${j}, ${k})`).toBeLessThanOrEqual(1e-9);
        expect(rel(cell.mu, own.mu) + rel(cell.sigma, own.sigma), `cell (${j}, ${k})`).toBeLessThanOrEqual(1e-12);
        cells += 1;
      }
      RAW.ladder.w[j].forEach((w: number[], l: number) => {
        const level = M.stats(w);
        expect(rel(level.mu, RAW.ladder.y[j][l]), `return of level (${j}, ${l})`).toBeLessThanOrEqual(1e-9);
        expect(rel(level.enb, RAW.ladder.z[j][l]), `ENB of level (${j}, ${l})`).toBeLessThanOrEqual(1e-9);
        // every level of a column holds the column's risk (spec 4.7)
        expect(Math.abs(level.sigma - RAW.frontier.x[j]), `risk of level (${j}, ${l})`).toBeLessThanOrEqual(1e-6);
        levels += 1;
      });
    }
    expect(cells).toBeGreaterThan(NX * 5);
    expect(levels).toBe(NX * RAW.ladder.y[0].length);
  });

  it("has no answer for a vector of the wrong length or without variance", () => {
    expect(() => M.stats(RAW.frontier.w[0].slice(1))).toThrow(RangeError);
    expect(M.stats(Array(N).fill(0)).enb).toBeNaN();
  });

  it("range6m is mu/2 -+ 1.96 sigma/sqrt 2", () => {
    const r = M.range6m(0.08, 0.2);
    expect(r.typical).toBeCloseTo(0.04, 15);
    // 1.96 * 0.2 / sqrt(2) = 0.2771858582...
    expect(r.low).toBeCloseTo(-0.2371858582, 9);
    expect(r.high).toBeCloseTo(0.3171858582, 9);
    expect(r.high - r.typical).toBeCloseTo(r.typical - r.low, 15);
    expect(M.range6m(0.05, 0)).toEqual({ low: 0.025, typical: 0.025, high: 0.025 });
  });
});

describe("interpolate", () => {
  const M = portfolioMath(parseTensor(clone()));

  it("walks a column's ladder level by level and reaches both ends exactly", () => {
    const m = tinyMath(FULL, FULL);
    expect(m.interpolate(0, 0)).toEqual([0, 1]);
    expectMix(m.interpolate(0, 0.25), [0.25, 0.75]);
    expectMix(m.interpolate(0, 0.5), [0.5, 0.5]);
    expectMix(m.interpolate(0, 0.75), [0.75, 0.25]);
    expect(m.interpolate(0, 1)).toEqual([1, 0]);
    expect(m.interpolate(1, 1)).toEqual([1, 0]);
  });

  it("does not blend across a hop: the upper level holds to the middle of the step", () => {
    const m = tinyMath(HOP, HOP);
    expect(m.interpolate(0, 0.2)).toEqual([0, 1]);
    expect(m.interpolate(0, 0.249)).toEqual([0, 1]);
    expect(m.interpolate(0, 0.25)).toEqual([0.5, 0.5]);
    expect(m.interpolate(0, 0.5)).toEqual([0.5, 0.5]);
    // the next step is no hop and blends as usual
    expectMix(m.interpolate(0, 0.75), [0.75, 0.25]);
    expect(m.interpolate(0, 1)).toEqual([1, 0]);
  });

  it("stays on the peak where the ladder has a plateau", () => {
    const m = tinyMath(PLATEAU, PLATEAU);
    expectMix(m.interpolate(0, 0.25), [0.1, 0.9]);
    expect(m.interpolate(0, 0.75)).toEqual([0.2, 0.8]);
    expect(m.interpolate(0, 1)).toEqual([0.2, 0.8]);
    expect(m.ladderCollapsed(0.5)).toBe(false);
  });

  it("combines the two neighbouring columns by the column fraction", () => {
    const m = tinyMath(FULL, SHORT, COLLAPSED);
    expectMix(m.interpolate(0.5, 0.5), [0.4375, 0.5625]);
    expectMix(m.interpolate(0.25, 1), [0.875, 0.125]);
    // next to a collapsed column only the other column moves with t
    expectMix(m.interpolate(1.5, 0), [0.375, 0.625]);
    expectMix(m.interpolate(1.5, 1), [0.5, 0.5]);
    expect(m.interpolate(2, 0.7)).toEqual([0.5, 0.5]);
  });

  it("is constant in t where the ladders are collapsed, without renormalizing", () => {
    const heavy: Column = { levels: Array(3).fill([0.5, 0.5000005]), collapsed: true };
    const m = tinyMath(COLLAPSED, heavy, FULL);
    for (const s of [0, 0.25, 0.5, 1]) {
      const at0 = m.interpolate(s, 0);
      for (const t of [0.3, 1]) expect(m.interpolate(s, t), `s=${s}, t=${t}`).toEqual(at0);
      expect(sum(at0)).toBeCloseTo(1 + 5e-7 * s, 12);
    }
    expect(m.interpolate(1.5, 0)).not.toEqual(m.interpolate(1.5, 1));
  });

  it("equals the Python reference on the fixture", () => {
    // sum((i + 1) * w_i) of portfoliosight.engine.surface.interpolate(tensor, s, t)
    const reference: [number, number, number][] = [
      [0.625, 0.5, 13.562826330688583],
      [1.0, 1.0, 13.337987608148868],
      [3.25, 0.2, 13.779159052339946],
      [10.5, 0.75, 14.136803856701988],
      [12.0, 0.4, 15.176797417988647],
      [19.25, 0.333, 13.161744353629249],
      [30.875, 0.9, 8.158569927140386],
      [46.5, 0.05, 5.78180799298763],
      [47.0, 0.0, 6.0],
      [47.0, 0.6, 4.426989033071524],
    ];
    for (const [s, t, want] of reference) {
      const got = M.interpolate(s, t).reduce((acc, v, i) => acc + (i + 1) * v, 0);
      expect(rel(got, want), `(s=${s}, t=${t})`).toBeLessThanOrEqual(1e-12);
    }
  });

  it("keeps the 4.11 invariants at 200 random positions and never renormalizes", () => {
    const rnd = seeded(411);
    for (let i = 0; i < 200; i++) {
      const s = rnd() * (NX - 1);
      const t = rnd();
      const w = M.interpolate(s, t);
      const where = `(s=${s}, t=${t})`;
      const st = ownStats(RAW, w);
      expect(Array.isArray(w) && w.length === N, where).toBe(true);
      expect(Math.abs(sum(w) - 1), where).toBeLessThanOrEqual(1e-6);
      w.forEach((v, k) => expect(v >= RAW.bounds.min[k] - 1e-6 && v <= RAW.bounds.max[k] + 1e-6, `${where} weight ${k} = ${v}`).toBe(true));
      expect(st.sigma, where).toBeLessThanOrEqual(M.ceiling(s) + 1e-6);
      expect(st.enb >= 1 - 1e-6 && st.enb <= N + 1e-6, `${where} ENB ${st.enb}`).toBe(true);
      // both ends are the plain combinations of the tensor's own columns
      expect(maxDiff(M.interpolate(s, 0), nodeMix(RAW.frontier.w, s)), where).toBeLessThanOrEqual(1e-12);
      expect(maxDiff(M.interpolate(s, 1), nodeMix(peaksOf(RAW), s)), where).toBeLessThanOrEqual(1e-12);
      expect(maxDiff(M.mostDiversified(s), nodeMix(peaksOf(RAW), s)), where).toBeLessThanOrEqual(1e-15);
    }
  });

  it("returns a fresh array and never hands out the tensor's own rows", () => {
    const T = parseTensor(clone());
    const m = portfolioMath(T);
    for (const w of [m.interpolate(0, 0.5), m.interpolate(5, 0), m.interpolate(5, 1), m.mostDiversified(5)]) w.fill(9);
    expect(T.frontier.w).toEqual(RAW.frontier.w);
    expect(T.ladder.w).toEqual(RAW.ladder.w);
  });

  it("refuses a position outside [0, nx - 1] x [0, 1]", () => {
    for (const [s, t] of [[-0.001, 0.5], [NX - 0.999, 0.5], [3, -0.001], [3, 1.001], [Number.NaN, 0.5], [3, Number.NaN]]) {
      expect(() => M.interpolate(s, t), `(${s}, ${t})`).toThrow(RangeError);
    }
    expect(() => M.tAuto(NX)).toThrow(RangeError);
    expect(() => M.ceiling(-1)).toThrow(RangeError);
  });
});

describe("frontier curve and risk slider domain", () => {
  const M = portfolioMath(parseTensor(clone()));

  it("recomputes the 377 points of the fixture to 1e-9 relative", () => {
    const curve = M.frontierCurve();
    expect(curve.sigma).toHaveLength(8 * (NX - 1) + 1);
    expect(curve.mu).toHaveLength(8 * (NX - 1) + 1);
    curve.sigma.forEach((v, i) => expect(rel(v, RAW.frontier_curve.sigma[i]), `sigma ${i}`).toBeLessThanOrEqual(1e-9));
    curve.mu.forEach((v, i) => expect(rel(v, RAW.frontier_curve.mu[i]), `mu ${i}`).toBeLessThanOrEqual(1e-9));
  });

  it("follows the weights, not the shipped curve", () => {
    // tiny() ships a curve of 0.5 everywhere; the real locus runs from [0, 1] to [0.25, 0.75]
    const curve = tinyMath(FULL, SHORT).frontierCurve();
    expect(curve.sigma).toHaveLength(9);
    expect(curve.sigma[0]).toBeCloseTo(0.2, 15);
    expect(curve.mu[0]).toBeCloseTo(0.1, 15);
    expect(curve.mu[4]).toBeCloseTo(0.09, 15);
    expect(curve.sigma[4]).toBeCloseTo(Math.sqrt(0.125 ** 2 * 0.01 + 0.875 ** 2 * 0.04), 15);
    expect(curve.sigma[8]).toBeCloseTo(Math.sqrt(0.25 ** 2 * 0.01 + 0.75 ** 2 * 0.04), 15);
  });

  it("takes the domain's left end from the tensor: the engine reads it off the one-year range", () => {
    expect(M.riskSliderDomain()).toEqual({ s_safe: RAW.frontier.s_safe, s_max: NX - 1 });
    // the rule is the engine's (spec 4.9): the rightmost frontier node with the best bad year
    const bad: number[] = RAW.frontier.range.bad;
    expect(RAW.frontier.s_safe).toBe(bad.lastIndexOf(Math.max(...bad)));
    expect(portfolioMath(parseTensor(tiny([FULL, SHORT, COLLAPSED], 1.5))).riskSliderDomain()).toEqual({ s_safe: 1.5, s_max: 2 });
    expect(tinyMath(COLLAPSED, COLLAPSED, COLLAPSED).riskSliderDomain()).toEqual({ s_safe: 0, s_max: 2 });
  });
});

describe("slider helpers", () => {
  const M = portfolioMath(parseTensor(clone()));

  it("tSug is the suggested point's position on its column's ladder", () => {
    const m = tinyMath(FULL, SHORT, { ...SHORT, tSug: undefined }, { ...COLLAPSED, tSug: 0.5 }, PLATEAU);
    expect(m.tSug(0)).toBe(0.5);
    expect(m.tSug(1)).toBe(1);
    expect(m.tSug(2)).toBe(0);
    expect(m.tSug(3), "a collapsed ladder").toBe(0);
    expect(m.tSug(4)).toBe(0);
    expect(() => m.tSug(5)).toThrow(RangeError);
    for (let j = 0; j < NX; j++) {
      const want = RAW.ladder.collapsed[j] ? 0 : RAW.ladder.t_suggested[j];
      expect(M.tSug(j), `column ${j}`).toBe(want);
      // the suggested point is a ladder level: its mix earns the stored return
      expect(rel(M.stats(M.interpolate(j, M.tSug(j))).mu, RAW.ladder.y_suggested[j]), `column ${j}`).toBeLessThanOrEqual(1e-9);
    }
  });

  it("tAuto interpolates tSug between the neighbouring columns", () => {
    const m = tinyMath(FULL, COLLAPSED, SHORT);
    expect(m.tAuto(0)).toBeCloseTo(0.5, 14);
    expect(m.tAuto(0.5)).toBeCloseTo(0.25, 14);
    expect(m.tAuto(1)).toBe(0);
    expect(m.tAuto(1.75)).toBeCloseTo(0.75, 14);
    expect(m.tAuto(2)).toBeCloseTo(1, 14);
    expect(M.tAuto(20.25)).toBeCloseTo(0.75 * M.tSug(20) + 0.25 * M.tSug(21), 12);
  });

  it("ceiling is the risk ceiling X(s)", () => {
    const m = tinyMath(FULL, SHORT, COLLAPSED);
    expect(m.ceiling(0)).toBe(0.1);
    expect(m.ceiling(0.25)).toBeCloseTo(0.1125, 15);
    expect(m.ceiling(1.5)).toBeCloseTo(0.175, 15);
    expect(m.ceiling(2)).toBeCloseTo(0.2, 15);
    expect(M.ceiling(7)).toBe(RAW.frontier.x[7]);
    expect(M.ceiling(NX - 1)).toBe(RAW.frontier.x[NX - 1]);
  });

  it("ladderCollapsed says where the diversification slider has nothing to move", () => {
    const m = tinyMath(COLLAPSED, COLLAPSED, FULL, COLLAPSED);
    expect(m.ladderCollapsed(0.5), "both neighbours collapsed").toBe(true);
    expect(m.ladderCollapsed(1.5), "one neighbour has a ladder").toBe(false);
    expect(m.ladderCollapsed(2.5)).toBe(false);
    // on a column itself only that column counts
    expect([0, 1, 2, 3].map((s) => m.ladderCollapsed(s))).toEqual([true, true, false, true]);
    for (const s of [0, 0.5, 1, 1.5, 2, 2.5, 3]) {
      const moves = maxDiff(m.interpolate(s, 0), m.interpolate(s, 1)) > 0;
      expect(m.ladderCollapsed(s), `s=${s}`).toBe(!moves);
    }
    expect(M.ladderCollapsed(0)).toBe(true);
    expect(M.ladderCollapsed(0.625)).toBe(false);
  });

  it("mostDiversified is the combination of the neighbouring most diversified mixes", () => {
    const m = tinyMath(FULL, SHORT, COLLAPSED);
    expect(m.mostDiversified(0)).toEqual([1, 0]);
    expectMix(m.mostDiversified(0.5), [0.75, 0.25]);
    expect(m.mostDiversified(2)).toEqual([0.5, 0.5]);
  });

  it("sAtCeiling inverts the ceiling and stays inside the slider domain", () => {
    const m = tinyMath(SHORT, FULL, FULL);
    expect(m.riskSliderDomain()).toEqual({ s_safe: 0, s_max: 2 });
    expect(m.sAtCeiling(0.125)).toBeCloseTo(0.5, 12);
    expect(m.sAtCeiling(0.19)).toBeCloseTo(1.8, 12);
    expect(m.sAtCeiling(0.01)).toBe(0);
    expect(m.sAtCeiling(0.9)).toBe(2);

    const { s_safe, s_max } = M.riskSliderDomain();
    for (const s of [s_safe, 3.3, 19.25, 46.999, s_max]) expect(M.sAtCeiling(M.ceiling(s)), `s=${s}`).toBeCloseTo(s, 9);
    expect(M.sAtCeiling(M.ceiling(0.25)), "a mix calmer than the domain's left end").toBe(s_safe);
    expect(M.sAtCeiling(0)).toBe(s_safe);
    expect(M.sAtCeiling(5)).toBe(s_max);
  });
});
