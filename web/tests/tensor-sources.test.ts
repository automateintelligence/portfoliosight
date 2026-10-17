// The page's tensor parser: every manifest source a served fund can have (spec 5.2, 7), and both
// tensor schemas (simulation engines spec 7): schema 2 from engine 0.2.0, still served after a
// rollback, and schema 3 with its engines, per-engine ranges and shape.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";

const read = (file: string) => JSON.parse(fs.readFileSync(path.join(__dirname, file), "utf8"));
const RAW = read("../fixtures/guide2017_5y.json");
// A five-fund tensor built by engine 0.2.0 (the rollback generation's engine), small grid.
const OLD = read("tensor-schema2.json");
type Doc = typeof RAW;

function withSource(source: string) {
  const tensor = structuredClone(RAW);
  tensor.universe.funds[0].source = source;
  return tensor;
}

function changed(change: (t: Doc) => void, base: unknown = RAW) {
  const tensor = structuredClone(base);
  change(tensor);
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

describe("tensor schemas", () => {
  it("reads the old bytes: a schema 2 tensor from engine 0.2.0", () => {
    expect(OLD.schema).toBe(2);
    expect(OLD.engine_version).toBe("0.2.0");
    expect(OLD.engines).toBeUndefined();
    const tensor = parseTensor(structuredClone(OLD));
    expect(tensor).toEqual(OLD);
    expect(tensor.universe.funds).toHaveLength(5);
  });

  it("reads the new fixture: schema 3 with both simulation engines", () => {
    const tensor = parseTensor(structuredClone(RAW));
    expect(tensor.schema).toBe(3);
    expect(tensor.range_default).toBe("replay");
    expect(tensor.engines?.garch.status).toBe("ready");
    expect(tensor.engines?.copula).toEqual({ status: "unavailable", reason: "not computed for this menu", method: null });
    expect(Object.keys(tensor.ladder.ranges ?? {}).sort()).toEqual(["garch", "replay"]);
    expect(tensor.shape?.funds.map((fund) => fund.id)).toEqual(tensor.universe.funds.map((fund) => fund.id));
  });

  it("refuses a schema 3 tensor without any of what schema 3 adds", () => {
    const drops: ((t: Doc) => void)[] = [
      (t) => delete t.engines,
      (t) => delete t.range_default,
      (t) => delete t.shape,
      (t) => delete t.frontier.ranges,
      (t) => delete t.ladder.ranges,
      (t) => delete t.entered.ranges,
    ];
    for (const drop of drops) expect(() => parseTensor(changed(drop)), drop.toString()).toThrow();
    expect(() => parseTensor(changed((t) => (t.shape = null)))).toThrow(/ready volatility model/);
  });

  it("refuses a schema 2 tensor that carries schema 3 blocks, and an unknown schema", () => {
    expect(() => parseTensor(changed((t) => (t.engines = RAW.engines), OLD))).toThrow(/schema 2 tensor has no engines/);
    expect(() => parseTensor(changed((t) => (t.frontier.ranges = { replay: { s_safe: 0, bad: [0, 0], typical: [0, 0], good: [0, 0] } }), OLD))).toThrow();
    for (const schema of [1, 4]) expect(() => parseTensor(changed((t) => (t.schema = schema)))).toThrow();
    expect(() => parseTensor(changed((t) => (t.schema = 2)))).toThrow(/schema 2 tensor has no/);
  });

  it("holds the engines block to its rules", () => {
    const bad: ((t: Doc) => void)[] = [
      (t) => (t.engines.garch.method = null), // ready without a method
      (t) => (t.engines.garch.reason = "why"), // ready with a reason
      (t) => (t.engines.copula.reason = null), // unavailable without a reason
      (t) => (t.engines.copula.method = { name: "vine" }), // unavailable with a method
      (t) => (t.engines.replay.status = "unavailable"),
      (t) => (t.engines.garch.method.qse = "ca8c"),
      (t) => (t.engines.garch.method.start = "last"),
      (t) => (t.engines.garch.status = "maybe"),
      (t) => (t.range_default = "copula"), // not a ready engine
      (t) => (t.range_default = "other"),
      (t) => (t.shape.funds[0].status = "fine"),
      (t) => (t.shape.funds[0].omega = -1),
    ];
    for (const change of bad) expect(() => parseTensor(changed(change)), change.toString()).toThrow();
    const unavailable = (t: Doc) => {
      t.engines.garch = { status: "unavailable", reason: "not enough shared history for the volatility model", method: null };
      for (const key of ["frontier", "ladder", "entered"]) delete t[key].ranges.garch;
    };
    expect(() => parseTensor(changed(unavailable))).not.toThrow();
    expect(() => parseTensor(changed((t) => (t.engines.garch = { status: "unavailable", reason: "r", method: null })))).toThrow(/ready engines/);
  });

  it("refuses per-engine blocks whose sizes disagree with n, nx and the levels", () => {
    const short: ((t: Doc) => void)[] = [
      (t) => t.frontier.ranges.garch.bad.pop(),
      (t) => t.frontier.ranges.replay.good.pop(),
      (t) => t.ladder.ranges.garch.typical.pop(),
      (t) => t.ladder.ranges.garch.bad[4].pop(),
      (t) => t.shape.funds.pop(),
      (t) => (t.frontier.ranges.garch.s_safe = t.frontier.x.length),
    ];
    for (const change of short) expect(() => parseTensor(changed(change)), change.toString()).toThrow();
  });
});
