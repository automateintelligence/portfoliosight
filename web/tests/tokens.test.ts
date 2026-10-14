import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { nextTheme, resolveTheme } from "../src/theme/useTheme";

const css = fs.readFileSync(path.resolve(process.cwd(), "src/theme/tokens.css"), "utf8");

// Spec 3.5, verbatim.
const TABLE: Record<string, [string, string, string, string]> = {
  "--bg": ["#141417", "#F3F3F3", "#080506", "#04070B"],
  "--surface": ["#1A1A1E", "#FFFFFF", "#170D0B", "#0A1119"],
  "--elevated": ["#111114", "#FFFFFF", "#1D100D", "#0E1722"],
  "--input": ["#0D0D0F", "#FFFFFF", "#0E0807", "#070C12"],
  "--text": ["#EAE6E2", "#1B1B1B", "#F6EEE3", "#D7F3FA"],
  "--text-2": ["#BEBAB6", "#444444", "#D2BFAB", "#8FB8C6"],
  "--muted": ["#8A8784", "#6B6B6B", "#9A8572", "#5C7E8C"],
  "--border": ["#2A2A2E", "#D9D9D9", "#4A2A20", "#163041"],
  "--accent": ["#C76346", "#0F6CBD", "#D63A18", "#35C9E8"],
  "--accent-dark": ["#A54930", "#0B5394", "#A82A10", "#1D8FA8"],
  "--accent-light": ["#E8907E", "#5AA0E0", "#FF8A52", "#8AE4F5"],
  "--success": ["#46C789", "#107C10", "#F5C451", "#5EF2B0"],
  "--error": ["#EA5023", "#C42B1C", "#FF4D3A", "#FF5C5C"],
  "--warn": ["#E8907E", "#B85C00", "#FFA63D", "#FFB347"],
  "--link": ["#6CB4EE", "#0F6CBD", "#FFC96B", "#8AE4F5"],
  "--shadow": ["0 4px 12px rgba(0,0,0,.3)", "0 1px 3px rgba(0,0,0,.08)", "0 0 14px rgba(232,64,28,.32)", "0 0 12px rgba(53,201,232,.35)"],
  "--heat-0": ["#1A1A1E", "#FFFFFF", "#080506", "#04070B"],
  "--heat-1": ["#4A2A24", "#DCEBF9", "#3D0E08", "#0B2F3F"],
  "--heat-2": ["#A54930", "#8BBDEA", "#B02A10", "#1D8FA8"],
  "--heat-3": ["#E8907E", "#2F86D1", "#F08A24", "#35C9E8"],
  "--heat-4": ["#F5DCC9", "#0B5394", "#FFE39A", "#C8F7FF"],
  "--frontier": ["#EAE6E2", "#1B1B1B", "#FFF4DC", "#C8F7FF"],
  "--mark-selected-fill": ["var(--accent)", "var(--accent)", "#FFD25A", "var(--warn)"],
  "--mark-selected-ring": ["var(--text)", "#FFFFFF", "#FFFFFF", "var(--accent)"],
  "--mark-current": ["var(--link)", "#E07A1F", "#FFFFFF", "var(--error)"],
  "--mark-div": ["var(--success)", "var(--success)", "#9FE6F2", "var(--success)"],
  "--risk-line": ["var(--text-2)", "#6B6B6B", "#FFC96B", "var(--accent)"],
};
const THEMES = ["ks-dark", "light", "hud", "grid"] as const;

/** Declarations of every rule whose selector list names the theme, later rules winning. */
function declarations(theme: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    if (!m[1].includes(`[data-theme="${theme}"]`)) continue;
    for (const d of m[2].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out.set(d[1], d[2].trim());
  }
  return out;
}

describe("theme tokens (spec 3.5)", () => {
  THEMES.forEach((theme, column) => {
    it(`${theme} carries every token of the table`, () => {
      const got = declarations(theme);
      for (const [name, values] of Object.entries(TABLE)) {
        expect(got.get(name)?.toLowerCase(), `${name} in ${theme}`).toBe(values[column].toLowerCase());
      }
    });
  });

  it("ks-dark is also the default on :root", () => {
    expect(css).toMatch(/:root,\s*\[data-theme="ks-dark"\]\s*\{\s*--bg: #141417;/);
  });

  it("reduced motion removes transitions and animations everywhere", () => {
    const block = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(block).toMatch(/\*,\s*\*::before,\s*\*::after/);
    expect(block).toContain("transition-duration: 0s !important");
    expect(block).toContain("animation: none !important");
  });

  it("fonts are self-hosted: no font is loaded from another origin", () => {
    const urls = [...css.matchAll(/url\(([^)]+)\)/g)].map((m) => m[1].replace(/["']/g, ""));
    expect(urls.length).toBeGreaterThanOrEqual(8);
    for (const u of urls) {
      expect(u.startsWith("/fonts/"), u).toBe(true);
      expect(fs.existsSync(path.resolve(process.cwd(), "public", u.slice(1))), `${u} exists`).toBe(true);
    }
  });
});

describe("theme resolution", () => {
  it("the URL wins over storage, storage over the default", () => {
    expect(resolveTheme("hud", "light")).toBe("hud");
    expect(resolveTheme(null, "light")).toBe("light");
    expect(resolveTheme(null, null)).toBe("ks-dark");
    expect(resolveTheme("neon", "sepia")).toBe("ks-dark");
  });
  it("cycles ks-dark, light, hud, grid", () => {
    expect(nextTheme("ks-dark")).toBe("light");
    expect(nextTheme("light")).toBe("hud");
    expect(nextTheme("hud")).toBe("grid");
    expect(nextTheme("grid")).toBe("ks-dark");
  });
});
