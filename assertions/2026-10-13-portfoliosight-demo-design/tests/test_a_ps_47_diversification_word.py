"""A-PS-47 — the diversification word is quiet, one of four, with thresholds as specified.

Phase 3, ui + unit (Playwright against `vite preview` and a vitest leg, both run from pytest;
standard library only).

UI legs (desktop, three themes, three risk positions each): `div-word` is exactly one of
Good/Average/Fair/Poor and is the word for q = ENB(frontier.w[r]) / enb_ref recomputed here from the
tensor (spec 4.6); computed font-size <= 14 px; computed colour equals the computed `--muted`,
which equals the spec 3.5 value; before details no visible text matches the ENB patterns, no
neighbour of the word carries a digit and `details-enb` is hidden; after `details-toggle` the
`details-enb` line matches "spreads risk over the equivalent of N independent bets; highest found on
this menu: M" with N and M equal to the recomputed values at the shown precision, N/M inside the
band of the shown word, and the technical name visible.
Unit leg: the seven boundary values and a seeded sweep of 600 values.

The Playwright spec mocks /api/* itself (page.route) from web/fixtures/guide2017_5y.json and
data/holdings/holdings_guide2017_step2.csv: GET /api/presets (guide2017 with its "$" allocation and
tsp with allocation null, a distinct hash and the same tensor re-labelled), GET /api/tensors/{G}/
{hash}/{lb}, GET /api/symbols, GET /api/health, POST /api/tensors (200 ready, body recorded),
POST /api/share (202), anything else 404. Views are addressed through the spec 8.1 URL keys; with
an integer `r` inside the slider domain and `d=0` the selected mix is exactly `frontier.w[r]`
(`d=1`: `grid.w_div[r]`), which is what the test recomputes from. The product must keep `r` and `d`
as given (it may leave the URL untouched or rewrite the same values).

Pinned interface (beyond the shared pins)
- `diversificationWord(q: number): "Good" | "Average" | "Fair" | "Poor"` exported from
  `web/src/math/portfolio.ts` (pure; importing the module needs no DOM).
- `div-word` holds the bare word as its whole text; `details-enb` is absent or hidden until
  `details-toggle` is clicked.
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
// A-PS-47, UI legs
// ---------------------------------------------------------------------------------------------
const WORDS = ["Good", "Average", "Fair", "Poor"];
const CUTS = [0.3, 0.5, 0.75];
const wordFor = (q: number) => (q >= 0.75 ? "Good" : q >= 0.5 ? "Average" : q >= 0.3 ? "Fair" : "Poor");
const BAND: Record<string, [number, number]> = {
  Good: [0.75, Infinity], Average: [0.5, 0.75], Fair: [0.3, 0.5], Poor: [-Infinity, 0.3],
};
// spec 3.5, row --muted
const MUTED: Record<string, string> = { "ks-dark": "#8a8784", light: "#6b6b6b", hud: "#5c7e8c" };
const halfUnit = (shown: string) => 0.5 * Math.pow(10, -((shown.split(".")[1] ?? "").length)) + 1e-9;

for (const theme of THEMES) {
  test(`div word ${theme}`, async ({ page }) => {
    const tensor = readFixtureTensor();
    await installMock(page, tensor);
    const positions = threeInts(tensor);
    let checked = 0;
    for (const r of positions) {
      await openApp(page, `u=guide2017&lb=5y&r=${r}&d=0&t=${theme}`);
      await expectPosition(page, r, 0);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const enb = enbOf(tensor, tensor.frontier.w[r]);
      const q = enb / tensor.enb_ref;

      // default view: the word, quiet, and no number
      const wordEl = page.getByTestId("div-word");
      const word = norm((await wordEl.textContent()) ?? "");
      expect(WORDS, `div-word text "${word}" at r=${r}`).toContain(word);
      if (CUTS.every((cut) => Math.abs(q - cut) > 1e-6)) {
        expect(word, `word for q=${q.toFixed(4)} at r=${r}`).toBe(wordFor(q));
      }
      const style = await wordEl.evaluate((el) => {
        const cs = getComputedStyle(el);
        const near: string[] = [];
        for (const sib of [el.previousElementSibling, el.nextElementSibling]) {
          if (!sib) continue;
          const holdsRange = sib.matches('[data-testid^="range-"]') || sib.querySelector('[data-testid^="range-"]') !== null;
          if (!holdsRange) near.push((sib as HTMLElement).innerText ?? "");
        }
        return { fontSize: parseFloat(cs.fontSize), color: cs.color, near };
      });
      expect(style.fontSize, "div-word computed font-size (px)").toBeGreaterThan(0);
      expect(style.fontSize, "div-word computed font-size (px)").toBeLessThanOrEqual(14.01);
      const muted = await tokenHex(page, "--muted");
      expect(muted, `computed --muted in ${theme}`).toBe(MUTED[theme]);
      expect(await cssColorToHex(page, style.color), "div-word colour equals --muted").toBe(muted);
      for (const text of style.near) expect(text, "no numeric score next to the word").not.toMatch(/\d/);
      await expect(page.getByTestId("details-enb")).toBeHidden();
      const plain = norm(await page.evaluate(() => document.body.innerText));
      expect(plain.length, "the page rendered text").toBeGreaterThan(100);
      expect(plain, "no ENB number before details").not.toMatch(/\d\.\d+ (independent )?bets|ENB/);
      expect(plain, "no ENB number before details").not.toMatch(/\d\.\d+ (independent )?bets/i);

      // details on: the template, the two numbers and the ratio band
      await page.getByTestId("details-toggle").click();
      const detail = page.getByTestId("details-enb");
      await expect(detail).toBeVisible();
      const line = norm((await detail.textContent()) ?? "");
      const m = line.match(/spreads risk over the equivalent of (\d+(?:\.\d+)?) independent bets; highest found on this menu: (\d+(?:\.\d+)?)/);
      expect(m, `details-enb text "${line}"`).not.toBeNull();
      const shownN = Number(m![1]);
      const shownM = Number(m![2]);
      expect(Math.abs(shownN - enb), `N=${m![1]} vs ENB ${enb} of frontier.w[${r}]`).toBeLessThanOrEqual(halfUnit(m![1]));
      expect(Math.abs(shownM - tensor.enb_ref), `M=${m![2]} vs enb_ref ${tensor.enb_ref}`).toBeLessThanOrEqual(halfUnit(m![2]));
      const wordNow = norm((await wordEl.textContent()) ?? "");
      expect(WORDS).toContain(wordNow);
      const lowRatio = (shownN - halfUnit(m![1])) / (shownM + halfUnit(m![2]));
      const highRatio = (shownN + halfUnit(m![1])) / (shownM - halfUnit(m![2]));
      const [bandLow, bandHigh] = BAND[wordNow];
      expect(highRatio >= bandLow && lowRatio < bandHigh, `ratio ${shownN}/${shownM} outside the band of "${wordNow}"`).toBe(true);
      const technical = norm(await page.evaluate(() => document.body.innerText)).toLowerCase();
      expect(technical).toContain("effective number of bets, minimum torsion");
      checked += 1;
    }
    expect(checked, "risk positions checked").toBe(positions.length);
    expect(checked).toBeGreaterThanOrEqual(1);
  });
}
"""
EXPECTED_TITLES = {"div word ks-dark", "div word light", "div word hud"}

# The vitest leg (pure function, no browser). Written to web/tests/__gate__/ for the run.
VITEST_TS = r"""
import { describe, expect, it } from "vitest";

const WORDS = ["Good", "Average", "Fair", "Poor"];
const reference = (q: number) => (q >= 0.75 ? "Good" : q >= 0.5 ? "Average" : q >= 0.3 ? "Fair" : "Poor");

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

describe("A-PS-47", () => {
  it("word thresholds at the seven boundary values", async () => {
    const mod: any = await import("../../src/math/portfolio");
    expect(typeof mod.diversificationWord, "web/src/math/portfolio.ts must export diversificationWord(q)").toBe("function");
    const cases: [number, string][] = [
      [0.299, "Poor"], [0.3, "Fair"], [0.499, "Fair"], [0.5, "Average"], [0.749, "Average"], [0.75, "Good"], [1.0, "Good"],
    ];
    for (const [q, word] of cases) expect(mod.diversificationWord(q), `q=${q}`).toBe(word);
    expect(mod.diversificationWord(0.299)).not.toBe("Fair");
    expect(mod.diversificationWord(0.749)).not.toBe("Good");
  });

  it("word mapping over a seeded sweep stays inside the four words", async () => {
    const mod: any = await import("../../src/math/portfolio");
    expect(typeof mod.diversificationWord).toBe("function");
    const random = mulberry32(47);
    const seen: Record<string, number> = { Good: 0, Average: 0, Fair: 0, Poor: 0 };
    for (let i = 0; i < 600; i++) {
      const q = random() * 1.1;
      const word = mod.diversificationWord(q);
      expect(WORDS, `q=${q}`).toContain(word);
      expect(word, `q=${q}`).toBe(reference(q));
      seen[word] += 1;
    }
    for (const word of WORDS) expect(seen[word], `sweep reached ${word}`).toBeGreaterThanOrEqual(50);
    expect(mod.diversificationWord(0)).toBe("Poor");
  });
});
"""
VITEST_TITLES = {
    "word thresholds at the seven boundary values",
    "word mapping over a seeded sweep stays inside the four words",
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


def test_a_ps_47_vitest():
    statuses = _run_vitest("a_ps_47", VITEST_TS)
    assert set(statuses) == VITEST_TITLES, (
        f"vitest ran a different set of tests: {sorted(statuses)}"
    )
    not_passed = {title: status for title, status in statuses.items() if status != "passed"}
    assert not not_passed, f"vitest legs not passed (failed, skipped or todo): {not_passed}"


def test_a_ps_47_playwright():
    statuses = _run_playwright("a_ps_47", SPEC_TS, PROJECTS)
    expected = {(project, title) for project in PROJECTS for title in EXPECTED_TITLES}
    assert set(statuses) == expected, f"Playwright ran a different set of tests: {sorted(statuses)}"
    not_passed = {key: status for key, status in statuses.items() if status != "passed"}
    assert not not_passed, (
        f"Playwright legs not passed (failed, skipped, timed out or retried): {not_passed}"
    )
