"""A-PS-53 — cap edits are validated inline and sent only when valid.

Phase 3, ui (Playwright against `vite preview`, run from pytest; desktop; standard library only).

Invalid: `cap-min-VTI` set above `cap-max-VTI` shows an inline error and no POST leaves the page
(1.5 s bounded wait). Valid: `cap-max-VTI = 10` sends exactly one `POST /api/tensors` whose body
carries VTI with `min` null and `max` 0.10 and every other fund null/null (an absent key counts as
null), lookback 5y; the address gets `c=VTI::10` and the chart is back. Reset: after the valid edit
`caps-reset` sends one more POST with an all-null policy, every `cap-max-{ID}` reads the rule value
`clamp(3/N, 0.25, 1)` in percent and every `cap-min-{ID}` reads 0, `c` is cleared, and Settings
states "No single fund above P% (menu of N)" with P the resolved maximum and N the tensor's
included fund count or included + excluded count.

The Playwright spec mocks /api/* itself (page.route) from web/fixtures/guide2017_5y.json and
data/holdings/holdings_guide2017_step2.csv: GET /api/presets (guide2017 with its "$" allocation and
tsp with allocation null, a distinct hash and the same tensor re-labelled), GET /api/tensors/{G}/
{hash}/{lb}, GET /api/symbols, GET /api/health, POST /api/tensors (200 ready, body recorded),
POST /api/share (202), anything else 404. Views are addressed through the spec 8.1 URL keys; with
an integer `r` inside the slider domain and `d=0` the selected mix is exactly `frontier.w[r]`
(`d=1`: `grid.w_div[r]`), which is what the test recomputes from. The product must keep `r` and `d`
as given (it may leave the URL untouched or rewrite the same values).

Pinned interface (beyond the shared pins)
- `cap-min-{ID}` / `cap-max-{ID}` are inputs in percent that show the resolved rule values by
  default; an edit is committed on blur (Tab).
- The inline error is the target of `aria-errormessage` / `aria-describedby` of either VTI field, or
  a `role=alert` element inside the smallest container holding both fields.
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
// A-PS-53
// ---------------------------------------------------------------------------------------------
const RULE_RE = /No single fund above (\d+(?:\.\d+)?)% \(menu of (\d+)\)/;
const orNull = (v: any) => (v === undefined ? null : v);

function ruleMax(tensor: any): number {
  const n = tensor.universe.funds.length;
  const rule = Math.min(1, Math.max(0.25, 3 / n));
  const requested: any[] = tensor.bounds?.requested ?? [];
  if (requested.some((b) => orNull(b?.min) !== null || orNull(b?.max) !== null)) {
    throw new Error("the fixture tensor was built with cap overrides; A-PS-53 needs the default rule (bounds.requested all null)");
  }
  if ((tensor.bounds?.max ?? []).length !== n || tensor.bounds.max.some((v: number) => Math.abs(v - rule) > 1e-9)) {
    throw new Error(`the fixture's bounds.max is not the default rule clamp(3/N, 0.25, 1) = ${rule} for N = ${n}`);
  }
  return rule;
}

async function openSettings(page: Page): Promise<void> {
  await openApp(page, "u=guide2017&lb=5y");
  await page.getByTestId("chip-settings").click();
  await expect(page.getByTestId("section-settings")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("cap-max-VTI")).toBeVisible();
  await expect(page.getByTestId("cap-min-VTI")).toBeVisible();
}

// The inline error of the VTI cap fields: the target of aria-errormessage / aria-describedby of
// either field, or a role=alert element inside the smallest container holding both fields.
async function capErrorText(page: Page): Promise<string> {
  return page.evaluate(() => {
    const byId = (id: string) => document.querySelector(`[data-testid="${id}"]`);
    const lo = byId("cap-min-VTI"), hi = byId("cap-max-VTI");
    if (!lo || !hi) return "";
    const visible = (el: Element) => {
      const rect = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
    };
    const found = new Set<Element>();
    for (const input of [lo, hi]) {
      for (const attr of ["aria-errormessage", "aria-describedby"]) {
        for (const id of (input.getAttribute(attr) ?? "").split(/\s+/).filter(Boolean)) {
          const el = document.getElementById(id);
          if (el && visible(el)) found.add(el);
        }
      }
    }
    let row: Element | null = lo.parentElement;
    while (row && !row.contains(hi)) row = row.parentElement;
    if (row) for (const el of Array.from(row.querySelectorAll('[role="alert"]'))) if (visible(el)) found.add(el);
    return Array.from(found).map((el) => (el.textContent ?? "").replace(/\s+/g, " ").trim()).filter(Boolean).join(" | ");
  });
}

async function ruleSentence(page: Page, tensor: any): Promise<void> {
  const text = norm((await page.getByTestId("section-settings").textContent()) ?? "");
  const m = text.match(RULE_RE);
  expect(m, 'Settings must state the rule as "No single fund above P% (menu of N)"').not.toBeNull();
  expect(Math.abs(Number(m![1]) - ruleMax(tensor) * 100), `rule percentage ${m![1]}`).toBeLessThanOrEqual(0.05);
  const included = tensor.universe.funds.length;
  const excluded = (tensor.universe.excluded ?? []).length;
  expect([included, included + excluded], `menu size ${m![2]} in the rule sentence`).toContain(Number(m![2]));
}

// Every fund's min/max of one POST body against the expected overrides (absent key = null).
function checkPolicy(body: any, tensor: any, edited: Record<string, { min: number | null; max: number | null }>): void {
  expect(body?.lookback, "POST body lookback").toBe("5y");
  expect(Array.isArray(body?.funds), "POST body funds is a list").toBe(true);
  const ids: string[] = body.funds.map((f: any) => f.id);
  expect(new Set(ids).size, "no duplicate fund in the POST body").toBe(ids.length);
  const included: string[] = tensor.universe.funds.map((f: any) => f.id);
  const allowed = new Set([...included, ...(tensor.universe.excluded ?? []).map((f: any) => f.id)]);
  for (const id of included) expect(ids, `fund ${id} missing from the POST body`).toContain(id);
  for (const id of ids) expect(allowed.has(id), `unexpected fund ${id} in the POST body`).toBe(true);
  for (const fund of body.funds) {
    const want = edited[fund.id] ?? { min: null, max: null };
    for (const side of ["min", "max"] as const) {
      const got = orNull(fund[side]);
      if (want[side] === null) expect(got, `${fund.id}.${side} must be null (unedited)`).toBeNull();
      else {
        expect(got, `${fund.id}.${side}`).not.toBeNull();
        expect(Math.abs(got - (want[side] as number)), `${fund.id}.${side} = ${got}`).toBeLessThanOrEqual(1e-9);
      }
    }
  }
}

async function editVtiMax(page: Page, mock: Mock, before: number): Promise<void> {
  await page.getByTestId("cap-max-VTI").fill("10");
  await page.keyboard.press("Tab");
  await expect.poll(() => mock.tensorPosts().length, { message: "one POST /api/tensors after the valid cap edit" }).toBe(before + 1);
}

test("invalid cap shows an inline error and sends nothing", async ({ page }) => {
  const tensor = readFixtureTensor();
  const rule = ruleMax(tensor);
  const mock = await installMock(page, tensor);
  await openSettings(page);
  await ruleSentence(page, tensor);
  const quiet = await capErrorText(page);
  const before = mock.tensorPosts().length;
  // POST /api/range asks for the one-year range of the mix on screen once the sliders rest; it
  // carries no limits and is not a send of the cap table
  const sends = () => mock.calls.filter((c) => c.method === "POST" && c.path !== "/api/range").length;
  const anyPostBefore = sends();
  const tooHigh = Math.min(100, Math.round(rule * 100) + 5); // above the max field, still <= 100 %
  expect(Math.abs(Number(await page.getByTestId("cap-max-VTI").inputValue()) - rule * 100), "cap-max-VTI starts at the rule value").toBeLessThanOrEqual(1e-6);
  await page.getByTestId("cap-min-VTI").fill(String(tooHigh));
  await page.keyboard.press("Tab");
  await expect.poll(() => capErrorText(page), { message: "inline error beside the VTI cap fields" }).not.toBe(quiet);
  expect(await capErrorText(page), "inline error text").not.toBe("");
  // absence of a request needs a bounded wait: longer than the 250 ms URL debounce and any send debounce
  await page.waitForTimeout(1500);
  expect(mock.tensorPosts().length, "POST /api/tensors sent on invalid input").toBe(before);
  expect(sends(), "no POST of any kind (other than the range of the mix on screen) on invalid input").toBe(anyPostBefore);
});

test("valid cap sends one POST with VTI max 0.10", async ({ page }) => {
  const tensor = readFixtureTensor();
  ruleMax(tensor);
  const mock = await installMock(page, tensor);
  await openSettings(page);
  const before = mock.tensorPosts().length;
  await editVtiMax(page, mock, before);
  await page.waitForTimeout(1000); // a second, late POST would show up here
  const posts = mock.tensorPosts();
  expect(posts.length, "exactly one POST for one valid edit").toBe(before + 1);
  checkPolicy(posts[posts.length - 1].body, tensor, { VTI: { min: null, max: 0.1 } });
  const others = posts[posts.length - 1].body.funds.filter((f: any) => f.id !== "VTI");
  expect(others.length).toBeGreaterThanOrEqual(tensor.universe.funds.length - 1);
  for (const fund of others) expect(orNull(fund.max), `non-null max for unedited ${fund.id}`).toBeNull();
  // the rebuild flow proceeds: the override is in the address and the chart is back
  await expect.poll(() => urlParam(page, "c"), { message: "URL key c carries the override (spec 8.1)" }).toBe("VTI::10");
  await expect(page.getByTestId("chart-canvas")).toBeVisible();
  await expect(page.getByTestId("building-notice")).toBeHidden();
  expect(Number(await page.getByTestId("cap-max-VTI").inputValue())).toBe(10);
});

test("caps reset restores the rule and sends an all-null policy", async ({ page }) => {
  const tensor = readFixtureTensor();
  const rule = ruleMax(tensor);
  const mock = await installMock(page, tensor);
  await openSettings(page);
  const before = mock.tensorPosts().length;
  await editVtiMax(page, mock, before);
  await page.getByTestId("caps-reset").click();
  await expect.poll(() => mock.tensorPosts().length, { message: "one POST after caps-reset" }).toBe(before + 2);
  await page.waitForTimeout(1000);
  const posts = mock.tensorPosts();
  expect(posts.length).toBe(before + 2);
  checkPolicy(posts[posts.length - 1].body, tensor, {});
  let fields = 0;
  for (const fund of tensor.universe.funds) {
    const max = Number(await page.getByTestId(`cap-max-${fund.id}`).inputValue());
    const min = Number(await page.getByTestId(`cap-min-${fund.id}`).inputValue());
    expect(Math.abs(max - rule * 100), `cap-max-${fund.id} after reset reads ${max}`).toBeLessThanOrEqual(1e-6);
    expect(min, `cap-min-${fund.id} after reset`).toBe(0);
    fields += 2;
  }
  expect(fields).toBe(2 * tensor.universe.funds.length);
  expect(Number(await page.getByTestId("cap-max-VTI").inputValue())).not.toBe(10);
  await ruleSentence(page, tensor);
  await expect.poll(() => urlParam(page, "c") ?? "", { message: "URL key c cleared after reset" }).toBe("");
});
"""
EXPECTED_TITLES = {
    "invalid cap shows an inline error and sends nothing",
    "valid cap sends one POST with VTI max 0.10",
    "caps reset restores the rule and sends an all-null policy",
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


def test_a_ps_53_playwright():
    statuses = _run_playwright("a_ps_53", SPEC_TS, PROJECTS)
    expected = {(project, title) for project in PROJECTS for title in EXPECTED_TITLES}
    assert set(statuses) == expected, f"Playwright ran a different set of tests: {sorted(statuses)}"
    not_passed = {key: status for key, status in statuses.items() if status != "passed"}
    assert not not_passed, (
        f"Playwright legs not passed (failed, skipped, timed out or retried): {not_passed}"
    )
