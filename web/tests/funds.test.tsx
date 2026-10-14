// @vitest-environment jsdom
// Funds & amounts: the two always-on percentage columns, the units, and the recalculate button.
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, expect, it, vi } from "vitest";
import { parseTensor } from "../src/api/client";
import { ThemeSwitch } from "../src/controls/ThemeSwitch";
import { Funds } from "../src/sections/Funds";
import type { Row, Unit } from "../src/state/store";

const here = path.dirname(fileURLToPath(import.meta.url));
const raw = JSON.parse(fs.readFileSync(path.join(here, "..", "fixtures", "guide2017_5y.json"), "utf8"));
const tensor = parseTensor(raw);
const funds = tensor.universe.funds;
const noop = () => undefined;
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

afterEach(cleanup);

function show(opts: { unit: Unit; amounts: (number | null)[]; selected?: number[] | null; onUseMenu?: (rows: Row[]) => void; onAmount?: (id: string, amount: number | null) => void; onUnit?: (unit: Unit) => void }) {
  const rows: Row[] = funds.map((f, i) => ({ id: f.id, name: f.name ?? f.id, amount: opts.amounts[i] ?? null }));
  const selected = opts.selected === undefined ? funds.map((_, i) => (i === 0 ? 0.4 : i === 1 ? 0.6 : 0)) : opts.selected;
  const symbols = [...funds.map((f) => ({ id: f.id, name: f.name ?? f.id })), { id: "ZZNEW", name: "A New Fund" }];
  const props = { rows, unit: opts.unit, tensor, symbols: symbols as never, mixStatus: "ok" as const, setAside: 0, menuError: null, busy: false, selected, onUnit: opts.onUnit ?? noop, onAmount: opts.onAmount ?? noop, onUseMenu: opts.onUseMenu ?? noop, onNeedSymbols: noop };
  return { rows, ...render(<Funds {...props} />) };
}
const cell = (kind: "entered" | "selected", id: string) => screen.getByTestId(`mix-${kind}-${id}`).textContent;

it("shows both percentage columns in every unit, the entered one from the amounts", () => {
  const [a, b] = [funds[0], funds[1]];
  const cases: { unit: Unit; amounts: number[]; want: [number, number] }[] = [
    { unit: "usd", amounts: [3000, 1000], want: [0.75, 0.25] },
    { unit: "pct", amounts: [75, 25], want: [0.75, 0.25] },
    { unit: "shares", amounts: [10, 10], want: [a.last_close! / (a.last_close! + b.last_close!), b.last_close! / (a.last_close! + b.last_close!)] },
  ];
  for (const c of cases) {
    show({ unit: c.unit, amounts: c.amounts });
    expect(screen.getByText("Mix entered %")).toBeTruthy();
    expect(screen.getByText("Selected mix %")).toBeTruthy();
    expect(cell("entered", a.id), c.unit).toBe(pct(c.want[0]));
    expect(cell("entered", b.id), c.unit).toBe(pct(c.want[1]));
    expect(cell("entered", funds[2].id), c.unit).toBe("0.0%");
    expect(cell("selected", a.id)).toBe("40.0%");
    expect(cell("selected", b.id)).toBe("60.0%");
    cleanup();
  }
});

it("scales percentages up over the funds in use when one fund is set aside", () => {
  const out = { id: "ZZOUT" };
  const partial = parseTensor({ ...raw, universe: { ...raw.universe, excluded: [{ id: out.id, reason: "no data since 2024-10-30", last_close: null }] } });
  const rows: Row[] = [funds[0], funds[1], out].map((f, i) => ({ id: f.id, name: f.id, amount: [60, 20, 20][i] }));
  render(<Funds rows={rows} unit="pct" tensor={partial} symbols={null} mixStatus="ok" setAside={0.2} menuError={null} busy={false} selected={null} onUnit={noop} onAmount={noop} onUseMenu={noop} onNeedSymbols={noop} />);
  // exactly 100%: no running total and no Scale to 100%
  expect(screen.queryByTestId("funds-total")).toBeNull();
  expect(screen.queryByTestId("funds-scale100")).toBeNull();
  expect(cell("entered", funds[0].id)).toBe("75.0%");
  expect(cell("entered", funds[1].id)).toBe("25.0%");
  expect(cell("entered", out.id)).toBe("");
});

it("names each percentage for a screen reader", () => {
  show({ unit: "usd", amounts: [3000, 1000] });
  expect(screen.getByTestId(`mix-entered-${funds[0].id}`).parentElement?.textContent).toBe("Mix entered %: 75.0%");
  expect(screen.getByTestId(`mix-selected-${funds[0].id}`).parentElement?.textContent).toBe("Selected mix %: 40.0%");
});

it("leaves the entered column blank when no amounts are entered, and still shows the selected mix", () => {
  show({ unit: "usd", amounts: [] });
  for (const f of funds) expect(cell("entered", f.id)).toBe("");
  expect(cell("selected", funds[1].id)).toBe("60.0%");
});

it("follows the selected point as it moves", () => {
  const first = show({ unit: "usd", amounts: [1, 1], selected: funds.map((_, i) => (i === 2 ? 1 : 0)) });
  expect(cell("selected", funds[2].id)).toBe("100.0%");
  first.unmount();
  show({ unit: "usd", amounts: [1, 1], selected: funds.map((_, i) => (i === 3 ? 0.125 : i === 2 ? 0.875 : 0)) });
  expect(cell("selected", funds[2].id)).toBe("87.5%");
  expect(cell("selected", funds[3].id)).toBe("12.5%");
});

it("offers Shares, % and $, and heads the amount column Shares (Qty) in the share unit", () => {
  const onUnit = vi.fn();
  show({ unit: "shares", amounts: [10, 10], onUnit });
  const options = within(screen.getByTestId("unit-toggle")).getAllByRole("radio");
  expect(options.map((o) => o.textContent)).toEqual(["Shares", "%", "$"]);
  expect(options[0].getAttribute("aria-checked")).toBe("true");
  expect(screen.getByTestId("amount-head").textContent).toBe("Shares (Qty)");
  fireEvent.click(options[2]);
  expect(onUnit).toHaveBeenCalledWith("usd");
});

it("says amounts apply as you type and applies them without a button", () => {
  const onAmount = vi.fn();
  show({ unit: "usd", amounts: [100, 100], onAmount });
  expect(screen.getByTestId("funds-hint").textContent).toBe("Amounts apply as you type.");
  expect(screen.queryByTestId("use-menu")).toBeNull();
  fireEvent.change(screen.getByLabelText(`${funds[0].id} amount in dollars`), { target: { value: "250" } });
  expect(onAmount).toHaveBeenCalledWith(funds[0].id, 250);
  expect(screen.queryByTestId("use-menu")).toBeNull();
});

it("shows Recalculate with these funds only while the fund list differs from the one plotted", () => {
  const onUseMenu = vi.fn();
  const { rows } = show({ unit: "usd", amounts: [100, 100], onUseMenu });
  expect(screen.queryByText("Use this menu")).toBeNull();
  // remove a fund: the button appears
  fireEvent.click(screen.getByLabelText(`Remove ${funds[0].id}`));
  const button = screen.getByTestId("use-menu");
  expect(button.textContent).toBe("Recalculate with these funds");
  // put it back: the list is what is plotted again, so the button goes
  fireEvent.change(screen.getByTestId("fund-add"), { target: { value: funds[0].id } });
  fireEvent.keyDown(screen.getByTestId("fund-add"), { key: "Enter" });
  expect(screen.queryByTestId("use-menu")).toBeNull();
  // add a new fund and recalculate
  fireEvent.change(screen.getByTestId("fund-add"), { target: { value: "ZZNEW" } });
  fireEvent.keyDown(screen.getByTestId("fund-add"), { key: "Enter" });
  fireEvent.click(screen.getByTestId("use-menu"));
  expect(onUseMenu).toHaveBeenCalledTimes(1);
  expect(onUseMenu.mock.calls[0][0].map((r: Row) => r.id)).toEqual([...rows.map((r) => r.id), "ZZNEW"]);
});

it("the theme switch offers four looks in order, as segments and as one cycling button", () => {
  const onChange = vi.fn();
  const wide = render(<ThemeSwitch theme="hud" compact={false} onChange={onChange} />);
  const segments = within(screen.getByTestId("theme-switch")).getAllByRole("radio");
  expect(segments.map((s) => s.textContent)).toEqual(["Dark", "Light", "HUD", "Grid"]);
  expect(segments.map((s) => s.getAttribute("aria-checked"))).toEqual(["false", "false", "true", "false"]);
  fireEvent.click(segments[3]);
  expect(onChange).toHaveBeenLastCalledWith("grid");
  wide.unmount();
  for (const [from, to] of [["ks-dark", "light"], ["light", "hud"], ["hud", "grid"], ["grid", "ks-dark"]] as const) {
    const one = render(<ThemeSwitch theme={from} compact onChange={onChange} />);
    fireEvent.click(screen.getByTestId("theme-switch"));
    expect(onChange).toHaveBeenLastCalledWith(to);
    one.unmount();
  }
});

it("in %, shows the running total and Scale to 100% together while the entries are not exactly 100%", () => {
  const onAmount = vi.fn();
  show({ unit: "pct", amounts: [60, 32], onAmount });
  expect(screen.getByTestId("funds-total").textContent).toBe("Total: 92%, 8% to go");
  const scale = screen.getByTestId("funds-scale100");
  expect(scale.getAttribute("aria-label")).toMatch(/^Scale to 100%: /);
  expect(scale.textContent).toBe("Scale to 100%");
  fireEvent.click(scale);
  expect(onAmount.mock.calls).toEqual([
    [funds[0].id, 65.22],
    [funds[1].id, 34.78],
  ]);
  cleanup();
  show({ unit: "pct", amounts: [70, 38.9] });
  expect(screen.getByTestId("funds-total").textContent).toBe("Total: 108.9%, 8.9% over");
  cleanup();
  // inside the drawing rule (100 +- 0.05) but not exactly 100 at the fields' precision
  show({ unit: "pct", amounts: [60, 39.98] });
  expect(screen.getByTestId("funds-total").textContent).toBe("Total: 99.98%, 0.02% to go");
  expect(screen.getByTestId("funds-scale100")).toBeTruthy();
});

it("hides the running total and Scale to 100% at exactly 100%, with nothing entered, and in $ and Shares", () => {
  const cases: { unit: Unit; amounts: (number | null)[] }[] = [
    { unit: "pct", amounts: [60, 40] },
    { unit: "pct", amounts: [33.33, 33.33, 33.34] },
    { unit: "pct", amounts: [] },
    { unit: "pct", amounts: [0, 0] },
    { unit: "usd", amounts: [3000, 1000] },
    { unit: "shares", amounts: [10, 3] },
  ];
  for (const c of cases) {
    show({ unit: c.unit, amounts: c.amounts });
    expect(screen.queryByTestId("funds-total"), JSON.stringify(c)).toBeNull();
    expect(screen.queryByTestId("funds-scale100"), JSON.stringify(c)).toBeNull();
    expect(screen.getByTestId("funds-clear"), "Clear all is in every unit").toBeTruthy();
    cleanup();
  }
  show({ unit: "pct", amounts: [] });
  expect(screen.getByTestId("funds-entered").textContent).toBe("No amounts entered: tickers only.");
  cleanup();
  show({ unit: "usd", amounts: [3000, 1000] });
  expect(screen.getByTestId("funds-entered").textContent).toBe("$4,000 entered");
});

it("Clear all empties every amount and keeps the fund list", () => {
  const onAmount = vi.fn();
  const onUseMenu = vi.fn();
  show({ unit: "usd", amounts: [3000, null, 500], onAmount, onUseMenu });
  const clear = screen.getByTestId("funds-clear");
  expect(clear.getAttribute("aria-label")).toMatch(/^Clear all: /);
  fireEvent.click(clear);
  expect(onAmount.mock.calls).toEqual([
    [funds[0].id, null],
    [funds[2].id, null],
  ]);
  expect(onUseMenu).not.toHaveBeenCalled();
  for (const f of funds) expect(screen.getByTestId(`fund-row-${f.id}`)).toBeTruthy();
  cleanup();
  show({ unit: "pct", amounts: [] });
  expect((screen.getByTestId("funds-clear") as HTMLButtonElement).disabled, "nothing to clear").toBe(true);
});

it("Clear all and Scale to 100% also act on a changed fund list before it is recalculated", () => {
  const onAmount = vi.fn();
  show({ unit: "pct", amounts: [30, 10], onAmount });
  fireEvent.change(screen.getByTestId("fund-add"), { target: { value: "ZZNEW" } });
  fireEvent.keyDown(screen.getByTestId("fund-add"), { key: "Enter" });
  expect(screen.getByTestId("use-menu")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("ZZNEW amount in percent"), { target: { value: "40" } });
  expect(screen.getByTestId("funds-total").textContent).toBe("Total: 80%, 20% to go");
  fireEvent.click(screen.getByTestId("funds-scale100"));
  expect(screen.queryByTestId("funds-total")).toBeNull();
  expect((screen.getByLabelText("ZZNEW amount in percent") as HTMLInputElement).value).toBe("50");
  expect(onAmount).toHaveBeenCalledWith(funds[0].id, 37.5);
  fireEvent.click(screen.getByTestId("funds-clear"));
  expect((screen.getByLabelText("ZZNEW amount in percent") as HTMLInputElement).value).toBe("");
  expect(screen.getByTestId("use-menu")).toBeTruthy();
});

it("Scale to 100% hands keyboard focus to Clear all as it goes away", () => {
  show({ unit: "pct", amounts: [60, 32] });
  const scale = screen.getByTestId("funds-scale100");
  scale.focus();
  fireEvent.click(scale);
  expect(document.activeElement).toBe(screen.getByTestId("funds-clear"));
});
