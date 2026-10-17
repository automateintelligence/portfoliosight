// The scale of the "Selected mix" strip's bar: one fixed range per (menu, history window), taken
// from the tensor's own nodes, so the bar does not jump as the sliders move. Pure.
import type { Tensor } from "../api/tensor";
import { ENGINES } from "../state/url";

/** Bad and Good one-year returns bounding every mix a tensor carries. */
export type Bounds = { min: number; max: number };
/** The bar's scale: `lo` at its left end, `hi` at its right. */
export type StripScale = { lo: number; hi: number };

/** Share of the span added at each end, so no marker sits on the bar's edge. */
export const STRIP_PAD = 0.06;

const finite = (values: Iterable<number>, pick: (a: number, b: number) => number, start: number) => {
  let out = start;
  for (const v of values) if (Number.isFinite(v)) out = pick(out, v);
  return out;
};

/**
 * The lowest Bad and the highest Good year over every mix a tensor carries a range for, under
 * every engine it carries (engines spec 6: switching engines moves the band, not the scale): the
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
  // the kept blocks above are the default engine's; the other engines' figures sit beside them
  for (const id of ENGINES) {
    const front = tensor.frontier.ranges?.[id];
    const ladder = tensor.ladder.ranges?.[id];
    const entered = tensor.entered?.ranges?.[id];
    if (front) {
      bad.push(...front.bad);
      good.push(...front.good);
    }
    if (ladder) {
      bad.push(...ladder.bad.flat());
      good.push(...ladder.good.flat());
    }
    if (entered) {
      bad.push(entered.bad);
      good.push(entered.good);
    }
  }
  return { min: finite(bad, Math.min, Infinity), max: finite(good, Math.max, -Infinity) };
}

/**
 * The bar's scale for one tensor: its bounds (`tensorBounds`) and 0% (always on the bar), with
 * `STRIP_PAD` of the span added at each end. It depends on nothing else, so it is fixed for a
 * (menu, history window): neither the sliders, the service's exact ranges nor a ghost window's
 * tensor move it.
 */
export function stripScale(bounds: Bounds | null): StripScale {
  let min = Math.min(0, bounds?.min ?? 0);
  let max = Math.max(0, bounds?.max ?? 0);
  if (!(max > min)) {
    min -= 0.01;
    max += 0.01;
  }
  const pad = (max - min) * STRIP_PAD;
  return { lo: min - pad, hi: max + pad };
}

/** Where `value` sits along the bar, from 0 (left end) to 1 (right end). */
export const stripAt = (scale: StripScale, value: number) => (value - scale.lo) / (scale.hi - scale.lo);

/**
 * Where `value` is drawn on the bar: its place from 0 to 1, clamped to the ends, and which end it
 * runs past when it lies outside the scale (rare: an exact range is a blend of node mixes).
 */
export function stripPlace(scale: StripScale, value: number): { at: number; over: "low" | "high" | null } {
  const at = stripAt(scale, value);
  if (at < 0) return { at: 0, over: "low" };
  if (at > 1) return { at: 1, over: "high" };
  return { at, over: null };
}
