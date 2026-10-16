// @vitest-environment jsdom
// The pinned card in the chart: a click on the selected point pins it, a drag does not, a press
// outside the chart and the sliders or Escape lets it go, and while pinned it follows every move
// of the sliders and of the point.
import fs from "node:fs";
import path from "node:path";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseTensor } from "../src/api/client";
import { Chart } from "../src/chart/Chart";
import { makeScales, paddedExtent } from "../src/chart/scales";
import { pct } from "../src/format";
import { portfolioMath } from "../src/math/portfolio";
import { deriveView, type View } from "../src/math/view";

const RAW = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8"));
const tensor = parseTensor(RAW);
const math = portfolioMath(tensor);
const pts = tensor.frontier_curve.sigma.map((sigma, i) => ({ sigma, mu: tensor.frontier_curve.mu[i] }));
const scales = makeScales(1040, 560, paddedExtent(pts, { dx: 0.002, dy: 0.002 }), false);
const domain = math.riskSliderDomain();
const at = (fs: number, t: number): View => deriveView(tensor, math, domain.s_safe + fs * (domain.s_max - domain.s_safe), t);

afterEach(cleanup);

function chart(view: View, onRiskPixel = vi.fn(), onDivDrag = vi.fn()) {
  const props = {
    tensor,
    scales,
    ghosts: [],
    frontierEnb: [],
    current: null,
    details: false,
    phone: false,
    themeEpoch: 0,
    reveal: false,
    notice: null,
    busy: false,
    cellMix: () => null,
    onRiskPixel,
    onDivDrag,
    onNudge: vi.fn(),
  };
  const r = render(
    <div>
      <Chart {...props} view={view} />
      <div data-keeps-pin="" data-testid="a-slider" />
      <p data-testid="elsewhere">elsewhere</p>
    </div>,
  );
  return { ...r, update: (next: View, details = false) => r.rerender(
    <div>
      <Chart {...props} view={next} details={details} />
      <div data-keeps-pin="" data-testid="a-slider" />
      <p data-testid="elsewhere">elsewhere</p>
    </div>,
  ) };
}

const point = () => screen.getByTestId("point-selected");
const pinnedCard = () => screen.queryByTestId("mix-card-pinned");
const press = (x: number, y: number) => fireEvent.pointerDown(point(), { clientX: x, clientY: y, pointerType: "mouse", button: 0, pointerId: 1 });
const move = (x: number, y: number) => fireEvent.pointerMove(point(), { clientX: x, clientY: y, pointerType: "mouse", buttons: 1, pointerId: 1 });
const release = () => fireEvent.pointerUp(point(), { pointerType: "mouse", pointerId: 1 });
const click = () => {
  press(200, 200);
  release();
};

describe("the pinned card", () => {
  it("a click pins it, a second click unpins it", () => {
    chart(at(0.5, 0.3));
    expect(pinnedCard()).toBeNull();
    click();
    expect(pinnedCard()).not.toBeNull();
    expect(point().getAttribute("aria-describedby")).toBe("mix-card-pinned");
    expect(pinnedCard()!.querySelector('[data-testid="mix-card"]')!.getAttribute("data-for")).toBe("selected");
    click();
    expect(pinnedCard()).toBeNull();
  });

  it("a drag of the point moves the risk and leaves the pin as it was", () => {
    const onRiskPixel = vi.fn();
    chart(at(0.5, 0.3), onRiskPixel);
    press(200, 200);
    move(230, 201);
    move(260, 202);
    release();
    expect(onRiskPixel).toHaveBeenCalled();
    expect(pinnedCard()).toBeNull();
    // a press that wobbles less than the slop is still a click
    press(200, 200);
    move(203, 202);
    release();
    expect(pinnedCard()).not.toBeNull();
    click();
    expect(pinnedCard()).toBeNull();
    click();
    press(200, 200);
    move(200, 240);
    release();
    expect(pinnedCard()).not.toBeNull();
  });

  it("a press outside the chart and the sliders unpins; one on a slider or the chart does not", () => {
    chart(at(0.5, 0.3));
    click();
    fireEvent.pointerDown(screen.getByTestId("a-slider"));
    fireEvent.pointerDown(screen.getByTestId("chart"));
    expect(pinnedCard()).not.toBeNull();
    fireEvent.pointerDown(screen.getByTestId("elsewhere"));
    expect(pinnedCard()).toBeNull();
  });

  it("Escape unpins, and Enter or Space on the point toggles it", () => {
    chart(at(0.5, 0.3));
    fireEvent.keyDown(point(), { key: "Enter" });
    expect(pinnedCard()).not.toBeNull();
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(pinnedCard()).toBeNull();
    fireEvent.keyDown(point(), { key: " " });
    expect(pinnedCard()).not.toBeNull();
    fireEvent.keyDown(point(), { key: " " });
    expect(pinnedCard()).toBeNull();
  });

  it("follows the sliders and the point: risk, return, range, word and holdings, and the details lines", () => {
    const first = at(0.2, 0.1);
    const { update } = chart(first);
    click();
    const text = () => pinnedCard()!.textContent ?? "";
    const before = text();
    expect(before).toContain(pct(first.selected.sigma));
    expect(before).toContain(pct(first.selected.mu));
    for (const [fs, t] of [[0.8, 0.1], [0.8, 0.9], [0.4, 0.5]] as const) {
      const v = at(fs, t);
      update(v);
      const now = text();
      expect(now).toContain(pct(v.selected.sigma));
      expect(now).toContain(pct(v.selected.mu));
      expect(now).toContain(v.word);
      expect(pinnedCard()).not.toBeNull();
    }
    expect(text()).not.toBe(before);
    update(at(0.4, 0.5), true);
    expect(text()).toContain("independent bets");
  });
});
