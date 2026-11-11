// The fund-list CSV: parsing, which amount column is used, the notes for columns that disagree,
// and the limits. Pure functions; nothing here touches the page.
import { describe, expect, it } from "vitest";
import { menuFull, menuNeedsMore } from "../src/copy";
import {
  dollarsVsShares,
  parseFundsCsv,
  parseNumber,
  percentVsDollars,
  percentVsShares,
  resolveUpload,
  settlePending,
  TEMPLATE_CSV,
  TEMPLATE_FILENAME,
  type FundLine,
} from "../src/sections/fundsCsv";

const lines = (text: string): FundLine[] => {
  const parsed = parseFundsCsv(text);
  if (!parsed.ok) throw new Error(parsed.error);
  return parsed.lines;
};
const failure = (text: string): string => {
  const parsed = parseFundsCsv(text);
  if (parsed.ok) throw new Error("expected a refusal");
  return parsed.error;
};
const line = (ticker: string, shares: number | null, dollars: number | null, percent: number | null): FundLine => ({ ticker, shares, dollars, percent });
const catalog = (...ids: string[]) => ids.map((id) => ({ id, name: `${id} Fund` }));
const LIMITS = { min: 2, max: 30 };
const BOM = String.fromCharCode(0xfeff); // as Excel writes at the start of a CSV file

describe("the template", () => {
  it("is the five lines of the brief, and parses back to the four funds it shows", () => {
    expect(TEMPLATE_FILENAME).toBe("portfoliosight-template.csv");
    expect(TEMPLATE_CSV).toBe("ticker,shares,dollars,percent\nVTI,,10000,40\nVXUS,,5000,20\nBND,,7500,30\nVNQ,,2500,10\n");
    expect(lines(TEMPLATE_CSV)).toEqual([line("VTI", null, 10000, 40), line("VXUS", null, 5000, 20), line("BND", null, 7500, 30), line("VNQ", null, 2500, 10)]);
  });
});

describe("parseNumber", () => {
  it("accepts $, %, thousands commas and spaces", () => {
    for (const [text, value] of [
      ["12", 12],
      ["12.5", 12.5],
      [".5", 0.5],
      ["$1,234.50", 1234.5],
      ["40%", 40],
      [" $ 10,000 ", 10000],
      ["1 000", 1000],
      ["1,000,000", 1000000],
      ["0", 0],
      ["0.0", 0],
    ] as const) {
      expect(parseNumber(text), text).toEqual({ ok: true, value });
    }
  });
  it("reads a blank cell as no amount", () => {
    expect(parseNumber("")).toEqual({ ok: true, value: null });
    expect(parseNumber("   ")).toEqual({ ok: true, value: null });
  });
  it("refuses what is not a plain number", () => {
    for (const text of ["abc", "$", "%", "1,00", "12,34,567", "1e3", "1.2.3", "--5", "N/A", "12 shares"]) {
      expect(parseNumber(text), text).toEqual({ ok: false, reason: "number" });
    }
  });
  it("refuses a negative amount, however it is written", () => {
    for (const text of ["-5", "−5", "(5)", "-$1,000", "($1,000.00)", "-0.5%"]) {
      expect(parseNumber(text), text).toEqual({ ok: false, reason: "negative" });
    }
  });
  it("takes a minus zero as zero", () => {
    expect(parseNumber("-0")).toEqual({ ok: true, value: 0 });
  });
});

describe("parseFundsCsv", () => {
  it("reads header names without regard to case or surrounding spaces, in any order and any subset", () => {
    expect(lines(" PERCENT , Ticker \n40,vti\n60,bnd\n")).toEqual([line("VTI", null, null, 40), line("BND", null, null, 60)]);
    expect(lines("Shares,TICKER,Dollars\n10,VTI,\n,BND,500\n")).toEqual([line("VTI", 10, null, null), line("BND", null, 500, null)]);
  });
  it("needs only the ticker column", () => {
    expect(lines("ticker\nvti\nbnd\n")).toEqual([line("VTI", null, null, null), line("BND", null, null, null)]);
  });
  it("trims and upper-cases tickers", () => {
    expect(lines("ticker\n  brk-b  \n")[0].ticker).toBe("BRK-B");
  });
  it("keeps each ticker as the file writes it, separators and all, and adds the rows of one spelling", () => {
    expect(lines("ticker,shares\nBRK/B,1\nbf.b,3\nBRK.B,2\nBRK-B,4\nbrk/b,5\nry.to,6\n")).toEqual([
      line("BRK/B", 6, null, null),
      line("BF.B", 3, null, null),
      line("BRK.B", 2, null, null),
      line("BRK-B", 4, null, null),
      line("RY.TO", 6, null, null),
    ]);
  });
  it("names a class share in a row's refusal as the file wrote it", () => {
    expect(failure("ticker,shares\nVTI,1\nBRK/B,ten\n")).toBe('Row 3 (BRK/B): "ten" in the shares column is not a number.');
    expect(failure("ticker,percent\nbrk.b,-5\n")).toBe("Row 2 (BRK.B): the percent column can't be negative.");
  });
  it("ignores blank lines and rows of nothing but commas, and a missing final newline", () => {
    expect(lines("ticker,shares\n\nVTI,1\n,\n   ,  \n\nBND,2")).toEqual([line("VTI", 1, null, null), line("BND", 2, null, null)]);
  });
  it("reads CRLF line ends, a byte order mark and quoted cells", () => {
    expect(lines(`${BOM}ticker,dollars\r\n"VTI","$1,000"\r\nBND,"2,000.50"\r\n`)).toEqual([line("VTI", null, 1000, null), line("BND", null, 2000.5, null)]);
  });
  it("reads a semicolon- or tab-separated file as well", () => {
    expect(lines("ticker;shares\nVTI;10\n")).toEqual([line("VTI", 10, null, null)]);
    expect(lines("ticker\tshares\nVTI\t10\n")).toEqual([line("VTI", 10, null, null)]);
  });
  it("ignores columns it does not know, and a row shorter than the header", () => {
    expect(lines("name,ticker,shares,dollars\nTotal Market,VTI,5\n")).toEqual([line("VTI", 5, null, null)]);
  });
  it("adds the amounts of a ticker that appears twice, column by column", () => {
    expect(lines("ticker,shares,dollars,percent\nVTI,10,100,\nBND,1,,\nVTI,5,,25\nVTI,0.5,50,\n")).toEqual([
      line("VTI", 15.5, 150, 25),
      line("BND", 1, null, null),
    ]);
  });
  it("keeps funds in the order of their first row", () => {
    expect(lines("ticker\nB\nA\nB\nC\n").map((l) => l.ticker)).toEqual(["B", "A", "C"]);
  });
  it("refuses a file without a ticker column, and says so", () => {
    expect(failure("symbol,shares\nVTI,1\n")).toBe("The file needs a column named ticker.");
    expect(failure("VTI\nBND\n")).toBe("The file needs a column named ticker.");
    expect(failure("")).toBe("The file needs a column named ticker.");
  });
  it("refuses a file with no funds under the header", () => {
    expect(failure("ticker,shares\n")).toBe("The file has no funds in it.");
    expect(failure("ticker,shares\n\n,\n")).toBe("The file has no funds in it.");
  });
  it("refuses a column named twice", () => {
    expect(failure("ticker,shares,Shares\nVTI,1,2\n")).toBe("The file has two columns named shares.");
  });
  it("refuses a non-numeric amount, naming the row and the fund", () => {
    expect(failure("ticker,shares,dollars\nVTI,10,\nBND,ten,\n")).toBe('Row 3 (BND): "ten" in the shares column is not a number.');
    expect(failure("ticker,dollars\nVTI,12 dollars\n")).toBe('Row 2 (VTI): "12 dollars" in the dollars column is not a number.');
  });
  it("refuses a negative amount, naming the row and the fund", () => {
    expect(failure("ticker,percent\nVTI,50\nBND,-5\n")).toBe("Row 3 (BND): the percent column can't be negative.");
  });
  it("counts the row as the file shows it, blank lines included", () => {
    expect(failure("ticker,shares\n\nVTI,1\n\nBND,x\n")).toBe('Row 5 (BND): "x" in the shares column is not a number.');
  });
  it("refuses an amount on a row with no ticker", () => {
    expect(failure("ticker,shares\nVTI,1\n,5\n")).toBe("Row 3 has an amount but no ticker.");
  });
  it("refuses a badly quoted file", () => {
    expect(failure('ticker,shares\n"VTI,1\n')).toBe("The file could not be read as a CSV.");
  });
  it("refuses a row with more values than the header has columns, as an unquoted thousands comma makes, naming the row", () => {
    const why = (row: number) => `Row ${row} has more values than the header has columns. Put numbers that contain commas in quotes or remove those commas, and remove any extra comma at the end of a row.`;
    expect(failure("ticker,shares,dollars\nVTI,1,000,\n")).toBe(why(2));
    expect(failure("ticker,shares,dollars\nBND,5,\n\nVTI,1,000,500\n")).toBe(why(4));
    expect(failure("ticker,dollars\nVTI,10,000\n")).toBe(why(2));
  });
  it("reads the same number quoted, and a file whose every line ends in a comma", () => {
    expect(lines('ticker,shares,dollars\nVTI,"1,000",\n')).toEqual([line("VTI", 1000, null, null)]);
    expect(lines("ticker,shares,dollars,\nVTI,1,,\nBND,,500,\n")).toEqual([line("VTI", 1, null, null), line("BND", null, 500, null)]);
  });
  it("reads values under unnamed columns the header leaves blank, as a spreadsheet pads them", () => {
    expect(lines("ticker,shares,,\nVTI,1,,a note\n")).toEqual([line("VTI", 1, null, null)]);
  });
});

describe("resolveUpload: which column is used", () => {
  const resolve = (parsed: FundLine[], ids: string[] = parsed.map((l) => l.ticker), limits = LIMITS) => resolveUpload(parsed, catalog(...ids), limits);
  const plan = (parsed: FundLine[], ids?: string[], limits = LIMITS) => {
    const out = resolve(parsed, ids, limits);
    if (!out.ok) throw new Error(out.error);
    return out.plan;
  };

  it("takes shares first when every fund with an amount has them", () => {
    const out = plan([line("VTI", 10, 1000, 60), line("BND", 5, 500, 40)]);
    expect(out.unit).toBe("shares");
    expect(out.rows).toEqual([
      { id: "VTI", name: "VTI Fund", amount: 10 },
      { id: "BND", name: "BND Fund", amount: 5 },
    ]);
  });
  it("takes dollars when shares are not filled for every fund with an amount", () => {
    const out = plan([line("VTI", 10, 1000, 60), line("BND", null, 500, 40)]);
    expect(out.unit).toBe("usd");
    expect(out.rows.map((r) => r.amount)).toEqual([1000, 500]);
  });
  it("takes percent only when it is the only column they all share", () => {
    const out = plan([line("VTI", 10, null, 60), line("BND", null, 500, 40)]);
    expect(out.unit).toBe("pct");
    expect(out.rows.map((r) => r.amount)).toEqual([60, 40]);
  });
  it("loads a fund with only a ticker at no amount, beside funds with amounts", () => {
    const out = plan([line("VTI", null, 1000, null), line("BND", null, null, null), line("VNQ", null, 250, null)]);
    expect(out.unit).toBe("usd");
    expect(out.rows.map((r) => [r.id, r.amount])).toEqual([["VTI", 1000], ["BND", null], ["VNQ", 250]]);
  });
  it("treats an amount of 0 as an amount", () => {
    const out = plan([line("VTI", 0, null, null), line("BND", null, null, null)]);
    expect(out.unit).toBe("shares");
    expect(out.rows.map((r) => r.amount)).toEqual([0, null]);
  });
  it("loads tickers only, and leaves the unit alone, when no fund has an amount", () => {
    const out = plan([line("VTI", null, null, null), line("BND", null, null, null)]);
    expect(out.unit).toBeNull();
    expect(out.rows.map((r) => r.amount)).toEqual([null, null]);
    expect(out.notes).toEqual([]);
    expect(out.pending).toEqual([]);
  });
  it("refuses the whole file when the funds with amounts share no column, naming who has what", () => {
    const out = resolve([line("VTI", 10, null, null), line("BND", null, null, 40)]);
    expect(out).toEqual({
      ok: false,
      error: "Every fund with an amount needs the same column filled in (shares, dollars or percent). VTI has only shares; BND has only percent.",
      skipped: [],
    });
  });
  it("names a fund that has two columns, and one that has all three", () => {
    const out = resolve([line("VTI", 10, 100, null), line("BND", null, null, 40), line("VNQ", 1, 2, 3)]);
    expect(out.ok).toBe(false);
    expect(!out.ok && out.error).toBe(
      "Every fund with an amount needs the same column filled in (shares, dollars or percent). VTI has only shares and dollars; BND has only percent; VNQ has shares, dollars and percent.",
    );
  });
  it("lists the funds that lack the commonest column first, and at most six, in a long file", () => {
    const many = Array.from({ length: 12 }, (_, i) => line(`S${String(i).padStart(2, "0")}`, 1, null, null));
    const out = resolve([...many, line("ODD", null, null, 5)]);
    expect(!out.ok && out.error).toBe(
      "Every fund with an amount needs the same column filled in (shares, dollars or percent). ODD has only percent; S00 has only shares; S01 has only shares; S02 has only shares; S03 has only shares; S04 has only shares; and 7 more.",
    );
  });
  it("does not let a fund that is not served decide the column", () => {
    const out = plan([line("VTI", 10, null, null), line("BND", 5, null, null), line("ZZZ", null, null, 100)], ["VTI", "BND"]);
    expect(out.unit).toBe("shares");
  });
  it("loads one row per fund, whatever the case of the catalog's ids and the file", () => {
    const out = plan(lines("ticker,shares\nvti,1\nVTI,2\nbnd,3\n"), ["VTI", "BND"]);
    expect(out.rows).toEqual([
      { id: "VTI", name: "VTI Fund", amount: 3 },
      { id: "BND", name: "BND Fund", amount: 3 },
    ]);
  });
  it("uses the ticker as the name of a fund the catalog has no name for", () => {
    const out = resolveUpload([line("VTI", null, null, null), line("BND", null, null, null)], [{ id: "VTI" }, { id: "BND", name: null }], LIMITS);
    expect(out.ok && out.plan.rows.map((r) => r.name)).toEqual(["VTI", "BND"]);
  });
});

describe("resolveUpload: tickers that are not served, and the limits", () => {
  it("skips them, in file order, once each, and loads the rest", () => {
    const out = resolveUpload(lines("ticker\nVTI\nXYZ\nBND\nABC\nxyz\n"), catalog("VTI", "BND"), LIMITS);
    expect(out.ok && out.plan.skipped).toEqual(["XYZ", "ABC"]);
    expect(out.ok && out.plan.rows.map((r) => r.id)).toEqual(["VTI", "BND"]);
  });
  it("serves a class share the file writes with a slash or a dot, and skips an unserved one under its hyphen form", () => {
    const out = resolveUpload(lines("ticker\nVTI\nBRK/B\nbf.b\nXYZ/B\n"), catalog("VTI", "BRK-B", "BF-B"), LIMITS);
    expect(out.ok && out.plan.rows.map((r) => r.id)).toEqual(["VTI", "BRK-B", "BF-B"]);
    expect(out.ok && out.plan.skipped).toEqual(["XYZ-B"]);
  });
  it("adds the rows of one served class share whichever way the file writes it, under the served id", () => {
    const out = resolveUpload(lines("ticker,shares\nBRK/B,1\nVTI,5\nbrk.b,2\nBRK-B,4\n"), catalog("VTI", "BRK-B"), LIMITS);
    expect(out.ok && out.plan.rows.map((r) => [r.id, r.amount])).toEqual([["BRK-B", 7], ["VTI", 5]]);
    expect(out.ok && out.plan.skipped).toEqual([]);
  });
  it("serves a ticker the catalog serves as the file writes it, dot and all, before its class-share form", () => {
    const out = resolveUpload(lines("ticker,shares\nVTI,1\nbrk.b,2\nBRK/B,3\nry.to,4\n"), catalog("VTI", "BRK.B", "BRK-B", "RY.TO"), LIMITS);
    expect(out.ok && out.plan.rows.map((r) => [r.id, r.amount])).toEqual([["VTI", 1], ["BRK.B", 2], ["BRK-B", 3], ["RY.TO", 4]]);
    expect(out.ok && out.plan.skipped).toEqual([]);
  });
  it("skips an exchange suffix or a ticker of several parts as the file writes it, and never as a hyphenated id", () => {
    const file = lines("ticker\nVTI\nBND\nry.to\nBMW.DE\na.b.c\nBRK.B\nXYZ/BB\nA/B/C\n");
    // served ids that the over-broad rewriting would have reached: a suffix is not a share class
    const out = resolveUpload(file, catalog("VTI", "BND", "RY-TO", "BMW-DE", "A-B-C"), LIMITS);
    expect(out.ok && out.plan.rows.map((r) => r.id)).toEqual(["VTI", "BND"]);
    expect(out.ok && out.plan.skipped).toEqual(["RY.TO", "BMW.DE", "A.B.C", "BRK.B", "XYZ/BB", "A/B/C"]);
  });
  it("names a fund in the no-common-column refusal as the file wrote it", () => {
    const out = resolveUpload(lines("ticker,shares,dollars\nbrk/b,1,\nVTI,,5\n"), catalog("VTI", "BRK-B"), LIMITS);
    expect(!out.ok && out.error).toContain("BRK/B has only shares; VTI has only dollars.");
  });
  it("has nothing skipped when every ticker is served", () => {
    const out = resolveUpload([line("VTI", null, null, null), line("BND", null, null, null)], catalog("VTI", "BND"), LIMITS);
    expect(out.ok && out.plan.skipped).toEqual([]);
  });
  it("refuses a file with fewer than the minimum served tickers, and still reports the ones it skipped", () => {
    const out = resolveUpload([line("VTI", null, null, null), line("XYZ", null, null, null)], catalog("VTI"), LIMITS);
    expect(out).toEqual({ ok: false, error: menuNeedsMore(2), skipped: ["XYZ"] });
    expect(resolveUpload([line("XYZ", null, null, null), line("ABC", null, null, null)], catalog("VTI"), LIMITS)).toEqual({ ok: false, error: menuNeedsMore(2), skipped: ["XYZ", "ABC"] });
  });
  it("takes exactly the minimum", () => {
    expect(resolveUpload([line("VTI", null, null, null), line("BND", null, null, null)], catalog("VTI", "BND"), LIMITS).ok).toBe(true);
  });
  it("refuses a file with more served tickers than the menu holds, and cuts nothing", () => {
    const ids = Array.from({ length: 31 }, (_, i) => `F${i}`);
    const out = resolveUpload(ids.map((id) => line(id, null, null, null)), catalog(...ids), LIMITS);
    expect(out).toEqual({ ok: false, error: menuFull(30), skipped: [] });
    expect(resolveUpload(ids.slice(0, 30).map((id) => line(id, null, null, null)), catalog(...ids), LIMITS).ok).toBe(true);
    expect(resolveUpload(ids.map((id) => line(id, null, null, null)), catalog(...ids), { min: 2, max: 100 }).ok).toBe(true);
  });
  it("counts only served tickers against the maximum", () => {
    const ids = Array.from({ length: 30 }, (_, i) => `F${i}`);
    const out = resolveUpload([...ids, "UNKNOWN1", "UNKNOWN2"].map((id) => line(id, null, null, null)), catalog(...ids), LIMITS);
    expect(out.ok && out.plan.skipped).toEqual(["UNKNOWN1", "UNKNOWN2"]);
  });
});

describe("mismatch checks and their exact thresholds", () => {
  it("percent against dollars: each fund's share of the dollars against its share of the percent, 0.5 points", () => {
    // 50 / 50 in dollars against 50.5 / 49.5: exactly 0.5 points apart, so within
    expect(percentVsDollars([{ dollars: 5000, percent: 50.5 }, { dollars: 5000, percent: 49.5 }])).toBe(0);
    // 0.6 points apart: both funds disagree
    expect(percentVsDollars([{ dollars: 5000, percent: 50.6 }, { dollars: 5000, percent: 49.4 }])).toBe(2);
    // only the funds that are off are counted
    expect(percentVsDollars([{ dollars: 1000, percent: 10 }, { dollars: 1000, percent: 10 }, { dollars: 8000, percent: 80 }])).toBe(0);
    expect(percentVsDollars([{ dollars: 1000, percent: 10 }, { dollars: 1000, percent: 19 }, { dollars: 8000, percent: 71 }])).toBe(2);
  });
  it("percent against dollars compares shares of the totals, so percent that does not add to 100 still agrees in proportion", () => {
    expect(percentVsDollars([{ dollars: 3000, percent: 30 }, { dollars: 1000, percent: 10 }])).toBe(0);
    expect(percentVsDollars([{ dollars: 3000, percent: 3 }, { dollars: 1000, percent: 1 }])).toBe(0);
  });
  it("percent against dollars cannot compare totals of nothing", () => {
    expect(percentVsDollars([])).toBe(0);
    expect(percentVsDollars([{ dollars: 0, percent: 10 }])).toBe(0);
    expect(percentVsDollars([{ dollars: 10, percent: 0 }])).toBe(0);
  });
  it("dollars against shares at the latest price: 2% of the fund's dollars", () => {
    // dollars of 100 against shares worth 102 or 98: exactly 2% of the dollars either way, so within
    expect(dollarsVsShares([{ shares: 5.1, dollars: 100, lastClose: 20 }])).toBe(0);
    expect(dollarsVsShares([{ shares: 4.9, dollars: 100, lastClose: 20 }])).toBe(0);
    expect(dollarsVsShares([{ shares: 5, dollars: 100, lastClose: 20 }])).toBe(0);
    // beyond 2%
    expect(dollarsVsShares([{ shares: 5.1005, dollars: 100, lastClose: 20 }])).toBe(1);
    expect(dollarsVsShares([{ shares: 4.8995, dollars: 100, lastClose: 20 }])).toBe(1);
    // a fund's threshold is its own dollars, not the total
    expect(dollarsVsShares([{ shares: 1, dollars: 1000, lastClose: 1000 }, { shares: 1, dollars: 10, lastClose: 11 }])).toBe(1);
  });
  it("dollars against shares leaves out a fund with no latest price, and a fund of zero dollars is compared exactly", () => {
    expect(dollarsVsShares([{ shares: 5, dollars: 1, lastClose: null }])).toBe(0);
    expect(dollarsVsShares([{ shares: 0, dollars: 0, lastClose: 20 }])).toBe(0);
    expect(dollarsVsShares([{ shares: 1, dollars: 0, lastClose: 20 }])).toBe(1);
  });
  it("percent against shares: each fund's share of the shares' value against its share of the percent, 0.5 points", () => {
    // 10 shares at 50 and 10 shares at 50: 50 / 50
    expect(percentVsShares([{ shares: 10, percent: 50.5, lastClose: 50 }, { shares: 10, percent: 49.5, lastClose: 50 }])).toBe(0);
    expect(percentVsShares([{ shares: 10, percent: 50.6, lastClose: 50 }, { shares: 10, percent: 49.4, lastClose: 50 }])).toBe(2);
    // the share is of the funds that have a price: the third has none and is left out of both totals
    expect(percentVsShares([{ shares: 10, percent: 25, lastClose: 50 }, { shares: 30, percent: 75, lastClose: 50 }, { shares: 1, percent: 60, lastClose: null }])).toBe(0);
    expect(percentVsShares([])).toBe(0);
  });
  it("settles a pending check against the new menu's prices, and compares nothing for a fund the menu has no price for", () => {
    const funds = [{ id: "VTI", last_close: 20 }, { id: "BND", last_close: null }, { id: "VNQ" }];
    const against = (kind: "dollars" | "percent", entries: { id: string; shares: number; value: number }[]) => settlePending([{ against: kind, entries }], funds);
    expect(against("dollars", [{ id: "VTI", shares: 5, value: 100 }])).toEqual([]);
    expect(against("dollars", [{ id: "VTI", shares: 5, value: 200 }])).toEqual(["Dollars didn't match shares at the latest price for 1 fund and were ignored."]);
    expect(against("dollars", [{ id: "BND", shares: 5, value: 200 }, { id: "VNQ", shares: 5, value: 200 }, { id: "ZZZ", shares: 5, value: 200 }])).toEqual([]);
    expect(against("percent", [{ id: "VTI", shares: 5, value: 60 }, { id: "VNQ", shares: 5, value: 40 }])).toEqual([]);
    const two = [{ id: "VTI", last_close: 20 }, { id: "VNQ", last_close: 20 }];
    expect(settlePending([{ against: "percent", entries: [{ id: "VTI", shares: 5, value: 70 }, { id: "VNQ", shares: 5, value: 30 }] }], two)).toEqual([
      "Percent didn't match shares at the latest price for 2 funds and was ignored.",
    ]);
  });
});

describe("resolveUpload: notes for the columns that were not used", () => {
  const resolve = (parsed: FundLine[]) => {
    const out = resolveUpload(parsed, catalog(...parsed.map((l) => l.ticker)), LIMITS);
    if (!out.ok) throw new Error(out.error);
    return out.plan;
  };
  it("says percent was ignored when dollars were used and the two disagree", () => {
    const out = resolve([line("VTI", null, 5000, 70), line("BND", null, 5000, 30)]);
    expect(out.unit).toBe("usd");
    expect(out.notes).toEqual(["Percent didn't match dollars for 2 funds and was ignored."]);
    expect(out.pending).toEqual([]);
  });
  it("says nothing when percent agrees with the dollars, or when there is no percent", () => {
    expect(resolve([line("VTI", null, 7000, 70), line("BND", null, 3000, 30)]).notes).toEqual([]);
    expect(resolve([line("VTI", null, 7000, null), line("BND", null, 3000, null)]).notes).toEqual([]);
  });
  it("compares only the funds that have both dollars and percent", () => {
    const out = resolve([line("VTI", null, 7000, 70), line("BND", null, 3000, null), line("VNQ", null, 1000, 10)]);
    // among VTI and VNQ: 7000 / 8000 = 87.5% of the dollars against 70 / 80 = 87.5% of the percent
    expect(out.notes).toEqual([]);
  });
  it("holds the shares checks until the new menu has prices", () => {
    const out = resolve([line("VTI", 10, 1000, 60), line("BND", 5, 500, 40), line("VNQ", 2, null, null)]);
    expect(out.unit).toBe("shares");
    expect(out.notes).toEqual([]);
    expect(out.pending).toEqual([
      { against: "dollars", entries: [{ id: "VTI", shares: 10, value: 1000 }, { id: "BND", shares: 5, value: 500 }] },
      { against: "percent", entries: [{ id: "VTI", shares: 10, value: 60 }, { id: "BND", shares: 5, value: 40 }] },
    ]);
  });
  it("holds nothing when only shares are given, or percent was the column used", () => {
    expect(resolve([line("VTI", 10, null, null), line("BND", 5, null, null)]).pending).toEqual([]);
    const pctOnly = resolve([line("VTI", null, null, 60), line("BND", null, null, 40)]);
    expect(pctOnly.pending).toEqual([]);
    expect(pctOnly.notes).toEqual([]);
  });
  it("does not use a fund that is not served in any check", () => {
    const out = resolveUpload([line("VTI", null, 5000, 50), line("BND", null, 5000, 50), line("ZZZ", null, 1, 99)], catalog("VTI", "BND"), LIMITS);
    expect(out.ok && out.plan.notes).toEqual([]);
  });
});

describe("resolveUpload: shares valued at the file's own dollars", () => {
  const resolve = (parsed: FundLine[], ids: string[] = parsed.map((l) => l.ticker)) => {
    const out = resolveUpload(parsed, catalog(...ids), LIMITS);
    if (!out.ok) throw new Error(out.error);
    return out.plan;
  };
  it("gives each fund a price per share (its dollars over its shares) when every fund with shares has dollars", () => {
    expect(resolve([line("VTI", 10, 1500, 60), line("BND", 4, 100, 40)]).prices).toEqual({ VTI: 150, BND: 25 });
  });
  it("gives no price to a fund with no shares, and does not need its dollars", () => {
    expect(resolve([line("VTI", 10, 1500, null), line("BND", 0, null, null), line("VNQ", null, null, null)]).prices).toEqual({ VTI: 150 });
  });
  it("gives no price at all when any fund with shares has no dollars, so the whole upload keeps the current rules", () => {
    expect(resolve([line("VTI", 10, 1500, null), line("BND", 4, null, null)]).prices).toEqual({});
    expect(resolve([line("VTI", 10, 1500, null), line("BND", 4, 0, null)]).prices).toEqual({});
  });
  it("gives no price when shares are not the unit used", () => {
    expect(resolve([line("VTI", null, 1000, null), line("BND", null, 500, null)]).prices).toEqual({});
    expect(resolve([line("VTI", 10, null, 60), line("BND", null, 500, 40)]).prices).toEqual({});
    expect(resolve([line("VTI", 10, null, null), line("BND", 5, null, null)]).prices).toEqual({});
  });
  it("does not let a fund that is not served decide whether the dollars are complete", () => {
    expect(resolve([line("VTI", 10, 1000, null), line("BND", 5, 500, null), line("ZZZ", 1, null, null)], ["VTI", "BND"]).prices).toEqual({ VTI: 100, BND: 100 });
  });
  it("holds no check of the dollars against the shares when the dollars are the basis, and checks the percent against them at once", () => {
    const out = resolve([line("VTI", 10, 7000, 50), line("BND", 5, 3000, 50)]);
    expect(out.pending).toEqual([]);
    expect(out.notes).toEqual(["Percent didn't match dollars for 2 funds and was ignored."]);
    expect(resolve([line("VTI", 10, 7000, 70), line("BND", 5, 3000, 30)]).notes).toEqual([]);
  });
  it("keeps the shares checks, as before, when the dollars are not the basis", () => {
    const out = resolve([line("VTI", 10, 1000, 60), line("BND", 5, null, 40)]);
    expect(out.prices).toEqual({});
    expect(out.pending).toEqual([
      { against: "dollars", entries: [{ id: "VTI", shares: 10, value: 1000 }] },
      { against: "percent", entries: [{ id: "VTI", shares: 10, value: 60 }, { id: "BND", shares: 5, value: 40 }] },
    ]);
  });
});
