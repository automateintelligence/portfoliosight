// Shared fixtures and page helpers for the production smoke tests (smoke.spec.ts, preview.spec.ts).
//
// The gate header: `x-ps-gate` is added only to requests whose origin is the site's own, by a
// route on the browser context. The request is fetched with redirects off and the answer handed
// back to the browser, so a redirect to another origin can never carry the header (with
// `route.continue({ headers })` it would: the override follows the redirect). Calls made from the
// test itself go through `site`, which sets the header per call and only for the site's own hosts.
import { expect, request as playwrightRequest, test as base, type APIRequestContext, type APIResponse, type BrowserContext, type Locator, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { redact, SECRET_NAMES, type FundPolicy, type Rgb, type TensorLike } from "./smoke-lib";

export * from "./smoke-lib";
export { expect };

const here = path.dirname(fileURLToPath(import.meta.url));
export const WEB = path.resolve(here, "..");
export const REPO = path.resolve(WEB, "..");
export const ARTIFACTS = path.join(WEB, "e2e", "artifacts", "smoke");
export const RUNBOOK = path.join(REPO, "docs", "plans", "2026-10-13-ks001-cloudflare-runbook.md");

/** A local dry run: the same specs against `vite preview` and the API mock, with no gate header. */
export const DRY_RUN = process.env.PS_SMOKE_DRY_RUN === "1";
export const GATE_HEADER = "x-ps-gate";
const BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36";

/** A required environment variable; its absence is a failure that names the variable. */
export function env(name: string): string {
  const value = (process.env[name] ?? "").trim();
  if (!value) throw new Error(`${name} is not set (scripts/smoke.sh loads it from the settings file)`);
  return value;
}

/** The gate secret: required against production, absent in a local dry run. */
export function gateSecret(): string {
  return DRY_RUN ? "" : env("PS_GATE_SECRET");
}

/** The hosts the header may go to: the site, its www alias and its api host. Nothing else. */
export function siteHosts(baseURL: string): { site: string; www: string; api: string } {
  const url = new URL(baseURL);
  const port = url.port ? `:${url.port}` : "";
  return { site: url.origin, www: `${url.protocol}//www.${url.hostname}${port}`, api: `${url.protocol}//api.${url.hostname}${port}` };
}

export type Site = {
  origin: string;
  www: string;
  api: string;
  /** GET with the gate header (unless `gate: false`), never following redirects. */
  get(url: string, options?: { gate?: boolean }): Promise<APIResponse>;
  post(url: string, data: unknown, options?: { gate?: boolean }): Promise<APIResponse>;
  json(url: string): Promise<unknown>;
};

function makeSite(ctx: APIRequestContext, baseURL: string): Site {
  const hosts = siteHosts(baseURL);
  const own = new Set([hosts.site, hosts.www, hosts.api]);
  const absolute = (url: string) => (url.startsWith("/") ? hosts.site + url : url);
  const headers = (url: string, gate: boolean): Record<string, string> => {
    const out: Record<string, string> = { "user-agent": BROWSER_UA };
    if (!gate || DRY_RUN) return out;
    if (!own.has(new URL(url).origin)) throw new Error(`the gate header is only ever sent to the site's own hosts, not to ${new URL(url).origin}`);
    out[GATE_HEADER] = gateSecret();
    return out;
  };
  const site: Site = {
    origin: hosts.site,
    www: hosts.www,
    api: hosts.api,
    get: (url, options = {}) => ctx.get(absolute(url), { headers: headers(absolute(url), options.gate ?? true), maxRedirects: 0, failOnStatusCode: false }),
    post: (url, data, options = {}) =>
      ctx.post(absolute(url), { headers: { ...headers(absolute(url), options.gate ?? true), origin: hosts.site }, data, maxRedirects: 0, failOnStatusCode: false }),
    async json(url) {
      const response = await site.get(url);
      expect(response.status(), `GET ${url} with the gate header`).toBe(200);
      return response.json();
    },
  };
  return site;
}

/**
 * Puts the gate header on this context's requests to the site's own origin and nowhere else, and
 * records every other origin the pages contact. Returns that record.
 */
export async function gateContext(context: BrowserContext, baseURL: string): Promise<Set<string>> {
  const origin = new URL(baseURL).origin;
  const secret = gateSecret();
  const foreign = new Set<string>();
  context.on("request", (request) => {
    const url = new URL(request.url());
    if ((url.protocol === "http:" || url.protocol === "https:") && url.origin !== origin) foreign.add(url.origin);
  });
  if (secret) {
    await context.route(
      (url) => url.origin === origin,
      async (route) => {
        const response = await route.fetch({ headers: { ...route.request().headers(), [GATE_HEADER]: secret }, maxRedirects: 0 });
        await route.fulfill({ response });
      },
    );
  }
  return foreign;
}

type Fixtures = {
  /** Auto: the gate header for the site's own origin, and a failure if a page contacts any other. */
  gate: Set<string>;
  /** A cookieless HTTP client for calls the test makes itself. */
  site: Site;
};

export const test = base.extend<Fixtures>({
  gate: [
    async ({ context, baseURL }, provide) => {
      const foreign = await gateContext(context, baseURL as string);
      await provide(foreign);
      // Fonts are self-hosted and the page names no other origin (run rule 15, INTERFACES.md).
      expect([...foreign], "origins other than the site's own that a page contacted").toEqual([]);
    },
    { auto: true },
  ],
  site: async ({ baseURL }, provide) => {
    const ctx = await playwrightRequest.newContext();
    await provide(makeSite(ctx, baseURL as string));
    await ctx.dispose();
  },
});

// ── Python side: the trading calendar and the store (never re-implemented here) ──────────────

function projectPython(): string {
  const candidates = [process.env.PS_PYTHON ?? "", path.join(REPO, ".venv", "bin", "python")];
  const dotGit = path.join(REPO, ".git");
  if (fs.existsSync(dotGit) && fs.statSync(dotGit).isFile()) {
    // a linked worktree: "gitdir: <main>/.git/worktrees/<name>"
    const gitdir = fs.readFileSync(dotGit, "utf8").split(":").slice(1).join(":").trim();
    candidates.push(path.join(path.resolve(gitdir, "..", "..", ".."), ".venv", "bin", "python"));
  }
  const found = candidates.find((candidate) => candidate !== "" && fs.existsSync(candidate));
  if (!found) throw new Error("no project interpreter: set PS_PYTHON or create .venv with `uv pip install -e .[api,dev]`");
  return found;
}

export type Ran = { status: number; stdout: string; stderr: string };

/** Runs a command from the repository root; output is redacted before anything can print it. */
export function run(command: string, args: string[], options: { env?: Record<string, string>; input?: string; timeoutMs?: number; cwd?: string } = {}): Ran {
  try {
    const stdout = execFileSync(command, args, {
      cwd: options.cwd ?? REPO,
      env: { ...process.env, ...(options.env ?? {}) },
      input: options.input,
      encoding: "utf8",
      timeout: options.timeoutMs ?? 120_000,
      maxBuffer: 64 * 1024 * 1024,
      stdio: ["pipe", "pipe", "pipe"],
    });
    return { status: 0, stdout, stderr: "" };
  } catch (err) {
    const failed = err as { status?: number | null; stdout?: string; stderr?: string; message?: string };
    if (typeof failed.status !== "number") throw new Error(redact(`${command} could not run: ${failed.message ?? "unknown error"}`));
    return { status: failed.status, stdout: failed.stdout ?? "", stderr: redact(failed.stderr ?? "") };
  }
}

export function python(args: string[], options: { env?: Record<string, string>; input?: string; timeoutMs?: number } = {}): Ran {
  return run(projectPython(), args, options);
}

function pythonJson<T>(code: string, args: string[]): T {
  const result = python(["-c", code, ...args]);
  if (result.status !== 0) throw new Error(`the calendar helper failed: ${result.stderr.slice(-600)}`);
  return JSON.parse(result.stdout) as T;
}

/** `D_G` for a nightly run on the Los Angeles day of `now` (spec 4.2), from the product's calendar. */
export function generationDate(now: Date = new Date()): string {
  const code = [
    "import json, sys",
    "from datetime import datetime",
    "from portfoliosight.data.calendar import generation_date",
    "print(json.dumps(generation_date(datetime.fromisoformat(sys.argv[1])).isoformat()))",
  ].join("\n");
  return pythonJson<string>(code, [now.toISOString().replace("Z", "+00:00")]);
}

/** Hour of the day in Los Angeles, for the "at or after 08:00 PT" rule of DoD 23. */
export function losAngelesHour(now: Date = new Date()): number {
  return Number(new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", hourCycle: "h23" }).format(now));
}

/** XNYS sessions around `asof`: the session `back` sessions earlier, then `forward` sessions after that. */
export function sessionWindow(asof: string, back: number, forward = 0): { isSession: boolean; start: string; threshold: string } {
  const code = [
    "import json, sys",
    "from datetime import date, timedelta",
    "import exchange_calendars as xcals",
    "asof, back, forward = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])",
    "day = date.fromisoformat(asof)",
    "sessions = xcals.get_calendar('XNYS').sessions_in_range((day - timedelta(days=2 * back + 60)).isoformat(), asof)",
    "assert len(sessions) > back, 'not enough sessions'",
    "print(json.dumps({'isSession': str(sessions[-1])[:10] == asof, 'start': str(sessions[-1 - back])[:10], 'threshold': str(sessions[-1 - back + forward])[:10]}))",
  ].join("\n");
  return pythonJson(code, [asof, String(back), String(forward)]);
}

// ── Watching the page's own API traffic ──────────────────────────────────────

export type PostBody = { funds: FundPolicy[]; lookback: string };
export type Post = { path: string; body: PostBody; at: number; status: number | null };
export type TensorGet = { path: string; status: number; at: number; body: TensorLike | null };

/** Records every POST to /api/* and every GET of a tensor URL (with the 200 bodies). */
export function watchApi(page: Page) {
  const posts: Post[] = [];
  const tensors: TensorGet[] = [];
  const gets: string[] = [];
  const pending = new Map<unknown, Post>();
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) return;
    if (request.method() === "GET") gets.push(url.pathname);
    if (request.method() !== "POST") return;
    let body: unknown = null;
    try {
      body = request.postDataJSON();
    } catch {
      body = null;
    }
    const entry: Post = { path: url.pathname, body: body as PostBody, at: Date.now(), status: null };
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
      try {
        entry.body = (await response.json()) as TensorLike;
      } catch {
        entry.body = null;
      }
    }
  });
  const loaded = () => tensors.filter((entry) => entry.status === 200 && entry.body !== null);
  return {
    posts,
    tensors,
    gets,
    tensorPosts: () => posts.filter((post) => post.path === "/api/tensors"),
    /** The newest tensor the page received, optionally for one lookback. */
    latest: (lookback?: string): TensorLike | null => {
      const all = loaded().filter((entry) => !lookback || entry.body!.lookback.id === lookback);
      return all.length ? all[all.length - 1].body : null;
    },
    loaded,
  };
}

export type Api = ReturnType<typeof watchApi>;

// ── Page helpers ─────────────────────────────────────────────────────────────

/** Opens the page (with an optional query) and waits for a drawn chart. */
export async function openApp(page: Page, query = ""): Promise<void> {
  const response = await page.goto(query ? `/?${query}` : "/");
  expect(response?.status(), "GET / with the gate header").toBe(200);
  await expect(page.getByTestId("chart-canvas")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("point-selected")).toBeVisible({ timeout: 15_000 });
}

/** The tensor the page is showing: waits for the page's own tensor request to answer. */
export async function shownTensor(api: Api, lookback?: string): Promise<TensorLike> {
  await expect.poll(() => api.latest(lookback) !== null, { timeout: 30_000, message: "the page loads a tensor" }).toBe(true);
  return api.latest(lookback) as TensorLike;
}

/** Expands a collapsed section through its first-screen chip (spec 3.3). */
export async function openSection(page: Page, id: "funds" | "trades" | "stress" | "settings"): Promise<Locator> {
  const section = page.getByTestId(`section-${id}`);
  if ((await section.getAttribute("aria-expanded")) !== "true") await page.getByTestId(`chip-${id}`).click();
  await expect(section).toHaveAttribute("aria-expanded", "true");
  return section;
}

export async function param(page: Page, key: string): Promise<string | null> {
  return new URL(page.url()).searchParams.get(key);
}

export type Rect = { left: number; top: number; right: number; bottom: number; width: number; height: number; cx: number; cy: number };

export async function rectOf(locator: Locator): Promise<Rect> {
  return locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height, cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
  });
}

/** The risk position `s`, read from the risk slider's ARIA value (four decimals). */
export async function riskPosition(page: Page): Promise<number> {
  return Number(await page.getByTestId("risk-slider").getAttribute("aria-valuenow"));
}

/** Focuses a slider and presses a key on it `times` times. */
export async function nudge(slider: Locator, key: string, times = 1): Promise<void> {
  await slider.focus();
  for (let i = 0; i < times; i++) await slider.press(key);
}

/** The key that moves the diversification slider toward "More diversified" in its orientation. */
export async function towardDiversified(slider: Locator): Promise<string> {
  return (await slider.getAttribute("aria-orientation")) === "horizontal" ? "ArrowRight" : "ArrowDown";
}

/** Presses the diversification slider at one end of its track: "return" (top/left) or "diversified". */
export async function pressDivEnd(slider: Locator, end: "return" | "diversified", options: { force?: boolean } = {}): Promise<void> {
  const horizontal = (await slider.getAttribute("aria-orientation")) === "horizontal";
  const box = await rectOf(slider);
  const near = 3;
  const position = horizontal
    ? { x: end === "return" ? near : box.width - near, y: box.height / 2 }
    : { x: box.width / 2, y: end === "return" ? near : box.height - near };
  await slider.scrollIntoViewIfNeeded();
  // Forced for a slider the page has disabled: the press must still reach it, to show it does nothing.
  await slider.click({ position, force: options.force ?? false });
}

/** Chart scales from the overlay's d3-axis ticks: client pixel = a + b · value (value as a fraction). */
export async function chartScales(page: Page): Promise<{ x: (v: number) => number; y: (v: number) => number }> {
  const groups = await page.getByTestId("chart").evaluate((chart) => {
    const byParent = new Map<Element, { value: number; px: number; py: number }[]>();
    for (const tick of Array.from(chart.querySelectorAll("svg g.tick"))) {
      const line = tick.querySelector("line");
      const text = tick.querySelector("text");
      if (!line || !text || !tick.parentElement) continue;
      const value = parseFloat((text.textContent || "").replace(/[−–]/g, "-").replace(/[^0-9.+-]/g, ""));
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
    expect(worst, "the axis ticks lie on one linear scale").toBeLessThanOrEqual(1);
    if (horizontal && !x) x = { a, b };
    if (!horizontal && !y) y = { a, b };
  }
  if (!x || !y) throw new Error("could not read both chart scales from the axis ticks");
  const sx = x;
  const sy = y;
  expect(sx.b, "risk increases to the right").toBeGreaterThan(0);
  expect(sy.b, "return increases upwards").toBeLessThan(0);
  return { x: (v: number) => sx.a + sx.b * v, y: (v: number) => sy.a + sy.b * v };
}

/** Computed colours of CSS custom properties, resolved inside the chart. */
export async function themeColors(page: Page, names: string[]): Promise<Record<string, Rgb>> {
  const raw = await page.getByTestId("chart").evaluate((chart, props) => {
    const probe = document.createElement("span");
    chart.appendChild(probe);
    const out: Record<string, string> = {};
    for (const name of props) {
      probe.style.color = "";
      probe.style.color = `var(${name})`;
      out[name] = getComputedStyle(probe).getPropertyValue(name).trim() === "" ? "" : getComputedStyle(probe).color;
    }
    probe.remove();
    return out;
  }, names);
  const out: Record<string, Rgb> = {};
  for (const name of names) {
    const nums = (raw[name].match(/-?\d+(\.\d+)?/g) || []).map(Number);
    if (!/^rgba?\(/.test(raw[name]) || nums.length < 3) throw new Error(`custom property ${name} does not compute to a colour (got "${raw[name]}")`);
    out[name] = [nums[0], nums[1], nums[2]];
  }
  return out;
}

/** Canvas pixels (r, g, b, a) at client coordinates. */
export async function canvasPixels(page: Page, points: { x: number; y: number }[]): Promise<number[][]> {
  const result = await page.getByTestId("chart-canvas").evaluate((el, pts) => {
    if (!(el instanceof HTMLCanvasElement)) return { error: "chart-canvas is not a <canvas> element", pixels: [] as number[][] };
    const ctx = el.getContext("2d");
    if (!ctx) return { error: "chart-canvas has no 2d context", pixels: [] as number[][] };
    const rect = el.getBoundingClientRect();
    const pixels: number[][] = [];
    for (const p of pts) {
      const px = Math.floor((p.x - rect.left) * (el.width / rect.width));
      const py = Math.floor((p.y - rect.top) * (el.height / rect.height));
      if (px < 0 || py < 0 || px >= el.width || py >= el.height) return { error: `sample point (${p.x.toFixed(1)}, ${p.y.toFixed(1)}) is outside chart-canvas`, pixels };
      pixels.push(Array.from(ctx.getImageData(px, py, 1, 1).data));
    }
    return { error: "", pixels };
  }, points);
  if (result.error) throw new Error(result.error);
  return result.pixels;
}

/** A position-sensitive checksum of 50 one-pixel columns of the canvas: any redraw changes it. */
export async function canvasPrint(page: Page): Promise<number[]> {
  return page.getByTestId("chart-canvas").evaluate((el) => {
    if (!(el instanceof HTMLCanvasElement)) throw new Error("chart-canvas is not a <canvas> element");
    const ctx = el.getContext("2d");
    if (!ctx) throw new Error("chart-canvas has no 2d context");
    const out: number[] = [];
    for (let i = 0; i < 50; i++) {
      const x = Math.min(el.width - 1, Math.floor(((i + 0.5) / 50) * el.width));
      const data = ctx.getImageData(x, 0, 1, el.height).data;
      let sum = 0;
      for (let p = 0; p < data.length; p++) sum = (sum * 31 + data[p]) % 2147483647;
      out.push(sum);
    }
    return out;
  });
}

export const samePrint = (a: number[], b: number[]): boolean => a.length === b.length && a.every((value, index) => value === b[index]);

/** A drawing that is not blank and is the same in two readings 250 ms apart. */
export async function settledPrint(page: Page): Promise<number[]> {
  let previous = await canvasPrint(page);
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(250);
    const next = await canvasPrint(page);
    if (samePrint(previous, next) && next.some((value) => value !== 0)) return next;
    previous = next;
  }
  throw new Error("chart-canvas never settled to a drawing within 15 s");
}

/** Picks an entry of the preset menu by its exact label. */
export async function choosePreset(page: Page, label: string | RegExp): Promise<void> {
  const menu = page.getByTestId("preset-menu");
  if ((await menu.getAttribute("aria-expanded")) !== "true") await menu.click();
  const entry = page.getByRole("menuitemradio", { name: label, exact: typeof label === "string" });
  await expect(entry, `the portfolio menu offers ${String(label)}`).toBeVisible({ timeout: 10_000 });
  await entry.click();
}

export async function fundRowIds(page: Page): Promise<string[]> {
  return page.locator('[data-testid^="fund-row-"]').evaluateAll((rows) => rows.map((row) => (row.getAttribute("data-testid") ?? "").slice("fund-row-".length)));
}

/** Types into the fund picker and commits: the matching option if one shows, else Enter. */
export async function typeFund(page: Page, id: string): Promise<void> {
  const input = page.getByTestId("fund-add");
  await input.fill(id);
  const exact = new RegExp(`(^|[^A-Z0-9-])${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}($|[^A-Z0-9-])`);
  const option = page.getByRole("option").filter({ hasText: exact }).first();
  try {
    await option.click({ timeout: 2_500 });
  } catch {
    await input.press("Enter");
  }
}

/** Makes the Funds table hold exactly `ids` (a draft until "Use this menu"). */
export async function setMenu(page: Page, ids: string[]): Promise<void> {
  for (const id of await fundRowIds(page)) {
    if (ids.includes(id)) continue;
    await page.getByTestId(`fund-row-${id}`).getByRole("button", { name: /remove/i }).click();
    await expect(page.getByTestId(`fund-row-${id}`)).toHaveCount(0);
  }
  for (const id of ids) {
    if ((await page.getByTestId(`fund-row-${id}`).count()) > 0) continue;
    await typeFund(page, id);
    await expect(page.getByTestId(`fund-row-${id}`), `the row of ${id} after adding it`).toBeVisible({ timeout: 5_000 });
  }
  expect((await fundRowIds(page)).sort()).toEqual([...ids].sort());
}

/** Waits until nothing is queued and nothing is being built, as DoD 12 and 30 require before a measurement. */
export async function idleQueue(site: Site, timeoutMs = 120_000): Promise<void> {
  await expect
    .poll(
      async () => {
        const queue = ((await site.json("/api/health")) as { queue: { depth: number; building: boolean } }).queue;
        return [queue.depth, queue.building];
      },
      { timeout: timeoutMs, intervals: [3_000], message: "the build queue is idle (depth 0, nothing building)" },
    )
    .toEqual([0, false]);
}

/** Everything a visitor can read or be told by a screen reader, as one string. */
export async function pageWords(page: Page): Promise<string> {
  return page.evaluate(() => {
    const parts = [document.body.innerText];
    for (const el of Array.from(document.querySelectorAll("[aria-label], [title], [placeholder], [alt], [aria-valuetext]"))) {
      for (const name of ["aria-label", "title", "placeholder", "alt", "aria-valuetext"]) parts.push(el.getAttribute(name) ?? "");
    }
    return parts.join("\n");
  });
}

/** The values of the named credentials, for the leak scans of DoD 25 (never printed). */
export function secretValues(): string[] {
  const out: string[] = [];
  for (const name of SECRET_NAMES) {
    if (name === "PS_SHARE_TEST_RECIPIENT") continue;
    const value = (process.env[name] ?? "").trim();
    if (!value.includes("\n")) {
      if (value.length >= 8) out.push(value);
      continue;
    }
    // a multi-line key (PEM): each body line is a needle of its own
    for (const line of value.split(/\r?\n/).map((part) => part.trim())) if (line.length >= 16 && !line.startsWith("-----")) out.push(line);
  }
  return out;
}
