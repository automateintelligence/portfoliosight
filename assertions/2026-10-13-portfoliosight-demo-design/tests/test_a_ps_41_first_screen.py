"""A-PS-41 - the first screen is the chart and its controls; sections are collapsed; no tangency marker.

Playwright (desktop 1366x900, all three themes via ?t=) run from pytest; stdlib only.

Mock (built by the embedded spec, no product mock server): page.route on /api/** serving
GET /api/presets (two presets: guide2017 with the allocation from
data/holdings/holdings_guide2017_step2.csv in "$", and tsp named "TSP (G, F, C, S, I) [mock-7f3]"
with a distinct hash and allocation null; six ready lookbacks each), GET /api/tensors/{G}/{hash}/{lb}
(web/fixtures/guide2017_5y.json with lookback.id patched; for the second hash also universe.hash,
preset_id, name and the excluded reasons patched), GET /api/symbols, GET /api/health,
POST /api/tensors, POST /api/share, anything else 404. Every /api/ request is logged.

Pinned interface (beyond the shared pins of the gate contract):
- web/ builds with `npm run build` and serves with `vite preview`; web/fixtures/guide2017_5y.json.
- html[data-theme], URL keys u, lb, r, d, t, x (spec 8.1); r and d are written to the address
  (debounced) after every change, with at least six decimals.
- test ids: chart, chart-canvas, risk-slider, div-slider, range-low, range-typical, range-high,
  div-word, chip-{funds,trades,stress,settings}, section-{funds,trades,stress,settings} (each
  carries aria-expanded), point-selected, point-div, point-current, ceiling-line, fund-row-{ID},
  stress-{id}.
- point-* and ceiling-line live in one <svg> overlay inside the chart element; its axes are
  d3-axis groups (g.tick with a line). Any other line/polyline, or a straight path, in that svg
  fails the assertion.
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
      { id: "tsp", name: SECOND_NAME, hash: hash2, funds, allocation: null, allocation_unit: null, lookbacks: lookbacks(hash2) },
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

// Signed percent in a readout such as "Bad year −9.4%" -> -9.4 (percentage points).
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
  // the slider's left end is the engine's (spec 4.9): the rightmost frontier node with the best bad year
  const bad: number[] = tensor.frontier.range.bad;
  const sSafe = bad.lastIndexOf(Math.max(...bad));
  if (sSafe !== tensor.frontier.s_safe) throw new Error(`fixture frontier.s_safe (${tensor.frontier.s_safe}) is not the rightmost frontier node with the best bad year (${sSafe})`);
  const sMax = NX - 1;
  if (!(sMax > sSafe)) throw new Error("fixture risk-slider domain is a single point; these assertions need a real domain");
  const frontAt = (s: number) => {
    const sigma = lerp(curve.sigma, s * 8);
    const mu = lerp(curve.mu, s * 8);
    // the frontier mix's bad and typical year (spec 4.9): the node figures blended between columns
    return { sigma, mu, lowPct: 100 * lerp(tensor.frontier.range.bad, s), typicalPct: 100 * lerp(tensor.frontier.range.typical, s) };
  };
  const ceilingAt = (s: number) => lerp(tensor.frontier.x, s);
  // the suggested point's position on each column's ladder (spec 4.8); 0 on a collapsed column
  const tSug = (j: number) => (tensor.ladder.collapsed[j] ? 0 : tensor.ladder.t_suggested[j]);
  const tAuto = (s: number) => {
    const j = Math.min(Math.floor(s), NX - 2);
    const lam = s - j;
    return (1 - lam) * tSug(j) + lam * tSug(j + 1);
  };
  return { NX, sSafe, sMax, step: (sMax - sSafe) / 200, frontAt, ceilingAt, tAuto };
}

// ---------------------------------------------------------------------------------------------
// A-PS-41
// ---------------------------------------------------------------------------------------------
const FIRST_SCREEN_IDS = [
  "chart-canvas", "risk-slider", "div-slider", "range-low", "range-typical", "range-high", "div-word",
  "chip-funds", "chip-trades", "chip-stress", "chip-settings",
];
const SECTIONS = ["funds", "trades", "stress", "settings"];
const HIDDEN_SELECTOR = "table, [data-testid^=fund-row-], [data-testid^=stress-]";

// Elements matching `selector` that are painted inside the viewport (rect clipped by every
// ancestor that clips overflow, then by the viewport; CSS-hidden elements do not count).
async function paintedInViewport(page: Page, selector: string): Promise<string[]> {
  return page.evaluate((sel) => {
    const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll(sel))) {
      if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue;
      const r = el.getBoundingClientRect();
      let left = Math.max(r.left, 0);
      let top = Math.max(r.top, 0);
      let right = Math.min(r.right, window.innerWidth);
      let bottom = Math.min(r.bottom, window.innerHeight);
      for (let anc = el.parentElement; anc; anc = anc.parentElement) {
        const cs = getComputedStyle(anc);
        if (cs.overflowX === "visible" && cs.overflowY === "visible") continue;
        const ar = anc.getBoundingClientRect();
        left = Math.max(left, ar.left);
        top = Math.max(top, ar.top);
        right = Math.min(right, ar.right);
        bottom = Math.min(bottom, ar.bottom);
      }
      if (right - left > 0.5 && bottom - top > 0.5) out.push(`<${el.tagName.toLowerCase()} data-testid="${el.getAttribute("data-testid") || ""}">`);
    }
    return out;
  }, selector);
}

for (const theme of THEMES) {
  test(`first screen, collapsed sections and markers: ${theme}`, async ({ page }) => {
    const mock = buildMock(readFixture());
    await installMock(page, mock);
    await openApp(page, mock, `t=${theme}`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.getByTestId("point-current"), "the fixture preset has an allocation, so point-current is shown").toBeVisible();

    // Leg 1: every named control is inside the first viewport without scrolling.
    const first = await page.evaluate((ids) => ({
      scrollY: window.scrollY,
      w: window.innerWidth,
      h: window.innerHeight,
      items: ids.map((id) => {
        const el = document.querySelector(`[data-testid="${id}"]`);
        if (!el) return { id, missing: true, visible: false, left: 0, top: 0, right: 0, bottom: 0 };
        const r = el.getBoundingClientRect();
        return { id, missing: false, visible: el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && r.width > 0 && r.height > 0, left: r.left, top: r.top, right: r.right, bottom: r.bottom };
      }),
    }), FIRST_SCREEN_IDS);
    expect(first.scrollY, "the page must not be scrolled on load").toBe(0);
    expect(first.h, "desktop project viewport height").toBe(900);
    expect(first.items.length).toBe(11);
    for (const item of first.items) {
      expect(item.missing, `${item.id} is not in the DOM`).toBe(false);
      expect(item.visible, `${item.id} is not visible`).toBe(true);
      expect(item.top >= 0 && item.bottom <= 900 && item.left >= 0 && item.right <= first.w, `${item.id} is not inside the first viewport: top ${item.top}, bottom ${item.bottom}, left ${item.left}, right ${item.right}`).toBe(true);
    }

    // Leg 2: no table, fund row or stress card is painted in the first viewport.
    expect(await paintedInViewport(page, HIDDEN_SELECTOR), "tables, fund rows and stress cards must not be visible on the first screen").toEqual([]);

    // Leg 3: all four sections are collapsed on load.
    for (const id of SECTIONS) {
      await expect(page.getByTestId(`section-${id}`), `section-${id} must be collapsed on load`).toHaveAttribute("aria-expanded", "false");
    }

    // Leg 4: the overlay holds exactly the three markers and nothing tangency-like.
    const overlay = await page.getByTestId("point-selected").evaluate((point) => {
      const svg = point.closest("svg");
      const chart = document.querySelector('[data-testid="chart"]');
      if (!svg || !chart) return null;
      const ids = (root: ParentNode) => Array.from(root.querySelectorAll('[data-testid^="point-"]')).map((el) => el.getAttribute("data-testid") || "");
      const banned = /sharpe|tangency|capital market/i;
      const textHits: string[] = [];
      for (const el of [chart, ...Array.from(chart.querySelectorAll("*"))]) {
        const label = el.getAttribute("aria-label") || "";
        const own = Array.from(el.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent || "").join(" ");
        if (banned.test(label) || banned.test(own)) textHits.push(`<${el.tagName.toLowerCase()}> ${label} ${own}`.trim());
      }
      const allowed = (el: Element) =>
        !!el.closest('[data-testid="ceiling-line"]') || !!el.closest("g.tick") || (!!el.parentElement && !!el.parentElement.querySelector(":scope > g.tick"));
      const strayLines = Array.from(svg.querySelectorAll("line, polyline")).filter((el) => !allowed(el)).map((el) => el.outerHTML.slice(0, 160));
      const strayPaths: string[] = [];
      for (const el of Array.from(svg.querySelectorAll("path")) as SVGPathElement[]) {
        if (allowed(el) || el.closest('[data-testid^="point-"]')) continue;
        const len = el.getTotalLength();
        const p0 = el.getPointAtLength(0);
        const p1 = el.getPointAtLength(len);
        if (len > 8 && len - Math.hypot(p1.x - p0.x, p1.y - p0.y) < 1) strayPaths.push(el.outerHTML.slice(0, 160));
      }
      return {
        inSvg: ids(svg).sort(), inDocument: ids(document).sort(), textHits, strayLines, strayPaths,
        ticks: svg.querySelectorAll("g.tick line").length,
        ceilingInSvg: !!svg.querySelector('[data-testid="ceiling-line"]'),
      };
    });
    expect(overlay, "point-selected must live in an <svg> overlay inside the chart element").not.toBeNull();
    const want = ["point-current", "point-div", "point-selected"];
    expect(overlay!.inSvg, "the overlay's markers must be exactly point-selected, point-div and point-current").toEqual(want);
    expect(overlay!.inDocument, "no fourth point-* marker anywhere in the page").toEqual(want);
    expect(overlay!.textHits, "no Sharpe / tangency / capital market text or aria-label in the chart").toEqual([]);
    expect(overlay!.ticks, "the overlay must carry the axes (g.tick lines), so the stray-line scan looked at real content").toBeGreaterThanOrEqual(4);
    expect(overlay!.ceilingInSvg, "ceiling-line must be in the overlay").toBe(true);
    expect(overlay!.strayLines, "no line in the overlay other than ceiling-line and the axes").toEqual([]);
    expect(overlay!.strayPaths, "no straight path in the overlay other than ceiling-line and the axes").toEqual([]);

    // Leg 5: each chip expands its matching section and brings it into view (stress first).
    for (const id of ["stress", "funds", "trades", "settings"]) {
      await page.getByTestId(`chip-${id}`).click();
      const section = page.getByTestId(`section-${id}`);
      await expect(section, `chip-${id} must expand section-${id}`).toHaveAttribute("aria-expanded", "true");
      await expect.poll(async () => {
        const r = await rectOf(section);
        return r.height > 0 && r.top < 900 && r.bottom > 0;
      }, { message: `chip-${id} must scroll section-${id} into view` }).toBe(true);
    }
    // Control for leg 2: the selector finds real, visible content once the sections are open.
    await expect(page.locator('[data-testid^="stress-"]').first()).toBeVisible();
    await expect(page.locator('[data-testid^="fund-row-"]').first()).toBeVisible();
    expect(await page.locator('[data-testid^="stress-"]').count(), "three stress cards after expanding").toBeGreaterThanOrEqual(3);
  });
}
"""
EXPECTED_TITLES = {
    "first screen, collapsed sections and markers: ks-dark",
    "first screen, collapsed sections and markers: light",
    "first screen, collapsed sections and markers: hud",
    "first screen, collapsed sections and markers: grid",
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


def test_a_ps_41_playwright():
    statuses = _run_playwright("a_ps_41", SPEC_TS, PROJECTS)
    expected = {(project, title) for project in PROJECTS for title in EXPECTED_TITLES}
    assert set(statuses) == expected, f"Playwright ran a different set of tests: {sorted(statuses)}"
    not_passed = {key: status for key, status in statuses.items() if status != "passed"}
    assert not not_passed, (
        f"Playwright legs not passed (failed, skipped, timed out or retried): {not_passed}"
    )
