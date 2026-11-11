// An uploaded file with shares and dollars values its shares at the price its own dollars give
// (dollars over shares): the starting mix, the strip's value and Trades read the same prices, in
// place of the service's latest closes.
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";
import { fundsWithPrices, tradeDeltas } from "../src/math/amounts";
import { currentMix, enteredValue, type Row } from "../src/state/store";

const RAW = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8"));
const TENSOR = parseTensor(structuredClone(RAW));
const [A, B] = TENSOR.universe.funds;
const aClose = A.last_close as number;
const bClose = B.last_close as number;
/** The same view, but the service has no latest close for fund A (a fund that lags the build day). */
const noCloseForA = parseTensor({ ...structuredClone(RAW), universe: { ...RAW.universe, funds: RAW.universe.funds.map((f: { id: string }) => (f.id === A.id ? { ...f, last_close: null } : f)) } });
const row = (id: string, amount: number | null, price?: number): Row => ({ id, name: id, amount, ...(price === undefined ? {} : { price }) });
// 10 shares of A held at $200 and 10 shares of B at $50: $2,000 and $500, whatever the service's closes are
const snapshot = [row(A.id, 10, 200), row(B.id, 10, 50)];

describe("fundsWithPrices", () => {
  it("puts a row's price in place of the service's close, and leaves a fund without one as the service has it", () => {
    const funds = [{ id: "X", last_close: null }, { id: "Y", last_close: 20 }, { id: "Z", last_close: 8 }, { id: "W" }];
    const rows = [row("X", 1, 50), row("Y", 1, 99), row("W", 1, 7)];
    expect(fundsWithPrices(funds, rows).map((f) => f.last_close ?? null)).toEqual([50, 99, 8, 7]);
  });
});

describe("the starting mix of a file with shares and dollars", () => {
  it("is the file's dollars, even where the service has every close", () => {
    const mix = currentMix({ rows: snapshot, unit: "shares" }, TENSOR);
    expect(mix.status).toBe("ok");
    expect(mix.weights?.[0]).toBeCloseTo(2000 / 2500, 12);
    expect(mix.weights?.[1]).toBeCloseTo(500 / 2500, 12);
  });

  it("is valued where the service has no close for a fund", () => {
    const mix = currentMix({ rows: snapshot, unit: "shares" }, noCloseForA);
    expect(mix.status).toBe("ok");
    expect(mix.weights?.[0]).toBeCloseTo(0.8, 12);
  });

  it("follows an edited share count at the same prices", () => {
    const mix = currentMix({ rows: [row(A.id, 20, 200), row(B.id, 10, 50)], unit: "shares" }, TENSOR);
    expect(mix.weights?.[0]).toBeCloseTo(4000 / 4500, 12);
  });

  it("stays at the service's closes when the rows carry no price, and cannot be valued without a close", () => {
    const plain = [row(A.id, 10), row(B.id, 10)];
    const mix = currentMix({ rows: plain, unit: "shares" }, TENSOR);
    expect(mix.weights?.[0]).toBeCloseTo((10 * aClose) / (10 * aClose + 10 * bClose), 12);
    expect(currentMix({ rows: plain, unit: "shares" }, noCloseForA).status).toBe("unknown_price");
  });

  it("is the dollars as entered in the dollar unit, whatever a row's price", () => {
    const usd = currentMix({ rows: [row(A.id, 300, 5), row(B.id, 100, 5)], unit: "usd" }, TENSOR);
    expect(usd.weights?.[0]).toBeCloseTo(0.75, 12);
  });

  it("is the same value in the strip: the file's dollars in total", () => {
    const value = enteredValue({ rows: snapshot, unit: "shares" }, TENSOR);
    expect(value.status).toBe("usd");
    expect(value.status === "usd" && value.total).toBeCloseTo(2500, 9);
    expect(enteredValue({ rows: [row(A.id, 10), row(B.id, 10)], unit: "shares" }, noCloseForA)).toEqual({ status: "unknown_price", funds: [A.id] });
  });

  it("trades in shares at the same prices, so selling a fund out sells exactly the shares held", () => {
    const funds = fundsWithPrices(TENSOR.universe.funds, snapshot);
    const wNow = currentMix({ rows: snapshot, unit: "shares" }, TENSOR).weights as number[];
    const wSel = TENSOR.universe.funds.map((_, i) => (i === 1 ? 1 : 0));
    const { rows, value } = tradeDeltas({ wNow, wSel, unit: "shares", amounts: TENSOR.universe.funds.map((f) => snapshot.find((r) => r.id === f.id)?.amount ?? null), lastClose: funds.map((f) => f.last_close ?? null) });
    expect(value).toBeCloseTo(2500, 9);
    expect(rows[0].dShares).toBe(-10); // all of A
    expect(rows[1].dShares).toBe(40); // 2,000 more dollars of B at $50
  });
});
