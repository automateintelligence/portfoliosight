import type { ReactNode } from "react";
import { enbLine, plain, technical } from "../copy";
import { pct, signedPct } from "../format";

const BELL_Z = 1.96;

export type CardMix = {
  /** Yearly risk and expected return of the mix, and the measure behind the diversification word. */
  sigma: number;
  mu: number;
  enb: number;
  word: string;
  /** Largest holdings, biggest first. */
  holdings: { id: string; w: number }[];
  /** One-year range; left out of the smaller card that follows the pointer over the map, and while an entered mix's range is not known. */
  range?: { low: number; typical: number; high: number };
};

/** The five largest holdings of a mix, biggest first, dropping anything that rounds to nothing. */
export function topHoldings(funds: { id: string }[], weights: ArrayLike<number>, n = 5): { id: string; w: number }[] {
  return funds
    .map((f, i) => ({ id: f.id, w: weights[i] ?? 0 }))
    .sort((a, b) => b.w - a.w)
    .slice(0, n)
    .filter((f) => f.w > 0.0005);
}

type Props = {
  kind: "selected" | "current" | "div" | "cell";
  title: string;
  mix: CardMix;
  details: boolean;
  /** Highest value of the measure found on this menu (details only). */
  enbRef: number;
  /** Extra technical lines (details only). */
  extra?: ReactNode;
};

/** One card for every mix the chart can name: the three markers and the spot under the pointer. */
export function MixCard({ kind, title, mix, details, enbRef, extra }: Props) {
  const lead = mix.holdings[0]?.w || 1;
  return (
    <div className="mixcard" data-testid="mix-card" data-for={kind}>
      <h3>
        <i className={`mk mk-${kind}`} aria-hidden="true" />
        {title}
      </h3>
      {mix.range && (
        <div className="tip-range num">
          <span>
            <small>{plain.rangeLow}</small> {signedPct(mix.range.low)}
          </span>
          <span>
            <small>{plain.rangeTypical}</small> {signedPct(mix.range.typical)}
          </span>
          <span>
            <small>{plain.rangeHigh}</small> {signedPct(mix.range.high)}
          </span>
        </div>
      )}
      {mix.range && <p className="tip-sub">{plain.resultStripSuffix}</p>}
      <dl className="tip-facts">
        <div>
          <dt>{plain.cardRisk}</dt>
          <dd className="num">{pct(mix.sigma)}</dd>
        </div>
        <div>
          <dt>{plain.cardReturn}</dt>
          <dd className="num">{pct(mix.mu)}</dd>
        </div>
        <div>
          <dt>{plain.diversification}</dt>
          <dd data-testid="mix-card-word">{mix.word}</dd>
        </div>
      </dl>
      <p className="tip-sub">{plain.cardPerYear}</p>
      {details && (
        <p className="tip-tech">
          {`This mix ${enbLine(mix.enb.toFixed(1), enbRef.toFixed(1))}.`}
          {` ${technical.bellCurve(signedPct(mix.mu - BELL_Z * mix.sigma), signedPct(mix.mu), signedPct(mix.mu + BELL_Z * mix.sigma))}.`}
          {extra}
        </p>
      )}
      {mix.holdings.length > 0 && (
        <ul aria-label={plain.cardHoldings}>
          {mix.holdings.map((f) => (
            <li key={f.id}>
              <span className="num">{f.id}</span>
              <span className="wbar" style={{ width: `${Math.max(4, (f.w / lead) * 100)}%` }} />
              <span className="num">{pct(f.w)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
