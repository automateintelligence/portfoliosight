// What the first screen shows for one slider position, derived from the tensor with the
// browser math of spec 4.9 and 4.11. Pure; statistics are recomputed, never interpolated.
import type { Tensor } from "../api/tensor";
import { diversificationWord, portfolioMath } from "./portfolio";

export type PMath = ReturnType<typeof portfolioMath>;
export type Stats = { mu: number; sigma: number; enb: number };
export type Range = { low: number; typical: number; high: number };

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
  const k = tensor.grid.k_div;
  const j = Math.min(Math.max(0, Math.floor(s)), k.length - 2);
  const lam = s - j;
  if (lam <= 1e-12) return k[j] < 0;
  if (lam >= 1 - 1e-12) return k[j + 1] < 0;
  return k[j] < 0 && k[j + 1] < 0;
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
  range: Range;
  front: Stats;
  frontRange: Range;
  mostDiversified: Stats;
  /** Weights of the most diversified mix at this risk (the open circle). */
  divWeights: number[];
  divRange: Range;
  word: ReturnType<typeof diversificationWord>;
};

/** Everything the first screen needs at slider position (s, t | "auto"). About a millisecond. */
export function deriveView(tensor: Tensor, math: PMath, sIn: number, tSetting: number | "auto"): View {
  const domain = math.riskSliderDomain();
  const s = Math.min(domain.s_max, Math.max(domain.s_safe, sIn));
  const disabled = ladderCollapsedAt(tensor, s);
  const tAuto = math.tAuto(s);
  const t = disabled ? 0 : tSetting === "auto" ? tAuto : Math.min(1, Math.max(0, tSetting));
  const weights = math.interpolate(s, t);
  const selected = math.stats(weights);
  const front = math.stats(math.interpolate(s, 0));
  const divWeights = math.interpolate(s, 1);
  const mostDiversified = math.stats(divWeights);
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
    range: math.range6m(selected.mu, selected.sigma),
    front,
    frontRange: math.range6m(front.mu, front.sigma),
    mostDiversified,
    divWeights,
    divRange: math.range6m(mostDiversified.mu, mostDiversified.sigma),
    word: diversificationWord(selected.enb / tensor.enb_ref),
  };
}
