import { BarChart3, ChevronDown, ExternalLink, ListChecks, PanelRightClose, PanelRightOpen, Settings as SettingsIcon, Share2, ArrowLeftRight } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { Chart, MarkKeys } from "./chart/Chart";
import { NO_LIMITS } from "./chart/Heatmap";
import { clipCurve, DESKTOP_MARGINS, makeScales, paddedExtent, type ChartScales } from "./chart/scales";
import { DivSlider } from "./controls/DivSlider";
import { PresetMenu } from "./controls/PresetMenu";
import { ResultStrip } from "./controls/ResultStrip";
import { RiskSlider } from "./controls/RiskSlider";
import { ShareDialog } from "./controls/ShareDialog";
import { ThemeSwitch } from "./controls/ThemeSwitch";
import { disclaimer, family, lookbackLine, lookbackNames, plain } from "./copy";
import { portfolioMath, type YearRange } from "./math/portfolio";
import { stripScale } from "./math/stripScale";
import { atNode, ceilingAt, deriveView, limitsBind, positionOfCeiling } from "./math/view";
import { Funds } from "./sections/Funds";
import { Settings } from "./sections/Settings";
import { Stress } from "./sections/Stress";
import { Trades } from "./sections/Trades";
import { createStore, currentMix, LOOKBACKS, type LookbackId } from "./state/store";
import { useExactRange } from "./state/useExactRange";
import { useStripBounds } from "./state/useStripBounds";
import { applyTheme, useMediaQuery, useThemeEpoch } from "./theme/useTheme";

type SectionId = "funds" | "trades" | "stress" | "settings";
const SECTION_ICON = { funds: ListChecks, trades: ArrowLeftRight, stress: BarChart3, settings: SettingsIcon } as const;

function useSize(): [React.RefObject<HTMLDivElement | null>, { width: number; height: number }] {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      setSize((prev) => (prev.width === w && prev.height === h ? prev : { width: w, height: h }));
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size];
}

const SIDE_KEY = "ps.funds";
/** Whether the Funds sidebar was left open in this browser (closed unless it says so). */
function storedSide(): boolean {
  try {
    return globalThis.localStorage?.getItem(SIDE_KEY) === "open";
  } catch {
    return false;
  }
}

function Wordmark() {
  return (
    <h1 className="wordmark">
      <svg className="wordmark-glyph" viewBox="0 0 24 24" aria-hidden="true">
        <path className="g-fill" d="M3 21 C6 11 12 6 21 5 L21 21 Z" />
        <path className="g-curve" d="M3 21 C6 11 12 6 21 5" />
        <circle className="g-dot" cx="10.4" cy="10.6" r="2.7" />
      </svg>
      <span>{plain.wordmark}</span>
    </h1>
  );
}

function Accordion({ id, title, open, onToggle, children }: { id: SectionId; title: string; open: boolean; onToggle: () => void; children: ReactNode }) {
  return (
    <section className="acc" id={`section-${id}`} data-testid={`section-${id}`} aria-expanded={open}>
      <button type="button" className="acc-head" aria-expanded={open} aria-controls={`section-${id}-body`} onClick={onToggle}>
        <span className="heading">{title}</span>
        <ChevronDown className="chev" size={18} aria-hidden="true" />
      </button>
      {open && (
        <div className="acc-body" id={`section-${id}-body`}>
          {children}
        </div>
      )}
    </section>
  );
}

export default function App() {
  const store = useMemo(() => {
    const created = createStore({ search: typeof window !== "undefined" ? window.location.search : "" });
    applyTheme(created.getState().theme);
    return created;
  }, []);
  const state = useSyncExternalStore(store.subscribe, store.getState, store.getState);
  const dispatch = store.dispatch;
  useEffect(() => dispatch({ type: "start" }), [dispatch]);

  const phone = useMediaQuery("(max-width: 768px)");
  // From 1024 px up, Funds & amounts is a sidebar beside the chart; below that, a section under it.
  const wide = useMediaQuery("(min-width: 1024px)");
  const [sideOpen, setSideOpenState] = useState(storedSide);
  const setSideOpen = useCallback((next: boolean) => {
    setSideOpenState(next);
    try {
      globalThis.localStorage?.setItem(SIDE_KEY, next ? "open" : "closed");
    } catch {
      // storage unavailable: the sidebar simply starts closed next time
    }
  }, []);
  const themeEpoch = useThemeEpoch(state.theme);
  const [chartRef, size] = useSize();
  const [open, setOpen] = useState<Record<SectionId, boolean>>({ funds: false, trades: false, stress: false, settings: false });
  const [scrollTo, setScrollTo] = useState<{ id: SectionId; n: number } | null>(null);
  const [share, setShare] = useState<string | null>(null);

  const { tensor } = state;
  const math = useMemo(() => (tensor ? portfolioMath(tensor) : null), [tensor]);
  const nodeView = useMemo(() => (tensor && math ? deriveView(tensor, math, state.s, state.t) : null), [tensor, math, state.s, state.t]);
  const rangeKey = useMemo(() => (tensor ? { generation: tensor.generation, hash: tensor.universe.hash, lookback: tensor.lookback.id } : null), [tensor]);
  // The selected mix's exact one-year range comes from the service once the sliders rest; at a
  // column's level the tensor's own figure is already exact, so nothing is asked.
  const selectedExact = useExactRange(rangeKey, tensor && nodeView && !atNode(tensor, nodeView.s, nodeView.t) ? nodeView.weights : null);
  const view = useMemo(() => (nodeView && selectedExact ? { ...nodeView, range: selectedExact } : nodeView), [nodeView, selectedExact]);
  const mix = useMemo(() => (tensor ? currentMix({ rows: state.rows, unit: state.unit }, tensor) : null), [tensor, state.rows, state.unit]);
  const cellMix = useCallback(
    (j: number, k: number) => {
      const w = tensor?.grid.w[j]?.[k];
      return math && w ? { weights: w, stats: math.stats(w) } : null;
    },
    [tensor, math],
  );
  const frontierEnb = useMemo(() => (tensor && math ? tensor.frontier.w.map((w) => math.stats(w).enb) : []), [tensor, math]);
  const currentStats = useMemo(() => (math && mix?.weights ? math.stats(mix.weights) : null), [math, mix]);
  // The entered mix's range: the tensor's own when it is the menu's allocation (presets), else the
  // service's for these weights; until then, or if it cannot answer, none (the bell-curve figure
  // stays in the details).
  const builtIn = useMemo((): YearRange | null => {
    const entered = tensor?.entered;
    const w = mix?.weights;
    if (!entered || !w || entered.w.length !== w.length || entered.w.some((v, i) => Math.abs(v - w[i]) > 1e-9)) return null;
    return { low: entered.range.bad, typical: entered.range.typical, high: entered.range.good };
  }, [tensor, mix]);
  const enteredExact = useExactRange(rangeKey, builtIn === null && mix?.weights ? mix.weights : null);
  const current = useMemo(() => {
    if (!math || !mix?.weights || !currentStats) return null;
    return { stats: currentStats, range: builtIn ?? enteredExact, weights: mix.weights };
  }, [math, mix, currentStats, builtIn, enteredExact]);

  // The strip's bar keeps one scale per menu, over every history window loaded for it.
  const stripBounds = useStripBounds(tensor, state.ghostTensors);

  const lookbackGhosts = useMemo(
    () => state.ghosts.flatMap((id) => (state.ghostTensors[id] ? [{ id, curve: state.ghostTensors[id]!.frontier_curve }] : [])),
    [state.ghosts, state.ghostTensors],
  );
  // Ghost data is a faint extra for the chart, so the view asks for it once the main view is ready.
  const ghostKey = state.ghosts.join(",");
  useEffect(() => {
    if (state.build.status === "ready" && ghostKey) dispatch({ type: "loadGhosts" });
  }, [state.build.status, ghostKey, dispatch]);

  const scales: ChartScales | null = useMemo(() => {
    if (!tensor || size.width <= 0 || size.height <= 0) return null;
    const { frontier, grid, frontier_curve: curve } = tensor;
    const dx = frontier.x.length > 1 ? frontier.x[1] - frontier.x[0] : 0.01;
    const dy = grid.y.length > 1 ? grid.y[1] - grid.y[0] : 0.01;
    const pts = curve.sigma.map((sigma, i) => ({ sigma, mu: curve.mu[i] }));
    pts.push({ sigma: frontier.x[0], mu: grid.y[0] - dy / 2 });
    if (currentStats) pts.push(currentStats);
    for (const g of lookbackGhosts) g.curve.sigma.forEach((sigma, i) => pts.push({ sigma, mu: g.curve.mu[i] }));
    if (state.details) tensor.sigma.forEach((sigma, i) => pts.push({ sigma, mu: tensor.mu_s[i] }));
    const extent = paddedExtent(pts, { dx: dx / 2, dy: dy / 2 });
    if (!phone) {
      // Room to the right of every frontier line for the name of its history window.
      const plotW = size.width - DESKTOP_MARGINS.left - DESKTOP_MARGINS.right;
      const ends = [{ id: tensor.lookback.id as string, curve }, ...lookbackGhosts].filter((l) => l.curve.sigma.length > 0);
      for (const line of ends) {
        const need = 20 + (lookbackLine[line.id] ?? line.id).length * 6.3 - (DESKTOP_MARGINS.right - 4);
        const reach = line.curve.sigma[line.curve.sigma.length - 1] - extent.xMin;
        if (plotW - need > 120) extent.xMax = Math.max(extent.xMax, extent.xMin + (reach * plotW) / (plotW - need));
      }
    }
    return makeScales(size.width, size.height, extent, phone);
  }, [tensor, size.width, size.height, currentStats, lookbackGhosts, state.details, phone]);

  // The same menu with every limit lifted, drawn like a ghost whenever the limits bind. It does not
  // widen the chart: where it rises above the view it is cut at the edge and named there.
  const chartGhosts = useMemo(() => {
    if (!tensor || !scales) return lookbackGhosts;
    if (!limitsBind(tensor)) return lookbackGhosts;
    const [xMin, xMax] = scales.x.domain();
    const [yMin, yMax] = scales.y.domain();
    const curve = clipCurve(tensor.frontier_uncapped, { xMin, xMax, yMin, yMax });
    return curve.sigma.length >= 2 ? [...lookbackGhosts, { id: NO_LIMITS, curve }] : lookbackGhosts;
  }, [tensor, scales, lookbackGhosts]);

  // The first paint of a chart wipes in once; later redraws (theme, ghosts) are immediate.
  const [reveal, setReveal] = useState(true);
  useEffect(() => {
    if (!scales) return;
    const timer = setTimeout(() => setReveal(false), 1200);
    return () => clearTimeout(timer);
  }, [scales !== null]); // eslint-disable-line react-hooks/exhaustive-deps

  const domain = view?.domain ?? { s_safe: 0, s_max: 0 };
  const clampS = useCallback((v: number) => Math.min(domain.s_max, Math.max(domain.s_safe, v)), [domain.s_max, domain.s_safe]);
  const setS = useCallback((s: number) => dispatch({ type: "riskSlider", s }), [dispatch]);
  const setT = useCallback((t: number) => dispatch({ type: "divSlider", t }), [dispatch]);
  const xOf = useCallback((s: number) => (scales && tensor ? scales.x(ceilingAt(tensor, s)) : 0), [scales, tensor]);
  const sOf = useCallback((px: number) => (scales && tensor ? positionOfCeiling(tensor, scales.x.invert(px)) : 0), [scales, tensor]);
  const onRiskPixel = useCallback((px: number) => setS(clampS(sOf(px))), [setS, clampS, sOf]);
  // A vertical drag moves the diversification position by the distance travelled, measured against
  // the on-screen height of the column's ladder, starting from where the slider was.
  const dragT0 = useRef(0);
  const onDivDrag = useCallback(
    (dy: number, start: boolean) => {
      if (!scales || !view || view.disabled) return;
      if (start) dragT0.current = view.t;
      const span = scales.y(view.peak.mu) - scales.y(view.front.mu);
      if (span < 3 || start) return;
      setT(Math.min(1, Math.max(0, dragT0.current + dy / span)));
    },
    [scales, view, setT],
  );
  const onNudge = useCallback(
    (ds: number, dt: number) => {
      if (!view) return;
      if (ds !== 0) setS(clampS(view.s + (ds * (domain.s_max - domain.s_safe)) / 200));
      if (dt !== 0 && !view.disabled) setT(Math.min(1, Math.max(0, view.t + dt / 40)));
    },
    [view, setS, setT, clampS, domain.s_max, domain.s_safe],
  );

  const showSection = useCallback(
    (id: SectionId) => {
      if (id === "funds" && wide) setSideOpen(true);
      else setOpen((prev) => ({ ...prev, [id]: true }));
      setScrollTo((prev) => ({ id, n: (prev?.n ?? 0) + 1 }));
    },
    [wide, setSideOpen],
  );
  useEffect(() => {
    if (!scrollTo) return;
    const el = document.getElementById(`section-${scrollTo.id}`);
    const calm = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const beside = scrollTo.id === "funds" && el?.tagName === "ASIDE";
    el?.scrollIntoView?.({ behavior: calm ? "auto" : "smooth", block: beside ? "nearest" : "start" });
  }, [scrollTo]);

  const openShare = useCallback(() => {
    dispatch({ type: "flushUrl" });
    setShare(window.location.href);
  }, [dispatch]);
  const closeShare = useCallback(() => setShare(null), []);
  const needSymbols = useCallback(() => dispatch({ type: "loadSymbols" }), [dispatch]);

  const hasMix = Boolean(mix?.weights);
  // Stress tests come before Trades, so the cards sit near the chart on a smaller screen.
  const sections: SectionId[] = hasMix ? ["funds", "stress", "trades", "settings"] : ["funds", "stress", "settings"];
  const presets = state.presets?.presets ?? [];
  const busy = state.build.status === "building";
  const includedAmounts = useMemo(() => {
    if (!tensor) return [];
    const byId = new Map(state.rows.map((r) => [r.id, r.amount]));
    return tensor.universe.funds.map((f) => byId.get(f.id) ?? null);
  }, [tensor, state.rows]);

  let notice: ReactNode = null;
  if (state.build.status === "building") {
    notice = (
      <div className={tensor ? "notice notice-late" : "notice"} data-testid="building-notice" role="status">
        <div className="notice-card">
          <span className="ring" aria-hidden="true" />
          <p>{plain.building}</p>
          {state.build.position !== null && state.build.position > 0 && <p className="sub">{`Place in line: ${state.build.position}`}</p>}
        </div>
      </div>
    );
  } else if (state.build.status === "build-retry" || state.build.status === "build-failed-final") {
    const final = state.build.status === "build-failed-final";
    notice = (
      <div className="notice" data-testid="building-notice" role="alert">
        <div className="notice-card">
          <p>{final ? plain.buildFailedFinal : plain.buildFailed}</p>
          {state.build.error && <p className="sub num">{state.build.error}</p>}
          {final ? (
            <div className="notice-presets">
              {presets.map((p) => (
                <button key={p.id} type="button" className="btn" onClick={() => dispatch({ type: "selectPreset", id: p.id })}>
                  {p.name}
                </button>
              ))}
            </div>
          ) : (
            <button type="button" className="btn btn-primary" data-testid="build-retry" onClick={() => dispatch({ type: "retryBuild" })}>
              {plain.retry}
            </button>
          )}
        </div>
      </div>
    );
  } else if (!tensor && state.unavailable[state.lookback]) {
    notice = (
      <div className="notice" role="status">
        <div className="notice-card">
          <p>{`This menu does not have enough shared history for the ${lookbackNames[state.lookback].toLowerCase()} view. Try another:`}</p>
          <div className="notice-presets">
            {LOOKBACKS.filter((id) => !state.unavailable[id]).map((id) => (
              <button key={id} type="button" className="btn" onClick={() => dispatch({ type: "setLookback", lookback: id })}>
                {lookbackNames[id]}
              </button>
            ))}
          </div>
        </div>
      </div>
    );
  } else if (state.loadError && !tensor) {
    notice = (
      <div className="notice" role="status">
        <div className="notice-card">
          <p>{state.loadError}</p>
        </div>
      </div>
    );
  }

  const fundsTable = (
    <Funds
      rows={state.rows}
      unit={state.unit}
      tensor={tensor}
      symbols={state.symbols}
      mixStatus={mix?.status ?? "empty"}
      setAside={mix?.setAside ?? null}
      menuError={state.menuError}
      busy={busy}
      selected={view?.weights ?? null}
      onUnit={(unit) => dispatch({ type: "setUnit", unit })}
      onAmount={(id, amount) => dispatch({ type: "setAmount", id, amount })}
      onUseMenu={(rows) => dispatch({ type: "useMenu", rows })}
      onNeedSymbols={needSymbols}
    />
  );

  return (
    <div className="app">
      <header className="hdr">
        <div className="wrap hdr-in">
          <Wordmark />
          <div className="hdr-tools">
            <PresetMenu
              presets={presets}
              active={state.preset}
              compact={phone}
              onSelect={(id) => dispatch({ type: "selectPreset", id })}
              onCustom={() => showSection("funds")}
            />
            <button type="button" className="btn btn-icon" data-testid="share-open" aria-label="Share this view" onClick={openShare}>
              <Share2 size={phone ? 18 : 16} aria-hidden="true" />
            </button>
            <ThemeSwitch theme={state.theme} compact={phone} onChange={(theme) => dispatch({ type: "setTheme", theme })} />
          </div>
        </div>
      </header>

      <main className={`wrap stage${wide ? " has-side" : ""}${wide && sideOpen ? " side-open" : ""}`}>
        <div className="stage-main">
        <div className="hero">
          <Chart
            ref={chartRef}
            tensor={tensor}
            view={view}
            scales={scales}
            ghosts={chartGhosts}
            frontierEnb={frontierEnb}
            current={current}
            details={state.details}
            phone={phone}
            themeEpoch={themeEpoch}
            reveal={reveal}
            notice={notice}
            busy={busy}
            cellMix={cellMix}
            onRiskPixel={onRiskPixel}
            onDivDrag={onDivDrag}
            onNudge={onNudge}
          />
          {view && phone && <MarkKeys hasCurrent={currentStats !== null} hasGhosts={lookbackGhosts.length > 0} hasNoLimits={chartGhosts.length > lookbackGhosts.length} compact />}
          {view && !phone && (
            <DivSlider
              t={view.t}
              moved={view.moved}
              disabled={view.disabled || busy}
              horizontal={false}
              details={state.details}
              onChange={setT}
              onReset={() => dispatch({ type: "resetDiv" })}
            />
          )}
          {view && scales && (
            <RiskSlider
              s={view.s}
              domain={view.domain}
              xOf={xOf}
              sOf={sOf}
              width={scales.width}
              low={view.frontRange.low}
              typical={view.frontRange.typical}
              details={state.details}
              phone={phone}
              stem={scales.margins.bottom + 22}
              busy={busy}
              onChange={setS}
            />
          )}
          {view && phone && (
            <DivSlider
              t={view.t}
              moved={view.moved}
              disabled={view.disabled || busy}
              horizontal
              details={state.details}
              onChange={setT}
              onReset={() => dispatch({ type: "resetDiv" })}
            />
          )}
        </div>

        {view && tensor && (
          <ResultStrip
            low={view.range.low}
            typical={view.range.typical}
            high={view.range.high}
            normal={view.normal}
            scale={stripScale(stripBounds, [view.range.low, view.range.typical, view.range.high])}
            word={view.word}
            details={state.details}
            facts={{
              enb: view.selected.enb,
              enbRef: tensor.enb_ref,
              mu: view.selected.mu,
              sigma: view.selected.sigma,
              lookbackStart: tensor.lookback.start,
              lookbackEnd: tensor.lookback.end,
              rows: tensor.lookback.rows,
              asof: tensor.asof,
              notes: tensor.notes ?? [],
              defaultPoint: tensor.ladder.default_point,
            }}
            staleAsof={state.staleness?.asof ?? null}
            onToggleDetails={() => dispatch({ type: "setDetails", details: !state.details })}
          />
        )}

        <div className="below">
          <nav className="chips" aria-label="More about this view">
            {sections.map((id) => {
              const Icon = SECTION_ICON[id];
              return (
                <button key={id} type="button" className="chip" data-testid={`chip-${id}`} onClick={() => showSection(id)}>
                  <Icon size={15} aria-hidden="true" />
                  <span>{plain.chips[id]}</span>
                </button>
              );
            })}
          </nav>
          <p className="advice">{plain.advice}</p>
        </div>
        </div>
        {wide && (
          <aside className="side" id="section-funds" data-testid="section-funds" aria-expanded={sideOpen} aria-label={plain.chips.funds}>
            <button
              type="button"
              className="side-tab"
              data-testid="funds-toggle"
              aria-expanded={sideOpen}
              aria-controls="section-funds-body"
              aria-label={sideOpen ? plain.fundsClose : plain.fundsOpen}
              title={sideOpen ? plain.fundsClose : plain.fundsOpen}
              onClick={() => setSideOpen(!sideOpen)}
            >
              {sideOpen ? <PanelRightClose size={17} aria-hidden="true" /> : <PanelRightOpen size={17} aria-hidden="true" />}
              <span className="heading">{plain.chips.funds}</span>
            </button>
            {sideOpen && (
              <div className="side-body" id="section-funds-body">
                {fundsTable}
              </div>
            )}
          </aside>
        )}
      </main>

      <div className="wrap sections">
        {!wide && (
          <Accordion id="funds" title={plain.chips.funds} open={open.funds} onToggle={() => setOpen((p) => ({ ...p, funds: !p.funds }))}>
            {fundsTable}
          </Accordion>
        )}
        <Accordion id="stress" title={plain.chips.stress} open={open.stress} onToggle={() => setOpen((p) => ({ ...p, stress: !p.stress }))}>
          {tensor && view ? <Stress tensor={tensor} wSel={view.weights} wNow={mix?.weights ?? null} details={state.details} /> : null}
        </Accordion>
        {hasMix && tensor && view && mix?.weights && (
          <Accordion id="trades" title={plain.chips.trades} open={open.trades} onToggle={() => setOpen((p) => ({ ...p, trades: !p.trades }))}>
            <Trades funds={tensor.universe.funds} wNow={mix.weights} wSel={view.weights} unit={state.unit} amounts={includedAmounts} asof={tensor.asof} />
          </Accordion>
        )}
        <Accordion id="settings" title={plain.chips.settings} open={open.settings} onToggle={() => setOpen((p) => ({ ...p, settings: !p.settings }))}>
          {tensor ? (
            <Settings
              tensor={tensor}
              lookback={state.lookback}
              ghosts={state.ghosts}
              caps={state.caps}
              unavailable={state.unavailable}
              details={state.details}
              busy={busy}
              problem={state.menuError}
              onLookback={(lookback: LookbackId) => dispatch({ type: "setLookback", lookback })}
              onGhost={(lookback: LookbackId) => dispatch({ type: "toggleGhost", lookback })}
              onCaps={(caps) => dispatch({ type: "setCaps", caps })}
              onShare={openShare}
            />
          ) : null}
        </Accordion>
      </div>

      <footer className="foot">
        <div className="wrap foot-in">
          <p className="disclaimer" data-testid="disclaimer">
            {disclaimer}
          </p>
          <p className="cta" data-testid="footer-cta">
            <span>{family.lead}:</span>
            {family.links.map((link, i) => (
              <span key={link.href}>
                <a href={link.href} target="_blank" rel="noopener noreferrer" title={`${link.name} ${family.newTab}`}>
                  {link.name}
                  <ExternalLink className="ext" size={11} aria-hidden="true" />
                  <span className="sr-only">{` ${family.newTab}`}</span>
                </a>
                <span className="sep">{` (${link.href})${i < family.links.length - 1 ? ", " : "."}`}</span>
              </span>
            ))}
          </p>
        </div>
      </footer>

      <ShareDialog open={share !== null} url={share ?? ""} privatePreview={state.previewOn} onClose={closeShare} onChallenge={() => dispatch({ type: "challenged" })} />
    </div>
  );
}
