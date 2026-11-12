// @vitest-environment jsdom
// Owner direction 2026-11-11: the page never names an "Optimized" mix and never grades diversification
// with a word. Each mix states the neutral figure instead, and the one line from our tests on past data
// appears once, in the details.
import fs from "node:fs";
import path from "node:path";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseTensor } from "../src/api/client";
import { Chart } from "../src/chart/Chart";
import { makeScales, paddedExtent } from "../src/chart/scales";
import { DivSlider } from "../src/controls/DivSlider";
import { ResultStrip, type DetailFacts } from "../src/controls/ResultStrip";
import { portfolioMath } from "../src/math/portfolio";
import { stripScale } from "../src/math/stripScale";
import { deriveView, type View } from "../src/math/view";

const TENSOR = parseTensor(JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8")));
const math = portfolioMath(TENSOR);
const domain = math.riskSliderDomain();
const pts = TENSOR.frontier_curve.sigma.map((sigma, i) => ({ sigma, mu: TENSOR.frontier_curve.mu[i] }));
const scales = makeScales(1040, 560, paddedExtent(pts, { dx: 0.002, dy: 0.002 }), false);
const at = (fs: number, t: number): View => deriveView(TENSOR, math, domain.s_safe + fs * (domain.s_max - domain.s_safe), t);

const PAST_DATA_LINE = "In our tests on past data, mixes with risk spread more evenly did not lose less than the best-return mix at the same risk.";
const line = (enb: number, ref = TENSOR.enb_ref) => `This mix spreads risk over the equivalent of ${enb.toFixed(1)} independent bets; highest found on this portfolio: ${ref.toFixed(1)}.`;
/** The four grade words that used to stand for the diversification measure. */
const GRADE_WORDS = /\b(Good|Average|Fair|Poor)\b/;
/** "Good" is also the label of the one-year range's top figure, so it is looked for only where diversification is read. */
const OTHER_GRADE_WORDS = /\b(Average|Fair|Poor)\b/;

/** Everything a visitor reads or hears from a container: its text and its accessible names. */
function visible(root: HTMLElement): string {
  const names = Array.from(root.querySelectorAll("[aria-label], [aria-valuetext], [title]")).flatMap((el) => [el.getAttribute("aria-label"), el.getAttribute("aria-valuetext"), el.getAttribute("title")]);
  return [root.textContent ?? "", ...names].filter(Boolean).join("\n");
}

afterEach(cleanup);

const facts: DetailFacts = { enb: 3.84, enbRef: 5.1, mu: 0.06, sigma: 0.1, lookbackStart: "2020-10-01", lookbackEnd: "2025-10-01", rows: 1250, asof: "2026-10-12", notes: [] };
function strip(details: boolean) {
  return render(
    <ResultStrip
      low={-0.108}
      typical={0.062}
      high={0.224}
      normal={{ low: -0.1, mid: 0.06, high: 0.22 }}
      scale={stripScale({ min: -0.2, max: 0.35 })}
      value={null}
      details={details}
      facts={facts}
      staleAsof={null}
      onToggleDetails={() => undefined}
    />,
  );
}

function chart(view: View, details = false) {
  const w = TENSOR.frontier.w[10];
  const own = math.stats(w);
  return render(
    <Chart
      tensor={TENSOR}
      view={view}
      scales={scales}
      ghosts={[]}
      frontierEnb={[]}
      current={{ stats: own, range: { low: -0.1, typical: 0.05, high: 0.2 }, weights: w }}
      details={details}
      phone={false}
      themeEpoch={0}
      reveal={false}
      notice={null}
      busy={false}
      cellMix={() => null}
      onRiskPixel={vi.fn()}
      onDivDrag={vi.fn()}
      onNudge={vi.fn()}
    />,
  );
}

describe("the app opens on the best-return mix", () => {
  it("at position 0 the selected mix is the frontier mix at every risk setting", () => {
    for (const f of [0, 0.25, 0.5, 0.75, 1]) {
      const v = at(f, 0);
      expect(v.t).toBe(0);
      expect(v.moved).toBe(false);
      expect(v.selected).toEqual(v.front);
      expect(v.range).toEqual(v.frontRange);
    }
  });

  it("a position other than 0 counts as moved", () => {
    expect(at(0.5, 0.4).moved).toBe(true);
    expect(at(0.5, 1).moved).toBe(true);
  });
});

describe("the chart", () => {
  it("draws the selected mix and the starting mix and no third marker", () => {
    const { container } = chart(at(0.5, 0));
    expect(screen.queryByTestId("point-div")).toBeNull();
    expect(Array.from(container.querySelectorAll("[data-mark]")).map((el) => el.getAttribute("data-mark")).sort()).toEqual(["current", "selected"]);
  });

  it("never says Optimized and grades nothing in its legend", () => {
    const { container } = chart(at(0.5, 0), true);
    const text = visible(container);
    expect(text).not.toMatch(/optimi[sz]ed/i);
    expect(text).not.toMatch(OTHER_GRADE_WORDS);
    const legend = screen.getByTestId("chart-legend");
    expect(legend.textContent).toContain("How spread out the risk is");
    expect(legend.textContent).toContain("Fewer independent bets");
    expect(legend.textContent).toContain("More independent bets");
    expect(legend.textContent).not.toMatch(/\bLess\b/);
    expect(legend.querySelectorAll("li")).toHaveLength(3); // the frontier line, the selected mix and the starting mix: no key for a third marker
  });

  it("the starting mix is spoken with the neutral figure, not a grade", () => {
    const v = at(0.5, 0);
    const w = TENSOR.frontier.w[10];
    const { container } = chart(v);
    const label = container.querySelector('[data-mark="current"]')!.getAttribute("aria-label")!;
    expect(label).toContain(`Diversification: ${line(math.stats(w).enb)}`);
    expect(label.split("Diversification:")[1]).not.toMatch(GRADE_WORDS);
    expect(label).not.toMatch(OTHER_GRADE_WORDS);
  });

  it("the starting mix's card shows the neutral figure in its Diversification row", () => {
    chart(at(0.5, 0));
    act(() => {
      fireEvent.focus(document.querySelector('[data-mark="current"]')!);
    });
    const card = screen.getByTestId("mix-card");
    expect(card.getAttribute("data-for")).toBe("current");
    expect(screen.getByTestId("mix-card-word").textContent).toBe(line(math.stats(TENSOR.frontier.w[10]).enb));
    expect(card.textContent).not.toMatch(OTHER_GRADE_WORDS);
    expect(screen.getByTestId("mix-card-word").textContent).not.toMatch(GRADE_WORDS);
  });

  it("the pinned card shows the selected mix's own figure and follows it", () => {
    const first = at(0.2, 0);
    const { rerender, container } = chart(first);
    const point = () => screen.getByTestId("point-selected");
    fireEvent.pointerDown(point(), { clientX: 200, clientY: 200, pointerType: "mouse", button: 0, pointerId: 1 });
    fireEvent.pointerUp(point(), { pointerType: "mouse", pointerId: 1 });
    const pinned = () => screen.getByTestId("mix-card-pinned").querySelector('[data-testid="mix-card-word"]')!.textContent;
    expect(pinned()).toBe(line(first.selected.enb));
    expect(visible(container)).not.toMatch(/optimi[sz]ed/i);
    expect(screen.getByTestId("mix-card-pinned").textContent).not.toMatch(OTHER_GRADE_WORDS);
    const next = at(0.8, 0.6);
    rerender(
      <Chart
        tensor={TENSOR}
        view={next}
        scales={scales}
        ghosts={[]}
        frontierEnb={[]}
        current={null}
        details={false}
        phone={false}
        themeEpoch={0}
        reveal={false}
        notice={null}
        busy={false}
        cellMix={() => null}
        onRiskPixel={vi.fn()}
        onDivDrag={vi.fn()}
        onNudge={vi.fn()}
      />,
    );
    expect(pinned()).toBe(line(next.selected.enb));
  });
});

describe("the strip", () => {
  it("states the neutral figure where the grade word was, in the quiet label", () => {
    strip(false);
    expect(screen.getByTestId("div-word").textContent).toBe(line(facts.enb, facts.enbRef));
    expect(screen.getByTestId("div-word").textContent).not.toMatch(GRADE_WORDS);
    expect(screen.getByRole("region", { name: "Selected mix" }).textContent).not.toMatch(OTHER_GRADE_WORDS);
  });

  it("keeps the past-data line out of the default view and shows it once behind details", () => {
    const off = strip(false);
    expect(visible(off.container)).not.toContain(PAST_DATA_LINE);
    cleanup();
    const on = strip(true);
    const text = visible(on.container);
    expect(text.split(PAST_DATA_LINE)).toHaveLength(2);
    expect(on.container.textContent!.split(PAST_DATA_LINE)).toHaveLength(2);
  });

  it("explains neither a grade word nor Optimized in the details, and the method line does not mention it", () => {
    const { container } = strip(true);
    const text = visible(container);
    expect(text).not.toMatch(/optimi[sz]ed/i);
    expect(text).not.toMatch(OTHER_GRADE_WORDS);
    expect(text).not.toMatch(/diversification word/i);
    expect(screen.queryByTestId("details-words")).toBeNull();
    expect(screen.queryByTestId("details-suggested")).toBeNull();
    expect(screen.getByTestId("details-method").textContent).not.toMatch(/balanced point|knee/i);
    // the measure's technical name stays behind details
    expect(screen.getByTestId("details-enb").textContent).toContain("effective number of bets, minimum torsion");
  });
});

describe("the diversification slider", () => {
  const slider = (t: number, moved: boolean, horizontal = false, onChange = vi.fn()) =>
    render(<DivSlider t={t} moved={moved} disabled={false} horizontal={horizontal} details={false} onChange={onChange} />);

  it("reads Best-return mix at position 0", () => {
    const { container } = slider(0, false);
    expect(screen.getByRole("slider").getAttribute("aria-valuetext")).toBe("Best-return mix");
    expect(screen.queryByTestId("div-reset")).toBeNull();
    expect(visible(container)).not.toMatch(/optimi[sz]ed/i);
    expect(screen.getByText("More return")).toBeTruthy();
    expect(screen.getByText("More diversified")).toBeTruthy();
  });

  it("once moved reads the distance, and offers no button of any kind to go back (owner direction 2026-11-11)", () => {
    for (const horizontal of [false, true]) {
      const { container } = slider(0.4, true, horizontal);
      expect(screen.getByRole("slider").getAttribute("aria-valuetext")).toBe("40 of 100 toward more diversified");
      expect(screen.queryByTestId("div-reset")).toBeNull();
      expect(container.querySelectorAll("button")).toHaveLength(0);
      expect(visible(container)).not.toMatch(/optimi[sz]ed|back to/i);
      cleanup();
    }
  });

  it("is brought back to position 0 by the keyboard: End on the vertical slider, Home on the horizontal one", () => {
    const vertical = vi.fn();
    slider(0.4, true, false, vertical);
    fireEvent.keyDown(screen.getByRole("slider"), { key: "End" });
    expect(vertical).toHaveBeenLastCalledWith(0);
    cleanup();
    const horizontal = vi.fn();
    slider(0.4, true, true, horizontal);
    fireEvent.keyDown(screen.getByRole("slider"), { key: "Home" });
    expect(horizontal).toHaveBeenLastCalledWith(0);
  });
});
