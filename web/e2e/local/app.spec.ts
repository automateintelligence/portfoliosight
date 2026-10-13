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
const section = async (page: Page, id: string) => {
  await page.getByTestId(`chip-${id}`).click();
  await expect(page.getByTestId(`section-${id}`)).toHaveAttribute("aria-expanded", "true");
};
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
  await page.getByTestId("lookback-3y").check({ force: true });
  await reloaded;
  await expect(page.getByTestId("chart-canvas")).toBeVisible();
  expect(new URL(page.url()).searchParams.get("lb")).toBe("3y");
  expect(new URL(page.url()).searchParams.get("f")).toBe("SGOV:50,VTIP:50");
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
  await expect(page.getByTestId("funds-total")).toHaveText("Adds up to 92%: 8% to go");
  await expect(page.getByTestId("use-menu")).toBeDisabled();
  await expect(page.getByTestId("point-current")).toHaveCount(0);
  await page.getByTestId("fund-row-VTIP").locator("input").fill("40");
  await expect(page.getByTestId("use-menu")).toBeEnabled();
  await expect(page.getByTestId("point-current")).toBeVisible();
  await expect(page.getByTestId("chip-trades")).toBeVisible();
});

test("before the first data load the page says so plainly", async ({ page, request }) => {
  await request.post("/__mock/config", { data: { noGeneration: true } });
  await page.goto("/");
  await expect(page.getByTestId("chart")).toContainText("price data is not loaded yet");
  await expect(page.getByTestId("build-retry")).toHaveCount(0);
});

test("the share dialog says the link is for invited testers while preview is on", async ({ page }) => {
  await open(page);
  await page.getByTestId("share-open").click();
  await expect(page.getByRole("dialog")).toContainText("private preview");
  await page.getByTestId("share-email").fill("not-an-address");
  await page.getByTestId("share-send").click();
  await expect(page.getByTestId("share-status")).toHaveText("That address doesn't look right");
});
