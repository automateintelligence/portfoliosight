import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  benchmarkRecords, collapsedPosition, decisionDates, frontAt, mixStats, parsePercent, pickCells, readmeProblems, redact, rgbBasis, ruleMaxPct,
  sliderDomain, stressOf, universeHash, walkableColumn, wordFor, BACKUP_PATH, LAKE_PATH, type TensorLike,
} from "../e2e/smoke-lib";
import { portfolioMath } from "../src/math/portfolio";
import { parseTensor } from "../src/api/client";

const here = path.dirname(fileURLToPath(import.meta.url));
const raw = JSON.parse(fs.readFileSync(path.join(here, "..", "fixtures", "guide2017_5y.json"), "utf8"));
const tensor = raw as TensorLike;

describe("redact", () => {
  const env = { PS_GATE_SECRET: "abc123def456", PS_SHARE_TEST_RECIPIENT: "someone@example.org", TIINGO_API_KEY: "abc" };

  it("replaces secret values wherever they appear", () => {
    const out = redact("x-ps-gate: abc123def456 sent to someone@example.org (abc123def456)", env);
    expect(out).toBe("x-ps-gate: [redacted] sent to [redacted] ([redacted])");
  });

  it("replaces the value of a k= query parameter, whatever it is", () => {
    expect(redact("GET https://site.test/?k=whatever-it-is&u=tsp", {})).toBe("GET https://site.test/?k=[redacted]&u=tsp");
    expect(redact("https://site.test/?u=tsp&k=zzz#top", {})).toBe("https://site.test/?u=tsp&k=[redacted]#top");
  });

  it("leaves other text alone and ignores values too short to be secrets", () => {
    expect(redact("abc risk=0.4 link=1", env)).toBe("abc risk=0.4 link=1");
  });
});

describe("universeHash", () => {
  it("equals the engine's hash for the same policy, in any order", () => {
    const four = ["VOO", "BND", "VNQ", "SGOV"].map((id) => ({ id }));
    expect(universeHash(four)).toBe("e0b92be3558524e3");
    expect(universeHash([...four].reverse())).toBe("e0b92be3558524e3");
    expect(universeHash([{ id: "VTI", max: 0.1 }, { id: "BND", min: 0.05 }])).toBe("7cdfb001688ed117");
  });

  it("reproduces the fixture tensor's own hash", () => {
    const ids = [...raw.universe.funds, ...raw.universe.excluded].map((f: { id: string }) => f.id);
    expect(universeHash(ids.map((id: string) => ({ id })))).toBe(raw.universe.hash);
  });
});

describe("the test's own tensor math agrees with the page's", () => {
  const math = portfolioMath(parseTensor(raw));

  it("slider domain and frontier figures", () => {
    const { sSafe, sMax } = sliderDomain(tensor);
    expect(sSafe).toBe(math.riskSliderDomain().s_safe);
    expect(sMax).toBe(math.riskSliderDomain().s_max);
    for (const s of [sSafe, 10, 23.4, sMax]) {
      const range = math.yearRange(s, 0);
      const own = frontAt(tensor, s);
      expect(Math.abs(own.low - 100 * range.low)).toBeLessThan(0.05);
      expect(Math.abs(own.typical - 100 * range.typical)).toBeLessThan(0.05);
    }
  });

  it("statistics and the word of a mix", () => {
    for (const j of [3, 20, 40]) {
      const own = mixStats(tensor, tensor.frontier.w[j]);
      const page = math.stats(tensor.frontier.w[j]);
      expect(own.mu).toBeCloseTo(page.mu, 12);
      expect(own.sigma).toBeCloseTo(page.sigma, 12);
      expect(own.enb).toBeCloseTo(page.enb, 9);
    }
    expect([0.75, 0.74, 0.5, 0.49, 0.3, 0.29].map(wordFor)).toEqual(["Good", "Average", "Average", "Fair", "Fair", "Poor"]);
  });

  it("stress return, coverage and the default cap rule", () => {
    expect(stressOf([0.5, 0.5], [0.1, null])).toEqual({ value: 0.1, covered: 0.5, missing: 1 });
    expect(stressOf([0.4, 0.6], [0.1, null]).value).toBeNull();
    expect(stressOf([0.25, 0.75], [0.04, -0.02]).value).toBeCloseTo(-0.005, 12);
    expect([5, 22, 23, 2].map(ruleMaxPct)).toEqual([60, 25, 25, 100]);
  });

  it("columns for the diversification checks and cells for the heatmap", () => {
    const j = walkableColumn(tensor);
    expect(Number.isInteger(j) && tensor.grid.k_div[j] >= 0 && j >= sliderDomain(tensor).sSafe).toBe(true);
    expect(collapsedPosition(tensor)).toBeNull();
    const collapsed = structuredClone(tensor);
    collapsed.grid.k_div[30] = -1;
    expect(collapsedPosition(collapsed)).toBe(30);
    const cells = pickCells(tensor);
    expect(cells.length).toBe(20);
    expect(cells.every((c) => tensor.grid.z[c.j][c.k] !== null)).toBe(true);
    expect(cells[19].q).toBeGreaterThan(cells[0].q);
  });

  it("percent parsing and the heat ramp", () => {
    expect(parsePercent("Bad six months−9.4%")).toBe(-9.4);
    expect(parsePercent("Typical six months +3.1%")).toBe(3.1);
    expect(() => parsePercent("no figure")).toThrow();
    const ramp = rgbBasis([[0, 0, 0], [10, 20, 30], [20, 40, 60], [30, 60, 90], [40, 80, 120]]);
    expect(ramp(0).map(Math.round)).toEqual([0, 0, 0]);
    expect(ramp(0.5).map(Math.round)).toEqual([20, 40, 60]);
    expect(ramp(1).map(Math.round)).toEqual([40, 80, 120]);
  });
});

describe("runbook and README rules", () => {
  it("reads the benchmark lines and the dated decision under step 3", () => {
    const runbook = [
      "## Step 3: owner decision",
      "Owner decision 2026-10-13: Tiingo data under personal use for development and testing.",
      "## Measured",
      "- 23-fund build: 41.2 s on the 48x32 grid",
      "- after the fallback: 18 seconds, NX = 32, NY = 24",
      "- six lookbacks: 95 s",
    ].join("\n");
    expect(benchmarkRecords(runbook).map((r) => [r.seconds, r.grid])).toEqual([[41.2, [48, 32]], [18, [32, 24]]]);
    expect(decisionDates(runbook)).toEqual(["2026-10-13"]);
    expect(decisionDates("personal use decided 2026-10-13")).toEqual([]);
    expect(decisionDates("### 3. Owner\npersonal use, 2026-02-31")).toEqual([]);
  });

  it("accepts a README that follows DoD 27 and names what is wrong with one that does not", () => {
    const good = [
      "# PortfolioSight",
      "Layout: portfoliosight/ web/ deploy/ scripts/ data/ docs/",
      "Commands: ruff check . && ruff format --check . && pyright . && pytest; npm run lint && npm run typecheck && npm test; scripts/smoke.sh; scripts/deploy_ks001.sh",
      `- The lake is the WSL working copy \`${LAKE_PATH}/\`;`,
      "  `/mnt/d/tft-quantile-forecaster` is only QSE's mirror of it.",
      `- R2 is canonical; \`${BACKUP_PATH}\` is the laptop backup of the bucket.`,
    ].join("\n");
    expect(readmeProblems(good)).toEqual([]);
    const bad = `${good.replace("only QSE's mirror of it", "the lake")}\n${"x\n".repeat(60)}`;
    const problems = readmeProblems(bad);
    expect(problems.some((p) => p.includes("more than 60"))).toBe(true);
    expect(problems.some((p) => p.includes("mirror"))).toBe(true);
    expect(readmeProblems("# PortfolioSight").length).toBeGreaterThan(5);
  });
});
