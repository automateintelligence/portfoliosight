// @vitest-environment jsdom
// The Settings checkbox for the No allocation limits line (owner direction 2026-11-15).
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseTensor } from "../src/api/client";
import { limitsBind } from "../src/math/view";
import { Settings } from "../src/sections/Settings";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixture = JSON.parse(fs.readFileSync(path.join(here, "..", "fixtures", "guide2017_5y.json"), "utf8"));
const noop = () => undefined;

afterEach(cleanup);

const binding = () => parseTensor(fixture);
// the same menu with every limit lifted gives the same frontier: nothing for the line to show
const loose = () => parseTensor({ ...fixture, frontier_uncapped: { sigma: fixture.frontier.x, mu: fixture.frontier.y } });

function show(tensor: ReturnType<typeof parseTensor>, showNoLimits: boolean, onNoLimitsLine: (show: boolean) => void = noop) {
  render(
    <Settings tensor={tensor} lookback="5y" ghosts={[]} caps={[]} unavailable={{}} details={false} busy={false} problem={null} adminMenuMax={null} showNoLimits={showNoLimits} onLookback={noop} onGhost={noop} onCaps={noop} onNoLimitsLine={onNoLimitsLine} onShare={noop} />,
  );
  return screen.getByRole("checkbox", { name: /no allocation limits/i }) as HTMLInputElement;
}

describe("the No allocation limits line checkbox", () => {
  it("the fixtures are what these tests say: the default menu's limits bind, the loosened one's do not", () => {
    expect(limitsBind(binding())).toBe(true);
    expect(limitsBind(loose())).toBe(false);
  });

  it("is a checkbox named for the line, checked when the line is shown, and asks for the opposite when pressed", () => {
    const onChange = vi.fn();
    const box = show(binding(), true, onChange);
    expect(box.checked).toBe(true);
    expect(box.disabled).toBe(false);
    fireEvent.click(box);
    expect(onChange).toHaveBeenLastCalledWith(false);
  });

  it("is unchecked when the line is hidden, and asks to show it when pressed", () => {
    const onChange = vi.fn();
    const box = show(binding(), false, onChange);
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    expect(onChange).toHaveBeenLastCalledWith(true);
  });

  it("is reachable by keyboard and by a screen reader like the other checkboxes: a native input with a visible label", () => {
    const box = show(binding(), true);
    expect(box.type).toBe("checkbox");
    expect(box.tabIndex).toBeGreaterThanOrEqual(0);
    expect(box.closest("label"), "the label is the checkbox's own, so the whole label is the hit area").not.toBeNull();
    // a ghost checkbox is built the same way
    const ghost = screen.getByTestId("ghost-10y");
    expect(ghost.closest("label")?.className).toBe(box.closest("label")?.className);
  });

  it("when the limits do not bind it stays on the page, disabled, keeps the choice and says why there is no line", () => {
    for (const choice of [true, false]) {
      const box = show(loose(), choice);
      expect(box.disabled).toBe(true);
      expect(box.checked, "the choice is kept for when the limits bind again").toBe(choice);
      expect(screen.getByTestId("nolimits-line-note").textContent).toMatch(/nothing to show/i);
      // like the other conditional controls (a window without history), the note is in the label, so a screen reader reads it with the box's name
      expect(box.closest("label")?.contains(screen.getByTestId("nolimits-line-note"))).toBe(true);
      cleanup();
    }
  });

  it("when the limits bind there is no note", () => {
    show(binding(), true);
    expect(screen.queryByTestId("nolimits-line-note")).toBeNull();
  });
});
