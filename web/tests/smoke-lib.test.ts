import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  benchmarkRecords, collapsedPosition, decisionDates, frontAt, isTensorBuildPost, mixStats, pacingDelayMs, parsePercent, parseTensorPostLedger, pickCells, readmeProblems,
  redact, rgbBasis, ruleMaxPct, sliderDomain, stressOf, universeHash, walkableColumn, diversificationText, BACKUP_PATH, LAKE_PATH, TENSOR_POST_LIMIT,
  TENSOR_POST_MARGIN_MS, type TensorLike,
} from "../e2e/smoke-lib";
import * as lib from "../e2e/smoke-lib";
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

  it("statistics of a mix and the line that replaced its word", () => {
    for (const j of [3, 20, 40]) {
      const own = mixStats(tensor, tensor.frontier.w[j]);
      const page = math.stats(tensor.frontier.w[j]);
      expect(own.mu).toBeCloseTo(page.mu, 12);
      expect(own.sigma).toBeCloseTo(page.sigma, 12);
      expect(own.enb).toBeCloseTo(page.enb, 9);
    }
    expect(diversificationText(3.84, 5.1)).toBe("This mix spreads risk over the equivalent of 3.8 independent bets; highest found on this portfolio: 5.1.");
    expect(Object.keys(lib)).not.toContain("wordFor");
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

// The site admits TENSOR_POST_LIMIT.posts tensor POSTs per address in any TENSOR_POST_LIMIT.windowMs
// (portfoliosight/api/limiter.py:10-11,27-39). `serverAdmits` is a second, independent copy of that
// sliding window; the pacing is right when a run that waits as `pacingDelayMs` says is never refused.
describe("pacing of live tensor builds", () => {
  const { posts, windowMs } = TENSOR_POST_LIMIT;

  function serverAdmits(admitted: number[], at: number): boolean {
    const inWindow = admitted.filter((t) => t > at - windowMs);
    if (inWindow.length >= posts) return false;
    admitted.push(at);
    return true;
  }

  it("does not wait while fewer than the allowance are on record", () => {
    expect(pacingDelayMs([], 1_000_000)).toBe(0);
    const some = Array.from({ length: posts - 1 }, (_, i) => 1_000_000 + i * 100);
    expect(pacingDelayMs(some, 1_000_500)).toBe(0);
  });

  it("does not count requests older than the window plus the margin", () => {
    const now = 5_000_000;
    const old = Array.from({ length: posts }, (_, i) => now - windowMs - TENSOR_POST_MARGIN_MS - 1 - i);
    expect(pacingDelayMs(old, now)).toBe(0);
  });

  it("waits until the oldest request that would make one too many has left the window, plus the margin", () => {
    const first = 2_000_000;
    const full = Array.from({ length: posts }, (_, i) => first + i * 1_000);
    const now = first + 4_500;
    // the next request needs the first to be out: it leaves at first + window + margin
    expect(pacingDelayMs(full, now)).toBe(first + windowMs + TENSOR_POST_MARGIN_MS - now);
    // two at once need the first two out
    expect(pacingDelayMs(full, now, 2)).toBe(first + 1_000 + windowMs + TENSOR_POST_MARGIN_MS - now);
  });

  it("reads the record in any order", () => {
    const stamps = [1_004_000, 1_000_000, 1_003_000, 1_001_000, 1_002_000];
    expect(pacingDelayMs(stamps, 1_004_500)).toBe(pacingDelayMs([...stamps].sort((a, b) => a - b), 1_004_500));
  });

  it("refuses a batch the allowance can never hold", () => {
    expect(() => pacingDelayMs([], 0, posts + 1)).toThrow(RangeError);
    expect(() => pacingDelayMs([], 0, 0)).toThrow(RangeError);
  });

  it("a run that waits as told is never refused by the site's window, however the sends bunch up", () => {
    // A deterministic mix of quick bursts and pauses; one request or a pair at a time.
    const gaps = [0, 0, 0, 200, 0, 5_000, 0, 0, 30_000, 0, 700, 0, 0, 0, 12_000, 0, 0, 0, 0, 59_999, 0, 0, 1];
    const sentAt: number[] = [];
    const admitted: number[] = [];
    let clock = 9_000_000;
    for (let round = 0; round < 60; round++) {
      clock += gaps[round % gaps.length];
      const count = round % 7 === 3 ? 2 : 1;
      clock += pacingDelayMs(sentAt, clock, count);
      for (let k = 0; k < count; k++) {
        sentAt.push(clock);
        expect(serverAdmits(admitted, clock), `request ${admitted.length + 1} at ${clock - 9_000_000} ms`).toBe(true);
      }
    }
    expect(admitted.length).toBeGreaterThan(60);
  });

  it("without the waits the same run is refused, so the check above is not vacuous", () => {
    const admitted: number[] = [];
    const results = Array.from({ length: posts + 1 }, (_, i) => serverAdmits(admitted, 100 + i));
    expect(results).toEqual([...Array(posts).fill(true), false]);
  });

  it("parses the record: one epoch-milliseconds stamp a line, anything else skipped", () => {
    expect(parseTensorPostLedger("1700000000000\n1700000001500\n")).toEqual([1_700_000_000_000, 1_700_000_001_500]);
    expect(parseTensorPostLedger("1700000000000\n\nnot a stamp\n17000000\n17000000015")).toEqual([1_700_000_000_000, 17_000_000, 17_000_000_015]);
    expect(parseTensorPostLedger("")).toEqual([]);
  });

  it("counts only POSTs to /api/tensors as builds", () => {
    expect(isTensorBuildPost("POST", "https://site.test/api/tensors")).toBe(true);
    expect(isTensorBuildPost("post", "https://api.site.test/api/tensors?x=1")).toBe(true);
    expect(isTensorBuildPost("GET", "https://site.test/api/tensors")).toBe(false);
    expect(isTensorBuildPost("POST", "https://site.test/api/range")).toBe(false);
    expect(isTensorBuildPost("POST", "https://site.test/api/tensors/2026-11-15-1/abc/5y")).toBe(false);
    expect(isTensorBuildPost("POST", "https://site.test/api/share")).toBe(false);
  });
});
