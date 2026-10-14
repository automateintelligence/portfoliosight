// Browser-side math over one tensor (spec 4.6, 4.9, 4.10, 4.11). Every statistic is recomputed
// from the tensor's moments; every mix is a convex combination of mixes the engine computed.
// Nothing here clips or renormalizes weights. The interpolation walks each column's ladder
// (`tensor.ladder`) and mirrors `interpolate` and `_ladder_mix` in portfoliosight/engine/surface.py.
import type { Tensor } from "../api/tensor";

export type Stats = { mu: number; sigma: number; enb: number };
export type Range6m = { low: number; typical: number; high: number };
export type Curve = { sigma: number[]; mu: number[] };
export type Domain = { s_safe: number; s_max: number };
export type DiversificationWord = "Good" | "Average" | "Fair" | "Poor";

export interface PortfolioMath {
  /** Yearly expected return, yearly standard deviation and ENB of weights `w` (`enb` is NaN for a mix without variance). */
  stats(w: ArrayLike<number>): Stats;
  /** Six-month range of a mix with yearly `(mu, sigma)`: `mu/2 -+ 1.96 * sigma/sqrt(2)`. */
  range6m(mu: number, sigma: number): Range6m;
  /** The mix at risk position `s` in `[0, nx - 1]` and diversification position `t` in `[0, 1]` (0 = frontier mix, 1 = the peak, the most diversified mix found at that risk). */
  interpolate(s: number, t: number): number[];
  /** Actual `(sigma, mu)` of the frontier mix at 8 sub-steps per column gap, recomputed from `frontier.w`. The same object on every call: do not mutate. */
  frontierCurve(): Curve;
  /** The risk slider's domain: `s_safe` is the tensor's `frontier.s_safe` (the engine reads it off the one-year range, which needs the return history), `s_max = nx - 1`. The same object on every call. */
  riskSliderDomain(): Domain;
  /** The diversification slider's default at `s`: `tSug` interpolated between the two neighbouring columns. */
  tAuto(s: number): number;
  /** The risk ceiling `X(s)`, interpolated between the two neighbouring columns. */
  ceiling(s: number): number;
  /** True where `interpolate(s, t)` is the same mix for every `t`: every column that carries weight at `s` is collapsed (`ladder.collapsed`). */
  ladderCollapsed(s: number): boolean;
  /** Column `j`'s suggested point as a position on its ladder: `ladder.t_suggested[j]` (0 for a collapsed ladder). */
  tSug(j: number): number;
  /** The most diversified mix at `s`: the neighbouring columns' peaks (the last ladder level), combined like `interpolate(s, 1)`. */
  mostDiversified(s: number): number[];
  /** The position whose ceiling `X(s)` equals `sigma`, clamped into the risk slider's domain (spec 4.9, the initial position for a current mix). */
  sAtCeiling(sigma: number): number;
}

const SUBSTEPS = 8;
const RANGE_Z = 1.96;

type Mix = ArrayLike<number>;

const lerp = (a: Mix, b: Mix, f: number): number[] => Array.from(a, (v, i) => (1 - f) * v + f * b[i]);

function range6m(mu: number, sigma: number): Range6m {
  const typical = mu / 2;
  const spread = (RANGE_Z * sigma) / Math.SQRT2;
  return { low: typical - spread, typical, high: typical + spread };
}

/** The word for `q = ENB(w) / enb_ref` (spec 4.6). */
export function diversificationWord(q: number): DiversificationWord {
  if (q >= 0.75) return "Good";
  if (q >= 0.5) return "Average";
  if (q >= 0.3) return "Fair";
  return "Poor";
}

/**
 * A mix's return over one stress window (spec 4.10): `sum(w_i r_i) / sum(w_i)` over the funds
 * that have a return. `covered` is their share of the weight; below half of it `value` is `null`.
 */
export function stressReturn(w: ArrayLike<number>, r: ArrayLike<number | null>): { value: number | null; covered: number } {
  let total = 0;
  let held = 0;
  let gained = 0;
  for (let i = 0; i < w.length; i++) {
    total += w[i];
    const ri = r[i];
    if (typeof ri === "number") {
      held += w[i];
      gained += w[i] * ri;
    }
  }
  const covered = total > 0 ? held / total : 0;
  return { value: covered >= 0.5 ? gained / held : null, covered };
}

export function portfolioMath(tensor: Tensor): PortfolioMath {
  const { frontier, ladder } = tensor;
  const n = tensor.mu_s.length;
  const nx = frontier.x.length;
  const mu = Float64Array.from(tensor.mu_s);
  const cov = Float64Array.from(tensor.cov.flat());
  const invT = Float64Array.from(tensor.torsion_inv_t.flat());
  const lambda = Float64Array.from(tensor.torsion_lambda);

  function stats(w: ArrayLike<number>): Stats {
    if (w.length !== n) throw new RangeError(`a mix of this menu has ${n} weights, got ${w.length}`);
    let mean = 0;
    let variance = 0;
    for (let i = 0; i < n; i++) {
      let row = 0;
      for (let k = 0; k < n; k++) row += cov[i * n + k] * w[k];
      variance += w[i] * row;
      mean += mu[i] * w[i];
    }
    let entropy = 0;
    for (let i = 0; i < n; i++) {
      let exposure = 0;
      for (let k = 0; k < n; k++) exposure += invT[i * n + k] * w[k];
      const share = (lambda[i] * exposure * exposure) / variance;
      if (share > 0) entropy -= share * Math.log(share);
    }
    return { mu: mean, sigma: Math.sqrt(variance), enb: variance > 0 ? Math.exp(entropy) : Number.NaN };
  }

  const peaks: Mix[] = ladder.w.map((levels) => levels[levels.length - 1]);

  // Column j's mix at fraction t of its ladder. Level l of L sits at t = l / (L - 1); between two
  // levels the mix is their straight blend, except across a hop, where the upper level holds up
  // to the middle of the step and the lower one from there on.
  function ladderMix(j: number, t: number): Mix {
    const levels = ladder.w[j];
    const last = levels.length - 1;
    const position = t * last;
    const level = Math.min(Math.floor(position), last - 1);
    let share = position - level;
    if (ladder.hop[j][level]) share = share < 0.5 ? 0 : 1;
    return lerp(levels[level], levels[level + 1], share);
  }

  function split(s: number): { j: number; lam: number } {
    if (!(s >= 0 && s <= nx - 1)) throw new RangeError(`risk position ${s} is outside [0, ${nx - 1}]`);
    const j = Math.min(Math.floor(s), nx - 2);
    return { j, lam: s - j };
  }

  function between(rows: Mix[], s: number): number[] {
    const { j, lam } = split(s);
    return lerp(rows[j], rows[j + 1], lam);
  }

  function interpolate(s: number, t: number): number[] {
    if (!(t >= 0 && t <= 1)) throw new RangeError(`diversification position ${t} is outside [0, 1]`);
    const { j, lam } = split(s);
    return lerp(ladderMix(j, t), ladderMix(j + 1, t), lam);
  }

  function tSug(j: number): number {
    if (!(j >= 0 && j < nx)) throw new RangeError(`column ${j} is outside [0, ${nx - 1}]`);
    return ladder.collapsed[j] ? 0 : ladder.t_suggested[j];
  }

  const curve: Curve = { sigma: [], mu: [] };
  for (let i = 0; i <= (nx - 1) * SUBSTEPS; i++) {
    const point = stats(between(frontier.w, i / SUBSTEPS));
    curve.sigma.push(point.sigma);
    curve.mu.push(point.mu);
  }
  const domain: Domain = { s_safe: frontier.s_safe, s_max: nx - 1 };

  return {
    stats,
    range6m,
    interpolate,
    frontierCurve: () => curve,
    riskSliderDomain: () => domain,
    tAuto(s) {
      const { j, lam } = split(s);
      return (1 - lam) * tSug(j) + lam * tSug(j + 1);
    },
    ceiling(s) {
      const { j, lam } = split(s);
      return (1 - lam) * frontier.x[j] + lam * frontier.x[j + 1];
    },
    ladderCollapsed(s) {
      const { j, lam } = split(s);
      return (lam === 1 || ladder.collapsed[j]) && (lam === 0 || ladder.collapsed[j + 1]);
    },
    tSug,
    mostDiversified: (s) => between(peaks, s),
    sAtCeiling(sigma) {
      const x = frontier.x;
      let j = nx - 2;
      while (j > 0 && sigma < x[j]) j--;
      const width = x[j + 1] - x[j];
      const s = width > 0 ? j + (sigma - x[j]) / width : j;
      return Math.min(Math.max(s, domain.s_safe), domain.s_max);
    },
  };
}
