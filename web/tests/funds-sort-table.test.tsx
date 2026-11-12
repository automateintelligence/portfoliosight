// @vitest-environment jsdom
// Funds & amounts "Sort by" (spec 3.3, owner direction 2026-11-11): the six options, the order
// holding still while a slider, the chart's point or an amount field is in use and re-sorting once
// when that ends, adding and removing funds, and the remembered choice.
import fs from "node:fs";
import path from "node:path";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseTensor } from "../src/api/client";
import { Funds } from "../src/sections/Funds";
import type { Row, Unit } from "../src/state/store";

const tensor = parseTensor(JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8")));
const universe = tensor.universe.funds;
const noop = () => undefined;
const OPTIONS = ["As entered", "Ticker", "Fund name", "Amount", "Mix entered %", "Selected mix %"];

/** Weights of the selected point in the tensor's fund order, from a few named funds (the rest 0). */
const weights = (given: Record<string, number>) => universe.map((f) => given[f.id] ?? 0);
const make = (id: string, amount: number | null): Row => ({ id, name: universe.find((f) => f.id === id)?.name ?? id, amount });
/** The list as entered: VTI, BND, AGG, VNQ. In dollars: BND 300, VNQ 200, VTI 100, AGG blank. */
const entered = (): Row[] => [make("VTI", 100), make("BND", 300), make("AGG", null), make("VNQ", 200)];
const symbols = [...universe.map((f) => ({ id: f.id, name: f.name ?? f.id })), { id: "ZZNEW", name: "A New Fund" }];

type HarnessProps = { initial?: Row[]; unit?: Unit; selected?: number[]; interacting?: boolean };
/** Keeps the rows as the page does: amounts typed into a field come back as new rows. */
function Harness({ initial = entered(), unit = "usd", selected = weights({ VTI: 0.1, BND: 0.2, AGG: 0.3, VNQ: 0.4 }), interacting }: HarnessProps) {
  const [rows, setRows] = useState(initial);
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
      menuMax={30}
      selected={selected}
      upload={null}
      interacting={interacting}
      onUnit={noop}
      onAmount={(id, amount) => setRows((rs) => rs.map((r) => (r.id === id ? { ...r, amount } : r)))}
      onUseMenu={(next) => setRows(next)}
      onNeedSymbols={noop}
      onUpload={noop}
      onDismissUpload={noop}
      onRequestTickers={noop}
    />
  );
}

const shown = (props: HarnessProps = {}) => render(<Harness {...props} />);
const order = () => screen.getAllByRole("listitem").map((el) => el.getAttribute("data-testid")!.replace("fund-row-", ""));
const select = () => screen.getByLabelText("Sort by") as HTMLSelectElement;
const optionFor = (label: string) => Array.from(select().options).find((o) => o.textContent === label)!.value;
const choose = (label: string) => fireEvent.change(select(), { target: { value: optionFor(label) } });
const amountField = (id: string, unit = "dollars") => screen.getByLabelText(`${id} amount in ${unit}`) as HTMLInputElement;
const selectedCell = (id: string) => screen.getByTestId(`mix-selected-${id}`).textContent;
const enteredCell = (id: string) => screen.getByTestId(`mix-entered-${id}`).textContent;

beforeEach(() => localStorage.clear());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("the Sort by control", () => {
  it("is a labelled drop-down of the six options, starting on As entered", () => {
    shown();
    expect(select().tagName).toBe("SELECT");
    expect(Array.from(select().options).map((o) => o.textContent)).toEqual(OPTIONS);
    expect(select().selectedOptions[0].textContent).toBe("As entered");
    expect(order()).toEqual(["VTI", "BND", "AGG", "VNQ"]);
  });

  it("sorts by each option: names A to Z, numbers largest first, blanks last", () => {
    shown();
    const wanted: Record<string, string[]> = {
      "As entered": ["VTI", "BND", "AGG", "VNQ"],
      Ticker: ["AGG", "BND", "VNQ", "VTI"],
      "Fund name": ["AGG", "VNQ", "BND", "VTI"],
      Amount: ["BND", "VNQ", "VTI", "AGG"],
      "Mix entered %": ["BND", "VNQ", "VTI", "AGG"],
      "Selected mix %": ["VNQ", "AGG", "BND", "VTI"],
    };
    for (const label of OPTIONS) {
      choose(label);
      expect(order(), label).toEqual(wanted[label]);
    }
  });

  it("sorts Amount by the number in the column, in the unit shown, not by what it is worth", () => {
    // 5 shares of VTI ($810) against 20 shares of BND ($680): in shares the 20 is larger
    shown({ unit: "shares", initial: [make("VTI", 5), make("BND", 20)] });
    choose("Amount");
    expect(order()).toEqual(["BND", "VTI"]);
    choose("Mix entered %");
    expect(order()).toEqual(["VTI", "BND"]);
  });

  it("keeps the entered order for funds that tie", () => {
    shown({ initial: [make("VTI", 50), make("BND", 50), make("AGG", 50)], selected: weights({}) });
    for (const label of ["Amount", "Mix entered %", "Selected mix %"]) {
      choose(label);
      expect(order(), label).toEqual(["VTI", "BND", "AGG"]);
    }
  });
});

describe("while a slider or the chart's point is in use", () => {
  const later = weights({ VTI: 0.7, BND: 0.1, AGG: 0.1, VNQ: 0.1 });

  it("holds the order, keeps the selected mix numbers moving, and re-sorts once when it ends", () => {
    const { rerender } = shown();
    choose("Selected mix %");
    expect(order()).toEqual(["VNQ", "AGG", "BND", "VTI"]);
    // the interaction begins with the first change to the point
    rerender(<Harness interacting selected={later} />);
    expect(order()).toEqual(["VNQ", "AGG", "BND", "VTI"]);
    expect(selectedCell("VTI")).toBe("70.0%");
    expect(selectedCell("VNQ")).toBe("10.0%");
    const further = weights({ VTI: 0.2, BND: 0.5, AGG: 0.2, VNQ: 0.1 });
    rerender(<Harness interacting selected={further} />);
    expect(order()).toEqual(["VNQ", "AGG", "BND", "VTI"]);
    expect(selectedCell("BND")).toBe("50.0%");
    // released: one re-sort, on the numbers as they stand
    rerender(<Harness selected={further} />);
    expect(order()).toEqual(["BND", "VTI", "AGG", "VNQ"]);
  });

  it("re-sorts at once when nothing is in use", () => {
    const { rerender } = shown();
    choose("Selected mix %");
    rerender(<Harness selected={later} />);
    expect(order()).toEqual(["VTI", "BND", "AGG", "VNQ"]);
  });

  it("holds the other options too, whatever they are sorted on", () => {
    const { rerender } = shown();
    choose("Mix entered %");
    expect(order()).toEqual(["BND", "VNQ", "VTI", "AGG"]);
    rerender(<Harness interacting initial={entered()} selected={later} />);
    expect(order()).toEqual(["BND", "VNQ", "VTI", "AGG"]);
  });

  it("puts a changed sort in order at once even in the middle of one", () => {
    const { rerender } = shown();
    rerender(<Harness interacting selected={later} />);
    choose("Ticker");
    expect(order()).toEqual(["AGG", "BND", "VNQ", "VTI"]);
  });

  it("sorts a fund added in the middle of one into its place at once", () => {
    const { rerender } = shown();
    choose("Fund name");
    rerender(<Harness interacting selected={later} />);
    fireEvent.change(screen.getByTestId("fund-add"), { target: { value: "ZZNEW" } });
    fireEvent.keyDown(screen.getByTestId("fund-add"), { key: "Enter" });
    // "A New Fund" comes before every other name
    expect(order()).toEqual(["ZZNEW", "AGG", "VNQ", "BND", "VTI"]);
  });

  it("sorts what is left into place at once when a fund is removed in the middle of one", () => {
    const { rerender } = shown();
    choose("Selected mix %");
    rerender(<Harness interacting selected={later} />);
    expect(order()).toEqual(["VNQ", "AGG", "BND", "VTI"]);
    fireEvent.click(screen.getByLabelText("Remove AGG"));
    // VTI is now largest; BND and VNQ tie and keep their entered order
    expect(order()).toEqual(["VTI", "BND", "VNQ"]);
  });
});

describe("while an amount field has focus", () => {
  it("holds the order as the amount is typed, and re-sorts when the field loses focus", () => {
    shown();
    choose("Amount");
    expect(order()).toEqual(["BND", "VNQ", "VTI", "AGG"]);
    const field = amountField("VTI");
    act(() => field.focus());
    fireEvent.change(field, { target: { value: "900" } });
    // VTI is now the largest, and still sits where it was under the cursor; its numbers are live
    expect(order()).toEqual(["BND", "VNQ", "VTI", "AGG"]);
    expect(enteredCell("VTI")).toBe("64.3%");
    fireEvent.change(field, { target: { value: "9000" } });
    expect(order()).toEqual(["BND", "VNQ", "VTI", "AGG"]);
    act(() => field.blur());
    expect(order()).toEqual(["VTI", "BND", "VNQ", "AGG"]);
  });

  it("keeps holding while focus moves from one amount field to another, and re-sorts when it leaves them", () => {
    shown();
    choose("Amount");
    const first = amountField("VTI");
    const second = amountField("AGG");
    act(() => first.focus());
    fireEvent.change(first, { target: { value: "900" } });
    // a browser sends the blur and the focus as two events, with a render after each
    fireEvent.blur(first, { relatedTarget: second });
    expect(order(), "between the blur and the focus").toEqual(["BND", "VNQ", "VTI", "AGG"]);
    fireEvent.focus(second);
    expect(order()).toEqual(["BND", "VNQ", "VTI", "AGG"]);
    fireEvent.change(second, { target: { value: "1000" } });
    expect(order()).toEqual(["BND", "VNQ", "VTI", "AGG"]);
    fireEvent.blur(second, { relatedTarget: document.body });
    expect(order()).toEqual(["AGG", "VTI", "BND", "VNQ"]);
  });

  it("re-sorts at once for an amount that changes while no field has focus", () => {
    shown();
    choose("Amount");
    fireEvent.change(amountField("AGG"), { target: { value: "5000" } });
    expect(order()).toEqual(["AGG", "BND", "VNQ", "VTI"]);
  });

  it("holds while either a slider or a field is in use, and re-sorts only when both are done", () => {
    const { rerender } = shown();
    choose("Selected mix %");
    const field = amountField("VTI");
    act(() => field.focus());
    const later = weights({ VTI: 0.7, BND: 0.1, AGG: 0.1, VNQ: 0.1 });
    rerender(<Harness interacting selected={later} />);
    rerender(<Harness selected={later} />);
    expect(order(), "the interaction ended but the field still has focus").toEqual(["VNQ", "AGG", "BND", "VTI"]);
    act(() => field.blur());
    expect(order()).toEqual(["VTI", "BND", "AGG", "VNQ"]);
  });
});

describe("while focus is inside the rows", () => {
  it("keeps holding as Tab goes from an amount field to the row's Remove button and on to the next amount field, and re-sorts when focus leaves the rows", () => {
    shown();
    choose("Amount");
    expect(order()).toEqual(["BND", "VNQ", "VTI", "AGG"]);
    const field = amountField("VTI");
    act(() => field.focus());
    fireEvent.change(field, { target: { value: "900" } });
    // the browser's Tab order: the field, its row's Remove button, the next row's field
    act(() => screen.getByLabelText("Remove VTI").focus());
    expect(order(), "on the Remove button").toEqual(["BND", "VNQ", "VTI", "AGG"]);
    act(() => amountField("AGG").focus());
    expect(order(), "on the next amount field").toEqual(["BND", "VNQ", "VTI", "AGG"]);
    act(() => select().focus());
    expect(order()).toEqual(["VTI", "BND", "VNQ", "AGG"]);
  });

  it("stops holding when the row with the focused field leaves the list", () => {
    const table = (rows: Row[]) => (
      <Funds
        rows={rows}
        unit="usd"
        tensor={tensor}
        symbols={symbols as never}
        mixStatus="ok"
        setAside={0}
        menuError={null}
        busy={false}
        menuMax={30}
        selected={null}
        upload={null}
        onUnit={noop}
        onAmount={noop}
        onUseMenu={noop}
        onNeedSymbols={noop}
        onUpload={noop}
        onDismissUpload={noop}
        onRequestTickers={noop}
      />
    );
    const { rerender } = render(table(entered()));
    choose("Amount");
    act(() => amountField("VTI").focus());
    // VTI leaves the list (another tab's change, a preset): its field goes with it and focus with the field
    rerender(table([make("BND", 300), make("AGG", null), make("VNQ", 200)]));
    expect(document.activeElement).toBe(document.body);
    expect(order()).toEqual(["BND", "VNQ", "AGG"]);
    rerender(table([make("BND", 300), make("AGG", 5000), make("VNQ", 200)]));
    expect(order()).toEqual(["AGG", "BND", "VNQ"]);
  });
});

describe("the remembered choice", () => {
  it("comes back on the next visit", () => {
    shown();
    choose("Ticker");
    cleanup();
    shown();
    expect(select().selectedOptions[0].textContent).toBe("Ticker");
    expect(order()).toEqual(["AGG", "BND", "VNQ", "VTI"]);
  });

  it("starts on As entered when what is stored is not one of the options", () => {
    localStorage.setItem("ps.fundsSort", "price");
    shown();
    expect(select().selectedOptions[0].textContent).toBe("As entered");
  });

  it("starts on As entered, and still sorts, when storage throws on every read and write", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    shown();
    expect(select().selectedOptions[0].textContent).toBe("As entered");
    expect(() => choose("Amount")).not.toThrow();
    expect(select().selectedOptions[0].textContent).toBe("Amount");
    expect(order()).toEqual(["BND", "VNQ", "VTI", "AGG"]);
  });
});
