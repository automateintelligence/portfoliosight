// @vitest-environment jsdom
// The strip's figures in dollars: the one-year change of the selected mix on the value entered.
import fs from "node:fs";
import path from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";
import { ResultStrip, type DetailFacts } from "../src/controls/ResultStrip";
import { dollars, signedDollars } from "../src/format";
import { amountsValue } from "../src/math/amounts";
import { stripScale } from "../src/math/stripScale";
import { enteredValue, type Row } from "../src/state/store";

const T5 = parseTensor(JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8")));
const FUNDS = T5.universe.funds;

afterEach(cleanup);

describe("dollar figures", () => {
  it("are whole dollars with a sign and thousands separators", () => {
    expect(signedDollars(98_900 * -0.108)).toBe("−$10,681");
    expect(signedDollars(4_210.4)).toBe("+$4,210");
    expect(signedDollars(999.5)).toBe("+$1,000");
    expect(signedDollars(-0.4)).toBe("$0");
    expect(signedDollars(0)).toBe("$0");
    expect(dollars(98_900)).toBe("$98,900");
    expect(dollars(0.2)).toBe("$0");
  });

  it("are abbreviated only above $10M", () => {
    expect(signedDollars(-10_000_000)).toBe("−$10,000,000");
    expect(signedDollars(9_999_999.4)).toBe("+$9,999,999");
    expect(signedDollars(-12_345_678)).toBe("−$12.3M");
    expect(signedDollars(10_049_999)).toBe("+$10.0M");
    expect(signedDollars(2_340_000_000)).toBe("+$2.3B");
    expect(dollars(15_600_000)).toBe("$15.6M");
  });
});

describe("the value entered", () => {
  const close = [100, 50, null];
  it("is the dollars entered, or shares at the last close", () => {
    expect(amountsValue([60_000, 38_900, null], "usd", close)).toEqual({ status: "usd", total: 98_900 });
    expect(amountsValue([10, 4, null], "shares", close)).toEqual({ status: "usd", total: 1_200 });
    // a fund without a last close but no shares in it does not matter
    expect(amountsValue([10, 4, 0], "shares", close)).toEqual({ status: "usd", total: 1_200 });
  });

  it("is unknown when shares are held in a fund without a last close", () => {
    expect(amountsValue([10, null, 3], "shares", close)).toEqual({ status: "unknown_price", unknownPrice: [2] });
    // dollars do not need a price
    expect(amountsValue([10, null, 3], "usd", close)).toEqual({ status: "usd", total: 13 });
  });

  it("stays percent in the % unit and when nothing is entered", () => {
    expect(amountsValue([60, 40, null], "pct", close)).toEqual({ status: "pct" });
    expect(amountsValue([null, null, null], "usd", close)).toEqual({ status: "pct" });
    expect(amountsValue([0, 0, null], "shares", close)).toEqual({ status: "pct" });
  });

  it("counts the funds of the view, at the tensor's last close, and names the funds without one", () => {
    const rows: Row[] = [
      { id: FUNDS[0].id, name: FUNDS[0].id, amount: 10 },
      { id: FUNDS[1].id, name: FUNDS[1].id, amount: 2 },
      { id: "NOTINVIEW", name: "NOTINVIEW", amount: 1_000 },
    ];
    const want = 10 * (FUNDS[0].last_close as number) + 2 * (FUNDS[1].last_close as number);
    const shares = enteredValue({ rows, unit: "shares" }, T5);
    expect(shares.status).toBe("usd");
    expect(shares.status === "usd" && shares.total).toBeCloseTo(want, 9);
    const usd = enteredValue({ rows, unit: "usd" }, T5);
    expect(usd).toEqual({ status: "usd", total: 12 });
    expect(enteredValue({ rows, unit: "pct" }, T5)).toEqual({ status: "pct" });
    const noClose = structuredClone(T5);
    noClose.universe.funds[1] = { ...noClose.universe.funds[1], last_close: null };
    expect(enteredValue({ rows, unit: "shares" }, noClose)).toEqual({ status: "unknown_price", funds: [FUNDS[1].id] });
  });
});

const facts: DetailFacts = { enb: 3, enbRef: 5, mu: 0.06, sigma: 0.1, lookbackStart: "2020-10-01", lookbackEnd: "2025-10-01", rows: 1250, asof: "2026-10-12", notes: [], defaultPoint: "balanced" };
const strip = (value: Parameters<typeof ResultStrip>[0]["value"], details = false) =>
  render(
    <ResultStrip
      low={-0.108}
      typical={0.062}
      high={0.224}
      normal={{ low: -0.1, mid: 0.06, high: 0.22 }}
      scale={stripScale({ min: -0.2, max: 0.35 })}
      value={value}
      word="Good"
      details={details}
      facts={facts}
      staleAsof={null}
      onToggleDetails={() => undefined}
    />,
  );

describe("the strip", () => {
  it("in dollars shows the change on the total with the percent beneath, and says on what", () => {
    strip({ status: "usd", total: 98_900 });
    expect(screen.getByTestId("range-low-usd").textContent).toBe("−$10,681");
    expect(screen.getByTestId("range-low-pct").textContent).toBe("−10.8%");
    expect(screen.getByTestId("range-typical-usd").textContent).toBe("+$6,132");
    expect(screen.getByTestId("range-high-usd").textContent).toBe("+$22,154");
    expect(screen.getByTestId("range-high-pct").textContent).toBe("+22.4%");
    expect(screen.getByTestId("strip-sub").textContent).toBe("over one year on your $98,900");
    // a reader hears both values
    expect(screen.getByRole("group", { name: "Bad year: −$10,681, −10.8%" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Good year: +$22,154, +22.4%" })).toBeTruthy();
    expect(screen.getByTestId("range-bar").getAttribute("aria-label")).toContain("Bad −10.8% (−$10,681)");
    // the bar stays in percent on its fixed scale
    expect(screen.getByTestId("range-bar").getAttribute("data-lo")).toBe(stripScale({ min: -0.2, max: 0.35 }).lo.toFixed(6));
  });

  it("in percent is as before, with no dollar figure", () => {
    strip({ status: "pct" });
    expect(screen.getByTestId("range-low").textContent).toBe("−10.8%");
    expect(screen.queryByTestId("range-low-usd")).toBeNull();
    expect(screen.getByTestId("strip-sub").textContent).toBe("over one year");
    expect(screen.queryByRole("group")).toBeNull();
    cleanup();
    strip(null);
    expect(screen.getByTestId("range-typical").textContent).toBe("+6.2%");
  });

  it("stays in percent when shares cannot be valued, and its details say why", () => {
    strip({ status: "unknown_price", funds: ["VTI", "BND"] }, true);
    expect(screen.getByTestId("range-low").textContent).toBe("−10.8%");
    expect(screen.getByTestId("strip-sub").textContent).toBe("over one year");
    expect(screen.getByTestId("details-no-price").textContent).toBe("Shown in percent: VTI and BND have no latest price, so the shares entered cannot be valued in dollars.");
  });

  it("in large amounts abbreviates above $10M only", () => {
    strip({ status: "usd", total: 120_000_000 });
    expect(screen.getByTestId("range-low-usd").textContent).toBe("−$13.0M");
    expect(screen.getByTestId("strip-sub").textContent).toBe("over one year on your $120.0M");
  });
});
