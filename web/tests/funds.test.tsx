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
const tensor = parseTensor(JSON.parse(fs.readFileSync(path.join(here, "..", "fixtures", "guide2017_5y.json"), "utf8")));
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
