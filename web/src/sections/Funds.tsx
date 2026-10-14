import { Plus, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { SymbolEntry } from "../api/http";
import type { Tensor } from "../api/tensor";
import { plain } from "../copy";
import { amountText, money, parseAmount, pct } from "../format";
import { amountsToWeights, percentTotal } from "../math/amounts";
import { MAX_FUNDS, MIN_FUNDS, type Row, type Unit } from "../state/store";

type Props = {
  rows: Row[];
  unit: Unit;
  tensor: Tensor | null;
  symbols: SymbolEntry[] | null;
  mixStatus: "ok" | "empty" | "invalid_total" | "unknown_price" | "all_set_aside";
  setAside: number | null;
  menuError: string | null;
  busy: boolean;
  /** Weights of the point selected in the chart, in the tensor's fund order. */
  selected: number[] | null;
  onUnit: (unit: Unit) => void;
  onAmount: (id: string, amount: number | null) => void;
  onUseMenu: (rows: Row[]) => void;
  onNeedSymbols: () => void;
};

const UNITS: { id: Unit; label: string; hint: string }[] = [
  { id: "shares", label: "Shares", hint: "Share counts" },
  { id: "pct", label: "%", hint: "Percent of the portfolio" },
  { id: "usd", label: "$", hint: "Dollar amounts" },
];

function AmountInput({ id, value, unit, onCommit }: { id: string; value: number | null; unit: Unit; onCommit: (amount: number | null) => void }) {
  const [text, setText] = useState(amountText(value));
  const [focused, setFocused] = useState(false);
  useEffect(() => {
    if (!focused) setText(amountText(value));
  }, [value, focused]);
  return (
    <input
      className="field num amt"
      inputMode="decimal"
      aria-label={`${id} amount in ${unit === "usd" ? "dollars" : unit === "pct" ? "percent" : "shares"}`}
      placeholder="—"
      value={text}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      onChange={(e) => {
        setText(e.target.value);
        const parsed = parseAmount(e.target.value);
        if (parsed !== null || e.target.value.trim() === "") onCommit(parsed);
      }}
    />
  );
}

const sameIds = (a: Row[], b: Row[]) => a.length === b.length && [...a.map((r) => r.id)].sort().join(",") === [...b.map((r) => r.id)].sort().join(",");

/** Funds & amounts: the menu, the ways to enter it, and the two mixes side by side (spec 3.3). */
export function Funds({ rows, unit, tensor, symbols, mixStatus, setAside, menuError, busy, selected, onUnit, onAmount, onUseMenu, onNeedSymbols }: Props) {
  // Adding or removing funds edits a draft; amounts of the menu in use apply as they are typed.
  const [draft, setDraft] = useState<Row[] | null>(null);
  const [query, setQuery] = useState("");
  const [addError, setAddError] = useState("");
  useEffect(() => setDraft(null), [rows.map((r) => r.id).join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => onNeedSymbols(), [onNeedSymbols]);

  const list = draft ?? rows;
  const excluded = useMemo(() => new Map((tensor?.universe.excluded ?? []).map((e) => [e.id, e.reason])), [tensor]);
  const included = useMemo(() => new Set((tensor?.universe.funds ?? []).map((f) => f.id)), [tensor]);
  const servedIds = useMemo(() => (symbols ? new Set(symbols.map((s) => s.id)) : null), [symbols]);

  const anyAmount = list.some((r) => r.amount !== null);
  const total = percentTotal(list.map((r) => r.amount));
  const pctBlocked = unit === "pct" && anyAmount && !total.ok;
  const countBlocked = list.length < MIN_FUNDS || list.length > MAX_FUNDS;
  const sum = list.reduce((acc, r) => acc + (r.amount ?? 0), 0);

  // The fund list on screen differs from the one plotted: only then is there anything to recalculate.
  const changed = draft !== null;
  const edit = (next: Row[]) => setDraft(sameIds(next, rows) ? null : next);

  // "Mix entered %": the amounts as percentages of what was entered, whatever the unit. Funds
  // this view sets aside are left out, as they are for the square on the chart.
  const lastClose = useMemo(() => new Map((tensor?.universe.funds ?? []).map((f) => [f.id, f.last_close ?? null])), [tensor]);
  const entered = useMemo(() => {
    const counted = list.filter((r) => (changed || !tensor ? !excluded.has(r.id) : included.has(r.id)));
    const res = amountsToWeights(counted.map((r) => r.amount), unit, counted.map((r) => lastClose.get(r.id) ?? null));
    return new Map(res.weights ? counted.map((r, i) => [r.id, res.weights[i]]) : []);
  }, [list, changed, tensor, excluded, included, unit, lastClose]);
  const selectedById = useMemo(() => new Map((tensor && selected ? tensor.universe.funds : []).map((f, i) => [f.id, selected?.[i] ?? 0])), [tensor, selected]);

  const setAmount = (id: string, amount: number | null) => {
    if (draft) setDraft(draft.map((r) => (r.id === id ? { ...r, amount } : r)));
    // Amounts of funds already plotted apply as they are typed, with or without a changed list.
    if (rows.some((r) => r.id === id)) onAmount(id, amount);
  };
  const remove = (id: string) => edit(list.filter((r) => r.id !== id));
  const add = (sym: { id: string; name?: string | null }) => {
    setQuery("");
    if (list.some((r) => r.id === sym.id)) return setAddError(`${sym.id} is already in the menu.`);
    if (list.length >= MAX_FUNDS) return setAddError(`A menu holds at most ${MAX_FUNDS} funds.`);
    setAddError("");
    edit([...list, { id: sym.id, name: sym.name ?? sym.id, amount: rows.find((r) => r.id === sym.id)?.amount ?? null }]);
  };
  const q = query.trim().toLowerCase();
  const matches = q && symbols ? symbols.filter((s) => s.id.toLowerCase().includes(q.replace(/\s+/g, "")) || (s.name ?? "").toLowerCase().includes(q) || s.id.toLowerCase().replace("-", " ").includes(q)).slice(0, 8) : [];
  const tryAddTyped = () => {
    if (!q) return;
    const exact = symbols?.find((s) => s.id.toLowerCase() === q) ?? (matches.length === 1 ? matches[0] : undefined);
    if (exact) add(exact);
    else setAddError(`${query.trim().toUpperCase()} isn't offered: no verified current data for it.`);
  };

  const totalLine =
    unit === "pct"
      ? anyAmount
        ? total.message
        : "No amounts entered: tickers only."
      : anyAmount
        ? unit === "usd"
          ? `${money(sum)} entered`
          : `${sum.toLocaleString("en-US")} shares entered`
        : "No amounts entered: tickers only.";

  return (
    <div>
      <div className="toolbar">
        <div className="seg" data-testid="unit-toggle" role="radiogroup" aria-label="Amounts are in">
          {UNITS.map((u) => (
            <button key={u.id} type="button" role="radio" className="seg-btn" aria-checked={unit === u.id} title={u.hint} onClick={() => onUnit(u.id)}>
              {u.label}
            </button>
          ))}
        </div>
        <span className={pctBlocked ? "err" : "hint"} data-testid="funds-total" role="status">
          {totalLine}
        </span>
      </div>
      <p className="hint" data-testid="funds-hint">
        {plain.fundsAsYouType}
      </p>
      {changed && (
        <div className="recalc" role="status">
          <span>{plain.fundsChanged}</span>
          <button type="button" className="btn btn-primary" data-testid="use-menu" disabled={pctBlocked || countBlocked || busy} onClick={() => onUseMenu(list)}>
            {plain.fundsRecalculate}
          </button>
        </div>
      )}
      {countBlocked && <p className="err">{list.length < MIN_FUNDS ? `A menu needs at least ${MIN_FUNDS} funds.` : `A menu holds at most ${MAX_FUNDS} funds.`}</p>}
      {menuError && (
        <p className="err" role="alert">
          {menuError}
        </p>
      )}
      {mixStatus === "all_set_aside" && <p className="hint">{plain.allSetAside}</p>}
      {mixStatus === "unknown_price" && <p className="hint">A fund with shares entered has no current price, so the mix you entered cannot be valued.</p>}
      {mixStatus === "ok" && setAside !== null && setAside > 0.0005 && (
        <p className="hint">{`${pct(setAside)} of the mix you entered is in funds set aside in this view; the rest is scaled up to 100%.`}</p>
      )}
      <div className="rows" role="list">
        <div className="row row-head" aria-hidden="true">
          <span className="tk">Ticker</span>
          <span className="nm">Fund</span>
          <span className="amt" data-testid="amount-head">
            {unit === "usd" ? "Amount ($)" : unit === "pct" ? "Share (%)" : "Shares (Qty)"}
          </span>
          <span className="pc pc-ent">{plain.colEntered}</span>
          <span className="pc pc-sel">{plain.colSelected}</span>
          <span className="rm" />
        </div>
        {list.map((r) => {
          const reason = excluded.get(r.id) ?? (tensor && !draft && !included.has(r.id) ? "no verified current data" : servedIds && !servedIds.has(r.id) && !included.has(r.id) ? "no verified current data" : null);
          return (
            <div key={r.id} className={reason ? "row is-out" : "row"} role="listitem" data-testid={`fund-row-${r.id}`}>
              <span className="tk">{r.id}</span>
              <span className="nm">
                <span>{r.name}</span>
                {reason && (
                  <span className="note" data-testid="excluded-note">
                    {reason}: not used
                  </span>
                )}
              </span>
              <AmountInput id={r.id} value={r.amount} unit={unit} onCommit={(amount) => setAmount(r.id, amount)} />
              <span className="pc pc-ent num" data-testid={`mix-entered-${r.id}`} data-label={plain.colEntered}>
                {entered.has(r.id) ? pct(entered.get(r.id) ?? 0) : ""}
              </span>
              <span className="pc pc-sel num" data-testid={`mix-selected-${r.id}`} data-label={plain.colSelected}>
                {selectedById.has(r.id) ? pct(selectedById.get(r.id) ?? 0) : "—"}
              </span>
              <button type="button" className="btn btn-icon btn-quiet rm" aria-label={`Remove ${r.id}`} onClick={() => remove(r.id)}>
                <X size={15} aria-hidden="true" />
              </button>
            </div>
          );
        })}
      </div>
      <div className="adder">
        <label className="sr-only" htmlFor="fund-add">
          Add a fund
        </label>
        <input
          id="fund-add"
          className="field"
          data-testid="fund-add"
          placeholder="Add a fund: ticker or name"
          autoComplete="off"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setAddError("");
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") tryAddTyped();
            if (e.key === "Escape") setQuery("");
          }}
        />
        {matches.length > 0 && (
          <ul className="adder-list" role="listbox" aria-label="Matching funds">
            {matches.map((s) => (
              <li key={s.id} role="none">
                <button type="button" role="option" aria-selected="false" className="adder-opt" onClick={() => add(s)}>
                  <span className="tk">
                    <Plus size={12} aria-hidden="true" /> {s.id}
                  </span>
                  <span className="nm">{s.name}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {addError && (
          <p className="err" role="alert">
            {addError}
          </p>
        )}
        <p className="hint">{plain.symbolsHelp}</p>
      </div>
    </div>
  );
}
