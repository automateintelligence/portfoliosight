// Which simulation engines a tensor carries and which one a view reads (engines spec 6 and 7).
// A schema 2 tensor, and any tensor without an `engines` block, carries History replay only; its
// kept range fields hold that engine's figures, so every engine answers the default there.
import type { Tensor } from "../api/tensor";
import { ENGINES, type EngineId } from "../state/url";

/** The reason shown for an engine a tensor says nothing about (a tensor from before engines). */
export const NOT_COMPUTED = "not computed for this menu";

/** The engine the tensor's kept range fields (`frontier.range`, `ladder.range`, `entered.range`) hold. */
export const defaultEngine = (tensor: Tensor): EngineId => tensor.range_default ?? "replay";

/** Whether the tensor has ranges for `id`: the engine is ready in its `engines` block. */
export const carries = (tensor: Tensor, id: EngineId): boolean => (tensor.engines ? tensor.engines[id].status === "ready" : id === "replay");

export const carriedEngines = (tensor: Tensor): EngineId[] => ENGINES.filter((id) => carries(tensor, id));

/** Why the tensor does not carry `id`, or `null` when it does. */
export function engineReason(tensor: Tensor, id: EngineId): string | null {
  if (carries(tensor, id)) return null;
  return tensor.engines?.[id].reason ?? NOT_COMPUTED;
}

/** The engine a view reads: the one asked for when the tensor carries it, else the tensor's default. */
export const resolveEngine = (tensor: Tensor, wanted: EngineId): EngineId => (carries(tensor, wanted) ? wanted : defaultEngine(tensor));

/** The left end of the risk slider under `engine`: its own `s_safe` when the tensor carries one, else the kept `frontier.s_safe`. */
export function safeStart(tensor: Tensor, engine: EngineId): number {
  return engine === defaultEngine(tensor) ? tensor.frontier.s_safe : (tensor.frontier.ranges?.[engine]?.s_safe ?? tensor.frontier.s_safe);
}
