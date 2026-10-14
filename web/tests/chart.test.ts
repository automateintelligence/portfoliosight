import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parseTensor } from "../src/api/client";
import { drawHeatmap, RAMP_FLOOR, rampPosition } from "../src/chart/Heatmap";
import { DESKTOP_MARGINS, makeScales, paddedExtent, PHONE_MARGINS } from "../src/chart/scales";
import { portfolioMath } from "../src/math/portfolio";
import { ceilingAt, deriveView, frontierMuAt, ladderCollapsedAt, positionOfCeiling } from "../src/math/view";

const TENSOR = parseTensor(JSON.parse(fs.readFileSync(path.resolve(process.cwd(), "fixtures/guide2017_5y.json"), "utf8")));
const math = portfolioMath(TENSOR);
const COLORS = { heat: ["#000000", "#400000", "#800000", "#c00000", "#ff0000"], frontier: "#ffffff", backdrop: "#101010", gap: 0 };

function recorder() {
  const rects: { style: string; x: number; y: number; w: number; h: number }[] = [];
  const strokes: { style: string; width: number; alpha: number; points: number }[] = [];
  let points = 0;
  const ctx = {
    fillStyle: "", strokeStyle: "", lineWidth: 1, lineJoin: "", lineCap: "", globalAlpha: 1,
    save() {}, restore() { this.globalAlpha = 1; }, closePath() {}, clip() {}, clearRect() {}, setTransform() {}, setLineDash() {},
    beginPath() { points = 0; },
    moveTo() { points += 1; },
    lineTo() { points += 1; },
    fillRect(x: number, y: number, w: number, h: number) { rects.push({ style: String(this.fillStyle), x, y, w, h }); },
    stroke() { strokes.push({ style: String(this.strokeStyle), width: this.lineWidth, alpha: this.globalAlpha, points }); },
  };
  return { ctx, rects, strokes };
}

describe("chart scales (spec 8)", () => {
  it("uses the desktop and phone margins and maps risk right, return up", () => {
    expect(DESKTOP_MARGINS).toEqual({ top: 48, right: 16, bottom: 40, left: 56 });
    expect(PHONE_MARGINS).toEqual({ top: 32, right: 12, bottom: 36, left: 44 });
    const extent = { xMin: 0, xMax: 0.2, yMin: 0, yMax: 0.1 };
    const d = makeScales(1000, 500, extent, false);
    expect([d.x(0), d.x(0.2), d.y(0), d.y(0.1)]).toEqual([56, 984, 460, 48]);
    const p = makeScales(358, 358, extent, true);
    expect([p.x(0), p.x(0.2), p.y(0), p.y(0.1)]).toEqual([44, 346, 322, 32]);
  });

  it("pads the extent so no mark touches the frame", () => {
    const e = paddedExtent([{ sigma: 0.03, mu: 0.02 }, { sigma: 0.17, mu: 0.12 }], { dx: 0.001, dy: 0.001 });
    expect(e.xMin).toBeLessThan(0.03);
    expect(e.xMax).toBeGreaterThan(0.17);
    expect(e.yMin).toBeLessThan(0.02);
    expect(e.yMax).toBeGreaterThan(0.12);
  });
});

describe("heatmap drawing", () => {
  const scales = makeScales(1000, 500, { xMin: 0.02, xMax: 0.18, yMin: 0.01, yMax: 0.13 }, false);
  const feasible = TENSOR.grid.z.flat().filter((z) => z !== null).length;

  it("puts the least spread-out mix at the bright end of the ramp and stops the most spread-out one short of the dark end", () => {
    expect(rampPosition(0)).toBe(1);
    expect(rampPosition(1)).toBeCloseTo(RAMP_FLOOR, 12);
    expect(rampPosition(0.5)).toBeCloseTo(0.6, 12);
    expect(rampPosition(0.25)).toBeGreaterThan(rampPosition(0.75));
    expect(rampPosition(-1)).toBe(1);
    expect(rampPosition(7)).toBeCloseTo(RAMP_FLOOR, 12);
  });

  it("paints one rectangle per feasible cell, centred on its column and row, coloured by 1 - 0.8 * Z / enb_ref", () => {
    const { ctx, rects } = recorder();
    expect(drawHeatmap(ctx, TENSOR, [], scales, COLORS, 1)).toBe(feasible);
    expect(rects.length).toBe(feasible);
    const j = 20;
    // the row of the column's peak always holds a cell
    const k = TENSOR.grid.k_div[j];
    expect(k).toBeGreaterThanOrEqual(0);
    const cx = scales.x(TENSOR.frontier.x[j]);
    const cy = scales.y(TENSOR.grid.y[k]);
    const hit = rects.filter((r) => r.x <= cx && cx <= r.x + r.w && r.y <= cy && cy <= r.y + r.h);
    expect(hit.length).toBe(1);
    const q = (TENSOR.grid.z[j][k] as number) / TENSOR.enb_ref;
    const red = Number(/rgb\((\d+)/.exec(hit[0].style)?.[1]);
    expect(Math.abs(red - 255 * (1 - 0.8 * q))).toBeLessThan(12);
    // different Z, different colour
    expect(new Set(rects.map((r) => r.style)).size).toBeGreaterThan(10);
  });

  it("draws ghosts thin at 40% and the frontier last at 2 px in the frontier colour", () => {
    const { ctx, strokes } = recorder();
    drawHeatmap(ctx, TENSOR, [{ id: "1y", curve: TENSOR.frontier_curve }], scales, COLORS, 2);
    expect(strokes[0]).toMatchObject({ alpha: 0.4, width: 2, style: "#ffffff" });
    const last = strokes[strokes.length - 1];
    expect(last).toMatchObject({ alpha: 1, width: 4, style: "#ffffff", points: TENSOR.frontier_curve.sigma.length });
  });
});

describe("view derivation", () => {
  const domain = math.riskSliderDomain();
  it("the ceiling and its inverse agree, and the dashed line ends on the drawn frontier", () => {
    for (const s of [domain.s_safe, 10.25, 33.5, domain.s_max]) {
      expect(positionOfCeiling(TENSOR, ceilingAt(TENSOR, s))).toBeCloseTo(s, 9);
    }
    const j = 17;
    expect(frontierMuAt(TENSOR.frontier_curve, TENSOR.frontier_curve.sigma[8 * j])).toBeCloseTo(TENSOR.frontier_curve.mu[8 * j], 12);
  });

  it("auto follows the suggested position and the selected mix never passes the ceiling", () => {
    for (const s of [domain.s_safe, 12.5, 30, domain.s_max]) {
      const auto = deriveView(TENSOR, math, s, "auto");
      expect(auto.t).toBe(math.tAuto(s));
      expect(auto.moved).toBe(false);
      for (const t of [0, 0.5, 1]) {
        const v = deriveView(TENSOR, math, s, t);
        expect(v.selected.sigma).toBeLessThanOrEqual(v.ceiling + 1e-6);
        expect(v.moved).toBe(true);
      }
      expect(deriveView(TENSOR, math, s, 0).selected.mu).toBeCloseTo(auto.front.mu, 12);
      expect(deriveView(TENSOR, math, s, 1).selected.enb).toBeCloseTo(auto.mostDiversified.enb, 12);
    }
  });

  it("readouts come from the frontier mix and the strip from the selected mix", () => {
    const v = deriveView(TENSOR, math, 30, 1);
    expect(v.frontRange).toEqual(math.range6m(v.front.mu, v.front.sigma));
    expect(v.range).toEqual(math.range6m(v.selected.mu, v.selected.sigma));
    expect(v.range.typical).not.toBe(v.frontRange.typical);
  });

  it("a position outside the domain is clamped, and a collapsed column disables the second slider", () => {
    expect(deriveView(TENSOR, math, -5, "auto").s).toBe(domain.s_safe);
    expect(TENSOR.grid.k_div[0]).toBe(-1);
    expect(ladderCollapsedAt(TENSOR, 0)).toBe(true);
    expect(ladderCollapsedAt(TENSOR, 0.5)).toBe(TENSOR.grid.k_div[1] < 0);
    expect(ladderCollapsedAt(TENSOR, 20)).toBe(false);
  });
});
