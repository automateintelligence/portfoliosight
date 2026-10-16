import { expect, test, type Page } from "@playwright/test";

// Local behaviour checks against `vite preview` with /api proxied to mock/server.mjs. They cover
// what the frozen gate does not: failure paths, the mock's switches and the details-on layout.
test.beforeEach(async ({ request }) => {
  await request.post("/__mock/reset");
});

const open = async (page: Page, query = "") => {
  await page.goto(`/${query ? `?${query}` : ""}`);
  await expect(page.getByTestId("chart-canvas")).toBeVisible();
  await expect(page.getByTestId("point-selected")).toBeVisible();
};
// The page scrolls a section into view smoothly; a click sent while it still moves can land
// somewhere else, so this waits until the scroll position holds.
const settled = async (page: Page) => {
  await expect
    .poll(async () => {
      const y = await page.evaluate(() => window.scrollY);
      await page.waitForTimeout(120);
      return (await page.evaluate(() => window.scrollY)) === y;
    })
    .toBe(true);
};
const section = async (page: Page, id: string) => {
  await page.getByTestId(`chip-${id}`).click();
  await expect(page.getByTestId(`section-${id}`)).toHaveAttribute("aria-expanded", "true");
  await settled(page);
};
const isPhone = (name: string) => name.includes("phone");
const boxOf = async (page: Page, id: string) => (await page.getByTestId(id).boundingBox())!;
const posts = async (page: Page) => (await (await page.request.get("/__mock/posts")).json()) as { funds: { id: string }[]; lookback: string }[];

test("nothing scrolls sideways with details on and every section open", async ({ page }) => {
  await open(page);
  await page.getByTestId("details-toggle").click();
  for (const id of ["funds", "trades", "stress", "settings"]) await section(page, id);
  const width = page.viewportSize()!.width;
  const size = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));
  expect(size.inner, "the layout viewport did not grow").toBeLessThanOrEqual(width);
  expect(size.scroll).toBeLessThanOrEqual(width);
});

test("the first screen needs nothing entered and shows no table", async ({ page }) => {
  await open(page);
  await expect(page.locator("table")).toHaveCount(0);
  await expect(page.getByTestId("fund-row-VTI")).toHaveCount(0);
  await expect(page.getByText("How spread out the risk is").first()).toBeVisible();
  await expect(page.getByTestId("div-reset")).toBeHidden();
});

test("a window without enough shared history is disabled with its note and the view carries on", async ({ page, request }) => {
  await request.post("/__mock/config", { data: { unavailable: "10y" } });
  await open(page, "f=SGOV:50,VTIP:50&unit=pct");
  const before = await page.getByTestId("risk-readout-bad").textContent();
  await section(page, "settings");
  await page.getByTestId("lookback-10y").check({ force: true });
  await expect(page.getByTestId("lookback-10y")).toBeDisabled();
  await expect(page.getByTestId("section-settings")).toContainText("not enough shared history");
  await expect(page.getByTestId("chart-canvas")).toBeVisible();
  await expect(page.getByTestId("risk-readout-bad")).toHaveText(before ?? "");
  await page.getByTestId("lookback-1y").check({ force: true });
  await expect.poll(() => new URL(page.url()).searchParams.get("lb")).toBe("1y");
  await expect(page.getByTestId("lookback-1y")).toBeChecked();
  expect((await posts(page)).map((p) => p.lookback)).toEqual(["5y", "10y", "1y"]);
});

test("a shared link to a window the menu cannot fill offers the other windows", async ({ page, request }) => {
  await request.post("/__mock/config", { data: { unavailable: "10y" } });
  await page.goto("/?f=SGOV:50,VTIP:50&unit=pct&lb=10y");
  await expect(page.getByTestId("chart")).toContainText("does not have enough shared history for the 10 years view");
  await page.getByTestId("chart").getByRole("button", { name: "1 year" }).click();
  await expect(page.getByTestId("chart-canvas")).toBeVisible();
  await expect.poll(() => new URL(page.url()).searchParams.get("lb")).toBe("1y");
});

test("a stopped nightly shows the dated notice without details", async ({ page, request }) => {
  await request.post("/__mock/config", { data: { stale: 3 } });
  await open(page);
  await expect(page.getByText(/Prices through \d{4}-\d{2}-\d{2}; the nightly refresh has not run since then\./)).toBeVisible();
});

test("fresh data shows no dated notice", async ({ page }) => {
  await open(page);
  await expect(page.getByText(/the nightly refresh has not run/)).toHaveCount(0);
});

test("an expired human check reloads once and the view comes back", async ({ page, request }) => {
  await open(page, "f=SGOV:50,VTIP:50&unit=pct");
  await request.post("/__mock/config", { data: { challenge: 1 } });
  await section(page, "settings");
  const reloaded = page.waitForEvent("load");
  // a click, not check(): check() then waits to see the radio checked, and the reload it starts
  // can take the collapsed section (and the radio) away first
  await page.getByTestId("lookback-3y").click({ force: true });
  await reloaded;
  await expect(page.getByTestId("chart-canvas")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("lb")).toBe("3y");
  expect(new URL(page.url()).searchParams.get("f")).toBe("SGOV:50,VTIP:50");
});

test("the strip swaps in the service's one-year range for exact weights, and keeps its own when the service cannot answer", async ({ page, request }) => {
  // the percent figure (beneath the dollars when the strip is in dollars, as for this preset)
  const pctOf = async (id: string) => Number(/([−+]?\d+\.\d)%/.exec((await page.getByTestId(id).textContent()) ?? "")?.[1].replace("−", "-").replace("+", ""));
  // a position between two columns: the page blends the node ranges, then asks the service
  await open(page, "u=guide2017&lb=5y&r=20.5&d=0.4");
  const own = await pctOf("range-typical");
  await expect.poll(async () => ((await (await page.request.get("/__mock/ranges")).json()) as unknown[]).length).toBeGreaterThan(0);
  const asked = ((await (await page.request.get("/__mock/ranges")).json()) as { weights: number[]; lookback: string }[]).at(-1)!;
  expect(asked.lookback).toBe("5y");
  expect(asked.weights.length).toBe(23);
  expect(Math.abs(asked.weights.reduce((a, b) => a + b, 0) - 1)).toBeLessThan(1e-9);
  // the mock refuses by default (409): the blended figure stays
  await page.waitForTimeout(800);
  expect(await pctOf("range-typical")).toBe(own);
  // with answers switched on, the service's figure replaces it once the sliders rest
  await request.post("/__mock/config", { data: { ranges: true } });
  await open(page, "u=guide2017&lb=5y&r=20.25&d=0.45");
  const before = await pctOf("range-typical");
  await expect.poll(() => pctOf("range-typical"), { timeout: 5000 }).not.toBe(before);
  // a column and one of its levels is exact already: nothing is asked
  const count = ((await (await page.request.get("/__mock/ranges")).json()) as unknown[]).length;
  await open(page, "u=guide2017&lb=5y&r=24&d=0");
  await page.waitForTimeout(800);
  expect(((await (await page.request.get("/__mock/ranges")).json()) as unknown[]).length).toBe(count);
});

test("a failed build offers Retry, and Retry sends the same request", async ({ page, request }) => {
  await request.post("/__mock/config", { data: { build409: 1 } });
  await page.goto("/?f=SGOV:50,VTIP:50&unit=pct");
  await expect(page.getByTestId("build-retry")).toBeVisible();
  await expect(page.getByTestId("building-notice")).toContainText("We couldn't compute this menu");
  await expect(page.getByTestId("building-notice")).toContainText("build_failed");
  await page.getByTestId("build-retry").click();
  await expect(page.getByTestId("chart-canvas")).toBeVisible();
  const sent = await posts(page);
  expect(sent.length).toBe(2);
  expect(JSON.stringify(sent[1])).toBe(JSON.stringify(sent[0]));
});

test("a ghost frontier can be switched on and off again", async ({ page }) => {
  await open(page);
  await section(page, "settings");
  const chart = page.getByTestId("chart");
  await expect(chart).toHaveAttribute("data-ghost-count", "0");
  await page.getByTestId("ghost-1y").check({ force: true });
  await expect(chart).toHaveAttribute("data-ghost-count", "1");
  await expect.poll(() => new URL(page.url()).searchParams.get("g")).toBe("1y");
  await page.getByTestId("ghost-1y").uncheck({ force: true });
  await expect(chart).toHaveAttribute("data-ghost-count", "0");
});

test("the picker offers served funds, and percentages must add up before the menu is used", async ({ page }) => {
  await open(page, "u=tsp");
  await expect(page.getByTestId("chip-trades")).toHaveCount(0);
  await section(page, "funds");
  await page.getByTestId("fund-add").fill("L 2050");
  await expect(page.getByRole("option", { name: /TSP-L2050/ })).toBeVisible();
  await page.getByTestId("fund-add").fill("ZZZZ");
  await page.getByTestId("fund-add").press("Enter");
  await expect(page.getByText(/ZZZZ isn't offered/)).toBeVisible();

  await page.goto("/?f=SGOV:60,VTIP:32&unit=pct");
  await section(page, "funds");
  await expect(page.getByTestId("funds-total")).toHaveText("Total: 92%, 8% to go");
  // Amounts apply as they are typed: there is nothing to press while the fund list is unchanged.
  await expect(page.getByTestId("funds-hint")).toHaveText("Amounts apply as you type.");
  await expect(page.getByTestId("use-menu")).toHaveCount(0);
  await expect(page.getByTestId("point-current")).toHaveCount(0);
  await expect(page.getByTestId("mix-entered-VTIP")).toHaveText("");
  await page.getByTestId("fund-row-VTIP").locator("input").fill("40");
  await expect(page.getByTestId("point-current")).toBeVisible();
  await expect(page.getByTestId("mix-entered-VTIP")).toHaveText("40.0%");
  await expect(page.getByTestId("chip-trades")).toBeVisible();
});

test("the picker lists the exact ticker first and finds funds and companies by name", async ({ page, request }) => {
  await request.post("/__mock/config", { data: { stocks: true } });
  await open(page);
  await section(page, "funds");
  const options = page.getByRole("listbox", { name: "Matching funds" }).getByRole("option");
  const firstOf = async (typed: string) => {
    await page.getByTestId("fund-add").fill(typed);
    await expect(options.first()).toBeVisible();
    return (await options.first().innerText()).replace(/\s+/g, " ").trim();
  };
  expect(await firstOf("C")).toBe("C Citigroup Inc.");
  await expect(options.nth(1)).toContainText("CB");
  expect(await firstOf("AAPL")).toBe("AAPL Apple Inc.");
  expect(await firstOf("apple")).toBe("AAPL Apple Inc.");
  await page.getByTestId("fund-add").fill("vang");
  await expect(options).toHaveCount(8);
  for (const text of await options.allInnerTexts()) expect(text).toMatch(/Vanguard/);
  await page.getByTestId("fund-add").fill("c");
  await page.getByTestId("fund-add").press("Enter");
  await expect(page.getByTestId("fund-row-C")).toBeVisible();
});

test("the picker's list is opaque and drawn over the help text in every look", async ({ page }) => {
  for (const look of ["ks-dark", "light", "hud", "grid"]) {
    await open(page, `t=${look}`);
    await section(page, "funds");
    await page.getByTestId("fund-add").evaluate((el) => el.scrollIntoView({ block: "center" }));
    await page.getByTestId("fund-add").fill("v");
    const list = page.getByRole("listbox", { name: "Matching funds" });
    await expect(list).toBeVisible();
    await expect(list.getByRole("option")).toHaveCount(8);
    const look_ = () =>
      page.evaluate(() => {
        const listEl = document.querySelector(".adder-list")!;
        const help = document.querySelector('[data-testid="funds-limit"]')!.getBoundingClientRect();
        const box = listEl.getBoundingClientRect();
        const inList = (x: number, y: number) => listEl.contains(document.elementFromPoint(x, y));
        return {
          background: getComputedStyle(listEl).backgroundColor,
          overHelp: inList(help.x + Math.min(40, help.width / 2), help.y + help.height / 2),
          lastInView: box.bottom <= window.innerHeight && box.top >= 0,
          // every point of the list, sampled every 16 px down its middle, shows the list
          lastOnTop: Array.from({ length: Math.floor(box.height / 16) }, (_, i) => box.top + 8 + i * 16).every((y) => inList(box.x + box.width / 2, y)),
        };
      });
    // The list is scrolled into view smoothly: wait until it holds still.
    await expect.poll(async () => (await look_()).lastInView, { message: `${look}: the whole list is brought into view` }).toBe(true);
    await page.waitForTimeout(400);
    const seen = await look_();
    expect(seen.background, `${look}: the list's background is opaque`).toMatch(/^rgb\(/);
    expect(seen.overHelp, `${look}: the list is drawn over the help text`).toBe(true);
    expect(seen.lastOnTop, `${look}: nothing after the section is drawn over the list`).toBe(true);
  }
});

test("recalculate appears only when the fund list changes, and sends the new list", async ({ page }) => {
  await open(page, "f=SGOV:60,VTIP:40&unit=pct");
  await section(page, "funds");
  await expect(page.getByText("Use this menu")).toHaveCount(0);
  await expect(page.getByTestId("use-menu")).toHaveCount(0);
  const before = (await posts(page)).length;
  await page.getByTestId("fund-add").fill("VTI");
  await page.getByTestId("fund-add").press("Enter");
  await expect(page.getByTestId("fund-row-VTI")).toBeVisible();
  const button = page.getByTestId("use-menu");
  await expect(button).toHaveText("Recalculate with these funds");
  expect((await posts(page)).length, "nothing is computed before the button is pressed").toBe(before);
  await button.click();
  await expect.poll(async () => (await posts(page)).length).toBe(before + 1);
  expect((await posts(page)).at(-1)!.funds.map((f) => f.id).sort()).toEqual(["SGOV", "VTI", "VTIP"]);
  await expect(page.getByTestId("use-menu")).toHaveCount(0);
});

test("funds sit in a sidebar beside the chart on a wide screen and in a section on a phone", async ({ page }, testInfo) => {
  await open(page);
  const side = page.getByTestId("section-funds");
  await expect(side).toHaveAttribute("aria-expanded", "false");
  if (isPhone(testInfo.project.name)) {
    await expect(page.getByTestId("funds-toggle")).toHaveCount(0);
    await section(page, "funds");
    const chart = await boxOf(page, "chart");
    const row = await boxOf(page, "fund-row-VTI");
    expect(row.y, "on a phone the table is below the chart").toBeGreaterThan(chart.y + chart.height);
    return;
  }
  const closed = await boxOf(page, "chart");
  const toggle = page.getByTestId("funds-toggle");
  await expect(toggle).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByTestId("fund-row-VTI")).toHaveCount(0);
  await toggle.click();
  await expect(side).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("fund-row-VTI")).toBeVisible();
  const chart = await boxOf(page, "chart");
  const panel = (await side.boundingBox())!;
  const view = page.viewportSize()!;
  expect(chart.width, "the chart gives up width").toBeLessThan(closed.width - 200);
  expect(chart.width, "and is still a chart").toBeGreaterThan(520);
  expect(chart.x, "the chart stays on the left").toBeLessThanOrEqual(closed.x);
  expect(panel.x, "the sidebar is to the right of the chart").toBeGreaterThanOrEqual(chart.x + chart.width);
  expect(panel.x + panel.width).toBeLessThanOrEqual(view.width);
  expect(panel.y, "beside the chart, not under it").toBeLessThan(chart.y + 40);
  expect(panel.y + panel.height, "inside the first screen").toBeLessThanOrEqual(view.height);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  // remembered in this browser
  await page.reload();
  await expect(page.getByTestId("section-funds")).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByTestId("fund-row-VTI")).toBeVisible();
  await page.getByTestId("funds-toggle").click();
  await expect(page.getByTestId("section-funds")).toHaveAttribute("aria-expanded", "false");
  await page.reload();
  await expect(page.getByTestId("point-selected")).toBeVisible();
  await expect(page.getByTestId("section-funds")).toHaveAttribute("aria-expanded", "false");
  // the chip opens it too
  await page.getByTestId("chip-funds").click();
  await expect(page.getByTestId("section-funds")).toHaveAttribute("aria-expanded", "true");
});

test("at 1024 px the open sidebar leaves a first screen in which nothing overlaps", async ({ page }) => {
  // The width is set here, so this runs the same in both projects.
  await page.setViewportSize({ width: 1024, height: 768 });
  await open(page);
  await page.getByTestId("funds-toggle").click();
  await expect(page.getByTestId("fund-row-VTI")).toBeVisible();
  const box = async (selector: string) => (await page.locator(selector).first().boundingBox())!;
  const apart = (a: { x: number; y: number; width: number; height: number }, b: typeof a) => a.x + a.width <= b.x + 0.5 || b.x + b.width <= a.x + 0.5 || a.y + a.height <= b.y + 0.5 || b.y + b.height <= a.y + 0.5;
  const parts = [".strip-label", '[data-testid="range-low"]', '[data-testid="range-typical"]', '[data-testid="range-high"]', ".divword", '[data-testid="details-toggle"]'];
  const boxes = await Promise.all(parts.map(box));
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) expect(apart(boxes[i], boxes[j]), `${parts[i]} and ${parts[j]} overlap`).toBe(true);
  const chips = await Promise.all(["funds", "trades", "stress", "settings"].map((id) => box(`[data-testid="chip-${id}"]`)));
  const advice = await box(".advice");
  for (const chip of chips) expect(apart(chip, advice), "a chip and the advice line overlap").toBe(true);
  const chart = await box('[data-testid="chart"]');
  const side = await box('[data-testid="section-funds"]');
  expect(chart.width).toBeGreaterThan(400);
  expect(side.x + side.width).toBeLessThanOrEqual(1024);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1024);
  // every column of the table is inside the sidebar
  const cellBox = await box('[data-testid="mix-selected-VTI"]');
  expect(cellBox.x + cellBox.width).toBeLessThanOrEqual(side.x + side.width);
});

test("the table always shows the mix entered and the selected mix, and the selected one follows the sliders", async ({ page }) => {
  await open(page);
  await section(page, "funds");
  await expect(page.getByTestId("section-funds").getByText("Mix entered %").first()).toBeAttached();
  await expect(page.getByTestId("section-funds").getByText("Selected mix %").first()).toBeAttached();
  const column = async (kind: string) => page.locator(`[data-testid^="mix-${kind}-"]`).allTextContents();
  const total = (cells: string[]) => cells.reduce((acc, c) => acc + (Number.parseFloat(c) || 0), 0);
  const entered = await column("entered");
  expect(entered.length).toBeGreaterThan(10);
  expect(Math.abs(total(entered) - 100), "the mix entered adds up to 100%").toBeLessThan(0.6);
  const first = await column("selected");
  expect(Math.abs(total(first) - 100), "the selected mix adds up to 100%").toBeLessThan(0.6);
  // the risk slider moves it
  await page.getByTestId("point-selected").focus();
  for (let i = 0; i < 12; i++) await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await column("selected")).join("|")).not.toBe(first.join("|"));
  const second = await column("selected");
  // and so does the diversification slider
  for (let i = 0; i < 8; i++) await page.keyboard.press("ArrowDown");
  await expect.poll(async () => (await column("selected")).join("|")).not.toBe(second.join("|"));
  expect(Math.abs(total(await column("selected")) - 100)).toBeLessThan(0.6);
  expect((await column("entered")).join("|"), "the mix entered does not move").toBe(entered.join("|"));
  // the other units keep both columns
  const units = page.getByTestId("unit-toggle").getByRole("radio");
  await expect(units).toHaveText(["Shares", "%", "$"]);
  await units.nth(0).click();
  await expect(page.getByTestId("amount-head")).toHaveText("Shares (Qty)");
  await expect(page.locator('[data-testid^="mix-selected-"]').first()).toHaveText(/%$/);
  await page.getByTestId("fund-row-VTI").locator("input").fill("10");
  await expect(page.getByTestId("mix-entered-VTI")).toHaveText(/^\d+\.\d%$/);
});

test("every frontier line is named at its right end and the names do not collide", async ({ page }, testInfo) => {
  await open(page);
  await expect(page.getByTestId("frontier-label-5y")).toHaveText("5 years");
  await open(page, "g=10y,ew,1y");
  await expect(page.getByTestId("chart")).toHaveAttribute("data-ghost-count", "3");
  // the No limits line is named like the history windows, and is not one of them in the count
  const want: Record<string, string> = { "5y": "5 years", "10y": "10 years", ew: "Weighted recent", "1y": "1 year", nolimits: "No allocation limits" };
  for (const [id, text] of Object.entries(want)) await expect(page.getByTestId(`frontier-label-${id}`)).toHaveText(text);
  const chart = await boxOf(page, "chart");
  const boxes = await Promise.all(Object.keys(want).map(async (id) => ({ id, box: (await page.getByTestId(`frontier-label-${id}`).locator("text").boundingBox())! })));
  for (const { id, box } of boxes) {
    expect(box.x >= chart.x && box.x + box.width <= chart.x + chart.width && box.y >= chart.y && box.y + box.height <= chart.y + chart.height, `${id} label is inside the chart`).toBe(true);
  }
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i].box;
      const b = boxes[j].box;
      const apart = a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y + 1 || b.y + b.height <= a.y + 1;
      expect(apart, `${boxes[i].id} and ${boxes[j].id} labels overlap`).toBe(true);
    }
  }
  // "ew" ends beside the primary line in the mock, so it is stepped away and joined by a leader
  await expect(page.getByTestId("frontier-label-ew").locator("path.leader")).toHaveCount(1);
  await expect(page.getByTestId("frontier-label-5y").locator("path.leader")).toHaveCount(0);
  if (isPhone(testInfo.project.name)) return;
  // the legend names the curve the same way, with what it means
  await expect(page.getByTestId("key-nolimits")).toHaveText("No allocation limits: same funds, no limit on any one fund");
  // hovering a ghost line names it; the primary line does not need it
  const end = page.getByTestId("frontier-label-10y");
  const x = chart.x + Number(await end.getAttribute("data-end-x"));
  const y = chart.y + Number(await end.getAttribute("data-end-y"));
  await expect(page.getByTestId("ghost-tip")).toHaveCount(0);
  await page.mouse.move(x - 80, y + 60);
  await page.mouse.move(x - 2, y + 1, { steps: 5 });
  await expect(page.getByTestId("ghost-tip")).toContainText("10 years");
  await expect(end).toHaveClass(/is-hot/);
  await page.mouse.move(chart.x + 20, chart.y + 20);
  await expect(page.getByTestId("ghost-tip")).toHaveCount(0);
});

test("the square and the open circle show the same card as the selected mix", async ({ page }, testInfo) => {
  await open(page);
  const card = page.getByTestId("mix-card");
  const titles: Record<string, string> = { selected: "Selected mix", current: "The mix you entered", div: "Optimized" };
  if (isPhone(testInfo.project.name)) {
    // at rest on Optimized the selected point sits on the open circle, and a tap there reaches the
    // point (it pins its card); move the point off the circle first
    await page.getByTestId("div-slider").focus();
    for (let i = 0; i < 12; i++) await page.keyboard.press("ArrowLeft");
  }
  for (const kind of ["current", "div", "selected"]) {
    const mark = page.locator(`[data-mark="${kind}"]`);
    if (isPhone(testInfo.project.name)) {
      if (kind === "selected") continue; // on a phone the selected point is a drag handle
      await page.getByTestId("chart").tap({ position: { x: 30, y: 30 } });
      await mark.locator(".hit").tap({ force: true });
    } else {
      await page.mouse.move(5, 5);
      await expect(card).toHaveCount(0);
      // the square and the circle can sit on top of each other: keyboard focus picks one exactly
      await mark.focus();
    }
    await expect(card).toHaveCount(1);
    if (isPhone(testInfo.project.name) && kind === "div" && (await card.getAttribute("data-for")) === "current") {
      // the square covers the circle in this view: a second tap turns the card over
      await expect(page.getByText("Tap again for the marker underneath.")).toBeVisible();
      await page.locator('[data-mark="current"] .hit').tap({ force: true });
    }
    await expect(card).toHaveAttribute("data-for", kind);
    await expect(card.locator("h3")).toHaveText(titles[kind]);
    await expect(card.locator(".tip-range")).toHaveText(/Bad\s*[+−]?\d+\.\d%\s*Typical\s*[+−]?\d+\.\d%\s*Good\s*[+−]?\d+\.\d%/);
    await expect(card.getByTestId("mix-card-word")).toHaveText(/^(Good|Average|Fair|Poor)$/);
    expect(await card.locator("li").count(), `${kind}: largest holdings`).toBeGreaterThanOrEqual(3);
    await expect(card).toContainText("Risk and expected return are per year.");
    expect(await mark.getAttribute("aria-describedby"), `${kind}: the open card describes its marker`).toBe(await card.locator("xpath=..").getAttribute("id"));
    await expect(card.locator("li").first()).toHaveText(/^[A-Z0-9.-]+\s*\d+\.\d%$/);
    const box = (await card.boundingBox())!;
    const chart = await boxOf(page, "chart");
    expect(box.x >= chart.x && box.y >= chart.y && box.x + box.width <= chart.x + chart.width + 1 && box.y + box.height <= chart.y + chart.height + 1, `${kind}: the card stays inside the chart`).toBe(true);
    await page.keyboard.press("Escape");
    if (!isPhone(testInfo.project.name)) await mark.blur();
  }
  if (isPhone(testInfo.project.name)) {
    // a press on either marker that moves drags the selected point, so the page must not pan from it
    for (const kind of ["current", "div"]) {
      expect(await page.locator(`[data-mark="${kind}"]`).evaluate((el) => getComputedStyle(el).touchAction), `${kind}: no panning from the marker`).toBe("none");
    }
    return;
  }
  // a mouse over the square shows its card as well
  const square = await boxOf(page, "point-current");
  await page.mouse.move(square.x + square.width / 2, square.y + square.height / 2);
  await expect(card).toHaveCount(1);
  expect(["current", "div"]).toContain(await card.getAttribute("data-for"));
});

test("hovering the colour map shows a plain card for the mix there", async ({ page }, testInfo) => {
  await open(page);
  const chart = await boxOf(page, "chart");
  if (isPhone(testInfo.project.name)) {
    // The map answers to a mouse only: a touch on it shows no card and moves nothing.
    const before = (await page.getByTestId("range-typical").textContent()) ?? "";
    await page.getByTestId("chart").tap({ position: { x: chart.width * 0.3, y: chart.height * 0.72 } });
    await page.waitForTimeout(300);
    await expect(page.getByTestId("mix-card")).toHaveCount(0);
    await expect(page.getByTestId("range-typical")).toHaveText(before);
    return;
  }
  await page.mouse.move(chart.x + chart.width * 0.3, chart.y + chart.height * 0.72);
  const card = page.locator('[data-testid="mix-card"][data-for="cell"]');
  await expect(card).toBeVisible();
  await expect(card.locator("h3")).toHaveText("The mix at this spot");
  await expect(card).toContainText(/Risk\s*\d+\.\d%/);
  await expect(card).toContainText(/Expected return\s*\d+\.\d%/);
  await expect(card.getByTestId("mix-card-word")).toHaveText(/^(Good|Average|Fair|Poor)$/);
  expect(await card.locator("li").count()).toBeGreaterThanOrEqual(3);
  const plain = (await card.innerText()).toLowerCase();
  for (const word of ["ceiling", "floor", "sits at", "bets", "computed for"]) expect(plain, `"${word}" in the default card`).not.toContain(word);
  // over a marker the marker's own card wins
  await page.getByTestId("point-selected").hover({ force: true });
  await expect(card).toHaveCount(0);
  // details add the measure and where the mix was computed
  await page.mouse.move(chart.x + 10, chart.y + 10);
  await page.getByTestId("details-toggle").click();
  await page.evaluate(() => window.scrollTo(0, 0));
  const after = await boxOf(page, "chart");
  await page.mouse.move(after.x + after.width * 0.3, after.y + after.height * 0.72);
  await expect(card).toContainText("independent bets");
  await expect(card).toContainText(/At risk \d+\.\d%, earning at least \d+\.\d%/);
});

test("the details explain the diversification word and Optimized in plain words, each once", async ({ page }) => {
  await open(page);
  await page.getByTestId("details-toggle").click();
  await expect(page.getByTestId("details-words")).toContainText("the most spread-out mix these funds can make");
  for (const word of ["Good:", "Average:", "Fair:", "Poor:"]) await expect(page.getByTestId("details-words")).toContainText(word);
  await expect(page.getByTestId("details-suggested")).toContainText("Optimized is the balanced point");
  const text = await page.locator("body").innerText();
  expect(text).not.toContain("Words compare this mix");
  expect(text).not.toContain("standard error");
  expect(text.split("the knee of diversification (ENB) gained against return given up").length - 1, "the method sentence is stated once").toBe(1);
  await expect(page.getByTestId("details-method")).toContainText("Optimized: the knee of diversification");
  // the bell-curve figure appears in the details only, labelled as such
  await expect(page.getByTestId("details-bell")).toContainText("Textbook bell-curve figure");
});

test("trades export a CSV file from the browser", async ({ page }) => {
  await open(page);
  await section(page, "trades");
  const sent: string[] = [];
  page.on("request", (r) => sent.push(r.url()));
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("trades-export").click()]);
  expect(download.suggestedFilename()).toMatch(/^portfoliosight-trades-\d{4}-\d{2}-\d{2}\.csv$/);
  const stream = await download.createReadStream();
  let csv = "";
  for await (const chunk of stream) csv += chunk.toString();
  const lines = csv.trimEnd().split("\r\n");
  expect(lines[0]).toBe("Fund,Now %,Selected %,Change (percentage points),Change ($)");
  expect(lines.length).toBeGreaterThan(5);
  const rows = lines.slice(1).map((l) => l.split(","));
  for (const r of rows) {
    expect(r.length).toBe(5);
    expect(r[0]).toMatch(/^[A-Z0-9.-]+$/);
    for (const cell of r.slice(1)) expect(Number.isFinite(Number(cell)), cell).toBe(true);
  }
  const sum = (col: number) => rows.reduce((acc, r) => acc + Number(r[col]), 0);
  expect(Math.abs(sum(1) - 100)).toBeLessThan(0.3);
  expect(Math.abs(sum(2) - 100)).toBeLessThan(0.3);
  expect(Math.abs(sum(3)), "changes cancel out").toBeLessThan(0.3);
  // the table on the page agrees with the file for its first row
  const shown = await page.getByTestId("section-trades").getByRole("listitem").first().innerText();
  expect(shown).toContain(rows[0][0]);
  expect(sent.filter((u) => !u.startsWith("blob:")), "the export sends nothing").toEqual([]);
});

test("four looks: the switcher reaches each, and a shared link opens the HUD or the Grid", async ({ page }, testInfo) => {
  await open(page);
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "ks-dark");
  const control = page.getByTestId("theme-switch");
  const order = ["ks-dark", "light", "hud", "grid"];
  if (isPhone(testInfo.project.name)) {
    for (const next of ["light", "hud", "grid", "ks-dark"]) {
      await control.click();
      await expect(html).toHaveAttribute("data-theme", next);
    }
  } else {
    const segments = control.getByRole("radio");
    await expect(segments).toHaveText(["Dark", "Light", "HUD", "Grid"]);
    const header = (await page.locator(".hdr-in").boundingBox())!;
    const box = (await control.boundingBox())!;
    expect(box.x + box.width, "the four segments fit in the header").toBeLessThanOrEqual(header.x + header.width + 0.5);
    for (const id of ["grid", "hud", "light", "ks-dark"]) {
      await segments.nth(order.indexOf(id)).click();
      await expect(html).toHaveAttribute("data-theme", id);
      await expect(segments.nth(order.indexOf(id))).toHaveAttribute("aria-checked", "true");
      await expect.poll(() => new URL(page.url()).searchParams.get("t")).toBe(id);
    }
  }
  const look = async () =>
    page.evaluate(() => {
      const cs = getComputedStyle(document.documentElement);
      const chart = document.querySelector('[data-testid="chart"]')!;
      return {
        accent: cs.getPropertyValue("--accent").trim().toLowerCase(),
        gap: cs.getPropertyValue("--cell-gap").trim(),
        gridLines: getComputedStyle(chart, "::after").content !== "none",
        ring: getComputedStyle(document.querySelector(".pt-selected .reticle")!).animationName,
      };
    });
  await open(page, "t=hud");
  await expect(html).toHaveAttribute("data-theme", "hud");
  expect(await look(), "HUD: red accent, no grid over the map, the turning ring").toEqual({ accent: "#d63a18", gap: "0", gridLines: false, ring: "reticle" });
  await open(page, "t=grid");
  await expect(html).toHaveAttribute("data-theme", "grid");
  expect(await look(), "Grid: the cyan look with its grid").toEqual({ accent: "#35c9e8", gap: "1", gridLines: true, ring: "reticle" });
});

test("the legend bar reads the way the map does: Light pale at Less, the other looks bright at Less", async ({ page }) => {
  for (const [theme, lessEnd, moreEnd] of [["ks-dark", "--heat-4", "--heat-1"], ["light", "--heat-1", "--heat-4"], ["hud", "--heat-4", "--heat-1"], ["grid", "--heat-4", "--heat-1"]]) {
    await open(page, `t=${theme}`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    const got = await page.evaluate(([less, more]) => {
      const probe = document.createElement("span");
      document.body.appendChild(probe);
      const rgb = (name: string) => {
        probe.style.color = `var(${name})`;
        return getComputedStyle(probe).color;
      };
      const want = { less: rgb(less), more: rgb(more), ramp: getComputedStyle(document.documentElement).getPropertyValue("--heat-ramp").trim() };
      probe.remove();
      const stops = getComputedStyle(document.querySelector(".ramp-bar")!).backgroundImage.match(/rgba?\([^)]*\)/g) ?? [];
      const labels = [...document.querySelectorAll(".ramp > span:not(.ramp-bar)")].map((s) => s.textContent);
      return { want, first: stops[0], last: stops[stops.length - 1], labels };
    }, [lessEnd, moreEnd]);
    expect(got.labels, `${theme}: Less on the left, More on the right`).toEqual(["Less", "More"]);
    expect(got.first, `${theme}: the bar starts at ${lessEnd} under Less`).toBe(got.want.less);
    expect(got.last, `${theme}: the bar ends at ${moreEnd} under More`).toBe(got.want.more);
    expect(got.want.ramp, `${theme}: the map reads its ramp the same way`).toBe(theme === "light" ? "rising" : "turned");
  }
});

test("stress cards name the selected mix and set the entered mix in bold", async ({ page }) => {
  await open(page);
  await section(page, "stress");
  const cards = page.locator('[data-testid^="stress-"]');
  await expect(cards).toHaveCount(3);
  for (let i = 0; i < 3; i++) {
    await expect(cards.nth(i).locator(".big")).toHaveText(/^What this mix did: [+−]?\d+\.\d% \(Selected mix\)$/);
    const entered = cards.nth(i).locator("strong");
    await expect(entered).toHaveText(/^The mix you entered: [+−]?\d+\.\d%$/);
    expect(Number(await entered.evaluate((el) => getComputedStyle(el).fontWeight))).toBeGreaterThanOrEqual(700);
    expect(Number(await entered.locator(".num").evaluate((el) => getComputedStyle(el).fontWeight))).toBeGreaterThanOrEqual(700);
  }
});

test("before the first data load the page says so plainly", async ({ page, request }) => {
  await request.post("/__mock/config", { data: { noGeneration: true } });
  await page.goto("/");
  await expect(page.getByTestId("chart")).toContainText("price data is not loaded yet");
  await expect(page.getByTestId("build-retry")).toHaveCount(0);
});

test("trades show dollar changes at every width, and details name a map cell on hover", async ({ page }, testInfo) => {
  await open(page);
  await section(page, "trades");
  const row = page.getByTestId("section-trades").getByRole("listitem").first();
  await expect(row).toContainText("$");
  const money = row.locator(".extra").first();
  await expect(money).toBeVisible();
  expect((await money.boundingBox())!.width).toBeGreaterThan(20);
  if (testInfo.project.name.includes("phone")) return;
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByTestId("details-toggle").click();
  const box = (await page.getByTestId("chart").boundingBox())!;
  // the same spot of the plot as before the box grew a foot for the axis title (CHART_FOOT, 18 px)
  await page.mouse.move(box.x + box.width * 0.6, box.y + (box.height - 18) * 0.75);
  await expect(page.locator('[data-testid="mix-card"][data-for="cell"]')).toContainText(/At risk \d+\.\d%, earning at least \d+\.\d%/);
});

test("the share dialog says the link is for invited testers while preview is on", async ({ page }) => {
  await open(page);
  await page.getByTestId("share-open").click();
  await expect(page.getByRole("dialog")).toContainText("private preview");
  await page.getByTestId("share-email").fill("not-an-address");
  await page.getByTestId("share-send").click();
  await expect(page.getByTestId("share-status")).toHaveText("That address doesn't look right");
});

test("Clear all and Scale to 100% work from the keyboard; the total and Scale show only for % entries off 100%", async ({ page }) => {
  await open(page, "f=SGOV:60,VTIP:32&unit=pct");
  await section(page, "funds");
  const total = page.getByTestId("funds-total");
  const scale = page.getByTestId("funds-scale100");
  const clear = page.getByTestId("funds-clear");
  const amount = (id: string) => page.getByTestId(`fund-row-${id}`).locator("input");
  await expect(total).toHaveText("Total: 92%, 8% to go");
  await expect(scale).toHaveAccessibleName(/^Scale to 100%/);
  await expect(page.getByTestId("point-current")).toHaveCount(0);
  // the total follows the typing
  await amount("VTIP").fill("38.9");
  await expect(total).toHaveText("Total: 98.9%, 1.1% to go");
  await scale.focus();
  await page.keyboard.press("Enter");
  // the button goes away; focus moves on to Clear all, not to the page
  await expect(clear).toBeFocused();
  await expect(amount("SGOV")).toHaveValue("60.67");
  await expect(amount("VTIP")).toHaveValue("39.33");
  await expect(total).toHaveCount(0);
  await expect(scale).toHaveCount(0);
  await expect(page.getByTestId("point-current")).toBeVisible();
  await expect(page.getByTestId("mix-entered-SGOV")).toHaveText("60.7%");
  // Clear all empties the amounts and keeps the funds; the square goes with the amounts
  await expect(clear).toHaveAccessibleName(/^Clear all/);
  await clear.focus();
  await page.keyboard.press("Space");
  await expect(amount("SGOV")).toHaveValue("");
  await expect(amount("VTIP")).toHaveValue("");
  // Clear all turns off; focus moves to the first amount
  await expect(amount("SGOV")).toBeFocused();
  await expect(page.getByTestId("fund-row-SGOV")).toBeVisible();
  await expect(page.getByTestId("fund-row-VTIP")).toBeVisible();
  await expect(page.getByTestId("point-current")).toHaveCount(0);
  await expect(page.getByTestId("funds-entered")).toHaveText("No amounts entered: tickers only.");
  await expect(total).toHaveCount(0);
  await expect(clear).toBeDisabled();
  // in $ there is no total note and no Scale to 100%, whatever the amounts; Clear all stays
  await page.goto("/?f=SGOV:600,VTIP:320&unit=usd");
  await section(page, "funds");
  await expect(page.getByTestId("funds-entered")).toHaveText("$920 entered");
  await expect(total).toHaveCount(0);
  await expect(scale).toHaveCount(0);
  await expect(clear).toBeEnabled();
});

// @desktop-only: the phone strip shows the three figures without the bar (playwright.config.ts).
test("the strip marks Bad, Typical and Good on one scale that holds still as the sliders move @desktop-only", async ({ page }) => {
  // a preset without amounts: the strip is in percent
  await open(page, "u=tsp&lb=5y");
  await expect(page.getByTestId("strip-sub")).toHaveText("over one year");
  const bar = page.getByTestId("range-bar");
  // the scale, and where the bar's track sits on screen (the figures beside it change width)
  const scaleOf = async () => {
    const t = (await bar.locator(".rb-track").boundingBox())!;
    return [await bar.getAttribute("data-lo"), await bar.getAttribute("data-hi"), t.x, t.width];
  };
  const xOf = async (id: string) => {
    const b = (await page.getByTestId(id).boundingBox())!;
    return b.x + b.width / 2;
  };
  await expect(bar).toHaveAttribute("role", "img");
  await expect(bar).toHaveAttribute("aria-label", /fixed scale.*Bad .*Typical .*Good /);
  for (const id of ["range-mark-low", "range-mark-typical", "range-mark-high"]) await expect(page.getByTestId(id)).toBeVisible();
  await expect(page.getByTestId("range-mark-low")).toHaveAttribute("title", /^Bad year: /);
  await expect(page.getByTestId("range-mark-high")).toHaveAttribute("title", /^Good year: /);
  const ends = async () => [await xOf("range-mark-low"), await xOf("range-mark-typical"), await xOf("range-mark-high")];
  const [lo, typ, hi] = await ends();
  expect(lo).toBeLessThan(typ);
  expect(typ).toBeLessThan(hi);
  // the caps are not the dot: thin and taller than wide
  const cap = (await page.getByTestId("range-mark-high").boundingBox())!;
  expect(cap.height).toBeGreaterThan(cap.width * 3);
  const first = await scaleOf();
  const lowBefore = await page.getByTestId("range-low").textContent();
  await page.getByTestId("point-selected").focus();
  for (let i = 0; i < 25; i++) {
    await page.keyboard.press(i < 12 ? "ArrowLeft" : "ArrowRight");
    expect(await scaleOf(), `the scale as the risk slider moves (${i})`).toEqual(first);
  }
  for (let i = 0; i < 25; i++) await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("range-low")).not.toHaveText(lowBefore ?? "");
  expect(await scaleOf(), "the scale after the risk slider moved").toEqual(first);
  expect((await ends())[2]).not.toBeCloseTo(hi, 0);
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press("ArrowDown");
    expect(await scaleOf(), `the scale as the diversification slider moves (${i})`).toEqual(first);
  }
  // Another window has its own scale from its own nodes (the mock's windows share theirs).
  await section(page, "settings");
  await page.getByTestId("lookback-1y").check({ force: true });
  await expect.poll(() => new URL(page.url()).searchParams.get("lb")).toBe("1y");
  await expect(page.getByTestId("point-selected")).toBeVisible();
  expect(await scaleOf(), "the scale of the 1y window").toEqual(first);
});

const signedNumber = (text: string) => Number(text.replace(/[−–]/g, "-").replace(/[+$,%]/g, ""));

test("with amounts in $ or Shares the strip shows the year in dollars on the value entered, the percent beneath", async ({ page }) => {
  await open(page, "f=SGOV:60000,VTIP:38900&unit=pct");
  // in % (these do not add up to 100) the strip is in percent
  await expect(page.getByTestId("strip-sub")).toHaveText("over one year");
  await expect(page.getByTestId("range-low-usd")).toHaveCount(0);
  await section(page, "funds");
  const units = page.getByTestId("unit-toggle").getByRole("radio");
  await units.nth(2).click();
  await expect(page.getByTestId("strip-sub")).toHaveText("over one year on your $98,900");
  for (const id of ["range-low", "range-typical", "range-high"]) {
    const usd = signedNumber(await page.getByTestId(`${id}-usd`).innerText());
    const pct = signedNumber(await page.getByTestId(`${id}-pct`).innerText());
    expect(await page.getByTestId(`${id}-usd`).innerText()).toMatch(/^([−+]\$\d{1,3}(,\d{3})*|\$0)$/);
    expect(await page.getByTestId(`${id}-pct`).innerText()).toMatch(/^[−+]?\d+\.\d%$/);
    // the dollars are the total times the (unrounded) percent: within the percent's rounding
    expect(Math.abs(usd - (98_900 * pct) / 100), id).toBeLessThanOrEqual(98_900 * 0.0005 + 1);
    // the percent sits under the dollar figure, smaller
    const [u, p] = [(await page.getByTestId(`${id}-usd`).boundingBox())!, (await page.getByTestId(`${id}-pct`).boundingBox())!];
    expect(p.y).toBeGreaterThanOrEqual(u.y + u.height - 1);
    expect(p.height).toBeLessThan(u.height);
  }
  await expect(page.getByRole("group", { name: /^Bad year: [−+]?\$[\d,]+, [−+]?\d+\.\d%$/ })).toBeVisible();
  // Shares: valued at the tensor's last close (SGOV 100.42, VTIP 49.87 in the mock)
  await units.nth(0).click();
  await expect(page.getByTestId("strip-sub")).toHaveText("over one year on your $7,965,143");
  // back to %: percent again
  await units.nth(1).click();
  await expect(page.getByTestId("strip-sub")).toHaveText("over one year");
  await expect(page.getByTestId("range-low-usd")).toHaveCount(0);
});

// @desktop-only: the bar is hidden on a phone.
test("in dollars the bar's ends hold still as both sliders move, and its marks sit on its fixed percent scale @desktop-only", async ({ page, request }) => {
  await request.post("/__mock/config", { data: { ranges: true } });
  await open(page, "u=guide2017&lb=5y");
  await expect(page.getByTestId("strip-sub")).toHaveText(/^over one year on your \$[\d,]+$/);
  // the figures' columns are sized in the figure font's character width: measure once it has loaded
  await page.evaluate(() => document.fonts.ready);
  // one read of the page per call, so an exact range arriving between two reads cannot split it
  const state = async () => {
    const got = await page.evaluate(() => {
      const q = (id: string) => document.querySelector(`[data-testid="${id}"]`)!;
      const bar = q("range-bar");
      const t = bar.querySelector(".rb-track")!.getBoundingClientRect();
      const cap = (id: string) => {
        const b = q(`range-mark-${id}`).getBoundingClientRect();
        return { x: b.x + b.width / 2, text: q(`range-${id}-pct`).textContent ?? "" };
      };
      return { left: t.x, right: t.x + t.width, lo: Number(bar.getAttribute("data-lo")), hi: Number(bar.getAttribute("data-hi")), caps: [cap("low"), cap("high")] };
    });
    for (const [i, c] of got.caps.entries()) {
      const pct = signedNumber(c.text) / 100;
      // the cap's centre is where its percent falls on the track's own scale
      const want = got.left + ((pct - got.lo) / (got.hi - got.lo)) * (got.right - got.left);
      expect(Math.abs(c.x - want), `range-mark-${i ? "high" : "low"}`).toBeLessThanOrEqual((got.right - got.left) * 0.0006 + 1.5);
    }
    return { ends: [got.left, got.right, got.lo, got.hi], caps: got.caps.map((c) => c.x) };
  };
  const first = await state();
  const risk = (await page.getByTestId("risk-slider").boundingBox())!;
  const div = (await page.getByTestId("div-slider").boundingBox())!;
  const drags: [number, number, number, number][] = [
    [risk.x + risk.width * 0.55, risk.y + risk.height / 2, risk.x + risk.width * 0.95, risk.y + risk.height / 2],
    [risk.x + risk.width * 0.95, risk.y + risk.height / 2, risk.x + risk.width * 0.4, risk.y + risk.height / 2],
    [div.x + div.width / 2, div.y + div.height * 0.1, div.x + div.width / 2, div.y + div.height * 0.9],
  ];
  let moved = 0;
  for (const [x0, y0, x1, y1] of drags) {
    await page.mouse.move(x0, y0);
    await page.mouse.down();
    for (let k = 1; k <= 12; k++) {
      await page.mouse.move(x0 + ((x1 - x0) * k) / 12, y0 + ((y1 - y0) * k) / 12);
      expect((await state()).ends, "the bar's ends during the drag").toEqual(first.ends);
    }
    await page.mouse.up();
    // the service's exact range arrives once the sliders rest; the ends still hold
    await page.waitForTimeout(600);
    const now = await state();
    expect(now.ends, "the bar's ends after the exact range arrived").toEqual(first.ends);
    if (now.caps.join() !== first.caps.join()) moved += 1;
  }
  expect(moved, "the marks moved with the mix").toBeGreaterThan(0);
  expect(((await (await page.request.get("/__mock/ranges")).json()) as unknown[]).length, "exact ranges were asked").toBeGreaterThan(0);
});

test("the axis title and its details line sit inside the chart frame, under the tick labels, in every look", async ({ page }, testInfo) => {
  const looks = isPhone(testInfo.project.name) ? ["ks-dark", "grid"] : ["ks-dark", "light", "hud", "grid"];
  for (const look of looks) {
    await open(page, `t=${look}&x=1`);
    if ((await page.getByTestId("details-toggle").getAttribute("aria-pressed")) !== "true") await page.getByTestId("details-toggle").click();
    await page.evaluate(() => window.scrollTo(0, 0));
    const title = page.getByTestId("x-title");
    if (isPhone(testInfo.project.name)) {
      // on a phone the axes' technical lines are in the details under the chart
      await expect(title.locator(".tech")).toHaveCount(0);
      await expect(page.getByTestId("details-chart")).toContainText("Standard deviation of yearly return");
    } else await expect(title.locator(".tech")).toHaveText("Standard deviation of yearly return");
    const facts = await page.getByTestId("chart").evaluate((chart) => {
      const c = chart.getBoundingClientRect();
      const t = chart.querySelector(".x-title")!.getBoundingClientRect();
      const ticks = Array.from(chart.querySelectorAll(".axis-x .tick text")).map((el) => el.getBoundingClientRect());
      const border = parseFloat(getComputedStyle(chart).borderBottomWidth) || 0;
      return { frameBottom: c.bottom - border, frameRight: c.right, titleTop: t.top, titleBottom: t.bottom, titleRight: t.right, tickBottom: Math.max(...ticks.map((r) => r.bottom)) };
    });
    expect(facts.titleBottom, `${look}: room under the title`).toBeLessThanOrEqual(facts.frameBottom - 4);
    expect(facts.titleRight, `${look}: inside on the right`).toBeLessThanOrEqual(facts.frameRight);
    expect(facts.titleTop, `${look}: the title is under the tick labels`).toBeGreaterThanOrEqual(facts.tickBottom);
  }
});

test("the family links open in a new tab and say so", async ({ page }) => {
  await open(page);
  const links = page.getByTestId("footer-cta").locator("a");
  await expect(links).toHaveCount(3);
  for (const link of await links.all()) {
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(link).toHaveAccessibleName(/\(opens in a new tab\)$/);
  }
});

test("the sections and their buttons run Funds & amounts, Stress tests, Trades, Settings", async ({ page }) => {
  await open(page);
  const chips = await page.locator(".chips .chip").evaluateAll((els) => els.map((el) => el.getAttribute("data-testid")));
  expect(chips).toEqual(["chip-funds", "chip-stress", "chip-trades", "chip-settings"]);
  const sections = await page.locator('[data-testid^="section-"]').evaluateAll((els) => els.map((el) => el.getAttribute("data-testid")));
  expect(sections.filter((id) => id !== "section-funds")).toEqual(["section-stress", "section-trades", "section-settings"]);
});

// @desktop-only: there is no sidebar on a phone (playwright.config.ts).
test("the sidebar's amount column holds 1,000,000 and the sidebar leaves the chart its room @desktop-only", async ({ page }) => {
  for (const [theme, width] of ["ks-dark", "light", "hud", "grid"].flatMap((t) => [1024, 1280, 1366, 1920].map((w) => [t, w] as const))) {
    await page.setViewportSize({ width, height: 900 });
    await open(page, `t=${theme}&f=VTI:1000000,BND:250000&unit=usd`);
    if ((await page.getByTestId("funds-toggle").getAttribute("aria-expanded")) !== "true") await page.getByTestId("funds-toggle").click();
    const input = page.getByTestId("fund-row-VTI").locator("input");
    await expect(input).toHaveValue("1000000");
    // the field shows the whole number: nothing scrolls inside it
    const fits = () => input.evaluate((el) => (el as HTMLInputElement).scrollWidth <= (el as HTMLInputElement).clientWidth + 1);
    expect(await fits(), `${theme} ${width}: 1000000 fits`).toBe(true);
    if (width >= 1280) {
      // typed with separators, while the field has focus
      await input.fill("1,000,000");
      expect(await fits(), `${theme} ${width}: 1,000,000 fits as typed`).toBe(true);
      await input.blur();
    }
    const side = await boxOf(page, "section-funds");
    expect(side.width, `${theme} ${width}: sidebar width`).toBeLessThanOrEqual(360);
    // the amount head stays on one line (two in the tight 1024 px layout, as before); the narrow
    // percentage heads keep their three lines at most
    const lines = await page.locator(".side .row-head > span").evaluateAll((els) =>
      els.map((el) => {
        const range = document.createRange();
        range.selectNodeContents(el);
        return [el.getAttribute("data-testid") ?? el.className, new Set(Array.from(range.getClientRects()).map((r) => Math.round(r.top))).size] as const;
      }),
    );
    for (const [head, n] of lines) expect(n, `${theme} ${width}: ${head} lines`).toBeLessThanOrEqual(head === "amount-head" ? (width >= 1280 ? 1 : 2) : 3);
  }
});

test("in dollars the strip's parts stay inside it and apart, with the sidebar open or closed and for large amounts", async ({ page }, testInfo) => {
  const phone = isPhone(testInfo.project.name);
  const views = ["u=guide2017&lb=5y", "f=SGOV:60000,VTIP:38900&unit=shares", "f=SGOV:150000,VTIP:20000&unit=shares"];
  const widths = phone ? [null] : [1280, 1366, 1920];
  for (const width of widths) {
    if (width) await page.setViewportSize({ width, height: 860 });
    for (const query of views) {
      for (const side of phone ? [false] : [false, true]) {
        await open(page, query);
        await expect(page.getByTestId("strip-sub")).toHaveText(/on your \$/);
        if (!phone) {
          // the sidebar remembers its state in this browser: set it either way
          const funds = page.getByTestId("section-funds");
          if ((await funds.getAttribute("aria-expanded")) !== String(side)) await page.getByTestId("funds-toggle").click();
          await expect(funds).toHaveAttribute("aria-expanded", String(side));
        }
        await page.evaluate(() => document.fonts.ready);
        const where = `${width ?? "phone"} ${query} sidebar ${side ? "open" : "closed"}`;
        const got = await page.evaluate(() => {
          const r = (el: Element | null) => (el ? el.getBoundingClientRect() : null);
          const strip = document.querySelector(".strip")!;
          const range = document.querySelector(".range")!;
          const pad = parseFloat(getComputedStyle(strip).paddingRight);
          const parts = ["range-low", "range-typical", "range-high"].map((id) => r(document.querySelector(`[data-testid="${id}"]`))!);
          const bar = r(document.querySelector(".rangebar"));
          return {
            overflow: range.scrollWidth - range.clientWidth,
            inside: r(strip)!.right - pad,
            parts: parts.map((p) => ({ left: p.left, right: p.right, top: p.top, bottom: p.bottom })),
            bar: bar && bar.width > 0 ? { left: bar.left, right: bar.right, top: bar.top, bottom: bar.bottom } : null,
            word: r(document.querySelector(".divword"))!,
          };
        });
        expect(got.overflow, `${where}: the figures and the bar fit their row`).toBeLessThanOrEqual(0);
        for (const p of got.parts) expect(p.right, `${where}: a figure inside the strip`).toBeLessThanOrEqual(got.inside + 0.5);
        const apart = (a: { left: number; right: number; top: number; bottom: number }, b: typeof a) => a.right <= b.left + 0.5 || b.right <= a.left + 0.5 || a.bottom <= b.top + 0.5 || b.bottom <= a.top + 0.5;
        for (let i = 0; i < got.parts.length; i++) for (let j = i + 1; j < got.parts.length; j++) expect(apart(got.parts[i], got.parts[j]), `${where}: figures apart`).toBe(true);
        if (got.bar) {
          expect(apart(got.bar, got.word), `${where}: the bar and the diversification word apart`).toBe(true);
          for (const p of got.parts) expect(apart(got.bar, p), `${where}: the bar and a figure apart`).toBe(true);
        }
      }
    }
  }
});

// Menu size by access tier (engines spec 6.2): the page reads its limit from /api/tier.
const mockFunds = (n: number, from = 1) => Array.from({ length: n }, (_, i) => `MOCKF${String(from + i).padStart(3, "0")}`);
const addFund = async (page: Page, id: string) => {
  await page.getByTestId("fund-add").fill(id);
  await page.getByTestId("fund-add").press("Enter");
};

test("the funds picker: the 31st fund is refused for the public and accepted for an admin", async ({ page, request }) => {
  await request.post("/__mock/config", { data: { manySymbols: true } });
  await open(page, `f=${mockFunds(30).join(",")}`);
  await section(page, "funds");
  await expect(page.getByTestId("funds-limit")).toContainText("Up to 30 funds.");
  const before = (await posts(page)).length;
  await addFund(page, "MOCKF031");
  await expect(page.getByTestId("section-funds").getByRole("alert")).toHaveText("A menu holds up to 30 funds.");
  await expect(page.getByTestId("fund-row-MOCKF031")).toHaveCount(0);
  await expect(page.getByTestId("use-menu")).toHaveCount(0);
  expect((await posts(page)).length, "no request for a 31st fund").toBe(before);
  await section(page, "settings");
  await expect(page.getByTestId("admin-tag")).toHaveCount(0);

  await request.post("/__mock/config", { data: { tier: "admin" } });
  await open(page, `f=${mockFunds(30).join(",")}`);
  await section(page, "funds");
  await expect(page.getByTestId("funds-limit")).toContainText("Up to 100 funds.");
  await addFund(page, "MOCKF031");
  await expect(page.getByTestId("fund-row-MOCKF031")).toBeVisible();
  const sent = (await posts(page)).length;
  await page.getByTestId("use-menu").click();
  await expect.poll(async () => (await posts(page)).length).toBe(sent + 1);
  expect((await posts(page)).at(-1)!.funds.length).toBe(31);
  await section(page, "settings");
  await expect(page.getByTestId("admin-tag")).toHaveText("Admin");
});

test("the funds picker: an admin's 101st fund is refused", async ({ page, request }) => {
  await request.post("/__mock/config", { data: { manySymbols: true, tier: "admin" } });
  await open(page, `f=${mockFunds(100).join(",")}`);
  expect((await posts(page)).at(-1)!.funds.length).toBe(100);
  await section(page, "funds");
  await addFund(page, "MOCKF101");
  await expect(page.getByTestId("section-funds").getByRole("alert")).toHaveText("A menu holds up to 100 funds.");
  await expect(page.getByTestId("fund-row-MOCKF101")).toHaveCount(0);
});

test("a shared link over the public limit is refused with a message and the default view opens", async ({ page, request }) => {
  await request.post("/__mock/config", { data: { manySymbols: true } });
  await open(page, `f=${mockFunds(31).join(",")}&lb=5y`);
  await expect(page.getByTestId("link-refused")).toHaveText("This menu has more funds than this site allows (30).");
  expect(await posts(page), "nothing is built for the refused menu").toEqual([]);
  await expect(page.getByTestId("preset-menu")).toHaveAccessibleName(/Example Portfolio/);
  await expect.poll(() => page.url()).not.toContain("MOCKF");
});

// ── The pinned card (owner direction 2026-10-16) ─────────────────────────────────────────────
type Box = { x: number; y: number; width: number; height: number };
const overlap = (a: Box, b: Box) => a.x < b.x + b.width - 0.5 && b.x < a.x + a.width - 0.5 && a.y < b.y + b.height - 0.5 && b.y < a.y + a.height - 0.5;
const centre = async (page: Page, id: string) => {
  const b = await boxOf(page, id);
  return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
};
/** A click with a mouse, a tap with a finger. */
const press = async (page: Page, phone: boolean, x: number, y: number) => {
  if (phone) await page.touchscreen.tap(x, y);
  else await page.mouse.click(x, y);
};
/** A drag of `dx`, `dy` px from (x, y): mouse buttons on a desktop, real touch events on a phone. */
const dragBy = async (page: Page, phone: boolean, x: number, y: number, dx: number, dy: number) => {
  if (!phone) {
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x + dx, y + dy, { steps: 8 });
    await page.mouse.up();
    return;
  }
  const cdp = await page.context().newCDPSession(page);
  const touch = (type: "touchStart" | "touchMove" | "touchEnd", px: number, py: number) => cdp.send("Input.dispatchTouchEvent", { type, touchPoints: type === "touchEnd" ? [] : [{ x: px, y: py, id: 1 }] });
  await touch("touchStart", x, y);
  for (let i = 1; i <= 8; i++) await touch("touchMove", x + (dx * i) / 8, y + (dy * i) / 8);
  await touch("touchEnd", x + dx, y + dy);
  await cdp.detach();
};

test("a click or tap on the selected point pins its card; it follows both sliders and a drag of the point, and keeps its place", async ({ page }, testInfo) => {
  const phone = isPhone(testInfo.project.name);
  await open(page);
  const pinned = page.getByTestId("mix-card-pinned");
  const point = page.getByTestId("point-selected");
  await expect(pinned).toHaveCount(0);
  const p0 = await centre(page, "point-selected");
  await press(page, phone, p0.x, p0.y);
  await expect(pinned).toBeVisible();
  await expect(pinned.getByTestId("mix-card")).toHaveAttribute("data-for", "selected");
  await expect(point).toHaveAttribute("aria-describedby", "mix-card-pinned");
  const chart = await boxOf(page, "chart");
  const where = async () => {
    const b = (await pinned.boundingBox())!;
    return { x: Math.round(b.x - chart.x), y: Math.round(b.y - chart.y), corner: await pinned.getAttribute("data-corner"), box: b };
  };
  const inPlace = async (what: string) => {
    const now = await where();
    const c = await centre(page, "point-selected");
    expect(now.box.x >= chart.x && now.box.x + now.box.width <= chart.x + chart.width + 0.5, `${what}: the card stays inside the chart across`).toBe(true);
    expect(now.box.y >= chart.y, `${what}: the card starts inside the chart`).toBe(true);
    if (!phone) expect({ x: now.x, y: now.y, corner: now.corner }, `${what}: the card keeps its top-left anchor`).toEqual({ x: first.x, y: first.y, corner: "top-left" });
    else {
      // on a phone the card takes the first corner (top-left, top-right, bottom-left, bottom-right)
      // that leaves the point clear; only when none can (data-clear=false) the one farthest from it
      expect(["top-left", "top-right", "bottom-left", "bottom-right"]).toContain(now.corner);
      if ((await pinned.getAttribute("data-clear")) !== "false") {
        const covered = c.x > now.box.x - 8 && c.x < now.box.x + now.box.width + 8 && c.y > now.box.y - 8 && c.y < now.box.y + now.box.height + 8;
        expect(covered, `${what}: the card leaves the point clear`).toBe(false);
      }
    }
    // the legend is covered while the card sits on it
    if (now.corner === "top-left") await expect(page.getByTestId("chart-legend")).toBeHidden();
  };
  const first = await where();
  await expect(pinned, "the default view leaves the point clear").toHaveAttribute("data-clear", "true");
  await inPlace("pinned");
  const text = async () => (await pinned.innerText()).replace(/\s+/g, " ");
  let before = await text();

  // the risk slider, pressed at another place along it
  const rs = await boxOf(page, "risk-slider");
  await press(page, phone, rs.x + rs.width * 0.75, rs.y + rs.height / 2);
  await expect.poll(text, { message: "the card follows the risk slider" }).not.toBe(before);
  await expect(pinned).toBeVisible();
  await inPlace("after the risk slider");
  before = await text();

  // the diversification slider, pressed near its "More diversified" end
  const ds = await boxOf(page, "div-slider");
  const horizontal = (await page.getByTestId("div-slider").getAttribute("aria-orientation")) === "horizontal";
  await press(page, phone, horizontal ? ds.x + ds.width * 0.85 : ds.x + ds.width / 2, horizontal ? ds.y + ds.height / 2 : ds.y + ds.height * 0.85);
  await expect.poll(text, { message: "the card follows the diversification slider" }).not.toBe(before);
  await expect(pinned).toBeVisible();
  await inPlace("after the diversification slider");
  before = await text();

  // a drag of the point moves it and leaves the card pinned
  const p1 = await centre(page, "point-selected");
  await dragBy(page, phone, p1.x, p1.y, -50, 0);
  await expect.poll(text, { message: "the card follows a drag of the point" }).not.toBe(before);
  await expect(pinned).toBeVisible();
  await inPlace("after a drag");
  await expect(pinned).toContainText(/Bad\s*[+−]?\d+\.\d%/);
  await expect(pinned.getByTestId("mix-card-word")).toHaveText(/^(Good|Average|Fair|Poor)$/);

  // a second click or tap on the point lets it go
  const p2 = await centre(page, "point-selected");
  await press(page, phone, p2.x, p2.y);
  await expect(pinned).toHaveCount(0);
  await expect(page.getByTestId("chart-legend")).toBeVisible();
  // on a phone the tap that unpins does not leave the ordinary card open in its place
  if (phone) await expect(page.getByTestId("mix-card")).toHaveCount(0);

  // so does a click or tap outside the chart
  await press(page, phone, p2.x, p2.y);
  await expect(pinned).toBeVisible();
  const adv = await boxOf(page, "range-typical");
  await press(page, phone, adv.x + adv.width / 2, adv.y + adv.height / 2);
  await expect(pinned).toHaveCount(0);

  // and Escape, from the keyboard: Enter on the focused point pins it
  if (!phone) {
    await point.focus();
    await page.keyboard.press("Enter");
    await expect(pinned).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(pinned).toHaveCount(0);
  }
});

test("unpinned, hovering still shows each card by the pointer; pinned, the map's card never sits on the pinned one @desktop-only", async ({ page }) => {
  await open(page);
  const chart = await boxOf(page, "chart");
  const cell = page.locator('[data-testid="mix-card"][data-for="cell"]');
  const pinned = page.getByTestId("mix-card-pinned");
  await page.getByTestId("point-selected").hover({ force: true });
  await expect(page.locator('[role="tooltip"] [data-testid="mix-card"]')).toHaveAttribute("data-for", "selected");
  await page.mouse.move(chart.x + chart.width * 0.6, chart.y + chart.height * 0.75);
  await expect(cell).toBeVisible();
  const p = await centre(page, "point-selected");
  await page.mouse.click(p.x, p.y);
  await expect(pinned).toBeVisible();
  // hovering the point no longer opens a second card for it
  await expect(page.getByTestId("mix-card")).toHaveCount(1);
  const pin = (await pinned.boundingBox())!;
  // across the map, near the pinned card and away from it: one cell card at most, never on the pinned one
  for (const [fx, fy] of [[0.6, 0.75], [0.3, 0.72], [0.25, 0.5], [0.45, 0.4], [0.5, 0.85]]) {
    await page.mouse.move(chart.x + chart.width * fx, chart.y + chart.height * fy);
    await page.waitForTimeout(80);
    if ((await cell.count()) === 0) continue;
    const b = (await cell.boundingBox())!;
    expect(overlap(b, pin), `cell card at ${fx},${fy} sits on the pinned card`).toBe(false);
  }
  await page.mouse.move(chart.x + chart.width * 0.6, chart.y + chart.height * 0.75);
  await expect(cell).toBeVisible();
  await expect(pinned).toBeVisible();
});

test("details on: the legend, the axis titles and their technical lines do not overlap, and no fund tickers touch", async ({ page }, testInfo) => {
  const phone = isPhone(testInfo.project.name);
  const sizes = phone ? [null] : [{ width: 1024, height: 768 }, { width: 1280, height: 800 }, { width: 1366, height: 900 }, { width: 1920, height: 1080 }];
  for (const look of ["ks-dark", "hud", "grid", "light"]) {
    for (const size of sizes) {
      if (size) await page.setViewportSize(size);
      await open(page, `t=${look}&x=1`);
      if ((await page.getByTestId("details-toggle").getAttribute("aria-pressed")) !== "true") await page.getByTestId("details-toggle").click();
      await page.evaluate(() => window.scrollTo(0, 0));
      await expect(page.locator(".fund-dot").first()).toBeVisible();
      const what = `${look} ${size ? size.width : "phone"}`;
      const boxes = await page.getByTestId("chart").evaluate((el) => {
        const r = (q: string) => Array.from(el.querySelectorAll(q)).map((n) => {
          const b = n.getBoundingClientRect();
          return { x: b.x, y: b.y, width: b.width, height: b.height, name: q, text: (n.textContent ?? "").slice(0, 24) };
        });
        return {
          text: [...r(".y-title"), ...r(".x-title"), ...r(".legend-title"), ...r(".legend-tech"), ...r(".legend .ramp"), ...r(".legend .keys")].filter((b) => b.width > 0),
          funds: r(".fund-dot text").filter((b) => b.width > 0),
          dots: el.querySelectorAll(".fund-dot").length,
        };
      });
      for (let i = 0; i < boxes.text.length; i++)
        for (let j = i + 1; j < boxes.text.length; j++) {
          const [a, b] = [boxes.text[i], boxes.text[j]];
          if (a.name.startsWith(".legend") && b.name.startsWith(".legend")) continue; // parts of one stacked block
          expect(overlap(a, b), `${what}: ${a.name} "${a.text}" overlaps ${b.name} "${b.text}"`).toBe(false);
        }
      for (let i = 0; i < boxes.funds.length; i++)
        for (let j = i + 1; j < boxes.funds.length; j++) expect(overlap(boxes.funds[i], boxes.funds[j]), `${what}: tickers ${boxes.funds[i].text} and ${boxes.funds[j].text} overlap`).toBe(false);
      expect(boxes.dots, `${what}: every fund keeps its dot`).toBeGreaterThan(boxes.funds.length - 1);
      if (phone) {
        // the long technical lines are under the chart, in the details; the slider's method opens
        await expect(page.locator(".legend-tech")).toHaveCount(0);
        await expect(page.locator(".y-title .tech")).toHaveCount(0);
        await expect(page.getByTestId("details-chart")).toContainText("Shrunk expected return");
        await expect(page.getByTestId("details-chart")).toContainText("Standard deviation of yearly return");
        await expect(page.getByTestId("details-chart")).toContainText("minimum torsion");
        const method = page.getByTestId("risk-method");
        await expect(method.locator(".readout-tech")).toBeHidden();
        await method.locator("summary").click();
        await expect(method.locator(".readout-tech")).toBeVisible();
      }
    }
  }
  // a hidden ticker is named when its dot is hovered or tapped
  const quiet = page.locator(".fund-dot.is-quiet");
  if ((await quiet.count()) > 0) {
    const id = (await quiet.first().getAttribute("data-fund"))!;
    const dot = (await quiet.first().locator("circle.fund-hit").boundingBox())!;
    await expect(page.getByTestId(`fund-label-${id}`)).toHaveCount(0);
    await press(page, phone, dot.x + dot.width / 2, dot.y + dot.height / 2);
    await expect(page.getByTestId(`fund-label-${id}`)).toBeVisible();
  }
});
