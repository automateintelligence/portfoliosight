import { scaleLinear, type ScaleLinear } from "d3-scale";

export type Margins = { top: number; right: number; bottom: number; left: number };

/** Spec 8: chart margins 48/16/40/56 px (desktop) and 32/12/36/44 (phone), as top/right/bottom/left. */
export const DESKTOP_MARGINS: Margins = { top: 48, right: 16, bottom: 40, left: 56 };
export const PHONE_MARGINS: Margins = { top: 32, right: 12, bottom: 36, left: 44 };

export type Extent = { xMin: number; xMax: number; yMin: number; yMax: number };

export type ChartScales = {
  x: ScaleLinear<number, number>;
  y: ScaleLinear<number, number>;
  width: number;
  height: number;
  margins: Margins;
  plot: { left: number; right: number; top: number; bottom: number; width: number; height: number };
};

/** Maps (σ, μ), both annual fractions, to pixels inside a `width` × `height` box. */
export function makeScales(width: number, height: number, extent: Extent, phone: boolean): ChartScales {
  const margins = phone ? PHONE_MARGINS : DESKTOP_MARGINS;
  const left = margins.left;
  const right = Math.max(left + 1, width - margins.right);
  const top = margins.top;
  const bottom = Math.max(top + 1, height - margins.bottom);
  const x = scaleLinear().domain([extent.xMin, extent.xMax]).range([left, right]);
  const y = scaleLinear().domain([extent.yMin, extent.yMax]).range([bottom, top]);
  return { x, y, width, height, margins, plot: { left, right, top, bottom, width: right - left, height: bottom - top } };
}

/** Pads a data extent so marks never touch the plot edge and the axes start on round percents. */
export function paddedExtent(points: { sigma: number; mu: number }[], cell: { dx: number; dy: number }): Extent {
  let xMin = Infinity;
  let xMax = -Infinity;
  let yMin = Infinity;
  let yMax = -Infinity;
  for (const p of points) {
    if (!Number.isFinite(p.sigma) || !Number.isFinite(p.mu)) continue;
    xMin = Math.min(xMin, p.sigma);
    xMax = Math.max(xMax, p.sigma);
    yMin = Math.min(yMin, p.mu);
    yMax = Math.max(yMax, p.mu);
  }
  if (!Number.isFinite(xMin)) return { xMin: 0, xMax: 0.2, yMin: 0, yMax: 0.1 };
  const xPad = Math.max((xMax - xMin) * 0.045, cell.dx);
  const yPadTop = Math.max((yMax - yMin) * 0.14, cell.dy);
  const yPadBottom = Math.max((yMax - yMin) * 0.05, cell.dy);
  return { xMin: Math.max(0, xMin - xPad), xMax: xMax + xPad, yMin: yMin - yPadBottom, yMax: yMax + yPadTop };
}
