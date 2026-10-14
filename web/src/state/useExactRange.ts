// The exact one-year range of a mix, from the service (`POST /api/range`, spec 6). The page shows
// the tensor's node ranges at once and swaps in the exact figure once the weights have held
// still for a moment, so a drag never waits on the server.
import { useEffect, useState } from "react";
import { postRange, type TensorKey } from "../api/http";
import type { YearRange } from "../math/portfolio";

export const SETTLE_MS = 350;
const KEPT = 64;
// Answers by tensor and weights; `null` records that the service could not answer, so the page
// keeps its own figure and does not ask again for the same mix.
const answers = new Map<string, YearRange | null>();

const idOf = (key: TensorKey, weights: ArrayLike<number>) =>
  `${key.generation}/${key.hash}/${key.lookback}|${Array.from(weights, (w) => w.toPrecision(12)).join(",")}`;

function remember(id: string, range: YearRange | null) {
  answers.delete(id);
  answers.set(id, range);
  while (answers.size > KEPT) answers.delete(answers.keys().next().value as string);
}

/** Forgets every answer (tests). */
export function forgetExactRanges(): void {
  answers.clear();
}

/** The service's one-year range of `weights` on the tensor `key`, or `null` while there is none: not asked (no key or no weights), still settling, or not answerable. */
export function useExactRange(key: TensorKey | null, weights: ArrayLike<number> | null): YearRange | null {
  const id = key && weights ? idOf(key, weights) : null;
  // this hook's own last answer, so a mix that stays on screen keeps its figure after the shared
  // cache has moved on to other mixes
  const [held, setHeld] = useState<{ id: string; range: YearRange | null } | null>(null);
  useEffect(() => {
    if (!id || !key || !weights || answers.has(id)) return;
    const abort = new AbortController();
    const timer = setTimeout(() => {
      void postRange(key, weights, abort.signal).then((range) => {
        if (abort.signal.aborted) return;
        remember(id, range);
        setHeld({ id, range });
      });
    }, SETTLE_MS);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps -- `id` names key and weights
  if (!id) return null;
  if (answers.has(id)) return answers.get(id) ?? null;
  return held?.id === id ? held.range : null;
}
