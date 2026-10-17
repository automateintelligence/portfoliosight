import { engineNames } from "../copy";
import type { EngineId } from "../state/url";

/**
 * Which simulation produced the figures beside it (engines spec 6): a small muted tag, always
 * shown and never a headline. The little mark before the name is decoration only.
 */
export function EngineTag({ engine }: { engine: EngineId }) {
  return (
    <span className="engine-tag" data-testid="engine-tag" data-engine={engine}>
      <span className="engine-mark" aria-hidden="true" />
      {engineNames[engine]}
    </span>
  );
}
