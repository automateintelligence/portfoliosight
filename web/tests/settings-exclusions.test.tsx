// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";
import { Settings } from "../src/sections/Settings";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(fs.readFileSync(path.join(here, "..", "fixtures", "guide2017_5y.json"), "utf8"));
const noop = () => undefined;

afterEach(cleanup);

function show(excluded: { id: string; reason: string; last_close: number | null }[]) {
  const tensor = parseTensor({ ...fixture, universe: { ...fixture.universe, excluded } });
  render(<Settings tensor={tensor} lookback="10y" ghosts={[]} caps={[]} unavailable={{}} details={false} busy={false} problem={null} adminMenuMax={null} onLookback={noop} onGhost={noop} onCaps={noop} onShare={noop} />);
}

it("lists each fund set aside in this view with its reason, one note per fund", () => {
  show([
    { id: "SGOV", reason: "history starts 2020-05-28, not enough for the 10 years view", last_close: 100.4 },
    { id: "ZZZX", reason: "no data since 2024-10-30", last_close: null },
  ]);
  const notes = screen.getAllByTestId("excluded-note");
  expect(notes.map((note) => note.textContent)).toEqual(["SGOV: history starts 2020-05-28, not enough for the 10 years view", "ZZZX: no data since 2024-10-30"]);
  expect(within(notes[0].parentElement as HTMLElement).getAllByRole("listitem").length).toBe(2);
});

it("shows no list and no note when every fund is in use", () => {
  show([]);
  expect(screen.queryAllByTestId("excluded-note")).toEqual([]);
  expect(screen.queryByText("Set aside in this view:")).toBeNull();
});

it("shows a small Admin tag only in admin mode", () => {
  const tensor = parseTensor(fixture);
  const view = (adminMenuMax: number | null) =>
    render(<Settings tensor={tensor} lookback="5y" ghosts={[]} caps={[]} unavailable={{}} details={false} busy={false} problem={null} adminMenuMax={adminMenuMax} onLookback={noop} onGhost={noop} onCaps={noop} onShare={noop} />);
  view(null);
  expect(screen.queryByTestId("admin-tag")).toBeNull();
  cleanup();
  view(100);
  expect(screen.getByTestId("admin-tag").textContent).toBe("Admin");
  expect(screen.getByText("Admin mode: menus of up to 100 funds.")).toBeTruthy();
});
