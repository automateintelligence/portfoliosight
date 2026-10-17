// URL codec (spec 8.1, engines spec 6): the eleven keys, their canonical order and formats, and the debounced write.
import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ENGINE_IDS } from "../src/api/tensor";
import { ENGINES, LOOKBACKS, clampR, decode, encode, scheduleUrlWrite, writeUrl, type UrlState } from "../src/state/url";

const EMPTY: UrlState = { preset: null, funds: [], unit: "pct", caps: [], lookback: "5y", ghosts: [], r: null, d: "auto", theme: null, details: false, engine: "replay" };
const GUIDE: UrlState = { ...EMPTY, preset: "guide2017" };
const KEYS = ["u", "f", "unit", "c", "lb", "g", "r", "d", "t", "x", "e"];
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
      engine: "replay",
    });
    expect(encode(decode(custom))).toBe(custom);
  });

  it("reads an empty query as the defaults and writes lb and d even then", () => {
    for (const search of ["", "?", "?zz=1"]) expect(decode(search), `"${search}"`).toEqual(EMPTY);
    expect(encode(EMPTY)).toBe("?lb=5y&d=auto");
    expect(encode({ ...EMPTY, unit: "pct", details: false, theme: null })).not.toMatch(/unit|x=|t=/);
  });

  it("writes every key once, in the order u f unit c lb g r d t x e", () => {
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
      engine: "garch",
    };
    expect(encode(state)).toBe("?f=VTI:60.5,TSP-L2030,BRK.B:0&unit=usd&c=VTI:5:40,BRK.B::&lb=10y&g=1y,ew&r=12.5&d=0.25&t=ks-dark&x=1&e=garch");
    expect(decode(encode(state))).toEqual(state);
    expect(keysOf(encode({ ...state, preset: "tsp", funds: [] }))).toEqual(["u", "unit", "c", "lb", "g", "r", "d", "t", "x", "e"]);
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
        engine: pick(ENGINES),
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

  it("writes e only when it is not replay, after x, and reads it back", () => {
    expect(encode(GUIDE)).toBe("?u=guide2017&lb=5y&d=auto");
    for (const engine of ["garch", "copula"] as const) {
      const state: UrlState = { ...GUIDE, r: 19.25, theme: "hud", details: true, engine };
      expect(encode(state)).toBe(`?u=guide2017&lb=5y&r=19.25&d=auto&t=hud&x=1&e=${engine}`);
      expect(decode(encode(state))).toEqual(state);
      expect(keysOf(encode(state)).at(-1)).toBe("e");
    }
    // without details, e still follows the other keys
    expect(encode({ ...GUIDE, engine: "garch" })).toBe("?u=guide2017&lb=5y&d=auto&e=garch");
    // an address that names replay is read as replay and written without it
    expect(decode("?u=guide2017&e=replay").engine).toBe("replay");
    expect(encode(decode("?u=guide2017&lb=5y&d=auto&e=replay"))).toBe("?u=guide2017&lb=5y&d=auto");
  });

  it("reads an unknown or blank e as replay, and the first of a repeated e", () => {
    for (const value of ["foo", "", "GARCH", "Garch", "garch ", "vine", "1", "replay,garch", "constructor"]) {
      expect(decode(`?u=tsp&e=${encodeURIComponent(value)}`).engine, `e=${value}`).toBe("replay");
    }
    expect(decode("?e=garch&e=copula").engine).toBe("garch");
    expect(encode(decode("?u=tsp&e=foo"))).toBe("?u=tsp&lb=5y&d=auto");
  });

  it("names the engines of the tensor contract", () => {
    expect([...ENGINES]).toEqual([...ENGINE_IDS]);
    const schema = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "../portfoliosight/engine/tensor.schema.json"), "utf-8"));
    expect(Object.keys(schema.properties.engines.properties)).toEqual([...ENGINES]);
  });

  it("knows the lookbacks of the tensor contract", () => {
    const schema = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "../portfoliosight/engine/tensor.schema.json"), "utf-8"));
    expect([...LOOKBACKS]).toEqual(schema.properties.lookback.properties.id.enum);
    for (const lookback of LOOKBACKS) expect(decode(`?lb=${lookback}`).lookback).toBe(lookback);
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
