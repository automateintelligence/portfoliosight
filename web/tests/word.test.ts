// The four diversification words (spec 4.6): q = ENB(w) / enb_ref.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";
import { diversificationWord, portfolioMath } from "../src/math/portfolio";

describe("diversificationWord", () => {
  it("maps the seven boundary values of the spec", () => {
    const cases: [number, string][] = [[0.299, "Poor"], [0.3, "Fair"], [0.499, "Fair"], [0.5, "Average"], [0.749, "Average"], [0.75, "Good"], [1.0, "Good"]];
    for (const [q, word] of cases) expect(diversificationWord(q), `q=${q}`).toBe(word);
  });

  it("puts each cut point in the upper band and the value just below it in the lower one", () => {
    const below = (x: number) => x - 1e-12;
    expect([0.3, 0.5, 0.75].map(diversificationWord)).toEqual(["Fair", "Average", "Good"]);
    expect([0.3, 0.5, 0.75].map(below).map(diversificationWord)).toEqual(["Poor", "Fair", "Average"]);
  });

  it("stays inside the four words for anything it is given", () => {
    expect(diversificationWord(0)).toBe("Poor");
    expect(diversificationWord(-0.2)).toBe("Poor");
    expect(diversificationWord(Number.NaN)).toBe("Poor");
    expect(diversificationWord(1.0000001)).toBe("Good");
    const seen = new Set<string>();
    for (let i = 0; i <= 1100; i++) seen.add(diversificationWord(i / 1000));
    expect([...seen].sort()).toEqual(["Average", "Fair", "Good", "Poor"]);
  });

  it("never falls as a mix gets more diversified", () => {
    const rank = { Poor: 0, Fair: 1, Average: 2, Good: 3 };
    let previous = 0;
    for (let i = 0; i <= 1000; i++) {
      const now = rank[diversificationWord(i / 1000)];
      expect(now, `q=${i / 1000}`).toBeGreaterThanOrEqual(previous);
      previous = now;
    }
    expect(previous).toBe(3);
  });

  it("calls the fixture's reference mix Good and reads every frontier mix from its own ENB", () => {
    const tensor = parseTensor(JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf-8")));
    const math = portfolioMath(tensor);
    const words = new Set<string>();
    let best = 0;
    tensor.frontier.w.forEach((front, j) => {
      const enb = math.stats(front).enb;
      const band = enb >= 0.75 * tensor.enb_ref ? "Good" : enb >= 0.5 * tensor.enb_ref ? "Average" : enb >= 0.3 * tensor.enb_ref ? "Fair" : "Poor";
      expect(diversificationWord(enb / tensor.enb_ref), `frontier column ${j}`).toBe(band);
      words.add(band);
      best = Math.max(best, math.stats(tensor.grid.w_div[j]).enb);
    });
    expect(words.size, "the fixture's frontier crosses a cut point").toBeGreaterThan(1);
    // enb_ref is the highest ENB found on the menu, so the mix that reaches it is Good
    expect(best / tensor.enb_ref).toBeCloseTo(1, 9);
    expect(diversificationWord(best / tensor.enb_ref)).toBe("Good");
  });
});
