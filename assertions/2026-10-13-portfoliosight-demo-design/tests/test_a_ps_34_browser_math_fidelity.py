# ruff: noqa: E501
"""A-PS-34 — browser math reproduces the tensor and interpolation keeps every invariant.

Vitest leg run from pytest (stdlib only). The embedded spec runs in vitest's plain node
environment (no jsdom).

Pinned interface
- `web/fixtures/guide2017_5y.json`: a spec §7 tensor (the UI fixture).
- `web/src/api/client.ts`: `parseTensor(json: unknown)` (zod; throws on a bad tensor; importing the
  module has no side effects and needs no DOM). It must accept a tensor whose weights are inside
  the §4.11 tolerances (a column whose weights sum to 1 + 5e-7) and whose `frontier_curve` is stale.
- `web/src/math/portfolio.ts`: `portfolioMath(tensor)` (the value returned by `parseTensor`) with
  `stats(w) -> {mu, sigma, enb}`, `range6m(mu, sigma) -> {low, typical, high}`,
  `interpolate(s, t) -> number[]`, `frontierCurve() -> {sigma: number[], mu: number[]}` (recomputed
  from `frontier.w` and the moments, never a copy of `tensor.frontier_curve`),
  `riskSliderDomain() -> {s_safe, s_max}`.

Every expected value is recomputed by this test from the tensor's own fields (spec §4.6, §4.9,
§4.11); the frontier mixes' ENB is recomputed here in Python and injected into the spec.

Nearest-faithful encodings (the tensor carries no sigma for a node other than these):
- sigma of a frontier node is compared with `frontier_curve.sigma[8j]` (1e-9 relative) and with the
  ceiling `frontier.x[j]` by the spec §4.5 rule (`<= X_j + 1e-6`; `|sigma - X_j| <= 1e-6` below the
  last column), because a solver at 1e-8 cannot put sigma on `X_j` to 1e-9;
- a grid node has `Z[j][k]` for its ENB; its mu and sigma are checked against the independent
  recomputation and the cell's constraints (`sigma <= X_j + 1e-6`, `mu >= Y_k - 1e-6`).
"""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
FIXTURE = WEB / "fixtures" / "guide2017_5y.json"

SPEC_TS = r"""
import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";

const PY_FRONTIER_ENB: number[] = __PY_FRONTIER_ENB__;
const RAW: any = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf-8"));
const N: number = RAW.universe.funds.length;
const NX: number = RAW.frontier.x.length;
const NY: number = RAW.grid.y.length;

// ---- the test's own math (spec 4.6, 4.9, 4.11); nothing below comes from the product ----
const dot = (a: number[], b: number[]) => a.reduce((acc, v, i) => acc + v * b[i], 0);
const sum = (a: number[]) => a.reduce((acc, v) => acc + v, 0);
const close = (a: number, b: number, rel = 1e-9) =>
  Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= rel * Math.max(Math.abs(a), Math.abs(b)) + 1e-12;
const mix = (a: number[], b: number[], f: number) => a.map((v, i) => (1 - f) * v + f * b[i]);
const maxDiff = (a: number[], b: number[]) =>
  a.length === b.length ? a.reduce((acc, v, i) => Math.max(acc, Math.abs(v - b[i])), 0) : Infinity;

function ownStats(T: any, w: number[]) {
  const mu = dot(w, T.mu_s);
  const variance = dot(w, T.cov.map((row: number[]) => dot(row, w)));
  const b: number[] = T.torsion_inv_t.map((row: number[]) => dot(row, w));
  let h = 0;
  for (let i = 0; i < w.length; i++) {
    const p = (T.torsion_lambda[i] * b[i] * b[i]) / variance;
    if (p > 0) h -= p * Math.log(p);
  }
  return { mu, sigma: Math.sqrt(variance), enb: Math.exp(h) };
}

let ladderEntries = 0;
function ladder(T: any, j: number) {
  const w: number[][] = [T.frontier.w[j]];
  const y: number[] = [T.frontier.y[j]];
  const kDiv: number = T.grid.k_div[j];
  if (kDiv >= 0) {
    let started = false;
    for (let k = NY - 1; k >= kDiv; k--) {
      const cell = T.grid.w[j][k];
      if (cell === null) {
        if (started) throw new Error(`null cell (${j},${k}) between the frontier and k_div: it would enter the ladder`);
        continue;
      }
      started = true;
      w.push(cell);
      y.push(Math.min(y[y.length - 1], T.grid.y[k]));
      ladderEntries += 1;
    }
    if (!started) throw new Error(`column ${j}: k_div=${kDiv} points at a null cell`);
  }
  return { w, y };
}

function ownColumn(T: any, j: number, t: number): number[] {
  const L = ladder(T, j);
  const last = L.w.length - 1;
  if (last === 0) return L.w[0].slice();
  const span = L.y[0] - L.y[last];
  if (!(span > 0)) return (t >= 1 ? L.w[last] : L.w[0]).slice();
  const y = L.y[0] - t * span;
  for (let i = 0; i < last; i++) {
    if (y >= L.y[i + 1] || i === last - 1) {
      const seg = L.y[i] - L.y[i + 1];
      const f = seg > 0 ? Math.min(1, Math.max(0, (L.y[i] - y) / seg)) : 0;
      return mix(L.w[i], L.w[i + 1], f);
    }
  }
  throw new Error("unreachable");
}

function split(s: number) {
  const j = Math.min(Math.floor(s), NX - 1);
  return { j, lam: s - j };
}
function ownInterp(T: any, s: number, t: number): number[] {
  const { j, lam } = split(s);
  return lam === 0 ? ownColumn(T, j, t) : mix(ownColumn(T, j, t), ownColumn(T, j + 1, t), lam);
}
function ownNodeMix(cols: number[][], s: number): number[] {
  const { j, lam } = split(s);
  return lam === 0 ? cols[j].slice() : mix(cols[j], cols[j + 1], lam);
}
function ownCurve(T: any) {
  const sigma: number[] = [];
  const mu: number[] = [];
  for (let i = 0; i <= 8 * (NX - 1); i++) {
    const st = ownStats(T, ownNodeMix(T.frontier.w, i / 8));
    sigma.push(st.sigma);
    mu.push(st.mu);
  }
  return { sigma, mu };
}
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function positions(count: number): Array<{ s: number; t: number }> {
  const rnd = mulberry32(20261013);
  const out: Array<{ s: number; t: number }> = [];
  for (let i = 0; i < count; i++) out.push({ s: rnd() * (NX - 1), t: rnd() });
  return out;
}

// A copy of the fixture with two adjacent collapsed columns whose weights sum to 1 + 5e-7.
const J0 = Math.floor(NX / 2);
function miniTensor() {
  const T = structuredClone(RAW);
  for (const j of [J0, J0 + 1]) {
    const scale = (1 + 5e-7) / sum(T.frontier.w[j]);
    T.frontier.w[j] = T.frontier.w[j].map((v: number) => v * scale);
    T.grid.k_div[j] = -1;
    T.grid.w_div[j] = T.frontier.w[j].slice();
    T.grid.y_div[j] = T.frontier.y[j];
    T.grid.y_sug[j] = T.frontier.y[j];
  }
  return T;
}

let M: any;
let portfolioMath: any;
let parseTensor: any;

describe("A-PS-34", () => {
  beforeAll(async () => {
    ({ portfolioMath } = await import("../../src/math/portfolio"));
    ({ parseTensor } = await import("../../src/api/client"));
    expect(typeof portfolioMath).toBe("function");
    expect(typeof parseTensor).toBe("function");
    M = portfolioMath(parseTensor(structuredClone(RAW)));
  });

  it("stats equals the tensor at every frontier node and grid node", () => {
    const bad: string[] = [];
    expect(PY_FRONTIER_ENB.length).toBe(NX);
    expect(RAW.frontier_curve.sigma.length).toBe(8 * (NX - 1) + 1);
    for (let j = 0; j < NX; j++) {
      const w: number[] = RAW.frontier.w[j];
      const st = M.stats(w);
      const own = ownStats(RAW, w);
      if (!close(st.mu, own.mu) || !close(st.sigma, own.sigma) || !close(st.enb, own.enb)) bad.push(`frontier ${j}: stats differ from the recomputation`);
      if (!close(st.mu, RAW.frontier.y[j])) bad.push(`frontier ${j}: mu ${st.mu} != frontier.y ${RAW.frontier.y[j]}`);
      if (!close(st.mu, RAW.frontier_curve.mu[8 * j])) bad.push(`frontier ${j}: mu != frontier_curve.mu[${8 * j}]`);
      if (!close(st.sigma, RAW.frontier_curve.sigma[8 * j])) bad.push(`frontier ${j}: sigma != frontier_curve.sigma[${8 * j}]`);
      if (!(st.sigma <= RAW.frontier.x[j] + 1e-6)) bad.push(`frontier ${j}: sigma ${st.sigma} above the ceiling ${RAW.frontier.x[j]}`);
      if (j < NX - 1 && Math.abs(st.sigma - RAW.frontier.x[j]) > 1e-6) bad.push(`frontier ${j}: sigma ${st.sigma} is not on X_j ${RAW.frontier.x[j]}`);
      if (!close(st.enb, PY_FRONTIER_ENB[j])) bad.push(`frontier ${j}: enb ${st.enb} != Python ${PY_FRONTIER_ENB[j]}`);
    }
    let cells = 0;
    let nulls = 0;
    for (let j = 0; j < NX; j++) {
      for (let k = 0; k < NY; k++) {
        const w = RAW.grid.w[j][k];
        const z = RAW.grid.z[j][k];
        if (w === null || z === null) {
          if (w !== null || z !== null) bad.push(`cell (${j},${k}): w and z disagree on null`);
          nulls += 1;
          continue;
        }
        cells += 1;
        const st = M.stats(w);
        const own = ownStats(RAW, w);
        if (!close(st.enb, z)) bad.push(`cell (${j},${k}): enb ${st.enb} != Z ${z}`);
        if (!close(st.mu, own.mu) || !close(st.sigma, own.sigma) || !close(st.enb, own.enb)) bad.push(`cell (${j},${k}): stats differ from the recomputation`);
        if (!(st.sigma <= RAW.frontier.x[j] + 1e-6)) bad.push(`cell (${j},${k}): sigma above X_j`);
        if (!(st.mu >= RAW.grid.y[k] - 1e-6)) bad.push(`cell (${j},${k}): mu below Y_k`);
      }
    }
    expect(bad.slice(0, 8).join("\n")).toBe("");
    expect(cells + nulls).toBe(NX * NY);
    expect(cells).toBeGreaterThanOrEqual(NX);
  });

  it("200 random positions keep the 4.11 invariants and match the independent ladder", () => {
    const bad: string[] = [];
    const pos = positions(200);
    ladderEntries = 0;
    for (const { s, t } of pos) {
      const w: number[] = M.interpolate(s, t);
      const tag = `(s=${s}, t=${t})`;
      if (!Array.isArray(w) || w.length !== N || !w.every((v) => Number.isFinite(v))) {
        bad.push(`${tag}: not a finite vector of length N`);
        continue;
      }
      const { j, lam } = split(s);
      const ceiling = lam === 0 ? RAW.frontier.x[j] : (1 - lam) * RAW.frontier.x[j] + lam * RAW.frontier.x[j + 1];
      const own = ownStats(RAW, w);
      const st = M.stats(w);
      const expected = ownInterp(RAW, s, t);
      if (Math.abs(sum(w) - 1) > 1e-6) bad.push(`${tag}: sum ${sum(w)}`);
      w.forEach((v, i) => {
        if (v < RAW.bounds.min[i] - 1e-6 || v > RAW.bounds.max[i] + 1e-6) bad.push(`${tag}: weight ${i} outside its bounds`);
      });
      if (!(own.sigma <= ceiling + 1e-6)) bad.push(`${tag}: sigma ${own.sigma} above X(s) ${ceiling}`);
      if (!(own.enb >= 1 - 1e-6 && own.enb <= N + 1e-6)) bad.push(`${tag}: ENB ${own.enb} outside [1, N]`);
      if (!close(st.mu, own.mu) || !close(st.sigma, own.sigma) || !close(st.enb, own.enb)) bad.push(`${tag}: stats differ from the recomputation`);
      if (maxDiff(w, expected) > 1e-9) bad.push(`${tag}: differs from the 4.11 ladder interpolation by ${maxDiff(w, expected)}`);
      if (Math.abs(sum(w) - sum(expected)) > 1e-12) bad.push(`${tag}: sum is not the convex combination's sum (renormalized or clipped)`);
    }
    expect(bad.slice(0, 8).join("\n")).toBe("");
    expect(pos.length).toBe(200);
    // the ladders used above were built from non-null cells only (ladder() throws on a null)
    expect(ladderEntries).toBeGreaterThan(0);
  });

  it("t=0 is the frontier combination and t=1 the most-diversified combination", () => {
    const bad: string[] = [];
    const ss = positions(200).map((p) => p.s).concat([0, 1, NX - 2, NX - 1, 0.5, NX - 1.5]);
    for (const s of ss) {
      const front = ownNodeMix(RAW.frontier.w, s);
      const div = ownNodeMix(RAW.grid.w_div, s);
      const w0: number[] = M.interpolate(s, 0);
      const w1: number[] = M.interpolate(s, 1);
      if (maxDiff(w0, front) > 1e-12) bad.push(`s=${s}: interpolate(s, 0) differs from (1-l)w_front[j] + l w_front[j+1] by ${maxDiff(w0, front)}`);
      if (maxDiff(w1, div) > 1e-12) bad.push(`s=${s}: interpolate(s, 1) differs from (1-l)w_div[j] + l w_div[j+1] by ${maxDiff(w1, div)}`);
      if (Math.abs(sum(w0) - sum(front)) > 1e-12 || Math.abs(sum(w1) - sum(div)) > 1e-12) bad.push(`s=${s}: sum was rescaled`);
    }
    expect(bad.slice(0, 8).join("\n")).toBe("");
    expect(ss.length).toBe(206);
  });

  it("collapsed ladders are constant in t and nothing is renormalized", () => {
    const T = miniTensor();
    const mini = portfolioMath(parseTensor(structuredClone(T)));
    let checked = 0;
    for (const s of [J0, J0 + 0.25, J0 + 0.5, J0 + 0.875, J0 + 1]) {
      const expected = ownNodeMix(T.frontier.w, s);
      const at0: number[] = mini.interpolate(s, 0);
      for (const t of [0, 0.3, 1]) {
        const w: number[] = mini.interpolate(s, t);
        expect(maxDiff(w, at0), `collapsed pair moved with t at s=${s}, t=${t}`).toBeLessThanOrEqual(1e-15);
        expect(maxDiff(w, expected), `s=${s}, t=${t}`).toBeLessThanOrEqual(1e-12);
        expect(Math.abs(sum(w) - sum(expected))).toBeLessThanOrEqual(1e-12);
        // the columns sum to 1 + 5e-7: a renormalized result would sum to 1
        expect(Math.abs(sum(w) - 1)).toBeGreaterThan(4e-7);
        expect(Math.abs(sum(w) - 1)).not.toBeLessThan(4e-7);
        checked += 1;
      }
    }
    expect(checked).toBe(15);
    // a neighbouring, non-collapsed column still moves with t (the constancy above is not global)
    const moving = Array.from({ length: NX }, (_, j) => j).find((j) => RAW.grid.k_div[j] >= 0 && maxDiff(RAW.grid.w_div[j], RAW.frontier.w[j]) > 1e-6);
    expect(moving, "the fixture has no column with a non-collapsed ladder").not.toBeUndefined();
    expect(maxDiff(M.interpolate(moving as number, 0), M.interpolate(moving as number, 1))).toBeGreaterThan(1e-6);
  });

  it("frontierCurve and s_safe are recomputed and equal the tensor", () => {
    const bad: string[] = [];
    const curve = M.frontierCurve();
    const own = ownCurve(RAW);
    expect(curve.sigma.length).toBe(8 * (NX - 1) + 1);
    expect(curve.mu.length).toBe(8 * (NX - 1) + 1);
    for (let i = 0; i < own.sigma.length; i++) {
      if (!close(curve.sigma[i], RAW.frontier_curve.sigma[i]) || !close(curve.mu[i], RAW.frontier_curve.mu[i])) bad.push(`point ${i}: differs from tensor.frontier_curve`);
      if (!close(curve.sigma[i], own.sigma[i]) || !close(curve.mu[i], own.mu[i])) bad.push(`point ${i}: differs from the recomputed locus`);
    }
    expect(bad.slice(0, 8).join("\n")).toBe("");
    const low = own.mu.map((m, i) => m / 2 - (1.96 * own.sigma[i]) / Math.sqrt(2));
    const best = Math.max(...low);
    const sSafe = low.lastIndexOf(best) / 8;
    const domain = M.riskSliderDomain();
    expect(Math.abs(sSafe - RAW.frontier.s_safe)).toBeLessThanOrEqual(1e-12);
    expect(Math.abs(domain.s_safe - RAW.frontier.s_safe)).toBeLessThanOrEqual(1e-12);
    expect(domain.s_max).toBe(NX - 1);
    // recomputed, not copied: on a tensor whose frontier.w changed, the curve follows the weights
    const T = miniTensor();
    const mini = portfolioMath(parseTensor(structuredClone(T))).frontierCurve();
    const ownMini = ownCurve(T);
    expect(close(ownMini.sigma[8 * J0], T.frontier_curve.sigma[8 * J0])).toBe(false);
    for (const i of [8 * J0, 8 * J0 + 4, 8 * J0 + 8]) {
      expect(close(mini.sigma[i], ownMini.sigma[i]), `mini curve point ${i} is not recomputed from frontier.w`).toBe(true);
      expect(close(mini.mu[i], ownMini.mu[i])).toBe(true);
      expect(close(mini.sigma[i], T.frontier_curve.sigma[i])).not.toBe(true);
    }
  });

  it("range6m is mu/2 -+ 1.96 sigma/sqrt 2", () => {
    const rnd = mulberry32(99);
    let checked = 0;
    for (let i = 0; i < 50; i++) {
      const mu = rnd() * 0.3 - 0.05;
      const sigma = rnd() * 0.4;
      const r = M.range6m(mu, sigma);
      expect(Math.abs(r.typical - mu / 2)).toBeLessThanOrEqual(1e-12);
      expect(Math.abs(r.low - (mu / 2 - (1.96 * sigma) / Math.sqrt(2)))).toBeLessThanOrEqual(1e-12);
      expect(Math.abs(r.high - (mu / 2 + (1.96 * sigma) / Math.sqrt(2)))).toBeLessThanOrEqual(1e-12);
      checked += 1;
    }
    expect(checked).toBe(50);
    const st = M.stats(RAW.frontier.w[0]);
    const r0 = M.range6m(st.mu, st.sigma);
    expect(r0.low).not.toBe(r0.high);
  });
});
"""
EXPECTED_TITLES = {
    "stats equals the tensor at every frontier node and grid node",
    "200 random positions keep the 4.11 invariants and match the independent ladder",
    "t=0 is the frontier combination and t=1 the most-diversified combination",
    "collapsed ladders are constant in t and nothing is renormalized",
    "frontierCurve and s_safe are recomputed and equal the tensor",
    "range6m is mu/2 -+ 1.96 sigma/sqrt 2",
}


def _frontier_enb_in_python() -> list[float]:
    """ENB of every frontier mix, spec §4.6, from the fixture's own fields with plain lists."""
    assert FIXTURE.is_file(), (
        "web/fixtures/guide2017_5y.json is missing: the UI fixture tensor is not built yet"
    )
    tensor = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cov, inv_t, lam = tensor["cov"], tensor["torsion_inv_t"], tensor["torsion_lambda"]
    out = []
    for w in tensor["frontier"]["w"]:
        n = len(w)
        variance = sum(w[a] * cov[a][b] * w[b] for a in range(n) for b in range(n))
        bets = [sum(inv_t[a][b] * w[b] for b in range(n)) for a in range(n)]
        shares = [lam[a] * bets[a] ** 2 / variance for a in range(n)]
        out.append(math.exp(-sum(p * math.log(p) for p in shares if p > 0)))
    assert len(out) >= 2, "the fixture tensor has fewer than two frontier columns"
    return out


def _run_vitest(name: str, source: str, timeout: int = 300) -> dict[str, str]:
    """Run one embedded vitest file inside web/ and return {test title: status}."""
    assert (WEB / "package.json").is_file(), (
        "web/package.json is missing: the front end is not built yet"
    )
    vitest = WEB / "node_modules" / ".bin" / "vitest"
    assert vitest.exists(), "web/node_modules/.bin/vitest is missing: run `npm ci` in web/"
    gate_dir = WEB / "tests" / "__gate__"
    spec = gate_dir / f"{name}.test.ts"
    report = None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.json"
        try:
            gate_dir.mkdir(parents=True, exist_ok=True)
            spec.write_text(source, encoding="utf-8")
            proc = subprocess.run(
                [
                    str(vitest),
                    "run",
                    f"tests/__gate__/{name}.test.ts",
                    "--reporter=json",
                    f"--outputFile={out}",
                ],
                cwd=WEB,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if out.exists():
                report = json.loads(out.read_text(encoding="utf-8"))
        finally:
            spec.unlink(missing_ok=True)
            if gate_dir.is_dir() and not any(gate_dir.iterdir()):
                gate_dir.rmdir()
    tail = proc.stdout[-6000:] + proc.stderr[-3000:]
    assert report is not None, f"vitest wrote no JSON report:\n{tail}"
    statuses: dict[str, str] = {}
    for file_result in report.get("testResults", []):
        for case in file_result.get("assertionResults", []):
            statuses[case["title"]] = case["status"]
            if case["status"] != "passed":
                print(case["title"], "\n".join(case.get("failureMessages") or [])[:3000])
        if file_result.get("status") != "passed":
            print(file_result.get("message", ""))
    print(tail)
    return statuses


def test_a_ps_34_vitest():
    assert (WEB / "package.json").is_file(), (
        "web/package.json is missing: the front end is not built yet"
    )
    enb = _frontier_enb_in_python()
    assert not any(math.isnan(v) for v in enb), (
        "a frontier mix has a NaN ENB in the Python recomputation"
    )
    statuses = _run_vitest("a_ps_34", SPEC_TS.replace("__PY_FRONTIER_ENB__", json.dumps(enb)))
    assert set(statuses) == EXPECTED_TITLES, (
        f"vitest ran a different set of tests: {sorted(statuses)}"
    )
    not_passed = {title: status for title, status in statuses.items() if status != "passed"}
    assert not not_passed, f"vitest legs not passed (failed, skipped or todo): {not_passed}"
