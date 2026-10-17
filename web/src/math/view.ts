// What the first screen shows for one slider position, derived from the tensor with the
// browser math of spec 4.9 and 4.11. Pure; statistics are recomputed, never interpolated.
import type { Tensor } from "../api/tensor";
import type { EngineId } from "../state/url";
import { diversificationWord, portfolioMath, type NormalRange, type YearRange } from "./portfolio";

export type PMath = ReturnType<typeof portfolioMath>;
export type Stats = { mu: number; sigma: number; enb: number };
/** A one-year range: the bad, typical and good year (spec 4.9). */
export type Range = YearRange;

const lerp = (arr: number[], pos: number) => {
  const i = Math.min(Math.max(0, Math.floor(pos)), arr.length - 2);
  const f = pos - i;
  return (1 - f) * arr[i] + f * arr[i + 1];
};

/** The risk ceiling X(s) = (1 − λ)·X_j + λ·X_{j+1} (spec 4.9). */
export const ceilingAt = (tensor: Tensor, s: number): number => lerp(tensor.frontier.x, s);

/** The column position whose ceiling equals `sigma` (columns are uniform in risk), unclamped. */
export function positionOfCeiling(tensor: Tensor, sigma: number): number {
  const x = tensor.frontier.x;
  const n = x.length - 1;
  const span = x[n] - x[0];
  return span > 0 ? ((sigma - x[0]) / span) * n : 0;
}

/** True when the diversification slider cannot move the mix: every contributing ladder is collapsed. */
export function ladderCollapsedAt(tensor: Tensor, s: number): boolean {
  const collapsed = tensor.ladder.collapsed;
  const j = Math.min(Math.max(0, Math.floor(s)), collapsed.length - 2);
  const lam = s - j;
  if (lam <= 1e-12) return collapsed[j];
  if (lam >= 1 - 1e-12) return collapsed[j + 1];
  return collapsed[j] && collapsed[j + 1];
}

/** Return of the drawn frontier at risk `sigma` (for the top of the dashed ceiling line). */
export function frontierMuAt(curve: { sigma: number[]; mu: number[] }, sigma: number): number {
  const n = curve.sigma.length;
  if (sigma <= curve.sigma[0]) return curve.mu[0];
  for (let i = 1; i < n; i++) {
    if (curve.sigma[i] >= sigma) {
      const span = curve.sigma[i] - curve.sigma[i - 1];
      const f = span > 0 ? (sigma - curve.sigma[i - 1]) / span : 0;
      return (1 - f) * curve.mu[i - 1] + f * curve.mu[i];
    }
  }
  return curve.mu[n - 1];
}

/**
 * Whether the menu's limits change its frontier: the frontier with every limit lifted
 * (`frontier_uncapped`) reaches further in risk or earns more at some node's risk. Limits that
 * never bind leave the two frontiers the same, and then there is no "No limits" line to draw.
 */
export function limitsBind(tensor: Tensor): boolean {
  const free = tensor.frontier_uncapped;
  const { x, y } = tensor.frontier;
  if (free.sigma.length === 0 || x.length === 0) return false;
  if (Math.abs(free.sigma[0] - x[0]) > 1e-6 || Math.abs(free.sigma[free.sigma.length - 1] - x[x.length - 1]) > 1e-6) return true;
  return x.some((sigma, j) => frontierMuAt(free, sigma) - y[j] > 1e-4);
}

export type View = {
  s: number;
  t: number;
  tAuto: number;
  moved: boolean;
  disabled: boolean;
  domain: { s_safe: number; s_max: number };
  ceiling: number;
  ceilingMu: number;
  weights: number[];
  selected: Stats;
  /** The selected mix's one-year range: from the service for these exact weights when it has answered, else the tensor's node ranges blended to (s, t). */
  range: Range;
  /** The selected mix's bell-curve figure (details only). */
  normal: NormalRange;
  front: Stats;
  frontRange: Range;
  /** The Optimized mix at this risk (the open circle, where the second slider starts): ladder position t_auto(s). */
  optimized: Stats;
  optWeights: number[];
  optRange: Range;
  /** The most diversified mix found at this risk (t = 1): the far end of the second slider. */
  peak: Stats;
  word: ReturnType<typeof diversificationWord>;
};

/**
 * Everything the first screen needs at slider position (s, t | "auto") under one engine (the
 * tensor's default when none is given): the engine's slider domain and one-year ranges, and the
 * same mixes and statistics for every engine. About a millisecond.
 */
export function deriveView(tensor: Tensor, math: PMath, sIn: number, tSetting: number | "auto", engine?: EngineId): View {
  const domain = math.riskSliderDomain(engine);
  const s = Math.min(domain.s_max, Math.max(domain.s_safe, sIn));
  const disabled = ladderCollapsedAt(tensor, s);
  const tAuto = disabled ? 0 : math.tAuto(s);
  const t = disabled ? 0 : tSetting === "auto" ? tAuto : Math.min(1, Math.max(0, tSetting));
  const weights = math.interpolate(s, t);
  const selected = math.stats(weights);
  const front = math.stats(math.interpolate(s, 0));
  const optWeights = math.interpolate(s, tAuto);
  const optimized = math.stats(optWeights);
  const ceiling = ceilingAt(tensor, s);
  return {
    s,
    t,
    tAuto,
    moved: tSetting !== "auto",
    disabled,
    domain,
    ceiling,
    ceilingMu: frontierMuAt(tensor.frontier_curve, ceiling),
    weights,
    selected,
    range: math.yearRange(s, t, engine),
    normal: math.normalRange(selected.mu, selected.sigma),
    front,
    frontRange: math.yearRange(s, 0, engine),
    optimized,
    optWeights,
    optRange: math.yearRange(s, tAuto, engine),
    peak: math.stats(math.interpolate(s, 1)),
    word: diversificationWord(selected.enb / tensor.enb_ref),
  };
}

/** True where (s, t) sits on a column and one of its ladder levels: the node ranges are then exact. */
export function atNode(tensor: Tensor, s: number, t: number): boolean {
  const levels = tensor.ladder.w[0]?.length ?? 2;
  const near = (v: number) => Math.abs(v - Math.round(v)) <= 1e-9;
  return near(s) && near(t * (levels - 1));
}
