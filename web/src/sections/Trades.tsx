import { plain } from "../copy";
import { pct, signedInt, signedMoney, signedPp } from "../format";
import { tradeDeltas } from "../math/amounts";
import type { Unit } from "../state/store";

type Props = {
  funds: { id: string; last_close?: number | null }[];
  wNow: number[];
  wSel: number[];
  unit: Unit;
  /** Amounts in the tensor's fund order. */
  amounts: (number | null)[];
};

const tone = (v: number) => (v > 0.0005 ? "up" : v < -0.0005 ? "down" : undefined);

/** Moves from the mix you entered to the selected mix, per unit (spec 3.3). */
export function Trades({ funds, wNow, wSel, unit, amounts }: Props) {
  const lastClose = funds.map((f) => f.last_close ?? null);
  const { rows, turnover } = tradeDeltas({ wNow, wSel, unit, amounts, lastClose });
  const cols = unit === "shares" ? 6 : unit === "usd" ? 5 : 4;
  const shown = funds.map((f, i) => ({ f, i })).filter(({ i }) => wNow[i] > 5e-5 || wSel[i] > 5e-4);
  return (
    <div>
      <p className="acc-lead">{plain.trades}</p>
      <div role="list">
        <div className={`trow row-head cols-${cols}`} aria-hidden="true">
          <span>Fund</span>
          <span>Now</span>
          <span>Selected</span>
          <span>Change</span>
          {unit !== "pct" && <span className="wide-only">Change in $</span>}
          {unit === "shares" && <span className="wide-only">Change in shares</span>}
        </div>
        {shown.map(({ f, i }) => (
          <div key={f.id} className={`trow cols-${cols}`} role="listitem">
            <span className="tk num">{f.id}</span>
            <span className="num">{pct(wNow[i])}</span>
            <span className="num">{pct(wSel[i])}</span>
            <span className={`num ${tone(rows[i].dpp) ?? ""}`}>{signedPp(rows[i].dpp)}</span>
            {unit !== "pct" && <span className="num wide-only">{rows[i].dUsd === null ? "—" : signedMoney(rows[i].dUsd as number)}</span>}
            {unit === "shares" && <span className="num wide-only">{rows[i].unknownPrice || rows[i].dShares === null ? "no price" : signedInt(rows[i].dShares as number)}</span>}
          </div>
        ))}
        <div className={`trow trow-total cols-${cols}`}>
          <span>Total moved</span>
          <span />
          <span />
          <span className="num">{pct(turnover)}</span>
        </div>
      </div>
      <p className="hint">“Total moved” is the share of the portfolio that changes hands one way.</p>
    </div>
  );
}
