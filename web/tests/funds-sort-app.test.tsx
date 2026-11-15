// @vitest-environment jsdom
// The page wires the "interaction in progress" signal to the Funds table (owner direction
// 2026-11-11): with the table sorted on "Selected mix %", a drag of the risk slider leaves the rows
// where they are while the figures move, and the release sorts them once.
import fs from "node:fs";
import path from "node:path";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "../src/App";

const RAW = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8"));
const G = RAW.generation as string;
const H = RAW.universe.hash as string;

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const lookbacks = Object.fromEntries(["1y", "2y", "3y", "5y", "10y", "ew"].map((lb) => [lb, { status: "ready", url: `/api/tensors/${G}/${H}/${lb}` }]));
const presets = {
  generation: G,
  asof: RAW.asof,
  presets: [{ id: "guide2017", name: "Example Portfolio", hash: H, funds: RAW.universe.funds.map((f: { id: string; name: string }) => ({ id: f.id, name: f.name })), allocation: null, allocation_unit: null, lookbacks }],
};

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/presets")) return json(presets);
      if (url.includes(`/${H}/`)) return json(RAW);
      return json({ error: { code: "not_found", message: "", details: null } }, 404);
    }),
  );
  // jsdom lays nothing out: give the chart a size so it draws its axes and the risk slider
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(800);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(500);
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
  window.history.replaceState(null, "", "/?u=guide2017&lb=5y&r=20.5&d=0.4");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const mouse = { pointerType: "mouse", button: 0, buttons: 1, pointerId: 1 };
const table = () => screen.getByTestId("section-funds");
const order = () => within(table()).getAllByRole("listitem").map((el) => el.getAttribute("data-testid")!.replace("fund-row-", ""));
const figures = () => Object.fromEntries(order().map((id) => [id, screen.getByTestId(`mix-selected-${id}`).textContent]));
/** The Selected mix % figures down the table, as numbers (the page writes a minus sign as U+2212). */
const column = () => order().map((id) => Number.parseFloat((screen.getByTestId(`mix-selected-${id}`).textContent ?? "").replace("\u2212", "-")));
const largestFirst = (xs: number[]) => xs.every((x, i) => i === 0 || xs[i - 1] >= x);

it("holds the Funds order through a drag of the risk slider and sorts it once on release", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByTestId("risk-slider").getAttribute("tabindex")).toBe("0"), { timeout: 5000 });
  fireEvent.click(within(table()).getByRole("button", { name: "Funds & amounts" }));
  const sort = screen.getByLabelText("Sort by") as HTMLSelectElement;
  fireEvent.change(sort, { target: { value: Array.from(sort.options).find((o) => o.textContent === "Selected mix %")!.value } });
  const before = order();
  const figuresBefore = figures();

  const slider = screen.getByTestId("risk-slider");
  fireEvent.pointerDown(slider, { ...mouse, clientX: 700, clientY: 5 });
  fireEvent.pointerMove(slider, { ...mouse, clientX: 750, clientY: 5 });
  expect(figures(), "the drag moved the selected mix").not.toEqual(figuresBefore);
  expect(order(), "during the drag").toEqual(before);

  fireEvent.pointerUp(slider, { ...mouse });
  expect(largestFirst(column()), `after the release: ${column().join(", ")}`).toBe(true);
  expect(order(), "the release re-sorted").not.toEqual(before);
});
