// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it, vi } from "vitest";
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

it("keeps the limit of a fund this view sets aside when the limit of another fund is edited", () => {
  // Example Portfolio 2 sets WMT aside while the data for it is not served, and its limit is
  // part of the menu's policy: dropping it would turn the preset into a menu with another key.
  const excluded = [{ id: "SGOV", reason: "no data since 2024-10-30", last_close: null }];
  const tensor = parseTensor({ ...fixture, universe: { ...fixture.universe, excluded } });
  const onCaps = vi.fn();
  const caps = [
    { id: "SGOV", min: null, max: 10 },
    { id: "VTI", min: null, max: 40 },
  ];
  render(<Settings tensor={tensor} lookback="5y" ghosts={[]} caps={caps} unavailable={{}} details={false} busy={false} problem={null} adminMenuMax={null} onLookback={noop} onGhost={noop} onCaps={onCaps} onShare={noop} />);
  expect(screen.queryByTestId("cap-max-SGOV")).toBeNull();
  expect((screen.getByTestId("cap-max-VTI") as HTMLInputElement).value).toBe("40");
  const field = screen.getByTestId("cap-max-VTI");
  fireEvent.change(field, { target: { value: "30" } });
  fireEvent.blur(field);
  expect(onCaps).toHaveBeenLastCalledWith([
    { id: "VTI", min: null, max: 30 },
    { id: "SGOV", min: null, max: 10 },
  ]);
});
