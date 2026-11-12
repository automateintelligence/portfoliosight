// The order of the Funds & amounts table (spec 3.3, owner direction 2026-11-11): the pure
// comparison of the six "Sort by" options, and the remembered choice.
import { describe, expect, it } from "vitest";
import { DEFAULT_SORT, readSort, SORT_KEYS, SORT_STORAGE_KEY, sortFunds, writeSort, type SortKey } from "../src/sections/fundsSort";

type R = { id: string; name: string; amount: number | null };
const R = (id: string, name: string, amount: number | null): R => ({ id, name, amount });
const none = { entered: new Map<string, number>(), selected: new Map<string, number>() };
const order = (rows: R[], key: SortKey, mixes = none) => sortFunds(rows, key, mixes).map((r) => r.id);

describe("sortFunds", () => {
  const rows = [R("VTI", "Vanguard Total Stock Market", 30), R("BND", "Vanguard Total Bond Market", 5), R("AGG", "iShares Core US Aggregate Bond", null), R("VXUS", "Vanguard Total International Stock", 120)];

  it("names the six options, As entered first and the default", () => {
    expect([...SORT_KEYS]).toEqual(["entered", "ticker", "name", "amount", "mixEntered", "mixSelected"]);
    expect(DEFAULT_SORT).toBe("entered");
  });

  it("As entered keeps the list as it is and never changes the list it was given", () => {
    const given = [...rows];
    expect(order(rows, "entered")).toEqual(["VTI", "BND", "AGG", "VXUS"]);
    expect(rows).toEqual(given);
    expect(sortFunds(rows, "entered", none)).not.toBe(rows);
  });

  it("Ticker runs A to Z, without regard to case", () => {
    expect(order(rows, "ticker")).toEqual(["AGG", "BND", "VTI", "VXUS"]);
    expect(order([R("vti", "x", null), R("Bnd", "x", null), R("AGG", "x", null)], "ticker")).toEqual(["AGG", "Bnd", "vti"]);
  });

  it("Fund name runs A to Z, without regard to case, and a blank name goes last", () => {
    // iShares..., Vanguard Total Bond, Vanguard Total International, Vanguard Total Stock
    expect(order(rows, "name")).toEqual(["AGG", "BND", "VXUS", "VTI"]);
    expect(order([R("A", "zeta fund", null), R("B", "", null), R("C", "Alpha Fund", null), R("D", "   ", null)], "name")).toEqual(["C", "A", "B", "D"]);
  });

  it("Amount puts the largest first, a zero before a blank, and blanks last", () => {
    expect(order(rows, "amount")).toEqual(["VXUS", "VTI", "BND", "AGG"]);
    expect(order([R("A", "a", null), R("B", "b", 0), R("C", "c", 2)], "amount")).toEqual(["C", "B", "A"]);
  });

  it("Amount is the number in the column, in the unit shown, not what it is worth", () => {
    // 10 shares of a $5 fund are $50; 3 shares of a $100 fund are $300. Shares: the 10 is larger.
    const held = [R("CHEAP", "Cheap", 10), R("DEAR", "Dear", 3)];
    const worth = { entered: new Map([["CHEAP", 50 / 350], ["DEAR", 300 / 350]]), selected: new Map<string, number>() };
    expect(order(held, "amount", worth)).toEqual(["CHEAP", "DEAR"]);
    expect(order(held, "mixEntered", worth)).toEqual(["DEAR", "CHEAP"]);
    // the same numbers read as dollars or as percent sort the same way: the column's own numbers
    expect(order([R("A", "a", 40), R("B", "b", 60)], "amount")).toEqual(["B", "A"]);
  });

  it("Mix entered % puts the largest first and a fund with no entered mix last", () => {
    const mixes = { entered: new Map([["VTI", 0.5], ["BND", 0.2], ["VXUS", 0.3]]), selected: new Map<string, number>() };
    expect(order(rows, "mixEntered", mixes)).toEqual(["VTI", "VXUS", "BND", "AGG"]);
    // nothing entered at all: every fund is blank, so the entered order stays
    expect(order(rows, "mixEntered", none)).toEqual(["VTI", "BND", "AGG", "VXUS"]);
  });

  it("Selected mix % puts the largest first, a zero before a blank, and a fund without a selected weight last", () => {
    const mixes = { entered: new Map<string, number>(), selected: new Map([["VTI", 0.1], ["BND", 0], ["VXUS", 0.9]]) };
    expect(order(rows, "mixSelected", mixes)).toEqual(["VXUS", "VTI", "BND", "AGG"]);
  });

  it("ties keep the entered order, in every option", () => {
    const tied = [R("D", "Same", 5), R("B", "Same", 5), R("A", "Same", 5), R("C", "Same", 5)];
    const mixes = { entered: new Map(tied.map((r) => [r.id, 0.25] as [string, number])), selected: new Map(tied.map((r) => [r.id, 0.25] as [string, number])) };
    for (const key of ["name", "amount", "mixEntered", "mixSelected"] as const) expect(order(tied, key, mixes), key).toEqual(["D", "B", "A", "C"]);
    // a name that differs only by case is the same name
    expect(order([R("Z", "alpha", null), R("Y", "ALPHA", null)], "name")).toEqual(["Z", "Y"]);
  });

  it("two mixes that show as the same percent are a tie, whatever digits sit beyond the screen", () => {
    const third = [R("A", "a", null), R("B", "b", null), R("C", "c", null)];
    const mixes = { entered: new Map<string, number>(), selected: new Map([["A", 0.33333333333333326], ["B", 0.3333333333333334], ["C", 0.3333333333333333]]) };
    expect(order(third, "mixSelected", mixes)).toEqual(["A", "B", "C"]);
    // 33.3% against 33.4% is a real difference
    expect(order(third, "mixSelected", { ...mixes, selected: new Map([["A", 0.333], ["B", 0.334]]) })).toEqual(["B", "A", "C"]);
  });

  it("two amounts that show the same in the field are a tie", () => {
    expect(order([R("A", "a", 10.004), R("B", "b", 10.001)], "amount")).toEqual(["A", "B"]);
    expect(order([R("A", "a", 10.001), R("B", "b", 10.02)], "amount")).toEqual(["B", "A"]);
  });
});

describe("the remembered choice", () => {
  const stored = (value: string | null) => ({ getItem: (key: string) => (key === SORT_STORAGE_KEY ? value : "not ours") });

  it("is read back when it is one of the options", () => {
    for (const key of SORT_KEYS) expect(readSort(stored(key))).toBe(key);
  });

  it("falls back to As entered when nothing is stored, the value is not an option, or storage is not there", () => {
    expect(readSort(stored(null))).toBe("entered");
    expect(readSort(stored("price"))).toBe("entered");
    expect(readSort(stored(""))).toBe("entered");
    expect(readSort(null)).toBe("entered");
  });

  it("falls back to As entered when reading storage throws", () => {
    expect(
      readSort({
        getItem: () => {
          throw new Error("blocked");
        },
      }),
    ).toBe("entered");
  });

  it("writes the choice under one key, and a storage that throws is ignored", () => {
    const written: [string, string][] = [];
    writeSort("amount", { setItem: (k, v) => void written.push([k, v]) });
    expect(written).toEqual([[SORT_STORAGE_KEY, "amount"]]);
    expect(() =>
      writeSort("name", {
        setItem: () => {
          throw new Error("full");
        },
      }),
    ).not.toThrow();
    expect(() => writeSort("name", null)).not.toThrow();
  });
});
