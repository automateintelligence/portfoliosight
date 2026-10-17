# ruff: noqa: E501
"""A-PS-36 — the URL codec round-trips every state.

Vitest leg run from pytest (stdlib only). The embedded spec runs in vitest's plain node
environment (no jsdom); importing `web/src/state/url.ts` must not need a DOM.

Pinned interface (`web/src/state/url.ts`)
- `encode(state: UrlState) -> string`: the query string with its leading `?`, holding only the
  spec §8.1 keys `u, f, unit, c, lb, g, r, d, t, x, e`, each at most once.
- `decode(search: string, domain?: {s_safe: number, s_max: number}) -> UrlState`: reads only those
  keys, ignores every other key, and clamps `r` into `[s_safe, s_max]` when `domain` is given.
- `UrlState` has exactly these fields:
  `preset: "guide2017" | "tsp" | null` (`u`; `null` = custom menu),
  `funds: {id: string, amount: number | null}[]` (`f`, `ID:amount`, amount optional; `[]` with a preset),
  `unit: "pct" | "usd" | "shares"` (`unit`; default `pct`),
  `caps: {id: string, min: number | null, max: number | null}[]` (`c`, `ID:min:max`, percent integers, blank = `null`),
  `lookback: "1y" | "2y" | "3y" | "5y" | "10y" | "ew"` (`lb`; default `5y`),
  `ghosts: string[]` (`g`; lookback ids), `r: number | null` (`null` = not in the URL),
  `d: "auto" | number` (default `auto`), `theme: "ks-dark" | "light" | "hud" | null` (`t`; `null` =
  not in the URL, so stored preference applies), `details: boolean` (`x=1`),
  `engine: "replay" | "garch" | "copula"` (`e`; the simulation, written only when it is not
  `replay`; any other value reads as `replay`).
- The spec example `?u=guide2017&lb=5y&r=19.25&d=auto&t=hud` must re-encode to itself, which fixes
  the key order `u, f, unit, c, lb, g, r, d, t, x`, that `lb` and `d` are written even at their
  defaults, and that `unit=pct`, an empty `f`/`c`/`g` and `x` off are omitted.
- `r` and `d` survive a round trip to within 1e-9 (values carry up to six decimals); every other
  field survives exactly.
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

const ALLOWED = new Set(["u", "f", "unit", "c", "lb", "g", "r", "d", "t", "x", "e"]);
const ENGINES = ["replay", "garch", "copula"];
const LOOKBACKS = ["1y", "2y", "3y", "5y", "10y", "ew"];
const UNITS = ["pct", "usd", "shares"];
const THEMES = [null, "ks-dark", "light", "hud", "grid"];
const fixturePath = path.resolve(process.cwd(), "fixtures/guide2017_5y.json");
let IDS: string[] = [];
let DOMAIN = { s_safe: 0, s_max: 0 };
let U: any;

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
const round = (x: number, places: number) => Math.round(x * 10 ** places) / 10 ** places;

function sample<T>(rnd: () => number, pool: T[], n: number): T[] {
  const copy = pool.slice();
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy.slice(0, n);
}

function generate(rnd: () => number) {
  const pick = <T,>(xs: T[]): T => xs[Math.floor(rnd() * xs.length)];
  const state: any = {};
  if (rnd() < 0.4) {
    state.preset = pick(["guide2017", "tsp"]);
    state.funds = [];
  } else {
    state.preset = null;
    const n = 2 + Math.floor(rnd() * (Math.min(30, IDS.length) - 1));
    const blank = rnd() < 0.3;
    state.funds = sample(rnd, IDS, n).map((id) => {
      if (blank || rnd() < 0.15) return { id, amount: null };
      return { id, amount: rnd() < 0.5 ? Math.floor(rnd() * 20000) : round(rnd() * 5000, 2) };
    });
  }
  state.unit = pick(UNITS);
  const capIds = sample(rnd, state.preset ? IDS : state.funds.map((f: any) => f.id), Math.floor(rnd() * 4));
  state.caps = capIds.map((id: string) => {
    const lo = Math.floor(rnd() * 20);
    const hi = lo + 1 + Math.floor(rnd() * (100 - lo));
    const which = rnd();
    if (which < 0.34) return { id, min: lo, max: hi };
    return which < 0.67 ? { id, min: null, max: hi } : { id, min: lo, max: null };
  });
  state.lookback = pick(LOOKBACKS);
  state.ghosts = LOOKBACKS.filter((lb) => lb !== state.lookback && rnd() < 0.3);
  const span = DOMAIN.s_max - DOMAIN.s_safe;
  const kind = rnd();
  if (kind < 0.1) state.r = null;
  else if (kind < 0.4) state.r = Math.min(DOMAIN.s_max, Math.ceil(DOMAIN.s_safe * 8 + rnd() * span * 8) / 8);
  else if (kind < 0.7) state.r = round(DOMAIN.s_safe + (Math.floor(rnd() * 201) * span) / 200, 6);
  else state.r = Math.min(DOMAIN.s_max, Math.max(DOMAIN.s_safe, round(DOMAIN.s_safe + rnd() * span, 4)));
  const dk = rnd();
  state.d = dk < 0.4 ? "auto" : dk < 0.5 ? 0 : dk < 0.6 ? 1 : round(rnd(), 6);
  state.theme = pick(THEMES);
  state.details = rnd() < 0.5;
  state.engine = pick(ENGINES);
  return state;
}

function sameState(got: any, want: any): string | null {
  if (got === null || typeof got !== "object") return "decode did not return an object";
  const strip = (s: any) => ({ ...s, r: null, d: null });
  try {
    expect(strip(got)).toEqual(strip(want));
  } catch (err: any) {
    return String(err.message).slice(0, 600);
  }
  if (want.r === null ? got.r !== null : !(typeof got.r === "number" && Math.abs(got.r - want.r) <= 1e-9)) return `r: got ${got.r}, want ${want.r}`;
  if (want.d === "auto" ? got.d !== "auto" : !(typeof got.d === "number" && Math.abs(got.d - want.d) <= 1e-9)) return `d: got ${got.d}, want ${want.d}`;
  return null;
}

function keysOf(search: string): string[] {
  expect(typeof search).toBe("string");
  return Array.from(new URLSearchParams(search.startsWith("?") ? search.slice(1) : search).keys());
}

describe("A-PS-36", () => {
  beforeAll(async () => {
    expect(fs.existsSync(fixturePath), "web/fixtures/guide2017_5y.json is missing").toBe(true);
    const tensor = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));
    IDS = tensor.universe.funds.map((f: any) => f.id);
    expect(IDS.length, "the fixture universe needs at least two funds").toBeGreaterThanOrEqual(2);
    DOMAIN = { s_safe: tensor.frontier.s_safe, s_max: tensor.frontier.x.length - 1 };
    U = await import("../../src/state/url");
    expect(typeof U.encode, "url.ts must export encode").toBe("function");
    expect(typeof U.decode, "url.ts must export decode").toBe("function");
  });

  it("600 generated states round-trip and encode emits only the 8.1 keys", () => {
    const rnd = mulberry32(8136);
    const bad: string[] = [];
    const seenKeys = new Set<string>();
    const seen = { preset: 0, custom: 0, amounts: 0, shares: 0, caps: 0, ghosts: 0, dNumber: 0 };
    let cases = 0;
    for (let i = 0; i < 600; i++) {
      const state = generate(rnd);
      const encoded: string = U.encode(structuredClone(state));
      const keys = keysOf(encoded);
      for (const k of keys) {
        seenKeys.add(k);
        if (!ALLOWED.has(k)) bad.push(`case ${i}: encode wrote the key "${k}" (${encoded})`);
      }
      if (new Set(keys).size !== keys.length) bad.push(`case ${i}: a key is repeated (${encoded})`);
      const decoded = i % 2 === 0 ? U.decode(encoded) : U.decode(encoded, DOMAIN);
      const diff = sameState(decoded, state);
      if (diff) bad.push(`case ${i}: ${encoded} -> ${diff}`);
      if (state.preset) seen.preset += 1;
      else seen.custom += 1;
      if (state.funds.some((f: any) => f.amount !== null)) seen.amounts += 1;
      if (state.unit === "shares") seen.shares += 1;
      if (state.caps.length) seen.caps += 1;
      if (state.ghosts.length) seen.ghosts += 1;
      if (state.d !== "auto") seen.dNumber += 1;
      cases += 1;
    }
    expect(bad.slice(0, 6).join("\n")).toBe("");
    expect(cases).toBeGreaterThanOrEqual(500);
    for (const [name, count] of Object.entries(seen)) expect(count, `the generator never produced "${name}"`).toBeGreaterThan(20);
    // every 8.1 key was exercised, and nothing else was ever written
    expect(Array.from(seenKeys).sort()).toEqual(Array.from(ALLOWED).sort());
    expect(Array.from(seenKeys).filter((k) => !ALLOWED.has(k))).toEqual([]);
  });

  it("the spec example decodes to the obvious state and re-encodes to itself", () => {
    const example = "?u=guide2017&lb=5y&r=19.25&d=auto&t=hud";
    const state = U.decode(example);
    expect(state).toEqual({
      preset: "guide2017",
      funds: [],
      unit: "pct",
      caps: [],
      lookback: "5y",
      ghosts: [],
      r: 19.25,
      d: "auto",
      theme: "hud",
      details: false,
      engine: "replay",
    });
    expect(U.encode(state)).toBe(example);
    // the spec's custom-menu example
    const custom = U.decode("?f=VTI:60,BND:40,VNQ&unit=shares&c=VTI::10,BND:5:&lb=ew&g=1y,10y&d=0.5&x=1");
    expect(custom.preset).toBeNull();
    expect(custom.funds).toEqual([{ id: "VTI", amount: 60 }, { id: "BND", amount: 40 }, { id: "VNQ", amount: null }]);
    expect(custom.unit).toBe("shares");
    expect(custom.caps).toEqual([{ id: "VTI", min: null, max: 10 }, { id: "BND", min: 5, max: null }]);
    expect(custom.lookback).toBe("ew");
    expect(custom.ghosts).toEqual(["1y", "10y"]);
    expect(custom.r).toBeNull();
    expect(custom.d).toBe(0.5);
    expect(custom.theme).toBeNull();
    expect(custom.details).toBe(true);
    expect(custom.engine).toBe("replay");
    // the simulation (engines spec 6): written last, after x, and only when it is not replay
    const engine = "?u=guide2017&lb=5y&r=19.25&d=auto&t=hud&x=1&e=garch";
    expect(U.decode(engine).engine).toBe("garch");
    expect(U.encode(U.decode(engine))).toBe(engine);
    expect(U.encode({ ...U.decode(engine), engine: "replay" })).toBe("?u=guide2017&lb=5y&r=19.25&d=auto&t=hud&x=1");
    expect(U.encode({ ...U.decode(engine), details: false, engine: "copula" })).toBe("?u=guide2017&lb=5y&r=19.25&d=auto&t=hud&e=copula");
    // an unknown value reads as replay and is not written back
    for (const bad of ["foo", "GARCH", "garch,copula", ""]) {
      const read = U.decode(`?u=tsp&e=${bad}`);
      expect(read.engine, `e=${bad}`).toBe("replay");
      expect(keysOf(U.encode(read)), `e=${bad}`).not.toContain("e");
    }
  });

  it("unknown keys zz and k are ignored and never re-encoded", () => {
    const clean = "?u=tsp&lb=3y&r=12.5&d=0.25&t=light&x=1";
    const variants = [
      "?u=tsp&zz=1&k=ZZ-SENTINEL-ZZ&lb=3y&r=12.5&d=0.25&t=light&x=1",
      "?k=ZZ-SENTINEL-ZZ&zz=1&u=tsp&lb=3y&r=12.5&d=0.25&t=light&x=1",
      "?u=tsp&lb=3y&r=12.5&d=0.25&t=light&x=1&zz=1&k=ZZ-SENTINEL-ZZ&utm_source=mail",
    ];
    const want = U.decode(clean);
    expect(want.preset).toBe("tsp");
    for (const dirty of variants) {
      const state = U.decode(dirty);
      expect(state).toEqual(want);
      expect(Object.keys(state)).not.toContain("k");
      expect(Object.keys(state)).not.toContain("zz");
      expect(JSON.stringify(state)).not.toContain("ZZ-SENTINEL-ZZ");
      const again: string = U.encode(state);
      const keys = keysOf(again);
      expect(keys).not.toContain("zz");
      expect(keys).not.toContain("k");
      expect(keys).not.toContain("utm_source");
      expect(keys.filter((key) => !ALLOWED.has(key))).toEqual([]);
      expect(again).not.toContain("ZZ-SENTINEL-ZZ");
      expect(again).toBe(U.encode(want));
      expect(again).toBe(clean);
    }
  });

  it("r is clamped into the domain on load", () => {
    const domain = { s_safe: DOMAIN.s_safe, s_max: DOMAIN.s_max };
    const tight = { s_safe: 7.375, s_max: 47 };
    const cases: Array<[number, any, number]> = [
      [domain.s_safe - 3, domain, domain.s_safe],
      [domain.s_max + 5, domain, domain.s_max],
      [2, tight, 7.375],
      [-1, tight, 7.375],
      [99, tight, 47],
      [47.001, tight, 47],
      [19.25, tight, 19.25],
      [7.375, tight, 7.375],
    ];
    for (const [r, dom, want] of cases) {
      const state = U.decode(`?u=guide2017&lb=5y&r=${r}&d=auto`, dom);
      expect(state.r, `r=${r} in [${dom.s_safe}, ${dom.s_max}]`).toBe(want);
      expect(state.r).not.toBeLessThan(dom.s_safe);
      expect(state.r).not.toBeGreaterThan(dom.s_max);
    }
  });
});
"""
EXPECTED_TITLES = {
    "600 generated states round-trip and encode emits only the 8.1 keys",
    "the spec example decodes to the obvious state and re-encodes to itself",
    "unknown keys zz and k are ignored and never re-encoded",
    "r is clamped into the domain on load",
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


def test_a_ps_36_vitest():
    statuses = _run_vitest("a_ps_36", SPEC_TS)
    assert set(statuses) == EXPECTED_TITLES, (
        f"vitest ran a different set of tests: {sorted(statuses)}"
    )
    not_passed = {title: status for title, status in statuses.items() if status != "passed"}
    assert not not_passed, f"vitest legs not passed (failed, skipped or todo): {not_passed}"
