"""A-PS-49 — four themes with distinct computed tokens and a repainted canvas; the choice is
remembered; HUD references nothing.

Phase 3, ui + static (Playwright against `vite preview` run from pytest, plus a repository scan in
pytest; standard library only).

UI legs (desktop): `theme-switch` steps ks-dark -> light -> hud -> grid -> ks-dark on `html[data-theme]` and
`localStorage("ps.theme")` follows; per theme the computed `--bg`, `--surface`, `--text`,
`--accent`, `--frontier` and `--heat-0..4` equal the spec 3.5 table embedded here (any CSS colour
syntax, normalised to hex by painting it) and none carries another theme's column; an opaque pixel
of the `--frontier` colour is found in at least 25% of the canvas columns (the frontier stroke); the
mean RGB of 50 fixed canvas samples (over the theme's `--bg`) differs by more than 20/255 on some
channel between every pair of themes, on fresh loads and when switching in place; the stored theme
survives a load without `t=`; `?t=hud` wins over a stored `light` and `?t=grid` over a stored `hud`; under
`prefers-reduced-motion: reduce` no element (or its ::before/::after) has a non-zero computed
`transition-duration`, in all four themes with the sections expanded.
Static leg: zero hits of the needle list (kept only in this file) in `web/src`, `web/worker`,
`data/`, `README.md`, `ROADMAP.md`, `docs/specs`, `docs/plans/*runbook*` (excluding the assertions
file, the original prompt, `docs/reviews/` and `assertions/`), and at least 20 hits of the word HUD.

The Playwright spec mocks /api/* itself (page.route) from web/fixtures/guide2017_5y.json and
data/holdings/holdings_guide2017_step2.csv: GET /api/presets (guide2017 with its "$" allocation and
tsp with allocation null, a distinct hash and the same tensor re-labelled), GET /api/tensors/{G}/
{hash}/{lb}, GET /api/symbols, GET /api/health, POST /api/tensors (200 ready, body recorded),
POST /api/share (202), anything else 404. Views are addressed through the spec 8.1 URL keys; with
an integer `r` inside the slider domain and `d=0` the selected mix is exactly `frontier.w[r]`
(`d=1`: `grid.w_div[r]`), which is what the test recomputes from. The product must keep `r` and `d`
as given (it may leave the URL untouched or rewrite the same values).

Pinned interface (beyond the shared pins)
- `theme-switch` is either one clickable that cycles ks-dark -> light -> hud -> grid, or a group
  holding exactly four `button` / `[role=radio]` segments in that order.
- `chart-canvas` is a `<canvas>` that can be read with `drawImage` (2D, or WebGL with
  `preserveDrawingBuffer`); the heatmap and the frontier stroke are painted on it.
- With no `t=` and empty storage the theme is `ks-dark`.
"""

# ruff: noqa: E501
from __future__ import annotations

import json
import os
import re
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
const THEMES = ["ks-dark", "light", "hud", "grid"] as const;
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

// theme-switch: either one clickable that cycles ks-dark -> light -> hud -> grid, or a group holding
// exactly four button / role=radio segments in that order. Returns the theme that should now be active.
async function advanceTheme(page: Page): Promise<string> {
  const order = ["ks-dark", "light", "hud", "grid"];
  const current = (await page.locator("html").getAttribute("data-theme")) ?? "";
  const next = order[(order.indexOf(current) + 1) % 4];
  const control = page.getByTestId("theme-switch");
  const segments = control.locator('button, [role="radio"]');
  if ((await segments.count()) === 4) await segments.nth(order.indexOf(next)).click();
  else await control.click();
  return next;
}

// ---------------------------------------------------------------------------------------------
// A-PS-49, UI legs
// ---------------------------------------------------------------------------------------------
// spec 3.5 token table (the declared set of this assertion)
const TOKENS: Record<string, Record<string, string>> = {
  "ks-dark": {
    "--bg": "#141417", "--surface": "#1A1A1E", "--text": "#EAE6E2", "--accent": "#C76346", "--frontier": "#EAE6E2",
    "--heat-0": "#1A1A1E", "--heat-1": "#4A2A24", "--heat-2": "#A54930", "--heat-3": "#E8907E", "--heat-4": "#F5DCC9",
  },
  light: {
    "--bg": "#F3F3F3", "--surface": "#FFFFFF", "--text": "#1B1B1B", "--accent": "#0F6CBD", "--frontier": "#1B1B1B",
    "--heat-0": "#FFFFFF", "--heat-1": "#DCEBF9", "--heat-2": "#8BBDEA", "--heat-3": "#2F86D1", "--heat-4": "#0B5394",
  },
  hud: {
    "--bg": "#080506", "--surface": "#170D0B", "--text": "#F6EEE3", "--accent": "#D63A18", "--frontier": "#FFF4DC",
    "--heat-0": "#080506", "--heat-1": "#3D0E08", "--heat-2": "#B02A10", "--heat-3": "#F08A24", "--heat-4": "#FFE39A",
  },
  grid: {
    "--bg": "#04070B", "--surface": "#0A1119", "--text": "#D7F3FA", "--accent": "#35C9E8", "--frontier": "#C8F7FF",
    "--heat-0": "#04070B", "--heat-1": "#0B2F3F", "--heat-2": "#1D8FA8", "--heat-3": "#35C9E8", "--heat-4": "#C8F7FF",
  },
};
const TOKEN_NAMES = Object.keys(TOKENS["ks-dark"]);
const hexToRgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const storedTheme = (page: Page) => page.evaluate(() => window.localStorage.getItem("ps.theme"));

// 50 fixed samples (a 10 x 5 lattice) of the chart canvas, as raw RGBA.
async function canvasSamples(page: Page): Promise<number[][]> {
  return page.getByTestId("chart-canvas").evaluate((el) => {
    const source = el as HTMLCanvasElement;
    const copy = document.createElement("canvas");
    copy.width = source.width;
    copy.height = source.height;
    const ctx = copy.getContext("2d", { willReadFrequently: true })!;
    ctx.drawImage(source, 0, 0);
    const out: number[][] = [];
    for (let i = 0; i < 10; i++) {
      for (let k = 0; k < 5; k++) {
        const x = Math.floor(((i + 0.5) / 10) * source.width);
        const y = Math.floor(((k + 0.5) / 5) * source.height);
        out.push(Array.from(ctx.getImageData(x, y, 1, 1).data));
      }
    }
    return out;
  });
}

// Mean RGB of the 50 samples as the visitor sees them (canvas pixel over the theme's --bg).
function meanOverBackground(samples: number[][], bgHex: string): number[] {
  const bg = hexToRgb(bgHex);
  const sum = [0, 0, 0];
  for (const [r, g, b, a] of samples) {
    const px = [r, g, b];
    for (let c = 0; c < 3; c++) sum[c] += (px[c] * a + bg[c] * (255 - a)) / 255;
  }
  return sum.map((v) => v / samples.length);
}
const maxChannelGap = (a: number[], b: number[]) => Math.max(...a.map((v, i) => Math.abs(v - b[i])));

async function paintedMean(page: Page, theme: string): Promise<number[]> {
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect
    .poll(async () => (await canvasSamples(page)).filter((px) => px[3] > 0).length, { message: `canvas painted in ${theme}` })
    .toBeGreaterThanOrEqual(10);
  const samples = await canvasSamples(page);
  expect(samples.length).toBe(50);
  return meanOverBackground(samples, await tokenHex(page, "--bg"));
}

// Share of canvas columns holding an opaque pixel of the given colour (the 2 px frontier stroke).
async function columnsWithColour(page: Page, hex: string): Promise<number> {
  return page.getByTestId("chart-canvas").evaluate((el, rgb) => {
    const source = el as HTMLCanvasElement;
    const copy = document.createElement("canvas");
    copy.width = source.width;
    copy.height = source.height;
    const ctx = copy.getContext("2d", { willReadFrequently: true })!;
    ctx.drawImage(source, 0, 0);
    const data = ctx.getImageData(0, 0, copy.width, copy.height).data;
    let columns = 0;
    for (let x = 0; x < copy.width; x++) {
      for (let y = 0; y < copy.height; y++) {
        const i = 4 * (y * copy.width + x);
        if (data[i + 3] >= 250 && Math.abs(data[i] - rgb[0]) <= 6 && Math.abs(data[i + 1] - rgb[1]) <= 6 && Math.abs(data[i + 2] - rgb[2]) <= 6) {
          columns += 1;
          break;
        }
      }
    }
    return copy.width > 0 ? columns / copy.width : 0;
  }, hexToRgb(hex));
}

test("theme switch cycles ks-dark light hud grid and stores the choice", async ({ page }) => {
  await installMock(page, readFixtureTensor());
  await openApp(page, "");
  await expect(page.locator("html"), "default theme").toHaveAttribute("data-theme", "ks-dark");
  const seen: string[] = [];
  for (let click = 0; click < 4; click++) {
    const next = await advanceTheme(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", next);
    await expect.poll(() => storedTheme(page), { message: "localStorage ps.theme follows the choice" }).toBe(next);
    seen.push(next);
  }
  expect(seen).toEqual(["light", "hud", "grid", "ks-dark"]);
  expect(new Set(seen).size, "four distinct themes").toBe(4);
});

for (const theme of THEMES) {
  test(`tokens ${theme}`, async ({ page }) => {
    await installMock(page, readFixtureTensor());
    await openApp(page, `t=${theme}`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    let checked = 0;
    for (const name of TOKEN_NAMES) {
      const actual = await tokenHex(page, name);
      expect(actual, `${name} in ${theme}`).toBe(TOKENS[theme][name].toLowerCase());
      for (const other of THEMES) {
        const foreign = TOKENS[other][name].toLowerCase();
        if (other !== theme && foreign !== TOKENS[theme][name].toLowerCase()) {
          expect(actual, `${name} in ${theme} carries the ${other} column`).not.toBe(foreign);
        }
      }
      checked += 1;
    }
    expect(checked).toBe(10);
    await expect
      .poll(() => columnsWithColour(page, TOKENS[theme]["--frontier"]), { message: `frontier stroke drawn in --frontier (${theme})` })
      .toBeGreaterThanOrEqual(0.25);
  });
}

test("canvas repaints for every theme", async ({ page }) => {
  await installMock(page, readFixtureTensor());
  // each theme loaded on its own
  const loaded: Record<string, number[]> = {};
  for (const theme of THEMES) {
    await openApp(page, `t=${theme}`);
    loaded[theme] = await paintedMean(page, theme);
  }
  for (const [a, b] of [["ks-dark", "light"], ["light", "hud"], ["ks-dark", "hud"], ["ks-dark", "grid"], ["light", "grid"], ["hud", "grid"]]) {
    expect(maxChannelGap(loaded[a], loaded[b]), `canvas mean RGB ${a} vs ${b}: ${loaded[a]} / ${loaded[b]}`).toBeGreaterThan(20);
  }
  // and repainted in place when the switch is used (no reload)
  await openApp(page, "t=ks-dark");
  let previous = await paintedMean(page, "ks-dark");
  for (let click = 0; click < 3; click++) {
    const next = await advanceTheme(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", next);
    const before = previous;
    await expect
      .poll(async () => maxChannelGap(before, await paintedMean(page, next)), { message: `canvas repainted after switching to ${next}` })
      .toBeGreaterThan(20);
    previous = await paintedMean(page, next);
    expect(maxChannelGap(previous, loaded[next]), `in-place repaint of ${next} matches a fresh load`).toBeLessThanOrEqual(20);
  }
});

test("theme choice survives reload and t= wins over storage", async ({ page }) => {
  await installMock(page, readFixtureTensor());
  await openApp(page, "");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "ks-dark");
  expect(await advanceTheme(page)).toBe("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect.poll(() => storedTheme(page)).toBe("light");
  await openApp(page, ""); // a reload without t=
  expect(urlParam(page, "t") === null || urlParam(page, "t") === "light", "no other theme in the URL").toBe(true);
  await expect(page.locator("html"), "stored theme restored without t=").toHaveAttribute("data-theme", "light");
  expect(await page.locator("html").getAttribute("data-theme")).not.toBe("ks-dark");

  // light is stored; ?t=hud must win
  await openApp(page, "t=hud");
  await expect(page.locator("html"), "?t=hud beats storage").toHaveAttribute("data-theme", "hud");
  expect(await page.locator("html").getAttribute("data-theme")).not.toBe("light");

  // the same for hud stored and no t=
  await expect.poll(async () => ["hud", "light"].includes((await storedTheme(page)) ?? "")).toBe(true);
  await page.evaluate(() => window.localStorage.setItem("ps.theme", "hud"));
  await openApp(page, "");
  await expect(page.locator("html"), "stored hud restored").toHaveAttribute("data-theme", "hud");

  // hud is stored; ?t=grid must win, and a stored grid comes back without t=
  await openApp(page, "t=grid");
  await expect(page.locator("html"), "?t=grid beats storage").toHaveAttribute("data-theme", "grid");
  await page.evaluate(() => window.localStorage.setItem("ps.theme", "grid"));
  await openApp(page, "");
  await expect(page.locator("html"), "stored grid restored").toHaveAttribute("data-theme", "grid");
});

test("reduced motion leaves no css transition", async ({ page }) => {
  await installMock(page, readFixtureTensor());
  await page.emulateMedia({ reducedMotion: "reduce" });
  let scanned = 0;
  for (const theme of THEMES) {
    await openApp(page, `t=${theme}`);
    expect(await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
    await expandAll(page, true);
    const result = await page.evaluate(() => {
      const toMs = (value: string) => value.split(",").map((part) => part.trim()).map((part) => (part.endsWith("ms") ? parseFloat(part) : parseFloat(part) * 1000));
      const moving: string[] = [];
      let count = 0;
      for (const el of Array.from(document.querySelectorAll("*"))) {
        for (const pseudo of [null, "::before", "::after"]) {
          const duration = getComputedStyle(el, pseudo).transitionDuration || "0s";
          count += 1;
          if (toMs(duration).some((ms) => ms > 0)) {
            moving.push(`${el.tagName.toLowerCase()}[${el.getAttribute("data-testid") ?? el.className}]${pseudo ?? ""} ${duration}`);
          }
        }
      }
      return { count, moving: moving.slice(0, 10) };
    });
    expect(result.moving, `elements with a non-zero transition-duration under reduced motion (${theme})`).toEqual([]);
    expect(result.count, "elements scanned").toBeGreaterThanOrEqual(150);
    scanned += result.count;
  }
  expect(scanned).not.toBe(0);
});
"""
EXPECTED_TITLES = {
    "theme switch cycles ks-dark light hud grid and stores the choice",
    "tokens ks-dark",
    "tokens light",
    "tokens hud",
    "tokens grid",
    "canvas repaints for every theme",
    "theme choice survives reload and t= wins over storage",
    "reduced motion leaves no css transition",
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


# --- static leg -------------------------------------------------------------------------------
# The needle list lives only in this file: the film behind the owner's "HUD" reference, its
# characters and trademarked terms. Word-bounded, case-insensitive.
_NEEDLES = (
    r"\biron[\s_-]*man\b",
    r"\btony[\s_-]+stark\b",
    r"\bstark[\s_-]+industries\b",
    r"\bj\.?a\.?r\.?v\.?i\.?s\b",
    r"\bmarvel\b",
    r"\bavengers?\b",
    r"\bpepper[\s_-]+potts\b",
    r"\barc[\s_-]+reactor\b",
)
_NEEDLE_RE = re.compile("|".join(_NEEDLES), re.IGNORECASE)
_HUD_RE = re.compile(r"\bHUD\b")
_SCOPE_DIRS = ("web/src", "web/worker", "data", "docs/specs")
_SCOPE_FILES = ("README.md", "ROADMAP.md")
_EXCLUDED_FILES = (
    "docs/specs/2026-10-13-portfoliosight-demo-design.assertions.md",
    "docs/plans/2026-10-12_original_prompt.md",
)
_EXCLUDED_DIRS = ("assertions/", "docs/reviews/")


def _scoped_files() -> list[Path]:
    files: list[Path] = []
    for rel in _SCOPE_DIRS:
        base = ROOT / rel
        if base.is_dir():
            files.extend(p for p in sorted(base.rglob("*")) if p.is_file())
    files.extend(ROOT / rel for rel in _SCOPE_FILES if (ROOT / rel).is_file())
    plans = ROOT / "docs" / "plans"
    if plans.is_dir():
        files.extend(
            p for p in sorted(plans.iterdir()) if p.is_file() and "runbook" in p.name.lower()
        )
    kept = []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if (
            rel in _EXCLUDED_FILES
            or rel.startswith(_EXCLUDED_DIRS)
            or "/node_modules/" in f"/{rel}"
        ):
            continue
        kept.append(path)
    return kept


def test_a_ps_49_static_no_film_reference():
    # the needle pattern is live (control), and the scan does not flag the plain word it protects
    assert _NEEDLE_RE.search("styled like the Iron Man helmet") is not None
    assert _NEEDLE_RE.search("the HUD theme draws corner brackets") is None
    for rel in ("web/src", "web/worker"):
        base = ROOT / rel
        assert base.is_dir() and any(p.is_file() for p in base.rglob("*")), (
            f"{rel}/ is missing or empty: the front end is not built yet"
        )
    for rel in ("README.md", "ROADMAP.md", "docs/specs", "data"):
        assert (ROOT / rel).exists(), f"{rel} is missing from the scan scope"
    files = _scoped_files()
    assert len(files) >= 10, f"the scan scope holds only {len(files)} files"
    for excluded in _EXCLUDED_FILES:
        assert excluded not in {p.relative_to(ROOT).as_posix() for p in files}
    hits: list[str] = []
    hud = 0
    scanned = 0
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if _NEEDLE_RE.search(rel):
            hits.append(f"{rel} (file name)")
        text = path.read_bytes().decode("utf-8", errors="replace")
        scanned += 1
        for number, line in enumerate(text.splitlines(), start=1):
            if _NEEDLE_RE.search(line):
                hits.append(f"{rel}:{number}")
            hud += len(_HUD_RE.findall(line))
    assert scanned == len(files)
    assert not hits, (
        f"references to the film, its characters or trademarks behind the HUD look: {hits[:20]}"
    )
    assert hud >= 20, (
        f"only {hud} occurrences of the word HUD in the scope (need >= 20 to prove the scope is populated)"
    )


def test_a_ps_49_playwright():
    statuses = _run_playwright("a_ps_49", SPEC_TS, PROJECTS)
    expected = {(project, title) for project in PROJECTS for title in EXPECTED_TITLES}
    assert set(statuses) == expected, f"Playwright ran a different set of tests: {sorted(statuses)}"
    not_passed = {key: status for key, status in statuses.items() if status != "passed"}
    assert not not_passed, (
        f"Playwright legs not passed (failed, skipped, timed out or retried): {not_passed}"
    )
