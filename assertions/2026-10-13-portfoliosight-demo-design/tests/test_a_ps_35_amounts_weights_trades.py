# ruff: noqa: E501
"""A-PS-35 — amounts become weights in all three units, the 100% rule gates, trades per unit.

Vitest leg run from pytest (stdlib only). The embedded spec runs in vitest's plain node
environment (no jsdom).

Pinned interface (`web/src/math/amounts.ts`; arrays are in `universe.funds` order)
- `amountsToWeights(amounts: (number | null)[], unit: "shares" | "pct" | "usd",
  lastClose: (number | null)[])` returns `{status, weights, unknownPrice}`:
  `status "ok"` with `weights: number[]` summing to 1 (shares: `shares * last_close / sum`;
  pct and usd: `amount / sum`; a blank (`null`) amount counts as 0 once any amount is entered);
  `status "empty"` with `weights: null` when every amount is blank (tickers only);
  `status "invalid_total"` with `weights: null` when `unit` is `pct` and the total is outside
  100 +- 0.05; `status "unknown_price"` with `weights: null` when `unit` is `shares` and a fund
  holding shares has `last_close: null`. `unknownPrice` lists those funds' indices (else `[]`).
- `percentTotal(amounts: (number | null)[])` returns `{total, ok, message}`; `ok` is true exactly
  when `|total - 100| <= 0.05`; `message` reads the actual total, and below 100 it is exactly
  `"Adds up to {total}%: {100 - total}% to go"` with numbers printed without trailing zeros
  (`"Adds up to 92%: 8% to go"`).
- `tradeDeltas({wNow, wSel, unit, amounts, lastClose})` returns `{rows, turnover, value}`:
  `rows[i] = {dpp, dUsd, dShares, unknownPrice}` with `dpp = wSel[i] - wNow[i]` (a fraction),
  `value` = `V` (`sum shares * last_close` in shares mode, `sum amounts` in usd mode, `null` in pct
  mode), `dUsd = dpp * V` (`null` in pct mode), `dShares = round(dpp * V / last_close)` in shares
  mode only (`null` otherwise, and `null` with `unknownPrice: true` for a fund whose `last_close`
  is `null`), `turnover = sum max(dpp, 0)`.

Nearest-faithful encoding: "sum of dShares * last_close within one share's price of sum of d$"
cannot hold for an arbitrary number of funds (N rounding errors of up to half a share each), so the
test asserts the per-fund bound (`|dShares * last_close - d$| <= last_close / 2`) for every vector
and the aggregate "within the price of the dearest share" on two-fund menus, where it is a theorem.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"

SPEC_TS = r"""
import fs from "node:fs";
import path from "node:path";
import { beforeAll, describe, expect, it } from "vitest";

const fixturePath = path.resolve(process.cwd(), "fixtures/guide2017_5y.json");
let CLOSES: number[] = [];
let A: any;

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
const sum = (a: number[]) => a.reduce((acc, v) => acc + v, 0);
const near = (a: number, b: number, tol = 1e-9) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= tol * Math.max(1, Math.abs(a), Math.abs(b));

// a random amount vector over the first n funds: some blanks, at least one positive entry
function vector(rnd: () => number, n: number, scale: number, integer: boolean): (number | null)[] {
  const out: (number | null)[] = [];
  for (let i = 0; i < n; i++) {
    if (rnd() < 0.2) out.push(null);
    else out.push(integer ? Math.floor(rnd() * scale) : Math.round(rnd() * scale * 100) / 100);
  }
  out[Math.floor(rnd() * n)] = integer ? 1 + Math.floor(rnd() * scale) : Math.round((1 + rnd() * scale) * 100) / 100;
  return out;
}
function randomWeights(rnd: () => number, n: number): number[] {
  const raw = Array.from({ length: n }, () => (rnd() < 0.2 ? 0 : rnd()));
  raw[0] += 0.01;
  const total = sum(raw);
  return raw.map((v) => v / total);
}
// n numbers adding up to `total` (percent inputs)
function percents(rnd: () => number, n: number, total: number): number[] {
  const raw = Array.from({ length: n }, () => 0.05 + rnd());
  const s = sum(raw);
  return raw.map((v) => (v / s) * total);
}

describe("A-PS-35", () => {
  beforeAll(async () => {
    expect(fs.existsSync(fixturePath), "web/fixtures/guide2017_5y.json is missing").toBe(true);
    const tensor = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));
    CLOSES = tensor.universe.funds.map((f: any) => f.last_close).filter((v: any) => typeof v === "number" && v > 0);
    expect(CLOSES.length, "the fixture needs at least two funds with a last_close").toBeGreaterThanOrEqual(2);
    A = await import("../../src/math/amounts");
    for (const name of ["amountsToWeights", "percentTotal", "tradeDeltas"]) expect(typeof A[name], `amounts.ts must export ${name}`).toBe("function");
  });

  it("weights sum to 1 for 100 random vectors in each of the three units", () => {
    const rnd = mulberry32(35);
    const n = CLOSES.length;
    const counts: Record<string, number> = { shares: 0, pct: 0, usd: 0 };
    for (let i = 0; i < 100; i++) {
      const shares = vector(rnd, n, 500, i % 2 === 0);
      const rs = A.amountsToWeights(shares, "shares", CLOSES);
      expect(rs.status).toBe("ok");
      const values = shares.map((q, k) => (q ?? 0) * CLOSES[k]);
      const v = sum(values);
      expect(rs.weights.length).toBe(n);
      rs.weights.forEach((w: number, k: number) => expect(Math.abs(w - values[k] / v), `shares vector ${i}, fund ${k}`).toBeLessThanOrEqual(1e-12));
      expect(Math.abs(sum(rs.weights) - 1)).toBeLessThanOrEqual(1e-12);
      counts.shares += 1;

      const usd = vector(rnd, n, 20000, false);
      const ru = A.amountsToWeights(usd, "usd", CLOSES);
      expect(ru.status).toBe("ok");
      const totalUsd = sum(usd.map((x) => x ?? 0));
      ru.weights.forEach((w: number, k: number) => expect(Math.abs(w - (usd[k] ?? 0) / totalUsd), `usd vector ${i}, fund ${k}`).toBeLessThanOrEqual(1e-12));
      expect(Math.abs(sum(ru.weights) - 1)).toBeLessThanOrEqual(1e-12);
      counts.usd += 1;

      const total = 99.96 + rnd() * 0.08;
      const pct = percents(rnd, n, total);
      const rp = A.amountsToWeights(pct, "pct", CLOSES);
      expect(rp.status, `percent total ${total} is inside the band`).toBe("ok");
      const totalPct = sum(pct);
      rp.weights.forEach((w: number, k: number) => expect(Math.abs(w - pct[k] / totalPct), `pct vector ${i}, fund ${k}`).toBeLessThanOrEqual(1e-12));
      expect(Math.abs(sum(rp.weights) - 1)).toBeLessThanOrEqual(1e-12);
      counts.pct += 1;
    }
    expect(counts).toEqual({ shares: 100, pct: 100, usd: 100 });
    // the units are not interchangeable: the same numbers as shares and as dollars give different mixes
    const same = [10, 10].concat(Array(n - 2).fill(0));
    const asShares = A.amountsToWeights(same, "shares", CLOSES).weights;
    const asUsd = A.amountsToWeights(same, "usd", CLOSES).weights;
    expect(Math.abs(asUsd[0] - 0.5)).toBeLessThanOrEqual(1e-12);
    if (CLOSES[0] !== CLOSES[1]) expect(asShares[0]).not.toBe(asUsd[0]);
  });

  it("percent totals 99.9 and 100.1 are rejected, 99.96, 100.0 and 100.04 accepted", () => {
    // the five totals of the spec plus 99.94 and 100.06, which pin the band at 0.05
    const rnd = mulberry32(100);
    const n = CLOSES.length;
    const expected: Array<[number, boolean]> = [[99.9, false], [99.94, false], [99.96, true], [100.0, true], [100.04, true], [100.06, false], [100.1, false]];
    let checked = 0;
    for (const [total, ok] of expected) {
      const fixed = [60, total - 60];
      const vectors: number[][] = [fixed];
      for (let i = 0; i < 20; i++) vectors.push(percents(rnd, 2 + Math.floor(rnd() * (n - 1)), total));
      for (const amounts of vectors) {
        const padded: (number | null)[] = amounts.concat(Array(n - amounts.length).fill(null));
        const pt = A.percentTotal(padded);
        expect(Math.abs(pt.total - total)).toBeLessThanOrEqual(1e-9);
        expect(pt.ok, `total ${total}`).toBe(ok);
        const r = A.amountsToWeights(padded, "pct", CLOSES);
        if (ok) {
          expect(r.status).toBe("ok");
          expect(Math.abs(sum(r.weights) - 1)).toBeLessThanOrEqual(1e-12);
        } else {
          expect(r.status).toBe("invalid_total");
          expect(r.status).not.toBe("ok");
          expect(r.weights).toBeNull();
        }
        checked += 1;
      }
    }
    expect(checked).toBe(7 * 21);
  });

  it("the running-total message reads the actual total", () => {
    const pad = (xs: number[]): (number | null)[] => xs.concat(Array(Math.max(0, CLOSES.length - xs.length)).fill(null));
    expect(A.percentTotal(pad([60, 32])).message).toBe("Adds up to 92%: 8% to go");
    expect(A.percentTotal(pad([60, 32])).ok).toBe(false);
    expect(A.percentTotal(pad([25, 12.5])).message).toBe("Adds up to 37.5%: 62.5% to go");
    expect(A.percentTotal(pad([40, 30])).message).toBe("Adds up to 70%: 30% to go");
    const over = A.percentTotal(pad([80, 43]));
    expect(over.ok).toBe(false);
    expect(over.message).toContain("123");
    expect(over.message).not.toContain("92");
    expect(A.percentTotal(pad([60, 39.9])).message).toContain("99.9");
  });

  it("all-blank amounts give no allocation in every unit", () => {
    const blank = CLOSES.map(() => null);
    for (const unit of ["shares", "pct", "usd"]) {
      const r = A.amountsToWeights(blank, unit, CLOSES);
      expect(r.status, unit).toBe("empty");
      expect(r.weights, unit).toBeNull();
    }
    // one entered amount is an allocation again
    const one: (number | null)[] = CLOSES.map(() => null);
    one[1] = 5;
    expect(A.amountsToWeights(one, "usd", CLOSES).weights).not.toBeNull();
  });

  it("trade deltas and turnover follow the formulas in each unit", () => {
    const rnd = mulberry32(3535);
    const n = CLOSES.length;
    let checked = 0;
    for (let i = 0; i < 100; i++) {
      const wSel = randomWeights(rnd, n);
      const shares = vector(rnd, n, 400, true);
      const wNow: number[] = A.amountsToWeights(shares, "shares", CLOSES).weights;
      const V = sum(shares.map((q, k) => (q ?? 0) * CLOSES[k]));
      const d = A.tradeDeltas({ wNow, wSel, unit: "shares", amounts: shares, lastClose: CLOSES });
      expect(near(d.value, V)).toBe(true);
      expect(d.rows.length).toBe(n);
      let turnover = 0;
      for (let k = 0; k < n; k++) {
        const dpp = wSel[k] - wNow[k];
        turnover += Math.max(dpp, 0);
        expect(near(d.rows[k].dpp, dpp), `dpp ${i}/${k}`).toBe(true);
        expect(near(d.rows[k].dUsd, dpp * V), `dUsd ${i}/${k}`).toBe(true);
        const exact = (dpp * V) / CLOSES[k];
        if (Math.abs(Math.abs(exact % 1) - 0.5) > 1e-6) expect(d.rows[k].dShares + 0, `dShares ${i}/${k}`).toBe(Math.round(exact) + 0);
        expect(Number.isInteger(d.rows[k].dShares)).toBe(true);
        expect(Math.abs(d.rows[k].dShares * CLOSES[k] - d.rows[k].dUsd)).toBeLessThanOrEqual(CLOSES[k] / 2 + 1e-6);
        expect(d.rows[k].unknownPrice).toBe(false);
      }
      expect(near(d.turnover, turnover)).toBe(true);
      expect(d.turnover).toBeGreaterThanOrEqual(0);

      const usd = vector(rnd, n, 20000, false);
      const wNowUsd: number[] = A.amountsToWeights(usd, "usd", CLOSES).weights;
      const Vusd = sum(usd.map((x) => x ?? 0));
      const du = A.tradeDeltas({ wNow: wNowUsd, wSel, unit: "usd", amounts: usd, lastClose: CLOSES });
      const pct = percents(rnd, n, 100);
      const wNowPct: number[] = A.amountsToWeights(pct, "pct", CLOSES).weights;
      const dp = A.tradeDeltas({ wNow: wNowPct, wSel, unit: "pct", amounts: pct, lastClose: CLOSES });
      for (let k = 0; k < n; k++) {
        expect(near(du.rows[k].dUsd, (wSel[k] - wNowUsd[k]) * Vusd), `usd dUsd ${i}/${k}`).toBe(true);
        expect(du.rows[k].dShares).toBeNull();
        expect(near(dp.rows[k].dpp, wSel[k] - wNowPct[k])).toBe(true);
        expect(dp.rows[k].dUsd).toBeNull();
        expect(dp.rows[k].dShares).toBeNull();
      }
      expect(near(dp.turnover, sum(wSel.map((w, k) => Math.max(w - wNowPct[k], 0))))).toBe(true);
      checked += 1;
    }
    expect(checked).toBe(100);
    // two-fund menus: the share trades net out to within one share's price of the dollar trades
    let pairs = 0;
    for (let i = 0; i < 100; i++) {
      const a = Math.floor(rnd() * n);
      const b = (a + 1 + Math.floor(rnd() * (n - 1))) % n;
      const closes = [CLOSES[a], CLOSES[b]];
      const shares = [1 + Math.floor(rnd() * 300), 1 + Math.floor(rnd() * 300)];
      const wNow: number[] = A.amountsToWeights(shares, "shares", closes).weights;
      const x = rnd();
      const d = A.tradeDeltas({ wNow, wSel: [x, 1 - x], unit: "shares", amounts: shares, lastClose: closes });
      const viaShares = d.rows[0].dShares * closes[0] + d.rows[1].dShares * closes[1];
      const viaUsd = d.rows[0].dUsd + d.rows[1].dUsd;
      expect(Math.abs(viaShares - viaUsd)).toBeLessThanOrEqual(Math.max(closes[0], closes[1]) + 1e-6);
      pairs += 1;
    }
    expect(pairs).toBe(100);
  });

  it("a fund without a last close has an unknown price, never a number", () => {
    const n = CLOSES.length;
    const closes: (number | null)[] = CLOSES.slice();
    closes[1] = null;
    const held: (number | null)[] = CLOSES.map((_, k) => (k < 3 ? 10 : null));
    const r = A.amountsToWeights(held, "shares", closes);
    expect(r.status).toBe("unknown_price");
    expect(r.weights).toBeNull();
    expect(r.unknownPrice).toEqual([1]);
    // the same amounts are fine in dollars: the price is not needed there
    expect(A.amountsToWeights(held, "usd", closes).status).toBe("ok");
    // not held: the mix is known, but that fund's share trade is not
    const notHeld: (number | null)[] = CLOSES.map((_, k) => (k === 1 ? null : 10 + k));
    const now = A.amountsToWeights(notHeld, "shares", closes);
    expect(now.status).toBe("ok");
    expect(now.weights[1]).toBe(0);
    const wSel = Array(n).fill(1 / n);
    const d = A.tradeDeltas({ wNow: now.weights, wSel, unit: "shares", amounts: notHeld, lastClose: closes });
    expect(d.rows[1].unknownPrice).toBe(true);
    expect(d.rows[1].dShares).toBeNull();
    expect(typeof d.rows[1].dShares).not.toBe("number");
    expect(near(d.rows[1].dpp, 1 / n)).toBe(true);
    for (let k = 0; k < n; k++) {
      if (k === 1) continue;
      expect(d.rows[k].unknownPrice).toBe(false);
      expect(Number.isInteger(d.rows[k].dShares)).toBe(true);
    }
  });
});
"""
EXPECTED_TITLES = {
    "weights sum to 1 for 100 random vectors in each of the three units",
    "percent totals 99.9 and 100.1 are rejected, 99.96, 100.0 and 100.04 accepted",
    "the running-total message reads the actual total",
    "all-blank amounts give no allocation in every unit",
    "trade deltas and turnover follow the formulas in each unit",
    "a fund without a last close has an unknown price, never a number",
}


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


def test_a_ps_35_vitest():
    statuses = _run_vitest("a_ps_35", SPEC_TS)
    assert set(statuses) == EXPECTED_TITLES, (
        f"vitest ran a different set of tests: {sorted(statuses)}"
    )
    not_passed = {title: status for title, status in statuses.items() if status != "passed"}
    assert not not_passed, f"vitest legs not passed (failed, skipped or todo): {not_passed}"
