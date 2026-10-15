import { Share2 } from "lucide-react";
import { useEffect, useId, useState } from "react";
import type { Tensor } from "../api/tensor";
import { adminLine, adminTag, capsRule, lookbackNames, plain, technical } from "../copy";
import { pctPlain } from "../format";
import { LOOKBACKS, type Cap, type LookbackId } from "../state/store";

type Props = {
  tensor: Tensor;
  lookback: LookbackId;
  ghosts: LookbackId[];
  caps: Cap[];
  unavailable: Partial<Record<LookbackId, string>>;
  details: boolean;
  busy: boolean;
  problem: string | null;
  /** Set in admin mode (engines spec 6.2): the menu limit it allows. */
  adminMenuMax: number | null;
  onLookback: (lookback: LookbackId) => void;
  onGhost: (lookback: LookbackId) => void;
  onCaps: (caps: Cap[]) => void;
  onShare: () => void;
};

type Draft = Record<string, { min: string; max: string }>;

/** Default per-fund ceiling: clamp(3/N, 25%, 100%) (spec 4.4). */
export const ruleMax = (n: number) => Math.min(1, Math.max(0.25, 3 / Math.max(1, n)));

const num = (text: string): number | null => {
  const t = text.trim().replace(/%$/, "");
  if (t === "") return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : NaN;
};

/** Spec 4.4 validation over the whole table; returns a message per fund id, or "" for a table-wide one. */
export function validateCaps(ids: string[], draft: Draft, defaultMaxPct: number): Record<string, string> {
  const errors: Record<string, string> = {};
  let sumMin = 0;
  let sumMax = 0;
  for (const id of ids) {
    const lo = num(draft[id]?.min ?? "") ?? 0;
    const hi = num(draft[id]?.max ?? "") ?? defaultMaxPct;
    if (Number.isNaN(lo) || Number.isNaN(hi)) errors[id] = "Enter a percent from 0 to 100.";
    else if (lo < 0 || hi > 100) errors[id] = "Limits run from 0% to 100%.";
    else if (lo > hi) errors[id] = `The minimum (${lo}%) is above the maximum (${hi}%).`;
    else if (!Number.isInteger(lo) || (hi !== defaultMaxPct && !Number.isInteger(hi))) errors[id] = "Use whole percents.";
    sumMin += Number.isNaN(lo) ? 0 : lo;
    sumMax += Number.isNaN(hi) ? 0 : hi;
  }
  if (Object.keys(errors).length === 0) {
    if (sumMin > 100 + 1e-9) errors[""] = `The minimums add up to ${pctPlain(sumMin / 100)}%: they cannot pass 100%.`;
    else if (sumMax < 100 - 1e-9) errors[""] = `The maximums add up to ${pctPlain(sumMax / 100)}%: they must reach 100%.`;
  }
  return errors;
}

export function Settings({ tensor, lookback, ghosts, caps, unavailable, details, busy, problem, adminMenuMax, onLookback, onGhost, onCaps, onShare }: Props) {
  const uid = useId();
  const funds = tensor.universe.funds;
  const ids = funds.map((f) => f.id);
  const defMax = ruleMax(funds.length);
  const defMaxText = pctPlain(defMax, 2);
  const fromCaps = (): Draft => {
    const byId = new Map(caps.map((c) => [c.id, c]));
    return Object.fromEntries(ids.map((id) => [id, { min: String(byId.get(id)?.min ?? 0), max: String(byId.get(id)?.max ?? defMaxText) }]));
  };
  const [draft, setDraft] = useState<Draft>(fromCaps);
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    setDraft(fromCaps());
    setErrors({});
  }, [JSON.stringify(caps), ids.join(","), defMaxText]); // eslint-disable-line react-hooks/exhaustive-deps

  const commit = (next: Draft) => {
    const found = validateCaps(ids, next, Number(defMaxText));
    setErrors(found);
    if (Object.keys(found).length > 0) return; // nothing is sent while the table is invalid
    const overrides: Cap[] = [];
    for (const id of ids) {
      const lo = num(next[id].min) ?? 0;
      const hi = num(next[id].max) ?? Number(defMaxText);
      const min = lo !== 0 ? lo : null;
      const max = hi !== Number(defMaxText) ? hi : null;
      if (min !== null || max !== null) overrides.push({ id, min, max });
    }
    onCaps(overrides);
  };
  // "No limits" is on when every fund may go from 0% to 100%.
  const noLimits = ids.length > 0 && ids.every((id) => caps.some((c) => c.id === id && (c.min ?? 0) === 0 && c.max === 100));
  const edit = (id: string, side: "min" | "max", value: string) => setDraft({ ...draft, [id]: { ...draft[id], [side]: value } });
  const excluded = tensor.universe.excluded ?? [];

  return (
    <div className="set-grid">
      {adminMenuMax !== null && (
        <p className="hint admin-line">
          <span className="admin-tag" data-testid="admin-tag">
            {adminTag}
          </span>
          <span>{adminLine(adminMenuMax)}</span>
        </p>
      )}
      <div className="set-block">
        <h3 className="heading">Years of history</h3>
        <div className="opts" role="radiogroup" aria-label="Years of history">
          {LOOKBACKS.map((id) => {
            const note = unavailable[id];
            return (
              <label key={id} className="opt">
                <input type="radio" name={`${uid}-lb`} data-testid={`lookback-${id}`} checked={lookback === id} disabled={Boolean(note)} onChange={() => onLookback(id)} />
                <span>{lookbackNames[id]}</span>
                {note && <small>{note}</small>}
              </label>
            );
          })}
        </div>
        {excluded.length > 0 && (
          <>
            <p className="hint" style={{ marginTop: 10 }}>
              Set aside in this view:
            </p>
            <ul className="list-plain">
              {excluded.map((e) => (
                <li key={e.id} data-testid="excluded-note">
                  <span className="num">{e.id}</span>: {e.reason}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
      <div className="set-block">
        <h3 className="heading">{plain.ghosts}</h3>
        <div className="opts">
          {LOOKBACKS.filter((id) => id !== lookback).map((id) => (
            <label key={id} className="opt">
              <input type="checkbox" data-testid={`ghost-${id}`} checked={ghosts.includes(id)} disabled={Boolean(unavailable[id])} onChange={() => onGhost(id)} />
              <span>{lookbackNames[id]}</span>
            </label>
          ))}
        </div>
        <p className="hint" style={{ marginTop: 8 }}>
          Each one adds a faint curve to the chart{details ? `. ${technical.ghosts}` : "."}
        </p>
        <h3 className="heading" style={{ marginTop: 18 }}>
          Share this view
        </h3>
        <button type="button" className="btn" onClick={onShare}>
          <Share2 size={15} aria-hidden="true" />
          <span>Copy or email the link</span>
        </button>
      </div>
      <div className="set-block" style={{ gridColumn: "1 / -1" }}>
        <h3 className="heading">Limits per fund</h3>
        <p className="acc-lead">
          {capsRule(pctPlain(defMax), funds.length)}. A small menu gets a higher ceiling, so it stays usable; change any limit below.
          {details ? ` ${technical.caps}.` : ""}
        </p>
        {problem && (
          <p className="err" role="alert">
            {problem}
          </p>
        )}
        {errors[""] && (
          <p className="err" role="alert">
            {errors[""]}
          </p>
        )}
        <div className="caps">
          {ids.map((id) => {
            const errId = `${uid}-cap-${id}`;
            const bad = Boolean(errors[id]);
            return (
              <div key={id} className="cap-row">
                <span className="tk num">{id}</span>
                <label>
                  min %
                  <input
                    className="field num"
                    inputMode="decimal"
                    data-testid={`cap-min-${id}`}
                    aria-label={`${id} minimum percent`}
                    aria-invalid={bad || undefined}
                    aria-describedby={bad ? errId : undefined}
                    value={draft[id]?.min ?? ""}
                    onChange={(e) => edit(id, "min", e.target.value)}
                    onBlur={() => commit(draft)}
                  />
                </label>
                <label>
                  max %
                  <input
                    className="field num"
                    inputMode="decimal"
                    data-testid={`cap-max-${id}`}
                    aria-label={`${id} maximum percent`}
                    aria-invalid={bad || undefined}
                    aria-describedby={bad ? errId : undefined}
                    value={draft[id]?.max ?? ""}
                    onChange={(e) => edit(id, "max", e.target.value)}
                    onBlur={() => commit(draft)}
                  />
                </label>
                {bad && (
                  <span id={errId} className="err" role="alert">
                    {errors[id]}
                  </span>
                )}
              </div>
            );
          })}
        </div>
        <div className="toolbar" style={{ marginTop: 12, marginBottom: 0 }}>
          {/* every fund allowed from 0% to 100%: the menu's frontier with no limit on any one fund */}
          <button type="button" className="btn" data-testid="caps-none" disabled={busy || noLimits} aria-pressed={noLimits} onClick={() => onCaps(ids.map((id) => ({ id, min: null, max: 100 })))}>
            {plain.noLimits}
          </button>
          <button type="button" className="btn" data-testid="caps-reset" disabled={busy} onClick={() => onCaps([])}>
            {plain.resetLimits}
          </button>
        </div>
      </div>
    </div>
  );
}
