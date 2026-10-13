// The single store (spec 8): menu, allocation, lookback, ghosts, s, t | "auto", theme, caps and
// build status, plus the effects that load tensors. Slider actions never touch the network.
// Runs in plain node: `fetch`, `history`, `location` and `localStorage` are read only inside
// functions, never at import time.
import {
  ChallengeError,
  NoGenerationError,
  fetchHealth,
  fetchPresets,
  fetchSymbols,
  getTensor,
  postTensor,
  type Preset,
  type PresetsBody,
  type SymbolEntry,
  type TensorAnswer,
} from "../api/http";
import type { Tensor } from "../api/tensor";
import { amountsToWeights } from "../math/amounts";
import { portfolioMath } from "../math/portfolio";
import { positionOfCeiling } from "../math/view";
import { decode, encode, type UrlState } from "./url";

export type Unit = UrlState["unit"];
export type LookbackId = UrlState["lookback"];
export type ThemeId = NonNullable<UrlState["theme"]>;
export type Cap = UrlState["caps"][number];
export type Row = { id: string; name: string; amount: number | null };
export type BuildStatus = "idle" | "building" | "ready" | "build-retry" | "build-failed-final";

export const LOOKBACKS: LookbackId[] = ["1y", "2y", "3y", "5y", "10y", "ew"];
export const MAX_FUNDS = 30;
export const MIN_FUNDS = 2;
export const NOT_ENOUGH_HISTORY = "not enough shared history";
export const NOT_LOADED_YET = "PortfolioSight's price data is not loaded yet. Please check back in a little while.";
export const CAPS_INFEASIBLE = "These limits cannot all be met at once. Loosen one of them, or reset to the default rule.";
const POLL_MS = 2000;
const URL_DEBOUNCE_MS = 250;
const MAX_FAILURES = 3;

export type State = {
  preset: string | null;
  rows: Row[];
  unit: Unit;
  caps: Cap[];
  lookback: LookbackId;
  ghosts: LookbackId[];
  s: number;
  t: number | "auto";
  theme: ThemeId;
  details: boolean;
  presets: PresetsBody | null;
  previewOn: boolean;
  symbols: SymbolEntry[] | null;
  tensor: Tensor | null;
  /** Lookback of the tensor on screen (differs from `lookback` while a switch is loading). */
  tensorLookback: LookbackId | null;
  ghostTensors: Partial<Record<LookbackId, Tensor>>;
  build: { status: BuildStatus; error: string | null; position: number | null };
  /** Lookbacks that cannot be shown for this menu, with the one-sentence note. */
  unavailable: Partial<Record<LookbackId, string>>;
  /** Set when the price data is behind: the `asof` date to show (expectation F13). */
  staleness: { asof: string } | null;
  /** One-sentence problem with the requested menu (unknown symbols, refused request). */
  menuError: string | null;
  loadError: string | null;
};

export type Action =
  | { type: "start" }
  | { type: "riskSlider"; s: number }
  | { type: "divSlider"; t: number }
  | { type: "resetDiv" }
  | { type: "setLookback"; lookback: LookbackId }
  | { type: "retryBuild" }
  | { type: "selectPreset"; id: string }
  | { type: "setTheme"; theme: ThemeId }
  | { type: "setDetails"; details: boolean }
  | { type: "toggleGhost"; lookback: LookbackId }
  | { type: "loadGhosts" }
  | { type: "loadSymbols" }
  | { type: "flushUrl" }
  | { type: "setUnit"; unit: Unit }
  | { type: "setAmount"; id: string; amount: number | null }
  | { type: "useMenu"; rows: Row[] }
  | { type: "setCaps"; caps: Cap[] };

export type Store = {
  getState(): State;
  dispatch(action: Action): void;
  subscribe(listener: () => void): () => void;
};

const THEME_KEY = "ps.theme";
const isTheme = (v: unknown): v is ThemeId => v === "ks-dark" || v === "light" || v === "hud";

function storedTheme(): ThemeId | null {
  try {
    const v = globalThis.localStorage?.getItem(THEME_KEY);
    return isTheme(v) ? v : null;
  } catch {
    return null;
  }
}

const unitOfPreset = (preset: Preset): Unit | null =>
  preset.allocation_unit === "$" || preset.allocation_unit === "usd"
    ? "usd"
    : preset.allocation_unit === "shares"
      ? "shares"
      : preset.allocation_unit === "%" || preset.allocation_unit === "pct"
        ? "pct"
        : null;

const rowsOfPreset = (preset: Preset): Row[] =>
  preset.funds.map((f) => ({ id: f.id, name: f.name ?? f.id, amount: preset.allocation ? (preset.allocation[f.id] ?? null) : null }));

/** The URL description of a state (spec 8.1). A preset is named by `u`; its rows are not repeated. */
export function toUrlState(state: State, haveR: boolean): UrlState {
  return {
    preset: state.preset as UrlState["preset"],
    funds: state.preset ? [] : state.rows.map((r) => ({ id: r.id, amount: r.amount })),
    unit: state.unit,
    caps: state.caps,
    lookback: state.lookback,
    ghosts: state.ghosts,
    r: haveR ? state.s : null,
    d: state.t,
    theme: state.theme,
    details: state.details,
  };
}

/** Weights of "the mix you entered" over the tensor's included funds, or why there is none. */
export function currentMix(state: Pick<State, "rows" | "unit">, tensor: Tensor): {
  weights: number[] | null;
  status: "ok" | "empty" | "invalid_total" | "unknown_price" | "all_set_aside";
  /** Share of the entered mix held in funds this view sets aside (null when it cannot be valued). */
  setAside: number | null;
} {
  const byId = new Map(state.rows.map((r) => [r.id, r.amount]));
  const funds = tensor.universe.funds;
  const included = funds.map((f) => byId.get(f.id) ?? null);
  const includedIds = new Set(funds.map((f) => f.id));
  const outside = state.rows.filter((r) => !includedIds.has(r.id) && (r.amount ?? 0) > 0);
  if (state.rows.every((r) => r.amount === null)) return { weights: null, status: "empty", setAside: null };
  if (state.unit === "pct") {
    const total = state.rows.reduce((acc, r) => acc + (r.amount ?? 0), 0);
    if (Math.abs(total - 100) > 0.05) return { weights: null, status: "invalid_total", setAside: null };
  }
  const outsideAmount = outside.reduce((acc, r) => acc + (r.amount ?? 0), 0);
  const insideAmount = included.reduce((acc: number, a) => acc + (a ?? 0), 0);
  if (insideAmount <= 0) return { weights: null, status: outsideAmount > 0 ? "all_set_aside" : "empty", setAside: outsideAmount > 0 ? 1 : null };
  // Percent and dollar amounts renormalize over the included funds; shares are valued at last_close.
  const res = amountsToWeights(included, state.unit === "shares" ? "shares" : "usd", funds.map((f) => f.last_close ?? null));
  if (res.status !== "ok" || !res.weights) {
    return { weights: null, status: res.status === "unknown_price" ? "unknown_price" : "empty", setAside: null };
  }
  const setAside = outsideAmount <= 0 ? 0 : state.unit === "shares" ? null : outsideAmount / (outsideAmount + insideAmount);
  return { weights: res.weights, status: "ok", setAside };
}

const menuKey = (rows: Row[], caps: Cap[]) =>
  JSON.stringify([rows.map((r) => r.id).sort(), [...caps].sort((a, b) => a.id.localeCompare(b.id)).map((c) => [c.id, c.min, c.max])]);

export function createStore(init: { search: string }): Store {
  const url = decode(init.search);
  const params = new URLSearchParams(init.search.startsWith("?") ? init.search.slice(1) : init.search);
  const unitInUrl = params.has("unit");
  let haveR = url.r !== null;
  let pendingUrlR = url.r !== null;

  let state: State = {
    preset: url.preset,
    rows: url.funds.map((f) => ({ id: f.id, name: f.id, amount: f.amount })),
    unit: url.unit,
    caps: url.caps,
    lookback: url.lookback,
    ghosts: url.ghosts.filter((g): g is LookbackId => (LOOKBACKS as string[]).includes(g) && g !== url.lookback),
    s: url.r ?? 0,
    t: url.d,
    theme: url.theme ?? storedTheme() ?? "ks-dark",
    details: url.details,
    presets: null,
    previewOn: false,
    symbols: null,
    tensor: null,
    tensorLookback: null,
    ghostTensors: {},
    build: { status: "idle", error: null, position: null },
    unavailable: {},
    staleness: null,
    menuError: null,
    loadError: null,
  };

  const listeners = new Set<() => void>();
  const cache = new Map<string, Tensor>();
  let halted = false; // after a challenge reload: no more requests, no more URL writes
  let started = false;
  let urlTimer: ReturnType<typeof setTimeout> | null = null;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  const ghostTimers = new Set<ReturnType<typeof setTimeout>>();
  let loadSeq = 0;
  let failures = 0;
  let lastPost: { key: string; body: string } | null = null;
  let symbolsAsked = false;

  const emit = () => listeners.forEach((l) => l());
  const set = (patch: Partial<State>, writeUrl = true) => {
    state = { ...state, ...patch };
    if (writeUrl) scheduleUrl();
    emit();
  };

  const urlNow = () => `${globalThis.location?.pathname ?? "/"}${encode(toUrlState(state, haveR))}`;
  const writeUrl = () => {
    try {
      globalThis.history?.replaceState(globalThis.history.state ?? null, "", urlNow());
    } catch {
      // history may be unavailable (sandboxed frames); the view still works
    }
  };
  function scheduleUrl() {
    if (halted || !started) return;
    if (urlTimer !== null) clearTimeout(urlTimer);
    urlTimer = setTimeout(() => {
      urlTimer = null;
      if (!halted) writeUrl();
    }, URL_DEBOUNCE_MS);
  }
  const clearPoll = () => {
    if (pollTimer !== null) clearTimeout(pollTimer);
    pollTimer = null;
  };

  /** Spec 3.2: keep the state in the URL, reload at top level so the interstitial can run. */
  function onChallenge() {
    if (halted) return;
    halted = true;
    clearPoll();
    ghostTimers.forEach((timer) => clearTimeout(timer));
    ghostTimers.clear();
    if (urlTimer !== null) clearTimeout(urlTimer);
    urlTimer = null;
    writeUrl();
    globalThis.location?.reload();
  }
  const guard = (err: unknown): boolean => {
    if (err instanceof ChallengeError) {
      onChallenge();
      return true;
    }
    return false;
  };

  const activePreset = (): Preset | null => state.presets?.presets.find((p) => p.id === state.preset) ?? null;

  /** How to ask for this menu's tensor at `lookback`: the preset's declared URL, or a POST body. */
  function requestFor(lookback: LookbackId, post = false): { get: string } | { post: string } | { unavailable: string } {
    const preset = activePreset();
    if (preset && state.caps.length === 0 && !post) {
      const entry = preset.lookbacks[lookback];
      if (entry && entry.status === "ready" && entry.url) return { get: entry.url };
      if (entry && entry.status === "unavailable") return { unavailable: NOT_ENOUGH_HISTORY };
    }
    const capOf = new Map(state.caps.map((c) => [c.id, c]));
    // Every fund of the menu is sent: the service sets aside the ones it cannot use and says why
    // in the tensor's `excluded` list (expectation S24); a ticker it does not know is a 400.
    const ids = state.rows.map((r) => r.id);
    const funds = ids.map((id) => {
      const cap = capOf.get(id);
      return { id, min: cap && cap.min !== null ? cap.min / 100 : null, max: cap && cap.max !== null ? cap.max / 100 : null };
    });
    return { post: JSON.stringify({ funds, lookback }) };
  }

  function applyTensor(tensor: Tensor, lookback: LookbackId) {
    const math = portfolioMath(tensor);
    const domain = math.riskSliderDomain();
    const clamp = (v: number) => Math.min(domain.s_max, Math.max(domain.s_safe, v));
    let s: number;
    let t = state.t;
    if (pendingUrlR || state.tensor !== null) {
      // A position exists already (from the URL or the previous tensor): keep it, clamped into the
      // new domain; a clamp moves the point, so the diversification position returns to suggested.
      s = clamp(state.s);
      if (Math.abs(s - state.s) > 1e-12) t = "auto";
    } else {
      const mix = currentMix(state, tensor);
      s = mix.weights ? positionOfCeiling(tensor, math.stats(mix.weights).sigma) : (domain.s_safe + domain.s_max) / 2;
      s = clamp(s);
    }
    pendingUrlR = false;
    haveR = true;
    failures = 0;
    const names = new Map<string, string>([...tensor.universe.funds.map((f) => [f.id, f.name] as [string, string])]);
    set({
      tensor,
      tensorLookback: lookback,
      s,
      t,
      rows: state.rows.map((r) => (r.name === r.id && names.has(r.id) ? { ...r, name: names.get(r.id) as string } : r)),
      build: { status: "ready", error: null, position: null },
      menuError: null,
      ghosts: state.ghosts.filter((g) => g !== lookback),
    });
  }

  function fail(error: string, retryable: boolean) {
    clearPoll();
    failures += 1;
    const final = failures >= MAX_FAILURES || !retryable;
    set({ build: { status: final ? "build-failed-final" : "build-retry", error, position: null } }, false);
  }

  /** Spec 4.2 / expectation S24: say so in one sentence and carry on with the rest. */
  function windowUnavailable(lookback: LookbackId, previous: LookbackId | null) {
    clearPoll();
    set({
      unavailable: { ...state.unavailable, [lookback]: NOT_ENOUGH_HISTORY },
      lookback: previous ?? state.tensorLookback ?? lookback,
      build: { status: state.tensor ? "ready" : "idle", error: null, position: null },
    });
  }

  function refused(answer: Extract<TensorAnswer, { kind: "refused" }>, lookback: LookbackId, previous: LookbackId | null) {
    clearPoll();
    const reason = typeof answer.details?.reason === "string" ? answer.details.reason : "";
    if (answer.status === 422 && reason === NOT_ENOUGH_HISTORY) return windowUnavailable(lookback, previous);
    if (answer.code === "no_generation") {
      set({ loadError: NOT_LOADED_YET, build: { status: state.tensor ? "ready" : "idle", error: null, position: null } }, false);
      return;
    }
    if (answer.code === "unknown_symbols") {
      const list = Array.isArray(answer.details?.symbols) ? (answer.details.symbols as unknown[]).map(String) : [];
      set({
        menuError: list.length ? `No verified current data for ${list.join(", ")}. Remove ${list.length > 1 ? "them" : "it"} to continue.` : "This menu has a fund we cannot find.",
        build: { status: state.tensor ? "ready" : "idle", error: null, position: null },
      });
      return;
    }
    if (answer.status === 422 || answer.status === 400) {
      set({
        menuError: answer.message || reason || "This menu cannot be computed as entered.",
        build: { status: state.tensor ? "ready" : "idle", error: null, position: null },
      });
      return;
    }
    fail(answer.code, true);
  }

  /** Loads the primary tensor for `lookback`. Idempotent by (generation, hash, lookback) on the server. */
  async function load(lookback: LookbackId, opts: { retry?: boolean; previous?: LookbackId | null; fresh?: boolean } = {}) {
    if (halted) return;
    const seq = ++loadSeq;
    clearPoll();
    const req = requestFor(lookback, opts.fresh === true);
    if ("unavailable" in req) {
      set({
        unavailable: { ...state.unavailable, [lookback]: req.unavailable },
        lookback: opts.previous ?? state.tensorLookback ?? lookback,
      });
      return;
    }
    // Tensors are immutable per request (a declared URL, or a menu-and-caps body): keep them.
    const key = "get" in req ? req.get : req.post;
    const cached = opts.fresh ? undefined : cache.get(key);
    if (cached) {
      applyTensor(cached, lookback);
      return;
    }
    set({ build: { status: "building", error: null, position: null }, menuError: null }, false);
    const stale = () => halted || seq !== loadSeq;
    const handle = async (answer: TensorAnswer): Promise<void> => {
      if (stale()) return;
      if (answer.kind === "tensor") {
        cache.set(key, answer.tensor);
        applyTensor(answer.tensor, lookback);
      } else if (answer.kind === "ready") {
        await step(() => getTensor(answer.url, lookback));
      } else if (answer.kind === "pending") {
        set({ build: { status: "building", error: null, position: answer.position } }, false);
        const pollUrl = answer.pollUrl ?? lastPoll;
        if (!pollUrl) return fail("bad_response", true);
        lastPoll = pollUrl;
        pollTimer = setTimeout(() => {
          pollTimer = null;
          void step(() => getTensor(pollUrl, lookback));
        }, POLL_MS);
      } else if (answer.kind === "failed") {
        // The service answers an unusable window and unmeetable limits as failed builds that are
        // not retried; neither is a breakdown, so the view stays and says what happened.
        if (answer.error === "window_unavailable") windowUnavailable(lookback, opts.previous ?? null);
        else if (answer.error === "caps_infeasible") {
          clearPoll();
          set({ menuError: CAPS_INFEASIBLE, build: { status: state.tensor ? "ready" : "idle", error: null, position: null } }, false);
        } else fail(answer.error, answer.retry);
      } else {
        refused(answer, lookback, opts.previous ?? null);
      }
    };
    let lastPoll: string | null = null;
    const step = async (run: () => Promise<TensorAnswer>): Promise<void> => {
      if (stale()) return;
      try {
        await handle(await run());
      } catch (err) {
        if (guard(err) || stale()) return;
        fail("network_error", true);
      }
    };
    if ("get" in req) {
      await step(() => getTensor(req.get, lookback));
    } else {
      // A retry re-sends the identical body (the build is idempotent by generation, hash, lookback).
      const body = opts.retry && lastPost && lastPost.key === key ? lastPost.body : req.post;
      lastPost = { key, body };
      await step(() => postTensor(body, lookback));
    }
  }

  async function loadGhost(lookback: LookbackId) {
    if (halted || state.ghostTensors[lookback] || !state.tensor) return;
    const req = requestFor(lookback);
    const drop = (note: string | null) =>
      set({ ghosts: state.ghosts.filter((g) => g !== lookback), ...(note ? { unavailable: { ...state.unavailable, [lookback]: note } } : {}) });
    if ("unavailable" in req) return drop(req.unavailable);
    const key = "get" in req ? req.get : req.post;
    const sameMenu = () => {
      const now = requestFor(lookback);
      return !("unavailable" in now) && ("get" in now ? now.get : now.post) === key;
    };
    const done = (tensor: Tensor) => {
      cache.set(key, tensor);
      if (state.ghosts.includes(lookback) && sameMenu()) set({ ghostTensors: { ...state.ghostTensors, [lookback]: tensor } }, false);
    };
    const cached = cache.get(key);
    if (cached) return done(cached);
    try {
      let answer = "get" in req ? await getTensor(req.get, lookback) : await postTensor(req.post, lookback);
      // A ghost is a faint extra: follow a ready URL once, but do not queue builds for it.
      if (answer.kind === "ready") answer = await getTensor(answer.url, lookback);
      // A ghost that is still being built is polled like the main view, for as long as it stays
      // switched on for this menu (at most two minutes).
      for (let tries = 0; answer.kind === "pending" && answer.pollUrl && tries < 60; tries++) {
        const pollUrl: string = answer.pollUrl;
        await new Promise<void>((resolve) => {
          const timer = setTimeout(() => {
            ghostTimers.delete(timer);
            resolve();
          }, POLL_MS);
          ghostTimers.add(timer);
        });
        if (halted || !state.ghosts.includes(lookback) || !sameMenu()) return;
        answer = await getTensor(pollUrl, lookback);
      }
      if (answer.kind === "tensor") return done(answer.tensor);
      if (answer.kind === "refused" && answer.details?.reason === NOT_ENOUGH_HISTORY) return drop(NOT_ENOUGH_HISTORY);
      if (answer.kind === "failed" && answer.error === "window_unavailable") return drop(NOT_ENOUGH_HISTORY);
      drop(null);
    } catch (err) {
      if (guard(err)) return;
      drop(null);
    }
  }

  function deriveStaleness(health: { asof?: string | null; asof_trading_days_behind?: number | null } | null) {
    const asof = health?.asof ?? state.presets?.asof ?? state.tensor?.asof ?? null;
    if (health && typeof health.asof_trading_days_behind === "number") {
      set({ staleness: health.asof_trading_days_behind >= 2 && asof ? { asof } : null }, false);
      return;
    }
    // Health unreachable: fall back to the age of the presets' asof date (more than 4 calendar days).
    const presetsAsof = state.presets?.asof ?? null;
    if (!presetsAsof) return;
    const age = (Date.now() - Date.parse(`${presetsAsof}T00:00:00Z`)) / 86_400_000;
    set({ staleness: age > 4 ? { asof: presetsAsof } : null }, false);
  }

  function adoptPreset(preset: Preset, keepUnit: boolean) {
    state = {
      ...state,
      preset: preset.id,
      rows: rowsOfPreset(preset),
      unit: keepUnit ? state.unit : (unitOfPreset(preset) ?? "pct"),
    };
  }

  async function ensureSymbols() {
    if (symbolsAsked || halted) return;
    symbolsAsked = true;
    try {
      set({ symbols: await fetchSymbols() }, false);
    } catch (err) {
      if (guard(err)) return;
      symbolsAsked = false;
    }
  }

  async function start() {
    if (started || halted) return;
    started = true;
    const custom = state.preset === null && state.rows.length > 0;
    const presetsJob = fetchPresets().then(
      ({ body, previewOn }) => set({ presets: body, previewOn }, false),
      (err) => {
        if (guard(err)) return;
        if (err instanceof NoGenerationError) set({ loadError: NOT_LOADED_YET }, false);
        else if (!custom) set({ loadError: "The ready-made portfolios could not be loaded. Reload to try again." }, false);
      },
    );
    void fetchHealth().then(
      (health) => deriveStaleness(health),
      (err) => {
        if (!guard(err)) void presetsJob.then(() => deriveStaleness(null));
      },
    );
    const symbolsJob = ensureSymbols();
    if (custom) {
      // The catalog tells which of the URL's funds have verified current data before the one POST.
      await symbolsJob;
    } else {
      await presetsJob;
      if (halted || !state.presets) return;
      const preset = state.presets.presets.find((p) => p.id === state.preset) ?? state.presets.presets[0];
      if (!preset) return;
      adoptPreset(preset, unitInUrl);
      emit();
    }
    await load(state.lookback);
  }

  /** A change to the menu or its caps: drop per-menu data and load the current lookback again. */
  function menuChanged(patch: Partial<State>) {
    pendingUrlR = false;
    set({ ...patch, ghostTensors: {}, unavailable: {}, menuError: null });
    void load(state.lookback);
    for (const g of state.ghosts) void loadGhost(g);
  }

  function dispatch(action: Action): void {
    switch (action.type) {
      case "start":
        void start();
        return;
      case "riskSlider": {
        if (!Number.isFinite(action.s)) return;
        haveR = true;
        // Review focus 4: when the position leaves an "auto" neighbourhood nothing else changes;
        // the diversification default follows s by itself because t stays "auto".
        set({ s: action.s });
        return;
      }
      case "divSlider":
        if (!Number.isFinite(action.t)) return;
        set({ t: Math.min(1, Math.max(0, action.t)) });
        return;
      case "resetDiv":
        set({ t: "auto" });
        return;
      case "setLookback": {
        if (!LOOKBACKS.includes(action.lookback) || state.unavailable[action.lookback]) return;
        if (action.lookback === state.lookback && state.build.status !== "idle") return;
        const previous = state.tensorLookback;
        failures = 0;
        set({ lookback: action.lookback });
        void load(action.lookback, { previous });
        return;
      }
      case "retryBuild":
        if (state.build.status !== "build-retry") return;
        void load(state.lookback, { retry: true, previous: state.tensorLookback });
        return;
      case "selectPreset": {
        const preset = state.presets?.presets.find((p) => p.id === action.id);
        if (!preset) return;
        failures = 0;
        adoptPreset(preset, false);
        // A new menu starts at its own default position (spec 4.9), with the suggested point.
        state = { ...state, tensor: null, tensorLookback: null, caps: [], t: "auto" };
        menuChanged({});
        return;
      }
      case "setTheme":
        if (!isTheme(action.theme)) return;
        try {
          globalThis.localStorage?.setItem(THEME_KEY, action.theme);
        } catch {
          // storage unavailable: the URL still carries the theme
        }
        set({ theme: action.theme });
        return;
      case "setDetails":
        set({ details: action.details });
        return;
      case "toggleGhost": {
        if (action.lookback === state.lookback || !LOOKBACKS.includes(action.lookback)) return;
        const on = state.ghosts.includes(action.lookback);
        set({ ghosts: on ? state.ghosts.filter((g) => g !== action.lookback) : [...state.ghosts, action.lookback] });
        if (!on) void loadGhost(action.lookback);
        return;
      }
      case "loadGhosts":
        for (const g of state.ghosts) void loadGhost(g);
        return;
      case "loadSymbols":
        void ensureSymbols();
        return;
      case "setUnit": {
        // The address omits `unit=pct` (spec 8.1), so a preset that arrives in another unit could
        // not reopen in percent: in that one case the menu is written out as a custom one.
        const own = activePreset();
        const lost = own !== null && action.unit === "pct" && (unitOfPreset(own) ?? "pct") !== "pct";
        set(lost ? { unit: action.unit, preset: null } : { unit: action.unit });
        return;
      }
      case "setAmount": {
        // Amounts describe "the mix you entered" only; the tensor depends on the funds and caps,
        // so no request follows. An edited preset becomes a custom menu in the URL (spec 8.1).
        const rows = state.rows.map((r) => (r.id === action.id ? { ...r, amount: action.amount } : r));
        set({ rows, preset: null });
        return;
      }
      case "useMenu": {
        const rows = action.rows.slice(0, MAX_FUNDS);
        if (rows.length < MIN_FUNDS) return;
        const sameFunds = menuKey(rows, []) === menuKey(state.rows, []);
        if (sameFunds) {
          set({ rows, preset: null });
          return;
        }
        failures = 0;
        const ids = new Set(rows.map((r) => r.id));
        state = { ...state, tensor: null, tensorLookback: null, t: "auto" };
        menuChanged({ rows, preset: null, caps: state.caps.filter((c) => ids.has(c.id)) });
        return;
      }
      case "setCaps": {
        failures = 0;
        if (menuKey(state.rows, action.caps) === menuKey(state.rows, state.caps)) return;
        // Caps change the tensor but not the menu: keep the view while the new one loads.
        set({ caps: action.caps, ghostTensors: {}, unavailable: {}, menuError: null });
        // A cap policy is always sent, the all-default one included, so the server is the judge.
        void load(state.lookback, { previous: state.tensorLookback, fresh: true });
        for (const g of state.ghosts) void loadGhost(g);
        return;
      }
      case "flushUrl":
        if (halted || !started) return;
        if (urlTimer !== null) clearTimeout(urlTimer);
        urlTimer = null;
        writeUrl();
        return;
    }
  }

  return {
    getState: () => state,
    dispatch,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
