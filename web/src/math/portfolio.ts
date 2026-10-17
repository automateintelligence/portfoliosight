// Browser-side math over one tensor (spec 4.6, 4.9, 4.10, 4.11). Every statistic is recomputed
// from the tensor's moments; every mix is a convex combination of mixes the engine computed.
// Nothing here clips or renormalizes weights. The interpolation walks each column's ladder
// (`tensor.ladder`) and mirrors `interpolate` and `_ladder_mix` in portfoliosight/engine/surface.py.
import type { Tensor } from "../api/tensor";
import type { EngineId } from "../state/url";
import { carries, defaultEngine, safeStart } from "./engines";

export type Stats = { mu: number; sigma: number; enb: number };
/** A one-year range (spec 4.9): the bad, typical and good year (2.5th, 50th, 97.5th percentiles). */
export type YearRange = { low: number; typical: number; high: number };
/** The textbook bell-curve figure: `mu -+ 1.96 sigma` around `mu`, for the details only. */
export type NormalRange = { low: number; mid: number; high: number };
export type Curve = { sigma: number[]; mu: number[] };
export type Domain = { s_safe: number; s_max: number };
export type DiversificationWord = "Good" | "Average" | "Fair" | "Poor";

export interface PortfolioMath {
  /** Yearly expected return, yearly standard deviation and ENB of weights `w` (`enb` is NaN for a mix without variance). */
  stats(w: ArrayLike<number>): Stats;
  /**
   * The one-year range at `(s, t)` read off the tensor's node ranges for `engine`, blended exactly as `interpolate` blends the mixes. Exact at a column's levels; between them a blend of exact figures. The engine's own `ladder.ranges[engine]`; the kept `ladder.range` for the tensor's default engine (and so for every engine on a schema 2 tensor, or one the tensor does not carry). Without `engine`, the tensor's default.
   */
  yearRange(s: number, t: number, engine?: EngineId): YearRange;
  /** The bell-curve figure of a mix with yearly `(mu, sigma)`: `mu -+ 1.96 sigma`. */
  normalRange(mu: number, sigma: number): NormalRange;
  /** The mix at risk position `s` in `[0, nx - 1]` and diversification position `t` in `[0, 1]` (0 = frontier mix, 1 = the peak, the most diversified mix found at that risk). */
  interpolate(s: number, t: number): number[];
  /** Actual `(sigma, mu)` of the frontier mix at 8 sub-steps per column gap, recomputed from `frontier.w`. The same object on every call: do not mutate. */
  frontierCurve(): Curve;
  /** The risk slider's domain: `s_safe` is the tensor's `frontier.ranges[engine].s_safe` (`frontier.s_safe` for the default engine; the engine reads it off the one-year range, which needs the return history), `s_max = nx - 1`. The same object on every call for the same engine. */
  riskSliderDomain(engine?: EngineId): Domain;
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

function normalRange(mu: number, sigma: number): NormalRange {
  const spread = RANGE_Z * sigma;
  return { low: mu - spread, mid: mu, high: mu + spread };
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

  // Where fraction t falls on column j's ladder. Level l of L sits at t = l / (L - 1); between two
  // levels the blend is straight, except across a hop, where the upper level holds up to the
  // middle of the step and the lower one from there on.
  function step(j: number, t: number): { level: number; share: number } {
    const last = ladder.w[j].length - 1;
    const position = t * last;
    const level = Math.min(Math.floor(position), last - 1);
    const share = position - level;
    return { level, share: ladder.hop[j][level] ? (share < 0.5 ? 0 : 1) : share };
  }

  function ladderMix(j: number, t: number): Mix {
    const { level, share } = step(j, t);
    return lerp(ladder.w[j][level], ladder.w[j][level + 1], share);
  }

  // The engine whose figures answer: the one asked for when the tensor carries it, else the default.
  const standard = defaultEngine(tensor);
  const engineOf = (asked: EngineId | undefined): EngineId => (asked !== undefined && carries(tensor, asked) ? asked : standard);
  const figuresOf = (engine: EngineId) => (engine === standard ? ladder.range : (ladder.ranges?.[engine] ?? ladder.range));

  function columnRange(j: number, t: number, engine: EngineId): YearRange {
    const { level, share } = step(j, t);
    const at = (rows: number[][]) => (1 - share) * rows[j][level] + share * rows[j][level + 1];
    const { bad, typical, good } = figuresOf(engine);
    return { low: at(bad), typical: at(typical), high: at(good) };
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
  // one domain object per engine, so a caller can hold on to it
  const domains = new Map<EngineId, Domain>();
  const domainOf = (engine: EngineId): Domain => {
    let domain = domains.get(engine);
    if (!domain) {
      domain = { s_safe: safeStart(tensor, engine), s_max: nx - 1 };
      domains.set(engine, domain);
    }
    return domain;
  };
  const domain = domainOf(standard);

  return {
    stats,
    yearRange(s, t, engine) {
      if (!(t >= 0 && t <= 1)) throw new RangeError(`diversification position ${t} is outside [0, 1]`);
      const { j, lam } = split(s);
      const id = engineOf(engine);
      const a = columnRange(j, t, id);
      const b = columnRange(j + 1, t, id);
      return { low: (1 - lam) * a.low + lam * b.low, typical: (1 - lam) * a.typical + lam * b.typical, high: (1 - lam) * a.high + lam * b.high };
    },
    normalRange,
    interpolate,
    frontierCurve: () => curve,
    riskSliderDomain: (engine) => domainOf(engineOf(engine)),
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
