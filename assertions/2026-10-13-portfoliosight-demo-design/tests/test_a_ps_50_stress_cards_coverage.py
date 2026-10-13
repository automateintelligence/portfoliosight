"""A-PS-50 — stress cards show real history with coverage, or say they cannot.

Phase 3, ui + unit (Playwright against `vite preview` and a vitest leg, both run from pytest;
standard library only).

UI leg 1 (fixture tensor, which must hold at least one `null` in `stress.gfc2008.r`): at up to five
views chosen from the tensor (partly covered mixes first, then one below 50% and one fully covered
if the fixture has them) `section-stress` holds exactly three cards and each card's
"What this mix did: N%" equals the test's own `sum(w_i R_i) / sum(w_i)` over covered funds at the
shown precision (+-0.01 pp), is provably not the null-as-zero value where the two differ, and a
"N of M funds (P% of the mix) didn't exist yet" note is present whenever a number is shown for a mix
covered less than 99.5%, with N, M, P matching the null pattern; below 50% the card shows
"Not enough of this mix existed then to say." and no number.
UI leg 2 (custom SGOV + VTIP tensor hand-built here as a self-consistent spec section 7 tensor, both
funds `null` for gfc2008, served for `?f=SGOV:50,VTIP:50&unit=pct`): the gfc2008 card shows the exact
sentence and no percentage outside a coverage note; the other two cards show the aggregation of the
custom tensor.
Unit leg: 200 seeded `(w, R)` pairs with random null patterns, and the boundaries 0.5 / 0.4999.

The Playwright spec mocks /api/* itself (page.route) from web/fixtures/guide2017_5y.json and
data/holdings/holdings_guide2017_step2.csv: GET /api/presets (guide2017 with its "$" allocation and
tsp with allocation null, a distinct hash and the same tensor re-labelled), GET /api/tensors/{G}/
{hash}/{lb}, GET /api/symbols, GET /api/health, POST /api/tensors (200 ready, body recorded),
POST /api/share (202), anything else 404. Views are addressed through the spec 8.1 URL keys; with
an integer `r` inside the slider domain and `d=0` the selected mix is exactly `frontier.w[r]`
(`d=1`: `grid.w_div[r]`), which is what the test recomputes from. The product must keep `r` and `d`
as given (it may leave the URL untouched or rewrite the same values).

Pinned interface (beyond the shared pins)
- `stressReturn(w: number[], r: (number | null)[]): { value: number | null, covered: number }`
  exported from `web/src/math/portfolio.ts`; `covered` is the covered weight share
  `sum(w_i, R_i not null) / sum(w_i)`; `value` is `null` (the sentinel) when `covered < 0.5`.
- Card copy (spec 3.6): "What this mix did: N% (...)", the gap note, and the sentence above.
- A page opened with `f=SGOV:50,VTIP:50` requests the menu with `POST /api/tensors` and renders the
  tensor at the returned `url`.
"""

# ruff: noqa: E501
from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"

# Projects this assertion runs on (desktop = chromium 1366x900, phone = chromium "iPhone 13").
PROJECTS = ("desktop",)

CONFIG_TS = r"""
import { defineConfig, devices } from "@playwright/test";

const all = {
  desktop: { name: "desktop", use: { browserName: "chromium" as const, viewport: { width: 1366, height: 900 } } },
  phone: { name: "phone", use: { ...devices["iPhone 13"], browserName: "chromium" as const } },
};
const wanted = (process.env.PS_GATE_PROJECTS || "desktop").split(",");

export default defineConfig({
  testDir: ".",
  testMatch: process.env.PS_GATE_SPEC,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 120_000,
  outputDir: process.env.PS_GATE_OUTPUT,
  reporter: [["json", { outputFile: process.env.PS_GATE_REPORT }]],
  use: { baseURL: process.env.PS_GATE_BASE_URL },
  projects: wanted.map((name) => (all as any)[name]),
});
"""

# The whole Playwright spec lives in this frozen test: first the /api mock and page helpers
# (the gate contract's "UI mock"; each UI gate file carries its own copy), then this assertion's
# legs. It is written to web/e2e/__gate__/ for the run and removed afterwards.
SPEC_TS = r"""
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// ---------------------------------------------------------------------------------------------
// Fixture, presets body and the /api mock (the gate contract's "UI mock"; no product mock server)
// ---------------------------------------------------------------------------------------------
const GATE_ROOT = process.env.PS_GATE_ROOT || "";
const THEMES = ["ks-dark", "light", "hud"] as const;
const LOOKBACKS = ["1y", "2y", "3y", "5y", "10y", "ew"];
const TSP_IDS = [
  "TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I", "TSP-LINCOME", "TSP-L2030", "TSP-L2035", "TSP-L2040",
  "TSP-L2045", "TSP-L2050", "TSP-L2055", "TSP-L2060", "TSP-L2065", "TSP-L2070", "TSP-L2075",
];
type ApiCall = { method: string; path: string; body: any };
type Mock = { calls: ApiCall[]; tensorPosts: () => ApiCall[]; hashCustom: string };

function readFixtureTensor(): any {
  const file = path.join(GATE_ROOT, "web", "fixtures", "guide2017_5y.json");
  if (!fs.existsSync(file)) throw new Error("UI fixture missing: web/fixtures/guide2017_5y.json");
  const tensor = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!/^[0-9a-f]{16}$/.test(String(tensor?.universe?.hash))) {
    throw new Error("UI fixture is not a spec section 7 tensor: universe.hash is not 16 hex digits");
  }
  return tensor;
}

function readHoldings(): { id: string; description: string; amount: number }[] {
  const file = path.join(GATE_ROOT, "data", "holdings", "holdings_guide2017_step2.csv");
  if (!fs.existsSync(file)) throw new Error("holdings file missing: data/holdings/holdings_guide2017_step2.csv");
  const lines = fs.readFileSync(file, "utf8").split(/\r?\n/).filter((line) => line.trim() !== "");
  return lines.slice(1).map((line) => {
    const cells = line.split(",");
    const price = Number(cells[cells.length - 1]);
    const qty = Number(cells[cells.length - 2]);
    return {
      id: cells[1].trim().toUpperCase(),
      description: cells.slice(2, cells.length - 2).join(",").trim(),
      amount: qty * price,
    };
  });
}

function shiftHash(hash: string, by: number): string {
  return hash.split("").map((c) => ((parseInt(c, 16) + by) % 16).toString(16)).join("");
}

function buildPresets(tensor: any): any {
  const G = tensor.generation;
  const h1 = tensor.universe.hash;
  const h2 = shiftHash(h1, 1);
  const names = new Map<string, string>(tensor.universe.funds.map((f: any) => [f.id, f.name]));
  const holdings = readHoldings();
  const lookbacks = (hash: string) =>
    Object.fromEntries(LOOKBACKS.map((lb) => [lb, { status: "ready", url: `/api/tensors/${G}/${hash}/${lb}` }]));
  const allocation: Record<string, number> = {};
  for (const h of holdings) allocation[h.id] = h.amount;
  return {
    generation: G,
    asof: tensor.asof,
    presets: [
      {
        id: "guide2017",
        name: "The 2017 guide portfolio",
        hash: h1,
        funds: holdings.map((h) => ({ id: h.id, name: names.get(h.id) ?? h.description })),
        allocation,
        allocation_unit: "$",
        lookbacks: lookbacks(h1),
      },
      {
        id: "tsp",
        name: "TSP (G, F, C, S, I)",
        hash: h2,
        funds: tensor.universe.funds.map((f: any) => ({ id: f.id, name: f.name })),
        allocation: null,
        allocation_unit: null,
        lookbacks: lookbacks(h2),
      },
    ],
  };
}

// Installs the mock on one page. `custom` (optional) is a second tensor served for a POST whose
// fund ids are exactly the custom tensor's funds.
async function installMock(page: Page, tensor: any, custom?: any): Promise<Mock> {
  const calls: ApiCall[] = [];
  const G = String(tensor.generation);
  const h1 = String(tensor.universe.hash);
  const h2 = shiftHash(h1, 1);
  const h3 = shiftHash(h1, 2);
  const presets = buildPresets(tensor);
  const symbols = {
    catalog_at: tensor.built_at ?? "2026-10-13T09:00:00Z",
    tiers_served: [1, 2, 3],
    symbols: [
      ...tensor.universe.funds.map((f: any) => ({ id: f.id, name: f.name, kind: f.kind ?? "etf", tier: 1, first_date: "2005-01-03" })),
      ...(custom ? custom.universe.funds : [])
        .filter((f: any) => !tensor.universe.funds.some((g: any) => g.id === f.id))
        .map((f: any) => ({ id: f.id, name: f.name, kind: "etf", tier: 2, first_date: "2012-10-16" })),
      ...TSP_IDS.map((id) => ({ id, name: `${id.replace("TSP-", "")} Fund`, kind: "tsp", tier: 1, first_date: "2005-08-01" })),
    ],
  };
  const health = {
    status: "ok", version: tensor.engine_version, generation: G, asof: tensor.asof, asof_trading_days_behind: 0,
    queue: { depth: 0, building: false }, nightly: { status: "ok" },
  };
  const customIds = custom ? custom.universe.funds.map((f: any) => f.id).sort().join(",") : null;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const where = new URL(request.url()).pathname;
    if (!where.startsWith("/api/")) return route.continue();
    const method = request.method();
    let body: any = null;
    const raw = request.postData();
    if (raw) {
      try { body = JSON.parse(raw); } catch { body = raw; }
    }
    calls.push({ method, path: where, body });
    const send = (status: number, payload: any, r2 = false) =>
      route.fulfill({
        status,
        contentType: "application/json",
        headers: r2 ? { "x-ps-source": "r2", "cache-control": "no-store" } : { "cache-control": "no-store" },
        body: JSON.stringify(payload),
      });
    if (method === "GET" && where === "/api/presets") return send(200, presets, true);
    if (method === "GET" && where === "/api/symbols") return send(200, symbols, true);
    if (method === "GET" && where === "/api/health") return send(200, health);
    const hit = where.match(/^\/api\/tensors\/([^/]+)\/([0-9a-f]{16})\/([a-z0-9]+)$/);
    if (method === "GET" && hit && LOOKBACKS.includes(hit[3])) {
      const base = hit[2] === h3 && custom ? custom : hit[2] === h1 || hit[2] === h2 ? tensor : null;
      if (base) {
        const copy = JSON.parse(JSON.stringify(base));
        copy.lookback = { ...copy.lookback, id: hit[3] };
        if (hit[2] === h2) copy.universe = { ...copy.universe, hash: h2, preset_id: "tsp", name: "TSP (G, F, C, S, I)" };
        return send(200, copy, true);
      }
    }
    if (method === "POST" && where === "/api/tensors") {
      const ids = Array.isArray(body?.funds) ? body.funds.map((f: any) => String(f?.id)).sort().join(",") : "";
      const hash = customIds !== null && ids === customIds ? h3 : h1;
      const lb = LOOKBACKS.includes(body?.lookback) ? body.lookback : "5y";
      return send(200, { status: "ready", generation: G, hash, url: `/api/tensors/${G}/${hash}/${lb}` });
    }
    if (method === "POST" && where === "/api/share") return send(202, { status: "accepted" });
    return send(404, { error: { code: "not_found", message: "not found", details: null } });
  });
  return {
    calls,
    tensorPosts: () => calls.filter((c) => c.method === "POST" && c.path === "/api/tensors"),
    hashCustom: h3,
  };
}

// ---------------------------------------------------------------------------------------------
// Page helpers: only spec test ids, html[data-theme], the section 8.1 URL keys and ARIA are used
// ---------------------------------------------------------------------------------------------
const norm = (text: string) => text.replace(/\s+/g, " ").trim();

async function openApp(page: Page, query: string): Promise<void> {
  await page.goto(query ? `/?${query}` : "/");
  await expect(page.getByTestId("chart-canvas")).toBeVisible();
  await expect(page.getByTestId("div-word")).toHaveText(/\S/);
}

function urlParam(page: Page, key: string): string | null {
  return new URL(page.url()).searchParams.get(key);
}

// The page was opened with integer r and d in {0, 1}; the product must keep both (r inside the domain).
async function expectPosition(page: Page, r: number, d: number): Promise<void> {
  await expect.poll(() => Number(urlParam(page, "r") ?? "NaN"), { message: `URL key r stays ${r}` }).toBeCloseTo(r, 9);
  await expect.poll(() => Number(urlParam(page, "d") ?? "NaN"), { message: `URL key d stays ${d}` }).toBeCloseTo(d, 9);
}

// Integer risk positions inside the slider domain [s_safe, NX-1]: at these, with d=0, the selected
// mix is exactly frontier.w[r] (spec 4.11), and with d=1 exactly grid.w_div[r].
function domainInts(tensor: any): number[] {
  const hi = tensor.frontier.x.length - 1;
  const lo = Math.min(hi, Math.ceil(tensor.frontier.s_safe));
  const out: number[] = [];
  for (let r = lo; r <= hi; r++) out.push(r);
  return out;
}
function threeInts(tensor: any): number[] {
  const all = domainInts(tensor);
  return Array.from(new Set([all[0], all[Math.floor(all.length / 2)], all[all.length - 1]]));
}

// Spec 4.6: b = T^{-T} w, p_i = Lambda_i b_i^2 / (w' Sigma w), ENB = exp(-sum p ln p).
function enbOf(tensor: any, w: number[]): number {
  const n = w.length;
  let variance = 0;
  for (let i = 0; i < n; i++) for (let k = 0; k < n; k++) variance += w[i] * tensor.cov[i][k] * w[k];
  let entropy = 0;
  for (let i = 0; i < n; i++) {
    let b = 0;
    for (let k = 0; k < n; k++) b += tensor.torsion_inv_t[i][k] * w[k];
    const p = (tensor.torsion_lambda[i] * b * b) / variance;
    if (p > 0) entropy -= p * Math.log(p);
  }
  return Math.exp(entropy);
}

// Any CSS colour string -> "#rrggbb" (lower case), by painting it; "invalid:..." when the browser
// does not accept it as a colour.
async function cssColorToHex(page: Page, value: string): Promise<string> {
  return page.evaluate((v) => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    const paint = (base: string) => {
      ctx.fillStyle = base;
      ctx.fillStyle = v;
      ctx.clearRect(0, 0, 1, 1);
      ctx.fillRect(0, 0, 1, 1);
      return Array.from(ctx.getImageData(0, 0, 1, 1).data);
    };
    const a = paint("#000000");
    const b = paint("#ffffff");
    if (a.join() !== b.join()) return `invalid:${v}`;
    if (a[3] !== 255) return `translucent:${v}`;
    return "#" + a.slice(0, 3).map((x) => x.toString(16).padStart(2, "0")).join("");
  }, value.trim());
}

async function tokenHex(page: Page, name: string): Promise<string> {
  const raw = await page.evaluate((n) => getComputedStyle(document.documentElement).getPropertyValue(n), name);
  return cssColorToHex(page, raw);
}

// Clicks the four chips; every section must report aria-expanded="true" afterwards. The Trades
// section exists only when a current mix exists (spec 3.3), so it is optional without one.
async function expandAll(page: Page, hasAllocation: boolean): Promise<void> {
  for (const name of ["funds", "trades", "stress", "settings"]) {
    const chip = page.getByTestId(`chip-${name}`);
    if (name === "trades" && !hasAllocation && (await chip.count()) === 0) continue;
    await chip.click();
    await expect(page.getByTestId(`section-${name}`)).toHaveAttribute("aria-expanded", "true");
  }
}

// theme-switch: either one clickable that cycles ks-dark -> light -> hud, or a group holding exactly
// three button / role=radio segments in that order. Returns the theme that should now be active.
async function advanceTheme(page: Page): Promise<string> {
  const order = ["ks-dark", "light", "hud"];
  const current = (await page.locator("html").getAttribute("data-theme")) ?? "";
  const next = order[(order.indexOf(current) + 1) % 3];
  const control = page.getByTestId("theme-switch");
  const segments = control.locator('button, [role="radio"]');
  if ((await segments.count()) === 3) await segments.nth(order.indexOf(next)).click();
  else await control.click();
  return next;
}

// ---------------------------------------------------------------------------------------------
// A-PS-50, UI legs
// ---------------------------------------------------------------------------------------------
const STRESS_IDS = ["gfc2008", "covid2020", "rates2022"];
const SENTENCE = "Not enough of this mix existed then to say.";

// The test's own aggregation (spec 4.10): sum(w_i R_i) / sum(w_i) over covered funds.
function aggregate(w: number[], r: (number | null)[]) {
  let total = 0, covered = 0, numerator = 0, nulls = 0, heldNulls = 0, held = 0;
  for (let i = 0; i < w.length; i++) {
    total += w[i];
    if (w[i] > 1e-9) held += 1;
    if (r[i] === null) {
      nulls += 1;
      if (w[i] > 1e-9) heldNulls += 1;
    } else {
      covered += w[i];
      numerator += w[i] * (r[i] as number);
    }
  }
  return {
    covered: covered / total,
    value: covered > 0 ? numerator / covered : null,
    nullAsZero: numerator / total,
    nulls, heldNulls, held, funds: w.length,
  };
}

const cardText = async (page: Page, id: string) => {
  const card = page.getByTestId(`stress-${id}`);
  await expect(card, `stress card ${id}`).toBeVisible();
  return norm((await card.textContent()) ?? "").replace(/[−–—]/g, "-").replace(/[‘’]/g, "'");
};
const NOTE_RE = /(\d+) of (\d+) funds \((\d+(?:\.\d+)?)% of the mix\) didn't exist yet/;
const NUMBER_RE = /What this mix did:\s*([+-]?\d+(?:\.\d+)?)\s*%/i;
const pctTol = (shown: string) => 0.5 * Math.pow(10, -((shown.split(".")[1] ?? "").length)) + 0.01;

// One card against the test's aggregation. Returns what was exercised.
async function checkCard(page: Page, id: string, w: number[], r: (number | null)[], where: string) {
  const text = await cardText(page, id);
  const agg = aggregate(w, r);
  const note = text.match(NOTE_RE);
  if (agg.covered < 0.5) {
    expect(text, `${where}: covered ${agg.covered} < 50% must show the sentence`).toContain(SENTENCE);
    expect(text.match(NUMBER_RE), `${where}: a number although covered weight < 50%: "${text}"`).toBeNull();
  } else {
    const m = text.match(NUMBER_RE);
    expect(m, `${where}: card text "${text}" lacks "What this mix did: N%"`).not.toBeNull();
    const shown = Number(m![1]);
    expect(Math.abs(shown - agg.value! * 100), `${where}: shown ${m![1]}% vs own aggregation ${(agg.value! * 100).toFixed(4)}%`).toBeLessThanOrEqual(pctTol(m![1]));
    if (Math.abs(agg.nullAsZero - agg.value!) * 100 > 2 * pctTol(m![1])) {
      expect(Math.abs(shown - agg.nullAsZero * 100), `${where}: the number treats a null fund as 0`).toBeGreaterThan(pctTol(m![1]));
    }
    expect(text, `${where}: the sentence although covered weight >= 50%`).not.toContain(SENTENCE);
  }
  // required whenever a number is shown for a partly covered mix; optional beside the sentence
  if (agg.covered >= 0.5 && agg.covered < 1 - 0.005) {
    expect(note, `${where}: coverage note missing at covered ${agg.covered}: "${text}"`).not.toBeNull();
  }
  if (note) {
    const pair = `${note[1]} of ${note[2]}`;
    expect([`${agg.nulls} of ${agg.funds}`, `${agg.heldNulls} of ${agg.held}`], `${where}: note "${pair} funds"`).toContain(pair);
    expect(Math.abs(Number(note[3]) - (1 - agg.covered) * 100), `${where}: note share ${note[3]}%`).toBeLessThanOrEqual(pctTol(note[3]));
  }
  return { ...agg, noted: note !== null };
}

// A hand-built, self-consistent spec section 7 tensor for SGOV + VTIP (two uncorrelated funds, so
// the minimum-torsion matrix is the identity). Both funds are null in gfc2008.
function buildCustomTensor(fx: any, hash: string): any {
  const NX = 48, NY = 32;
  const mu = [0.045, 0.062];
  const sd = [0.006, 0.031];
  const v0 = sd[0] * sd[0], v1 = sd[1] * sd[1];
  const wOf = (a: number) => [1 - a, a];
  const sigmaOf = (a: number) => Math.sqrt((1 - a) * (1 - a) * v0 + a * a * v1);
  const muOf = (a: number) => (1 - a) * mu[0] + a * mu[1];
  const enbAt = (a: number) => {
    const s2 = sigmaOf(a) ** 2;
    const p = [((1 - a) * (1 - a) * v0) / s2, (a * a * v1) / s2];
    return Math.exp(-p.reduce((acc, x) => acc + (x > 0 ? x * Math.log(x) : 0), 0));
  };
  const aMin = v0 / (v0 + v1);
  const root = (X: number) => Math.sqrt(Math.max(0, v0 * v0 - (v0 + v1) * (v0 - X * X)));
  const aHigh = (X: number) => Math.min(1, (v0 + root(X)) / (v0 + v1));
  const aLow = (X: number) => Math.max(0, (v0 - root(X)) / (v0 + v1));
  const sMin = sigmaOf(aMin), sMax = sigmaOf(1);
  const x: number[] = [], aFront: number[] = [];
  for (let j = 0; j < NX; j++) {
    x.push(j === NX - 1 ? sMax : sMin + ((sMax - sMin) * j) / (NX - 1));
    aFront.push(j === NX - 1 ? 1 : j === 0 ? aMin : aHigh(x[j]));
  }
  const yFront = aFront.map(muOf);
  const gridY: number[] = [];
  for (let k = 0; k < NY; k++) gridY.push(k === NY - 1 ? mu[1] : mu[0] + ((mu[1] - mu[0]) * k) / (NY - 1));
  const z: (number | null)[][] = [], gw: (number[] | null)[][] = [];
  const kDiv: number[] = [], yDiv: number[] = [], wDiv: number[][] = [];
  let enbRef = 0;
  for (let j = 0; j < NX; j++) {
    const zCol: (number | null)[] = [], wCol: (number[] | null)[] = [];
    let best = { enb: enbAt(aFront[j]), ret: yFront[j], k: -1, w: wOf(aFront[j]) };
    for (let k = 0; k < NY; k++) {
      if (gridY[k] > yFront[j] + 1e-12) {
        zCol.push(null);
        wCol.push(null);
        continue;
      }
      const lo = Math.max((gridY[k] - mu[0]) / (mu[1] - mu[0]), aLow(x[j]));
      const a = Math.min(aFront[j], Math.max(lo, 0.5));
      const cell = { enb: enbAt(a), ret: gridY[k], k, w: wOf(a) };
      zCol.push(cell.enb);
      wCol.push(cell.w);
      if (cell.enb > best.enb + 1e-12 || (Math.abs(cell.enb - best.enb) <= 1e-12 && cell.ret > best.ret)) best = cell;
    }
    z.push(zCol);
    gw.push(wCol);
    kDiv.push(best.k);
    yDiv.push(best.ret);
    wDiv.push(best.w);
    enbRef = Math.max(enbRef, best.enb, enbAt(aFront[j]));
  }
  const curveSigma: number[] = [], curveMu: number[] = [];
  let sSafe = 0, bestLow = -Infinity;
  for (let i = 0; i <= (NX - 1) * 8; i++) {
    const s = i / 8;
    const j = Math.min(NX - 2, Math.floor(s));
    const lam = s - j;
    const a = (1 - lam) * aFront[j] + lam * aFront[j + 1];
    curveSigma.push(sigmaOf(a));
    curveMu.push(muOf(a));
    const low = muOf(a) / 2 - (1.96 * sigmaOf(a)) / Math.SQRT2;
    if (low >= bestLow) {
      bestLow = low;
      sSafe = s;
    }
  }
  const fund = (id: string, name: string, lastClose: number) => ({
    id, name, kind: "etf", source: "tiingo", adjusted_through: fx.asof, fetched_at: fx.built_at, last_close: lastClose,
  });
  const window = (id: string, r: (number | null)[]) => ({ label: fx.stress[id].label, start: fx.stress[id].start, end: fx.stress[id].end, r });
  return {
    schema: fx.schema, engine_version: fx.engine_version, generation: fx.generation, built_at: fx.built_at,
    build_seconds: 0.4, asof: fx.asof,
    frontier_curve: { sigma: curveSigma, mu: curveMu },
    universe: {
      hash, name: "Custom menu", preset_id: null,
      funds: [fund("SGOV", "iShares 0-3 Month Treasury Bond ETF", 100.42), fund("VTIP", "Vanguard Short-Term Inflation-Protected Securities ETF", 49.87)],
      excluded: [],
    },
    lookback: { ...fx.lookback },
    rf: fx.rf,
    mu_s: mu, mu_sample: mu, sigma: sd, cov: [[v0, 0], [0, v1]],
    torsion: [[1, 0], [0, 1]], torsion_inv_t: [[1, 0], [0, 1]], torsion_lambda: [v0, v1],
    bounds: { requested: [{ min: null, max: null }, { min: null, max: null }], min: [0, 0], max: [1, 1], rule: "max(0.25, 3/N)" },
    frontier: { x, y: yFront, w: aFront.map(wOf), s_safe: sSafe },
    grid: { y: gridY, z, w: gw, k_div: kDiv, y_div: yDiv, w_div: wDiv, y_sug: [...yFront] },
    enb_ref: enbRef,
    stress: { gfc2008: window("gfc2008", [null, null]), covid2020: window("covid2020", [0.004, -0.021]), rates2022: window("rates2022", [0.009, -0.034]) },
    notes: Array.isArray(fx.notes) ? fx.notes : [],
  };
}

test("stress cards default fixture", async ({ page }) => {
  const tensor = readFixtureTensor();
  const gfc: (number | null)[] = tensor.stress?.gfc2008?.r ?? [];
  if (!gfc.some((v) => v === null)) {
    throw new Error("the fixture web/fixtures/guide2017_5y.json has no null fund in stress.gfc2008.r; A-PS-50 needs at least one");
  }
  await installMock(page, tensor);
  // candidate views: integer r with d=0 (frontier.w[r]) or d=1 (grid.w_div[r])
  const views: { r: number; d: number; w: number[]; gap: number; covered: number }[] = [];
  for (const r of domainInts(tensor)) {
    for (const d of [0, 1]) {
      const w: number[] = d === 0 ? tensor.frontier.w[r] : tensor.grid.w_div[r];
      const agg = aggregate(w, gfc);
      views.push({ r, d, w, covered: agg.covered, gap: agg.value === null ? 0 : Math.abs(agg.value - agg.nullAsZero) });
    }
  }
  const partial = views.filter((v) => 1 - v.covered > 0.005 && v.covered >= 0.5).sort((a, b) => b.gap - a.gap);
  if (partial.length === 0) {
    throw new Error("no frontier or most-diversified mix of the fixture holds between 0.5% and 50% in funds that are null for gfc2008; the coverage note cannot be exercised");
  }
  const chosen = [partial[0], partial[Math.floor(partial.length / 2)], partial[partial.length - 1]];
  const starved = views.find((v) => v.covered < 0.5);
  if (starved) chosen.push(starved);
  const full = views.find((v) => v.covered >= 1 - 1e-12);
  if (full) chosen.push(full);
  let numbers = 0, notes = 0;
  const shownAt = new Set<string>();
  for (const view of chosen) {
    await openApp(page, `u=guide2017&lb=5y&r=${view.r}&d=${view.d}`);
    await expectPosition(page, view.r, view.d);
    await page.getByTestId("chip-stress").click();
    await expect(page.getByTestId("section-stress")).toHaveAttribute("aria-expanded", "true");
    await expect(page.locator('[data-testid^="stress-"]'), "exactly three stress cards").toHaveCount(3);
    for (const id of STRESS_IDS) {
      const result = await checkCard(page, id, view.w, tensor.stress[id].r, `${id} at r=${view.r}, d=${view.d}`);
      if (result.covered >= 0.5) numbers += 1;
      if (result.noted) notes += 1;
    }
    shownAt.add(`${view.r}/${view.d}:${await cardText(page, "gfc2008")}`);
  }
  expect(numbers, "cards compared with the aggregation").toBeGreaterThanOrEqual(3);
  expect(notes, "coverage notes checked").toBeGreaterThanOrEqual(1);
  expect(shownAt.size).not.toBe(0);
});

test("stress cards custom sgov vtip", async ({ page }) => {
  const tensor = readFixtureTensor();
  const custom = buildCustomTensor(tensor, shiftHash(tensor.universe.hash, 2));
  // the hand-built tensor honours the spec 4.11 invariants
  for (let j = 0; j < 48; j++) {
    const w = custom.frontier.w[j];
    expect(Math.abs(w[0] + w[1] - 1)).toBeLessThanOrEqual(1e-12);
    expect(Math.sqrt(w[0] * w[0] * custom.cov[0][0] + w[1] * w[1] * custom.cov[1][1])).toBeLessThanOrEqual(custom.frontier.x[j] + 1e-9);
    expect(enbOf(custom, custom.grid.w_div[j])).toBeGreaterThanOrEqual(enbOf(custom, w) - 1e-9);
    expect(custom.grid.y_div[j]).toBeLessThanOrEqual(custom.frontier.y[j] + 1e-12);
  }
  expect(custom.frontier_curve.sigma.length).toBe(377);
  const mock = await installMock(page, tensor, custom);
  const r = threeInts(custom)[1];
  await openApp(page, `f=SGOV:50,VTIP:50&unit=pct&lb=5y&r=${r}&d=0`);
  await expectPosition(page, r, 0);
  const posts = mock.tensorPosts();
  expect(posts.length, "the custom menu was requested with POST /api/tensors").toBeGreaterThanOrEqual(1);
  expect(posts[0].body.funds.map((f: any) => f.id).sort()).toEqual(["SGOV", "VTIP"]);
  expect(mock.calls.some((c) => c.method === "GET" && c.path.includes(`/${mock.hashCustom}/`)), "the custom tensor was fetched").toBe(true);
  await page.getByTestId("chip-stress").click();
  await expect(page.getByTestId("section-stress")).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator('[data-testid^="stress-"]')).toHaveCount(3);

  const gfc = await cardText(page, "gfc2008");
  expect(gfc, "gfc2008 card of a mix that did not exist then").toContain(SENTENCE);
  expect(gfc.match(NUMBER_RE), `a number on the gfc2008 card: "${gfc}"`).toBeNull();
  expect(gfc.replace(NOTE_RE, ""), `a percentage on the gfc2008 card: "${gfc}"`).not.toMatch(/\d\s*%/);
  await checkCard(page, "gfc2008", custom.frontier.w[r], custom.stress.gfc2008.r, "custom gfc2008");
  for (const id of ["covid2020", "rates2022"]) {
    const result = await checkCard(page, id, custom.frontier.w[r], custom.stress[id].r, `custom ${id} at r=${r}`);
    expect(result.covered).toBe(1);
  }
});
"""
EXPECTED_TITLES = {"stress cards default fixture", "stress cards custom sgov vtip"}

# The vitest leg (pure function, no browser). Written to web/tests/__gate__/ for the run.
VITEST_TS = r"""
import { describe, expect, it } from "vitest";

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// The test's own aggregation (spec 4.10).
function reference(w: number[], r: (number | null)[]) {
  let total = 0, covered = 0, numerator = 0;
  for (let i = 0; i < w.length; i++) {
    total += w[i];
    if (r[i] !== null) {
      covered += w[i];
      numerator += w[i] * (r[i] as number);
    }
  }
  const share = covered / total;
  return { covered: share, value: share >= 0.5 ? numerator / covered : null, nullAsZero: numerator / total };
}

describe("A-PS-50", () => {
  it("stress aggregation over 200 generated inputs", async () => {
    const mod: any = await import("../../src/math/portfolio");
    expect(typeof mod.stressReturn, "web/src/math/portfolio.ts must export stressReturn(w, r)").toBe("function");
    const random = mulberry32(50);
    let numbers = 0, sentinels = 0, partial = 0;
    for (let trial = 0; trial < 200; trial++) {
      const n = 2 + Math.floor(random() * 29);
      const nullRate = trial % 4 === 0 ? 0 : random() * 0.95;
      const raw = Array.from({ length: n }, () => (random() < 0.2 ? 0 : random()));
      if (raw.every((v) => v === 0)) raw[0] = 1;
      const sum = raw.reduce((a, b) => a + b, 0);
      const w = raw.map((v) => v / sum);
      const r: (number | null)[] = w.map(() => (random() < nullRate ? null : -0.6 + random()));
      const want = reference(w, r);
      if (Math.abs(want.covered - 0.5) < 1e-9) continue;
      const got = mod.stressReturn(w, r);
      expect(Math.abs(got.covered - want.covered), `trial ${trial}: covered share`).toBeLessThanOrEqual(1e-12);
      if (want.value === null) {
        expect(got.value, `trial ${trial}: covered ${want.covered} < 0.5 must return the sentinel`).toBeNull();
        sentinels += 1;
      } else {
        expect(typeof got.value, `trial ${trial}: covered ${want.covered} >= 0.5 must return a number`).toBe("number");
        expect(Math.abs(got.value - want.value), `trial ${trial}: value`).toBeLessThanOrEqual(1e-12);
        if (Math.abs(want.nullAsZero - want.value) > 1e-6) {
          expect(Math.abs(got.value - want.nullAsZero), `trial ${trial}: a null fund was treated as 0`).toBeGreaterThan(1e-9);
          partial += 1;
        }
        numbers += 1;
      }
    }
    expect(numbers, "generated cases with a number").toBeGreaterThanOrEqual(40);
    expect(sentinels, "generated cases with the sentinel").toBeGreaterThanOrEqual(40);
    expect(partial, "generated cases with partial coverage and a number").toBeGreaterThanOrEqual(15);
  });

  it("stress aggregation boundaries 0.5 and 0.4999", async () => {
    const mod: any = await import("../../src/math/portfolio");
    expect(typeof mod.stressReturn).toBe("function");
    const atHalf = mod.stressReturn([0.5, 0.5], [0.1, null]);
    expect(atHalf.covered).toBe(0.5);
    expect(atHalf.value).not.toBeNull();
    expect(Math.abs(atHalf.value - 0.1)).toBeLessThanOrEqual(1e-12);
    const below = mod.stressReturn([0.4999, 0.5001], [0.1, null]);
    expect(Math.abs(below.covered - 0.4999)).toBeLessThanOrEqual(1e-12);
    expect(below.value).toBeNull();
    const none = mod.stressReturn([0.5, 0.5], [null, null]);
    expect(none.covered).toBe(0);
    expect(none.value).toBeNull();
    const full = mod.stressReturn([0.25, 0.75], [-0.4, 0.2]);
    expect(full.covered).toBe(1);
    expect(Math.abs(full.value - 0.05)).toBeLessThanOrEqual(1e-12);
  });
});
"""
VITEST_TITLES = {
    "stress aggregation over 200 generated inputs",
    "stress aggregation boundaries 0.5 and 0.4999",
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(port: int, proc: subprocess.Popen, seconds: float = 60.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and proc.poll() is None:
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.25)
    return False


def _run_playwright(
    name: str,
    spec_ts: str,
    projects: tuple[str, ...],
    base_url: str | None = None,
    extra_env: dict[str, str] | None = None,
    timeout: int = 900,
) -> dict[tuple[str, str], str]:
    """Run one embedded Playwright spec and return {(project, test title): status}.

    base_url=None: build the site and serve it with `vite preview` on a free local port (the
    spec mocks /api/* itself with page.route). Otherwise run against base_url (production).
    """
    assert (WEB / "package.json").is_file(), (
        "web/package.json is missing: the front end is not built yet"
    )
    bin_dir = WEB / "node_modules" / ".bin"
    assert (bin_dir / "playwright").exists(), (
        "web/node_modules/.bin/playwright is missing: run `npm ci` in web/"
    )
    preview = None
    gate_dir = WEB / "e2e" / "__gate__"
    spec = gate_dir / f"{name}.spec.ts"
    config = gate_dir / f"{name}.config.ts"
    report = None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.json"
        try:
            if base_url is None:
                assert (bin_dir / "vite").exists(), (
                    "web/node_modules/.bin/vite is missing: run `npm ci` in web/"
                )
                build = subprocess.run(
                    ["npm", "run", "build"], cwd=WEB, capture_output=True, text=True, timeout=600
                )
                assert build.returncode == 0, (
                    f"`npm run build` failed in web/:\n{build.stdout[-3000:]}{build.stderr[-3000:]}"
                )
                port = _free_port()
                preview = subprocess.Popen(
                    [
                        str(bin_dir / "vite"),
                        "preview",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--strictPort",
                    ],
                    cwd=WEB,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )
                assert _wait_for_port(port, preview), (
                    "`vite preview` did not start listening within 60 s"
                )
                base_url = f"http://127.0.0.1:{port}"
            gate_dir.mkdir(parents=True, exist_ok=True)
            spec.write_text(spec_ts, encoding="utf-8")
            config.write_text(CONFIG_TS, encoding="utf-8")
            env = dict(
                os.environ,
                PS_GATE_ROOT=str(ROOT),
                PS_GATE_BASE_URL=base_url,
                PS_GATE_REPORT=str(out),
                PS_GATE_OUTPUT=str(Path(tmp) / "results"),
                PS_GATE_SPEC=spec.name,
                PS_GATE_PROJECTS=",".join(projects),
                **(extra_env or {}),
            )
            proc = subprocess.run(
                [str(bin_dir / "playwright"), "test", "--config", f"e2e/__gate__/{config.name}"],
                cwd=WEB,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if out.exists():
                report = json.loads(out.read_text(encoding="utf-8"))
        finally:
            if preview is not None:
                preview.terminate()
                try:
                    preview.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    preview.kill()
            spec.unlink(missing_ok=True)
            config.unlink(missing_ok=True)
            if gate_dir.is_dir() and not any(gate_dir.iterdir()):
                gate_dir.rmdir()
    tail = proc.stdout[-6000:] + proc.stderr[-3000:]
    assert report is not None, f"Playwright wrote no JSON report:\n{tail}"
    statuses: dict[tuple[str, str], str] = {}

    def walk(suite: dict) -> None:
        for case in suite.get("specs", []):
            for run in case.get("tests", []):
                results = run.get("results", [])
                for result in results:
                    for error in result.get("errors", []):
                        print(
                            f"[{run.get('projectName')}] {case['title']}: {error.get('message', '')[:3000]}"
                        )
                final = results[-1]["status"] if results else "not-run"
                statuses[(run.get("projectName", ""), case["title"])] = (
                    final if len(results) == 1 else "retried"
                )
        for child in suite.get("suites", []):
            walk(child)

    for suite in report.get("suites", []):
        walk(suite)
    for error in report.get("errors", []):
        print("playwright error:", error.get("message", "")[:3000])
    return statuses


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
        if file_result.get("status") != "passed":
            print(file_result.get("message", ""))
    print(tail)
    return statuses


def test_a_ps_50_vitest():
    statuses = _run_vitest("a_ps_50", VITEST_TS)
    assert set(statuses) == VITEST_TITLES, (
        f"vitest ran a different set of tests: {sorted(statuses)}"
    )
    not_passed = {title: status for title, status in statuses.items() if status != "passed"}
    assert not not_passed, f"vitest legs not passed (failed, skipped or todo): {not_passed}"


def test_a_ps_50_playwright():
    statuses = _run_playwright("a_ps_50", SPEC_TS, PROJECTS)
    expected = {(project, title) for project in PROJECTS for title in EXPECTED_TITLES}
    assert set(statuses) == expected, f"Playwright ran a different set of tests: {sorted(statuses)}"
    not_passed = {key: status for key, status in statuses.items() if status != "passed"}
    assert not not_passed, (
        f"Playwright legs not passed (failed, skipped, timed out or retried): {not_passed}"
    )
