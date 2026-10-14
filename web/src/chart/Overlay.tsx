import { axisBottom, axisLeft } from "d3-axis";
import { select } from "d3-selection";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import type { ChartScales } from "./scales";

export type Mark = { sigma: number; mu: number };

export type MarkId = "selected" | "div" | "current";

/** One frontier line to name at its right end: the primary line or a ghost. */
export type LineEnd = { id: string; label: string; primary: boolean; sigma: number; mu: number };

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
  /** What a screen reader hears on the other two markers. */
  divLabel: string;
  currentLabel: string;
  /** The risk position and its domain, for the point's slider semantics. */
  position: { s: number; min: number; max: number };
  /** A tensor is loading: the point does not move. */
  busy: boolean;
  /** The information card of each marker. */
  cards: Record<MarkId, ReactNode>;
  /** The frontier lines to label, the primary one included. */
  lines: LineEnd[];
  /** The ghost line under the pointer, redrawn at full strength. */
  hot: { id: string; path: string } | null;
  /** Horizontal drag: the pixel x the ceiling should move to. */
  onRiskPixel: (px: number) => void;
  /** Vertical drag: pixels moved down since the drag began (`start` is true on its first call). */
  onDivDrag: (dy: number, start: boolean) => void;
  /** Keyboard on the point: arrows step the two sliders. */
  onNudge: (ds: number, dt: number) => void;
};

const fmtTick = (v: number) => `${Number((v * 100).toFixed(1))}%`;
const HIT = 22; // 44 px touch target around a point drawn much smaller (spec 3.4)
const AXIS_LOCK = 6; // px of travel before a drag commits to one direction
const LABEL_STEP = 14; // px between two line labels that would otherwise touch
const CARD_W = { desktop: 260, phone: 224 };

export type PlacedLabel = LineEnd & { ex: number; ey: number; x: number; y: number; anchor: "start" | "end"; leader: string | null };

/**
 * Where each frontier label goes: to the right of its line's end where there is room, otherwise
 * above the end. Labels that would touch are stepped apart and joined to their line by a short
 * elbow, the primary line keeping its place.
 */
export function placeLabels(lines: LineEnd[], scales: ChartScales, phone: boolean): PlacedLabel[] {
  const charW = phone ? 5.7 : 6.3;
  const placed: (PlacedLabel & { w: number })[] = [];
  const ordered = [...lines].sort((a, b) => Number(b.primary) - Number(a.primary) || scales.y(a.mu) - scales.y(b.mu));
  for (const line of ordered) {
    const ex = scales.x(line.sigma);
    const ey = scales.y(line.mu);
    const w = line.label.length * charW;
    const right = !phone && ex + 10 + w <= scales.width - 4;
    const anchor = right ? ("start" as const) : ("end" as const);
    const x = right ? ex + 10 : Math.max(scales.plot.left + w + 2, ex - 2);
    const y0 = right ? ey + 4 : ey - 9;
    const span = (lx: number, a: "start" | "end", lw: number) => (a === "start" ? [lx, lx + lw] : [lx - lw, lx]);
    const clash = (y: number) =>
      placed.some((p) => {
        const [a0, a1] = span(x, anchor, w);
        const [b0, b1] = span(p.x, p.anchor, p.w);
        return Math.abs(p.y - y) < LABEL_STEP && a0 < b1 + 6 && b0 < a1 + 6;
      });
    let y = y0;
    for (let n = 1; clash(y) && n <= 2 * lines.length + 2; n++) {
      const step = Math.ceil(n / 2) * LABEL_STEP * (n % 2 === 1 ? -1 : 1);
      const cand = y0 + step;
      if (cand < 12 || cand > scales.plot.bottom - 4) continue;
      y = cand;
    }
    const moved = Math.abs(y - y0) > 1;
    const leader = !moved ? null : right ? `M${ex + 1} ${ey}L${ex + 4} ${ey}L${ex + 8} ${y - 4}` : `M${ex} ${ey - 1}L${ex} ${ey - 4}L${ex - 3} ${y + 3}`;
    placed.push({ ...line, ex, ey, x, y, anchor, leader, w });
  }
  return placed;
}

/**
 * SVG layer over the canvas: axes (d3-axis ticks), the dashed risk-ceiling line, the names of the
 * frontier lines and the markers, each drawn at its mix's actual risk and return. Updates on
 * every slider tick.
 */
export function Overlay({ scales, phone, ceiling, selected, mostDiversified, current, funds, selectedLabel, divLabel, currentLabel, position, busy, cards, lines, hot, onRiskPixel, onDivDrag, onNudge }: Props) {
  const xAxisRef = useRef<SVGGElement>(null);
  const yAxisRef = useRef<SVGGElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x0: number; y0: number; grabDx: number; axis: "x" | "y" | null } | null>(null);
  const fresh = useRef(false); // focus has just shown a card: the click that follows must not turn it over
  const [dragging, setDragging] = useState(false);
  const [tip, setTip] = useState<MarkId | null>(null);
  const [cardH, setCardH] = useState(250);
  const { x, y, plot } = scales;

  useEffect(() => {
    if (!xAxisRef.current || !yAxisRef.current) return;
    // offset(0): ticks sit exactly on the scale, so the markers, the canvas and the axes agree.
    select(xAxisRef.current).call(axisBottom(x).ticks(phone ? 5 : 9).tickFormat((v) => fmtTick(Number(v))).tickSize(4).tickPadding(4).offset(0));
    select(yAxisRef.current).call(axisLeft(y).ticks(phone ? 5 : 7).tickFormat((v) => fmtTick(Number(v))).tickSize(4).tickPadding(4).offset(0));
    select(yAxisRef.current).select(".domain").remove();
  }, [x, y, phone]);

  // A card opened by a tap stays until the next press anywhere else.
  useEffect(() => {
    if (tip === null) return;
    const away = (e: PointerEvent) => {
      if (!(e.target instanceof Element) || !e.target.closest("[data-mark]")) setTip(null);
    };
    document.addEventListener("pointerdown", away, true);
    return () => document.removeEventListener("pointerdown", away, true);
  }, [tip]);
  // The card's real height, measured whenever its content could have changed.
  useLayoutEffect(() => {
    const h = cardRef.current?.offsetHeight;
    if (h) setCardH((was) => (Math.abs(h - was) > 1 ? h : was));
  }, [tip, cards]);

  const labels = useMemo(() => placeLabels(lines, scales, phone), [lines, scales, phone]);

  const sx = x(selected.sigma);
  const sy = y(selected.mu);
  const cx = x(ceiling.sigma);
  const cTop = Math.min(plot.bottom, y(ceiling.mu));
  const at: Record<MarkId, { px: number; py: number } | null> = {
    selected: { px: sx, py: sy },
    div: { px: x(mostDiversified.sigma), py: y(mostDiversified.mu) },
    current: current ? { px: x(current.sigma), py: y(current.mu) } : null,
  };

  const local = (e: ReactPointerEvent) => {
    const r = svgRef.current?.getBoundingClientRect();
    return { px: e.clientX - (r?.left ?? 0), py: e.clientY - (r?.top ?? 0) };
  };
  const onPointerDown = (e: ReactPointerEvent<SVGGElement>) => {
    if (busy || (e.pointerType === "mouse" && e.button !== 0)) return;
    const p = local(e);
    // Remember where the pointer grabbed, so the ceiling and the point do not jump under it.
    drag.current = { x0: p.px, y0: p.py, grabDx: cx - p.px, axis: null };
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      // capture is a convenience only
    }
    setDragging(true);
    setTip("selected");
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
      if (d.axis === "y") {
        // Movement is measured from here, so the point leaves from where it is without a jump.
        d.y0 = p.py;
        onDivDrag(0, true);
      }
    }
    if (d.axis === "x") onRiskPixel(p.px + d.grabDx);
    else onDivDrag(p.py - d.y0, false);
  };
  const endDrag = () => {
    drag.current = null;
    setDragging(false);
  };
  const onKeyDown = (e: KeyboardEvent<SVGGElement>) => {
    const moves: Record<string, [number, number]> = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] };
    const move = moves[e.key];
    if (!move || busy) return;
    e.preventDefault();
    onNudge(move[0], move[1]);
  };

  // The square and the open circle can sit on top of each other; then only the upper one can be
  // reached, so a second tap or click on it turns the card over to the marker underneath.
  const under = (id: MarkId): MarkId | null => {
    const other = id === "current" ? "div" : id === "div" ? "current" : null;
    const a = at[id];
    const b = other ? at[other] : null;
    return other && a && b && Math.hypot(a.px - b.px, a.py - b.py) < 16 ? other : null;
  };
  // Hover shows a marker's card with a mouse; a tap or keyboard focus shows it too.
  const show = (id: MarkId) => ({
    onPointerEnter: (e: ReactPointerEvent) => {
      if (e.pointerType !== "touch") setTip(id);
    },
    onPointerLeave: (e: ReactPointerEvent) => {
      if (e.pointerType !== "touch" && !drag.current) setTip(null);
    },
    onFocus: () => {
      fresh.current = true;
      setTip(id);
    },
    onBlur: () => setTip(null),
  });
  // A tap focuses the marker first (which already shows the card), so the first tap only opens
  // it; the next press anywhere else, or Escape, closes it.
  const tapToggle = (id: MarkId) => ({
    onClick: () => {
      const first = fresh.current;
      fresh.current = false;
      setTip((now) => (!first && now === id ? (under(id) ?? id) : id));
    },
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key === "Escape") setTip(null);
    },
  });

  // The card sits beside its marker, on the side with room, and never leaves the chart.
  const where = tip ? at[tip] : null;
  const cardW = phone ? CARD_W.phone : CARD_W.desktop;
  let cardLeft = 0;
  let cardTop = 0;
  if (where) {
    cardLeft = where.px + 24 + cardW <= scales.width - 4 ? where.px + 24 : where.px - 24 - cardW;
    cardLeft = Math.max(4, Math.min(cardLeft, scales.width - cardW - 4));
    cardTop = Math.max(4, Math.min(where.py - cardH / 2, scales.height - cardH - 4));
  }

  return (
    <>
      <svg ref={svgRef} className="overlay" width={scales.width} height={scales.height} role="group" aria-label="Chart markers">
        <g ref={xAxisRef} className="axis axis-x" transform={`translate(0,${plot.bottom})`} aria-hidden="true" />
        <g ref={yAxisRef} className="axis axis-y" transform={`translate(${plot.left},0)`} aria-hidden="true" />
        {hot && <path className="ghost-hot" d={hot.path} aria-hidden="true" />}
        <g className="line-labels">
          {labels.map((l) => (
            <g key={l.id} className={`line-label${l.primary ? " is-primary" : ""}${hot?.id === l.id ? " is-hot" : ""}`} data-testid={`frontier-label-${l.id}`} data-end-x={l.ex.toFixed(1)} data-end-y={l.ey.toFixed(1)}>
              {l.leader && <path className="leader" d={l.leader} />}
              <text x={l.x} y={l.y} textAnchor={l.anchor}>
                {l.label}
              </text>
            </g>
          ))}
        </g>
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
        <g className="mark" data-mark="div" tabIndex={0} role="img" aria-label={divLabel} {...show("div")} {...tapToggle("div")}>
          <circle className="hit" cx={at.div!.px} cy={at.div!.py} r={phone ? HIT : 13} />
          <circle className="pt-div" data-testid="point-div" cx={at.div!.px} cy={at.div!.py} r={4.5} />
        </g>
        {at.current && (
          <g className="mark" data-mark="current" tabIndex={0} role="img" aria-label={currentLabel} {...show("current")} {...tapToggle("current")}>
            <circle className="hit" cx={at.current.px} cy={at.current.py} r={phone ? HIT : 14} />
            <rect className="pt-current" data-testid="point-current" x={at.current.px - 6.5} y={at.current.py - 6.5} width={13} height={13} rx={2} />
          </g>
        )}
        <g
          className={dragging ? "pt-selected dragging" : "pt-selected"}
          data-testid="point-selected"
          data-mark="selected"
          transform={`translate(${sx},${sy})`}
          tabIndex={0}
          role="slider"
          aria-label={selectedLabel}
          aria-orientation="horizontal"
          aria-valuemin={Number(position.min.toFixed(4))}
          aria-valuemax={Number(position.max.toFixed(4))}
          aria-valuenow={Number(position.s.toFixed(4))}
          aria-valuetext={selectedLabel}
          aria-disabled={busy || undefined}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onLostPointerCapture={endDrag}
          {...show("selected")}
          onKeyDown={onKeyDown}
        >
          <circle className="hit" r={HIT} />
          <circle className="halo" r={16} />
          <circle className="reticle-outer" r={23} />
          <circle className="reticle" r={16} />
          <circle className="dot-back" r={10.5} />
          <circle className="dot" r={8} />
        </g>
      </svg>
      {tip && where && cards[tip] && (
        <div ref={cardRef} className="tooltip" role="tooltip" style={{ left: cardLeft, top: cardTop, width: cardW }}>
          {cards[tip]}
          {tip !== "selected" && under(tip) && cards[under(tip)!] && <p className="tip-more">{phone ? "Tap" : "Click"} again for the marker underneath.</p>}
        </div>
      )}
    </>
  );
}
