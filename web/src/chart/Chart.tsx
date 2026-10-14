import { forwardRef, useMemo, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import type { Tensor } from "../api/tensor";
import { lookbackLine, plain, technical } from "../copy";
import { pct, signedPct } from "../format";
import { diversificationWord } from "../math/portfolio";
import type { Range, Stats, View } from "../math/view";
import { Heatmap, NO_LIMITS, type Ghost } from "./Heatmap";
import { MixCard, topHoldings, type CardMix } from "./MixCard";
import { Overlay, type LineEnd, type MarkId } from "./Overlay";
import { X_TITLE_GAP, type ChartScales } from "./scales";

type Props = {
  tensor: Tensor | null;
  view: View | null;
  scales: ChartScales | null;
  ghosts: Ghost[];
  frontierEnb: number[];
  /** The mix the visitor entered: its statistics, one-year range (null while it is not known) and weights. */
  current: { stats: Stats; range: Range | null; weights: number[] } | null;
  details: boolean;
  phone: boolean;
  themeEpoch: number;
  reveal: boolean;
  notice: ReactNode;
  busy: boolean;
  /** The mix computed for cell (j, k) and its actual statistics, or null for an empty cell. */
  cellMix: (j: number, k: number) => { weights: number[]; stats: Stats } | null;
  onRiskPixel: (px: number) => void;
  onDivDrag: (dy: number, start: boolean) => void;
  onNudge: (ds: number, dt: number) => void;
};

const GHOST_REACH = 7; // px from a ghost line within which the pointer names it

/** Squared distance from (px, py) to the segment a-b. */
function segDist2(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const f = len2 > 0 ? Math.min(1, Math.max(0, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0;
  const qx = ax + f * dx - px;
  const qy = ay + f * dy - py;
  return qx * qx + qy * qy;
}

/** What each mark on the chart is. Inside the chart on desktop, a row under it on a phone. */
export function MarkKeys({ hasCurrent, hasGhosts, hasNoLimits, compact = false }: { hasCurrent: boolean; hasGhosts: boolean; hasNoLimits: boolean; compact?: boolean }) {
  return (
      <ul className="keys">
        <li>
          <svg viewBox="0 0 18 12" aria-hidden="true">
            <path d="M1 10 C5 4 10 2.5 17 2" fill="none" stroke="var(--frontier)" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <span>{plain.frontier}</span>
        </li>
        <li>
          <svg viewBox="0 0 18 12" aria-hidden="true">
            <circle cx="9" cy="6" r="4.5" fill="var(--mark-selected-fill)" stroke="var(--mark-selected-ring)" strokeWidth="1.6" />
          </svg>
          <span>{plain.selectedMix}</span>
        </li>
        {hasCurrent && (
          <li>
            <svg viewBox="0 0 18 12" aria-hidden="true">
              <rect x="4.5" y="1.5" width="9" height="9" rx="1.2" fill="none" stroke="var(--mark-current)" strokeWidth="1.8" />
            </svg>
            <span>{plain.currentMix}</span>
          </li>
        )}
        <li>
          <svg viewBox="0 0 18 12" aria-hidden="true">
            <circle cx="9" cy="6" r="4" fill="none" stroke="var(--mark-div)" strokeWidth="1.8" />
          </svg>
          <span>{plain.optimized}</span>
        </li>
        {hasGhosts && (
          <li>
            <svg viewBox="0 0 18 12" aria-hidden="true">
              <path d="M1 10 C5 5 10 3.5 17 3" fill="none" stroke="var(--frontier)" strokeWidth="1.2" strokeDasharray="3 2.5" opacity="0.55" />
            </svg>
            <span>{plain.ghosts}</span>
          </li>
        )}
        {hasNoLimits && (
          <li data-testid="key-nolimits">
            <svg viewBox="0 0 18 12" aria-hidden="true">
              <path d="M1 10 C5 5 10 3.5 17 3" fill="none" stroke="var(--frontier)" strokeWidth="1.2" strokeDasharray="3 2.5" opacity="0.55" />
            </svg>
            <span>{compact ? plain.noLimits : `${plain.noLimits}: ${plain.noLimitsLine.toLowerCase()}`}</span>
          </li>
        )}
      </ul>
  );
}

function Legend({ scales, phone, details, hasCurrent, hasGhosts, hasNoLimits }: { scales: ChartScales; phone: boolean; details: boolean; hasCurrent: boolean; hasGhosts: boolean; hasNoLimits: boolean }) {
  return (
    <div className="legend" style={{ left: scales.plot.left + (phone ? 8 : 18), top: scales.plot.top + (phone ? 0 : 4) }}>
      <p className="legend-title">{plain.heatLegend}</p>
      {details && <p className="legend-tech">{technical.heatLegend}</p>}
      <div className="ramp" aria-hidden="true">
        <span>{plain.heatLess}</span>
        <span className="ramp-bar" style={{ background: "var(--heat-legend)" }} />
        <span>{plain.heatMore}</span>
      </div>
      {!phone && <MarkKeys hasCurrent={hasCurrent} hasGhosts={hasGhosts} hasNoLimits={hasNoLimits} />}
    </div>
  );
}

/** The chart: canvas heatmap and frontier, SVG markers, DOM labels. */
export const Chart = forwardRef<HTMLDivElement, Props>(function Chart(
  { tensor, view, scales, ghosts, frontierEnb, current, details, phone, themeEpoch, reveal, notice, busy, cellMix, onRiskPixel, onDivDrag, onNudge },
  ref,
) {
  const funds = useMemo(
    () => (details && tensor ? tensor.universe.funds.map((f, i) => ({ id: f.id, sigma: tensor.sigma[i], mu: tensor.mu_s[i] })) : null),
    [details, tensor],
  );
  const ready = tensor && view && scales && scales.width > 0;
  // `data-ghost-count` counts the history windows toggled on; the No limits line is not one.
  const lookbackGhosts = ghosts.filter((g) => g.id !== NO_LIMITS).length;

  // Everything right of the ceiling is beyond the chosen risk: that part of the map recedes.
  const dimPath = useMemo(() => {
    if (!tensor || !view || !scales) return "none";
    const curve = tensor.frontier_curve;
    // The map's own bottom edge (half a cell under the lowest return floor), so nothing is dimmed below it.
    const ys = tensor.grid.y;
    const floor = Math.min(scales.plot.bottom, scales.y(ys[0] - (ys.length > 1 ? (ys[1] - ys[0]) / 2 : 0)));
    const x0 = scales.x(view.ceiling);
    const pts: string[] = [`${x0.toFixed(1)}px ${floor.toFixed(1)}px`, `${x0.toFixed(1)}px ${(scales.y(view.ceilingMu) - 2).toFixed(1)}px`];
    let last = x0;
    for (let i = 0; i < curve.sigma.length; i++) {
      if (curve.sigma[i] <= view.ceiling) continue;
      last = scales.x(curve.sigma[i]);
      pts.push(`${last.toFixed(1)}px ${(scales.y(curve.mu[i]) - 2).toFixed(1)}px`);
    }
    pts.push(`${last.toFixed(1)}px ${floor.toFixed(1)}px`);
    return `polygon(${pts.join(", ")})`;
  }, [tensor, view, scales]);

  // Every frontier line is named at its right end by the history it was measured over.
  const lines: LineEnd[] = useMemo(() => {
    if (!tensor) return [];
    const end = (curve: { sigma: number[]; mu: number[] }) => ({ sigma: curve.sigma[curve.sigma.length - 1], mu: curve.mu[curve.mu.length - 1] });
    const name = (id: string) => lookbackLine[id] ?? id;
    return [
      { id: tensor.lookback.id, label: name(tensor.lookback.id), primary: true, ...end(tensor.frontier_curve) },
      ...ghosts.filter((g) => g.curve.sigma.length > 0).map((g) => ({ id: g.id, label: name(g.id), primary: false, ...end(g.curve) })),
    ];
  }, [tensor, ghosts]);
  const ghostPixels = useMemo(
    () => (scales ? ghosts.map((g) => ({ id: g.id, pts: g.curve.sigma.map((sigma, i) => [scales.x(sigma), scales.y(g.curve.mu[i])] as const) })) : []),
    [ghosts, scales],
  );

  // With a mouse, the map names the mix under the pointer, and a ghost line names its history.
  const [cell, setCell] = useState<{ j: number; k: number; px: number; py: number } | null>(null);
  const [ghostAt, setGhostAt] = useState<{ id: string; px: number; py: number } | null>(null);
  const clear = () => {
    setCell(null);
    setGhostAt(null);
  };
  const onHover = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!tensor || !scales || e.pointerType === "touch" || phone) return;
    if (e.buttons !== 0 || (e.target instanceof Element && e.target.closest("[data-mark], .legend, .notice"))) return clear();
    const r = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    let near: { id: string; d2: number } | null = null;
    for (const g of ghostPixels) {
      for (let i = 1; i < g.pts.length; i++) {
        const d2 = segDist2(px, py, g.pts[i - 1][0], g.pts[i - 1][1], g.pts[i][0], g.pts[i][1]);
        if (d2 <= GHOST_REACH * GHOST_REACH && (!near || d2 < near.d2)) near = { id: g.id, d2 };
      }
    }
    if (near) {
      setGhostAt({ id: near.id, px, py });
      return setCell(null);
    }
    setGhostAt(null);
    const xs = tensor.frontier.x;
    const ys = tensor.grid.y;
    const j = Math.round(((scales.x.invert(px) - xs[0]) / (xs[xs.length - 1] - xs[0])) * (xs.length - 1));
    const k = Math.round(((scales.y.invert(py) - ys[0]) / (ys[ys.length - 1] - ys[0])) * (ys.length - 1));
    const inside = j >= 0 && j < xs.length && k >= 0 && k < ys.length && tensor.grid.z[j][k] !== null;
    setCell(inside ? { j, k, px, py } : null);
  };
  const hovered = cell && tensor ? cellMix(cell.j, cell.k) : null;
  const hot = useMemo(() => {
    const g = ghostAt ? ghostPixels.find((p) => p.id === ghostAt.id) : null;
    return g ? { id: g.id, path: g.pts.map(([px, py], i) => `${i === 0 ? "M" : "L"}${px.toFixed(1)} ${py.toFixed(1)}`).join("") } : null;
  }, [ghostAt, ghostPixels]);

  const cardOf = (stats: Stats, weights: ArrayLike<number>, range?: Range): CardMix | null =>
    tensor ? { ...stats, word: diversificationWord(stats.enb / tensor.enb_ref), holdings: topHoldings(tensor.universe.funds, weights), range } : null;
  const spoken = (title: string, range: Range | null, word: string) =>
    range
      ? `${title}: ${plain.rangeLow} ${signedPct(range.low)}, ${plain.rangeTypical} ${signedPct(range.typical)}, ${plain.rangeHigh} ${signedPct(range.high)} ${plain.resultStripSuffix}. ${plain.diversification}: ${word}.`
      : `${title}. ${plain.diversification}: ${word}.`;

  let overlay: ReactNode = null;
  if (ready) {
    const selMix = cardOf(view.selected, view.weights, view.range)!;
    const divMix = cardOf(view.optimized, view.optWeights, view.optRange)!;
    const curMix = current ? cardOf(current.stats, current.weights, current.range ?? undefined) : null;
    const card = (kind: MarkId, title: string, mix: CardMix, extra?: ReactNode) => <MixCard kind={kind} title={title} mix={mix} details={details} enbRef={tensor.enb_ref} extra={extra} />;
    overlay = (
      <Overlay
        scales={scales}
        phone={phone}
        ceiling={{ sigma: view.ceiling, mu: view.ceilingMu }}
        selected={view.selected}
        optimized={view.optimized}
        current={current?.stats ?? null}
        funds={funds}
        selectedLabel={`${plain.selectedMix}: ${plain.rangeLow} ${signedPct(view.range.low)}, ${plain.rangeTypical} ${signedPct(view.range.typical)}, ${plain.rangeHigh} ${signedPct(view.range.high)} ${plain.resultStripSuffix}. Left and right arrows change risk; up and down arrows move between more return and more diversified.`}
        divLabel={spoken(plain.optimized, view.optRange, divMix.word)}
        currentLabel={current && curMix ? spoken(plain.currentMix, current.range, curMix.word) : ""}
        cards={{
          selected: card("selected", plain.selectedMix, selMix),
          div: card("div", plain.optimized, divMix),
          current: curMix ? card("current", plain.currentMix, curMix, current?.range ? undefined : ` ${technical.rangePending}`) : null,
        }}
        lines={lines}
        hot={hot}
        onRiskPixel={onRiskPixel}
        onDivDrag={onDivDrag}
        busy={busy}
        position={{ s: view.s, min: view.domain.s_safe, max: view.domain.s_max }}
        onNudge={onNudge}
      />
    );
  }
  const cellCard = ready && cell && hovered ? cardOf(hovered.stats, hovered.weights) : null;
  const flip = (p: number, size: number, room: number) => (p + 18 + size <= room - 4 ? p + 18 : Math.max(4, p - 18 - size));

  return (
    <div ref={ref} className="chart" data-testid="chart" data-ghost-count={lookbackGhosts} onPointerMove={onHover} onPointerLeave={clear} onPointerDown={clear}>
      {ready && (
        <>
          <Heatmap tensor={tensor} frontierEnb={frontierEnb} ghosts={ghosts} scales={scales} themeEpoch={themeEpoch} reveal={reveal} />
          <div className="dim" aria-hidden="true" style={{ clipPath: dimPath }} />
          <p className="chart-label y-title">
            {plain.yAxis}
            {details && <span className="tech">{technical.yAxis}</span>}
          </p>
          <p className="chart-label x-title" data-testid="x-title" style={{ top: scales.plot.bottom + (phone ? X_TITLE_GAP.phone : X_TITLE_GAP.desktop) }}>
            {plain.xAxis}
            {details && <span className="tech">{technical.xAxis}</span>}
          </p>
          <Legend scales={scales} phone={phone} details={details} hasCurrent={current !== null} hasGhosts={lookbackGhosts > 0} hasNoLimits={ghosts.length > lookbackGhosts} />
          {overlay}
        </>
      )}
      {ready && cell && cellCard && (
        <div className="celltip" role="status" style={{ left: flip(cell.px, 232, scales.width), top: flip(cell.py, details ? 216 : 168, scales.height) }}>
          <MixCard
            kind="cell"
            title={plain.cellMix}
            mix={cellCard}
            details={details}
            enbRef={tensor.enb_ref}
            extra={` ${technical.cellPlace(pct(tensor.frontier.x[cell.j]), pct(tensor.grid.y[cell.k]))}.`}
          />
        </div>
      )}
      {ready && ghostAt && (
        <div className="ghosttip" data-testid="ghost-tip" role="status" style={{ left: Math.min(ghostAt.px + 14, scales.width - 190), top: Math.max(6, ghostAt.py - 46) }}>
          <b>{lookbackLine[ghostAt.id] ?? ghostAt.id}</b>
          <span>{ghostAt.id === NO_LIMITS ? plain.noLimitsLine : plain.ghosts}</span>
          {details && ghostAt.id === NO_LIMITS && <span>{technical.noLimits}</span>}
        </div>
      )}
      {notice}
    </div>
  );
});
