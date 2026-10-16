import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

// Screenshots for the owner (plan task 5.14, and owner feedback 1): the four looks on the first
// screen, desktop and phone, then the views his first round of notes asked for.
const OUT = path.resolve(process.cwd(), "..", "docs", "reviews");
const THEMES = ["ks-dark", "light", "hud", "grid"] as const;

const ready = async (page: Page, query: string) => {
  await page.goto(`/?${query}`);
  await expect(page.getByTestId("chart-canvas")).toBeVisible();
  await expect(page.getByTestId("point-selected")).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(1600); // the one-time chart reveal has finished
};
const feedback = (what: string, theme: string, size: string) => path.join(OUT, `2026-10-13_feedback1_${what}_${theme}_${size}.png`);

for (const theme of THEMES) {
  test(`first screen ${theme}`, async ({ page, request }, testInfo) => {
    await request.post("/__mock/reset");
    const size = testInfo.project.name.includes("phone") ? "phone" : "desktop";
    await ready(page, `t=${theme}`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    if (process.env.PS_SHOT_DRAFT) {
      // Working drafts (not committed): the whole page with every section open.
      const dir = path.resolve(process.cwd(), "e2e", "artifacts");
      await page.screenshot({ path: path.join(dir, `draft_${theme}_${size}.png`), fullPage: false });
      for (const id of ["funds", "trades", "stress", "settings"]) await page.getByTestId(`chip-${id}`).click();
      await page.getByTestId("details-toggle").click();
      await page.waitForTimeout(500);
      await page.screenshot({ path: path.join(dir, `draft_${theme}_${size}_full.png`), fullPage: true });
      return;
    }
    await page.screenshot({ path: path.join(OUT, `2026-10-13_first-screen_${theme}_${size}.png`), fullPage: false });
    if (theme === "hud" || (theme === "grid" && size === "desktop")) await page.screenshot({ path: feedback("first-screen", theme, size) });
  });
}

test("owner feedback 1 views", async ({ page, request }, testInfo) => {
  // Desktop views: the phone project leaves this test out (playwright.config.ts). Drafts cover the first screens only.
  expect(testInfo.project.name).toBe("shots-desktop");
  if (process.env.PS_SHOT_DRAFT) return;
  await request.post("/__mock/reset");
  for (const [size, viewport] of [["desktop", { width: 1366, height: 900 }], ["wide", { width: 1920, height: 1080 }]] as const) {
    await page.setViewportSize(viewport);
    // the sidebar open beside the chart
    await ready(page, "t=ks-dark");
    await page.getByTestId("funds-toggle").click();
    await expect(page.getByTestId("fund-row-VTI")).toBeVisible();
    await page.waitForTimeout(400);
    await page.screenshot({ path: feedback("sidebar-open", "ks-dark", size) });
    await page.getByTestId("funds-toggle").click();
    // ghost frontiers with their labels
    await ready(page, "t=ks-dark&g=1y,10y,ew");
    await expect(page.getByTestId("frontier-label-ew")).toBeVisible();
    await page.screenshot({ path: feedback("ghost-labels", "ks-dark", size) });
    // the three marker cards
    await ready(page, "t=ks-dark");
    for (const mark of ["selected", "current", "div"]) {
      await page.locator(`[data-mark="${mark}"]`).focus();
      await expect(page.getByTestId("mix-card")).toHaveAttribute("data-for", mark);
      await page.waitForTimeout(200);
      await page.screenshot({ path: feedback(`card-${mark}`, "ks-dark", size) });
      await page.locator(`[data-mark="${mark}"]`).blur();
    }
    // the card for the mix under the pointer on the colour map
    const chart = (await page.getByTestId("chart").boundingBox())!;
    await page.mouse.move(chart.x + chart.width * 0.3, chart.y + chart.height * 0.72);
    await expect(page.locator('[data-testid="mix-card"][data-for="cell"]')).toBeVisible();
    await page.screenshot({ path: feedback("card-map", "ks-dark", size) });
    await page.mouse.move(2, 2);
    // the HUD and the Grid at this size (1366 comes from the first-screen tests above)
    if (size === "wide") {
      for (const theme of ["hud", "grid"]) {
        await ready(page, `t=${theme}`);
        await page.screenshot({ path: feedback("first-screen", theme, size) });
      }
      await ready(page, "t=hud&g=10y,ew");
      await page.getByTestId("funds-toggle").click();
      await page.locator('[data-mark="selected"]').focus();
      await page.waitForTimeout(400);
      await page.screenshot({ path: feedback("sidebar-open-card", "hud", size) });
      await page.getByTestId("funds-toggle").click();
    }
  }
});

test("the strip in dollars", async ({ page, request }, testInfo) => {
  // The Example Portfolio's amounts are in $: the strip shows the year in dollars on them.
  await request.post("/__mock/reset");
  const size = testInfo.project.name.includes("phone") ? "phone" : "desktop";
  await ready(page, "u=guide2017&lb=5y&t=ks-dark");
  await expect(page.getByTestId("strip-sub")).toHaveText(/^over one year on your \$[\d,]+$/);
  await page.screenshot({ path: path.join(OUT, `2026-10-15_strip-dollars_ks-dark_${size}.png`) });
});

// The pinned card (owner direction 2026-10-16), details off and on, in the Dark and HUD looks.
for (const theme of ["ks-dark", "hud"] as const) {
  test(`pinned card ${theme}`, async ({ page, request }, testInfo) => {
    if (process.env.PS_SHOT_DRAFT) return;
    await request.post("/__mock/reset");
    const size = testInfo.project.name.includes("phone") ? "phone" : "desktop";
    for (const details of [false, true]) {
      await ready(page, `t=${theme}${details ? "&x=1" : ""}`);
      if ((await page.getByTestId("details-toggle").getAttribute("aria-pressed")) !== String(details)) await page.getByTestId("details-toggle").click();
      await page.evaluate(() => window.scrollTo(0, 0));
      const b = (await page.getByTestId("point-selected").boundingBox())!;
      if (size === "phone") await page.touchscreen.tap(b.x + b.width / 2, b.y + b.height / 2);
      else await page.mouse.click(b.x + b.width / 2, b.y + b.height / 2);
      await expect(page.getByTestId("mix-card-pinned")).toBeVisible();
      if (size === "desktop") await page.mouse.move(2, 2);
      await page.waitForTimeout(300);
      await page.screenshot({ path: path.join(OUT, `2026-10-16_sticky-card_${size}_${theme}${details ? "_details" : ""}.png`) });
    }
  });
}
