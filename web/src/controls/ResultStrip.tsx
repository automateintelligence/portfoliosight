import { SlidersHorizontal } from "lucide-react";
import { enbLine, plain, staleLine, technical } from "../copy";
import { pct, signedPct } from "../format";

export type DetailFacts = {
  enb: number;
  enbRef: number;
  mu: number;
  sigma: number;
  ceiling: number;
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
  word: string;
  details: boolean;
  facts: DetailFacts;
  staleAsof: string | null;
  onToggleDetails: () => void;
};

/** "Selected mix": the one-year range, the quiet diversification word, and the details toggle. */
export function ResultStrip({ low, typical, high, normal, word, details, facts, staleAsof, onToggleDetails }: Props) {
  // A small picture of the range: where low, typical and high sit around zero.
  const lo = Math.min(low, 0);
  const hi = Math.max(high, 0);
  const span = hi - lo || 1;
  const at = (v: number) => `${(((v - lo) / span) * 100).toFixed(2)}%`;

  return (
    <section className="strip" aria-label={plain.resultStrip}>
      <div className="strip-label">
        <span className="heading">{plain.resultStrip}</span>
        <span className="sub">{plain.resultStripSuffix}</span>
      </div>
      <div className="range">
        <div className="fig">
          <span className="fig-cap">{plain.rangeLow}</span>
          <span className="fig-val num" data-testid="range-low">
            {signedPct(low)}
          </span>
        </div>
        <div className="fig fig-typ">
          <span className="fig-cap">{plain.rangeTypical}</span>
          <span className="fig-val num" data-testid="range-typical">
            {signedPct(typical)}
          </span>
        </div>
        <div className="fig">
          <span className="fig-cap">{plain.rangeHigh}</span>
          <span className="fig-val num" data-testid="range-high">
            {signedPct(high)}
          </span>
        </div>
        <div className="rangebar" aria-hidden="true">
          <span className="rb-line" style={{ left: at(low), right: `calc(100% - ${at(high)})` }} />
          <span className="rb-zero" style={{ left: at(0) }} />
          <span className="rb-dot" style={{ left: at(typical) }} />
        </div>
      </div>
      <div className="divword">
        <span className="divword-cap">{plain.diversification}</span>
        <span className="divword-val" data-testid="div-word">
          {word}
        </span>
      </div>
      <button type="button" className="btn details-btn" data-testid="details-toggle" aria-pressed={details} onClick={onToggleDetails}>
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
          <dl>
            <dt>Yearly figures for this mix</dt>
            <dd className="num">
              expected return {pct(facts.mu, 2)} · standard deviation {pct(facts.sigma, 2)} · risk ceiling {pct(facts.ceiling, 2)}
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
