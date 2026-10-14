"""A-PS-43 - the default view is the Example Portfolio with its allocation and no fund set
aside; a menu holding a fund its tensor sets aside shows the excluded-fund note with the tensor's
reason; the preset menu is driven by /api/presets.

Owner decision 2026-10-13: EFA holds FIENX's place in the default menu, so the fixture tensor has
23 included funds and an empty `excluded` list. The excluded-fund note is asserted on the second
menu of the mock, which holds FIENX (the catalog's converted fund) and whose tensor lists it in
`excluded`, as the service does for any menu holding a fund it cannot use.

Playwright (desktop) run from pytest; stdlib only.

Mock (built by the embedded spec, no product mock server): page.route on /api/** serving
GET /api/presets (two presets: guide2017 with the allocation from
data/holdings/holdings_guide2017_step2.csv in "$", and tsp named "TSP (G, F, C, S, I) [mock-7f3]"
with a distinct hash, allocation null and the same 23 funds plus FIENX; six ready lookbacks each),
GET /api/tensors/{G}/{hash}/{lb} (web/fixtures/guide2017_5y.json with lookback.id patched; for the
second hash also universe.hash, preset_id and name patched, and FIENX added to universe.excluded
with the reason "converted to an ETF; no data since 2024-10-30 [mock-7f3]", followed by " [{lb}]"
for every lookback but 5y, so two tensors of that menu give FIENX two different reasons),
GET /api/symbols, GET /api/health, POST /api/tensors, POST /api/share, anything else 404. Every
/api/ request is logged.

Pinned interface (beyond the shared pins of the gate contract):
- web/ builds with `npm run build` and serves with `vite preview`; web/fixtures/guide2017_5y.json.
- html[data-theme], URL keys u, lb, r, d, t, x (spec 8.1); r and d are written to the address
  (debounced) after every change, with at least six decimals.
- test ids: chart-canvas, point-selected, point-current, chip-funds, section-funds (aria-expanded),
  fund-row-{ID} (one row per fund of the menu, excluded ones included: 23 for the default menu,
  24 for the second), unit-toggle, excluded-note, preset-menu, chip-settings, section-settings
  (aria-expanded), lookback-10y (a click selects the 10y view and loads the menu's declared 10y
  tensor URL).
- each fund row holds its amount in its first non-checkbox <input>; accepted formatting: optional
  "$", digits with optional thousands separators, up to two decimals; blank reads as 0.
- unit-toggle marks its active option with aria-checked / aria-pressed / aria-selected = "true"
  (or a checked input / selected option); its text is "$".
- preset-menu is a <select> (or contains one), or a button that opens entries with role=option /
  menuitem / menuitemradio; the first two entries are the presets in body order, then "Custom...".
- excluded-note text is the tensor's reason string (optionally followed by ": not used"); a fund
  row carries one exactly when the tensor lists that fund in universe.excluded.
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

# Projects this assertion runs on. "desktop" = chromium 1366x900, "phone" = chromium with the
# "iPhone 13" device profile (the spec's chromium-desktop / chromium-phone).
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

# The whole Playwright spec lives in this frozen test. It is written to web/e2e/__gate__/ for the
# run and removed afterwards. Environment the spec may read: PS_GATE_ROOT (repo root),
# PS_GATE_BASE_URL. Never use __dirname (web/ is an ES-module package).
SPEC_TS = r"""
import { expect, test, type Locator, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// ---------------------------------------------------------------------------------------------
// Shared helper block (each gate file embeds its own copy; nothing here imports product code).
// ---------------------------------------------------------------------------------------------
const ROOT = process.env.PS_GATE_ROOT || "";
const THEMES = ["ks-dark", "light", "hud", "grid"];
const LOOKBACKS = ["1y", "2y", "3y", "5y", "10y", "ew"];
const TSP: [string, string][] = [
  ["TSP-G", "G Fund"], ["TSP-F", "F Fund"], ["TSP-C", "C Fund"], ["TSP-S", "S Fund"], ["TSP-I", "I Fund"],
  ["TSP-LINC", "L Income"], ["TSP-L2030", "L 2030"], ["TSP-L2035", "L 2035"], ["TSP-L2040", "L 2040"],
  ["TSP-L2045", "L 2045"], ["TSP-L2050", "L 2050"], ["TSP-L2055", "L 2055"], ["TSP-L2060", "L 2060"],
  ["TSP-L2065", "L 2065"], ["TSP-L2070", "L 2070"], ["TSP-L2075", "L 2075"],
];
const SECOND_NAME = "TSP (G, F, C, S, I) [mock-7f3]";
const SECOND_REASON_SUFFIX = " [mock-7f3]";
const FIENX_REASON = "converted to an ETF; no data since 2024-10-30";
const SET_ASIDE = { id: "FIENX", name: "Fidelity International Enhanced Index Fund" };

type ApiCall = { method: string; path: string; body: string | null };
type Rgb = [number, number, number];

function readFixture(): any {
  const file = path.join(ROOT, "web", "fixtures", "guide2017_5y.json");
  if (!fs.existsSync(file)) throw new Error("the UI fixture web/fixtures/guide2017_5y.json is missing (Phase 1 delivers it)");
  const tensor = JSON.parse(fs.readFileSync(file, "utf8"));
  for (const key of ["generation", "universe", "frontier", "grid", "frontier_curve", "mu_s", "cov", "enb_ref"]) {
    if (tensor[key] === undefined) throw new Error(`web/fixtures/guide2017_5y.json is not a spec section 7 tensor: no "${key}"`);
  }
  return tensor;
}

function readHoldings(): { id: string; name: string; amount: number }[] {
  const file = path.join(ROOT, "data", "holdings", "holdings_guide2017_step2.csv");
  if (!fs.existsSync(file)) throw new Error("data/holdings/holdings_guide2017_step2.csv is missing");
  const rows = fs.readFileSync(file, "utf8").split(/\r?\n/).filter((line) => line.trim() !== "").slice(1);
  return rows.map((line) => {
    const cells = line.split(",");
    const qty = Number(cells[cells.length - 2]);
    const price = Number(cells[cells.length - 1]);
    return { id: cells[1].trim(), name: cells.slice(2, cells.length - 2).join(",").trim(), amount: qty * price };
  });
}

function buildMock(tensor: any) {
  const G: string = tensor.generation;
  const hash1: string = tensor.universe.hash;
  const hash2 = hash1 === "7f3a0c5e9b1d2468" ? "8e4b1d6f0a2c3579" : "7f3a0c5e9b1d2468";
  const holdings = readHoldings();
  const tensorNames = new Map<string, string>(tensor.universe.funds.map((f: any) => [f.id, f.name]));
  const funds = holdings.map((h) => ({ id: h.id, name: tensorNames.get(h.id) || h.name || h.id }));
  const allocation: Record<string, number> = {};
  for (const h of holdings) allocation[h.id] = h.amount;
  const lookbacks = (hash: string) => {
    const out: Record<string, { status: string; url: string }> = {};
    for (const lb of LOOKBACKS) out[lb] = { status: "ready", url: `/api/tensors/${G}/${hash}/${lb}` };
    return out;
  };
  const presets = {
    generation: G,
    asof: tensor.asof,
    presets: [
      { id: "guide2017", name: tensor.universe.name || "The 2017 guide portfolio", hash: hash1, funds, allocation, allocation_unit: "$", lookbacks: lookbacks(hash1) },
      { id: "tsp", name: SECOND_NAME, hash: hash2, funds: [...funds, SET_ASIDE], allocation: null, allocation_unit: null, lookbacks: lookbacks(hash2) },
    ],
  };
  const symbols = {
    catalog_at: "2026-10-13T09:05:11Z",
    tiers_served: [1, 2, 3],
    symbols: [
      ...tensor.universe.funds.map((f: any) => ({ id: f.id, name: f.name, kind: f.kind || "etf", tier: 1, first_date: "2001-05-31" })),
      ...TSP.map(([id, name]) => ({ id, name, kind: "tsp", tier: 1, first_date: "2003-06-02" })),
    ],
  };
  const health = {
    status: "ok", version: tensor.engine_version, generation: G, asof: tensor.asof, asof_trading_days_behind: 0,
    queue: { depth: 0, building: false }, nightly: { status: "ok", generation: G },
  };
  const log: ApiCall[] = [];
  return { tensor, G, hash1, hash2, presets, symbols, health, log, holdings, allocation };
}
type Mock = ReturnType<typeof buildMock>;

function tensorBody(mock: Mock, hash: string, lb: string): any {
  const copy = JSON.parse(JSON.stringify(mock.tensor));
  copy.lookback = { ...copy.lookback, id: lb };
  if (hash === mock.hash2) {
    copy.universe.hash = mock.hash2;
    copy.universe.preset_id = "tsp";
    copy.universe.name = SECOND_NAME;
    for (const ex of copy.universe.excluded || []) ex.reason = ex.reason + SECOND_REASON_SUFFIX;
    copy.universe.excluded = [...(copy.universe.excluded || []), { id: SET_ASIDE.id, reason: FIENX_REASON + SECOND_REASON_SUFFIX + (lb === "5y" ? "" : ` [${lb}]`), last_close: null }];
  }
  return copy;
}

async function installMock(page: Page, mock: Mock) {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) return route.fallback();
    const method = request.method();
    mock.log.push({ method, path: url.pathname, body: request.postData() });
    const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
      route.fulfill({ status, contentType: "application/json", headers, body: JSON.stringify(body) });
    const r2 = { "x-ps-source": "r2" };
    const tensorMatch = url.pathname.match(/^\/api\/tensors\/([^/]+)\/([0-9a-f]{16})\/(1y|2y|3y|5y|10y|ew)$/);
    if (method === "GET" && url.pathname === "/api/presets") return json(200, mock.presets, { ...r2, "cache-control": "public, max-age=300" });
    if (method === "GET" && url.pathname === "/api/symbols") return json(200, mock.symbols, { ...r2, "cache-control": "public, max-age=3600" });
    if (method === "GET" && url.pathname === "/api/health") return json(200, mock.health, { "cache-control": "no-store" });
    if (method === "GET" && tensorMatch && tensorMatch[1] === mock.G && (tensorMatch[2] === mock.hash1 || tensorMatch[2] === mock.hash2)) {
      return json(200, tensorBody(mock, tensorMatch[2], tensorMatch[3]), { ...r2, "cache-control": "public, max-age=86400, immutable", etag: `"${tensorMatch[2]}-${tensorMatch[3]}"` });
    }
    if (method === "POST" && url.pathname === "/api/tensors") {
      return json(200, { status: "ready", generation: mock.G, hash: mock.hash1, url: `/api/tensors/${mock.G}/${mock.hash1}/5y` }, { "cache-control": "no-store" });
    }
    if (method === "POST" && url.pathname === "/api/share") return json(202, { status: "queued" });
    return json(404, { error: { code: tensorMatch ? "unknown_tensor" : "not_found", message: "not served by the gate mock", details: null } });
  });
}

const tensorGets = (mock: Mock) => mock.log.filter((c) => c.method === "GET" && c.path.startsWith("/api/tensors/"));

async function openApp(page: Page, mock: Mock, query: string) {
  await page.goto("/" + (query ? "?" + query : ""));
  await expect(page.getByTestId("chart-canvas"), "chart-canvas must become visible").toBeVisible({ timeout: 20_000 });
  await expect.poll(() => tensorGets(mock).length, { message: "the page must fetch a tensor from the URL declared by /api/presets" }).toBeGreaterThan(0);
  await expect(page.getByTestId("point-selected"), "point-selected must become visible").toBeVisible();
  await expect(page.getByTestId("ceiling-line"), "ceiling-line must be attached").toBeAttached();
}

const urlParam = (page: Page, key: string) => new URL(page.url()).searchParams.get(key);

async function waitParam(page: Page, key: string, pred: (v: string | null) => boolean, what: string, timeout = 5000) {
  await expect.poll(() => pred(urlParam(page, key)), { message: `${what} (URL is ${page.url()})`, timeout }).toBe(true);
  return urlParam(page, key);
}

async function rectOf(target: Locator) {
  return target.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height, cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
  });
}

// The focusable handle of a slider test id: the element itself or its inner ARIA slider / range input.
async function sliderHandle(page: Page, testid: string): Promise<Locator> {
  const inner = page.getByTestId(testid).locator("xpath=descendant-or-self::*[@role='slider' or (self::input and @type='range')]");
  return (await inner.count()) > 0 ? inner.first() : page.getByTestId(testid);
}

// Press keys on a slider until the URL parameter satisfies pred; returns the key that worked.
async function pressUntil(page: Page, testid: string, keys: string[], param: string, pred: (v: string | null) => boolean, what: string) {
  const handle = await sliderHandle(page, testid);
  await handle.focus();
  for (const key of keys) {
    await page.keyboard.press(key);
    try {
      await expect.poll(() => pred(urlParam(page, param)), { timeout: 2500 }).toBe(true);
      return key;
    } catch {
      // try the next key
    }
  }
  throw new Error(`${what}: none of the keys ${keys.join(", ")} on ${testid} produced it (URL is ${page.url()})`);
}

// Chart scales from the overlay's axis ticks (d3-axis: g.tick with a line and a text in percent).
// Returns pixel = a + b * value in client coordinates, value as a fraction (5% -> 0.05).
async function chartScales(page: Page) {
  const groups = await page.getByTestId("chart").evaluate((chart) => {
    const byParent = new Map<Element, { value: number; px: number; py: number }[]>();
    for (const tick of Array.from(chart.querySelectorAll("svg g.tick"))) {
      const line = tick.querySelector("line");
      const text = tick.querySelector("text");
      if (!line || !text || !tick.parentElement) continue;
      const raw = (text.textContent || "").replace(/[−–]/g, "-").replace(/[^0-9.+\-]/g, "");
      const value = parseFloat(raw);
      if (!Number.isFinite(value)) continue;
      const r = line.getBoundingClientRect();
      if (!byParent.has(tick.parentElement)) byParent.set(tick.parentElement, []);
      byParent.get(tick.parentElement)!.push({ value: value / 100, px: r.left + r.width / 2, py: r.top + r.height / 2 });
    }
    return Array.from(byParent.values());
  });
  let x: { a: number; b: number } | null = null;
  let y: { a: number; b: number } | null = null;
  for (const ticks of groups) {
    if (ticks.length < 2) continue;
    const spread = (key: "px" | "py") => Math.max(...ticks.map((t) => t[key])) - Math.min(...ticks.map((t) => t[key]));
    const horizontal = spread("px") > spread("py");
    const pts = ticks.map((t) => ({ v: t.value, p: horizontal ? t.px : t.py })).sort((p, q) => p.v - q.v);
    const first = pts[0];
    const last = pts[pts.length - 1];
    if (last.v === first.v) continue;
    const b = (last.p - first.p) / (last.v - first.v);
    const a = first.p - b * first.v;
    const worst = Math.max(...pts.map((p) => Math.abs(a + b * p.v - p.p)));
    expect(worst, `axis ticks must lie on one linear scale (worst tick is ${worst.toFixed(2)} px off the first-to-last fit)`).toBeLessThanOrEqual(1);
    if (horizontal && !x) x = { a, b };
    if (!horizontal && !y) y = { a, b };
  }
  if (!x || !y) throw new Error("could not read both chart scales: the overlay needs an x and a y axis made of g.tick elements (a line and a percent text each), two or more ticks per axis");
  const sx = x;
  const sy = y;
  expect(sx.b, "risk must increase to the right").toBeGreaterThan(0);
  expect(sy.b, "return must increase upwards").toBeLessThan(0);
  return { x: (v: number) => sx.a + sx.b * v, y: (v: number) => sy.a + sy.b * v };
}

// Computed colours of CSS custom properties, resolved through a probe element inside the chart.
async function themeColors(page: Page, names: string[]): Promise<Record<string, Rgb>> {
  const raw = await page.getByTestId("chart").evaluate((chart, props) => {
    const probe = document.createElement("span");
    chart.appendChild(probe);
    const out: Record<string, string> = {};
    for (const name of props) {
      const declared = getComputedStyle(probe).getPropertyValue(name).trim();
      probe.style.color = "";
      probe.style.color = `var(${name})`;
      out[name] = declared === "" ? "" : getComputedStyle(probe).color;
    }
    probe.remove();
    return out;
  }, names);
  const out: Record<string, Rgb> = {};
  for (const name of names) {
    const nums = (raw[name].match(/-?\d+(\.\d+)?/g) || []).map(Number);
    if (!/^rgba?\(/.test(raw[name]) || nums.length < 3) throw new Error(`custom property ${name} does not compute to an rgb colour (got "${raw[name]}")`);
    out[name] = [nums[0], nums[1], nums[2]];
  }
  return out;
}

// d3-interpolate's interpolateRgbBasis, written out (uniform cubic B-spline per channel).
function rgbBasis(colors: Rgb[]): (t: number) => Rgb {
  const n = colors.length - 1;
  const channel = (c: number) => (tIn: number) => {
    let t = tIn;
    let i: number;
    if (t <= 0) { t = 0; i = 0; } else if (t >= 1) { t = 1; i = n - 1; } else i = Math.floor(t * n);
    const v1 = colors[i][c];
    const v2 = colors[i + 1][c];
    const v0 = i > 0 ? colors[i - 1][c] : 2 * v1 - v2;
    const v3 = i < n - 1 ? colors[i + 2][c] : 2 * v2 - v1;
    const t1 = (t - i / n) * n;
    const t2 = t1 * t1;
    const t3 = t2 * t1;
    return ((1 - 3 * t1 + 3 * t2 - t3) * v0 + (4 - 6 * t2 + 3 * t3) * v1 + (1 + 3 * t1 + 3 * t2 - 3 * t3) * v2 + t3 * v3) / 6;
  };
  const ch = [channel(0), channel(1), channel(2)];
  return (t: number) => [ch[0](t), ch[1](t), ch[2](t)];
}

const channelDistance = (p: number[], q: number[]) => Math.max(Math.abs(p[0] - q[0]), Math.abs(p[1] - q[1]), Math.abs(p[2] - q[2]));

// Canvas pixels at client coordinates, read with getImageData and composited over `bg`.
async function sampleCanvas(page: Page, points: { x: number; y: number }[], bg: Rgb): Promise<Rgb[]> {
  const res = await page.getByTestId("chart-canvas").evaluate((el, pts) => {
    if (!(el instanceof HTMLCanvasElement)) return { error: "chart-canvas is not a <canvas> element", pixels: [] as number[][] };
    const ctx = el.getContext("2d");
    if (!ctx) return { error: "chart-canvas has no 2d context", pixels: [] as number[][] };
    const rect = el.getBoundingClientRect();
    const sx = el.width / rect.width;
    const sy = el.height / rect.height;
    const pixels: number[][] = [];
    for (const p of pts) {
      const px = Math.floor((p.x - rect.left) * sx);
      const py = Math.floor((p.y - rect.top) * sy);
      if (px < 0 || py < 0 || px >= el.width || py >= el.height) return { error: `sample point (${p.x.toFixed(1)}, ${p.y.toFixed(1)}) is outside chart-canvas`, pixels };
      pixels.push(Array.from(ctx.getImageData(px, py, 1, 1).data));
    }
    return { error: "", pixels };
  }, points);
  if (res.error) throw new Error(res.error);
  return res.pixels.map((p) => {
    const a = p[3] / 255;
    return [p[0] * a + bg[0] * (1 - a), p[1] * a + bg[1] * (1 - a), p[2] * a + bg[2] * (1 - a)] as Rgb;
  });
}

// Signed percent in a readout such as "Bad six months −9.4%" -> -9.4 (percentage points).
function parsePercent(text: string, what: string): number {
  const m = text.replace(/[−–]/g, "-").match(/([+-]?)\s?(\d+(?:\.\d+)?)\s*%/);
  if (!m) throw new Error(`${what}: no percent value in "${text}"`);
  return (m[1] === "-" ? -1 : 1) * Number(m[2]);
}

const lerp = (arr: number[], pos: number) => {
  const i = Math.min(Math.floor(pos), arr.length - 2);
  const f = pos - i;
  return (1 - f) * arr[i] + f * arr[i + 1];
};
const dot = (a: number[], b: number[]) => a.reduce((acc, v, i) => acc + v * b[i], 0);

// Independent reading of the tensor (spec 4.9, 4.11): grid sizes, the slider domain and curve points.
function tensorFacts(tensor: any) {
  const NX: number = tensor.frontier.x.length;
  const curve = tensor.frontier_curve;
  if (curve.sigma.length !== 8 * (NX - 1) + 1) throw new Error(`fixture frontier_curve has ${curve.sigma.length} points, expected ${8 * (NX - 1) + 1}`);
  const low = (i: number) => curve.mu[i] / 2 - (1.96 * curve.sigma[i]) / Math.SQRT2;
  let best = -Infinity;
  let at = 0;
  for (let i = 0; i < curve.mu.length; i++) if (low(i) >= best) { best = low(i); at = i; }
  const sSafe = at / 8;
  if (Math.abs(sSafe - tensor.frontier.s_safe) > 1e-9) throw new Error(`fixture frontier.s_safe (${tensor.frontier.s_safe}) is not the rightmost maximum of Low_front over frontier_curve (${sSafe})`);
  const sMax = NX - 1;
  if (!(sMax > sSafe)) throw new Error("fixture risk-slider domain is a single point; these assertions need a real domain");
  const frontAt = (s: number) => {
    const sigma = lerp(curve.sigma, s * 8);
    const mu = lerp(curve.mu, s * 8);
    return { sigma, mu, lowPct: 100 * (mu / 2 - (1.96 * sigma) / Math.SQRT2), typicalPct: 100 * (mu / 2) };
  };
  const ceilingAt = (s: number) => lerp(tensor.frontier.x, s);
  const tSug = (j: number) => {
    const span = tensor.frontier.y[j] - tensor.grid.y_div[j];
    return tensor.grid.k_div[j] < 0 || span <= 0 ? 0 : (tensor.frontier.y[j] - tensor.grid.y_sug[j]) / span;
  };
  const tAuto = (s: number) => {
    const j = Math.min(Math.floor(s), NX - 2);
    const lam = s - j;
    return (1 - lam) * tSug(j) + lam * tSug(j + 1);
  };
  return { NX, sSafe, sMax, step: (sMax - sSafe) / 200, frontAt, ceilingAt, tAuto };
}

// ---------------------------------------------------------------------------------------------
// A-PS-43
// ---------------------------------------------------------------------------------------------
// Accepted amount formatting: optional "$", digits with optional thousands separators, up to two
// decimals (e.g. "10840", "10,840", "$10,840.00"). A blank amount reads as 0.
function parseAmount(text: string, id: string): number {
  const t = text.trim();
  if (t === "") return 0;
  if (!/^\$?\s?(\d{1,3}(,\d{3})+|\d+)(\.\d{1,2})?$/.test(t)) throw new Error(`fund-row-${id}: amount "${text}" is not a plain dollar amount`);
  return Number(t.replace(/[$,\s]/g, ""));
}

async function menuEntries(page: Page): Promise<{ kind: "select" | "menu"; texts: string[] }> {
  const menu = page.getByTestId("preset-menu");
  const select = menu.locator("xpath=descendant-or-self::select");
  if ((await select.count()) > 0) {
    return { kind: "select", texts: (await select.first().locator("option").allTextContents()).map((t) => t.trim()) };
  }
  await menu.click();
  const items = page.locator("[role=option], [role=menuitem], [role=menuitemradio]");
  await expect(items.first(), "preset-menu must open a list of role=option / menuitem / menuitemradio entries (or be a <select>)").toBeVisible();
  return { kind: "menu", texts: (await items.allTextContents()).map((t) => t.trim()) };
}

async function openFunds(page: Page) {
  const section = page.getByTestId("section-funds");
  if ((await section.getAttribute("aria-expanded")) !== "true") await page.getByTestId("chip-funds").click();
  await expect(section).toHaveAttribute("aria-expanded", "true");
}

test("default view is the first preset with its allocation; preset menu is driven by /api/presets", async ({ page }) => {
  const tensor = readFixture();
  const mock = buildMock(tensor);
  const [firstPreset, secondPreset] = mock.presets.presets;
  expect(firstPreset.funds.length, "the 2017 guide Step 2 holdings file lists 23 funds").toBe(23);
  const universeIds = [...tensor.universe.funds.map((f: any) => f.id), ...tensor.universe.excluded.map((e: any) => e.id)].sort();
  expect(universeIds, "the fixture's funds plus excluded funds must be the 23 Step 2 funds").toEqual(firstPreset.funds.map((f) => f.id).sort());
  expect(tensor.universe.excluded, "the fixture tensor must set no fund aside: its 23 funds are all used").toEqual([]);
  expect(tensor.universe.funds.length, "the fixture tensor must use all 23 Step 2 funds").toBe(23);
  expect(firstPreset.funds.map((f) => f.id), "FIENX must not be a fund of the default menu").not.toContain(SET_ASIDE.id);
  expect(secondPreset.name.endsWith("[mock-7f3]")).toBe(true);
  // The second menu of the mock: the same 23 funds plus FIENX, which its tensor sets aside.
  expect(secondPreset.funds.map((f) => f.id), "the mock's second menu is the 23 funds plus FIENX").toEqual([...firstPreset.funds.map((f) => f.id), SET_ASIDE.id]);
  const secondTensor = tensorBody(mock, mock.hash2, "5y");
  expect(secondTensor.universe.funds.map((f: any) => f.id), "the second tensor uses the same 23 funds").toEqual(tensor.universe.funds.map((f: any) => f.id));
  expect(secondTensor.universe.excluded, "the second tensor sets exactly FIENX aside").toHaveLength(1);
  const fienx = secondTensor.universe.excluded.find((e: any) => e.id === SET_ASIDE.id);
  expect(fienx, "the second tensor's universe.excluded must contain FIENX").toBeTruthy();
  expect(fienx.reason, "the second tensor's FIENX reason string").toBe(FIENX_REASON + SECOND_REASON_SUFFIX);

  await installMock(page, mock);
  await openApp(page, mock, "");

  // Leg 1: the first preset's declared 5y tensor is what was loaded; the current mix is shown.
  expect(mock.log.filter((c) => c.method === "GET" && c.path === "/api/presets").length, "GET /api/presets").toBeGreaterThanOrEqual(1);
  const declaredFirst = firstPreset.lookbacks["5y"].url;
  expect(tensorGets(mock).map((c) => c.path), "with no query the page loads the first preset's 5y tensor and no other").toEqual([declaredFirst]);
  await expect(page.getByTestId("point-current")).toBeVisible();

  // Leg 2: 23 fund rows in "$" mode with the body's amounts, 18 of them non-zero.
  await openFunds(page);
  const rows = page.locator('[data-testid^="fund-row-"]');
  await expect(rows, "23 fund rows").toHaveCount(23);
  const unit = await page.getByTestId("unit-toggle").evaluate((el) => {
    if (el instanceof HTMLSelectElement) return el.selectedOptions[0] ? el.selectedOptions[0].textContent || "" : "";
    const active = el.querySelector('[aria-checked="true"], [aria-pressed="true"], [aria-selected="true"], input:checked, option:checked');
    if (!active) return "";
    const labels = (active as HTMLInputElement).labels;
    return (labels && labels.length ? labels[0].textContent : active.textContent) || "";
  });
  expect(unit.trim(), 'unit-toggle must have "$" as its active option (aria-checked / aria-pressed / aria-selected = "true", or a checked input)').toBe("$");
  let nonZero = 0;
  let compared = 0;
  for (const fund of firstPreset.funds) {
    const row = page.getByTestId(`fund-row-${fund.id}`);
    await expect(row, `fund-row-${fund.id}`).toHaveCount(1);
    const input = row.locator("input:not([type=checkbox]):not([type=radio]):not([type=hidden])");
    expect(await input.count(), `fund-row-${fund.id} must hold its amount in an <input>`).toBeGreaterThanOrEqual(1);
    const shown = parseAmount(await input.first().inputValue(), fund.id);
    expect(shown, `fund-row-${fund.id} amount must equal the presets body's allocation`).toBe(mock.allocation[fund.id]);
    compared += 1;
    if (shown !== 0) nonZero += 1;
  }
  expect(compared).toBe(23);
  expect(nonZero, "exactly 18 non-zero amounts").toBe(18);

  // Leg 3: the default tensor sets no fund aside, so no fund row carries an excluded-note and
  // there is no row for FIENX.
  await expect(rows.getByTestId("excluded-note"), "the default view uses all 23 funds: no fund row may carry an excluded-note").toHaveCount(0);
  await expect(page.getByTestId("fund-row-FIENX"), "FIENX is not a fund of the default menu").toHaveCount(0);

  // Leg 4: the preset menu lists the body's names, in order.
  const entries = await menuEntries(page);
  const names = mock.presets.presets.map((p) => p.name);
  expect(entries.texts.slice(0, 2), "preset-menu entries must be the names in the /api/presets body, in order").toEqual(names);
  expect(entries.texts.slice(2).filter((t) => !/^Custom/.test(t)), "after the presets only the Custom entry may follow").toEqual([]);
  expect(entries.texts.join(" | "), "the distinctive suffix of the mock body must show").toContain("[mock-7f3]");
  expect(entries.texts.filter((t) => t === "TSP (G, F, C, S, I)"), "a hard-coded preset name that differs from the body").toEqual([]);

  // Leg 5: choosing the second entry fetches exactly the declared URL once and sets u=.
  const before = mock.log.length;
  const declaredSecond = secondPreset.lookbacks["5y"].url;
  expect(declaredSecond).not.toBe(declaredFirst);
  if (entries.kind === "select") await page.getByTestId("preset-menu").locator("xpath=descendant-or-self::select").first().selectOption({ index: 1 });
  else await page.locator("[role=option], [role=menuitem], [role=menuitemradio]").nth(1).click();
  await expect.poll(() => mock.log.slice(before).filter((c) => c.path === declaredSecond).length, { message: `one GET to ${declaredSecond}` }).toBeGreaterThanOrEqual(1);
  await waitParam(page, "u", (v) => v === secondPreset.id, `the address must gain u=${secondPreset.id}`);
  await expect(page.getByTestId("point-current"), "the second preset has no allocation, so no current-mix marker").toHaveCount(0);

  // Leg 6 (anchor): the second menu holds FIENX and its tensor sets FIENX aside. The FIENX row
  // carries the exact reason string of the tensor that was just served (it exists only in this
  // mock, so it cannot be a constant), and no other row carries a note.
  await openFunds(page);
  await expect(rows, "24 fund rows: the 23 funds and FIENX").toHaveCount(24);
  const note = page.getByTestId("fund-row-FIENX").getByTestId("excluded-note");
  await expect(note, "fund-row-FIENX must contain an excluded-note").toHaveCount(1);
  const noteText = async () => ((await note.first().textContent()) || "").replace(/\s+/g, " ").trim();
  await expect.poll(noteText, { message: "after the switch the FIENX note must show the second tensor's reason string" }).toContain(fienx.reason);
  expect([fienx.reason, `${fienx.reason}: not used`], "excluded-note text must be the tensor's reason (optionally followed by ': not used' as in spec 3.3)").toContain(await noteText());
  await expect(rows.getByTestId("excluded-note"), "only the fund the tensor sets aside carries an excluded-note").toHaveCount(1);

  await page.waitForLoadState("networkidle");
  const after = mock.log.slice(before);
  const tensorCalls = after.filter((c) => c.path.startsWith("/api/tensors"));
  expect(tensorCalls.map((c) => `${c.method} ${c.path}`), "choosing the second preset must issue exactly one GET to the declared tensor URL and no other tensor request").toEqual([`GET ${declaredSecond}`]);
  expect(tensorCalls.filter((c) => c.path !== declaredSecond).length).toBe(0);

  // Leg 7 (anchor, same row): the 10y tensor of the same menu gives FIENX another reason. The
  // note on the FIENX row must change to it: a reason remembered from the first tensor fails.
  const declaredTen = secondPreset.lookbacks["10y"].url;
  const tenTensor = tensorBody(mock, mock.hash2, "10y");
  const fienxTen = tenTensor.universe.excluded.find((e: any) => e.id === SET_ASIDE.id);
  expect(tenTensor.universe.excluded, "the second menu's 10y tensor sets exactly FIENX aside").toHaveLength(1);
  expect(fienxTen.reason, "the 10y tensor's FIENX reason differs from the 5y one").toBe(fienx.reason + " [10y]");
  if ((await page.getByTestId("section-settings").getAttribute("aria-expanded")) !== "true") await page.getByTestId("chip-settings").click();
  await expect(page.getByTestId("section-settings")).toHaveAttribute("aria-expanded", "true");
  const beforeTen = mock.log.length;
  await page.getByTestId("lookback-10y").click();
  await expect.poll(() => mock.log.slice(beforeTen).filter((c) => c.method === "GET" && c.path === declaredTen).length, { message: `one GET to ${declaredTen}` }).toBeGreaterThanOrEqual(1);
  await openFunds(page);
  await expect(rows, "still 24 fund rows in the 10y view").toHaveCount(24);
  await expect.poll(noteText, { message: "after the lookback switch the FIENX note must show the 10y tensor's reason string" }).toContain(fienxTen.reason);
  expect([fienxTen.reason, `${fienxTen.reason}: not used`], "excluded-note text must be the 10y tensor's reason (optionally followed by ': not used')").toContain(await noteText());
  await expect(rows.getByTestId("excluded-note"), "only the fund the tensor sets aside carries an excluded-note").toHaveCount(1);
});
"""
EXPECTED_TITLES = {
    "default view is the first preset with its allocation; preset menu is driven by /api/presets",
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


def test_a_ps_43_playwright():
    statuses = _run_playwright("a_ps_43", SPEC_TS, PROJECTS)
    expected = {(project, title) for project in PROJECTS for title in EXPECTED_TITLES}
    assert set(statuses) == expected, f"Playwright ran a different set of tests: {sorted(statuses)}"
    not_passed = {key: status for key, status in statuses.items() if status != "passed"}
    assert not not_passed, (
        f"Playwright legs not passed (failed, skipped, timed out or retried): {not_passed}"
    )
