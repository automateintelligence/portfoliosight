// @vitest-environment jsdom
// Choosing the volatility model on the page (engines spec 6, S3, F4): every figure that shows a
// range moves to it at once, the tag says so, the address carries it, and nothing is fetched
// except the exact-range ask the page already makes once the sliders rest.
import fs from "node:fs";
import path from "node:path";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "../src/App";
import { parseTensor } from "../src/api/client";
import { signedPct } from "../src/format";
import { portfolioMath } from "../src/math/portfolio";
import { deriveView } from "../src/math/view";
import { forgetExactRanges } from "../src/state/useExactRange";

const RAW = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8"));
const T = parseTensor(RAW);
const G = RAW.generation as string;
const H = RAW.universe.hash as string;
const M = portfolioMath(T);

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const lookbacks = Object.fromEntries(["1y", "2y", "3y", "5y", "10y", "ew"].map((lb) => [lb, { status: "ready", url: `/api/tensors/${G}/${H}/${lb}` }]));
const presets = {
  generation: G,
  asof: RAW.asof,
  presets: [{ id: "guide2017", name: "Example Portfolio", hash: H, funds: RAW.universe.funds.map((f: { id: string; name: string }) => ({ id: f.id, name: f.name })), allocation: null, allocation_unit: null, lookbacks }],
};

let requests: { method: string; url: string; body: Record<string, unknown> | null }[] = [];
let tensor: unknown;
let exact = true;

beforeEach(() => {
  requests = [];
  tensor = RAW;
  exact = true;
  forgetExactRanges();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ method: init?.method ?? "GET", url, body: typeof init?.body === "string" ? JSON.parse(init.body) : null });
      if (url.endsWith("/api/presets")) return json(presets);
      if (url.endsWith(`/${H}/5y`)) return json(tensor);
      if (url.endsWith("/api/range") && init?.method === "POST") {
        const body = JSON.parse(init.body as string);
        if (!exact) return json({ error: { code: "range_unavailable", message: "", details: null } }, 409);
        return json({ engine: body.engine ?? "replay", bad: -0.5, typical: 0.01, good: 0.5, loss_sources: null });
      }
      return json({ error: { code: "not_found", message: "", details: null } }, 404);
    }),
  );
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
  window.history.replaceState(null, "", "/?u=guide2017&lb=5y&r=20&d=0.4");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const text = (id: string) => screen.getByTestId(id).textContent as string;
// jsdom has no layout, so the chart and the risk slider (which sits on its scales) are not drawn
// here; the strip's tag is, and the slider's tag is checked in engine-ui.test.tsx and the e2e run.
const tags = () => screen.getAllByTestId("engine-tag").map((tag) => tag.textContent);
const figure = (id: string) => (text(id).match(/[−+]?\d+\.\d%/) as RegExpMatchArray)[0];

async function openSettings() {
  render(<App />);
  await waitFor(() => expect(screen.getByTestId("range-bar")).toBeTruthy(), { timeout: 5000 });
  fireEvent.click(screen.getByTestId("chip-settings"));
  await waitFor(() => expect(screen.getByTestId("engine-garch")).toBeTruthy());
}

it("switching to the volatility model moves the strip's figures and tag at once, without a request", async () => {
  await openSettings();
  const before = requests.length;
  const replay = deriveView(T, M, 20, 0.4, "replay");
  expect(figure("range-low")).toBe(signedPct(replay.range.low));
  expect(tags()).toEqual(["History replay"]);

  fireEvent.click(screen.getByTestId("engine-garch"));
  const garch = deriveView(T, M, 20, 0.4, "garch");
  // the same React batch: no timer, no await
  expect(figure("range-low")).toBe(signedPct(garch.range.low));
  expect(figure("range-typical")).toBe(signedPct(garch.range.typical));
  expect(figure("range-high")).toBe(signedPct(garch.range.high));
  expect(figure("range-low")).not.toBe(signedPct(replay.range.low));
  expect(tags()).toEqual(["Volatility model"]);
  expect(requests.length, "nothing is fetched on the click").toBe(before);
  expect((screen.getByTestId("engine-garch") as HTMLInputElement).checked).toBe(true);

  // the address says so once the debounce passes, and a reload would read it back
  await waitFor(() => expect(window.location.search).toMatch(/[?&]e=garch$/), { timeout: 2000 });
  fireEvent.click(screen.getByTestId("engine-replay"));
  await waitFor(() => expect(window.location.search).not.toContain("e="), { timeout: 2000 });
});

it("asks the service for the resting mix under the chosen engine, by name, and never rebuilds a tensor", async () => {
  await openSettings();
  const from = requests.length;
  fireEvent.click(screen.getByTestId("engine-garch"));
  await waitFor(() => expect(requests.slice(from).some((r) => r.url.endsWith("/api/range"))).toBe(true), { timeout: 3000 });
  const asked = requests.slice(from).filter((r) => r.url.endsWith("/api/range"));
  expect(asked.every((r) => r.body?.engine === "garch")).toBe(true);
  // the service's answer for the engine replaces the node figure
  await waitFor(() => expect(figure("range-low")).toBe(signedPct(-0.5)), { timeout: 2000 });
  expect(requests.filter((r) => r.method === "POST" && r.url.endsWith("/api/tensors"))).toEqual([]);
  expect(requests.filter((r) => r.url.includes("/api/tensors/")).length, "the tensor was fetched once, at load").toBe(1);
});

it("History replay never names an engine to the service", async () => {
  render(<App />);
  await waitFor(() => expect(requests.some((r) => r.url.endsWith("/api/range"))).toBe(true), { timeout: 3000 });
  for (const r of requests.filter((r) => r.url.endsWith("/api/range"))) expect(Object.keys(r.body ?? {})).not.toContain("engine");
});

it("a link to the volatility model opens on it", async () => {
  exact = false;
  window.history.replaceState(null, "", "/?u=guide2017&lb=5y&r=20&d=0.4&e=garch");
  render(<App />);
  await waitFor(() => expect(screen.getByTestId("range-bar")).toBeTruthy(), { timeout: 5000 });
  expect(tags()).toEqual(["Volatility model"]);
  expect(figure("range-low")).toBe(signedPct(deriveView(T, M, 20, 0.4, "garch").range.low));
});

it("a tensor without the volatility model puts the link back to History replay and says why in Settings", async () => {
  const raw = structuredClone(RAW);
  raw.engines.garch = { status: "unavailable", reason: "not enough shared history for the volatility model", method: null };
  delete raw.frontier.ranges.garch;
  delete raw.ladder.ranges.garch;
  delete raw.entered.ranges.garch;
  tensor = raw;
  window.history.replaceState(null, "", "/?u=guide2017&lb=5y&r=20&d=0.4&e=garch");
  await openSettings();
  expect(tags()).toEqual(["History replay"]);
  const garch = screen.getByTestId("engine-garch") as HTMLInputElement;
  expect(garch.disabled).toBe(true);
  expect(screen.getByTestId("engine-garch-reason").textContent).toBe("not enough shared history for the volatility model");
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 400));
  });
  expect(window.location.search).not.toContain("e=");
});
