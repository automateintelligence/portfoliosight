// @vitest-environment jsdom
// Every control that moves the selected mix tells the app while it is being moved (owner direction
// 2026-11-11): a drag of the risk slider, the diversification slider, the chart's point or the
// starting-mix square, and a key held on any of them. A drag ends on pointerup, pointercancel or
// lost capture; a key on its release, so a held arrow is one interaction and a single press is one.
import fs from "node:fs";
import path from "node:path";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseTensor } from "../src/api/client";
import { Chart } from "../src/chart/Chart";
import { makeScales, paddedExtent } from "../src/chart/scales";
import { DivSlider } from "../src/controls/DivSlider";
import { RiskSlider } from "../src/controls/RiskSlider";
import { portfolioMath } from "../src/math/portfolio";
import { deriveView } from "../src/math/view";
import { createInteraction, InteractionContext, type Interaction } from "../src/state/interaction";

afterEach(cleanup);

const provided = (signal: Interaction, children: ReactNode) => <InteractionContext.Provider value={signal}>{children}</InteractionContext.Provider>;
const mouse = { pointerType: "mouse", button: 0, buttons: 1, pointerId: 1 };

describe("risk slider", () => {
  const slider = (signal: Interaction, onChange = vi.fn()) => {
    render(provided(signal, <RiskSlider s={0.5} domain={{ s_safe: 0, s_max: 1 }} xOf={(s) => s * 100} sOf={(px) => px / 100} width={100} low={-0.1} typical={0.05} details={false} phone={false} stem={20} onChange={onChange} />));
    return { el: screen.getByTestId("risk-slider"), onChange };
  };

  it("is in progress from the press until pointerup", () => {
    const signal = createInteraction();
    const { el, onChange } = slider(signal);
    expect(signal.active()).toBe(false);
    fireEvent.pointerDown(el, { ...mouse, clientX: 40, clientY: 5 });
    expect(onChange).toHaveBeenCalled();
    expect(signal.active()).toBe(true);
    fireEvent.pointerMove(el, { ...mouse, clientX: 60, clientY: 5 });
    expect(signal.active()).toBe(true);
    fireEvent.pointerUp(el, { ...mouse });
    expect(signal.active()).toBe(false);
  });

  it("ends on pointercancel and on lost capture", () => {
    const signal = createInteraction();
    const { el } = slider(signal);
    for (const end of [fireEvent.pointerCancel, fireEvent.lostPointerCapture]) {
      fireEvent.pointerDown(el, { ...mouse, clientX: 40, clientY: 5 });
      expect(signal.active()).toBe(true);
      end(el, { ...mouse });
      expect(signal.active()).toBe(false);
    }
  });

  it("does not start for a disabled slider or a right-hand mouse button", () => {
    const signal = createInteraction();
    const { el } = slider(signal);
    fireEvent.pointerDown(el, { ...mouse, button: 2, clientX: 40, clientY: 5 });
    expect(signal.active()).toBe(false);
    cleanup();
    render(provided(signal, <RiskSlider s={0.5} domain={{ s_safe: 0, s_max: 1 }} xOf={(s) => s * 100} sOf={(px) => px / 100} width={100} low={0} typical={0} details={false} phone={false} stem={20} busy onChange={vi.fn()} />));
    fireEvent.pointerDown(screen.getByTestId("risk-slider"), { ...mouse, clientX: 40, clientY: 5 });
    expect(signal.active()).toBe(false);
  });

  it("is in progress from the first arrow key down, through its repeats, until the key is released", () => {
    const signal = createInteraction();
    const { el, onChange } = slider(signal);
    fireEvent.keyDown(el, { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(signal.active()).toBe(true);
    fireEvent.keyDown(el, { key: "ArrowRight", repeat: true });
    fireEvent.keyDown(el, { key: "ArrowRight", repeat: true });
    expect(onChange).toHaveBeenCalledTimes(3);
    expect(signal.active()).toBe(true);
    fireEvent.keyUp(el, { key: "ArrowRight" });
    expect(signal.active()).toBe(false);
  });

  it("is one interaction for a single key press too, and a key the slider ignores starts none", () => {
    const signal = createInteraction();
    const { el } = slider(signal);
    fireEvent.keyDown(el, { key: "PageUp" });
    expect(signal.active()).toBe(true);
    fireEvent.keyUp(el, { key: "PageUp" });
    expect(signal.active()).toBe(false);
    fireEvent.keyDown(el, { key: "a" });
    expect(signal.active()).toBe(false);
  });

  it("ends when the slider leaves the page mid-drag", () => {
    const signal = createInteraction();
    const { el } = slider(signal);
    fireEvent.pointerDown(el, { ...mouse, clientX: 40, clientY: 5 });
    expect(signal.active()).toBe(true);
    cleanup();
    expect(signal.active()).toBe(false);
  });
});

describe("diversification slider", () => {
  for (const horizontal of [false, true]) {
    describe(horizontal ? "horizontal (phone)" : "vertical", () => {
      const slider = (signal: Interaction) => {
        const onChange = vi.fn();
        render(provided(signal, <DivSlider t={0.5} moved={false} disabled={false} horizontal={horizontal} details={false} onChange={onChange} onReset={vi.fn()} />));
        return { el: screen.getByTestId("div-slider"), onChange };
      };

      it("is in progress from the press until pointerup, pointercancel or lost capture", () => {
        const signal = createInteraction();
        const { el, onChange } = slider(signal);
        for (const end of [fireEvent.pointerUp, fireEvent.pointerCancel, fireEvent.lostPointerCapture]) {
          fireEvent.pointerDown(el, { ...mouse, clientX: 5, clientY: 5 });
          expect(onChange).toHaveBeenCalled();
          expect(signal.active()).toBe(true);
          end(el, { ...mouse });
          expect(signal.active()).toBe(false);
        }
      });

      it("is in progress while an arrow key is held, and ends on its release", () => {
        const signal = createInteraction();
        const { el } = slider(signal);
        fireEvent.keyDown(el, { key: "ArrowDown" });
        fireEvent.keyDown(el, { key: "ArrowDown", repeat: true });
        expect(signal.active()).toBe(true);
        fireEvent.keyUp(el, { key: "ArrowDown" });
        expect(signal.active()).toBe(false);
        fireEvent.keyDown(el, { key: "Tab" });
        expect(signal.active()).toBe(false);
      });
    });
  }
});

describe("the chart's selected point and starting-mix square", () => {
  const tensor = parseTensor(JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8")));
  const math = portfolioMath(tensor);
  const pts = tensor.frontier_curve.sigma.map((sigma, i) => ({ sigma, mu: tensor.frontier_curve.mu[i] }));
  const scales = makeScales(1040, 560, paddedExtent(pts, { dx: 0.002, dy: 0.002 }), false);
  const domain = math.riskSliderDomain();
  const view = deriveView(tensor, math, domain.s_safe + 0.5 * (domain.s_max - domain.s_safe), 0.3);
  const shown = (signal: Interaction, onNudge = vi.fn()) => {
    render(
      provided(
        signal,
        <Chart tensor={tensor} view={view} scales={scales} ghosts={[]} frontierEnb={[]} current={{ stats: view.selected, range: null, weights: view.weights }} details={false} phone={false} themeEpoch={0} reveal={false} notice={null} busy={false} cellMix={() => null} onRiskPixel={vi.fn()} onDivDrag={vi.fn()} onNudge={onNudge} />,
      ),
    );
    return { point: screen.getByTestId("point-selected"), square: document.querySelector<SVGGElement>('[data-mark="current"]')!, onNudge };
  };

  it("is in progress while the point is dragged, and ends on pointerup, pointercancel or lost capture", () => {
    const signal = createInteraction();
    const { point } = shown(signal);
    for (const end of [fireEvent.pointerUp, fireEvent.pointerCancel, fireEvent.lostPointerCapture]) {
      fireEvent.pointerDown(point, { ...mouse, clientX: 200, clientY: 200 });
      fireEvent.pointerMove(point, { ...mouse, clientX: 240, clientY: 202 });
      expect(signal.active()).toBe(true);
      end(point, { ...mouse });
      expect(signal.active()).toBe(false);
    }
  });

  it("is in progress while the starting-mix square is dragged, and ends when it is let go", () => {
    const signal = createInteraction();
    const { square } = shown(signal);
    expect(square).not.toBeNull();
    for (const end of [fireEvent.pointerUp, fireEvent.pointerCancel, fireEvent.lostPointerCapture]) {
      fireEvent.pointerDown(square, { ...mouse, clientX: 200, clientY: 200 });
      // a press that has not travelled is a tap on the marker, not a drag
      expect(signal.active()).toBe(false);
      fireEvent.pointerMove(square, { ...mouse, clientX: 240, clientY: 202 });
      expect(signal.active()).toBe(true);
      end(square, { ...mouse });
      expect(signal.active()).toBe(false);
    }
  });

  it("is in progress while an arrow key is held on the point, and ends on its release", () => {
    const signal = createInteraction();
    const { point, onNudge } = shown(signal);
    fireEvent.keyDown(point, { key: "ArrowLeft" });
    fireEvent.keyDown(point, { key: "ArrowLeft", repeat: true });
    expect(onNudge).toHaveBeenCalledTimes(2);
    expect(signal.active()).toBe(true);
    fireEvent.keyUp(point, { key: "ArrowLeft" });
    expect(signal.active()).toBe(false);
    // Enter pins the card: it moves nothing
    fireEvent.keyDown(point, { key: "Enter" });
    expect(signal.active()).toBe(false);
  });
});
