import { scaleLinear, type ScaleLinear } from "d3-scale";

export type Margins = { top: number; right: number; bottom: number; left: number };

/**
 * Spec 8: chart margins 48/16/58/56 px (desktop) and 32/12/54/44 (phone), as top/right/bottom/left.
 * The bottom margin holds the axis ticks and, under them, the axis title with its details line;
 * it is `CHART_FOOT` px deeper than the plot alone needs, and the chart box is that much taller
 * (app.css `--chart-foot`), so the plot keeps its size.
 */
export const DESKTOP_MARGINS: Margins = { top: 48, right: 16, bottom: 58, left: 56 };
export const PHONE_MARGINS: Margins = { top: 32, right: 12, bottom: 54, left: 44 };
export const CHART_FOOT = 18;
/** Distance from the plot's bottom edge to the top of the axis title: under the tick labels. */
export const X_TITLE_GAP = { desktop: 23, phone: 21 } as const;

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

/**
 * The longest run of a polyline that lies inside the box `[xMin, xMax] x [yMin, yMax]`, its ends
 * moved onto the box's edges (Liang-Barsky on each segment). A frontier rises in both risk and
 * return, so its inside part is one run.
 */
export function clipCurve(curve: { sigma: number[]; mu: number[] }, box: Extent): { sigma: number[]; mu: number[] } {
  let best: [number, number][] = [];
  let run: [number, number][] = [];
  const close = () => {
    if (run.length > best.length) best = run;
    run = [];
  };
  for (let i = 1; i < curve.sigma.length; i++) {
    const [x0, y0, x1, y1] = [curve.sigma[i - 1], curve.mu[i - 1], curve.sigma[i], curve.mu[i]];
    const dx = x1 - x0;
    const dy = y1 - y0;
    let lo = 0;
    let hi = 1;
    const sides: [number, number][] = [
      [-dx, x0 - box.xMin],
      [dx, box.xMax - x0],
      [-dy, y0 - box.yMin],
      [dy, box.yMax - y0],
    ];
    let inside = true;
    for (const [p, q] of sides) {
      if (p === 0) {
        if (q < 0) inside = false;
      } else if (p < 0) lo = Math.max(lo, q / p);
      else hi = Math.min(hi, q / p);
    }
    if (!inside || lo > hi) {
      close();
      continue;
    }
    const a: [number, number] = [x0 + lo * dx, y0 + lo * dy];
    const b: [number, number] = [x0 + hi * dx, y0 + hi * dy];
    if (run.length === 0) run.push(a);
    else if (lo > 0) {
      close();
      run.push(a);
    }
    run.push(b);
    if (hi < 1) close();
  }
  close();
  return { sigma: best.map((p) => p[0]), mu: best.map((p) => p[1]) };
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
