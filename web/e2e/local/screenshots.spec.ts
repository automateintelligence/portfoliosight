import { expect, test } from "@playwright/test";
import path from "node:path";

// First-screen screenshots for the owner: three looks, desktop and phone (plan task 5.14).
const OUT = path.resolve(process.cwd(), "..", "docs", "reviews");
const THEMES = ["ks-dark", "light", "hud"] as const;

for (const theme of THEMES) {
  test(`first screen ${theme}`, async ({ page, request }, testInfo) => {
    await request.post("/__mock/reset");
    const size = testInfo.project.name.includes("phone") ? "phone" : "desktop";
    await page.goto(`/?t=${theme}`);
    await expect(page.getByTestId("chart-canvas")).toBeVisible();
    await expect(page.getByTestId("point-selected")).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(1600); // the one-time chart reveal has finished
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
  });
}
