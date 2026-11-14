// @vitest-environment jsdom
// Owner direction 2026-11-14: the line from our tests on past data stands under the diversification
// slider when Details is on, and only then. With Details off it is not on the page and the slider has
// no description pointing at it. With Details on it is shown once, on desktop (vertical slider) and on
// a phone (horizontal slider), outside the Details panel, and the slider's description names it.
import fs from "node:fs";
import path from "node:path";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { plain } from "../src/copy";

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

/** The wording lives in one copy constant; the test reads it from there so a rewording changes one place. */
const LINE = plain.testedOnPastData;
const count = (text: string) => text.split(LINE).length - 1;

function page(phone: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/presets")) return json(presets);
      if (url.endsWith(`/${H}/5y`)) return json(RAW);
      return json({ error: { code: "not_found", message: "", details: null } }, 404);
    }),
  );
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: phone && query.includes("max-width: 768px"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
  window.history.replaceState(null, "", "/?u=guide2017&lb=5y&r=20.5&d=0");
  return render(<App />);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe.each([
  ["desktop", false],
  ["phone", true],
])("on %s", (_name, phone) => {
  it("with Details off, shows no past-data line and the slider has no description", async () => {
    const { container } = page(phone);
    await waitFor(() => expect(screen.getByTestId("div-slider")).toBeTruthy(), { timeout: 5000 });
    expect(screen.getByTestId("details-toggle").getAttribute("aria-pressed")).toBe("false");
    expect(screen.queryByTestId("past-data-line"), "no line element").toBeNull();
    expect(count(container.textContent ?? ""), "the wording is nowhere on the page").toBe(0);
    const slider = screen.getByTestId("div-slider");
    const ids = (slider.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean);
    for (const id of ids) expect(document.getElementById(id), `aria-describedby names #${id}, which is not on the page`).not.toBeNull();
    expect(slider.hasAttribute("aria-describedby"), "the slider has no description attached").toBe(false);
  });

  it("with Details on, shows the line once under the diversification slider, outside the Details panel", async () => {
    const { container } = page(phone);
    await waitFor(() => expect(screen.getByTestId("div-slider")).toBeTruthy(), { timeout: 5000 });
    fireEvent.click(screen.getByTestId("details-toggle"));
    await waitFor(() => expect(screen.getByTestId("details-enb")).toBeTruthy());
    expect(screen.getByTestId("details-toggle").getAttribute("aria-pressed")).toBe("true");
    const el = screen.getByTestId("past-data-line");
    expect(el.textContent).toBe(LINE);
    // it belongs to the slider, not to the strip or the details: inside the horizontal slider's block on a
    // phone, and directly after the vertical slider's column (the cell under it) beside the chart
    const block = screen.getByTestId("div-slider").closest(".divs");
    expect(block, "the slider has a block").not.toBeNull();
    if (phone) expect(block!.contains(el), "the line is in the diversification slider's block").toBe(true);
    else expect(block!.nextElementSibling, "the line follows the slider's column").toBe(el);
    // under the slider, not above it: the slider comes first in document order
    expect(screen.getByTestId("div-slider").compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // not part of the strip or the Details panel, which is open
    const panel = container.querySelector(".details-panel");
    expect(panel, "the details panel is open").not.toBeNull();
    expect(panel!.contains(el), "not inside the details panel").toBe(false);
    expect(el.closest(".strip, .details-panel"), "not part of the strip or the details").toBeNull();
    expect(count(panel!.textContent ?? ""), "not in the details text").toBe(0);
    expect(screen.queryByTestId("details-tested")).toBeNull();
    expect(count(container.textContent ?? ""), "shown once on the page").toBe(1);
  });

  it("with Details on, the slider's description names the line", async () => {
    page(phone);
    await waitFor(() => expect(screen.getByTestId("div-slider")).toBeTruthy(), { timeout: 5000 });
    fireEvent.click(screen.getByTestId("details-toggle"));
    await waitFor(() => expect(screen.getByTestId("details-enb")).toBeTruthy());
    const el = screen.getByTestId("past-data-line");
    const ids = (screen.getByTestId("div-slider").getAttribute("aria-describedby") ?? "").split(/\s+/);
    expect(el.id, "the line has an id").not.toBe("");
    expect(ids, "the slider is described by the line").toContain(el.id);
  });

  it("turning Details off again takes the line and the description away", async () => {
    const { container } = page(phone);
    await waitFor(() => expect(screen.getByTestId("div-slider")).toBeTruthy(), { timeout: 5000 });
    fireEvent.click(screen.getByTestId("details-toggle"));
    await waitFor(() => expect(screen.getByTestId("past-data-line")).toBeTruthy());
    fireEvent.click(screen.getByTestId("details-toggle"));
    await waitFor(() => expect(screen.queryByTestId("past-data-line")).toBeNull());
    expect(count(container.textContent ?? "")).toBe(0);
    expect(screen.getByTestId("div-slider").hasAttribute("aria-describedby")).toBe(false);
  });
});
