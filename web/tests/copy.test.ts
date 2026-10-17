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
    copy.stressLine("−31%"),
    copy.stressGap(2, 18, "11"),
    copy.staleLine("2026-10-09"),
    ...flatten(copy.engineNames),
    ...flatten(copy.engineDescriptions),
    ...flatten(copy.enginePlain),
    copy.heldConstantLine(["TSP-G", "SGOV"]),
    copy.poolLine(2352),
    copy.notComputed,
  ];

  it("default copy holds none of the forbidden words", () => {
    expect(defaults.length).toBeGreaterThan(50);
    for (const word of copy.forbiddenDefault) {
      const re = new RegExp(`\\b${word.replace(/ /g, "\\s+")}\\b`, "i");
      for (const text of defaults) expect(re.test(text), `"${word}" in "${text}"`).toBe(false);
    }
  });

  it("the engine words stay out of default copy: GARCH, vine, residual, expected shortfall, entropy", () => {
    for (const word of ["GARCH", "vine", "residual", "expected shortfall", "entropy"]) expect(copy.forbiddenDefault, word).toContain(word);
  });

  it("'Copula' is the control's label and the engine tag, and nowhere else in default copy", () => {
    expect(copy.engineNames.copula).toBe("Copula");
    const { copula: _label, ...others } = copy.engineNames;
    void _label;
    const rest = [...defaults.filter((text) => !Object.values(copy.engineNames).includes(text)), ...flatten(others)];
    for (const text of rest) expect(/copula/i.test(text), `"Copula" in "${text}"`).toBe(false);
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
    expect(copy.plain.optimized).toBe("Optimized");
    expect(copy.plain.noLimits).toBe("No limits");
    expect(copy.lookbackLine.nolimits).toBe("No allocation limits");
    expect(copy.plain.noAllocationLimits).toBe("No allocation limits");
    expect([copy.plain.rangeLow, copy.plain.rangeTypical, copy.plain.rangeHigh]).toEqual(["Bad", "Typical", "Good"]);
    expect([copy.plain.riskBad, copy.plain.riskTypical, copy.plain.resultStripSuffix]).toEqual(["Bad year", "Typical year", "over one year"]);
    expect(copy.plain.frontier).toBe("Best return at each level of risk");
    expect(copy.plain.ghosts).toBe("Same menu, different years of history");
    expect(copy.plain.currentMix).toBe("The mix you entered");
    expect(copy.plain.building).toBe("Give us a moment: computing this menu (about 30 seconds)");
    expect(copy.plain.advice).toBe("Historical math, not investment advice.");
    expect(copy.capsRule("25", 23)).toBe("No single fund above 25% (menu of 23)");
    expect(copy.stressLine("−31%")).toBe("What this mix did: −31% (Selected mix)");
    expect(copy.stressGap(2, 18, "11")).toBe("2 of 18 funds (11% of the mix) didn't exist yet; result is for the rest.");
  });

  it("names and describes the three engines as the Simulation control reads (engines spec 6)", () => {
    expect(copy.engineNames).toEqual({ replay: "History replay", garch: "Volatility model", copula: "Copula" });
    expect(copy.engineDescriptions).toEqual({
      replay: "replays runs of real days from this history window",
      garch: "fitted volatility clustering and fat tails; funds' shocks replayed together from up to ten years",
      copula: "fitted dependence between funds, including joint bad days the history does not contain",
    });
    expect(copy.plain.simulation).toBe("Simulation");
    expect(copy.enginePlain.garch).toBe(
      "Fitted volatility and fat tails per fund; funds' shocks replayed together from up to ten years; centred and scaled to this view's expected return and risk",
    );
    expect(copy.enginePlain.copula).toBe("As the volatility model, with the funds' co-movement fitted, including joint bad days beyond those in the history");
    expect(copy.heldConstantLine(["TSP-G", "SGOV"])).toBe("Volatility held constant: TSP-G, SGOV");
    expect(copy.heldConstantWhy).toBe("near-constant (daily sd < 0.03%) or fewer than 252 days");
    expect(copy.poolLine(2352)).toBe("funds' shocks replayed together from 2,352 shared days");
  });

  it("the technical method lines are behind details and carry the technical names", () => {
    const method = { shapeRows: 2520, paths: 2000, horizonDays: 252 };
    // replay: as today
    expect(copy.engineTechnical.replay(method, [])).toBe(copy.technical.resultStrip);
    const garch = copy.engineTechnical.garch(method, []);
    expect(garch).toContain("GARCH(1,1)-t per fund on up to 2,520 days");
    expect(garch).toContain("2,000 × 252-day paths");
    expect(garch).toContain("long-run variance start");
    expect(garch).not.toContain("constant volatility for");
    expect(copy.engineTechnical.garch(method, ["TSP-G", "SGOV"])).toContain("constant volatility for: TSP-G, SGOV");
    expect(copy.engineTechnical.copula(method, [])).toContain("R-vine copula");
    // the check on default copy is live for each: the technical lines would trip it
    const forbidden = copy.forbiddenDefault.map((word) => new RegExp(`\\b${word.replace(/ /g, "\\s+")}\\b`, "i"));
    expect(forbidden.some((re) => re.test(garch))).toBe(true);
    expect(forbidden.some((re) => re.test(copy.engineTechnical.copula(method, [])))).toBe(true);
    expect(copy.engineRiskSliderTechnical.replay).toBe(copy.technical.riskSlider);
    expect(copy.engineRiskSliderTechnical.garch).toMatch(/volatility model/);
  });

  it("carries the technical strings behind details", () => {
    expect(copy.technical.xAxis).toBe("Standard deviation of yearly return");
    expect(copy.technical.enbName).toBe("effective number of bets, minimum torsion");
    // A-PS-48 requires this technical name behind details
    expect(copy.technical.resultStrip).toMatch(/^Estimated central 95% range of the one-year return: .* over 2,000 one-year paths/);
    expect(copy.technical.bellCurve("−9.0%", "+6.0%", "+21.0%")).toBe("Textbook bell-curve figure (normal, μ ± 1.96σ): −9.0% to +21.0% around +6.0%");
    expect(copy.technical.optimized.balanced).toContain("balanced point");
    // nothing on the page speaks of six months any more
    const all = JSON.stringify({ plain: copy.plain, technical: { ...copy.technical, bellCurve: "", cellPlace: "" } });
    expect(all).not.toMatch(/six|6 months|six-month/i);
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
