import { describe, expect, it } from "vitest";
import * as copy from "../src/copy";

const flatten = (v: unknown): string[] => (typeof v === "string" ? [v] : v && typeof v === "object" ? Object.values(v).flatMap(flatten) : []);

describe("copy (spec 3.6, 3.7)", () => {
  const defaults = [
    ...flatten(copy.plain),
    ...flatten(copy.family),
    ...flatten(copy.lookbackNames),
    copy.disclaimer,
    copy.capsRule("25", 23),
    copy.excludedFund("VXUS", "2025-03-03", "3-year"),
    copy.stressLine("−31%", "2008 crisis"),
    copy.stressGap(2, 18, "11"),
    copy.staleLine("2026-10-09"),
  ];

  it("default copy holds none of the forbidden words", () => {
    expect(defaults.length).toBeGreaterThan(50);
    for (const word of copy.forbiddenDefault) {
      const re = new RegExp(`\\b${word.replace(/ /g, "\\s+")}\\b`, "i");
      for (const text of defaults) expect(re.test(text), `"${word}" in "${text}"`).toBe(false);
    }
  });

  it("the forbidden-word check is live", () => {
    const re = new RegExp(`\\b${copy.forbiddenDefault[0]}\\b`, "i");
    expect(re.test(copy.enbLine("3.8", "5.1"))).toBe(true);
  });

  it("carries the plain strings of the table verbatim", () => {
    expect(copy.plain.xAxis).toBe("Risk: how much it bounces around in a year");
    expect(copy.plain.yAxis).toBe("Expected return per year");
    expect(copy.plain.heatLegend).toBe("How spread out the risk is");
    expect(copy.plain.riskSlider).toBe("Best-return mix at this risk");
    expect(copy.plain.resultStrip).toBe("Selected mix");
    expect(copy.plain.words).toEqual(["Good", "Average", "Fair", "Poor"]);
    expect(copy.plain.divMoreReturn).toBe("More return");
    expect(copy.plain.divMoreDiversified).toBe("More diversified");
    expect(copy.plain.suggested).toBe("Suggested");
    expect(copy.plain.frontier).toBe("Best return at each level of risk");
    expect(copy.plain.ghosts).toBe("Same menu, different years of history");
    expect(copy.plain.currentMix).toBe("The mix you entered");
    expect(copy.plain.building).toBe("Give us a moment: computing this menu (about 30 seconds)");
    expect(copy.plain.advice).toBe("Historical math, not investment advice.");
    expect(copy.capsRule("25", 23)).toBe("No single fund above 25% (menu of 23)");
    expect(copy.stressLine("−31%", "2008 crisis")).toBe("What this mix did: −31% (2008 crisis)");
    expect(copy.stressGap(2, 18, "11")).toBe("2 of 18 funds (11% of the mix) didn't exist yet; result is for the rest.");
  });

  it("carries the technical strings behind details", () => {
    expect(copy.technical.xAxis).toBe("Standard deviation of yearly return");
    expect(copy.technical.enbName).toBe("effective number of bets, minimum torsion");
    expect(copy.technical.resultStrip).toContain("Estimated central 95% range");
    expect(copy.enbLine("3.8", "5.1")).toBe("spreads risk over the equivalent of 3.8 independent bets; highest found on this menu: 5.1");
  });

  it("carries the compliance copy verbatim", () => {
    expect(copy.disclaimer).toBe(
      "PortfolioSight is an educational tool. All figures are mathematical results computed from historical prices and are hypothetical; past performance does not predict future results. Nothing here is investment, tax or legal advice, and no output is a recommendation to buy or sell anything. PortfolioSight is not registered with the SEC, FINRA or any other regulator. You remain solely responsible for your decisions. Price data: Tiingo and tsp.gov.",
    );
    expect(copy.family.links.map((l) => l.href)).toEqual([
      "https://option-spread-scanner.ingage-bd0.workers.dev",
      "https://automateintelligence.ai",
      "https://securitysight.ai",
    ]);
  });
});
