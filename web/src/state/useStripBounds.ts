import { useState } from "react";
import type { Tensor } from "../api/tensor";
import { widenBy, widenSeen, type Bounds, type StripSeen } from "../math/stripScale";

/**
 * The Bad/Good bounds of the menu on screen over every history window the page has loaded for
 * it (the window shown and the ghost windows), and over every figure the strip has shown for it
 * (`shown`). They only widen while the menu stays the same, and start over when it changes.
 */
export function useStripBounds(tensor: Tensor | null, ghosts: Partial<Record<string, Tensor>>, shown: number[]): Bounds | null {
  const [seen, setSeen] = useState<StripSeen | null>(null);
  const tensors = tensor ? [tensor, ...Object.values(ghosts).filter((g): g is Tensor => g !== undefined)] : [];
  const next = widenBy(widenSeen(seen, tensors), shown);
  // Adjusting state while rendering, from what this render was given (React's documented pattern).
  if (next !== seen) setSeen(next);
  return next?.bounds ?? null;
}
