import { describe, expect, it } from "vitest";
import { PICKER_LIMIT, matchGroup, rankSymbols } from "../src/sections/symbolSearch";

const S = (id: string, name: string | null = id) => ({ id, name });
const symbols = [
  S("AAAC", "AAA Capital Corp"),
  S("AACAF", "AAC Technologies Holdings Inc"),
  S("ACN", "Accenture plc"),
  S("CAT", "Caterpillar Inc."),
  S("C", "Citigroup Inc."),
  S("CB", "Chubb Limited"),
  S("BAC", "Bank of America Corporation"),
  S("SCHD", "Schwab U.S. Dividend Equity ETF"),
  S("AAPL", "Apple Inc."),
  S("APLE", "Apple Hospitality REIT, Inc."),
  S("AAPB", "GraniteShares 2x Long AAPL Daily ETF"),
  S("PAAPL", "Pineapple Holdings"),
  S("VTI", "Vanguard Total Stock Market ETF"),
  S("VBIAX", "VANGUARD BALANCED INDEX FUND ADMIRAL SHARES"),
  S("BND", "Vanguard Total Bond Market ETF"),
  S("VANG", null),
  S("XVANG", "Not a fund"),
  S("BRK-B", "Berkshire Hathaway Inc"),
  S("TSP-L2050", "L 2050"),
  S("NONAME", null),
];
const ids = (query: string, limit?: number) => rankSymbols(symbols, query, limit).map((s) => s.id);

describe("picker search ranking", () => {
  it("puts the exact ticker first, then tickers that start with the query", () => {
    const found = ids("C");
    expect(found[0]).toBe("C");
    expect(found.slice(1, 3)).toEqual(["CB", "CAT"]); // prefix group: shorter first, then A-Z
  });

  it("ranks a name word before a ticker that only contains the query, then name substrings", () => {
    expect(ids("C", 50)).toEqual([
      "C", // the ticker
      "CB", "CAT", // tickers starting with C
      "BAC", "AAAC", // a name word starting with C: Bank of America Corporation, AAA Capital Corp
      "ACN", "SCHD", "AACAF", // tickers containing C
      "VTI", "AAPL", "APLE", "BRK-B", "VBIAX", // names containing c (Stock, Inc., Balanced)
    ]);
  });

  it("finds an exact ticker first, and a company by a word of its name", () => {
    expect(ids("AAPL")[0]).toBe("AAPL");
    expect(ids("aapl").slice(0, 3)).toEqual(["AAPL", "AAPB", "PAAPL"]); // AAPB by name word "AAPL"
    expect(ids("apple").slice(0, 2)).toEqual(["AAPL", "APLE"]);
    expect(ids("apple")).toContain("PAAPL"); // "Pineapple": a name substring, last
    expect(ids("apple").at(-1)).toBe("PAAPL");
  });

  it("finds Vanguard funds by name whatever the name's case", () => {
    const found = ids("vang", 50);
    expect(found[0]).toBe("VANG"); // the ticker itself
    expect(found.slice(1, 4)).toEqual(["BND", "VTI", "VBIAX"]);
    expect(found.slice(4)).toEqual(["XVANG"]); // a ticker containing it
  });

  it("matches tickers without punctuation and names across words", () => {
    expect(ids("brk b")[0]).toBe("BRK-B");
    expect(ids("brk.b")[0]).toBe("BRK-B");
    expect(ids("L 2050")).toEqual(["TSP-L2050"]);
    expect(ids("total stock")).toEqual(["VTI"]);
  });

  it("caps the list and matches nothing for an empty query", () => {
    expect(ids("a").length).toBe(PICKER_LIMIT);
    expect(ids("")).toEqual([]);
    expect(ids("   ")).toEqual([]);
    expect(ids("zzzz")).toEqual([]);
  });

  it("gives each entry its group", () => {
    expect(matchGroup(S("C", "Citigroup Inc."), "c")).toBe(1);
    expect(matchGroup(S("CAT", "Caterpillar Inc."), "c")).toBe(2);
    expect(matchGroup(S("AAAC", "AAA Capital Corp"), "c")).toBe(3);
    expect(matchGroup(S("ACN", "Accenture plc"), "c")).toBe(4);
    expect(matchGroup(S("XYZ", "Pineapple"), "apple")).toBe(5);
    expect(matchGroup(S("XYZ", null), "apple")).toBe(0);
  });

  it("keeps a stable order for equal keys", () => {
    const twice = [S("BBB", "Same Name"), S("AAA", "Same Name")];
    expect(rankSymbols(twice, "same").map((s) => s.id)).toEqual(["AAA", "BBB"]);
  });
});
