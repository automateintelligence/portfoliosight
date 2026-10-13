import { axisBottom, axisLeft } from "d3-axis";
import { select } from "d3-selection";
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import type { ChartScales } from "./scales";

export type Mark = { sigma: number; mu: number };

type Props = {
  scales: ChartScales;
  phone: boolean;
  /** The selected risk ceiling X(s) and the frontier's return there (top of the dashed line). */
  ceiling: Mark;
  selected: Mark;
  mostDiversified: Mark;
  current: Mark | null;
  /** Fund dots with ticker labels: details only. */
  funds: (Mark & { id: string })[] | null;
  selectedLabel: string;
  tooltip: ReactNode;
  /** Horizontal drag: the pixel x the ceiling should move to. */
  onRiskPixel: (px: number) => void;
  /** Vertical drag: the pixel y the point should move to. */
  onDivPixel: (py: number) => void;
  /** Keyboard on the point: arrows step the two sliders. */
  onNudge: (ds: number, dt: number) => void;
};

const fmtTick = (v: number) => `${Number((v * 100).toFixed(1))}%`;
const HIT = 22; // 44 px touch target around a point drawn much smaller (spec 3.4)
const AXIS_LOCK = 6; // px of travel before a drag commits to one direction

/**
 * SVG layer over the canvas: axes (d3-axis ticks), the dashed risk-ceiling line and the markers,
 * each drawn at its mix's actual risk and return. Updates on every slider tick.
 */
export function Overlay({ scales, phone, ceiling, selected, mostDiversified, current, funds, selectedLabel, tooltip, onRiskPixel, onDivPixel, onNudge }: Props) {
  const xAxisRef = useRef<SVGGElement>(null);
  const yAxisRef = useRef<SVGGElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x0: number; y0: number; grabDx: number; grabDy: number; axis: "x" | "y" | null } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [tip, setTip] = useState(false);
  const { x, y, plot } = scales;

  useEffect(() => {
    if (!xAxisRef.current || !yAxisRef.current) return;
    // offset(0): ticks sit exactly on the scale, so the markers, the canvas and the axes agree.
    select(xAxisRef.current).call(axisBottom(x).ticks(phone ? 5 : 9).tickFormat((v) => fmtTick(Number(v))).tickSize(4).tickPadding(4).offset(0));
    select(yAxisRef.current).call(axisLeft(y).ticks(phone ? 5 : 7).tickFormat((v) => fmtTick(Number(v))).tickSize(4).tickPadding(4).offset(0));
    select(yAxisRef.current).select(".domain").remove();
  }, [x, y, phone]);

  const sx = x(selected.sigma);
  const sy = y(selected.mu);
  const cx = x(ceiling.sigma);
  const cTop = Math.min(plot.bottom, y(ceiling.mu));

  const local = (e: ReactPointerEvent) => {
    const r = svgRef.current?.getBoundingClientRect();
    return { px: e.clientX - (r?.left ?? 0), py: e.clientY - (r?.top ?? 0) };
  };
  const onPointerDown = (e: ReactPointerEvent<SVGGElement>) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const p = local(e);
    // Remember where the pointer grabbed, so the ceiling and the point do not jump under it.
    drag.current = { x0: p.px, y0: p.py, grabDx: cx - p.px, grabDy: sy - p.py, axis: null };
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      // capture is a convenience only
    }
    setDragging(true);
    setTip(true);
  };
  const onPointerMove = (e: ReactPointerEvent<SVGGElement>) => {
    const d = drag.current;
    if (!d) return;
    const p = local(e);
    if (d.axis === null) {
      const dx = Math.abs(p.px - d.x0);
      const dy = Math.abs(p.py - d.y0);
      if (Math.max(dx, dy) < AXIS_LOCK) return;
      d.axis = dx >= dy ? "x" : "y";
    }
    if (d.axis === "x") onRiskPixel(p.px + d.grabDx);
    else onDivPixel(p.py + d.grabDy);
  };
  const endDrag = () => {
    drag.current = null;
    setDragging(false);
  };
  const onKeyDown = (e: KeyboardEvent<SVGGElement>) => {
    const moves: Record<string, [number, number]> = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] };
    const move = moves[e.key];
    if (!move) return;
    e.preventDefault();
    onNudge(move[0], move[1]);
  };

  const tipLeft = Math.min(Math.max(plot.left + 4, sx + 18), scales.width - (phone ? 214 : 240));
  const tipBelow = sy < plot.top + 170;

  return (
    <>
      <svg ref={svgRef} className="overlay" width={scales.width} height={scales.height} role="group" aria-label="Chart markers">
        <g ref={xAxisRef} className="axis axis-x" transform={`translate(0,${plot.bottom})`} aria-hidden="true" />
        <g ref={yAxisRef} className="axis axis-y" transform={`translate(${plot.left},0)`} aria-hidden="true" />
        <g data-testid="ceiling-line">
          <line className="ceiling-back" x1={cx} x2={cx} y1={plot.bottom} y2={cTop} />
          <line className="ceiling" x1={cx} x2={cx} y1={plot.bottom} y2={cTop} />
        </g>
        {funds?.map((f) => (
          <g key={f.id} className="fund-dot" transform={`translate(${x(f.sigma)},${y(f.mu)})`}>
            <circle r={2.6} />
            <text x={5} y={3}>
              {f.id}
            </text>
          </g>
        ))}
        <circle className="pt-div" data-testid="point-div" cx={x(mostDiversified.sigma)} cy={y(mostDiversified.mu)} r={4.5} />
        {current && <rect className="pt-current" data-testid="point-current" x={x(current.sigma) - 6.5} y={y(current.mu) - 6.5} width={13} height={13} rx={2} />}
        <g
          className={dragging ? "pt-selected dragging" : "pt-selected"}
          data-testid="point-selected"
          transform={`translate(${sx},${sy})`}
          tabIndex={0}
          role="img"
          aria-label={selectedLabel}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onLostPointerCapture={endDrag}
          onPointerEnter={() => setTip(true)}
          onPointerLeave={() => !drag.current && setTip(false)}
          onFocus={() => setTip(true)}
          onBlur={() => setTip(false)}
          onKeyDown={onKeyDown}
        >
          <circle className="hit" r={HIT} />
          <circle className="halo" r={16} />
          <circle className="reticle" r={16} />
          <circle className="dot-back" r={10.5} />
          <circle className="dot" r={8} />
        </g>
      </svg>
      {tip && tooltip && (
        <div className="tooltip" role="tooltip" style={{ left: tipLeft, top: tipBelow ? sy + 26 : undefined, bottom: tipBelow ? undefined : scales.height - sy + 26 }}>
          {tooltip}
        </div>
      )}
    </>
  );
}
