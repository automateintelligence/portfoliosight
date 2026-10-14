import type { Tensor } from "../api/tensor";
import { plain, stressGap } from "../copy";
import { signedPct } from "../format";
import { stressReturn } from "../math/portfolio";

type Props = { tensor: Tensor; wSel: number[]; wNow: number[] | null; details: boolean };

const ORDER = ["gfc2008", "covid2020", "rates2022"] as const;

/** Three fixed windows of real history; never a number for a mix that mostly did not exist (spec 4.10). */
export function Stress({ tensor, wSel, wNow, details }: Props) {
  const n = tensor.universe.funds.length;
  return (
    <div className="cards">
      {ORDER.map((id) => {
        const win = tensor.stress[id];
        const sel = stressReturn(wSel, win.r);
        const now = wNow ? stressReturn(wNow, win.r) : null;
        const missing = win.r.filter((v) => v === null).length;
        return (
          <article key={id} className="card" data-testid={`stress-${id}`}>
            <h3 className="heading">{win.label}</h3>
            {sel.value === null ? (
              <p className="big">{plain.stressSentinel}</p>
            ) : (
              <p className="big">
                What this mix did: <b className={`num ${sel.value < 0 ? "neg" : "pos"}`}>{signedPct(sel.value)}</b> ({plain.selectedMix})
              </p>
            )}
            {sel.value !== null && 1 - sel.covered >= 0.0005 && <p>{stressGap(missing, n, ((1 - sel.covered) * 100).toFixed(1))}</p>}
            {now &&
              (now.value === null ? (
                <p>{plain.currentMix}: not enough of it existed then to say.</p>
              ) : (
                <p>
                  <strong className="entered">
                    {plain.currentMix}: <span className="num">{signedPct(now.value)}</span>
                  </strong>
                  {1 - now.covered >= 0.0005 ? " (for the part of it that existed then)" : ""}
                </p>
              ))}
            {details && <p className="tech">{`Buy-and-hold with the selected weights, ${win.start} to ${win.end}`}</p>}
          </article>
        );
      })}
    </div>
  );
}
