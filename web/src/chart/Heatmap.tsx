import { interpolateRgbBasis } from "d3-interpolate";
import { useEffect, useRef } from "react";
import type { Tensor } from "../api/tensor";
import type { ChartScales } from "./scales";

export type Curve = { sigma: number[]; mu: number[] };
export type Ghost = { id: string; curve: Curve };

export type HeatColors = {
  heat: string[];
  frontier: string;
  backdrop: string;
  /** Gap between cells in CSS px (0 = seamless). */
  gap: number;
};

/** Reads the chart colours from the computed custom properties of `el`. */
export function readHeatColors(el: Element): HeatColors {
  const cs = getComputedStyle(el);
  const get = (name: string, fallback: string) => cs.getPropertyValue(name).trim() || fallback;
  return {
    heat: [0, 1, 2, 3, 4].map((i) => get(`--heat-${i}`, "#000000")),
    frontier: get("--frontier", "#ffffff"),
    backdrop: get("--chart-bg", get("--bg", "#000000")),
    gap: Number(get("--cell-gap", "0")) || 0,
  };
}

type Ctx = Pick<
  CanvasRenderingContext2D,
  | "save" | "restore" | "beginPath" | "moveTo" | "lineTo" | "closePath" | "clip" | "fillRect" | "stroke" | "clearRect"
  | "setTransform" | "setLineDash"
> & { fillStyle: unknown; strokeStyle: unknown; lineWidth: number; lineJoin: string; lineCap: string; globalAlpha: number };

function traceCurve(ctx: Ctx, curve: Curve, scales: ChartScales, dpr: number): void {
  for (let i = 0; i < curve.sigma.length; i++) {
    const px = scales.x(curve.sigma[i]) * dpr;
    const py = scales.y(curve.mu[i]) * dpr;
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
}

/**
 * Draws, in order: one filled rectangle per feasible cell (colour = ramp(Z / enb_ref), spec 8),
 * clipped to the area under the frontier so nothing is painted above it; ghost frontiers at 40%
 * opacity; the primary frontier at 2 px. Works in device pixels for crisp cell edges.
 */
export function drawHeatmap(ctx: Ctx, tensor: Tensor, ghosts: Ghost[], scales: ChartScales, colors: HeatColors, dpr: number, frontierEnb?: number[]): number {
  const { frontier, grid, frontier_curve: curve } = tensor;
  const NX = frontier.x.length;
  const NY = grid.y.length;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, Math.ceil(scales.width * dpr) + 2, Math.ceil(scales.height * dpr) + 2);
  if (NX < 2 || NY < 2) return 0;

  const ramp = interpolateRgbBasis(colors.heat);
  const cellW = Math.abs(scales.x(frontier.x[1]) - scales.x(frontier.x[0]));
  const cellH = Math.abs(scales.y(grid.y[1]) - scales.y(grid.y[0]));
  const gap = cellW >= 12 ? colors.gap : colors.gap * 0.5;
  const gapPx = Math.round(gap * dpr);
  const floorY = (scales.y(grid.y[0]) + cellH / 2) * dpr;

  // Clip to the region under the drawn frontier, between the first and the last risk column.
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(scales.x(curve.sigma[0]) * dpr, floorY);
  for (let i = 0; i < curve.sigma.length; i++) ctx.lineTo(scales.x(curve.sigma[i]) * dpr, scales.y(curve.mu[i]) * dpr);
  ctx.lineTo(scales.x(curve.sigma[curve.sigma.length - 1]) * dpr, floorY);
  ctx.closePath();
  ctx.clip();

  let cells = 0;
  for (let j = 0; j < NX; j++) {
    const cx = scales.x(frontier.x[j]);
    const left = Math.round((cx - cellW / 2) * dpr);
    const right = Math.round((cx + cellW / 2) * dpr);
    const column = grid.z[j];
    // The frontier mix is the column's top candidate (spec 4.7): its colour fills the sliver
    // between the highest computed cell and the frontier, so the map meets the line.
    const zTop = frontierEnb?.[j];
    if (zTop !== undefined && Number.isFinite(zTop)) {
      let kTop = -1;
      for (let k = 0; k < NY; k++) if (column[k] !== null && column[k] !== undefined) kTop = k;
      const from = kTop >= 0 ? Math.round((scales.y(grid.y[kTop]) - cellH / 2) * dpr) : Math.round(floorY);
      const upTo = Math.round((scales.y(frontier.y[j]) - cellH) * dpr);
      ctx.fillStyle = ramp(Math.max(0, Math.min(1, zTop / tensor.enb_ref)));
      if (from > upTo) ctx.fillRect(left, upTo, Math.max(1, right - left - gapPx), from - upTo - gapPx);
    }
    for (let k = 0; k < NY; k++) {
      const z = column[k];
      if (z === null || z === undefined) continue;
      const cy = scales.y(grid.y[k]);
      const top = Math.round((cy - cellH / 2) * dpr);
      const bottom = Math.round((cy + cellH / 2) * dpr);
      ctx.fillStyle = ramp(Math.max(0, Math.min(1, z / tensor.enb_ref)));
      ctx.fillRect(left, top, Math.max(1, right - left - gapPx), Math.max(1, bottom - top - gapPx));
      cells += 1;
    }
  }
  ctx.restore();

  // Ghost frontiers: thin, 40% opacity.
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  for (const ghost of ghosts) {
    ctx.save();
    ctx.globalAlpha = 0.4;
    ctx.strokeStyle = colors.frontier;
    ctx.lineWidth = Math.max(1, dpr);
    ctx.setLineDash([6 * dpr, 4 * dpr]);
    ctx.beginPath();
    traceCurve(ctx, ghost.curve, scales, dpr);
    ctx.stroke();
    ctx.restore();
  }

  // Primary frontier: a soft backdrop-coloured edge for legibility, then the 2 px line.
  ctx.save();
  ctx.setLineDash([]);
  ctx.globalAlpha = 0.5;
  ctx.strokeStyle = colors.backdrop;
  ctx.lineWidth = 5 * dpr;
  ctx.beginPath();
  traceCurve(ctx, curve, scales, dpr);
  ctx.stroke();
  ctx.globalAlpha = 1;
  ctx.strokeStyle = colors.frontier;
  ctx.lineWidth = 2 * dpr;
  ctx.beginPath();
  traceCurve(ctx, curve, scales, dpr);
  ctx.stroke();
  ctx.restore();
  return cells;
}

type Props = {
  tensor: Tensor;
  /** ENB of each column's frontier mix, for the sliver under the line. */
  frontierEnb: number[];
  ghosts: Ghost[];
  scales: ChartScales;
  /** Bumps when the theme attribute has changed, so colours are re-read. */
  themeEpoch: number;
  reveal: boolean;
};

/** Canvas layer. Redraws on theme, tensor, ghost and size changes only, never on a slider tick. */
export function Heatmap({ tensor, frontierEnb, ghosts, scales, themeEpoch, reveal }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || scales.width <= 0 || scales.height <= 0) return;
    const dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1));
    const w = Math.round(scales.width * dpr);
    const h = Math.round(scales.height * dpr);
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;
    drawHeatmap(ctx, tensor, ghosts, scales, readHeatColors(canvas), dpr, frontierEnb);
  }, [tensor, frontierEnb, ghosts, scales, themeEpoch]);

  return <canvas ref={ref} className={reveal ? "chart-canvas reveal" : "chart-canvas"} data-testid="chart-canvas" aria-hidden="true" />;
}
