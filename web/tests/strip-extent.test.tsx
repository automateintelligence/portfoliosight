// @vitest-environment jsdom
// The strip's bar keeps one extent per (menu, history window) while the selected mix moves, the
// service's exact ranges arrive (some just outside the node figures, as the live service does)
// and a ghost window's tensor loads late.
import fs from "node:fs";
import path from "node:path";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "../src/App";
import { parseTensor } from "../src/api/client";
import { stripScale, tensorBounds } from "../src/math/stripScale";

const RAW = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8"));
const T5 = parseTensor(RAW);
const G = RAW.generation as string;
const H = RAW.universe.hash as string;
const NODES = tensorBounds(T5);

/** The fixture as the 1y window, every range moved out by `by` (a ghost reaching further). */
function wider(by: number) {
  const t = structuredClone(RAW);
  t.lookback = { ...t.lookback, id: "1y" };
  const out = (xs: number[], s: number) => xs.map((x) => x + s * by);
  t.frontier.range.bad = out(t.frontier.range.bad, -1);
  t.frontier.range.good = out(t.frontier.range.good, 1);
  t.ladder.range.bad = t.ladder.range.bad.map((c: number[]) => out(c, -1));
  t.ladder.range.good = t.ladder.range.good.map((c: number[]) => out(c, 1));
  return t;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const lookbacks = Object.fromEntries(["1y", "2y", "3y", "5y", "10y", "ew"].map((lb) => [lb, { status: "ready", url: `/api/tensors/${G}/${H}/${lb}` }]));
const presets = {
  generation: G,
  asof: RAW.asof,
  presets: [{ id: "guide2017", name: "Example Portfolio", hash: H, funds: RAW.universe.funds.map((f: { id: string; name: string }) => ({ id: f.id, name: f.name })), allocation: null, allocation_unit: null, lookbacks }],
};

let releaseGhost: () => void = () => undefined;
let answers: { bad: number; typical: number; good: number }[] = [];

beforeEach(() => {
  answers = [];
  const ghost = new Promise<void>((resolve) => {
    releaseGhost = resolve;
  });
  // each exact answer steps a little further outside the node figures, as a blend can
  let n = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/presets")) return json(presets);
      if (url.endsWith(`/${H}/5y`)) return json(RAW);
      if (url.endsWith(`/${H}/1y`)) {
        await ghost;
        return json(wider(0.12));
      }
      if (url.endsWith("/api/range") && init?.method === "POST") {
        n += 1;
        const answer = { bad: NODES.min - 0.02 * n, typical: 0.05, good: NODES.max + 0.02 * n };
        answers.push(answer);
        return json(answer);
      }
      return json({ error: { code: "not_found", message: "", details: null } }, 404);
    }),
  );
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
  window.history.replaceState(null, "", `/?u=guide2017&lb=5y&g=1y&r=20.5&d=0.4`);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const extent = () => {
  const bar = screen.getByTestId("range-bar");
  return [Number(bar.getAttribute("data-lo")), Number(bar.getAttribute("data-hi"))];
};

it("the bar's extent holds still while the mix moves, exact ranges arrive and a ghost window loads", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByTestId("range-bar")).toBeTruthy(), { timeout: 5000 });
  const want = stripScale(NODES);
  const first = extent();
  expect(first[0]).toBeCloseTo(want.lo, 6);
  expect(first[1]).toBeCloseTo(want.hi, 6);
  const slider = screen.getByTestId("div-slider");
  for (let step = 0; step < 4; step++) {
    fireEvent.keyDown(slider, { key: "ArrowDown" });
    // the sliders rest: the service answers for these exact weights
    await waitFor(() => expect(answers.length).toBe(step + 1), { timeout: 3000 });
    await waitFor(() => expect(screen.getByTestId("range-low").textContent).toContain(`${((NODES.min - 0.02 * (step + 1)) * -100).toFixed(1)}%`));
    expect(extent(), `after exact answer ${step + 1}`).toEqual(first);
  }
  // the ghost window's tensor arrives late, reaching further than this window's nodes
  await act(async () => {
    releaseGhost();
    await new Promise((r) => setTimeout(r, 50));
  });
  fireEvent.keyDown(slider, { key: "ArrowDown" });
  await waitFor(() => expect(answers.length).toBe(5), { timeout: 3000 });
  expect(extent(), "after the ghost window loaded").toEqual(first);
  // a figure outside the extent is drawn at the end with an overflow mark
  await waitFor(() => expect(screen.getByTestId("range-mark-low").getAttribute("data-over")).toBe("low"));
  expect(screen.getByTestId("range-mark-high").getAttribute("data-over")).toBe("high");
});
