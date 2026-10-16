import { SlidersHorizontal } from "lucide-react";
import { enbLine, plain, rangeBarLabel, staleLine, stripFigure, stripNoPrice, stripOnTotal, technical } from "../copy";
import { dollars, pct, signedDollars, signedPct } from "../format";
import { stripPlace, type StripScale } from "../math/stripScale";
import type { enteredValue } from "../state/store";

export type DetailFacts = {
  enb: number;
  enbRef: number;
  mu: number;
  sigma: number;
  lookbackStart: string;
  lookbackEnd: string;
  rows: number;
  asof: string;
  notes: string[];
  /** Which mix the tensor calls Optimized (spec 4.8). */
  defaultPoint: "balanced" | "peak";
};

type Props = {
  low: number;
  typical: number;
  high: number;
  /** The bell-curve figure, shown in the details only. */
  normal: { low: number; mid: number; high: number };
  /** The bar's fixed scale for this menu and history window (math/stripScale.ts). */
  scale: StripScale;
  /** The value entered (state/store.ts `enteredValue`): dollars when it is known, else percent. */
  value: ReturnType<typeof enteredValue> | null;
  word: string;
  details: boolean;
  facts: DetailFacts;
  staleAsof: string | null;
  /** Phone: the chart's axis and legend technical lines are shown here instead of on the chart. */
  chartNotes?: boolean;
  onToggleDetails: () => void;
};

/** "Selected mix": the one-year range, the quiet diversification word, and the details toggle. */
export function ResultStrip({ low, typical, high, normal, scale, value, word, details, facts, staleAsof, chartNotes = false, onToggleDetails }: Props) {
  // A small picture of the range on one scale for the menu and window: the Bad-to-Good band with
  // its two ends marked, the typical year, and 0%. A figure past an end is drawn at that end with
  // an overflow mark. The bar is always in percent.
  const place = (v: number) => stripPlace(scale, v);
  const at = (v: number) => `${(place(v).at * 100).toFixed(2)}%`;
  const over = (v: number) => place(v).over ?? undefined;
  // In dollars: the one-year change of the selected mix on the value entered, percent beneath.
  const total = value?.status === "usd" ? value.total : null;
  const money = (r: number) => (total === null ? null : signedDollars(total * r));
  const both = (r: number) => (total === null ? signedPct(r) : `${signedPct(r)} (${money(r)})`);
  const spoken = rangeBarLabel(signedPct(scale.lo), signedPct(scale.hi), both(low), both(typical), both(high));
  // Each figure's column is as wide as the widest figure the scale can hold, so the bar beside them
  // keeps its place on screen while the figures change (their font is monospaced). A figure past
  // an end of the scale (rare) can be one character wider. In dollars the group's label speaks
  // both values, so the visible text is hidden from readers to avoid a double read.
  const widest = Math.max(...[scale.lo, scale.hi].map((r) => (total === null ? signedPct(r) : (money(r) as string)).length));
  const width = { minWidth: `${widest}ch` };
  const figure = (id: string, r: number) =>
    total === null ? (
      <span className="fig-val num" data-testid={id} style={width}>
        {signedPct(r)}
      </span>
    ) : (
      <span className={widest >= 11 ? "fig-val num has-usd is-long" : "fig-val num has-usd"} data-testid={id} aria-hidden="true">
        <span className="fig-usd" data-testid={`${id}-usd`} style={width}>
          {money(r)}
        </span>
        <span className="fig-pct" data-testid={`${id}-pct`}>
          {signedPct(r)}
        </span>
      </span>
    );
  const label = (cap: string, r: number) => (total === null ? {} : { role: "group", "aria-label": stripFigure(cap, money(r) as string, signedPct(r)) });

  return (
    <section className={total === null ? "strip" : "strip strip-usd"} aria-label={plain.resultStrip}>
      <div className="strip-label">
        <span className="heading">{plain.resultStrip}</span>
        <span className="sub" data-testid="strip-sub">
          {total === null ? plain.resultStripSuffix : stripOnTotal(dollars(total))}
        </span>
      </div>
      <div className="range">
        <div className="fig" {...label(plain.rangeLow, low)}>
          <span className="fig-cap" aria-hidden={total !== null || undefined}>{plain.rangeLow}</span>
          {figure("range-low", low)}
        </div>
        <div className="fig fig-typ" {...label(plain.rangeTypical, typical)}>
          <span className="fig-cap" aria-hidden={total !== null || undefined}>{plain.rangeTypical}</span>
          {figure("range-typical", typical)}
        </div>
        <div className="fig" {...label(plain.rangeHigh, high)}>
          <span className="fig-cap" aria-hidden={total !== null || undefined}>{plain.rangeHigh}</span>
          {figure("range-high", high)}
        </div>
        <div className="rangebar" data-testid="range-bar" role="img" aria-label={spoken} data-lo={scale.lo.toFixed(6)} data-hi={scale.hi.toFixed(6)}>
          <span className="rb-track" />
          <span className="rb-line" style={{ left: at(low), right: `calc(100% - ${at(high)})` }} />
          <span className="rb-zero" style={{ left: at(0) }} />
          <span className="rb-cap rb-low" data-testid="range-mark-low" data-over={over(low)} title={`${plain.rangeLow} year: ${both(low)}`} style={{ left: at(low) }} />
          <span className="rb-cap rb-high" data-testid="range-mark-high" data-over={over(high)} title={`${plain.rangeHigh} year: ${both(high)}`} style={{ left: at(high) }} />
          <span className="rb-dot" data-testid="range-mark-typical" data-over={over(typical)} title={`${plain.rangeTypical} year: ${both(typical)}`} style={{ left: at(typical) }} />
        </div>
      </div>
      <div className="divword">
        <span className="divword-cap">{plain.diversification}</span>
        <span className="divword-val" data-testid="div-word">
          {word}
        </span>
      </div>
      <button type="button" className="btn details-btn" data-testid="details-toggle" data-keeps-pin="" aria-pressed={details} onClick={onToggleDetails}>
        <SlidersHorizontal size={15} aria-hidden="true" />
        <span>{plain.details}</span>
      </button>
      {staleAsof && (
        <p className="stale" role="status">
          {staleLine(staleAsof)}
        </p>
      )}
      {details && (
        <div className="details-panel">
          <p className="wide" data-testid="details-enb">
            {`This mix ${enbLine(facts.enb.toFixed(1), facts.enbRef.toFixed(1))}.`} <span className="hint">({technical.enbName})</span>
          </p>
          {facts.sigma < 0.01 && <p className="wide">{plain.lowRisk}</p>}
          {chartNotes && (
            <dl className="wide chart-notes" data-testid="details-chart">
              <dt>{plain.chartNotes}</dt>
              <dd>
                <span>
                  {plain.yAxis}: {technical.yAxis}.
                </span>
                <span>
                  {plain.xAxis.split(":")[0]}: {technical.xAxis}.
                </span>
                <span>
                  {plain.heatLegend}: {technical.heatLegend}.
                </span>
              </dd>
            </dl>
          )}
          {value?.status === "unknown_price" && (
            <p className="wide" data-testid="details-no-price">
              {stripNoPrice(value.funds)}
            </p>
          )}
          <dl>
            <dt>Yearly figures for this mix</dt>
            <dd className="num">
              expected return {pct(facts.mu, 2)} · standard deviation {pct(facts.sigma, 2)}
            </dd>
          </dl>
          <dl>
            <dt>One-year range, two ways</dt>
            <dd className="num" data-testid="details-bell">
              from this history: {signedPct(low)} to {signedPct(high)} around {signedPct(typical)} · {technical.bellCurve(signedPct(normal.low), signedPct(normal.mid), signedPct(normal.high))}
            </dd>
          </dl>
          <dl>
            <dt>History used</dt>
            <dd className="num">
              {facts.lookbackStart} to {facts.lookbackEnd} ({facts.rows} trading days) · prices through {facts.asof}
            </dd>
          </dl>
          <dl className="wide">
            <dt>What the diversification word means</dt>
            <dd data-testid="details-words">{technical.cutPoints}</dd>
          </dl>
          <dl className="wide">
            <dt>What “{plain.optimized}” means</dt>
            <dd data-testid="details-suggested">{technical.optimized[facts.defaultPoint]}</dd>
          </dl>
          <p className="wide hint" data-testid="details-method">
            Method. Range: {technical.resultStrip}. The line on the chart: {technical.frontier}. {plain.optimized}: {technical.optimizedMethod[facts.defaultPoint]}.{" "}
            {facts.notes.filter((n) => !/^(the balanced point|one-year ranges)\b/i.test(n)).join(" ")}
          </p>
        </div>
      )}
    </section>
  );
}
