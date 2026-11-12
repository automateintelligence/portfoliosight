// @vitest-environment jsdom
// Funds & amounts: the two always-on percentage columns, the units, and the recalculate button.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseTensor } from "../src/api/client";
import { ThemeSwitch } from "../src/controls/ThemeSwitch";
import { Funds } from "../src/sections/Funds";
import { TEMPLATE_CSV, TEMPLATE_FILENAME } from "../src/sections/fundsCsv";
import type { Row, UploadReport, Unit } from "../src/state/store";
import type { TickerSource } from "../src/api/tickerShape";

const here = path.dirname(fileURLToPath(import.meta.url));
const raw = JSON.parse(fs.readFileSync(path.join(here, "..", "fixtures", "guide2017_5y.json"), "utf8"));
const tensor = parseTensor(raw);
const funds = tensor.universe.funds;
const noop = () => undefined;
const noUpload = { upload: null, onUpload: noop, onDismissUpload: noop, onRequestTickers: noop };
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

afterEach(cleanup);

function show(opts: { unit: Unit; amounts: (number | null)[]; selected?: number[] | null; onUseMenu?: (rows: Row[]) => void; onAmount?: (id: string, amount: number | null) => void; onUnit?: (unit: Unit) => void }) {
  const rows: Row[] = funds.map((f, i) => ({ id: f.id, name: f.name ?? f.id, amount: opts.amounts[i] ?? null }));
  const selected = opts.selected === undefined ? funds.map((_, i) => (i === 0 ? 0.4 : i === 1 ? 0.6 : 0)) : opts.selected;
  const symbols = [...funds.map((f) => ({ id: f.id, name: f.name ?? f.id })), { id: "ZZNEW", name: "A New Fund" }];
  const props = { rows, unit: opts.unit, tensor, symbols: symbols as never, mixStatus: "ok" as const, setAside: 0, menuError: null, busy: false, menuMax: 30, selected, onUnit: opts.onUnit ?? noop, onAmount: opts.onAmount ?? noop, onUseMenu: opts.onUseMenu ?? noop, onNeedSymbols: noop, ...noUpload };
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
    // the column heads (the "Sort by" list names both columns too)
    const head = within(document.querySelector<HTMLElement>(".row-head")!);
    expect(head.getByText("Mix entered %")).toBeTruthy();
    expect(head.getByText("Selected mix %")).toBeTruthy();
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
  render(<Funds rows={rows} unit="pct" tensor={partial} symbols={null} mixStatus="ok" setAside={0.2} menuError={null} busy={false} menuMax={30} selected={null} onUnit={noop} onAmount={noop} onUseMenu={noop} onNeedSymbols={noop} {...noUpload} />);
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
  expect(screen.getByTestId("mix-means").textContent).toBe("A mix, also called an allocation, is how your money is split across funds.");
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

it("keeps one live region mounted for the total, empty while there is nothing to say", () => {
  const rows = (amounts: number[]): Row[] => funds.slice(0, amounts.length).map((f, i) => ({ id: f.id, name: f.name ?? f.id, amount: amounts[i] }));
  const props = { unit: "pct" as const, tensor, symbols: null, mixStatus: "ok" as const, setAside: 0, menuError: null, busy: false, menuMax: 30, selected: null, onUnit: noop, onAmount: noop, onUseMenu: noop, onNeedSymbols: noop, ...noUpload };
  const { rerender } = render(<Funds {...props} rows={rows([60, 40])} />);
  const live = screen.getByRole("status");
  expect(live.textContent).toBe("");
  // the total goes off 100: the same region, now with the message
  rerender(<Funds {...props} rows={rows([60, 32])} />);
  expect(screen.getByRole("status")).toBe(live);
  expect(live.textContent).toBe("Total: 92%, 8% to go");
  rerender(<Funds {...props} rows={rows([60, 40])} />);
  expect(screen.getByRole("status")).toBe(live);
  expect(live.textContent).toBe("");
});

it("holds up to the tier's limit: the 31st fund refused for the public, accepted for an admin, the 101st refused for an admin", () => {
  const menu = (n: number): Row[] => Array.from({ length: n }, (_, i) => ({ id: `F${i}`, name: `Fund ${i}`, amount: null }));
  const symbols = [...menu(101).map((r) => ({ id: r.id, name: r.name })), { id: "ZZNEW", name: "A New Fund" }];
  const addZznew = () => {
    fireEvent.change(screen.getByTestId("fund-add"), { target: { value: "ZZNEW" } });
    fireEvent.keyDown(screen.getByTestId("fund-add"), { key: "Enter" });
  };
  const open = (rows: Row[], menuMax: number, onUseMenu = vi.fn()) => {
    render(<Funds rows={rows} unit="pct" tensor={null} symbols={symbols as never} mixStatus="empty" setAside={null} menuError={null} busy={false} menuMax={menuMax} selected={null} onUnit={noop} onAmount={noop} onUseMenu={onUseMenu} onNeedSymbols={noop} {...noUpload} />);
    return onUseMenu;
  };

  // public: 30 is full; the 31st is refused with a message and nothing to recalculate
  open(menu(30), 30);
  expect(screen.getByTestId("funds-limit").textContent).toContain("Up to 30 funds.");
  addZznew();
  expect(screen.getByRole("alert").textContent).toBe("A portfolio holds up to 30 funds.");
  expect(screen.queryByTestId("use-menu")).toBeNull();
  expect(screen.queryByTestId("fund-row-ZZNEW")).toBeNull();
  cleanup();

  // admin: the 31st goes in and can be recalculated
  const onUseMenu = open(menu(30), 100);
  expect(screen.getByTestId("funds-limit").textContent).toContain("Up to 100 funds.");
  addZznew();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByTestId("fund-row-ZZNEW")).toBeTruthy();
  fireEvent.click(screen.getByTestId("use-menu"));
  expect(onUseMenu.mock.calls[0][0].length).toBe(31);
  cleanup();

  // admin: 100 is full; the 101st is refused
  open(menu(100), 100);
  addZznew();
  expect(screen.getByRole("alert").textContent).toBe("A portfolio holds up to 100 funds.");
  expect(screen.queryByTestId("fund-row-ZZNEW")).toBeNull();
});

// ── CSV upload and download template ─────────────────────────────────────────
const [A, B, C, D] = funds.slice(0, 4).map((f) => f.id);
const catalog = funds.slice(0, 4).map((f) => ({ id: f.id, name: f.name ?? f.id }));

type Calls = { onUnit: (unit: Unit) => void; onAmount: (id: string, amount: number | null) => void; onUseMenu: (rows: Row[], unit?: Unit) => void; onRequestTickers: (tickers: string[], source: TickerSource) => void };
function Harness({ rows, unit, symbols, menuMax = 30, calls }: { rows: Row[]; unit: Unit; symbols: typeof catalog | null; menuMax?: number; calls: Calls }) {
  // the report lives in the page's store; this holds it the same way
  const [upload, setUpload] = useState<UploadReport | null>(null);
  return (
    <Funds
      rows={rows}
      unit={unit}
      tensor={tensor}
      symbols={symbols as never}
      mixStatus="ok"
      setAside={0}
      menuError={null}
      busy={false}
      menuMax={menuMax}
      selected={null}
      onUnit={calls.onUnit}
      onAmount={calls.onAmount}
      onUseMenu={calls.onUseMenu}
      onNeedSymbols={noop}
      upload={upload}
      onUpload={setUpload}
      onDismissUpload={() => setUpload(null)}
      onRequestTickers={calls.onRequestTickers}
    />
  );
}
function openUpload(opts: { plotted?: string[]; unit?: Unit; symbols?: typeof catalog | null; menuMax?: number } = {}) {
  const calls = { onUnit: vi.fn(), onAmount: vi.fn(), onUseMenu: vi.fn(), onRequestTickers: vi.fn() };
  const rows: Row[] = (opts.plotted ?? [A, B]).map((id) => ({ id, name: id, amount: null }));
  render(<Harness rows={rows} unit={opts.unit ?? "pct"} symbols={opts.symbols === undefined ? catalog : opts.symbols} menuMax={opts.menuMax} calls={calls} />);
  return calls;
}
const chooseFile = (text: string, name = "mix.csv") => {
  const input = screen.getByTestId("funds-file") as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File([text], name, { type: "text/csv" })] } });
};
const amounts = () => funds.slice(0, 4).map((f) => (screen.queryByLabelText(new RegExp(`^${f.id} amount in`)) as HTMLInputElement | null)?.value ?? null);

it("offers the template and the upload beside Clear all, and the upload button opens the file picker", () => {
  openUpload();
  const upload = screen.getByTestId("funds-upload");
  expect(screen.getByTestId("funds-template").textContent).toBe("Download template");
  expect(upload.textContent).toBe("Upload CSV");
  const input = screen.getByTestId("funds-file") as HTMLInputElement;
  expect(input.type).toBe("file");
  expect(input.accept).toBe(".csv,text/csv");
  expect(input.hidden).toBe(true);
  const click = vi.spyOn(input, "click").mockImplementation(() => undefined);
  fireEvent.click(upload);
  expect(click).toHaveBeenCalledTimes(1);
  // the file stays in the browser, and what does leave is said so
  expect(screen.getByTestId("funds-upload-hint").textContent).toMatch(/not uploaded/);
});

it("hands the template to the browser as portfoliosight-template.csv", async () => {
  openUpload();
  const blobs: Blob[] = [];
  const created = vi.fn((blob: Blob) => (blobs.push(blob), "blob:template"));
  Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
  const names: string[] = [];
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    names.push(this.download);
  });
  fireEvent.click(screen.getByTestId("funds-template"));
  expect(names).toEqual([TEMPLATE_FILENAME]);
  expect(await blobs[0].text()).toBe(TEMPLATE_CSV);
  click.mockRestore();
});

it("loads the funds of a file as the draft list with its amounts and unit, to be recalculated", async () => {
  const calls = openUpload({ plotted: [A, B], unit: "pct" });
  chooseFile(`ticker,dollars\n${C},6000\n${D},4000\n`);
  await screen.findByTestId("use-menu");
  expect(screen.queryByTestId(`fund-row-${A}`)).toBeNull();
  expect(amounts()).toEqual([null, null, "6000", "4000"]);
  // the table reads in dollars while the draft waits; nothing was changed in the page's menu yet
  expect(within(screen.getByTestId("unit-toggle")).getByRole("radio", { name: "$" }).getAttribute("aria-checked")).toBe("true");
  expect(screen.getByTestId("amount-head").textContent).toBe("Amount ($)");
  expect(calls.onUnit).not.toHaveBeenCalled();
  expect(calls.onUseMenu).not.toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("use-menu"));
  expect(calls.onUseMenu).toHaveBeenCalledTimes(1);
  const [rows, unit] = calls.onUseMenu.mock.calls[0] as [Row[], Unit];
  expect(rows.map((r) => [r.id, r.amount])).toEqual([[C, 6000], [D, 4000]]);
  expect(unit).toBe("usd");
});

it("uses shares when every fund with an amount has them, and percent only when it is all they share", async () => {
  const calls = openUpload({ plotted: [A, B], unit: "usd" });
  chooseFile(`ticker,shares,dollars,percent\n${C},10,1000,60\n${D},5,500,40\n`);
  await screen.findByTestId("use-menu");
  expect(screen.getByTestId("amount-head").textContent).toBe("Shares (Qty)");
  expect(amounts()).toEqual([null, null, "10", "5"]);
  cleanup();
  const again = openUpload({ plotted: [A, B], unit: "usd" });
  chooseFile(`ticker,shares,percent\n${C},10,60\n${D},,40\n`);
  await waitFor(() => expect(screen.getByTestId("amount-head").textContent).toBe("Share (%)"));
  expect(amounts()).toEqual([null, null, "60", "40"]);
  fireEvent.click(screen.getByTestId("use-menu"));
  expect(again.onUseMenu.mock.calls[0][1]).toBe("pct");
  expect(calls.onUseMenu).not.toHaveBeenCalled();
});

it("in percent, a draft that does not add up to 100% shows the running total and cannot be recalculated", async () => {
  openUpload({ plotted: [A, B], unit: "usd" });
  chooseFile(`ticker,percent\n${C},60\n${D},30\n`);
  await screen.findByTestId("funds-total");
  expect(screen.getByTestId("funds-total").textContent).toBe("Total: 90%, 10% to go");
  expect((screen.getByTestId("use-menu") as HTMLButtonElement).disabled).toBe(true);
});

it("loads only the tickers, and leaves the unit, when the file has no amounts", async () => {
  const calls = openUpload({ plotted: [A, B], unit: "usd" });
  chooseFile(`ticker\n${C}\n${D}\n`);
  await screen.findByTestId("use-menu");
  expect(amounts()).toEqual([null, null, "", ""]);
  expect(screen.getByTestId("amount-head").textContent).toBe("Amount ($)");
  fireEvent.click(screen.getByTestId("use-menu"));
  expect(calls.onUseMenu.mock.calls[0][1]).toBeUndefined();
});

it("applies a file that lists the funds already in the menu at once, amounts and unit together", async () => {
  const calls = openUpload({ plotted: [A, B], unit: "usd" });
  chooseFile(`ticker,shares\n${B},5\n${A},10\n`);
  await waitFor(() => expect(calls.onUseMenu).toHaveBeenCalledTimes(1));
  const [rows, unit] = calls.onUseMenu.mock.calls[0] as [Row[], Unit];
  expect(rows.map((r) => [r.id, r.amount])).toEqual([[B, 5], [A, 10]]);
  expect(unit).toBe("shares");
  expect(screen.queryByTestId("use-menu")).toBeNull();
  expect(screen.queryByTestId("upload-report")).toBeNull();
});

it("lists every ticker it did not add, tells the page about them, and keeps the list until dismissed or the next upload", async () => {
  const calls = openUpload({ plotted: [A, B] });
  chooseFile(`ticker,dollars\n${C},1000\nxyz,500\n${D},2000\nABC,1\n`);
  const skipped = await screen.findByTestId("upload-skipped");
  expect(skipped.textContent).toBe("Not added (no data for these yet): XYZ, ABC.");
  expect(calls.onRequestTickers).toHaveBeenCalledTimes(1);
  expect(calls.onRequestTickers).toHaveBeenCalledWith(["XYZ", "ABC"], "csv");
  expect(amounts()).toEqual([null, null, "1000", "2000"]);
  // it stays through other edits
  fireEvent.click(screen.getByLabelText(`Remove ${D}`));
  expect(screen.getByTestId("upload-skipped")).toBeTruthy();
  // dismissed
  fireEvent.click(screen.getByTestId("upload-dismiss"));
  expect(screen.queryByTestId("upload-skipped")).toBeNull();
  expect(screen.queryByTestId("upload-report")).toBeNull();
  // replaced by the next upload's own
  chooseFile(`ticker\n${A}\n${B}\nQQQQ\n`);
  expect((await screen.findByTestId("upload-skipped")).textContent).toBe("Not added (no data for these yet): QQQQ.");
  chooseFile(`ticker\n${A}\n${B}\n`);
  await waitFor(() => expect(screen.queryByTestId("upload-skipped")).toBeNull());
});

it("sends nothing about the tickers when every one of them is served", async () => {
  const calls = openUpload({ plotted: [A, B] });
  chooseFile(`ticker\n${C}\n${D}\n`);
  await screen.findByTestId("use-menu");
  expect(calls.onRequestTickers).not.toHaveBeenCalled();
  expect(screen.queryByTestId("upload-skipped")).toBeNull();
});

it("says which column was ignored when percent does not match dollars", async () => {
  openUpload({ plotted: [A, B] });
  chooseFile(`ticker,dollars,percent\n${C},5000,70\n${D},5000,30\n`);
  const note = await screen.findByTestId("upload-mismatch");
  expect(note.textContent).toBe("Percent didn't match dollars for 2 funds and was ignored.");
  expect(amounts()).toEqual([null, null, "5000", "5000"]);
});

it("refuses a file whose funds with amounts share no column, loads nothing and says who has what", async () => {
  const calls = openUpload({ plotted: [A, B], unit: "usd" });
  chooseFile(`ticker,shares,percent\n${C},10,\n${D},,40\n`);
  const error = await screen.findByTestId("upload-error");
  expect(error.textContent).toBe(`Every fund with an amount needs the same column filled in (shares, dollars or percent). ${C} has only shares; ${D} has only percent.`);
  expect(screen.queryByTestId("use-menu")).toBeNull();
  expect(screen.getByTestId(`fund-row-${A}`)).toBeTruthy();
  expect(screen.queryByTestId(`fund-row-${C}`)).toBeNull();
  expect(screen.getByTestId("amount-head").textContent).toBe("Amount ($)");
  expect(calls.onUseMenu).not.toHaveBeenCalled();
});

it("refuses a file with a bad amount, naming the row and the fund", async () => {
  openUpload();
  chooseFile(`ticker,shares\n${C},10\n${D},lots\n`);
  expect((await screen.findByTestId("upload-error")).textContent).toBe(`Row 3 (${D}): "lots" in the shares column is not a number.`);
  expect(screen.queryByTestId("use-menu")).toBeNull();
});

it("refuses a file with fewer than two served funds, with the usual sentence, and still reports what it skipped", async () => {
  const calls = openUpload();
  chooseFile(`ticker\n${C}\nXYZ\n`);
  expect((await screen.findByTestId("upload-error")).textContent).toBe("A portfolio needs at least 2 funds.");
  expect(screen.getByTestId("upload-skipped").textContent).toBe("Not added (no data for these yet): XYZ.");
  expect(calls.onRequestTickers).toHaveBeenCalledWith(["XYZ"], "csv");
  expect(screen.queryByTestId("use-menu")).toBeNull();
});

it("refuses a file with more served funds than the menu holds, and cuts nothing", async () => {
  const calls = openUpload({ menuMax: 3 });
  chooseFile(`ticker\n${A}\n${B}\n${C}\n${D}\n`);
  expect((await screen.findByTestId("upload-error")).textContent).toBe("A portfolio holds up to 3 funds.");
  expect(screen.queryByTestId(`fund-row-${C}`)).toBeNull();
  expect(calls.onUseMenu).not.toHaveBeenCalled();
});

it("refuses a file that is too big to be a fund list without reading it", async () => {
  openUpload();
  chooseFile(`ticker\n${"A".repeat(1_000_001)}`);
  expect((await screen.findByTestId("upload-error")).textContent).toBe("That file is too big to be a fund list.");
});

it("waits for the list of served funds rather than calling every ticker unknown", async () => {
  const calls = openUpload({ symbols: null });
  chooseFile(`ticker\n${A}\n${B}\n`);
  expect((await screen.findByTestId("upload-error")).textContent).toBe("The list of funds we have is still loading. Try again in a moment.");
  expect(calls.onRequestTickers).not.toHaveBeenCalled();
  expect(screen.queryByTestId("upload-skipped")).toBeNull();
});

it("switches a pending uploaded list's unit without touching the page's menu, and drops it with the draft", async () => {
  const calls = openUpload({ plotted: [A, B], unit: "usd" });
  chooseFile(`ticker,shares\n${C},10\n${D},5\n`);
  await screen.findByTestId("use-menu");
  fireEvent.click(within(screen.getByTestId("unit-toggle")).getByRole("radio", { name: "%" }));
  expect(calls.onUnit).not.toHaveBeenCalled();
  expect(screen.getByTestId("amount-head").textContent).toBe("Share (%)");
  fireEvent.click(screen.getByTestId("funds-clear"));
  fireEvent.click(screen.getByTestId("use-menu"));
  expect(calls.onUseMenu.mock.calls[0][1]).toBe("pct");
  // back to the plotted list: the unit is the page's again
  cleanup();
  const other = openUpload({ plotted: [A, B], unit: "usd" });
  chooseFile(`ticker,shares\n${C},10\n${D},5\n`);
  await screen.findByTestId("use-menu");
  fireEvent.click(screen.getByLabelText(`Remove ${C}`));
  fireEvent.click(screen.getByLabelText(`Remove ${D}`));
  for (const id of [A, B]) {
    fireEvent.change(screen.getByTestId("fund-add"), { target: { value: id } });
    fireEvent.keyDown(screen.getByTestId("fund-add"), { key: "Enter" });
  }
  expect(screen.queryByTestId("use-menu")).toBeNull();
  expect(screen.getByTestId("amount-head").textContent).toBe("Amount ($)");
  expect(other.onUnit).not.toHaveBeenCalled();
});

it("keeps the amounts typed into a pending uploaded list in the draft, never in the menu on screen", async () => {
  // B is in both lists: its plotted amount is in percent, the file's in shares
  const calls = openUpload({ plotted: [A, B], unit: "pct" });
  chooseFile(`ticker,shares\n${B},10\n${C},5\n`);
  await screen.findByTestId("use-menu");
  fireEvent.change(screen.getByLabelText(`${B} amount in shares`), { target: { value: "12" } });
  expect((screen.getByLabelText(`${B} amount in shares`) as HTMLInputElement).value).toBe("12");
  fireEvent.click(screen.getByTestId("funds-clear"));
  expect((screen.getByLabelText(`${B} amount in shares`) as HTMLInputElement).value).toBe("");
  expect(calls.onAmount).not.toHaveBeenCalled();
  // a draft in the page's own unit still applies amounts to the funds on screen as they are typed
  cleanup();
  const own = openUpload({ plotted: [A, B], unit: "pct" });
  chooseFile(`ticker,percent\n${B},60\n${C},40\n`);
  await screen.findByTestId("use-menu");
  fireEvent.change(screen.getByLabelText(`${B} amount in percent`), { target: { value: "55" } });
  expect(own.onAmount).toHaveBeenCalledWith(B, 55);
});

describe("a ticker typed into the picker that nothing matches", () => {
  const typeAndEnter = (text: string) => {
    fireEvent.change(screen.getByTestId("fund-add"), { target: { value: text } });
    fireEvent.keyDown(screen.getByTestId("fund-add"), { key: "Enter" });
  };
  it("is reported once it is committed with Enter, not while it is typed", () => {
    const calls = openUpload();
    fireEvent.change(screen.getByTestId("fund-add"), { target: { value: "z" } });
    fireEvent.change(screen.getByTestId("fund-add"), { target: { value: "zz" } });
    fireEvent.change(screen.getByTestId("fund-add"), { target: { value: "zzqj" } });
    expect(calls.onRequestTickers).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByTestId("fund-add"), { key: "Enter" });
    expect(screen.getByRole("alert").textContent).toBe("ZZQJ isn't offered: no verified current data for it.");
    expect(calls.onRequestTickers).toHaveBeenCalledTimes(1);
    expect(calls.onRequestTickers).toHaveBeenCalledWith(["ZZQJ"], "picker");
  });
  it("is not reported when it does not look like a ticker", () => {
    const calls = openUpload();
    for (const text of ["no such fund", "a very long ticker", "zz$q", "ZZQJ-LONGNAME"]) typeAndEnter(text);
    expect(calls.onRequestTickers).not.toHaveBeenCalled();
  });
  it("is not reported when it matches something served, or is served", () => {
    const calls = openUpload();
    typeAndEnter(A.toLowerCase());
    expect(screen.getByTestId(`fund-row-${A}`)).toBeTruthy();
    // a prefix of several served tickers matches them, so it is not a missing ticker
    typeAndEnter(A.slice(0, 1));
    expect(calls.onRequestTickers).not.toHaveBeenCalled();
  });
  it("is not reported while the list of served funds has not arrived", () => {
    const calls = openUpload({ symbols: null });
    typeAndEnter("zzqj");
    expect(calls.onRequestTickers).not.toHaveBeenCalled();
  });
});

// ── a file with shares and dollars: "Your starting mix" % comes from its dollars ──
const NEW_ONE = { id: "ZZONE", name: "New Fund One" };
const NEW_TWO = { id: "ZZTWO", name: "New Fund Two" };
const withNew = [...catalog, NEW_ONE, NEW_TWO];

it("fills the starting mix % from the file's dollars right after an upload of funds the plotted view has no price for", async () => {
  openUpload({ plotted: [A, B], unit: "usd", symbols: withNew });
  chooseFile(`ticker,shares,dollars\n${NEW_ONE.id},10,1000\n${NEW_TWO.id},5,500\n`);
  await screen.findByTestId("use-menu");
  expect(cell("entered", NEW_ONE.id)).toBe(pct(2 / 3));
  expect(cell("entered", NEW_TWO.id)).toBe(pct(1 / 3));
});

it("uses the file's dollars even for funds the view has a close for", async () => {
  openUpload({ plotted: [C, D], unit: "usd" });
  // 10 shares of A are worth 10 x its close at the latest price; the file says $2,000, and $1,000 for B
  chooseFile(`ticker,shares,dollars\n${A},10,2000\n${B},10,1000\n`);
  await screen.findByTestId("use-menu");
  expect(cell("entered", A)).toBe(pct(2 / 3));
  expect(cell("entered", B)).toBe(pct(1 / 3));
});

it("keeps the current rules, shares at the latest close, when a fund in the file has no dollars", async () => {
  openUpload({ plotted: [C, D], unit: "usd" });
  chooseFile(`ticker,shares,dollars\n${A},10,2000\n${B},10,\n`);
  await screen.findByTestId("use-menu");
  const [a, b] = [(funds[0].last_close as number) * 10, (funds[1].last_close as number) * 10];
  expect(cell("entered", A)).toBe(pct(a / (a + b)));
  expect(cell("entered", B)).toBe(pct(b / (a + b)));
});

it("hands the page each row's price, and follows an edited share count at the same price", async () => {
  const calls = openUpload({ plotted: [A, B], unit: "usd", symbols: withNew });
  chooseFile(`ticker,shares,dollars\n${NEW_ONE.id},10,1000\n${NEW_TWO.id},5,500\n`);
  await screen.findByTestId("use-menu");
  fireEvent.change(screen.getByLabelText(`${NEW_ONE.id} amount in shares`), { target: { value: "30" } });
  // 30 shares at $100 and 5 at $100
  expect(cell("entered", NEW_ONE.id)).toBe(pct(3000 / 3500));
  fireEvent.click(screen.getByTestId("use-menu"));
  const [rows] = calls.onUseMenu.mock.calls[0] as [Row[]];
  expect(rows.map((r) => [r.id, r.amount, r.price])).toEqual([[NEW_ONE.id, 30, 100], [NEW_TWO.id, 5, 100]]);
});

it("leaves the column blank for shares of new funds when the file gave no dollars", async () => {
  openUpload({ plotted: [A, B], unit: "usd", symbols: withNew });
  chooseFile(`ticker,shares\n${NEW_ONE.id},10\n${NEW_TWO.id},5\n`);
  await screen.findByTestId("use-menu");
  expect(cell("entered", NEW_ONE.id)).toBe("");
  expect(cell("entered", NEW_TWO.id)).toBe("");
});

it("fills the column for a plotted fund the service has no close for, from the price its row carries", () => {
  const lagging = parseTensor({ ...structuredClone(raw), universe: { ...raw.universe, funds: raw.universe.funds.map((f: { id: string }) => (f.id === A ? { ...f, last_close: null } : f)) } });
  const rows: Row[] = [{ id: A, name: A, amount: 10, price: 100 }, { id: B, name: B, amount: 10, price: 50 }];
  render(<Funds rows={rows} unit="shares" tensor={lagging} symbols={null} mixStatus="ok" setAside={0} menuError={null} busy={false} menuMax={30} selected={null} onUnit={noop} onAmount={noop} onUseMenu={noop} onNeedSymbols={noop} {...noUpload} />);
  expect(cell("entered", A)).toBe(pct(1000 / 1500));
  expect(cell("entered", B)).toBe(pct(500 / 1500));
});
