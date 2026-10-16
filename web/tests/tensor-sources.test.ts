// The page's tensor parser accepts every manifest source a served fund can have (spec 5.2, 7).
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";

const RAW = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "guide2017_5y.json"), "utf8"));

function withSource(source: string) {
  const tensor = structuredClone(RAW);
  tensor.universe.funds[0].source = source;
  return tensor;
}

describe("tensor fund sources", () => {
  it.each(["seed", "tiingo", "tsp", "seed+tiingo", "lake"])("accepts %s", (source) => {
    expect(() => parseTensor(withSource(source))).not.toThrow();
  });

  it("refuses an unknown source", () => {
    expect(() => parseTensor(withSource("unknown"))).toThrow();
  });
});
