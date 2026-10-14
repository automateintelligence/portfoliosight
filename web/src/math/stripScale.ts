// The scale of the "Selected mix" strip's bar: one fixed range per menu, so the bar does not jump
// as the sliders or the history window move. Pure.
import type { Tensor } from "../api/tensor";

/** Bad and Good one-year returns bounding every mix a tensor carries. */
export type Bounds = { min: number; max: number };
/** The bar's scale: `lo` at its left end, `hi` at its right. */
export type StripScale = { lo: number; hi: number };
/** What the page has seen of one menu: its hash, the tensors already counted and their bounds. */
export type StripSeen = { hash: string; keys: string[]; bounds: Bounds };

/** Share of the span added at each end, so no marker sits on the bar's edge. */
export const STRIP_PAD = 0.06;

const finite = (values: Iterable<number>, pick: (a: number, b: number) => number, start: number) => {
  let out = start;
  for (const v of values) if (Number.isFinite(v)) out = pick(out, v);
  return out;
};

/**
 * The lowest Bad and the highest Good year over every mix a tensor carries a range for: the
 * frontier nodes, every ladder node (the most diversified mixes at its top end) and the mix
 * entered, when the tensor has one.
 */
export function tensorBounds(tensor: Tensor): Bounds {
  const bad = [...tensor.frontier.range.bad, ...tensor.ladder.range.bad.flat()];
  const good = [...tensor.frontier.range.good, ...tensor.ladder.range.good.flat()];
  if (tensor.entered) {
    bad.push(tensor.entered.range.bad);
    good.push(tensor.entered.range.good);
  }
  return { min: finite(bad, Math.min, Infinity), max: finite(good, Math.max, -Infinity) };
}

const tensorKey = (tensor: Tensor) => `${tensor.lookback.id}|${tensor.generation}`;

/**
 * Folds the tensors on hand into what was seen of their menu. A tensor of another menu starts
 * over; a tensor already counted changes nothing (the same object comes back, so React keeps it).
 * Tensors of a menu other than the first one given are left out.
 */
export function widenSeen(prev: StripSeen | null, tensors: Tensor[]): StripSeen | null {
  if (tensors.length === 0) return prev;
  const hash = tensors[0].universe.hash;
  let seen: StripSeen | null = prev && prev.hash === hash ? prev : null;
  for (const tensor of tensors) {
    if (tensor.universe.hash !== hash) continue;
    const key = tensorKey(tensor);
    if (seen?.keys.includes(key)) continue;
    const b = tensorBounds(tensor);
    seen = {
      hash,
      keys: [...(seen?.keys ?? []), key],
      bounds: { min: Math.min(seen?.bounds.min ?? Infinity, b.min), max: Math.max(seen?.bounds.max ?? -Infinity, b.max) },
    };
  }
  return seen;
}

/**
 * Widens what was seen by figures shown on the strip that lie outside it (an exact range from the
 * service can step past the node figures), so the bar keeps that width for the rest of the menu
 * instead of shrinking back. Values inside change nothing (the same object comes back).
 */
export function widenBy(seen: StripSeen | null, values: number[]): StripSeen | null {
  if (!seen) return seen;
  const vs = values.filter(Number.isFinite);
  const min = Math.min(seen.bounds.min, ...vs);
  const max = Math.max(seen.bounds.max, ...vs);
  return min === seen.bounds.min && max === seen.bounds.max ? seen : { ...seen, bounds: { min, max } };
}

/**
 * The bar's scale: the menu's bounds and 0% (always on the bar), widened by any shown value that
 * lies outside them (an exact range from the service can step past the node figures), with
 * `STRIP_PAD` of the span added at each end.
 */
export function stripScale(bounds: Bounds | null, shown: number[]): StripScale {
  let min = Math.min(0, bounds?.min ?? 0, ...shown.filter(Number.isFinite));
  let max = Math.max(0, bounds?.max ?? 0, ...shown.filter(Number.isFinite));
  if (!(max > min)) {
    min -= 0.01;
    max += 0.01;
  }
  const pad = (max - min) * STRIP_PAD;
  return { lo: min - pad, hi: max + pad };
}

/** Where `value` sits along the bar, from 0 (left end) to 1 (right end). */
export const stripAt = (scale: StripScale, value: number) => (value - scale.lo) / (scale.hi - scale.lo);
