# ruff: noqa: E501
"""A-PS-63 — lookbacks, ghosts and cap rebuilds work in production.

Claim: on the default preset, choosing `lookback-10y` loads the 10y tensor and redraws the
frontier, the Settings exclusion list equals the set the test computes from `/api/symbols`
`first_date` values and the spec 4.2 rule for that window, the same holds for a custom menu that
holds a served fund too young for the 10y view (which is listed with its reason) and FIENX, a
catalog fund that is not served (which is listed too), toggling `ghost-1y` increments
`data-ghost-count` on `chart` by one and changes sampled canvas pixels, toggling it off restores
both, and editing `cap-max-VTI` to 10 triggers a rebuild whose tensor has every
`frontier.w[j][VTI] <= 0.10 + 1e-6`.

Playwright (desktop project) against https://portfoliosight.ai with the `x-ps-gate` header set
inside the embedded spec from `PS_GATE_SECRET`. A missing variable is a failure naming it.

The 10y window bounds are exact XNYS sessions, computed on the pytest side with
`exchange_calendars` (hence the project-virtualenv re-run) from the `asof` of `/api/presets`:
`start_10y` = the session 2,520 sessions before `asof`; a served fund is excluded iff its
`first_date` is later than the session 252 sessions after `start_10y`; a preset fund that
`/api/symbols` does not list (not served) is excluded too (spec 4.2: only served funds count).

Owner decision 2026-10-13: EFA holds FIENX's place in the default menu, so the default menu may
have no excluded fund in the 10y view and the computed set above may be empty. The exclusion list
is therefore also checked on a custom menu that provably has both kinds of exclusion: two funds
of the default menu whose history starts before the window (the first two of BND, VTI, AGG, VNQ
that qualify), one served fund whose `first_date` is after the threshold (SGOV when it qualifies,
else the first such id in alphabetical order), and FIENX, which the catalog knows and does not
serve (the not-served case the default menu used to supply). The menu is the same on every run,
so it costs one real build per generation.

Pinned interface (the product must provide exactly this), beyond the spec 10 test ids:
- `/api/presets`: the default preset has id `guide2017`, with `funds[].id` and
  `lookbacks[...].url`; `asof` is the generation date; `/api/symbols` rows carry `first_date`;
- `chip-settings` expands Settings; `lookback-10y`, `ghost-1y` are clickable; `cap-max-VTI` is
  (or wraps) an input taking the percentage; an edit is committed by Enter / leaving the field
  and triggers the rebuild by itself (one `POST /api/tensors`);
- inside `section-settings`, the `excluded-note` element(s) name each excluded fund by its id;
  a short-history fund reads "{ID}: history starts YYYY-MM-DD, not enough for the ... view"
  (spec 3.6 / 5.6);
- `chart` carries `data-ghost-count`; `chart-canvas` is (or holds) a 2D <canvas>;
- the address carries `lb=10y` (spec 8.1); the tensor per spec 7 (`universe.excluded`,
  `bounds.requested`, `frontier.w`, `grid.w`);
- opening `/?f=ID,ID,ID,FIENX&lb=10y` (spec 8.1) loads that custom menu in the 10y view by
  itself: the page requests the build (every fund of the menu is sent; FIENX is a catalog symbol,
  so the service accepts the menu and sets it aside) and then GETs `/api/tensors/{G}/{hash}/10y`,
  `hash` being the universe hash of the four funds with default caps (spec 6); the tensor is
  loaded within 150 s.
"""

from __future__ import annotations

import contextlib
import http.client
import importlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
PROJECTS = ("desktop",)


def _project_python() -> Path | None:
    """The project's virtualenv interpreter: this checkout's, else the main checkout's (worktree)."""
    roots = [ROOT]
    dot_git = ROOT / ".git"
    if dot_git.is_file():  # linked worktree: "gitdir: <main>/.git/worktrees/<name>"
        roots.append(Path(dot_git.read_text().split(":", 1)[1].strip()).parents[2])
    for root in roots:
        candidate = root / ".venv" / "bin" / "python"
        if candidate.exists():
            return candidate
    return None


_VENV_PY = _project_python()
_OUTER = (
    os.environ.get("PS_GATE_INNER") != "1"
    and _VENV_PY is not None
    and Path(sys.prefix).resolve() != _VENV_PY.parents[1].resolve()
)


def _need(module: str):
    """Import a product (or dev-dependency) module, failing the test cleanly when it is absent."""
    try:
        return importlib.import_module(module)
    except Exception as exc:  # ImportError, or an import-time crash in the product
        pytest.fail(f"A-PS-63 red: cannot import {module}: {type(exc).__name__}: {exc}")


SITE = "https://portfoliosight.ai"
API = "https://api.portfoliosight.ai"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
MAX_BODY = 8 * 1024 * 1024
SECRET_NAMES = (
    "PS_GATE_SECRET",
    "CLOUDFLARE_API_TOKEN",
    "PS_SHARE_TEST_RECIPIENT",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "TIINGO_API_KEY",
)


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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102, PLR0913
        return None


@dataclass
class _Resp:
    status: int  # 0 = no HTTP response at all (DNS, connect, TLS, timeout)
    headers: dict[str, str]
    body: bytes
    error: str = ""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


def _http(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 20.0,
) -> _Resp:
    """One request through a fresh opener: no cookie jar, no redirect following, explicit timeout."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        url, data=body, method=method, headers={"User-Agent": UA, **(headers or {})}
    )
    try:
        with opener.open(request, timeout=timeout) as resp:
            found = {key.lower(): value for key, value in resp.headers.items()}
            return _Resp(resp.status, found, resp.read(MAX_BODY))
    except urllib.error.HTTPError as err:
        with err:
            found = {key.lower(): value for key, value in err.headers.items()}
            return _Resp(err.code, found, err.read(MAX_BODY))
    except (urllib.error.URLError, OSError, http.client.HTTPException) as err:
        reason = getattr(err, "reason", err)
        return _Resp(0, {}, b"", _scrub(f"{type(err).__name__}: {reason}"))


def _reached(resp: _Resp, what: str) -> _Resp:
    """Fail cleanly when a request produced no HTTP response (today: nothing is deployed)."""
    if resp.status == 0:
        pytest.fail(
            f"{what}: no HTTP response ({resp.error}); the site is not deployed or not reachable",
            pytrace=False,
        )
    return resp


def _json_or_none(text: str):
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, (dict, list)) else None


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

const ASOF = process.env.PS_GATE_ASOF ?? "";
const START_10Y = process.env.PS_GATE_START_10Y ?? "";
const THRESHOLD_10Y = process.env.PS_GATE_THRESHOLD_10Y ?? "";
const CAP = 0.10;

async function defaultPreset(page: Page) {
  const presets = await apiJson(page, "/api/presets");
  expect(presets.asof, "generation asof (changed while the test ran?)").toBe(ASOF);
  const preset = presets.presets.find((item: { id: string }) => item.id === "guide2017");
  expect(preset, "the default preset guide2017").toBeTruthy();
  return preset as { funds: { id: string }[]; lookbacks: Record<string, { url: string }> };
}

test("10y lookback redraws the frontier and lists the computed exclusions", async ({ page }) => {
  test.setTimeout(300_000);
  expect(/^\d{4}-\d{2}-\d{2}$/.test(THRESHOLD_10Y)).toBe(true);
  expect(/^\d{4}-\d{2}-\d{2}$/.test(START_10Y) && START_10Y < THRESHOLD_10Y).toBe(true);
  const preset = await defaultPreset(page);
  const fundIds = preset.funds.map((fund) => fund.id);
  const url10 = preset.lookbacks["10y"].url;
  expect((await apiJson(page, preset.lookbacks["5y"].url)).asof).toBe(ASOF);
  const symbols: { id: string; first_date: string }[] = (await apiJson(page, "/api/symbols")).symbols;
  const firstDate = new Map(symbols.map((symbol) => [symbol.id, String(symbol.first_date).slice(0, 10)]));
  // Spec 4.2 for the 10y window: not served, or history starting after start_10y + 252 sessions.
  const notServed = fundIds.filter((id) => !firstDate.has(id));
  const shortHistory = fundIds.filter((id) => firstDate.has(id) && firstDate.get(id)! > THRESHOLD_10Y);
  const expected = [...notServed, ...shortHistory].sort();
  console.log(`A-PS-63 10y: threshold ${THRESHOLD_10Y}; expected exclusions [${expected.join(",")}] of ${fundIds.length} funds`);
  expect(fundIds.length).toBeGreaterThanOrEqual(2);

  const api = watchApi(page);
  await loadDefault(page);
  const drawn5y = await settledSample(page);
  await openSection(page, "settings", "lookback-10y");
  expect(api.gets.filter((path) => path === url10).length, "10y GETs before the click").toBe(0);

  await page.getByTestId("lookback-10y").click();
  await expect
    .poll(() => api.tensors.some((entry) => entry.path === url10 && entry.status === 200 && entry.body !== null), { timeout: 30_000 })
    .toBe(true);
  await expect.poll(() => new URL(page.url()).searchParams.get("lb"), { timeout: 5_000 }).toBe("10y");
  await expect.poll(async () => !same(await sampleCanvas(page), drawn5y), { timeout: 15_000 }).toBe(true);
  await page.waitForTimeout(1_500);
  expect(api.gets.filter((path) => path === url10).length, "GETs of the preset's 10y URL").toBe(1);

  const tensor = api.tensors.find((entry) => entry.path === url10 && entry.status === 200)!.body;
  expect(tensor.lookback.id).toBe("10y");
  expect(tensor.universe.excluded.map((item: { id: string }) => item.id).sort()).toEqual(expected);
  const included: string[] = tensor.universe.funds.map((fund: { id: string }) => fund.id);
  let checked = 0;
  for (const id of included) {
    expect(firstDate.has(id), `${id} is in the 10y tensor but not served`).toBe(true);
    expect(firstDate.get(id)! > THRESHOLD_10Y, `${id} starts after the 10y threshold but was included`).toBe(false);
    checked += 1;
  }
  expect(checked + expected.length).toBe(fundIds.length);

  const notes = page.getByTestId("section-settings").getByTestId("excluded-note");
  const listed = async () => {
    const text = (await notes.allInnerTexts()).join("\n");
    return fundIds.filter((id) => new RegExp("(^|[^A-Z0-9-])" + id + "($|[^A-Z0-9-])").test(text)).sort().join(",");
  };
  // Must-not-contain: an exclusion list that differs from the computed set.
  await expect.poll(listed, { timeout: 10_000 }).toBe(expected.join(","));
  const text = (await notes.allInnerTexts()).join("\n");
  for (const id of shortHistory) {
    const template = new RegExp(id + "\\b[^\\n]*history starts \\d{4}-\\d{2}-\\d{2}, not enough for the [^\\n]+ view");
    expect(template.test(text), `excluded-note for ${id} follows the spec 5.6 template`).toBe(true);
  }

  // The default menu may have no excluded fund (owner decision 2026-10-13: EFA holds FIENX's
  // place), which would leave the list above empty. The same rule on a menu that provably has
  // both kinds of exclusion: two funds of the default menu older than the window, one served
  // fund whose history starts after the threshold, and FIENX, which is not served.
  const served = symbols.map((symbol) => ({ id: symbol.id, first: String(symbol.first_date).slice(0, 10) }));
  const tooYoung = served
    .filter((symbol) => /^\d{4}-\d{2}-\d{2}$/.test(symbol.first) && symbol.first > THRESHOLD_10Y && !fundIds.includes(symbol.id))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const young = tooYoung.find((symbol) => symbol.id === "SGOV") ?? tooYoung[0];
  expect(young, `a served fund whose history starts after ${THRESHOLD_10Y}, to exercise the exclusion list`).toBeTruthy();
  const old = ["BND", "VTI", "AGG", "VNQ"].filter((id) => included.includes(id) && firstDate.get(id)! <= START_10Y).slice(0, 2);
  expect(old.length, `two of BND, VTI, AGG, VNQ in the 10y tensor with history from ${START_10Y} or earlier`).toBe(2);
  const menu = [...old, young.id, "FIENX"];
  const menuExpected = menu.filter((id) => !firstDate.has(id) || firstDate.get(id)! > THRESHOLD_10Y).sort();
  expect(menuExpected, "the computed exclusions of the custom menu: the young fund, and FIENX as not served").toEqual([young.id, "FIENX"].sort());
  console.log(`A-PS-63 10y custom menu [${menu.join(",")}]: expected exclusions [${menuExpected.join(",")}] (${young.id} starts ${young.first})`);

  const menuHash = universeHash(menu.map((id) => ({ id })));
  await page.goto("/?f=" + menu.join(",") + "&lb=10y");
  const menuLoaded = () => api.tensors.find((entry) => entry.status === 200 && entry.body !== null && entry.path.endsWith("/" + menuHash + "/10y"));
  await expect.poll(() => menuLoaded() !== undefined, { timeout: 150_000, message: `the page must load the custom menu's 10y tensor (hash ${menuHash})` }).toBe(true);
  const menuTensor = menuLoaded()!.body;
  expect(menuTensor.lookback.id).toBe("10y");
  expect(menuTensor.universe.hash).toBe(menuHash);
  expect(menuTensor.universe.excluded.map((item: { id: string }) => item.id).sort()).toEqual(menuExpected);
  expect(menuTensor.universe.funds.map((fund: { id: string }) => fund.id).sort()).toEqual([...old].sort());
  for (const row of menuTensor.frontier.w as number[][]) expect(row.length, "a frontier weight vector carries the excluded fund").toBe(old.length);

  await expect(page.getByTestId("chart-canvas")).toBeVisible({ timeout: 15_000 });
  await openSection(page, "settings", "lookback-10y");
  const menuNotes = page.getByTestId("section-settings").getByTestId("excluded-note");
  const menuListed = async () => {
    const shown = (await menuNotes.allInnerTexts()).join("\n");
    return menu.filter((id) => new RegExp("(^|[^A-Z0-9-])" + id + "($|[^A-Z0-9-])").test(shown)).sort().join(",");
  };
  // Must-not-contain: an exclusion list that differs from the computed set.
  await expect.poll(menuListed, { timeout: 10_000 }).toBe(menuExpected.join(","));
  const menuText = (await menuNotes.allInnerTexts()).join("\n");
  const youngTemplate = new RegExp(young.id + "\\b[^\\n]*history starts \\d{4}-\\d{2}-\\d{2}, not enough for the [^\\n]+ view");
  expect(youngTemplate.test(menuText), `excluded-note for ${young.id} follows the spec 5.6 template`).toBe(true);
});

test("ghost-1y toggles the ghost count and the canvas, and back", async ({ page }) => {
  await loadDefault(page);
  const chart = page.getByTestId("chart");
  await openSection(page, "settings", "ghost-1y");
  await expect(chart).toHaveAttribute("data-ghost-count", "0");
  const off1 = await settledSample(page);

  await page.getByTestId("ghost-1y").click();
  await expect(chart).toHaveAttribute("data-ghost-count", "1", { timeout: 30_000 });
  await expect.poll(async () => !same(await sampleCanvas(page), off1), { timeout: 15_000 }).toBe(true);
  const on = await settledSample(page);

  await page.getByTestId("ghost-1y").click();
  // Must-not-contain: a ghost count that fails to return to 0.
  await expect(chart).toHaveAttribute("data-ghost-count", "0", { timeout: 15_000 });
  await expect.poll(async () => same(await sampleCanvas(page), off1), { timeout: 15_000 }).toBe(true);
  const off2 = await settledSample(page);
  const mean = (values: number[]) => values.reduce((sum, value) => sum + value, 0) / values.length;
  expect(off1.length).toBe(50);
  expect(mean(on)).not.toBe(mean(off1));
  expect(mean(on)).not.toBe(mean(off2));
  expect(mean(off2)).toBe(mean(off1));
  expect(same(off2, off1)).toBe(true);
});

test("cap-max-VTI = 10 rebuilds and no VTI weight exceeds the cap", async ({ page }) => {
  test.setTimeout(300_000);
  await defaultPreset(page);
  await expect
    .poll(async () => (await apiJson(page, "/api/health")).queue.depth, { timeout: 120_000, intervals: [3_000] })
    .toBe(0);
  const api = watchApi(page);
  await loadDefault(page);
  await settledSample(page);
  await openSection(page, "settings", "cap-max-VTI");
  const posts = () => api.posts.filter((post) => post.path === "/api/tensors");
  expect(posts().length).toBe(0);

  const input = await inputOf(page.getByTestId("cap-max-VTI"));
  await input.fill("10");
  await input.press("Enter");
  await input.blur();
  await expect.poll(() => posts().length, { timeout: 15_000 }).toBeGreaterThanOrEqual(1);
  const post = posts()[0];
  await expect.poll(() => post.status, { timeout: 30_000 }).not.toBeNull();
  const vtiRequested = (post.body.funds as Fund[]).find((fund) => fund.id === "VTI");
  expect(vtiRequested, "VTI in the POST body").toBeTruthy();
  expect(Math.abs((vtiRequested!.max ?? -1) - CAP)).toBeLessThan(1e-9);
  expect(post.body.lookback).toBe("5y");
  // 202 then 200; a key already built in this generation answers 200 at once (recorded).
  console.log(`A-PS-63 cap rebuild: POST answered ${post.status}`);
  expect([200, 202]).toContain(post.status);

  const hash = universeHash(post.body.funds);
  const built = () => api.tensors.find((entry) => entry.status === 200 && entry.body !== null && entry.path.includes("/" + hash + "/"));
  await expect.poll(() => built() !== undefined, { timeout: 150_000 }).toBe(true);
  const tensor = built()!.body;
  expect(tensor.universe.hash).toBe(hash);
  const vti = tensor.universe.funds.findIndex((fund: { id: string }) => fund.id === "VTI");
  expect(vti).toBeGreaterThanOrEqual(0);
  expect(Math.abs(tensor.bounds.requested[vti].max - CAP)).toBeLessThan(1e-9);
  expect(tensor.bounds.max[vti]).toBeLessThanOrEqual(CAP + 1e-6);

  // Must-not-contain: a VTI weight above the cap, on the frontier or in any feasible cell.
  let frontierRows = 0;
  for (const row of tensor.frontier.w as number[][]) {
    expect(row[vti]).toBeLessThanOrEqual(CAP + 1e-6);
    frontierRows += 1;
  }
  expect(frontierRows).toBe(tensor.frontier.x.length);
  expect(frontierRows).toBeGreaterThanOrEqual(2);
  let cells = 0;
  let worst = 0;
  for (const column of tensor.grid.w as (number[] | null)[][]) {
    for (const cell of column) {
      if (cell === null) continue;
      worst = Math.max(worst, cell[vti]);
      cells += 1;
    }
  }
  expect(cells).toBeGreaterThan(0);
  expect(worst).toBeLessThanOrEqual(CAP + 1e-6);
  console.log(`A-PS-63 cap rebuild: ${frontierRows} frontier rows and ${cells} grid cells checked, max VTI ${worst}`);

  await page.waitForTimeout(1_500);
  expect(posts().length, "POSTs for one cap edit").toBe(1);
});
"""
EXPECTED_TITLES = {
    "10y lookback redraws the frontier and lists the computed exclusions",
    "ghost-1y toggles the ghost count and the canvas, and back",
    "cap-max-VTI = 10 rebuilds and no VTI weight exceeds the cap",
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


def _window_10y(asof: str) -> tuple[str, str]:
    """(start_10y, threshold) as ISO dates: asof - 2,520 XNYS sessions, and 252 sessions later."""
    calendars = _need("exchange_calendars")
    pandas = _need("pandas")
    end = pandas.Timestamp(asof)
    sessions = calendars.get_calendar("XNYS").sessions_in_range(
        end - pandas.Timedelta(days=4400), end
    )
    assert len(sessions) > 2520, f"only {len(sessions)} XNYS sessions found before {asof}"
    is_session = sessions[-1] == end
    assert is_session, f"asof {asof} is not an XNYS session"
    start = sessions[-1 - 2520]
    threshold = sessions[-1 - 2520 + 252]
    return start.date().isoformat(), threshold.date().isoformat()


if _OUTER:

    def test_a_ps_63_in_project_venv():
        env = dict(os.environ, PS_GATE_INNER="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        try:
            proc = subprocess.run(
                [
                    str(_VENV_PY),
                    "-m",
                    "pytest",
                    "-q",
                    "--noconftest",
                    "-p",
                    "no:cacheprovider",
                    __file__,
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=1700,
            )
        except subprocess.TimeoutExpired:
            pytest.fail("A-PS-63 did not finish within 1700 s inside the project virtualenv")
        print(_scrub(proc.stdout[-8000:]), _scrub(proc.stderr[-2000:]))
        code = proc.returncode  # a plain int, so a failure never prints the child's raw output
        assert code == 0, "A-PS-63 is red inside the project virtualenv (output above)"

else:

    def test_a_ps_63_playwright():
        secret = _env("PS_GATE_SECRET")
        resp = _reached(
            _http(
                "GET", SITE + "/api/presets", {"x-ps-gate": secret, "Accept": "application/json"}
            ),
            "GET /api/presets with the header",
        )
        assert resp.status == 200, f"GET /api/presets with the header: status {resp.status}"
        body = _json_or_none(resp.text)
        asof = body.get("asof") if isinstance(body, dict) else None
        assert isinstance(asof, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", asof), f"asof {asof!r}"
        start, threshold = _window_10y(asof)
        print(f"A-PS-63: asof {asof}, start_10y {start}, exclusion threshold {threshold}")
        assert start != threshold
        output = _playwright(
            "a_ps_63",
            SPEC_TS,
            EXPECTED_TITLES,
            extra_env={
                "PS_GATE_ASOF": asof,
                "PS_GATE_START_10Y": start,
                "PS_GATE_THRESHOLD_10Y": threshold,
            },
            timeout=1500,
        )
        leaked = secret in output
        assert not leaked, "the gate secret reached the test output"
