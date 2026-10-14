// Production smoke tests: one per definition of done in spec 11, titled DoD-NN.
//
// Run with scripts/smoke.sh (base URL and secrets come from the environment). Each test reads
// what it expects from the live answers (`/api/presets`, `/api/symbols`, `/api/health`, the tensor
// the page itself loaded) and does its own arithmetic on them, so a page that merely renders
// cannot pass. Which tests run on the phone project is set in playwright.config.ts.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  ARTIFACTS, DRY_RUN, REPO, RUNBOOK, WEB, benchmarkRecords, canvasPixels, canvasPrint, channelDistance, chartScales, choosePreset, collapsedPosition,
  decisionDates, env, expect, frontAt, fundRowIds, gateContext, generationDate, idleQueue, losAngelesHour, mixStats, nudge, openApp, openSection,
  pageWords, param, parsePercent, pickCells, pressDivEnd, python, range6mPct, readmeProblems, rectOf, rgbBasis, riskPosition, ruleMaxPct, run,
  samePrint, secretValues, sessionWindow, setMenu, settledPrint, shownTensor, sliderDomain, stressOf, test, themeColors, towardDiversified, typeFund,
  universeHash, walkableColumn, watchApi, wordFor, ROADMAP_ITEMS, type TensorLike,
} from "./helpers";

const GUIDE_NAME = "Example Portfolio";
const TSP_NAME = "TSP (G, F, C, S, I)";
const TSP_IDS = ["TSP-C", "TSP-F", "TSP-G", "TSP-I", "TSP-S"];
const LOOKBACKS = ["1y", "2y", "3y", "5y", "10y", "ew"];
const THEME_BG: Record<string, string> = { "ks-dark": "#141417", light: "#F3F3F3", hud: "#080506", grid: "#04070B" };
const DISCLAIMER =
  "PortfolioSight is an educational tool. All figures are mathematical results computed from historical prices and are hypothetical; past performance does not predict future results. Nothing here is investment, tax or legal advice, and no output is a recommendation to buy or sell anything. PortfolioSight is not registered with the SEC, FINRA or any other regulator. You remain solely responsible for your decisions. Price data: Tiingo and tsp.gov.";
const FAMILY = ["https://option-spread-scanner.ingage-bd0.workers.dev", "https://automateintelligence.ai", "https://securitysight.ai"];
const DIV_DISABLED = "At this risk, the best-return mix is already the most diversified one found.";
const STRESS_SENTINEL = "Not enough of this mix existed then to say";
const STRESS_IDS = ["gfc2008", "covid2020", "rates2022"];
const BENCHMARK_S = 30;

type Presets = {
  generation: string;
  asof: string;
  presets: { id: string; name: string; hash: string; funds: { id: string }[]; allocation: Record<string, number> | null; lookbacks: Record<string, { status: string; url: string }> }[];
};
type Symbols = { symbols: { id: string; name: string; first_date: string }[] };

const hex = (rgb: number[]) => `#${rgb.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`.toUpperCase();
const mkTemp = (prefix: string) => fs.mkdtempSync(path.join(os.tmpdir(), prefix));

/** The holdings file behind the default preset: amount = Qty × Price (spec 3.3). */
function guideHoldings(): { id: string; amount: number }[] {
  const lines = fs.readFileSync(path.join(REPO, "data", "holdings", "holdings_guide2017_step2.csv"), "utf8").split(/\r?\n/).filter((line) => line.trim() !== "");
  return lines.slice(1).map((line) => {
    const cells = line.split(",");
    return { id: cells[1].trim().toUpperCase(), amount: Number(cells[cells.length - 2]) * Number(cells[cells.length - 1]) };
  });
}

/** The percent figure of a readout or a strip value on the page. */
async function shownPercent(page: import("@playwright/test").Page, testId: string): Promise<number> {
  return parsePercent((await page.getByTestId(testId).innerText()).replace(/\s+/g, " "), testId);
}

/** The two figures of the details line: this mix's measure and the highest found on the menu. */
async function shownMeasure(page: import("@playwright/test").Page): Promise<{ enb: number; best: number }> {
  const line = await page.getByTestId("details-enb").innerText();
  return { enb: Number(/equivalent of (\d+(?:\.\d+)?) independent/.exec(line)?.[1]), best: Number(/menu: (\d+(?:\.\d+)?)/.exec(line)?.[1]) };
}
/** Equal to one decimal, as a figure printed with one decimal can be. */
const near = (shown: number, own: number) => Math.abs(shown - own) <= 0.051;

/** Distance in pixels from a point to a polyline. */
function distanceToLine(point: { x: number; y: number }, line: { x: number; y: number }[]): number {
  let best = Infinity;
  for (let i = 1; i < line.length; i++) {
    const a = line[i - 1];
    const b = line[i];
    const span = (b.x - a.x) ** 2 + (b.y - a.y) ** 2;
    const f = span === 0 ? 0 : Math.min(1, Math.max(0, ((point.x - a.x) * (b.x - a.x) + (point.y - a.y) * (b.y - a.y)) / span));
    best = Math.min(best, Math.hypot(point.x - (a.x + f * (b.x - a.x)), point.y - (a.y + f * (b.y - a.y))));
  }
  return best;
}

test("DoD-01 the page loads with the gate header and draws the chart within 5 s", async ({ page }) => {
  const api = watchApi(page);
  // The five seconds run from the moment the address is asked for, not from the end of loading.
  const started = Date.now();
  const response = await page.goto("/", { waitUntil: "commit", timeout: 5_000 });
  expect(response?.status(), "GET / with the gate header").toBe(200);
  expect(response?.headers()["cf-mitigated"], "no challenge for a request with the header").toBeUndefined();
  await expect(page.getByTestId("chart-canvas")).toBeVisible({ timeout: Math.max(1, 5_000 - (Date.now() - started)) });
  expect(Date.now() - started, "milliseconds from the request to a visible chart").toBeLessThanOrEqual(5_000);
  await expect(page.getByText("PortfolioSight is in private preview")).toHaveCount(0);
  // A canvas element alone is not a chart: it must hold a settled drawing of the default menu.
  const print = await settledPrint(page);
  expect(new Set(print).size, "distinct column checksums on the drawn canvas").toBeGreaterThan(5);
  const tensor = await shownTensor(api);
  expect(tensor.universe.funds.map((fund) => fund.id)).toContain("VTI");
  expect(await riskPosition(page)).toBeGreaterThanOrEqual(sliderDomain(tensor).sSafe - 1e-4);
});

test("DoD-02 the gate: challenge without the header, origin block, www redirect, no workers.dev", async ({ site }) => {
  // Control: with the header the Worker answers, so the refusals below are the gate and not an outage.
  expect((await site.get("/")).status(), "GET / with the header").toBe(200);

  const bare = await site.get("/", { gate: false });
  expect(bare.status(), "GET / without the header or a cookie").toBe(403);
  expect(bare.headers()["cf-mitigated"], "the refusal is Cloudflare's challenge").toBe("challenge");
  expect(await bare.text()).not.toContain('data-testid="chart');

  const direct = await site.get(`${site.api}/v1/health`, { gate: false });
  expect(direct.status(), "the api host without the header").toBe(403);
  expect(direct.headers()["cf-mitigated"], "a block, not a challenge").toBeUndefined();
  const health = await site.get(`${site.api}/v1/health`);
  expect(health.status(), "the api host with the header").toBe(200);
  expect(health.headers()["content-type"]).toContain("application/json");
  const body = await health.json();
  expect(body.generation).toMatch(/^\d{4}-\d{2}-\d{2}-[0-9.]+$/);
  expect(body.asof).toMatch(/^\d{4}-\d{2}-\d{2}$/);

  const www = await site.get(`${site.www}/?u=tsp`);
  expect(www.status(), "the www host redirects").toBe(301);
  expect(www.headers()["location"]).toBe(`${site.origin}/?u=tsp`);

  // The account's workers.dev name is never sent the gate header.
  const name = /"name"\s*:\s*"([^"]+)"/.exec(fs.readFileSync(path.join(WEB, "wrangler.jsonc"), "utf8"))?.[1];
  expect(name, "the Worker's name in web/wrangler.jsonc").toBe("portfoliosight");
  const lookup = await fetch(`${env("CLOUDFLARE_API_BASE")}/accounts/${env("CLOUDFLARE_ACCOUNT_ID")}/workers/subdomain`, {
    headers: { authorization: `Bearer ${env("CLOUDFLARE_API_TOKEN")}` },
  });
  expect(lookup.status, "reading the account's workers.dev subdomain").toBe(200);
  const subdomain = ((await lookup.json()) as { result?: { subdomain?: string } }).result?.subdomain ?? "";
  expect(subdomain).toMatch(/^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/);
  let status = 0;
  let text = "";
  try {
    const answer = await fetch(`https://${name}.${subdomain}.workers.dev/`, { redirect: "manual" });
    status = answer.status;
    text = await answer.text();
  } catch {
    status = 0; // no connection at all: the host does not serve anything
  }
  expect([0, 404], "workers.dev refuses the connection or answers 404").toContain(status);
  expect(text).not.toContain('data-testid="chart');
  expect(text).not.toContain("private preview");
});

test("DoD-03 desktop first screen: chart, sliders, result strip and chips; sections collapsed", async ({ page }) => {
  await openApp(page);
  const height = page.viewportSize()!.height;
  for (const id of ["chart", "risk-slider", "div-slider", "range-low", "range-typical", "range-high", "div-word", "chip-funds", "chip-trades", "chip-stress", "chip-settings"]) {
    const item = page.getByTestId(id);
    await expect(item, `${id} on the first screen`).toBeVisible();
    expect((await rectOf(item)).bottom, `${id} ends inside the first viewport`).toBeLessThanOrEqual(height);
  }
  await expect(page.locator("table")).toHaveCount(0);
  await expect(page.locator('[data-testid^="fund-row-"]')).toHaveCount(0);
  await expect(page.locator('[data-testid^="stress-"]')).toHaveCount(0);
  await expect(page.getByText("Total moved")).toHaveCount(0);
  for (const id of ["funds", "trades", "stress", "settings"]) {
    await expect(page.getByTestId(`section-${id}`), `section ${id} starts collapsed`).toHaveAttribute("aria-expanded", "false");
  }
  // A chip opens its own section and nothing else, and brings it into view.
  await page.getByTestId("chip-stress").click();
  await expect(page.getByTestId("section-stress")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("stress-gfc2008")).toBeInViewport();
  for (const id of ["funds", "trades", "settings"]) await expect(page.getByTestId(`section-${id}`)).toHaveAttribute("aria-expanded", "false");
});

test("DoD-04 phone first screen fits: no sideways scroll, thumb-sized targets, a tap moves the risk", async ({ page }) => {
  await openApp(page);
  const viewport = page.viewportSize()!;
  expect(viewport.width, "the phone project's viewport").toBeLessThanOrEqual(768);
  const overflow = () => page.evaluate((cap) => ({ scroll: document.documentElement.scrollWidth, inner: Math.min(window.innerWidth, cap) }), viewport.width);
  let size = await overflow();
  expect(size.scroll, "no horizontal scroll on load").toBeLessThanOrEqual(size.inner);

  const limit = 1.2 * (await page.evaluate(() => window.innerHeight));
  for (const id of ["chart", "risk-slider", "div-slider", "range-typical", "div-word", "chip-funds", "chip-stress", "chip-settings"]) {
    const item = page.getByTestId(id);
    await expect(item).toBeVisible();
    expect((await rectOf(item)).bottom, `${id} ends within the first 1.2 viewport heights`).toBeLessThanOrEqual(limit);
  }

  // Touch targets: every control of the first screen is at least 44 px in both directions, by its
  // own box, its label's, the box of the test-id wrapper it is alone in, or by hit-testing.
  const small = await page.evaluate(() => {
    const SELECTOR = "button, [role=slider], a, input, [data-testid=point-selected]";
    const MIN = 43.5;
    const found: string[] = [];
    let checked = 0;
    for (const el of Array.from(document.querySelectorAll(SELECTOR))) {
      if (!el.checkVisibility({ checkOpacity: false, checkVisibilityCSS: true })) continue;
      const own = el.getBoundingClientRect();
      if (own.width === 0 && own.height === 0) continue;
      checked += 1;
      const boxes = [own];
      const label = el.closest("label");
      if (label) boxes.push(label.getBoundingClientRect());
      const host = el.parentElement ? el.parentElement.closest("[data-testid]") : null;
      if (host && host.querySelectorAll(SELECTOR).length === 1) boxes.push(host.getBoundingClientRect());
      if (boxes.some((box) => box.width >= MIN && box.height >= MIN)) continue;
      el.scrollIntoView({ block: "center", inline: "center" });
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const lands = [[cx - 21.5, cy], [cx + 21.5, cy], [cx, cy - 21.5], [cx, cy + 21.5]].every(([x, y]) => {
        const hit = document.elementFromPoint(x, y);
        return !!hit && (hit === el || el.contains(hit));
      });
      if (!lands) found.push(`${el.tagName.toLowerCase()}[${el.getAttribute("data-testid") ?? el.getAttribute("aria-label") ?? (el.textContent ?? "").trim().slice(0, 24)}] ${own.width.toFixed(0)}x${own.height.toFixed(0)}`);
    }
    window.scrollTo(0, 0);
    return { found, checked };
  });
  expect(small.checked, "controls checked for their touch size").toBeGreaterThanOrEqual(8);
  expect(small.found, "controls under 44 x 44 px").toEqual([]);

  // A thumb works: tapping the risk track further right moves the ceiling right and both readouts.
  const slider = page.getByTestId("risk-slider");
  await nudge(slider, "Home");
  const before = { s: await riskPosition(page), line: (await rectOf(page.getByTestId("ceiling-line"))).cx, bad: await page.getByTestId("risk-readout-bad").innerText() };
  const track = await rectOf(slider);
  await page.touchscreen.tap(track.left + track.width * 0.8, track.cy);
  await expect.poll(() => riskPosition(page)).toBeGreaterThan(before.s + 1);
  expect((await rectOf(page.getByTestId("ceiling-line"))).cx).toBeGreaterThan(before.line + 5);
  expect(await page.getByTestId("risk-readout-bad").innerText()).not.toBe(before.bad);
  size = await overflow();
  expect(size.scroll, "no horizontal scroll after the tap").toBeLessThanOrEqual(size.inner);
});

test("DoD-05 default view: the Example Portfolio with its allocation; TSP loads in one click", async ({ page }) => {
  const api = watchApi(page);
  await openApp(page);
  const tensor = await shownTensor(api);
  await expect(page.getByTestId("preset-menu")).toHaveAttribute("aria-label", `Portfolio: ${GUIDE_NAME}`);
  await expect(page.getByTestId("point-current")).toBeVisible();

  await openSection(page, "funds");
  const holdings = guideHoldings();
  expect(holdings.length, "funds in the holdings file").toBe(23);
  expect((await fundRowIds(page)).sort()).toEqual(holdings.map((h) => h.id).sort());
  await expect(page.getByTestId("unit-toggle").getByRole("radio", { name: "$", exact: true })).toHaveAttribute("aria-checked", "true");
  let filled = 0;
  for (const holding of holdings) {
    const shown = await page.getByTestId(`fund-row-${holding.id}`).locator("input").inputValue();
    expect(Number(shown === "" ? 0 : shown), `amount shown for ${holding.id}`).toBe(holding.amount);
    if (Number(shown) > 0) filled += 1;
  }
  expect(filled, "funds with an amount").toBe(18);
  // Every fund of the default menu is in use in the 5-year view: nothing is set aside.
  expect(tensor.universe.funds.map((fund) => fund.id).sort(), "funds the default tensor uses").toEqual(holdings.map((h) => h.id).sort());
  expect(tensor.universe.excluded ?? [], "funds the default tensor sets aside").toEqual([]);
  await expect(page.getByTestId("excluded-note")).toHaveCount(0);
  await openSection(page, "settings");
  await expect(page.getByTestId("excluded-note")).toHaveCount(0);
  await expect(page.getByTestId("section-settings")).not.toContainText("Set aside in this view");

  // One click on the second ready-made portfolio: one tensor request, five funds, no build.
  const before = api.loaded().length;
  const drawn = await settledPrint(page);
  await choosePreset(page, TSP_NAME);
  await expect.poll(() => api.loaded().length, { timeout: 30_000 }).toBe(before + 1);
  await expect.poll(() => param(page, "u")).toBe("tsp");
  expect(api.loaded()[before].body!.universe.funds.map((fund) => fund.id).sort()).toEqual(TSP_IDS);
  await expect.poll(async () => !samePrint(await canvasPrint(page), drawn), { timeout: 15_000 }).toBe(true);
  expect(api.tensorPosts().length, "builds requested for a ready-made portfolio").toBe(0);
});

test("DoD-06 no tangency point and no jargon in the default page", async ({ page }) => {
  await openApp(page);
  const banned = [/sharpe/i, /\bbets\b/i, /\bknee\b/i, /significant/i, /tangen/i];
  const hits = (text: string) => banned.filter((pattern) => pattern.test(text)).map(String);
  expect(hits(await pageWords(page)), "jargon on the first screen").toEqual([]);
  for (const id of ["funds", "trades", "stress", "settings"] as const) await openSection(page, id);
  expect(hits(await pageWords(page)), "jargon with every section open").toEqual([]);

  // The only marks on the chart: the selected point, the entered mix, the most diversified mix and the ceiling.
  const marks = await page.getByTestId("chart").evaluate((chart) => Array.from(chart.querySelectorAll("svg [data-testid]")).map((el) => el.getAttribute("data-testid")));
  // Beside them the overlay holds only the names of the frontier lines (text, one per line drawn).
  const names = marks.filter((id) => (id ?? "").startsWith("frontier-label-"));
  expect(names, "the primary frontier line is named").toEqual(["frontier-label-5y"]);
  expect(marks.filter((id) => !names.includes(id)).sort()).toEqual(["ceiling-line", "point-current", "point-div", "point-selected"]);
  const ids = await page.evaluate(() => Array.from(document.querySelectorAll("[data-testid]")).map((el) => el.getAttribute("data-testid") ?? ""));
  expect(ids.filter((id) => /tangen|sharpe|cml|capital/i.test(id))).toEqual([]);

  // Control: the scan does see the page's words. Details on shows the technical measure, off hides it again.
  await page.getByTestId("details-toggle").click();
  await expect(page.getByTestId("details-enb")).toBeVisible();
  expect(hits(await pageWords(page)), "the technical words behind the details toggle").toContain(String(/\bbets\b/i));
  await page.getByTestId("details-toggle").click();
  await expect(page.getByTestId("details-enb")).toHaveCount(0);
  expect(hits(await pageWords(page))).toEqual([]);
});

test("DoD-07 the heatmap is drawn from the theme's ramp under the frontier only", async ({ page }) => {
  const api = watchApi(page);
  await openApp(page);
  const tensor = await shownTensor(api);
  await settledPrint(page);
  const scales = await chartScales(page);
  const heat = ["--heat-0", "--heat-1", "--heat-2", "--heat-3", "--heat-4"];
  const colors = await themeColors(page, heat);
  const ramp = rgbBasis(heat.map((name) => colors[name]));

  const cells = pickCells(tensor, 20);
  const pixels = await canvasPixels(page, cells.map((cell) => ({ x: scales.x(tensor.frontier.x[cell.j]), y: scales.y(tensor.grid.y[cell.k]) })));
  expect(new Set(pixels.map((p) => p.slice(0, 3).join(","))).size, "distinct colours among 20 feasible cells").toBeGreaterThanOrEqual(3);
  pixels.forEach((pixel, i) => {
    const cell = cells[i];
    expect(pixel[3], `cell (${cell.j}, ${cell.k}) is painted`).toBe(255);
    // Spec 8: colour = ramp(1 - 0.8 * Z / enb_ref), brightest along the frontier; the Z range of the cell's neighbourhood is allowed.
    let near = Infinity;
    for (let step = 0; step <= 50; step++) near = Math.min(near, channelDistance(ramp(1 - 0.8 * Math.min(1, cell.qMin + ((cell.qMax - cell.qMin) * step) / 50)), pixel));
    expect(near, `cell (${cell.j}, ${cell.k}) ${hex(pixel)} is the ramp colour of its own diversification value`).toBeLessThanOrEqual(12);
  });

  // Above the frontier nothing is painted: the canvas is clear there, so the page background shows.
  const above: { x: number; y: number }[] = [];
  const NX = tensor.frontier.x.length;
  const top = scales.y(Math.max(...tensor.frontier_curve.mu)) - 6;
  for (const j of [2, Math.floor(NX / 5), Math.floor((2 * NX) / 5), Math.floor((3 * NX) / 5), Math.floor((4 * NX) / 5)]) {
    const yFront = Math.min(scales.y(tensor.frontier.y[j]), scales.y(tensor.frontier.y[Math.min(NX - 1, j + 1)]));
    above.push({ x: scales.x(tensor.frontier.x[j]), y: (yFront + Math.min(top, yFront - 24)) / 2 });
  }
  for (const pixel of await canvasPixels(page, above)) expect(pixel[3], "canvas alpha above the frontier").toBe(0);
});

test("DoD-08 risk slider: the ceiling moves, both readouts follow the frontier, the strip is the selected mix", async ({ page }) => {
  const api = watchApi(page);
  await openApp(page);
  const tensor = await shownTensor(api);
  const { sSafe, sMax } = sliderDomain(tensor);
  expect(sMax, "the slider has a real domain").toBeGreaterThan(sSafe);
  const scales = await chartScales(page);
  const slider = page.getByTestId("risk-slider");
  await nudge(slider, "Home");
  await expect.poll(() => riskPosition(page)).toBeCloseTo(sSafe, 3);

  let previous: { s: number; line: number; low: number; typical: number } | null = null;
  let movedTogether = 0;
  for (let step = 0; step < 5; step++) {
    if (step > 0) {
      const from = await riskPosition(page);
      await nudge(slider, "PageUp", 3);
      await expect.poll(() => riskPosition(page)).toBeGreaterThan(from + 1e-3);
    }
    const s = await riskPosition(page);
    const own = frontAt(tensor, s);
    const low = await shownPercent(page, "risk-readout-bad");
    const typical = await shownPercent(page, "risk-readout-typical");
    expect(Math.abs(low - own.low), `bad six months at s=${s}: page ${low}, own ${own.low.toFixed(2)}`).toBeLessThanOrEqual(0.1);
    expect(Math.abs(typical - own.typical), `typical six months at s=${s}: page ${typical}, own ${own.typical.toFixed(2)}`).toBeLessThanOrEqual(0.1);
    const line = (await rectOf(page.getByTestId("ceiling-line"))).cx;
    // The line is the risk ceiling X(s) on the chart's own axis.
    const ceiling = (1 - (s - Math.floor(s))) * tensor.frontier.x[Math.min(Math.floor(s), sMax - 1)] + (s - Math.floor(s)) * tensor.frontier.x[Math.min(Math.floor(s), sMax - 1) + 1];
    expect(Math.abs(line - scales.x(ceiling)), "the ceiling line sits at X(s)").toBeLessThanOrEqual(1.5);
    expect((await rectOf(page.getByTestId("point-selected"))).cx, "the selected point is never right of the line").toBeLessThanOrEqual(line + 1);
    if (previous) {
      expect(line, "the ceiling line moves right").toBeGreaterThan(previous.line);
      const ownBefore = frontAt(tensor, previous.s);
      if (Math.abs(own.low - ownBefore.low) >= 0.15) expect(low, "the bad-six-months readout changes with the move").not.toBe(previous.low);
      if (Math.abs(own.typical - ownBefore.typical) >= 0.15) expect(typical, "the typical-six-months readout changes with the move").not.toBe(previous.typical);
      if (low !== previous.low && typical !== previous.typical) movedTogether += 1;
    }
    previous = { s, line, low, typical };
  }
  expect(movedTogether, "moves on which both readouts changed together").toBeGreaterThanOrEqual(1);

  // Down the diversification slider the strip describes another mix than the readouts do.
  const column = walkableColumn(tensor);
  await openApp(page, `u=guide2017&lb=5y&r=${column}&d=0`);
  const strip = page.getByRole("region", { name: "Selected mix" });
  await expect(strip.getByText("Selected mix", { exact: true })).toBeVisible();
  const readouts = { low: await shownPercent(page, "risk-readout-bad"), typical: await shownPercent(page, "risk-readout-typical") };
  expect(await shownPercent(page, "range-low")).toBe(readouts.low);
  expect(await shownPercent(page, "range-typical")).toBe(readouts.typical);
  await pressDivEnd(page.getByTestId("div-slider"), "diversified");
  const bottom = range6mPct(mixStats(tensor, tensor.grid.w_div[column]).mu, mixStats(tensor, tensor.grid.w_div[column]).sigma);
  await expect.poll(() => shownPercent(page, "range-typical")).toBeCloseTo(bottom.typical, 0);
  expect(Math.abs((await shownPercent(page, "range-low")) - bottom.low)).toBeLessThanOrEqual(0.1);
  expect(Math.abs((await shownPercent(page, "range-typical")) - bottom.typical)).toBeLessThanOrEqual(0.1);
  expect([await shownPercent(page, "range-low"), await shownPercent(page, "range-typical")], "the strip differs from the readouts").not.toEqual([readouts.low, readouts.typical]);
  expect({ low: await shownPercent(page, "risk-readout-bad"), typical: await shownPercent(page, "risk-readout-typical") }, "the readouts still describe the frontier mix").toEqual(readouts);
});

test("DoD-09 diversification slider: suggested by default, moves the point down, ends on the frontier", async ({ page }) => {
  const api = watchApi(page);
  await openApp(page);
  const tensor = await shownTensor(api);
  await expect(page.getByTestId("div-reset"), "no reset link at the suggested position").toHaveCount(0);
  await expect.poll(() => param(page, "d")).toBe("auto");
  await expect(page.getByTestId("div-slider")).toHaveAttribute("aria-valuetext", "Suggested");

  const column = walkableColumn(tensor);
  await openApp(page, `u=guide2017&lb=5y&r=${column}&d=0&x=1`);
  const slider = page.getByTestId("div-slider");
  const point = page.getByTestId("point-selected");
  const line = async () => (await rectOf(page.getByTestId("ceiling-line"))).cx;
  const scales = await chartScales(page);

  // Top end: the point sits on the drawn frontier.
  await pressDivEnd(slider, "return");
  await expect(slider).toHaveAttribute("aria-valuetext", /^0 of 100/);
  const curve = tensor.frontier_curve.sigma.map((sigma, i) => ({ x: scales.x(sigma), y: scales.y(tensor.frontier_curve.mu[i]) }));
  const top = await rectOf(point);
  expect(distanceToLine({ x: top.cx, y: top.cy }, curve), "distance from the point to the drawn frontier at the top end").toBeLessThanOrEqual(1);
  const enbTop = (await shownMeasure(page)).enb;
  expect(near(enbTop, mixStats(tensor, tensor.frontier.w[column]).enb), `the measure at the top end (${enbTop}) is the frontier mix's own`).toBe(true);

  // Toward "More diversified": the point goes down, never right of the ceiling, and the reset link shows.
  let last = top.cy;
  const key = await towardDiversified(slider);
  for (let step = 0; step < 4; step++) {
    await nudge(slider, key, 8);
    const now = await rectOf(point);
    expect(now.cy, "the point moves down").toBeGreaterThanOrEqual(last);
    expect(now.cx, "the point is not right of the ceiling").toBeLessThanOrEqual((await line()) + 1);
    last = now.cy;
  }
  expect(last, "the point moved down over the walk").toBeGreaterThan(top.cy + 3);
  await expect(page.getByTestId("div-reset")).toBeVisible();

  // Bottom end: the most diversified mix of the column, at least as spread out as the top end.
  await pressDivEnd(slider, "diversified");
  await expect(slider).toHaveAttribute("aria-valuetext", /^100 of 100/);
  const enbBottom = (await shownMeasure(page)).enb;
  expect(near(enbBottom, mixStats(tensor, tensor.grid.w_div[column]).enb), `the measure at the bottom end (${enbBottom}) is the most diversified mix's own`).toBe(true);
  expect(enbBottom, "ENB at the bottom end against the top end").toBeGreaterThanOrEqual(enbTop);
  const bottom = await rectOf(point);
  const div = await rectOf(page.getByTestId("point-div"));
  expect(Math.hypot(bottom.cx - div.cx, bottom.cy - div.cy), "at the bottom end the point is the most diversified marker").toBeLessThanOrEqual(1);

  // Reset returns to the suggested position.
  await page.getByTestId("div-reset").click();
  await expect(page.getByTestId("div-reset")).toHaveCount(0);
  await expect.poll(() => param(page, "d")).toBe("auto");

  await test.step("a position with collapsed ladders disables the slider", async (step) => {
    const collapsed = collapsedPosition(tensor);
    step.skip(collapsed === null, "this tensor has no position where both neighbouring ladders are collapsed");
    await openApp(page, `u=guide2017&lb=5y&r=${collapsed}`);
    await expect(page.getByTestId("div-slider")).toHaveAttribute("aria-disabled", "true");
    await expect(page.getByText(DIV_DISABLED)).toBeVisible();
    const before = await rectOf(page.getByTestId("point-selected"));
    await pressDivEnd(page.getByTestId("div-slider"), "diversified", { force: true });
    await page.waitForTimeout(300);
    expect((await rectOf(page.getByTestId("point-selected"))).cy, "a press on the disabled slider moves nothing").toBe(before.cy);
    await expect.poll(() => param(page, "d")).toBe("auto");
  });
});

test("DoD-10 the diversification word is quiet and the measure shows only with details", async ({ page }) => {
  const api = watchApi(page);
  await openApp(page);
  const tensor = await shownTensor(api);
  const column = walkableColumn(tensor);
  const muted = (await themeColors(page, ["--muted"]))["--muted"];
  const seen = new Set<string>();
  for (const [d, weights] of [["0", tensor.frontier.w[column]], ["1", tensor.grid.w_div[column]]] as const) {
    await openApp(page, `u=guide2017&lb=5y&r=${column}&d=${d}`);
    const own = mixStats(tensor, weights);
    const word = page.getByTestId("div-word");
    await expect(word, `the word for the mix at column ${column}, d=${d}`).toHaveText(wordFor(own.enb / tensor.enb_ref));
    seen.add(await word.innerText());
    const style = await word.evaluate((el) => ({ size: parseFloat(getComputedStyle(el).fontSize), color: getComputedStyle(el).color }));
    expect(style.size, "font size of the word").toBeLessThanOrEqual(14);
    expect((style.color.match(/\d+(\.\d+)?/g) ?? []).slice(0, 3).map(Number), "the word is in the muted colour").toEqual(muted);
    // Nothing bigger than the range figures: the word is not a headline.
    const figure = await page.getByTestId("range-typical").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
    expect(style.size).toBeLessThan(figure);

    await expect(page.getByTestId("details-enb")).toHaveCount(0);
    expect(await pageWords(page), "no measure without details").not.toMatch(/independent bets|effective number/i);
    await page.getByTestId("details-toggle").click();
    const measure = await shownMeasure(page);
    expect(near(measure.enb, own.enb), `the measure shown with details (${measure.enb}) is this mix's own (${own.enb.toFixed(3)})`).toBe(true);
    expect(near(measure.best, tensor.enb_ref), "the highest value found on the menu").toBe(true);
  }
  for (const word of seen) expect(["Good", "Average", "Fair", "Poor"]).toContain(word);
});

test("DoD-11 TSP preset: five funds, 60% ceiling, no entered mix, L 2050 offered as a custom fund", async ({ page }) => {
  const api = watchApi(page);
  await openApp(page);
  await shownTensor(api);
  const before = api.loaded().length;
  await choosePreset(page, TSP_NAME);
  await expect.poll(() => api.loaded().length, { timeout: 30_000 }).toBe(before + 1);
  const tensor = api.loaded()[before].body as TensorLike;
  expect(tensor.universe.funds.map((fund) => fund.id).sort()).toEqual(TSP_IDS);
  expect(ruleMaxPct(5)).toBe(60);
  for (const max of tensor.bounds.max) expect(max).toBeCloseTo(0.6, 9);
  let worst = 0;
  for (const row of tensor.frontier.w) worst = Math.max(worst, ...row);
  expect(worst, "largest frontier weight of the TSP tensor").toBeLessThanOrEqual(0.6 + 1e-6);

  await openSection(page, "settings");
  for (const id of TSP_IDS) await expect(page.getByTestId(`cap-max-${id}`)).toHaveValue("60");
  await expect(page.getByTestId("section-settings")).toContainText("No single fund above 60% (menu of 5)");
  await expect(page.getByTestId("point-current")).toHaveCount(0);
  await expect(page.getByTestId("section-trades")).toHaveCount(0);
  await expect(page.getByTestId("chip-trades")).toHaveCount(0);
  expect(api.tensorPosts().length, "builds requested for a ready-made portfolio").toBe(0);

  await openSection(page, "funds");
  expect((await fundRowIds(page)).sort()).toEqual(TSP_IDS);
  await page.getByTestId("fund-add").fill("L 2050");
  await expect(page.getByRole("option").filter({ hasText: "TSP-L2050" })).toBeVisible();
  await expect(page.getByTestId("fund-row-TSP-L2050")).toHaveCount(0);
  // Offered means it can be added: the row appears, as a draft that asks to be recalculated.
  await page.getByRole("option").filter({ hasText: "TSP-L2050" }).click();
  await expect(page.getByTestId("fund-row-TSP-L2050")).toBeVisible();
  expect(api.tensorPosts().length, "nothing is built until the menu is used").toBe(0);
});

test("DoD-12 custom menu: four served funds build within 120 s; failure, unknown ticker and 31st fund", async ({ page, site }) => {
  test.setTimeout(900_000);
  await idleQueue(site);
  const symbols = ((await site.json("/api/symbols")) as Symbols).symbols;
  const catalog = symbols.map((symbol) => symbol.id);
  let four = ["VOO", "BND", "VNQ", "SGOV"];
  if (!four.every((id) => catalog.includes(id))) {
    // Otherwise the first four served symbols with six years of history, so the 5y view keeps all four.
    const cutoff = new Date(Date.now() - 6 * 366 * 86_400_000).toISOString().slice(0, 10);
    const seasoned = symbols.filter((symbol) => String(symbol.first_date).slice(0, 10) <= cutoff).map((symbol) => symbol.id);
    four = (seasoned.length >= 4 ? seasoned : catalog).slice(0, 4);
  }
  const hash = universeHash(four.map((id) => ({ id })));
  const api = watchApi(page);
  await openApp(page);

  await test.step("an unknown ticker gets an inline error and no request", async () => {
    expect(catalog, "ZZZZ is not a served symbol").not.toContain("ZZZZ");
    await choosePreset(page, /^Custom/);
    await expect(page.getByTestId("fund-add")).toBeVisible();
    const section = page.getByTestId("section-funds");
    const rows = (await fundRowIds(page)).length;
    const sent = api.tensorPosts().length;
    await expect(section).not.toContainText("ZZZZ");
    await typeFund(page, "ZZZZ");
    await expect(section.getByRole("alert")).toContainText("ZZZZ");
    await page.waitForTimeout(1_000);
    await expect(page.getByTestId("fund-row-ZZZZ")).toHaveCount(0);
    expect((await fundRowIds(page)).length).toBe(rows);
    expect(api.tensorPosts().length, "requests for an unknown ticker").toBe(sent);
  });

  await test.step("a failed build offers Retry, and Retry sends the same request", async () => {
    // The one mocked leg (spec 11 item 12): the service's failure answer, given once.
    let failed = 0;
    await page.route("**/api/tensors", async (route) => {
      if (route.request().method() !== "POST" || failed > 0) return route.fallback();
      failed += 1;
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ status: "failed", error: "build_failed", attempts: 1, retry: true, details: null }) });
    });
    const pair = four.slice(0, 2);
    const sent = api.tensorPosts().length;
    await page.goto(`/?f=${pair.join(",")}`);
    await expect(page.getByTestId("build-retry")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("building-notice")).toContainText("We couldn't compute this menu");
    await expect(page.getByTestId("building-notice")).toContainText("build_failed");
    await page.getByTestId("build-retry").click();
    await expect(page.getByTestId("build-retry")).toHaveCount(0, { timeout: 150_000 });
    await expect(page.getByTestId("point-selected")).toBeVisible({ timeout: 150_000 });
    const posts = api.tensorPosts().slice(sent);
    expect(posts.length).toBeGreaterThanOrEqual(2);
    expect(JSON.stringify(posts[1].body), "Retry repeats the request").toBe(JSON.stringify(posts[0].body));
    await page.unroute("**/api/tensors");
  });

  await test.step("a 31st fund is refused with a message and no request", async () => {
    await openApp(page);
    await choosePreset(page, /^Custom/);
    await expect(page.getByTestId("fund-add")).toBeVisible();
    const present = await fundRowIds(page);
    const spare = symbols.filter((symbol) => !present.includes(symbol.id) && !/\b30\b/.test(`${symbol.id} ${symbol.name}`)).map((symbol) => symbol.id);
    expect(present.length + spare.length, "served symbols available for a 31-fund menu").toBeGreaterThanOrEqual(31);
    const sent = api.tensorPosts().length;
    let next = 0;
    while ((await fundRowIds(page)).length < 30) {
      await typeFund(page, spare[next]);
      await expect(page.getByTestId(`fund-row-${spare[next]}`)).toBeVisible();
      next += 1;
    }
    await typeFund(page, spare[next]);
    await expect(page.getByTestId("section-funds").getByRole("alert")).toContainText("30");
    await expect(page.getByTestId(`fund-row-${spare[next]}`)).toHaveCount(0);
    expect((await fundRowIds(page)).length).toBe(30);
    expect(api.tensorPosts().length, "requests for a 31st fund").toBe(sent);
  });

  await test.step("four served funds: the notice, then the chart of exactly that menu", async () => {
    await openApp(page);
    const drawn = await settledPrint(page);
    await choosePreset(page, /^Custom/);
    await expect(page.getByTestId("fund-add")).toBeVisible();
    await setMenu(page, four);
    const sent = api.tensorPosts().length;
    await page.waitForTimeout(500);
    expect(api.tensorPosts().length, "builds requested before Recalculate with these funds").toBe(sent);
    await expect(page.getByTestId("use-menu")).toHaveText("Recalculate with these funds");
    const mine = () => api.loaded().filter((entry) => entry.path.includes(`/${hash}/`));
    const notice = page.getByTestId("building-notice");
    const started = Date.now();
    await page.getByTestId("use-menu").click();
    let sawNotice = false;
    let cached = false;
    while (Date.now() - started < 120_000) {
      if (await notice.isVisible()) {
        sawNotice = true;
        break;
      }
      if (mine().length > 0) {
        cached = mine()[0].at - started <= 2_000;
        break;
      }
      await page.waitForTimeout(50);
    }
    expect(sawNotice || cached, "the building notice shows, or a cached key answers within 2 s").toBe(true);
    if (sawNotice) await expect(notice).toContainText("Give us a moment");
    const left = () => Math.max(1_000, 120_000 - (Date.now() - started));
    await expect.poll(() => mine().length > 0, { timeout: left(), message: "the build resolves within 120 s" }).toBe(true);
    await expect.poll(async () => !samePrint(await canvasPrint(page), drawn), { timeout: left() }).toBe(true);
    await expect(notice).toBeHidden({ timeout: left() });
    const tensor = mine()[0].body as TensorLike;
    expect(tensor.universe.funds.map((fund) => fund.id).sort()).toEqual([...four].sort());
    expect(tensor.universe.hash).toBe(hash);
    const posts = api.tensorPosts().slice(sent);
    expect(posts.length, "build requests for the menu").toBeGreaterThanOrEqual(1);
    for (const post of posts) expect(universeHash(post.body.funds)).toBe(hash);
    await expect.poll(() => param(page, "f")).not.toBeNull();
    expect(((await param(page, "f")) ?? "").split(",").map((item) => item.split(":")[0]).sort()).toEqual([...four].sort());
  });
});

test("DoD-13 funds and trades: dollar and share changes, the 100% rule, tickers only", async ({ page, site }) => {
  test.setTimeout(300_000);
  const api = watchApi(page);
  await openApp(page);
  const tensor = await shownTensor(api);
  // A known selected mix: the frontier mix of one column, whose weights are in the tensor.
  const column = walkableColumn(tensor);
  await openApp(page, `u=guide2017&lb=5y&r=${column}&d=0`);
  const selected = tensor.frontier.w[column];
  const funds = tensor.universe.funds;
  const held = guideHoldings().filter((h) => h.amount > 0 && funds.some((fund) => fund.id === h.id));
  const value = held.reduce((acc, h) => acc + h.amount, 0);

  const trades = await openSection(page, "trades");
  const rowOf = (id: string) => trades.getByRole("listitem").filter({ has: page.getByText(id, { exact: true }) });
  const figures = (cells: string[]) => cells.map((text) => text.replace(/[−–]/g, "-").replace(/[,$+]/g, "").trim());
  // Reads a trade row: now %, selected %, change in points, then money and shares where the unit has them.
  const read = async (id: string) => {
    const cells = figures(await rowOf(id).locator("span").allTextContents());
    return { now: parseFloat(cells[1]), selected: parseFloat(cells[2]), change: parseFloat(cells[3]), usd: cells[4] === undefined ? null : Number(cells[4]), shares: cells[5] === undefined ? null : Number(cells[5]) };
  };

  await test.step("dollar mode: every held fund with now, selected, change and dollars; a turnover total", async () => {
    for (const heading of ["Now", "Selected", "Change"]) await expect(trades.getByText(heading, { exact: true })).toHaveCount(1);
    for (const holding of held) {
      await expect(rowOf(holding.id), `a trade row for ${holding.id}`).toHaveCount(1);
      const row = await read(holding.id);
      expect(Math.abs(row.now - (100 * holding.amount) / value), `${holding.id}: now % is its share of the entered dollars`).toBeLessThanOrEqual(0.06);
      const weight = selected[funds.findIndex((fund) => fund.id === holding.id)];
      expect(Math.abs(row.selected - 100 * weight), `${holding.id}: selected % is the selected mix's own weight`).toBeLessThanOrEqual(0.06);
      expect(Math.abs(row.change - (100 * weight - (100 * holding.amount) / value)), `${holding.id}: change = selected − now`).toBeLessThanOrEqual(0.06);
      expect(row.usd, `${holding.id}: a dollar change`).not.toBeNull();
      expect(Math.abs((row.usd as number) - (row.change / 100) * value), `${holding.id}: dollars = change × portfolio value`).toBeLessThanOrEqual(0.0005 * value + 1);
    }
    await expect(rowOf(held[0].id).locator("span").nth(4), "the dollar change is on screen").toBeVisible();
    const all = (await trades.getByRole("listitem").evaluateAll((rows) => rows.map((row) => Array.from(row.querySelectorAll("span")).map((span) => span.textContent ?? "")))).map(figures);
    const buys = all.reduce((acc, cells) => acc + Math.max(parseFloat(cells[3]), 0), 0);
    const sells = all.reduce((acc, cells) => acc + Math.max(-parseFloat(cells[3]), 0), 0);
    const total = parsePercent(await trades.getByText("Total moved", { exact: true }).locator("xpath=..").innerText(), "total moved");
    expect(total, "something moves between the entered and the selected mix").toBeGreaterThan(0);
    expect(Math.abs(total - buys), "Total moved is the sum of the buys").toBeLessThanOrEqual(0.05 * all.length + 0.1);
    expect(Math.abs(buys - sells), "buys and sells balance").toBeLessThanOrEqual(0.1 * all.length);
    // Every fund the selected mix holds is listed, held before or not.
    for (const [index, fund] of funds.entries()) if (selected[index] > 0.001) await expect(rowOf(fund.id), `a trade row for ${fund.id}`).toHaveCount(1);
    const own = funds.reduce((acc, fund, index) => acc + Math.max(selected[index] - (held.find((h) => h.id === fund.id)?.amount ?? 0) / value, 0), 0);
    expect(Math.abs(total - 100 * own), "Total moved is the one-way turnover between the two mixes").toBeLessThanOrEqual(0.06);
  });

  await test.step("share mode: share and dollar changes use the tensor's last close", async () => {
    await openSection(page, "funds");
    await page.getByTestId("unit-toggle").getByRole("radio", { name: "Shares", exact: true }).click();
    await page.getByTestId("fund-row-VTI").locator("input").fill("100");
    await page.getByTestId("fund-row-BND").locator("input").fill("250");
    await expect.poll(() => param(page, "unit")).toBe("shares");
    const close = new Map(funds.map((fund) => [fund.id, fund.last_close ?? null]));
    let worth = 0;
    for (const fund of funds) {
      const shown = await page.getByTestId(`fund-row-${fund.id}`).locator("input").inputValue();
      const shares = shown === "" ? 0 : Number(shown);
      if (shares > 0) expect(close.get(fund.id), `${fund.id} has a last close in the tensor`).toBeGreaterThan(0);
      worth += shares * (close.get(fund.id) ?? 0);
    }
    for (const [id, shares] of [["VTI", 100], ["BND", 250]] as const) {
      const row = await read(id);
      const price = close.get(id) as number;
      expect(Math.abs(row.now - (100 * shares * price) / worth), `${id}: now % = shares × last close ÷ value`).toBeLessThanOrEqual(0.06);
      expect(Math.abs(row.selected - 100 * selected[funds.findIndex((fund) => fund.id === id)]), `${id}: selected % is unchanged by the unit`).toBeLessThanOrEqual(0.06);
      expect(Math.abs((row.usd as number) - (row.change / 100) * worth), `${id}: dollars = change × value`).toBeLessThanOrEqual(0.0005 * worth + 1);
      expect(row.shares, `${id}: a change in shares`).not.toBeNull();
      expect(Math.abs((row.shares as number) - (row.usd as number) / price), `${id}: shares = dollars ÷ last close`).toBeLessThanOrEqual(0.5 + 1 / price);
    }
    expect(api.tensorPosts().length, "amounts never trigger a build").toBe(0);
  });

  await test.step("percent mode: the running total gates the mix, with nothing to press; tickers only hides Trades", async () => {
    const catalog = ((await site.json("/api/symbols")) as Symbols).symbols.map((symbol) => symbol.id);
    const pair = ["SGOV", "VTIP"].every((id) => catalog.includes(id)) ? ["SGOV", "VTIP"] : ["VTI", "BND"];
    await page.goto(`/?f=${pair[0]}:60,${pair[1]}:32&unit=pct`);
    await expect(page.getByTestId("point-selected")).toBeVisible({ timeout: 150_000 });
    await openSection(page, "funds");
    await expect(page.getByTestId("funds-total")).toHaveText("Adds up to 92%: 8% to go");
    // The fund list is the one plotted, so there is no recalculate button: amounts apply as typed.
    await expect(page.getByTestId("use-menu")).toHaveCount(0);
    await expect(page.getByTestId("funds-hint")).toHaveText("Amounts apply as you type.");
    await expect(page.getByTestId(`mix-entered-${pair[1]}`)).toHaveText("");
    await expect(page.getByTestId("point-current")).toHaveCount(0);
    await expect(page.getByTestId("chip-trades")).toHaveCount(0);
    await page.getByTestId(`fund-row-${pair[1]}`).locator("input").fill("40");
    await expect(page.getByTestId("funds-total")).toHaveText("Adds up to 100%");
    await expect(page.getByTestId("use-menu")).toHaveCount(0);
    await expect(page.getByTestId(`mix-entered-${pair[1]}`)).toHaveText("40.0%");
    await expect(page.getByTestId(`mix-selected-${pair[1]}`)).toHaveText(/^\d+\.\d%$/);
    await expect(page.getByTestId("point-current")).toBeVisible();
    await expect(page.getByTestId("chip-trades")).toBeVisible();
    for (const id of pair) await page.getByTestId(`fund-row-${id}`).locator("input").fill("");
    await expect(page.getByTestId("funds-total")).toHaveText("No amounts entered: tickers only.");
    await expect(page.getByTestId("section-trades")).toHaveCount(0);
    await expect(page.getByTestId("chip-trades")).toHaveCount(0);
    await expect(page.getByTestId("point-current")).toHaveCount(0);
  });
});

test("DoD-14 caps: a 10% ceiling on VTI holds in every mix; bad limits are refused; reset restores the rule", async ({ page, site }) => {
  test.setTimeout(420_000);
  await idleQueue(site);
  const api = watchApi(page);
  await openApp(page);
  const base = await shownTensor(api);
  const rule = Number(ruleMaxPct(base.universe.funds.length).toFixed(2));
  await openSection(page, "settings");
  const max = page.getByTestId("cap-max-VTI");
  const min = page.getByTestId("cap-min-VTI");
  await expect(max).toHaveValue(String(rule));
  expect(base.bounds.max[base.universe.funds.findIndex((fund) => fund.id === "VTI")], "before the edit VTI's ceiling is the rule's").toBeCloseTo(rule / 100, 9);

  await max.fill("10");
  await max.blur();
  await expect.poll(() => api.tensorPosts().length, { timeout: 15_000 }).toBe(1);
  const post = api.tensorPosts()[0];
  const requested = (post.body.funds).find((fund) => fund.id === "VTI");
  expect(requested?.max, "the ceiling sent for VTI").toBeCloseTo(0.1, 9);
  const hash = universeHash(post.body.funds);
  const built = () => api.loaded().find((entry) => entry.path.includes(`/${hash}/`));
  await expect.poll(() => built() !== undefined, { timeout: 150_000, message: "the rebuild resolves" }).toBe(true);
  const tensor = built()!.body as TensorLike;
  const vti = tensor.universe.funds.findIndex((fund) => fund.id === "VTI");
  expect(tensor.universe.hash).toBe(hash);
  expect(hash, "the limit makes a new key").not.toBe(base.universe.hash);
  expect(tensor.bounds.requested[vti].max).toBeCloseTo(0.1, 9);
  expect(tensor.bounds.max[vti]).toBeLessThanOrEqual(0.1 + 1e-6);
  let worst = 0;
  let mixes = 0;
  for (const row of tensor.frontier.w) {
    worst = Math.max(worst, row[vti]);
    mixes += 1;
  }
  for (const columnCells of tensor.grid.w) {
    for (const cell of columnCells) {
      if (cell === null) continue;
      worst = Math.max(worst, cell[vti]);
      mixes += 1;
    }
  }
  expect(mixes, "mixes checked").toBeGreaterThan(tensor.frontier.x.length);
  expect(worst, "largest VTI weight in any mix of the rebuilt tensor").toBeLessThanOrEqual(0.1 + 1e-6);
  await expect.poll(() => param(page, "c")).toBe("VTI::10");

  // A minimum above the maximum: an inline error, and nothing is sent.
  await min.fill("20");
  await min.blur();
  await expect(page.getByTestId("section-settings").getByRole("alert")).toContainText("The minimum (20%) is above the maximum (10%).");
  await expect(min).toHaveAttribute("aria-invalid", "true");
  await page.waitForTimeout(1_500);
  expect(api.tensorPosts().length, "requests for an invalid limit").toBe(1);
  expect(await param(page, "c")).toBe("VTI::10");

  // Reset: the rule's values are back in the table and in the tensor the page shows.
  await page.getByTestId("caps-reset").click();
  await expect(max).toHaveValue(String(rule));
  await expect(min).toHaveValue("0");
  await expect(page.getByTestId("section-settings").getByRole("alert")).toHaveCount(0);
  await expect.poll(() => param(page, "c")).toBeNull();
  await expect.poll(() => api.latest()?.bounds.requested.every((bound) => bound.min === null && bound.max === null) ?? false, { timeout: 60_000 }).toBe(true);
});

test("DoD-15 lookbacks: 10 years redraws and lists the computed exclusions; a ghost curve toggles", async ({ page, site }) => {
  test.setTimeout(420_000);
  const presets = (await site.json("/api/presets")) as Presets;
  const preset = presets.presets.find((item) => item.id === "guide2017")!;
  const fundIds = preset.funds.map((fund) => fund.id);
  const firstDate = new Map(((await site.json("/api/symbols")) as Symbols).symbols.map((symbol) => [symbol.id, String(symbol.first_date).slice(0, 10)]));
  // Spec 4.2 for the 10y window: 2,520 sessions back from the generation date, and a fund counts
  // when its history starts within the first tenth (252 sessions) of the window. Not served: out.
  const window = sessionWindow(presets.asof, 2520, 252);
  expect(window.isSession, "the generation date is an XNYS session").toBe(true);
  const expected = fundIds.filter((id) => !firstDate.has(id) || (firstDate.get(id) as string) > window.threshold).sort();

  const api = watchApi(page);
  await openApp(page);
  await shownTensor(api, "5y");
  const drawn5y = await settledPrint(page);
  const settings = await openSection(page, "settings");
  await page.getByTestId("lookback-10y").check({ force: true });
  const tensor = await shownTensor(api, "10y");
  await expect.poll(() => param(page, "lb")).toBe("10y");
  expect(api.gets.filter((item) => item === preset.lookbacks["10y"].url).length, "requests for the preset's 10y tensor").toBe(1);
  await expect.poll(async () => !samePrint(await canvasPrint(page), drawn5y), { timeout: 15_000, message: "the chart is redrawn for the 10y tensor" }).toBe(true);
  expect((tensor.universe.excluded ?? []).map((item) => item.id).sort(), "the tensor's exclusions").toEqual(expected);
  const notes = settings.getByTestId("excluded-note");
  await expect(notes).toHaveCount(expected.length);
  const listed = (await notes.allInnerTexts()).map((text) => text.split(":")[0].trim()).sort();
  expect(listed, "the Settings exclusion list").toEqual(expected);
  for (const id of expected.filter((item) => firstDate.has(item))) {
    await expect(notes.filter({ hasText: id })).toContainText(/history starts \d{4}-\d{2}-\d{2}, not enough for the .+ view/);
  }

  await test.step("a fund too young for the 10-year view is set aside with its reason, and the rest carries on", async () => {
    // Three served funds, one of which started after the window's first tenth (spec 4.2, 5.6).
    const served = [...firstDate.entries()];
    const young = served.find(([id]) => id === "SGOV" && (firstDate.get(id) as string) > window.threshold) ?? served.find(([, first]) => first > window.threshold && first < sessionWindow(presets.asof, 400).start);
    expect(young, "a served fund that started inside the last ten years, at least 400 sessions ago").toBeTruthy();
    const old = ["BND", "VTI", "AGG", "VNQ"].filter((id) => firstDate.has(id) && (firstDate.get(id) as string) <= window.start).slice(0, 2);
    expect(old.length, "two served funds older than the 10-year window").toBe(2);
    const [youngId, youngFirst] = young as [string, string];
    await page.goto(`/?f=${[...old, youngId].join(",")}&lb=10y`);
    await expect(page.getByTestId("point-selected")).toBeVisible({ timeout: 150_000 });
    const custom = await shownTensor(api, "10y");
    expect(custom.universe.funds.map((fund) => fund.id).sort()).toEqual([...old].sort());
    expect((custom.universe.excluded ?? []).map((item) => item.id)).toEqual([youngId]);
    // The engine dates the reason by the fund's first return, the session after its first price.
    const reason = /history starts (\d{4}-\d{2}-\d{2}), not enough for the .+ view/;
    const inSettings = (await openSection(page, "settings")).getByTestId("excluded-note");
    await expect(inSettings).toHaveCount(1);
    const note = await inSettings.innerText();
    expect(note.startsWith(`${youngId}: `) && reason.test(note), `the Settings note for ${youngId}: ${note}`).toBe(true);
    const dated = reason.exec(note)![1];
    expect(dated >= youngFirst && dated <= new Date(Date.parse(`${youngFirst}T00:00:00Z`) + 7 * 86_400_000).toISOString().slice(0, 10), `the date in the note (${dated}) is the fund's start (${youngFirst})`).toBe(true);
    const funds = await openSection(page, "funds");
    await expect(funds.getByTestId(`fund-row-${youngId}`).getByTestId("excluded-note")).toContainText(/history starts \d{4}-\d{2}-\d{2}, not enough for the .+ view: not used/);
    for (const id of old) await expect(funds.getByTestId(`fund-row-${id}`).getByTestId("excluded-note")).toHaveCount(0);
    await openApp(page);
    await openSection(page, "settings");
  });

  // A ghost curve: the count and the canvas change, and both come back.
  const chart = page.getByTestId("chart");
  await expect(chart).toHaveAttribute("data-ghost-count", "0", { timeout: 15_000 });
  const off = await settledPrint(page);
  await page.getByTestId("ghost-1y").check({ force: true });
  await expect(chart).toHaveAttribute("data-ghost-count", "1", { timeout: 30_000 });
  await expect.poll(async () => !samePrint(await canvasPrint(page), off), { timeout: 15_000 }).toBe(true);
  await expect.poll(() => param(page, "g")).toBe("1y");
  await page.getByTestId("ghost-1y").uncheck({ force: true });
  await expect(chart).toHaveAttribute("data-ghost-count", "0");
  await expect.poll(async () => samePrint(await canvasPrint(page), off), { timeout: 15_000 }).toBe(true);
});

test("DoD-16 stress cards: three windows with the mix's own numbers and coverage notes", async ({ page }) => {
  test.setTimeout(240_000);
  const api = watchApi(page);
  await openApp(page);
  const tensor = await shownTensor(api);
  const column = walkableColumn(tensor);
  await openApp(page, `u=guide2017&lb=5y&r=${column}&d=0`);
  const weights = tensor.frontier.w[column];
  const section = await openSection(page, "stress");
  await expect(section.locator('[data-testid^="stress-"]')).toHaveCount(3);
  for (const id of STRESS_IDS) {
    const card = page.getByTestId(`stress-${id}`);
    const own = stressOf(weights, tensor.stress[id].r);
    const text = (await card.innerText()).replace(/\s+/g, " ");
    if (own.value === null) {
      expect(text, `${id}: under half of the mix existed`).toContain(STRESS_SENTINEL);
      continue;
    }
    expect(Math.abs(parsePercent(/What this mix did: ([^()]+)/.exec(text)?.[1] ?? "", id) - 100 * own.value), `${id}: the selected mix's return`).toBeLessThanOrEqual(0.1);
    expect(text, `${id}: the card is headed by its window`).toContain(tensor.stress[id].label);
    expect(text, `${id}: the number is the selected mix's`).toMatch(/What this mix did: [^()]+\(Selected mix\)/);
    const gap = `${own.missing} of ${weights.length} funds (${((1 - own.covered) * 100).toFixed(1)}% of the mix) didn't exist yet; result is for the rest.`;
    if (1 - own.covered >= 0.0005) expect(text, `${id}: coverage note`).toContain(gap);
    else expect(text, `${id}: no coverage note for a mix that fully existed`).not.toContain("didn't exist yet");
  }
  expect(STRESS_IDS.some((id) => stressOf(weights, tensor.stress[id].r).value !== null), "a card with a number").toBe(true);

  // A mix of two funds that both started after 2008: no number is made up for that window.
  await page.goto("/?f=SGOV,VTIP");
  await expect(page.getByTestId("point-selected")).toBeVisible({ timeout: 150_000 });
  const custom = await shownTensor(api);
  expect(custom.universe.funds.map((fund) => fund.id).sort()).toEqual(["SGOV", "VTIP"]);
  expect(custom.stress.gfc2008.r, "neither fund has a 2008 return").toEqual([null, null]);
  await openSection(page, "stress");
  const card = page.getByTestId("stress-gfc2008");
  await expect(card).toContainText(STRESS_SENTINEL);
  expect(await card.innerText()).not.toMatch(/\d%/);
});

test("DoD-17 themes: four looks, the table's backgrounds, a repainted chart, remembered; the address wins", async ({ page }, testInfo) => {
  await openApp(page);
  const html = page.locator("html");
  const next = async () => {
    const control = page.getByTestId("theme-switch");
    if ((await control.evaluate((el) => el.tagName)) === "BUTTON") return control.click();
    const radios = control.getByRole("radio");
    const checked = await radios.evaluateAll((items) => items.findIndex((item) => item.getAttribute("aria-checked") === "true"));
    await radios.nth((checked + 1) % (await radios.count())).click();
  };
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  const prints: number[][] = [];
  for (const theme of ["ks-dark", "light", "hud", "grid"]) {
    if (theme !== "ks-dark") await next();
    await expect(html).toHaveAttribute("data-theme", theme);
    expect((await html.evaluate((el) => getComputedStyle(el).getPropertyValue("--bg"))).trim().toUpperCase(), `--bg of ${theme}`).toBe(THEME_BG[theme]);
    expect(hex((await themeColors(page, ["--bg"]))["--bg"]), `the colour --bg resolves to in ${theme}`).toBe(THEME_BG[theme]);
    const print = await settledPrint(page);
    for (const earlier of prints) expect(samePrint(print, earlier), `the chart is repainted for ${theme}`).toBe(false);
    prints.push(print);
    await expect.poll(() => param(page, "t")).toBe(theme);
    await page.screenshot({ path: path.join(ARTIFACTS, `${testInfo.project.name}-${theme}.png`) });
  }
  expect(await page.evaluate(() => localStorage.getItem("ps.theme"))).toBe("grid");

  // Remembered: a fresh visit without a theme in the address opens in the last choice.
  await openApp(page);
  await expect(html).toHaveAttribute("data-theme", "grid");
  // The address wins over the stored choice, without overwriting it.
  await openApp(page, "t=light");
  await expect(html).toHaveAttribute("data-theme", "light");
  expect(await page.evaluate(() => localStorage.getItem("ps.theme"))).toBe("grid");
  await next();
  await expect(html).toHaveAttribute("data-theme", "hud");
  // A shared link with t=hud opens the red and gold HUD, whatever is stored; t=grid the cyan Grid.
  await page.evaluate(() => localStorage.setItem("ps.theme", "light"));
  await openApp(page, "t=hud");
  await expect(html).toHaveAttribute("data-theme", "hud");
  expect(hex((await themeColors(page, ["--accent"]))["--accent"]), "the HUD accent is red").toBe("#D63A18");
  await openApp(page, "t=grid");
  await expect(html).toHaveAttribute("data-theme", "grid");
  expect(hex((await themeColors(page, ["--accent"]))["--accent"]), "the Grid accent is cyan").toBe("#35C9E8");
});

test("DoD-18 the HUD look names no film, character or trademark, in the sources or as served", async ({ page, site }) => {
  // The needle list is kept in one place only, the frozen A-PS-49 test; it is read from there at
  // run time and never written anywhere else.
  const gate = path.join("assertions", "2026-10-13-portfoliosight-demo-design", "tests", "test_a_ps_49_themes_tokens_canvas.py");
  const scan = python(["-m", "pytest", "-q", "--noconftest", "-p", "no:cacheprovider", gate, "-k", "static_no_film_reference", "--color=no"], { env: { PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1" }, timeoutMs: 180_000 });
  expect(scan.status, `the static scan of the sources and docs: ${scan.stdout.slice(-600)}`).toBe(0);
  expect(scan.stdout, "the scan ran").toMatch(/(^|\D)1 passed/);

  const loader = [
    "import importlib.util, json, sys",
    "spec = importlib.util.spec_from_file_location('gate49', sys.argv[1])",
    "module = importlib.util.module_from_spec(spec)",
    "spec.loader.exec_module(module)",
    "print(json.dumps(list(module._NEEDLES)))",
  ].join("\n");
  const listed = python(["-c", loader, gate]);
  expect(listed.status, "reading the needle list").toBe(0);
  const needles = new RegExp((JSON.parse(listed.stdout) as string[]).join("|"), "i");
  expect("the HUD theme draws corner brackets").not.toMatch(needles);

  await openApp(page, "t=hud");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "hud");
  for (const id of ["funds", "stress", "settings"] as const) await openSection(page, id);
  const dom = await page.evaluate(() => document.documentElement.outerHTML);
  expect(dom, "the word HUD is what the look is called").toMatch(/\bHUD\b/);
  expect(needles.test(dom), "a film, character or trademark reference in the served page").toBe(false);
  const assets = await page.evaluate(() => Array.from(document.querySelectorAll("script[src], link[rel=stylesheet][href]")).map((el) => el.getAttribute("src") ?? el.getAttribute("href") ?? ""));
  expect(assets.length, "script and style files of the page").toBeGreaterThanOrEqual(2);
  for (const asset of assets) {
    const response = await site.get(new URL(asset, site.origin).pathname);
    expect(response.status(), `GET ${asset}`).toBe(200);
    expect(needles.test(await response.text()), `a film, character or trademark reference in ${asset}`).toBe(false);
  }
});

test("DoD-19 the address describes the view: a fresh browser reproduces it, and Copy link copies it", async ({ page, browser, context, baseURL, site }) => {
  test.setTimeout(180_000);
  const presets = (await site.json("/api/presets")) as Presets;
  const other = presets.presets.find((item) => item.id !== "guide2017")!;
  const api = watchApi(page);
  await openApp(page);
  await shownTensor(api);

  await choosePreset(page, other.name);
  await expect.poll(() => param(page, "u")).toBe(other.id);
  await openSection(page, "settings");
  await page.getByTestId("lookback-3y").check({ force: true });
  await shownTensor(api, "3y");
  await expect.poll(() => param(page, "lb")).toBe("3y");
  const risk = page.getByTestId("risk-slider");
  const from = await riskPosition(page);
  await nudge(risk, "PageUp", 2);
  await nudge(risk, "PageDown", 5);
  await expect.poll(() => riskPosition(page)).not.toBe(from);
  const div = page.getByTestId("div-slider");
  if ((await div.getAttribute("aria-disabled")) !== "true") await nudge(div, await towardDiversified(div), 6);
  const control = page.getByTestId("theme-switch");
  if ((await control.evaluate((el) => el.tagName)) === "BUTTON") await control.click();
  else await control.getByRole("radio", { name: "Light" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  await expect.poll(async () => ["u", "lb", "r", "d", "t"].every((key) => new URL(page.url()).searchParams.has(key)), { message: "the address carries u, lb, r, d and t" }).toBe(true);
  await expect.poll(async () => Number(await param(page, "r"))).toBeCloseTo(await riskPosition(page), 3);
  expect(await param(page, "t")).toBe("light");
  const address = page.url();
  const view = { bad: await page.getByTestId("risk-readout-bad").innerText(), word: await page.getByTestId("div-word").innerText(), low: await page.getByTestId("range-low").innerText() };

  // A browser that has never seen the site, opened on that address alone.
  const fresh = await browser.newContext({ viewport: page.viewportSize() ?? undefined });
  const foreign = await gateContext(fresh, baseURL as string);
  const copy = await fresh.newPage();
  await copy.goto(address);
  await expect(copy.getByTestId("point-selected")).toBeVisible({ timeout: 30_000 });
  await expect(copy.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(copy.getByTestId("risk-readout-bad")).toHaveText(view.bad);
  await expect(copy.getByTestId("div-word")).toHaveText(view.word);
  await expect(copy.getByTestId("range-low")).toHaveText(view.low);
  await expect(copy.getByTestId("preset-menu")).toHaveAttribute("aria-label", `Portfolio: ${other.name}`);
  await copy.getByTestId("chip-settings").click();
  await expect(copy.getByTestId("lookback-3y")).toBeChecked();
  expect([...foreign]).toEqual([]);
  await fresh.close();

  // Copy link puts exactly that address on the clipboard.
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.evaluate(() => navigator.clipboard.writeText("not the link"));
  await page.getByTestId("share-open").click();
  await expect(page.getByTestId("share-link")).toHaveValue(address);
  await page.getByTestId("share-copy").click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(address);
});

test("DoD-20 the disclaimer, the family links and the not-advice line are on the page", async ({ page }) => {
  await openApp(page);
  const disclaimer = page.getByTestId("disclaimer");
  await disclaimer.scrollIntoViewIfNeeded();
  await expect(disclaimer).toBeVisible();
  await expect(disclaimer).toHaveText(DISCLAIMER);
  const style = await disclaimer.evaluate((el) => ({ size: parseFloat(getComputedStyle(el).fontSize), opacity: Number(getComputedStyle(el).opacity), height: el.getBoundingClientRect().height }));
  expect(style.size, "readable disclaimer type").toBeGreaterThanOrEqual(11);
  expect(style.opacity).toBe(1);
  expect(style.height).toBeGreaterThan(20);
  // Not inside a collapsible section: it shows with every section closed.
  for (const id of ["funds", "stress", "settings"]) await expect(page.getByTestId(`section-${id}`)).toHaveAttribute("aria-expanded", "false");
  expect(await disclaimer.evaluate((el) => el.closest("[aria-expanded]") === null)).toBe(true);

  const cta = page.getByTestId("footer-cta");
  await expect(cta).toBeVisible();
  await expect(cta).toContainText("More from the AutomateIntelligence family");
  expect(await cta.getByRole("link").evaluateAll((links) => links.map((link) => link.getAttribute("href")))).toEqual(FAMILY);
  for (const href of FAMILY) await expect(cta).toContainText(href);

  await page.evaluate(() => window.scrollTo(0, 0));
  const advice = page.getByText("Historical math, not investment advice.", { exact: true });
  await expect(advice).toBeVisible();
  const strip = await rectOf(page.getByRole("region", { name: "Selected mix" }));
  expect((await rectOf(advice)).top, "the line sits under the result strip").toBeGreaterThanOrEqual(strip.bottom - 1);
});

test("DoD-21 presets and tensors come from R2, and a build request for the default preset is the same tensor", async ({ site }) => {
  const answer = await site.get("/api/presets");
  expect(answer.status()).toBe(200);
  expect(answer.headers()["x-ps-source"], "presets are read from R2").toBe("r2");
  const presets = (await answer.json()) as Presets;
  expect(presets.generation).toMatch(/^\d{4}-\d{2}-\d{2}-[0-9.]+$/);
  expect(presets.presets.map((preset) => preset.id).sort()).toEqual(["guide2017", "tsp"]);
  expect(presets.presets.find((preset) => preset.id === "guide2017")!.name).toBe(GUIDE_NAME);
  expect(presets.presets.find((preset) => preset.id === "tsp")!.name).toBe(TSP_NAME);
  for (const preset of presets.presets) {
    expect(Object.keys(preset.lookbacks).sort(), `${preset.id}: lookbacks`).toEqual([...LOOKBACKS].sort());
    for (const lookback of LOOKBACKS) {
      expect(preset.lookbacks[lookback].status, `${preset.id}/${lookback}`).toBe("ready");
      expect(preset.lookbacks[lookback].url).toBe(`/api/tensors/${presets.generation}/${preset.hash}/${lookback}`);
    }
  }

  const guide = presets.presets.find((preset) => preset.id === "guide2017")!;
  expect(guide.funds.length).toBe(23);
  const stored = await site.get(guide.lookbacks["5y"].url);
  expect(stored.status()).toBe(200);
  expect(stored.headers()["cache-control"]).toBe("public, max-age=86400, immutable");
  expect(stored.headers()["x-ps-source"], "the tensor is read from R2").toBe("r2");
  const body = await stored.text();
  const tensor = JSON.parse(body) as TensorLike;
  expect(tensor.universe.hash).toBe(guide.hash);
  expect(tensor.generation).toBe(presets.generation);
  expect(guide.hash, "the preset's key is the hash of its 23 funds with default limits").toBe(universeHash(guide.funds.map((fund) => ({ id: fund.id }))));

  // The contract of spec 7, checked with the schema the engine writes against.
  const dir = mkTemp("ps-smoke-21-");
  try {
    fs.writeFileSync(path.join(dir, "tensor.json"), body);
    const check = python(["-c", "import json, sys, jsonschema; jsonschema.validate(json.load(open(sys.argv[1])), json.load(open('portfoliosight/engine/tensor.schema.json')))", path.join(dir, "tensor.json")]);
    expect(check.status, `the tensor validates against tensor.schema.json: ${check.stderr.slice(-600)}`).toBe(0);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }

  const posted = await site.post("/api/tensors", { funds: guide.funds.map((fund) => ({ id: fund.id, min: null, max: null })), lookback: "5y" });
  expect(posted.status(), "a build request for a stored key answers at once").toBe(200);
  const ready = (await posted.json()) as { status: string; url: string; hash: string };
  expect(ready.status).toBe("ready");
  expect(ready.url).toBe(guide.lookbacks["5y"].url);
  const again = await site.get(ready.url);
  expect(again.status()).toBe(200);
  expect(await again.text(), "the same tensor, byte for byte").toBe(body);
});

test("DoD-22 provider gate: live Tiingo rows, recorded limits, and the ledger's unit tests", async () => {
  test.setTimeout(600_000);
  env("TIINGO_API_KEY");
  const dir = mkTemp("ps-smoke-22-");
  const junit = (file: string) => {
    const xml = fs.readFileSync(file, "utf8");
    const attr = (name: string) => Number(new RegExp(`<testsuite [^>]*\\b${name}="(\\d+)"`).exec(xml)?.[1] ?? Number.NaN);
    return { tests: attr("tests"), failures: attr("failures"), errors: attr("errors"), skipped: attr("skipped") };
  };
  try {
    // Two Tiingo price requests (VTI, VBIAX). PS_LIVE_TESTS is set here, so nothing may be skipped.
    const live = python(["-m", "pytest", "tests/data/test_live_provider.py", "-q", "-rs", "-p", "no:cacheprovider", `--junitxml=${path.join(dir, "live.xml")}`], { env: { PS_LIVE_TESTS: "1" }, timeoutMs: 300_000 });
    expect(live.status, `the live provider tests: ${live.stdout.slice(-1200)}`).toBe(0);
    const liveCounts = junit(path.join(dir, "live.xml"));
    expect(liveCounts.tests, "live tests that ran").toBeGreaterThanOrEqual(3);
    expect([liveCounts.failures, liveCounts.errors, liveCounts.skipped], "failed, errored and skipped live tests").toEqual([0, 0, 0]);

    // The adjClose cross-check, the split fixtures and the budget ledger (fake clock): no network.
    const unit = python(["-m", "pytest", "tests/data/test_tiingo.py", "tests/data/test_returns.py", "tests/data/test_budget.py", "-q", "-p", "no:cacheprovider", `--junitxml=${path.join(dir, "unit.xml")}`], { timeoutMs: 300_000 });
    expect(unit.status, `the adapter, returns and budget tests: ${unit.stdout.slice(-1200)}`).toBe(0);
    const unitCounts = junit(path.join(dir, "unit.xml"));
    expect(unitCounts.tests).toBeGreaterThanOrEqual(10);
    expect([unitCounts.failures, unitCounts.errors, unitCounts.skipped]).toEqual([0, 0, 0]);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
  const limits = python(["-c", "import json; from portfoliosight.data import store; from portfoliosight.data.limits import LIMITS_KEY; print(json.dumps(store.get_json(store.store_from_env(), LIMITS_KEY)))"]);
  expect(limits.status, `reading the recorded provider limits: ${limits.stderr.slice(-400)}`).toBe(0);
  const recorded = JSON.parse(limits.stdout) as Record<string, unknown>;
  for (const key of ["provider", "tier", "req_per_hour", "req_per_day", "unique_symbols_per_month", "measured_on", "method"]) expect(recorded, `provider_limits.json has ${key}`).toHaveProperty(key);
  expect(String(recorded.measured_on)).toMatch(/^\d{4}-\d{2}-\d{2}/);
});

test("DoD-23 nightly freshness: today's generation, a clean run, twelve tensors, a small cache", async ({ site }) => {
  test.setTimeout(180_000);
  expect(losAngelesHour(), "this check is meaningful at or after 08:00 in Los Angeles; run it later").toBeGreaterThanOrEqual(8);
  const expected = generationDate();
  const health = (await site.json("/api/health")) as { generation: string; asof: string; asof_trading_days_behind: number; nightly: { finished?: string; D_G?: string; errors?: unknown } | null };
  expect(health.asof, "asof is D_G for a run scheduled at 02:00 Los Angeles time today").toBe(expected);
  expect(health.asof_trading_days_behind).toBe(0);
  expect(health.generation.startsWith(`${expected}-`)).toBe(true);
  expect(health.nightly, "the nightly status").toBeTruthy();
  expect(health.nightly!.D_G).toBe(expected);
  const errors = health.nightly!.errors;
  expect(Array.isArray(errors) ? errors.length : errors === 0 ? 0 : Object.keys((errors as object) ?? { missing: 1 }).length, "errors recorded by the nightly run").toBe(0);
  const finished = new Date(String(health.nightly!.finished));
  expect(Number.isNaN(finished.getTime()), "nightly.finished is an instant").toBe(false);
  const dayIn = (instant: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" }).format(instant);
  expect(dayIn(finished), "the run finished today").toBe(dayIn(new Date()));

  const presets = (await site.json("/api/presets")) as Presets;
  expect(presets.generation).toBe(health.generation);
  const urls = presets.presets.flatMap((preset) => LOOKBACKS.map((lookback) => preset.lookbacks[lookback]?.url));
  expect(new Set(urls).size, "distinct preset tensors").toBe(12);
  for (const url of urls) {
    const tensor = (await site.json(url)) as TensorLike;
    expect(tensor.asof, `${url}: asof`).toBe(expected);
    expect(tensor.generation).toBe(health.generation);
  }

  const cache = run("ssh", ["-o", "BatchMode=yes", env("PS_KS001_SSH_HOST"), "docker exec portfoliosight-api du -sm /app/cache"], { timeoutMs: 60_000 });
  expect(cache.status, `du over ssh: ${cache.stderr.slice(-300)}`).toBe(0);
  const megabytes = Number(/^(\d+)\s+\/app\/cache\s*$/m.exec(cache.stdout)?.[1] ?? Number.NaN);
  expect(megabytes, "the cache volume on KS-001, in MB").toBeLessThanOrEqual(300);
});

test("DoD-24 engine fidelity: the browser math matches the tensor, and builds are deterministic", async () => {
  test.setTimeout(900_000);
  const dir = mkTemp("ps-smoke-24-");
  try {
    const report = path.join(dir, "vitest.json");
    const fidelity = run(path.join(WEB, "node_modules", ".bin", "vitest"), ["run", "tests/fidelity.test.ts", "--reporter=json", `--outputFile=${report}`], { cwd: WEB, timeoutMs: 300_000 });
    expect(fidelity.status, `vitest tests/fidelity.test.ts: ${fidelity.stdout.slice(-800)}`).toBe(0);
    const counts = JSON.parse(fs.readFileSync(report, "utf8")) as { numTotalTests: number; numPassedTests: number; numPendingTests: number; numTodoTests: number };
    expect(counts.numTotalTests, "fidelity tests").toBeGreaterThanOrEqual(10);
    expect(counts.numPassedTests, "every fidelity test passed, none pending").toBe(counts.numTotalTests);

    const junit = path.join(dir, "engine.xml");
    const engine = python(["-m", "pytest", "tests/engine/test_builder.py", "tests/engine/test_invariants.py", "-q", "-p", "no:cacheprovider", `--junitxml=${junit}`], { timeoutMs: 600_000 });
    expect(engine.status, `the builder and invariant tests: ${engine.stdout.slice(-800)}`).toBe(0);
    const xml = fs.readFileSync(junit, "utf8");
    expect(Number(/<testsuite [^>]*\bskipped="(\d+)"/.exec(xml)?.[1]), "skipped engine tests").toBe(0);
    expect(xml, "the determinism test ran").toMatch(/<testcase [^>]*name="test_two_builds_are_identical/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("DoD-25 container and bundle hygiene: no runs, no private holdings, no secret anywhere", async ({ site }) => {
  test.setTimeout(300_000);
  const needles = secretValues();
  expect(needles.length, "credential values to look for (from the environment)").toBeGreaterThanOrEqual(5);
  const patterns = `${needles.join("\n")}\n`;
  const host = env("PS_KS001_SSH_HOST");
  const ssh = (command: string, input?: string) => run("ssh", ["-o", "BatchMode=yes", host, command], { input, timeoutMs: 120_000 });

  // The image the running container was started from.
  const listing = ssh("docker exec portfoliosight-api sh -c 'ls -d /app/runs 2>/dev/null; find /app/data/holdings -type f 2>/dev/null; echo listed'");
  expect(listing.status, `listing the container: ${listing.stderr.slice(-300)}`).toBe(0);
  const lines = listing.stdout.split("\n").map((line) => line.trim()).filter((line) => line !== "");
  expect(lines.pop(), "the listing ran to its end").toBe("listed");
  expect(lines.filter((line) => line.includes("/runs")), "runs/ in the image").toEqual([]);
  expect(lines, "holdings files in the image").toEqual(["/app/data/holdings/holdings_guide2017_step2.csv"]);
  // Patterns go over stdin, never on a command line; grep prints file names only.
  // grep's own status is reported: 1 is "no file matched"; 0 is a leak and 2 a scan that did not run.
  const inImage = ssh("docker exec -i portfoliosight-api sh -c 'grep -rIlF -f /dev/stdin /app /usr/local/lib; echo \"grep-status=$?\"'", patterns);
  expect(inImage.status, `the scan of the image: ${inImage.stderr.slice(-300)}`).toBe(0);
  expect(inImage.stdout.trim().split("\n"), "files in the image that hold a credential value, then grep's status").toEqual(["grep-status=1"]);
  // Control: the same scan finds a string that is in the image.
  const control = ssh("docker exec -i portfoliosight-api sh -c 'grep -rIlF -f /dev/stdin /app/portfoliosight/engine | head -1; echo scanned'", "ENGINE_VERSION\n");
  expect(control.stdout.trim().split("\n").length, "the control scan finds the engine's version constant").toBe(2);

  // The repository at this revision.
  const inRepo = run("git", ["grep", "-I", "-l", "-F", "-f", "-", "--", "."], { input: patterns });
  expect([inRepo.status, inRepo.stdout.trim()], "tracked files that hold a credential value (git grep exits 1 when none)").toEqual([1, ""]);

  // The bundle as served.
  const index = await site.get("/");
  expect(index.status()).toBe(200);
  const html = await index.text();
  const assets = [...html.matchAll(/(?:src|href)="(\/[^"]+\.(?:js|css|svg|json|map))"/g)].map((match) => match[1]);
  expect(assets.filter((asset) => asset.endsWith(".js")).length, "script files of the page").toBeGreaterThanOrEqual(1);
  expect(assets.filter((asset) => asset.endsWith(".map")), "source maps are not published").toEqual([]);
  for (const [name, text] of [["/", html], ...(await Promise.all(assets.map(async (asset) => [asset, await (await site.get(asset)).text()] as const)))] as const) {
    expect(needles.filter((needle) => text.includes(needle)).length, `credential values in ${name}`).toBe(0);
    expect(text, `${name} names no secret variable's value holder`).not.toMatch(/PS_GATE_SECRET\s*[:=]\s*["'][0-9a-f]{16,}/);
  }
});

test("DoD-26 quality gates: Python lint, types and coverage; TypeScript lint, types and tests", async () => {
  test.setTimeout(2_400_000);
  const venv = (tool: string) => path.join(path.dirname(python(["-c", "import sys; print(sys.executable)"]).stdout.trim()), tool);
  for (const [tool, args] of [["ruff", ["check", "."]], ["ruff", ["format", "--check", "."]], ["pyright", ["-p", ".", "."]]] as const) {
    const gate = run(venv(tool), [...args], { timeoutMs: 600_000 });
    expect(gate.status, `${tool} ${args.join(" ")}: ${gate.stdout.slice(-1200)}`).toBe(0);
  }
  const dir = mkTemp("ps-smoke-26-");
  try {
    const report = path.join(dir, "coverage.json");
    const rc = path.join(dir, "empty.coveragerc");
    fs.writeFileSync(rc, "");
    const tests = python(["-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", "--cov=portfoliosight", `--cov-config=${rc}`, "--cov-report=term-missing", `--cov-report=json:${report}`], {
      env: { COVERAGE_FILE: path.join(dir, ".coverage"), PS_LIVE_TESTS: "" },
      timeoutMs: 1_500_000,
    });
    expect(tests.status, `pytest --cov=portfoliosight: ${tests.stdout.slice(-1500)}`).toBe(0);
    const coverage = JSON.parse(fs.readFileSync(report, "utf8")) as { totals: { percent_covered: number }; files: Record<string, { summary: { percent_covered: number; num_statements: number } }> };
    expect(coverage.totals.percent_covered, "total line coverage").toBeGreaterThanOrEqual(80);
    const engine = Object.entries(coverage.files).filter(([name]) => name.replace(/\\/g, "/").includes("portfoliosight/engine/"));
    expect(engine.length, "engine modules in the coverage report").toBeGreaterThanOrEqual(6);
    expect(engine.filter(([, file]) => file.summary.percent_covered !== 100).map(([name]) => name), "engine modules under 100% line coverage").toEqual([]);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
  for (const args of [["run", "lint"], ["run", "typecheck"], ["test"]]) {
    const gate = run("npm", args, { cwd: WEB, timeoutMs: 900_000, env: { CI: "1" } });
    expect(gate.status, `npm ${args.join(" ")} in web/: ${gate.stdout.slice(-1200)}`).toBe(0);
  }
  // "Every production smoke test passes" is this run itself: scripts/smoke.sh exits non-zero unless all 31 do.
});

test("DoD-27 docs: the ROADMAP carries the additions and the README describes what was built", async () => {
  const roadmap = fs.readFileSync(path.join(REPO, "ROADMAP.md"), "utf8").replace(/\s+/g, " ");
  expect(ROADMAP_ITEMS.filter((item) => !roadmap.includes(item)), "items missing from ROADMAP.md").toEqual([]);
  const readme = fs.readFileSync(path.join(REPO, "README.md"), "utf8");
  expect(readmeProblems(readme), "what README.md gets wrong").toEqual([]);
  // The layout it describes exists, and nothing it tells the reader to run is missing.
  for (const dir of ["portfoliosight/data", "portfoliosight/engine", "portfoliosight/api", "portfoliosight/jobs", "web", "deploy", "scripts", "data", "docs"]) {
    expect(fs.existsSync(path.join(REPO, dir)), `${dir} exists`).toBe(true);
  }
  for (const script of readme.match(/scripts\/[\w.-]+\.(?:sh|py)/g) ?? []) expect(fs.existsSync(path.join(REPO, script)), `${script} named in README.md exists`).toBe(true);
  expect(readme).toContain("portfoliosight-data");
  expect(readme, "the old provider guidance is gone").not.toMatch(/yfinance|Schwab|EODHD_API_KEY/i);
  for (const doc of [readme, roadmap]) expect(doc).not.toMatch(/\/home\/[a-z]+/);
});

test("DoD-28 store gate: the bucket verifies, holds the seeded symbols and the laptop mirror is whole", async () => {
  test.setTimeout(1_500_000);
  const verify = python(["-m", "portfoliosight.data.store", "--verify"], { env: { PS_STORE: "r2" }, timeoutMs: 180_000 });
  expect(verify.status, `python -m portfoliosight.data.store --verify: ${verify.stdout.slice(-600)}${verify.stderr.slice(-300)}`).toBe(0);

  const read = python(["-c", "import json; from portfoliosight.data import store; print(json.dumps(store.get_json(store.store_from_env(), 'meta/manifest.json')))"], { env: { PS_STORE: "r2" } });
  expect(read.status, `reading the manifest through the store: ${read.stderr.slice(-300)}`).toBe(0);
  const entries = Object.values((JSON.parse(read.stdout) as { symbols: Record<string, { source?: string; adjusted_through?: string }> }).symbols);
  const seeded = entries.filter((entry) => String(entry.source ?? "").includes("seed"));
  expect(seeded.length, "symbols seeded from the lake").toBeGreaterThanOrEqual(1400);
  expect(seeded.filter((entry) => !/^\d{4}-\d{2}-\d{2}/.test(String(entry.adjusted_through ?? ""))).length, "seeded symbols without adjusted_through").toBe(0);

  // Mirror the bucket now, then ask what a restore would upload: nothing.
  const backup = run(path.join(REPO, "scripts", "r2_backup.sh"), [], { timeoutMs: 900_000 });
  expect(backup.status, `scripts/r2_backup.sh: ${backup.stderr.slice(-400)}`).toBe(0);
  const mirror = "/mnt/d/portfoliosight-data";
  expect(fs.readdirSync(path.join(mirror, "prices")).filter((name) => name.endsWith(".parquet")).length, "price files in the mirror").toBeGreaterThanOrEqual(1400);
  const restore = run("aws", ["s3", "sync", mirror, "s3://portfoliosight-data", "--dryrun", "--endpoint-url", `https://${env("CLOUDFLARE_ACCOUNT_ID")}.r2.cloudflarestorage.com`], {
    env: { AWS_ACCESS_KEY_ID: env("CLOUDFLARE_R2_ACCESS_KEY_ID"), AWS_SECRET_ACCESS_KEY: env("CLOUDFLARE_R2_SECRET_ACCESS_KEY"), AWS_DEFAULT_REGION: "auto", AWS_PROFILE: "", AWS_SESSION_TOKEN: "" },
    timeoutMs: 600_000,
  });
  expect(restore.status, `the restore dry run: ${restore.stderr.slice(-400)}`).toBe(0);
  expect(restore.stdout.split("\n").filter((line) => line.includes("upload:")).length, "files a restore would upload").toBe(0);
  expect(restore.stdout).not.toContain("delete:");
});

test("DoD-29 served symbols: every one is current in the manifest, and the licensing decision is on record", async ({ site }) => {
  test.setTimeout(180_000);
  const presets = (await site.json("/api/presets")) as Presets;
  const listed = ((await site.json("/api/symbols")) as Symbols).symbols.map((symbol) => symbol.id);
  expect(listed.length, "symbols offered").toBeGreaterThanOrEqual(36);
  expect(new Set(listed).size).toBe(listed.length);
  const read = python(["-c", "import json; from portfoliosight.data import store; print(json.dumps(store.get_json(store.store_from_env(), 'meta/manifest.json')))"], { env: { PS_STORE: "r2" } });
  expect(read.status, `reading the manifest through the store: ${read.stderr.slice(-300)}`).toBe(0);
  const manifest = (JSON.parse(read.stdout) as { symbols: Record<string, { status?: string; adjusted_through?: string; last_date?: string }> }).symbols;

  // Served means "ok" in the manifest, both ways: nothing pending or unavailable is offered.
  expect(listed.filter((id) => manifest[id]?.status !== "ok"), "offered symbols that are not ok in the manifest").toEqual([]);
  expect(Object.keys(manifest).filter((id) => manifest[id].status === "ok" && !listed.includes(id)), "ok symbols that are not offered").toEqual([]);
  // Current means within three trading days of the generation date (D_G = the presets' asof).
  const floor = sessionWindow(presets.asof, 3).start;
  const step = Math.max(1, Math.floor(listed.length / 20));
  const sample = [...listed].sort().filter((_, index) => index % step === 0).slice(0, 20);
  expect(sample.length).toBe(20);
  for (const id of [...sample, ...listed.filter((item) => item.startsWith("TSP-"))]) {
    expect(String(manifest[id].adjusted_through).slice(0, 10) >= floor, `${id}: adjusted_through ${manifest[id].adjusted_through} is on or after ${floor}`).toBe(true);
    expect(String(manifest[id].last_date).slice(0, 10) >= floor, `${id}: last_date ${manifest[id].last_date} is on or after ${floor}`).toBe(true);
  }

  expect(fs.existsSync(RUNBOOK), "the deployment runbook exists").toBe(true);
  const dates = decisionDates(fs.readFileSync(RUNBOOK, "utf8"));
  expect(dates.length, "dated personal-use decision under step 3 of the runbook (spec 9.6)").toBeGreaterThanOrEqual(1);
});

test("DoD-30 build benchmark: the runbook's measurement and a fresh 23-fund build are within 30 s", async ({ site }) => {
  test.setTimeout(420_000);
  expect(fs.existsSync(RUNBOOK), "the deployment runbook exists").toBe(true);
  const records = benchmarkRecords(fs.readFileSync(RUNBOOK, "utf8"));
  expect(records.length, "runbook lines with the measured seconds and the grid").toBeGreaterThanOrEqual(1);
  const inForce = records[records.length - 1];
  expect(inForce.seconds, `the measurement in force: ${inForce.line}`).toBeLessThanOrEqual(BENCHMARK_S);
  expect(inForce.seconds).toBeGreaterThan(0);

  await idleQueue(site);
  const guide = ((await site.json("/api/presets")) as Presets).presets.find((preset) => preset.id === "guide2017")!;
  const ids = guide.funds.map((fund) => fund.id);
  expect(ids.length).toBe(23);
  // A key nobody has built: the first fund's ceiling is 0.24 − k·1e-6, k the second of the UTC day.
  const second = Math.floor(Date.now() / 1000) % 86_400;
  let accepted: { cap: number; started: number; generation: string; hash: string } | null = null;
  for (let step = 0; step < 5 && accepted === null; step++) {
    const cap = Number((0.24 - ((second + step) % 86_400) * 1e-6).toFixed(6));
    const body = { funds: ids.map((id, index) => ({ id, min: null, max: index === 0 ? cap : null })), lookback: "5y" };
    let started = Date.now();
    let answer = await site.post("/api/tensors", body);
    if (answer.status() === 429) {
      // the per-address allowance of five build requests a minute: wait it out once, then time the retry
      await new Promise((resolve) => setTimeout(resolve, 61_000));
      started = Date.now();
      answer = await site.post("/api/tensors", body);
    }
    if (answer.status() === 200) continue; // already built in this generation: nothing to measure
    expect(answer.status(), "a new key is queued").toBe(202);
    const queued = (await answer.json()) as { generation: string; hash: string };
    expect(queued.hash).toBe(universeHash(body.funds));
    accepted = { cap, started, generation: queued.generation, hash: queued.hash };
  }
  expect(accepted, "a fresh key to measure").not.toBeNull();
  const url = `/api/tensors/${accepted!.generation}/${accepted!.hash}/5y`;
  let tensor: TensorLike | null = null;
  let elapsed = 0;
  while (tensor === null && elapsed <= BENCHMARK_S + 15) {
    await new Promise((resolve) => setTimeout(resolve, 1_000));
    const poll = await site.get(url);
    elapsed = (Date.now() - accepted!.started) / 1000;
    if (poll.status() === 200) tensor = (await poll.json()) as TensorLike;
    else expect(poll.status(), `polling the build after ${elapsed.toFixed(1)} s`).toBe(202);
  }
  expect(tensor, `the build is ready (waited ${elapsed.toFixed(1)} s)`).not.toBeNull();
  expect(elapsed, "seconds from the request to the first ready answer").toBeLessThanOrEqual(BENCHMARK_S);
  const grid: [number, number] = [tensor!.frontier.x.length, tensor!.grid.y.length];
  expect([[48, 32], [32, 24]], "the grid is the full one or the one fallback").toContainEqual(grid);
  expect(inForce.grid, "the runbook's measurement is for the grid in effect").toEqual(grid);
  expect(tensor!.universe.hash).toBe(accepted!.hash);
  const first = tensor!.universe.funds.findIndex((fund) => fund.id === ids[0]);
  if (first >= 0) expect(tensor!.bounds.requested[first].max).toBeCloseTo(accepted!.cap, 9);
});

test.describe("share by email", () => {
  // One real message per run, to the test address only; nothing else in this file sends mail.
  test.describe.configure({ mode: "serial" });

  test("DoD-31 share by email: sent to the test recipient only; bad address and foreign link refused", async ({ page, site }) => {
    // Absent is a failure, never a skip. The address is never put in a message or a title.
    const recipient = DRY_RUN ? "smoke@example.org" : env("PS_SHARE_TEST_RECIPIENT");
    const shares: { to: unknown; url: unknown; raw: string; status: number | null }[] = [];
    const pending = new Map<unknown, (typeof shares)[number]>();
    page.on("request", (request) => {
      if (request.method() !== "POST" || new URL(request.url()).pathname !== "/api/share") return;
      const entry = { to: request.postDataJSON()?.to, url: request.postDataJSON()?.url, raw: request.postData() ?? "", status: null as number | null };
      shares.push(entry);
      pending.set(request, entry);
    });
    page.on("response", (response) => {
      const entry = pending.get(response.request());
      if (entry) entry.status = response.status();
    });
    await openApp(page, "u=tsp");
    await expect.poll(() => param(page, "r")).not.toBeNull();
    const address = page.url();

    // Refusals first, straight at the endpoint: neither may be accepted.
    const code = async (response: import("@playwright/test").APIResponse) => {
      const body = (await response.json().catch(() => null)) as { error?: { code?: string } | string; code?: string } | null;
      return typeof body?.error === "object" ? body.error?.code : (body?.error ?? body?.code);
    };
    const malformed = await site.post("/api/share", { to: "not-an-address", url: address });
    expect(malformed.status(), "a malformed address").toBe(400);
    expect(await code(malformed)).toBe("invalid_recipient");
    const foreign = await site.post("/api/share", { to: recipient, url: "https://example.com/?u=tsp" });
    expect(foreign.status(), "a link to another host").toBe(400);
    expect(await code(foreign)).toBe("invalid_url");

    await page.getByTestId("share-open").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("private preview");
    // In the dialog a malformed address is stopped before any request.
    await dialog.getByTestId("share-email").fill("not-an-address");
    await dialog.getByTestId("share-send").click();
    await expect(dialog.getByTestId("share-status")).toHaveText("That address doesn't look right");
    expect(shares.length, "requests for a malformed address").toBe(0);

    await dialog.getByTestId("share-email").fill(recipient);
    await dialog.getByTestId("share-send").click();
    await expect.poll(() => shares[0]?.status ?? null, { timeout: 30_000 }).toBe(202);
    await expect(dialog.getByTestId("share-status")).toHaveText("Sent");
    await page.waitForTimeout(1_000);
    expect(shares.length, "requests for one click").toBe(1);
    expect(shares[0].to === recipient, "the message goes to the test recipient").toBe(true);
    expect(shares[0].url, "the link sent is this view").toBe(address);
    const others = (shares[0].raw.match(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g) ?? []).filter((found) => found !== recipient).length;
    expect(others, "addresses other than the test recipient in the request").toBe(0);
    expect(Object.keys(JSON.parse(shares[0].raw)).sort(), "the request carries a recipient and a link, no message text").toEqual(["to", "url"]);
  });
});
