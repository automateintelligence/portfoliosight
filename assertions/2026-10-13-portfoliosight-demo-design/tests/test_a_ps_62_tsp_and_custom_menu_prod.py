# ruff: noqa: E501
"""A-PS-62 — TSP loads in one click and a custom menu builds end to end in production.

Claim: selecting "TSP (G, F, C, S, I)" in `preset-menu` loads a five-fund tensor whose Settings
show max 60% per fund, with no `point-current` and no `section-trades`; typing "L 2050" in
`fund-add` offers `TSP-L2050`; with an idle queue, a custom menu of four served symbols and
`use-menu` shows `building-notice` (unless the key is cached) and the chart updates within 120 s
with `universe.funds` equal to the four; an unknown ticker shows an inline error naming it; a
31st fund is refused with a message.

Playwright (desktop project) against https://portfoliosight.ai with the `x-ps-gate` header set
inside the embedded spec from `PS_GATE_SECRET`. A missing variable is a failure naming it.

Pinned interface (the product must provide exactly this), beyond the spec 10 test ids:
- `preset-menu` is a native <select> (or wraps one), or a control that, once clicked, shows the
  entries as ARIA options / menu items / buttons / text; entry labels "TSP (G, F, C, S, I)" and
  one starting with "Custom" (spec 3.2); choosing "Custom..." shows `fund-add`;
- chips `chip-funds` / `chip-settings` expand their sections (spec 3.3);
- `cap-max-{ID}` is (or wraps) an input whose value is the percentage as a number (60);
- `fund-add` is (or wraps) a text input; candidates are ARIA `role="option"` elements or native
  <option>s that carry the fund id as text or as `value` / `data-value` / `data-id`; a fund is
  added by clicking its option or pressing Enter and then shows as `fund-row-{ID}`;
- each `fund-row-{ID}` holds a button whose accessible name contains "Remove";
- an unknown ticker is NOT added as a row; its inline error text lives inside `section-funds`;
- the 31st-fund message lives inside `section-funds` (or `use-menu` is disabled);
- `chart-canvas` is (or holds) a 2D <canvas>;
- `/api/symbols`, `/api/health`, `/api/presets`, `POST /api/tensors` and the tensor per spec 6/7.
The universe hash is recomputed here with Node's crypto (spec 6): sha256 of the canonical JSON
(sorted keys, no whitespace, null defaults), first 16 hex digits.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
SITE = "https://portfoliosight.ai"
PROJECTS = ("desktop",)
SECRET_NAMES = ("PS_GATE_SECRET", "CLOUDFLARE_API_TOKEN", "PS_SHARE_TEST_RECIPIENT")

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

SPEC_TS = r"""
import { expect, test, type Locator, type Page } from "@playwright/test";
import { createHash } from "node:crypto";

test.use({ extraHTTPHeaders: { "x-ps-gate": process.env.PS_GATE_SECRET ?? "" } });

type Fund = { id: string; min?: number | null; max?: number | null };

// Canonical JSON (spec 6, A-PS-29): keys sorted, no whitespace, null for defaults.
function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  const obj = value as Record<string, unknown>;
  return "{" + Object.keys(obj).sort().map((key) => JSON.stringify(key) + ":" + canonical(obj[key])).join(",") + "}";
}

// The test's own universe hash: sha256(canonical_json({"schema":2,"funds":[{"id","min","max"} sorted by id]}))[:16].
function universeHash(funds: Fund[]): string {
  const sorted = funds
    .map((fund) => ({ id: fund.id, min: fund.min ?? null, max: fund.max ?? null }))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  return createHash("sha256").update(canonical({ schema: 2, funds: sorted }), "utf8").digest("hex").slice(0, 16);
}

function same(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

// 50 fixed samples of the chart canvas: a position-sensitive checksum of a one-pixel-wide,
// full-height column at 50 fixed x positions (a thin frontier curve crosses every column but would
// miss 50 single pixels; a checksum, unlike a sum, also sees a curve that only moves up or down).
async function sampleCanvas(page: Page): Promise<number[]> {
  return page.getByTestId("chart-canvas").evaluate((el) => {
    const canvas = el instanceof HTMLCanvasElement ? el : el.querySelector("canvas");
    if (!canvas) throw new Error("chart-canvas is not (and holds no) <canvas> element");
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("chart-canvas has no 2D context");
    const out: number[] = [];
    for (let i = 0; i < 50; i++) {
      const x = Math.min(canvas.width - 1, Math.floor(((i + 0.5) / 50) * canvas.width));
      const data = ctx.getImageData(x, 0, 1, canvas.height).data;
      let sum = 0;
      for (let p = 0; p < data.length; p++) sum = (sum * 31 + data[p]) % 2147483647;
      out.push(sum);
    }
    return out;
  });
}

// A drawing that is non-blank and identical in two samples 250 ms apart.
async function settledSample(page: Page): Promise<number[]> {
  let previous = await sampleCanvas(page);
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(250);
    const next = await sampleCanvas(page);
    if (same(previous, next) && next.some((value) => value !== 0)) return next;
    previous = next;
  }
  throw new Error("chart-canvas never settled to a non-blank drawing within 15 s");
}

type Post = { path: string; body: any; at: number; status: number | null };
type TensorGet = { path: string; status: number; at: number; body: any };

// Record every POST to /api/* and every GET of a tensor URL (with the 200 bodies).
function watchApi(page: Page) {
  const posts: Post[] = [];
  const tensors: TensorGet[] = [];
  const gets: string[] = [];
  const pending = new Map<unknown, Post>();
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) return;
    if (request.method() === "GET") gets.push(url.pathname);
    if (request.method() !== "POST") return;
    let body: any = null;
    try { body = request.postDataJSON(); } catch { body = null; }
    const entry: Post = { path: url.pathname, body, at: Date.now(), status: null };
    posts.push(entry);
    pending.set(request, entry);
  });
  page.on("response", async (response) => {
    const request = response.request();
    const url = new URL(response.url());
    const post = pending.get(request);
    if (post) post.status = response.status();
    if (request.method() !== "GET" || !/^\/api\/tensors\/[^/]+\/[^/]+\/[^/]+$/.test(url.pathname)) return;
    const entry: TensorGet = { path: url.pathname, status: response.status(), at: Date.now(), body: null };
    tensors.push(entry);
    if (response.status() === 200) {
      try { entry.body = await response.json(); } catch { entry.body = null; }
    }
  });
  return { posts, tensors, gets };
}

async function inputOf(locator: Locator): Promise<Locator> {
  const tag = await locator.evaluate((el) => el.tagName);
  return tag === "INPUT" || tag === "TEXTAREA" ? locator : locator.locator("input").first();
}

async function readNumber(locator: Locator): Promise<number> {
  const raw = await locator.evaluate((el) =>
    el instanceof HTMLInputElement || el instanceof HTMLSelectElement
      ? el.value
      : (el.querySelector("input")?.value ?? el.textContent ?? ""),
  );
  return Number.parseFloat(raw);
}

// Open a collapsed section through its first-screen chip (spec 3.3) and wait for one control in it.
async function openSection(page: Page, name: string, control: string): Promise<void> {
  const inner = page.getByTestId(control).first();
  if (!(await inner.isVisible())) await page.getByTestId("chip-" + name).click();
  await expect(inner).toBeVisible({ timeout: 10_000 });
}

async function loadDefault(page: Page): Promise<void> {
  const response = await page.goto("/");
  expect(response?.status(), "GET / with the gate header").toBe(200);
  await expect(page.getByTestId("chart-canvas")).toBeVisible({ timeout: 15_000 });
}

async function apiJson(page: Page, path: string): Promise<any> {
  const response = await page.request.get(path);
  expect(response.status(), `GET ${path} with the gate header`).toBe(200);
  return response.json();
}
// Choose an entry of the preset menu: a native <select>, or a button that opens a list.
async function choosePreset(page: Page, label: RegExp): Promise<void> {
  const menu = page.getByTestId("preset-menu");
  await expect(menu).toBeVisible();
  const isSelect = (await menu.evaluate((el) => el.tagName)) === "SELECT";
  const select = isSelect ? menu : menu.locator("select").first();
  if (isSelect || (await select.count()) > 0) {
    const find = () =>
      select.evaluate((el, source) => {
        const pattern = new RegExp(source);
        const option = Array.from((el as HTMLSelectElement).options).find((item) => pattern.test(item.label.trim()));
        return option ? option.value : null;
      }, label.source);
    // The menu is filled from /api/presets, so the entry may arrive a moment after the chart.
    await expect.poll(find, { timeout: 10_000, message: `preset-menu offers an option matching ${label}` }).not.toBeNull();
    const value = (await find()) as string;
    await select.selectOption(value);
    return;
  }
  const choice = page
    .getByRole("option", { name: label })
    .or(page.getByRole("menuitem", { name: label }))
    .or(page.getByRole("menuitemradio", { name: label }))
    .or(page.getByRole("button", { name: label }))
    .or(page.getByText(label))
    .first();
  if (!(await choice.isVisible())) await menu.click();
  await choice.click();
}

function idPattern(id: string): RegExp {
  return new RegExp("(^|[^A-Z0-9-])" + id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "($|[^A-Z0-9-])");
}

// How many offered options (ARIA options or native <option>s) carry this fund id.
async function offered(page: Page, id: string): Promise<number> {
  return page.evaluate((want) => {
    const nodes = Array.from(document.querySelectorAll('[role="option"], option'));
    return nodes.filter(
      (node) =>
        node.getAttribute("value") === want ||
        node.getAttribute("data-value") === want ||
        node.getAttribute("data-id") === want ||
        (node.textContent ?? "").includes(want),
    ).length;
  }, id);
}

// Type an id into fund-add and commit it: click the matching option if one shows, else press Enter.
async function typeFund(page: Page, id: string): Promise<void> {
  const input = await inputOf(page.getByTestId("fund-add"));
  await input.fill(id);
  const option = page.locator('[role="option"]').filter({ hasText: idPattern(id) }).first();
  try {
    await option.click({ timeout: 2_500 });
  } catch {
    await input.press("Enter");
  }
}

async function addFund(page: Page, id: string): Promise<void> {
  await typeFund(page, id);
  await expect(page.getByTestId("fund-row-" + id), `fund row for ${id} after adding it`).toBeVisible({ timeout: 5_000 });
}

async function rowIds(page: Page): Promise<string[]> {
  return page
    .locator('[data-testid^="fund-row-"]')
    .evaluateAll((rows) => rows.map((row) => (row.getAttribute("data-testid") ?? "").slice("fund-row-".length)));
}

// Open "Custom…" (spec 3.2: it opens the Funds section) and return the ids listed there.
async function openCustom(page: Page): Promise<string[]> {
  await choosePreset(page, /^Custom/);
  await expect(page.getByTestId("fund-add")).toBeVisible({ timeout: 10_000 });
  return rowIds(page);
}

// Make the Funds table hold exactly `ids`: remove the others (each row's "Remove" button), add the missing.
async function setMenu(page: Page, ids: string[]): Promise<void> {
  const present = await openCustom(page);
  for (const id of present) {
    if (ids.includes(id)) continue;
    await page.getByTestId("fund-row-" + id).getByRole("button", { name: /remove/i }).click();
    await expect(page.getByTestId("fund-row-" + id)).toHaveCount(0);
  }
  for (const id of ids) {
    if (!present.includes(id)) await addFund(page, id);
  }
  expect((await rowIds(page)).sort().join(",")).toBe([...ids].sort().join(","));
}

const TSP_IDS = ["TSP-C", "TSP-F", "TSP-G", "TSP-I", "TSP-S"];
const PREFERRED = ["VOO", "BND", "VNQ", "SGOV"];

function tensorPosts(api: { posts: Post[] }): Post[] {
  return api.posts.filter((post) => post.path === "/api/tensors");
}

test("TSP preset loads in one click", async ({ page }) => {
  const api = watchApi(page);
  await loadDefault(page);
  await settledSample(page);
  const before = api.tensors.length;

  await choosePreset(page, /^TSP \(G, F, C, S, I\)$/);
  await expect
    .poll(() => api.tensors.slice(before).some((entry) => entry.status === 200 && entry.body !== null), { timeout: 30_000 })
    .toBe(true);
  await expect.poll(() => new URL(page.url()).searchParams.get("u"), { timeout: 5_000 }).toBe("tsp");
  await page.waitForTimeout(1_500);

  const loaded = api.tensors.slice(before).filter((entry) => entry.status === 200);
  expect(loaded.length, "tensor GETs after the one TSP click").toBe(1);
  const funds: string[] = loaded[0].body.universe.funds.map((fund: { id: string }) => fund.id);
  expect([...funds].sort()).toEqual(TSP_IDS);

  await openSection(page, "settings", "cap-max-TSP-G");
  let caps = 0;
  for (const id of TSP_IDS) {
    expect(await readNumber(page.getByTestId("cap-max-" + id)), `cap-max-${id}`).toBe(60);
    caps += 1;
  }
  expect(caps).toBe(5);

  // Must-not-contain: a current-mix marker or a trades section for the TSP preset.
  await expect(page.getByTestId("point-current")).toHaveCount(0);
  await expect(page.getByTestId("section-trades")).toHaveCount(0);
  expect(tensorPosts(api).length, "POSTs for a preset").toBe(0);

  await openSection(page, "funds", "fund-add");
  const input = await inputOf(page.getByTestId("fund-add"));
  await input.fill("L 2050");
  await expect.poll(() => offered(page, "TSP-L2050"), { timeout: 5_000 }).toBeGreaterThan(0);
  expect(await page.getByTestId("fund-row-TSP-L2050").count()).toBe(0);
});

test("custom menu of four served symbols builds end to end", async ({ page }) => {
  test.setTimeout(420_000);
  await expect
    .poll(async () => (await apiJson(page, "/api/health")).queue.depth, { timeout: 120_000, intervals: [3_000] })
    .toBe(0);
  const symbols: { id: string; first_date: string }[] = (await apiJson(page, "/api/symbols")).symbols;
  const catalog = symbols.map((symbol) => symbol.id);
  expect(catalog.length).toBeGreaterThanOrEqual(4);
  let four = PREFERRED;
  if (!PREFERRED.every((id) => catalog.includes(id))) {
    // Otherwise the first four served symbols (those with at least six years of history, so the
    // 5y window cannot exclude one of them; the plain first four if there are not enough).
    const cutoff = new Date(Date.now() - 6 * 366 * 86_400_000).toISOString().slice(0, 10);
    const seasoned = symbols.filter((symbol) => String(symbol.first_date).slice(0, 10) <= cutoff).map((symbol) => symbol.id);
    four = (seasoned.length >= 4 ? seasoned : catalog).slice(0, 4);
  }
  const wanted = [...four].sort();
  const hash = universeHash(four.map((id) => ({ id, min: null, max: null })));
  console.log(`A-PS-62 custom menu: ${wanted.join(",")} hash ${hash}`);

  const api = watchApi(page);
  await loadDefault(page);
  const drawnBefore = await settledSample(page);
  await setMenu(page, four);
  expect(tensorPosts(api).length, "POSTs before use-menu").toBe(0);

  const notice = page.getByTestId("building-notice");
  const mine = () => api.tensors.filter((entry) => entry.path.includes("/" + hash + "/"));
  const started = Date.now();
  await page.getByTestId("use-menu").click();
  let sawNotice = false;
  let cachedFast = false;
  while (Date.now() - started < 120_000) {
    if (await notice.isVisible()) { sawNotice = true; break; }
    const done = mine().find((entry) => entry.status === 200);
    if (done) { cachedFast = done.at - started <= 2_000 && mine()[0] === done; break; }
    await page.waitForTimeout(50);
  }
  console.log(`A-PS-62 custom build: ${sawNotice ? "building-notice shown" : cachedFast ? "cached key, 200 within 2 s" : "neither"}`);
  expect(sawNotice || cachedFast, "building-notice visible, or a cached key answered 200 within 2 s").toBe(true);

  // Must-not-contain: a build that never resolves (120 s cap from the click).
  const left = () => Math.max(1_000, 120_000 - (Date.now() - started));
  await expect
    .poll(() => mine().some((entry) => entry.status === 200 && entry.body !== null), { timeout: left() })
    .toBe(true);
  await expect.poll(async () => !same(await sampleCanvas(page), drawnBefore), { timeout: left() }).toBe(true);
  await expect(notice).toBeHidden({ timeout: left() });

  const tensor = mine().find((entry) => entry.status === 200 && entry.body !== null)!.body;
  const loadedIds: string[] = tensor.universe.funds.map((fund: { id: string }) => fund.id);
  expect([...loadedIds].sort()).toEqual(wanted);
  expect(tensor.universe.hash).toBe(hash);
  expect(tensor.universe.hash).not.toBe(universeHash(four.slice(0, 3).map((id) => ({ id }))));
  const posts = tensorPosts(api);
  expect(posts.length).toBeGreaterThanOrEqual(1);
  for (const post of posts) {
    expect(post.body.funds.map((fund: Fund) => fund.id).sort()).toEqual(wanted);
    expect(universeHash(post.body.funds)).toBe(hash);
  }
});

test("unknown ticker is refused inline without a POST", async ({ page }) => {
  const catalog: string[] = (await apiJson(page, "/api/symbols")).symbols.map((symbol: { id: string }) => symbol.id);
  expect(catalog.includes("ZZZZ"), "ZZZZ must not be a served symbol").toBe(false);
  const api = watchApi(page);
  await loadDefault(page);
  const rowsBefore = (await openCustom(page)).length;
  const section = page.getByTestId("section-funds");
  expect(await section.innerText()).not.toContain("ZZZZ");

  await typeFund(page, "ZZZZ");
  await expect(section).toContainText("ZZZZ", { timeout: 5_000 });
  await page.waitForTimeout(2_000);
  // Must-not-contain: the unknown ticker in the menu, or a POST for it.
  await expect(page.getByTestId("fund-row-ZZZZ")).toHaveCount(0);
  expect((await rowIds(page)).length).toBe(rowsBefore);
  expect(tensorPosts(api).length, "POST /api/tensors for an unknown ticker").toBe(0);
});

test("a 31st fund is refused with a message and no POST", async ({ page }) => {
  test.setTimeout(300_000);
  const symbols: { id: string; name: string }[] = (await apiJson(page, "/api/symbols")).symbols;
  const plain = symbols.filter((symbol) => !/\b30\b/.test(symbol.id + " " + symbol.name)).map((symbol) => symbol.id);
  const api = watchApi(page);
  await loadDefault(page);
  const present = await openCustom(page);
  const spare = plain.filter((id) => !present.includes(id));
  expect(present.length + spare.length, "served symbols available for a 31-fund menu").toBeGreaterThanOrEqual(31);
  let next = 0;
  while ((await rowIds(page)).length < 30) {
    await addFund(page, spare[next]);
    next += 1;
  }
  expect((await rowIds(page)).length).toBe(30);

  await typeFund(page, spare[next]);
  await page.waitForTimeout(1_500);
  const rows = (await rowIds(page)).length;
  const disabled = await page.getByTestId("use-menu").isDisabled();
  const says30 = /\b30\b/.test(await page.getByTestId("section-funds").innerText());
  console.log(`A-PS-62 31st fund: rows=${rows} use-menu disabled=${disabled} message with 30=${says30}`);
  expect(rows <= 30 || disabled, "the 31st fund is not accepted into a usable menu").toBe(true);
  expect(disabled || says30, 'use-menu disabled, or a message containing "30"').toBe(true);
  expect(rows).not.toBeGreaterThan(31);
  expect(tensorPosts(api).length, "POST /api/tensors for a 31-fund menu").toBe(0);
});
"""
EXPECTED_TITLES = {
    "TSP preset loads in one click",
    "custom menu of four served symbols builds end to end",
    "unknown ticker is refused inline without a POST",
    "a 31st fund is refused with a message and no POST",
}


def _scrub(text: str) -> str:
    """Replace every secret value by its variable name before anything is printed or asserted."""
    for name in SECRET_NAMES:
        value = os.environ.get(name, "").strip()
        if len(value) >= 4:
            text = text.replace(value, f"<{name}>")
    return text


def _env(name: str, blocked: bool = False) -> str:
    """A required environment variable; its absence is a failure that names the variable."""
    value = os.environ.get(name, "").strip()
    if not value:
        prefix = "BLOCKED: " if blocked else ""
        pytest.fail(
            f"{prefix}{name} is not set (the caller loads ~/.secrets/portfoliosight.env)",
            pytrace=False,
        )
    return value


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


def _playwright(
    name: str,
    spec_ts: str,
    titles: set[str],
    extra_env: dict[str, str] | None = None,
    timeout: int = 900,
) -> str:
    """Run the embedded spec against production; scrub secrets from everything that is shown.

    Returns the scrubbed Playwright error output. Fails unless exactly `titles` ran and passed.
    """
    captured = io.StringIO()
    statuses: dict[tuple[str, str], str] = {}
    problem = ""
    try:
        with contextlib.redirect_stdout(captured):
            statuses = _run_playwright(
                name, spec_ts, PROJECTS, base_url=SITE, extra_env=extra_env, timeout=timeout
            )
    except AssertionError as err:
        problem = str(err) or "the Playwright wrapper failed"
    except subprocess.TimeoutExpired:
        problem = f"Playwright did not finish within {timeout} s"
    except OSError as err:
        problem = f"Playwright could not be started: {type(err).__name__}: {err}"
    output = _scrub(captured.getvalue())
    print(output)
    if problem:
        pytest.fail(_scrub(problem), pytrace=False)
    blocked = re.search(r"BLOCKED: [^\n]*", output)
    if blocked:
        pytest.fail(blocked.group(0)[:300], pytrace=False)
    expected = {(project, title) for project in PROJECTS for title in titles}
    assert set(statuses) == expected, f"Playwright ran a different set of tests: {sorted(statuses)}"
    not_passed = {key: status for key, status in statuses.items() if status != "passed"}
    assert not not_passed, (
        f"Playwright legs not passed (failed, skipped, timed out or retried): {not_passed}"
    )
    return output


def test_a_ps_62_playwright():
    secret = _env("PS_GATE_SECRET")
    output = _playwright("a_ps_62", SPEC_TS, EXPECTED_TITLES, timeout=1500)
    leaked = secret in output
    assert not leaked, "the gate secret reached the test output"
