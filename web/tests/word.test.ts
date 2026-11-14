// The diversification figure (owner direction 2026-11-11): the grade words Good, Average, Fair and
// Poor are gone. A mix states its own measure beside the highest found on its portfolio.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";
import { diversificationLine } from "../src/copy";
import { portfolioMath } from "../src/math/portfolio";

const tensor = parseTensor(JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf-8")));
const math = portfolioMath(tensor);
const GRADE = /\b(Good|Average|Fair|Poor)\b|optimi[sz]ed/i;

describe("the diversification figure", () => {
  it("grades no mix: the most diversified and the best-return mix of every column read only their figures", () => {
    for (const [j, front] of tensor.frontier.w.entries()) {
      for (const [kind, w] of [["frontier", front], ["most diversified", tensor.grid.w_div[j]]] as const) {
        const enb = math.stats(w).enb;
        const line = diversificationLine(enb, tensor.enb_ref);
        expect(line, `${kind} mix of column ${j}`).toBe(
          `This mix spreads risk over the equivalent of ${enb.toFixed(1)} independent bets; highest found on this portfolio: ${tensor.enb_ref.toFixed(1)}.`,
        );
        expect(line, `${kind} mix of column ${j}`).not.toMatch(GRADE);
      }
    }
  });

  it("reads each frontier mix's own measure beside the highest found, one decimal each", () => {
    for (const [j, front] of tensor.frontier.w.entries()) {
      const enb = math.stats(front).enb;
      expect(diversificationLine(enb, tensor.enb_ref), `frontier column ${j}`).toBe(
        `This mix spreads risk over the equivalent of ${enb.toFixed(1)} independent bets; highest found on this portfolio: ${tensor.enb_ref.toFixed(1)}.`,
      );
    }
  });

  it("never reads a measure above the highest found, and the most diversified mix reaches it", () => {
    let best = 0;
    for (const [j, front] of tensor.frontier.w.entries()) {
      expect(math.stats(front).enb, `frontier column ${j}`).toBeLessThanOrEqual(tensor.enb_ref + 1e-9);
      best = Math.max(best, math.stats(tensor.grid.w_div[j]).enb);
    }
    expect(best).toBeCloseTo(tensor.enb_ref, 9);
  });
});
