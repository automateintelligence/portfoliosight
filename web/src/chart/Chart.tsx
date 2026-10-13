import { forwardRef, useMemo, type ReactNode } from "react";
import type { Tensor } from "../api/tensor";
import { plain, technical } from "../copy";
import { pct, signedPct } from "../format";
import type { View } from "../math/view";
import { Heatmap, type Ghost } from "./Heatmap";
import { Overlay, type Mark } from "./Overlay";
import type { ChartScales } from "./scales";

type Props = {
  tensor: Tensor | null;
  view: View | null;
  scales: ChartScales | null;
  ghosts: Ghost[];
  frontierEnb: number[];
  current: Mark | null;
  details: boolean;
  phone: boolean;
  themeEpoch: number;
  reveal: boolean;
  notice: ReactNode;
  onRiskPixel: (px: number) => void;
  onDivDrag: (dy: number, start: boolean) => void;
  onNudge: (ds: number, dt: number) => void;
};

/** What each mark on the chart is. Inside the chart on desktop, a row under it on a phone. */
export function MarkKeys({ hasCurrent, hasGhosts }: { hasCurrent: boolean; hasGhosts: boolean }) {
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
          <span>{plain.mostDiversified}</span>
        </li>
        {hasGhosts && (
          <li>
            <svg viewBox="0 0 18 12" aria-hidden="true">
              <path d="M1 10 C5 5 10 3.5 17 3" fill="none" stroke="var(--frontier)" strokeWidth="1.2" strokeDasharray="3 2.5" opacity="0.55" />
            </svg>
            <span>{plain.ghosts}</span>
          </li>
        )}
      </ul>
  );
}

function Legend({ scales, phone, details, hasCurrent, hasGhosts }: { scales: ChartScales; phone: boolean; details: boolean; hasCurrent: boolean; hasGhosts: boolean }) {
  return (
    <div className="legend" style={{ left: scales.plot.left + (phone ? 8 : 18), top: scales.plot.top + (phone ? 0 : 4) }}>
      <p className="legend-title">{plain.heatLegend}</p>
      {details && <p className="legend-tech">{technical.heatLegend}</p>}
      <div className="ramp" aria-hidden="true">
        <span>{plain.heatLess}</span>
        <span className="ramp-bar" style={{ background: "linear-gradient(90deg, var(--heat-1), var(--heat-2), var(--heat-3), var(--heat-4))" }} />
        <span>{plain.heatMore}</span>
      </div>
      {!phone && <MarkKeys hasCurrent={hasCurrent} hasGhosts={hasGhosts} />}
    </div>
  );
}

/** The chart: canvas heatmap and frontier, SVG markers, DOM labels. */
export const Chart = forwardRef<HTMLDivElement, Props>(function Chart(
  { tensor, view, scales, ghosts, frontierEnb, current, details, phone, themeEpoch, reveal, notice, onRiskPixel, onDivDrag, onNudge },
  ref,
) {
  const funds = useMemo(
    () => (details && tensor ? tensor.universe.funds.map((f, i) => ({ id: f.id, sigma: tensor.sigma[i], mu: tensor.mu_s[i] })) : null),
    [details, tensor],
  );
  const ready = tensor && view && scales && scales.width > 0;
  const top = useMemo(() => {
    if (!tensor || !view) return [];
    return tensor.universe.funds
      .map((f, i) => ({ id: f.id, w: view.weights[i] }))
      .sort((a, b) => b.w - a.w)
      .slice(0, 5)
      .filter((f) => f.w > 0.0005);
  }, [tensor, view]);

  // Everything right of the ceiling is beyond the chosen risk: that part of the map recedes.
  const dimPath = useMemo(() => {
    if (!tensor || !view || !scales) return "none";
    const curve = tensor.frontier_curve;
    const floor = scales.plot.bottom;
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

  return (
    <div ref={ref} className="chart" data-testid="chart" data-ghost-count={ghosts.length}>
      {ready && (
        <>
          <Heatmap tensor={tensor} frontierEnb={frontierEnb} ghosts={ghosts} scales={scales} themeEpoch={themeEpoch} reveal={reveal} />
          <div className="dim" aria-hidden="true" style={{ clipPath: dimPath }} />
          <p className="chart-label y-title">
            {plain.yAxis}
            {details && <span className="tech">{technical.yAxis}</span>}
          </p>
          <p className="chart-label x-title">
            {plain.xAxis}
            {details && <span className="tech">{technical.xAxis}</span>}
          </p>
          <Legend scales={scales} phone={phone} details={details} hasCurrent={current !== null} hasGhosts={ghosts.length > 0} />
          <Overlay
            scales={scales}
            phone={phone}
            ceiling={{ sigma: view.ceiling, mu: view.ceilingMu }}
            selected={view.selected}
            mostDiversified={view.mostDiversified}
            current={current}
            funds={funds}
            selectedLabel={`${plain.selectedMix}: ${plain.rangeLow} ${signedPct(view.range.low)}, ${plain.rangeTypical} ${signedPct(view.range.typical)}, ${plain.rangeHigh} ${signedPct(view.range.high)} ${plain.resultStripSuffix}. Left and right arrows change risk; up and down arrows move between more return and more diversified.`}
            tooltip={
              <>
                <h3>{plain.selectedMix}</h3>
                <div className="tip-range num">
                  <span>
                    {plain.rangeLow} {signedPct(view.range.low)}
                  </span>
                  <span>
                    {plain.rangeTypical} {signedPct(view.range.typical)}
                  </span>
                  <span>
                    {plain.rangeHigh} {signedPct(view.range.high)}
                  </span>
                </div>
                <p className="tip-line">
                  {plain.diversification}: {view.word}
                </p>
                <p className="tip-line">
                  Risk ceiling <span className="num">{pct(view.ceiling)}</span> · this mix <span className="num">{pct(view.selected.sigma)}</span>
                </p>
                <ul>
                  {top.map((f) => (
                    <li key={f.id}>
                      <span className="num">{f.id}</span>
                      <span className="wbar" style={{ width: `${Math.max(4, (f.w / (top[0]?.w || 1)) * 100)}%` }} />
                      <span className="num">{pct(f.w)}</span>
                    </li>
                  ))}
                </ul>
              </>
            }
            onRiskPixel={onRiskPixel}
            onDivDrag={onDivDrag}
            position={{ s: view.s, min: view.domain.s_safe, max: view.domain.s_max }}
            onNudge={onNudge}
          />
        </>
      )}
      {notice}
    </div>
  );
});
