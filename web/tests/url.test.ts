// URL codec (spec 8.1): the ten keys, their canonical order and formats, and the debounced write.
import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LOOKBACKS, clampR, decode, encode, scheduleUrlWrite, writeUrl, type UrlState } from "../src/state/url";

const EMPTY: UrlState = { preset: null, funds: [], unit: "pct", caps: [], lookback: "5y", ghosts: [], r: null, d: "auto", theme: null, details: false };
const GUIDE: UrlState = { ...EMPTY, preset: "guide2017" };
const KEYS = ["u", "f", "unit", "c", "lb", "g", "r", "d", "t", "x"];
const keysOf = (search: string) => Array.from(new URLSearchParams(search).keys());
const valueOf = (search: string, key: string) => new URLSearchParams(search).get(key);

describe("encode and decode", () => {
  it("round-trips the spec's two examples character for character", () => {
    const preset = "?u=guide2017&lb=5y&r=19.25&d=auto&t=hud";
    expect(decode(preset)).toEqual({ ...GUIDE, r: 19.25, theme: "hud" });
    expect(encode(decode(preset))).toBe(preset);

    const custom = "?f=VTI:60,BND:40,VNQ&unit=shares&c=VTI::10,BND:5:&lb=ew&g=1y,10y&d=0.5&x=1";
    expect(decode(custom)).toEqual({
      preset: null,
      funds: [{ id: "VTI", amount: 60 }, { id: "BND", amount: 40 }, { id: "VNQ", amount: null }],
      unit: "shares",
      caps: [{ id: "VTI", min: null, max: 10 }, { id: "BND", min: 5, max: null }],
      lookback: "ew",
      ghosts: ["1y", "10y"],
      r: null,
      d: 0.5,
      theme: null,
      details: true,
    });
    expect(encode(decode(custom))).toBe(custom);
  });

  it("reads an empty query as the defaults and writes lb and d even then", () => {
    for (const search of ["", "?", "?zz=1"]) expect(decode(search), `"${search}"`).toEqual(EMPTY);
    expect(encode(EMPTY)).toBe("?lb=5y&d=auto");
    expect(encode({ ...EMPTY, unit: "pct", details: false, theme: null })).not.toMatch(/unit|x=|t=/);
  });

  it("writes every key once, in the order u f unit c lb g r d t x", () => {
    const state: UrlState = {
      preset: null,
      funds: [{ id: "VTI", amount: 60.5 }, { id: "TSP-L2030", amount: null }, { id: "BRK.B", amount: 0 }],
      unit: "usd",
      caps: [{ id: "VTI", min: 5, max: 40 }, { id: "BRK.B", min: null, max: null }],
      lookback: "10y",
      ghosts: ["1y", "ew"],
      r: 12.5,
      d: 0.25,
      theme: "ks-dark",
      details: true,
    };
    expect(encode(state)).toBe("?f=VTI:60.5,TSP-L2030,BRK.B:0&unit=usd&c=VTI:5:40,BRK.B::&lb=10y&g=1y,ew&r=12.5&d=0.25&t=ks-dark&x=1");
    expect(decode(encode(state))).toEqual(state);
    expect(keysOf(encode({ ...state, preset: "tsp", funds: [] }))).toEqual(["u", "unit", "c", "lb", "g", "r", "d", "t", "x"]);
    expect(keysOf(encode(state))).toEqual(KEYS.filter((key) => key !== "u"));
  });

  it("writes r, d and amounts as plain decimals with six places at most", () => {
    const written = (r: number, d: number) => {
      const search = encode({ ...GUIDE, r, d });
      return [valueOf(search, "r"), valueOf(search, "d")];
    };
    expect(written(19, 0)).toEqual(["19", "0"]);
    expect(written(47, 1)).toEqual(["47", "1"]);
    expect(written(7.573125, 0.125)).toEqual(["7.573125", "0.125"]);
    expect(written(12.3456789, 1 / 3)).toEqual(["12.345679", "0.333333"]);
    expect(written(0.1 + 0.2, 2 / 3)).toEqual(["0.3", "0.666667"]);
    // never an exponent: the UI gates read these with /^\d+(\.\d+)?$/
    expect(written(46.9999996, 1e-7)).toEqual(["47", "0"]);
    expect(written(1e-9, 0.9999999)).toEqual(["0", "1"]);
    expect(encode({ ...EMPTY, funds: [{ id: "VTI", amount: 0.1 + 0.2 }, { id: "BND", amount: 1234567.891 }] })).toContain("f=VTI:0.3,BND:1234567.891&");
    // six places keep a keyboard step of the risk slider (1/200 of a domain in eighths) exact
    for (let k = 0; k <= 200; k++) {
      const r = 0.625 + (k * (47 - 0.625)) / 200;
      expect(Math.abs((decode(encode({ ...GUIDE, r })).r as number) - r), `step ${k}`).toBeLessThanOrEqual(1e-9);
    }
  });

  it("falls back to the default for any value outside its shape", () => {
    expect(decode("?u=other&unit=euros&lb=7y&g=1y,7y,1y,ew,,&r=abc&d=soon&t=neon&x=yes")).toEqual({ ...EMPTY, ghosts: ["1y", "ew"] });
    expect(decode("?r=&d=&x=&lb=&t=&u=&f=&c=&g=")).toEqual(EMPTY);
    expect(decode("?r=1e3").r).toBeNull();
    expect(decode("?r=0x10").r).toBeNull();
    expect(decode("?r=Infinity").r).toBeNull();
    expect(decode("?r=.5&d=.25")).toEqual({ ...EMPTY, r: 0.5, d: 0.25 });
    expect(decode("?x=1").details).toBe(true);
    expect(decode("?x=true").details).toBe(false);
  });

  it("keeps d inside [0, 1]", () => {
    expect(["7", "1.0001", "-0.5", "0", "1", "0.999999"].map((d) => decode(`?d=${d}`).d)).toEqual([1, 1, 0, 0, 1, 0.999999]);
  });

  it("reads fund amounts and caps leniently and never invents a number", () => {
    expect(decode("?f=vti:12.50,BND:abc,VNQ:-5,AGG:,TIP:1e3,,:7,GLD").funds).toEqual([
      { id: "VTI", amount: 12.5 },
      { id: "BND", amount: null },
      { id: "VNQ", amount: null },
      { id: "AGG", amount: null },
      { id: "TIP", amount: null },
      { id: "GLD", amount: null },
    ]);
    expect(decode("?c=vti:5:40,BND:x:101,AGG,:5:10,TIP:2.5:-1,GLD:0:100").caps).toEqual([
      { id: "VTI", min: 5, max: 40 },
      { id: "BND", min: null, max: null },
      { id: "AGG", min: null, max: null },
      { id: "TIP", min: null, max: null },
      { id: "GLD", min: 0, max: 100 },
    ]);
  });

  it("reads separators that another program percent-encoded", () => {
    const state = decode("?f=VTI%3A60%2CBND%3A40%2C+VNQ&c=VTI%3A%3A10&g=1y%2C10y&lb=3y");
    expect(state.funds).toEqual([{ id: "VTI", amount: 60 }, { id: "BND", amount: 40 }, { id: "VNQ", amount: null }]);
    expect(state.caps).toEqual([{ id: "VTI", min: null, max: 10 }]);
    expect(state.ghosts).toEqual(["1y", "10y"]);
    expect(encode(state)).toBe("?f=VTI:60,BND:40,VNQ&c=VTI::10&lb=3y&g=1y,10y&d=auto");
  });

  it("ignores unknown keys, takes the first of a repeated key and never writes either back", () => {
    const clean = "?u=tsp&lb=3y&r=12.5&d=0.25&t=light&x=1";
    for (const dirty of ["?zz=1&u=tsp&k=SECRET&lb=3y&r=12.5&d=0.25&t=light&x=1&utm_source=mail", "?u=tsp&lb=3y&lb=10y&r=12.5&r=40&d=0.25&t=light&t=hud&x=1"]) {
      expect(decode(dirty)).toEqual(decode(clean));
      expect(encode(decode(dirty))).toBe(clean);
    }
    expect(Object.keys(decode("?zz=1&k=SECRET")).sort()).toEqual(Object.keys(EMPTY).sort());
  });

  it("a preset carries no fund list", () => {
    expect(decode("?u=tsp&f=VTI:60,BND:40")).toEqual({ ...EMPTY, preset: "tsp" });
    expect(encode({ ...EMPTY, preset: "tsp", funds: [{ id: "VTI", amount: 60 }] })).toBe("?u=tsp&lb=5y&d=auto");
    // caps and the unit do travel with a preset
    const capped = "?u=guide2017&unit=shares&c=VTI::10&lb=5y&d=auto";
    expect(encode(decode(capped))).toBe(capped);
  });

  it("reads and writes the third ready-made portfolio, and still refuses a preset it does not know", () => {
    expect(decode("?u=research2003")).toEqual({ ...EMPTY, preset: "research2003" });
    expect(encode({ ...EMPTY, preset: "research2003" })).toBe("?u=research2003&lb=5y&d=auto");
    const edited = "?u=research2003&c=SPY::30,GE::5&lb=5y&d=auto";
    expect(encode(decode(edited))).toBe(edited);
    expect(decode("?u=research2004").preset).toBeNull();
  });

  it("escapes a fund id so it cannot add a key or break the list", () => {
    const state: UrlState = { ...EMPTY, funds: [{ id: "X&K=1#Y", amount: 5 }, { id: "A B+C%", amount: null }], caps: [{ id: "X&K=1#Y", min: 1, max: 2 }] };
    const search = encode(state);
    expect(keysOf(search)).toEqual(["f", "c", "lb", "d"]);
    expect(search).not.toContain("#");
    expect(decode(search)).toEqual(state);
  });

  it("round-trips 400 generated states exactly", () => {
    let seed = 81;
    const rnd = () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    const pick = <T,>(xs: readonly T[]): T => xs[Math.floor(rnd() * xs.length)];
    const ids = ["VTI", "BND", "VNQ", "AGG", "TSP-G", "TSP-L2030", "BRK.B", "VBIAX", "GLD", "TIP"];
    const seen = new Set<string>();
    for (let i = 0; i < 400; i++) {
      const preset = rnd() < 0.4 ? pick(["guide2017", "tsp"] as const) : null;
      const menu = ids.filter(() => rnd() < 0.5).concat("SGOV", "VTIP");
      const state: UrlState = {
        preset,
        funds: preset ? [] : menu.map((id) => ({ id, amount: rnd() < 0.3 ? null : Math.round(rnd() * 5e6) / 100 })),
        unit: pick(["pct", "usd", "shares"] as const),
        caps: menu.filter(() => rnd() < 0.2).map((id) => ({ id, min: rnd() < 0.5 ? null : Math.floor(rnd() * 20), max: rnd() < 0.5 ? null : 20 + Math.floor(rnd() * 81) })),
        lookback: pick(LOOKBACKS),
        ghosts: LOOKBACKS.filter(() => rnd() < 0.3),
        r: rnd() < 0.2 ? null : Math.round(rnd() * 47e6) / 1e6,
        d: rnd() < 0.4 ? "auto" : Math.round(rnd() * 1e6) / 1e6,
        theme: pick([null, "ks-dark", "light", "hud", "grid"] as const),
        details: rnd() < 0.5,
      };
      const search = encode(state);
      expect(decode(search), search).toEqual(state);
      expect(encode(decode(search))).toBe(search);
      const keys = keysOf(search);
      expect(keys).toEqual(KEYS.filter((key) => keys.includes(key)));
      keys.forEach((key) => seen.add(key));
    }
    expect([...seen].sort()).toEqual([...KEYS].sort());
  });

  it("knows the lookbacks of the tensor contract", () => {
    const schema = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "../portfoliosight/engine/tensor.schema.json"), "utf-8"));
    expect([...LOOKBACKS]).toEqual(schema.properties.lookback.properties.id.enum);
    for (const lookback of LOOKBACKS) expect(decode(`?lb=${lookback}`).lookback).toBe(lookback);
  });
});

describe("file prices (p)", () => {
  // the price per share an uploaded file gave: `p=ID:price`, only in the shares unit
  const shares = (funds: UrlState["funds"], patch: Partial<UrlState> = {}): UrlState => ({ ...EMPTY, unit: "shares", funds, ...patch });

  it("writes the prices after f, only for rows that have one, and reads them back", () => {
    const state = shares([{ id: "VTI", amount: 10, price: 200.5 }, { id: "BND", amount: 100 }, { id: "VNQ", amount: 7, price: 80 }]);
    const search = encode(state);
    expect(search).toBe("?f=VTI:10,BND:100,VNQ:7&p=VTI:200.5,VNQ:80&unit=shares&lb=5y&d=auto");
    expect(decode(search)).toEqual(state);
    expect(encode(decode(search))).toBe(search);
    expect(keysOf(search)).toEqual(["f", "p", "unit", "lb", "d"]);
  });

  it("keeps a price on a row whose amount is blank, and a row without a price has no price at all", () => {
    const state = shares([{ id: "VTI", amount: null, price: 200 }, { id: "BND", amount: 5 }]);
    expect(encode(state)).toBe("?f=VTI,BND:5&p=VTI:200&unit=shares&lb=5y&d=auto");
    const back = decode(encode(state));
    expect(back).toEqual(state);
    expect(Object.keys(back.funds[1])).toEqual(["id", "amount"]);
  });

  it("leaves addresses without prices exactly as they were, written and read", () => {
    expect(encode(shares([{ id: "VTI", amount: 10 }, { id: "BND", amount: 100 }]))).toBe("?f=VTI:10,BND:100&unit=shares&lb=5y&d=auto");
    const old = decode("?f=VTI:10,BND:100&unit=shares&lb=5y&d=auto");
    expect(old.funds).toStrictEqual([{ id: "VTI", amount: 10 }, { id: "BND", amount: 100 }]);
    // a page that never meets a price writes the same address it always did
    expect(encode({ ...EMPTY, funds: [{ id: "VTI", amount: 60 }, { id: "BND", amount: 40 }] })).toBe("?f=VTI:60,BND:40&lb=5y&d=auto");
  });

  it("writes no prices outside the shares unit, and none with a preset", () => {
    const funds = [{ id: "VTI", amount: 10, price: 200 }, { id: "BND", amount: 5, price: 10 }];
    expect(encode({ ...EMPTY, unit: "pct", funds })).toBe("?f=VTI:10,BND:5&lb=5y&d=auto");
    expect(encode({ ...EMPTY, unit: "usd", funds })).toBe("?f=VTI:10,BND:5&unit=usd&lb=5y&d=auto");
    expect(encode({ ...EMPTY, unit: "shares", preset: "tsp", funds })).toBe("?u=tsp&unit=shares&lb=5y&d=auto");
  });

  it("writes prices at six decimals like every other number, and leaves out one that would be written as zero", () => {
    const search = encode(shares([{ id: "VTI", amount: 3, price: 1000 / 3 }, { id: "BND", amount: 1, price: 0.0000004 }, { id: "VNQ", amount: 1, price: 0.000001 }]));
    expect(search).toBe("?f=VTI:3,BND:1,VNQ:1&p=VTI:333.333333,VNQ:0.000001&unit=shares&lb=5y&d=auto");
    expect(encode(decode(search))).toBe(search);
    // not a number a price can be: nothing is written for them
    for (const price of [0, -5, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(encode(shares([{ id: "VTI", amount: 1, price }])), String(price)).toBe("?f=VTI:1&unit=shares&lb=5y&d=auto");
    }
  });

  it("reads a price only when it is a positive number, and ignores anything else without touching the funds", () => {
    const read = (p: string) => decode(`?f=VTI:10,BND:5&unit=shares&p=${p}`).funds;
    expect(read("VTI:200,BND:0.5")).toEqual([{ id: "VTI", amount: 10, price: 200 }, { id: "BND", amount: 5, price: 0.5 }]);
    expect(read("vti:200.50")).toEqual([{ id: "VTI", amount: 10, price: 200.5 }, { id: "BND", amount: 5 }]);
    const plain = [{ id: "VTI", amount: 10 }, { id: "BND", amount: 5 }];
    for (const bad of ["VTI:0", "VTI:-3", "VTI:abc", "VTI:1e3", "VTI:Infinity", "VTI:NaN", "VTI:", "VTI", "VTI:0x10", ":200", "", ",,", "VTI:" + "9".repeat(400)]) {
      expect(read(bad), bad).toStrictEqual(plain);
    }
    // a good entry survives the bad one beside it; extra fields are not part of the price
    expect(read("VTI:abc,BND:10:99")).toEqual([{ id: "VTI", amount: 10 }, { id: "BND", amount: 5, price: 10 }]);
  });

  it("ignores prices unless the unit is shares", () => {
    for (const unit of ["", "&unit=pct", "&unit=usd", "&unit=bogus"]) {
      expect(decode(`?f=VTI:10,BND:5&p=VTI:200,BND:10${unit}`).funds, unit).toStrictEqual([{ id: "VTI", amount: 10 }, { id: "BND", amount: 5 }]);
    }
  });

  it("ignores a price for a fund the address does not list, and with a preset; the first price of a fund counts", () => {
    expect(decode("?f=VTI:10&unit=shares&p=ZZZ:5,VTI:200,VTI:300").funds).toEqual([{ id: "VTI", amount: 10, price: 200 }]);
    expect(decode("?u=tsp&unit=shares&p=VTI:200")).toEqual({ ...EMPTY, preset: "tsp", unit: "shares" });
    expect(decode("?unit=shares&p=VTI:200").funds).toEqual([]);
  });

  it("reads percent-encoded separators, and never writes the key back when nothing is left", () => {
    const state = decode("?f=VTI%3A10%2CBND%3A5&unit=shares&p=VTI%3A200%2CBND%3A10");
    expect(state.funds).toEqual([{ id: "VTI", amount: 10, price: 200 }, { id: "BND", amount: 5, price: 10 }]);
    expect(encode(decode("?f=VTI:10&unit=shares&p=VTI:0")).includes("p=")).toBe(false);
  });

  it("round-trips 300 generated states with prices exactly", () => {
    let seed = 7;
    const rnd = () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    const ids = ["VTI", "BND", "VNQ", "AGG", "TSP-G", "BRK.B", "VBIAX", "GLD", "TIP", "SGOV"];
    let withPrices = 0;
    for (let i = 0; i < 300; i++) {
      const unit = (["pct", "usd", "shares", "shares"] as const)[Math.floor(rnd() * 4)];
      const funds = ids.filter(() => rnd() < 0.5).concat("QQQ").map((id) => {
        const amount = rnd() < 0.2 ? null : Math.round(rnd() * 5e6) / 100;
        return rnd() < 0.6 && unit === "shares" ? { id, amount, price: Math.max(1, Math.round(rnd() * 5e8)) / 1e6 } : { id, amount };
      });
      const state: UrlState = { ...EMPTY, unit, funds };
      const search = encode(state);
      expect(decode(search), search).toEqual(state);
      expect(encode(decode(search))).toBe(search);
      if (search.includes("&p=")) withPrices += 1;
    }
    expect(withPrices).toBeGreaterThan(50);
  });
});

describe("clampR", () => {
  const wide = { s_safe: 0.625, s_max: 47 };
  const tight = { s_safe: 7.375, s_max: 31 };

  it("moves r into the domain of the tensor at hand", () => {
    const state = { ...GUIDE, r: 5 };
    expect(clampR(state, wide).r).toBe(5);
    expect(clampR(state, tight).r).toBe(7.375);
    expect(clampR({ ...GUIDE, r: 40 }, tight).r).toBe(31);
    expect(clampR({ ...GUIDE, r: -3 }, wide).r).toBe(0.625);
    expect(clampR({ ...GUIDE, r: 7.375 }, tight).r).toBe(7.375);
    expect(clampR({ ...GUIDE, r: 9 }, { s_safe: 12, s_max: 12 }).r).toBe(12);
  });

  it("changes nothing else, leaves its input alone and hands back the same state when r already fits", () => {
    const state: UrlState = { ...GUIDE, r: 40, d: 0.5, theme: "hud" };
    const clamped = clampR(state, tight);
    expect(clamped).toEqual({ ...state, r: 31 });
    expect(state.r).toBe(40);
    expect(clampR(clamped, tight)).toBe(clamped);
    const unset = { ...GUIDE, r: null };
    expect(clampR(unset, tight)).toBe(unset);
  });

  it("is applied by decode when a domain is given", () => {
    expect(decode("?u=guide2017&r=2", tight).r).toBe(7.375);
    expect(decode("?u=guide2017&r=99", tight).r).toBe(31);
    expect(decode("?u=guide2017&r=19.25", tight).r).toBe(19.25);
    expect(decode("?u=guide2017&r=2").r).toBe(2);
    expect(decode("?u=guide2017", tight).r).toBeNull();
  });
});

describe("scheduleUrlWrite and writeUrl", () => {
  let replaceState: ReturnType<typeof vi.fn>;
  const at = (r: number): UrlState => ({ ...GUIDE, r });

  it("the module loads where there is no browser", () => {
    expect("history" in globalThis).toBe(false);
    expect("window" in globalThis).toBe(false);
    expect(typeof scheduleUrlWrite).toBe("function");
  });

  describe("in a page", () => {
    beforeEach(() => {
      vi.useFakeTimers();
      replaceState = vi.fn();
      vi.stubGlobal("history", { state: { kept: true }, replaceState });
      vi.stubGlobal("location", { pathname: "/", search: "?u=tsp", hash: "" });
    });
    afterEach(() => {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    });

    it("writes once, 250 ms after the last change, with the last state", () => {
      scheduleUrlWrite(at(10));
      vi.advanceTimersByTime(200);
      scheduleUrlWrite(at(11));
      vi.advanceTimersByTime(249);
      expect(replaceState).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);
      expect(replaceState).toHaveBeenCalledTimes(1);
      expect(replaceState).toHaveBeenCalledWith({ kept: true }, "", "/?u=guide2017&lb=5y&r=11&d=auto");
      vi.advanceTimersByTime(60_000);
      expect(replaceState).toHaveBeenCalledTimes(1);
      expect(vi.getTimerCount()).toBe(0);
    });

    it("keeps the page's path and fragment", () => {
      vi.stubGlobal("location", { pathname: "/preview/", search: "", hash: "#funds" });
      scheduleUrlWrite(at(3));
      vi.advanceTimersByTime(250);
      expect(replaceState).toHaveBeenCalledWith({ kept: true }, "", "/preview/?u=guide2017&lb=5y&r=3&d=auto#funds");
    });

    it("writeUrl writes at once and replaces a pending write", () => {
      scheduleUrlWrite(at(10));
      vi.advanceTimersByTime(100);
      writeUrl(at(20));
      expect(replaceState).toHaveBeenCalledTimes(1);
      expect(replaceState).toHaveBeenLastCalledWith({ kept: true }, "", "/?u=guide2017&lb=5y&r=20&d=auto");
      vi.advanceTimersByTime(60_000);
      expect(replaceState).toHaveBeenCalledTimes(1);
      expect(vi.getTimerCount()).toBe(0);
    });
  });
});
