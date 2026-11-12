import { Download, Eraser, Percent, Plus, Upload, X } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { SymbolEntry } from "../api/http";
import type { Tensor } from "../api/tensor";
import { TICKER_SHAPE, type TickerSource } from "../api/tickerShape";
import { fundsTotal, fundsUpTo, menuFull, menuNeedsMore, plain, uploadCatalogLoading, uploadSkipped, uploadTooBig, uploadUnreadable } from "../copy";
import { amountText, money, parseAmount, pct } from "../format";
import { amountsToWeights, fundsWithPrices, percentShown, percentTotal, scaleTo100 } from "../math/amounts";
import { MIN_FUNDS, type Row, type Unit, type UploadReport } from "../state/store";
import { MAX_FILE_BYTES, parseFundsCsv, resolveUpload, TEMPLATE_CSV, TEMPLATE_FILENAME } from "./fundsCsv";
import { readSort, SORT_KEYS, sortFunds, writeSort, type SortKey } from "./fundsSort";
import { matchGroup, rankSymbols } from "./symbolSearch";
import { downloadCsv } from "./tradesCsv";

type Props = {
  rows: Row[];
  unit: Unit;
  tensor: Tensor | null;
  symbols: SymbolEntry[] | null;
  mixStatus: "ok" | "empty" | "invalid_total" | "unknown_price" | "all_set_aside";
  setAside: number | null;
  menuError: string | null;
  busy: boolean;
  /** The most funds a menu may hold for this browser's access tier (engines spec 6.2). */
  menuMax: number;
  /** Weights of the point selected in the chart, in the tensor's fund order. */
  selected: number[] | null;
  /** What the last CSV upload has to say (refusal, tickers left out, notes), until dismissed. */
  upload: UploadReport | null;
  /** A slider or the chart's point is being dragged, or a key is held on one: the order of the rows holds still. */
  interacting?: boolean;
  onUnit: (unit: Unit) => void;
  onAmount: (id: string, amount: number | null) => void;
  /** A fund list to use, with the unit its amounts are in when that is not the page's own. */
  onUseMenu: (rows: Row[], unit?: Unit) => void;
  onNeedSymbols: () => void;
  onUpload: (report: UploadReport) => void;
  onDismissUpload: () => void;
  /** Tickers the site does not serve that someone asked for (a CSV file, or typed into the picker). */
  onRequestTickers: (tickers: string[], source: TickerSource) => void;
};

/** The "Sort by" choices in the order they are offered. */
const SORT_LABEL: Record<SortKey, string> = {
  entered: plain.sortEntered,
  ticker: plain.sortTicker,
  name: plain.sortName,
  amount: plain.sortAmount,
  mixEntered: plain.colEntered,
  mixSelected: plain.colSelected,
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
export function Funds({ rows, unit: pageUnit, tensor, symbols, mixStatus, setAside, menuError, busy, menuMax, selected, upload, interacting = false, onUnit, onAmount, onUseMenu, onNeedSymbols, onUpload, onDismissUpload, onRequestTickers }: Props) {
  // Adding or removing funds edits a draft; amounts of the menu in use apply as they are typed.
  const [draft, setDraft] = useState<Row[] | null>(null);
  // A file's list comes with the unit of its amounts. The page's menu keeps its own unit until the
  // list is used, so the amounts of the menu on screen are never read in another unit meanwhile.
  const [draftUnit, setDraftUnit] = useState<Unit | null>(null);
  const [query, setQuery] = useState("");
  const [addError, setAddError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    setDraft(null);
    setDraftUnit(null);
  }, [rows.map((r) => r.id).join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => onNeedSymbols(), [onNeedSymbols]);
  const unit = draft !== null && draftUnit !== null ? draftUnit : pageUnit;
  const changeUnit = (next: Unit) => (draft !== null && draftUnit !== null ? setDraftUnit(next) : onUnit(next));
  // Amounts of funds already plotted normally apply to the page as they are typed; while the draft's
  // unit is not the page's they stay in the draft, or the plotted menu would read them in the wrong unit.
  const unitPending = unit !== pageUnit;

  const list = draft ?? rows;
  const excluded = useMemo(() => new Map((tensor?.universe.excluded ?? []).map((e) => [e.id, e.reason])), [tensor]);
  const included = useMemo(() => new Set((tensor?.universe.funds ?? []).map((f) => f.id)), [tensor]);
  const servedIds = useMemo(() => (symbols ? new Set(symbols.map((s) => s.id)) : null), [symbols]);

  const anyAmount = list.some((r) => r.amount !== null);
  const total = percentTotal(list.map((r) => r.amount));
  const pctBlocked = unit === "pct" && anyAmount && !total.ok;
  const countBlocked = list.length < MIN_FUNDS || list.length > menuMax;
  const sum = list.reduce((acc, r) => acc + (r.amount ?? 0), 0);

  // The fund list on screen differs from the one plotted: only then is there anything to recalculate.
  const changed = draft !== null;
  const edit = (next: Row[]) => {
    const same = sameIds(next, rows);
    setDraft(same ? null : next);
    if (same) setDraftUnit(null);
  };

  // "Mix entered %": the amounts as percentages of what was entered, whatever the unit. Funds
  // this view sets aside are left out, as they are for the square on the chart.
  const lastClose = useMemo(() => new Map((tensor?.universe.funds ?? []).map((f) => [f.id, f.last_close ?? null])), [tensor]);
  const entered = useMemo(() => {
    // Percentages must add up over the whole list (the rule of the running total); what is left
    // after funds are set aside is then scaled up to 100%, as it is for the square on the chart.
    if (unit === "pct" && !percentTotal(list.map((r) => r.amount)).ok) return new Map<string, number>();
    const counted = list.filter((r) => (changed || !tensor ? !excluded.has(r.id) : included.has(r.id)));
    // shares of an uploaded file with dollars are valued at its own prices, as the chart's square and Trades value them
    const priced = fundsWithPrices(counted.map((r) => ({ id: r.id, last_close: lastClose.get(r.id) ?? null })), counted);
    const res = amountsToWeights(counted.map((r) => r.amount), unit === "shares" ? "shares" : "usd", priced.map((f) => f.last_close ?? null));
    return new Map(res.weights ? counted.map((r, i) => [r.id, res.weights[i]]) : []);
  }, [list, changed, tensor, excluded, included, unit, lastClose]);
  const selectedById = useMemo(() => new Map((tensor && selected ? tensor.universe.funds : []).map((f, i) => [f.id, selected?.[i] ?? 0])), [tensor, selected]);

  // "Sort by" (owner direction 2026-11-11). The order on screen is the last one committed. It is
  // recomputed whenever nothing is in use, and held while a slider, the chart's point or a key on
  // one is in use (`interacting`) or focus is inside the rows (an amount field, a Remove button, and
  // the Tab between them), so a row never moves under the visitor's hand; the numbers in the rows
  // keep updating in place. Changing the sort, adding or removing a fund put the list in order at once.
  const [sortKey, setSortKey] = useState<SortKey>(readSort);
  const [focusInRows, setFocusInRows] = useState(false);
  const rowsRef = useRef<HTMLDivElement>(null);
  // A focused element that leaves the page (its row removed) sends no blur: the flag is only as good
  // as where focus actually is after each render.
  useLayoutEffect(() => {
    if (focusInRows && !rowsRef.current?.contains(document.activeElement)) setFocusInRows(false);
  });
  const [committed, setCommitted] = useState<{ key: SortKey; ids: string[] }>({ key: sortKey, ids: [] });
  const wanted = (): string[] => sortFunds(list, sortKey, { entered, selected: selectedById }).map((r) => r.id);
  const committedIds = new Set(committed.ids);
  const sameFunds = committedIds.size === list.length && list.every((r) => committedIds.has(r.id));
  const holding = sortKey !== "entered" && (interacting || focusInRows) && committed.key === sortKey && sameFunds;
  const orderedIds = holding ? committed.ids : wanted();
  if (!holding && (committed.key !== sortKey || orderedIds.join(",") !== committed.ids.join(","))) setCommitted({ key: sortKey, ids: orderedIds });
  const byId = new Map(list.map((r) => [r.id, r]));
  const ordered = orderedIds.map((id) => byId.get(id)!);
  const chooseSort = (next: SortKey) => {
    setSortKey(next);
    writeSort(next);
  };

  const setAmount = (id: string, amount: number | null) => {
    if (draft) setDraft(draft.map((r) => (r.id === id ? { ...r, amount } : r)));
    // Amounts of funds already plotted apply as they are typed, with or without a changed list.
    if (!unitPending && rows.some((r) => r.id === id)) onAmount(id, amount);
  };
  const remove = (id: string) => edit(list.filter((r) => r.id !== id));
  const add = (sym: { id: string; name?: string | null }) => {
    setQuery("");
    if (list.some((r) => r.id === sym.id)) return setAddError(`${sym.id} is already in the portfolio.`);
    if (list.length >= menuMax) return setAddError(menuFull(menuMax));
    setAddError("");
    const plotted = rows.find((r) => r.id === sym.id);
    edit([...list, { id: sym.id, name: sym.name ?? sym.id, amount: plotted?.amount ?? null, ...(plotted?.price === undefined ? {} : { price: plotted.price }) }]);
  };
  const q = query.trim().toLowerCase();
  const matches = useMemo(() => (q && symbols ? rankSymbols(symbols, q) : []), [q, symbols]);
  // In the sidebar the list can open below its visible part: bring the whole list into view.
  const listRef = useRef<HTMLUListElement>(null);
  const listOpen = matches.length > 0;
  useEffect(() => {
    if (listOpen) listRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [listOpen, matches.length]);
  const tryAddTyped = () => {
    if (!q) return;
    const exact = (matches[0] && matchGroup(matches[0], q) === 1 ? matches[0] : undefined) ?? (matches.length === 1 ? matches[0] : undefined);
    if (exact) return add(exact);
    const typed = query.trim().toUpperCase();
    setAddError(`${typed} isn't offered: no verified current data for it.`);
    // Committed (not merely typed), shaped like a ticker and matching nothing served: someone wants a ticker we do not have.
    if (symbols !== null && matches.length === 0 && TICKER_SHAPE.test(typed)) onRequestTickers([typed], "picker");
  };

  /** A CSV file replaces the fund list: the draft, as adding funds makes it, with the file's amounts and unit. */
  const loadFile = async (file: File) => {
    const refuse = (error: string, skipped: string[] = []) => {
      onUpload({ error, skipped, notes: [], pending: [], menu: [] });
      if (skipped.length > 0) onRequestTickers(skipped, "csv");
    };
    setQuery("");
    setAddError("");
    if (file.size > MAX_FILE_BYTES) return refuse(uploadTooBig);
    if (symbols === null) return refuse(uploadCatalogLoading);
    let text: string;
    try {
      text = await file.text();
    } catch {
      return refuse(uploadUnreadable);
    }
    const parsed = parseFundsCsv(text);
    if (!parsed.ok) return refuse(parsed.error);
    const resolved = resolveUpload(parsed.lines, symbols, { min: MIN_FUNDS, max: menuMax });
    if (!resolved.ok) return refuse(resolved.error, resolved.skipped);
    const { plan } = resolved;
    const fileRows = plan.rows.map((r) => (plan.prices[r.id] === undefined ? r : { ...r, price: plan.prices[r.id] }));
    if (sameIds(fileRows, rows)) {
      // the funds on screen already: nothing to recalculate, so the amounts and their unit apply now
      setDraft(null);
      setDraftUnit(null);
      onUseMenu(fileRows, plan.unit ?? undefined);
    } else {
      setDraft(fileRows);
      setDraftUnit(plan.unit);
    }
    onUpload({ error: null, skipped: plan.skipped, notes: plan.notes, pending: plan.pending, menu: plan.rows.map((r) => r.id) });
    if (plan.skipped.length > 0) onRequestTickers(plan.skipped, "csv");
  };

  // In %, while the entries are not exactly 100% as the fields show them, the running total and
  // the button that scales them there appear together; otherwise neither does.
  const shown = percentShown(list.map((r) => r.amount));
  const offTotal = unit === "pct" && shown.entered && !shown.exact;
  const gap = Math.round(Math.abs(100 - shown.total) * 100) / 100;
  const enteredLine = !anyAmount
    ? plain.fundsNone
    : unit === "usd"
      ? `${money(sum)} entered`
      : unit === "shares"
        ? `${sum.toLocaleString("en-US")} shares entered`
        : null;
  // Both act on every fund in the list on screen, as typing into each field would.
  const setAll = (next: (number | null)[]) => {
    if (draft) setDraft(draft.map((r, i) => ({ ...r, amount: next[i] })));
    list.forEach((r, i) => {
      if (!unitPending && next[i] !== r.amount && rows.some((p) => p.id === r.id)) onAmount(r.id, next[i]);
    });
  };
  // Each button goes away (Scale) or turns off (Clear all) once used, so keyboard focus moves on to
  // a control that stays: Clear all after scaling, the first amount after clearing.
  const clearRef = useRef<HTMLButtonElement>(null);
  const clearAll = () => {
    setAll(list.map(() => null));
    // after the emptied fields have rendered: a focused field keeps the text it had
    requestAnimationFrame(() => rowsRef.current?.querySelector<HTMLInputElement>("input.amt")?.focus());
  };
  const scaleAll = () => {
    clearRef.current?.focus();
    setAll(scaleTo100(list.map((r) => r.amount)));
  };

  return (
    <div>
      <div className="toolbar">
        <div className="seg" data-testid="unit-toggle" role="radiogroup" aria-label="Amounts are in">
          {UNITS.map((u) => (
            <button key={u.id} type="button" role="radio" className="seg-btn" aria-checked={unit === u.id} title={u.hint} onClick={() => changeUnit(u.id)}>
              {u.label}
            </button>
          ))}
        </div>
        {/* One live region, always mounted, so a reader hears the total as soon as it appears. */}
        <span className="funds-live" role="status">
          {offTotal && (
            <span className="funds-total" data-testid="funds-total">
              {fundsTotal(String(shown.total), String(gap), shown.total > 100)}
            </span>
          )}
          {enteredLine && (
            <span className="hint" data-testid="funds-entered">
              {enteredLine}
            </span>
          )}
        </span>
        {offTotal && (
          <button type="button" className="btn" data-testid="funds-scale100" title={plain.fundsScaleHint} aria-label={`${plain.fundsScale}: ${plain.fundsScaleHint.toLowerCase()}`} onClick={scaleAll}>
            <Percent size={14} aria-hidden="true" />
            <span>{plain.fundsScale}</span>
          </button>
        )}
        <span className="spacer" />
        <label className="funds-sort">
          <span>{plain.fundsSort}</span>
          <select className="field" data-testid="funds-sort" value={sortKey} onChange={(e) => chooseSort(e.target.value as SortKey)}>
            {SORT_KEYS.map((k) => (
              <option key={k} value={k}>
                {SORT_LABEL[k]}
              </option>
            ))}
          </select>
        </label>
        <button ref={clearRef} type="button" className="btn btn-quiet" data-testid="funds-clear" title={plain.fundsClearHint} aria-label={`${plain.fundsClear}: ${plain.fundsClearHint.toLowerCase()}`} disabled={!anyAmount} onClick={clearAll}>
          <Eraser size={14} aria-hidden="true" />
          <span>{plain.fundsClear}</span>
        </button>
      </div>
      <p className="hint" data-testid="funds-hint">
        {plain.fundsAsYouType}
      </p>
      <p className="hint" data-testid="mix-means">
        {plain.mixMeans}
      </p>
      {changed && (
        <div className="recalc" role="status">
          <span>{plain.fundsChanged}</span>
          <button type="button" className="btn btn-primary" data-testid="use-menu" disabled={pctBlocked || countBlocked || busy} onClick={() => onUseMenu(list, draftUnit ?? undefined)}>
            {plain.fundsRecalculate}
          </button>
        </div>
      )}
      {countBlocked && <p className="err">{list.length < MIN_FUNDS ? menuNeedsMore(MIN_FUNDS) : menuFull(menuMax)}</p>}
      {menuError && (
        <p className="err" role="alert">
          {menuError}
        </p>
      )}
      {mixStatus === "all_set_aside" && <p className="hint">{plain.allSetAside}</p>}
      {mixStatus === "unknown_price" && <p className="hint">A fund with shares entered has no current price, so your starting mix cannot be valued.</p>}
      {mixStatus === "ok" && setAside !== null && setAside > 0.0005 && (
        <p className="hint">{`${pct(setAside)} of your starting mix is in funds set aside in this view; the rest is scaled up to 100%.`}</p>
      )}
      <div
        className="rows"
        role="list"
        ref={rowsRef}
        onFocus={() => setFocusInRows(true)}
        // focus moving within the rows (field to Remove button to the next field) is still inside them
        onBlur={(e) => !(e.relatedTarget instanceof Node && e.currentTarget.contains(e.relatedTarget)) && setFocusInRows(false)}
      >
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
        {ordered.map((r) => {
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
              <span className="pc pc-ent num" data-label={plain.colEntered}>
                <span className="sr-only">{`${plain.colEntered}: `}</span>
                <span data-testid={`mix-entered-${r.id}`}>{entered.has(r.id) ? pct(entered.get(r.id) ?? 0) : ""}</span>
              </span>
              <span className="pc pc-sel num" data-label={plain.colSelected}>
                <span className="sr-only">{`${plain.colSelected}: `}</span>
                <span data-testid={`mix-selected-${r.id}`}>{selectedById.has(r.id) ? pct(selectedById.get(r.id) ?? 0) : "—"}</span>
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
          <ul ref={listRef} className="adder-list" role="listbox" aria-label="Matching funds">
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
        <p className="hint" data-testid="funds-limit">{`${fundsUpTo(menuMax)} ${plain.symbolsHelp}`}</p>
      </div>
      <div className="toolbar file-tools">
        <button type="button" className="btn btn-quiet" data-testid="funds-template" title={plain.fundsTemplateHint} aria-label={`${plain.fundsTemplate}: ${plain.fundsTemplateHint.toLowerCase()}`} onClick={() => downloadCsv(TEMPLATE_CSV, TEMPLATE_FILENAME)}>
          <Download size={14} aria-hidden="true" />
          <span>{plain.fundsTemplate}</span>
        </button>
        <button type="button" className="btn btn-quiet" data-testid="funds-upload" title={plain.fundsUploadHint} aria-label={`${plain.fundsUpload}: ${plain.fundsUploadHint.toLowerCase()}`} onClick={() => fileRef.current?.click()}>
          <Upload size={14} aria-hidden="true" />
          <span>{plain.fundsUpload}</span>
        </button>
        <input
          ref={fileRef}
          type="file"
          hidden
          accept=".csv,text/csv"
          data-testid="funds-file"
          onChange={(e) => {
            const file = e.target.files?.[0];
            // cleared so choosing the same file again is a change again
            e.target.value = "";
            if (file) void loadFile(file);
          }}
        />
      </div>
      <p className="hint" data-testid="funds-upload-hint">
        {plain.fundsUploadPrivacy}
      </p>
      {upload && (upload.error !== null || upload.skipped.length > 0 || upload.notes.length > 0) && (
        <div className="upload-report" data-testid="upload-report">
          <div className="upload-report-body">
            {upload.error !== null && (
              <p className="err" role="alert" data-testid="upload-error">
                {upload.error}
              </p>
            )}
            {upload.skipped.length > 0 && (
              <p role="status" data-testid="upload-skipped">
                {uploadSkipped(upload.skipped)}
              </p>
            )}
            {upload.notes.length > 0 && (
              <div className="upload-notes" role="status" data-testid="upload-mismatch">
                {upload.notes.map((note) => (
                  <p key={note}>{note}</p>
                ))}
              </div>
            )}
          </div>
          <button type="button" className="btn btn-quiet" data-testid="upload-dismiss" onClick={onDismissUpload}>
            {plain.uploadDismiss}
          </button>
        </div>
      )}
    </div>
  );
}
