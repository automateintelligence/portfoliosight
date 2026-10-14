import { describe, expect, it } from "vitest";
import { ruleMax, validateCaps } from "../src/sections/Settings";

const draft = (rows: Record<string, [string, string]>) => Object.fromEntries(Object.entries(rows).map(([id, [min, max]]) => [id, { min, max }]));

describe("caps (spec 4.4)", () => {
  it("the default ceiling is clamp(3/N, 25%, 100%)", () => {
    expect(ruleMax(5)).toBeCloseTo(0.6, 12);
    expect(ruleMax(10)).toBeCloseTo(0.3, 12);
    expect(ruleMax(12)).toBe(0.25);
    expect(ruleMax(23)).toBe(0.25);
    expect(ruleMax(2)).toBe(1);
    expect(ruleMax(3)).toBe(1);
  });

  it("accepts a valid table", () => {
    const ids = ["A", "B", "C", "D", "E"];
    expect(validateCaps(ids, draft({ A: ["0", "60"], B: ["0", "60"], C: ["10", "60"], D: ["0", "60"], E: ["0", "10"] }), 60)).toEqual({});
  });

  it("names the fund whose minimum is above its maximum, or whose value is out of range", () => {
    const ids = ["A", "B", "C", "D", "E"];
    const base = { A: ["0", "60"], B: ["0", "60"], C: ["0", "60"], D: ["0", "60"], E: ["0", "60"] } as Record<string, [string, string]>;
    expect(Object.keys(validateCaps(ids, draft({ ...base, B: ["70", "60"] }), 60))).toEqual(["B"]);
    expect(Object.keys(validateCaps(ids, draft({ ...base, C: ["0", "120"] }), 60))).toEqual(["C"]);
    expect(Object.keys(validateCaps(ids, draft({ ...base, D: ["-1", "60"] }), 60))).toEqual(["D"]);
    expect(Object.keys(validateCaps(ids, draft({ ...base, E: ["abc", "60"] }), 60))).toEqual(["E"]);
  });

  it("refuses minimums above 100% in total and maximums that cannot reach 100%", () => {
    const ids = ["A", "B", "C"];
    expect(validateCaps(ids, draft({ A: ["40", "100"], B: ["40", "100"], C: ["30", "100"] }), 100)[""]).toContain("minimums");
    expect(validateCaps(ids, draft({ A: ["0", "30"], B: ["0", "30"], C: ["0", "30"] }), 100)[""]).toContain("maximums");
  });
});
