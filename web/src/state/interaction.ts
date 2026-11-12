import { createContext, useContext, useEffect, useId, useMemo, useSyncExternalStore } from "react";

/**
 * The app-level "interaction in progress" signal (owner direction 2026-11-11): on while a slider or
 * the chart's point is being dragged, or a key is held on one. The Funds table reads it so its
 * order holds still under the visitor's hand and re-sorts once, when the interaction ends.
 *
 * Sources begin it and end it by name; it is on while any source is. Beginning must come before the
 * change the interaction makes, so no render sees the new numbers with the signal still off. Three
 * backstops end a source whose own release was never heard (capture lost, focus moved, a release
 * outside the window): that pointer's release anywhere, any key's release, and the window blur.
 */
export type Interaction = {
  /** A drag by one pointer began. */
  beginPointer: (source: string, pointerId: number) => void;
  /** A key is held on a control. */
  beginKey: (source: string) => void;
  end: (source: string) => void;
  active: () => boolean;
  subscribe: (listener: () => void) => () => void;
};

type Held = { kind: "pointer"; pointerId: number } | { kind: "key" };

export function createInteraction(): Interaction {
  const held = new Map<string, Held>();
  const listeners = new Set<() => void>();
  let detach: (() => void) | null = null;

  const changed = (wasActive: boolean) => {
    if (held.size > 0 && detach === null) detach = listen();
    if (held.size === 0 && detach) {
      detach();
      detach = null;
    }
    if (wasActive !== held.size > 0) listeners.forEach((l) => l());
  };
  const endWhere = (match: (h: Held) => boolean) => {
    const was = held.size > 0;
    for (const [source, h] of [...held]) if (match(h)) held.delete(source);
    changed(was);
  };
  const listen = () => {
    const pointerOver = (e: Event) => {
      const id = (e as PointerEvent).pointerId;
      endWhere((h) => h.kind === "pointer" && h.pointerId === id);
    };
    const keyOver = () => endWhere((h) => h.kind === "key");
    const everything = () => endWhere(() => true);
    document.addEventListener("pointerup", pointerOver, true);
    document.addEventListener("pointercancel", pointerOver, true);
    document.addEventListener("keyup", keyOver, true);
    window.addEventListener("blur", everything);
    return () => {
      document.removeEventListener("pointerup", pointerOver, true);
      document.removeEventListener("pointercancel", pointerOver, true);
      document.removeEventListener("keyup", keyOver, true);
      window.removeEventListener("blur", everything);
    };
  };
  const begin = (source: string, what: Held) => {
    const was = held.size > 0;
    held.set(source, what);
    changed(was);
  };
  return {
    beginPointer: (source, pointerId) => begin(source, { kind: "pointer", pointerId }),
    beginKey: (source) => begin(source, { kind: "key" }),
    end: (source) => {
      const was = held.size > 0;
      held.delete(source);
      changed(was);
    },
    active: () => held.size > 0,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  };
}

const idle: Interaction = { beginPointer: () => undefined, beginKey: () => undefined, end: () => undefined, active: () => false, subscribe: () => () => undefined };

/** The signal the app provides; a component outside any provider (a test, a story) gets one that is never on. */
export const InteractionContext = createContext<Interaction>(idle);

/** Whether the signal is on, re-read whenever it turns on or off. */
export function useInteracting(signal: Interaction): boolean {
  return useSyncExternalStore(signal.subscribe, signal.active, () => false);
}

/**
 * One control's way of holding the signal on: `pointer` when a drag starts, `key` when a key it
 * handles goes down, `endPointer` when the drag is released, cancelled or loses capture. The key's
 * release is heard by the signal itself. Whatever is held ends when the control goes away.
 */
export function useHold() {
  const signal = useContext(InteractionContext);
  const id = useId();
  const pointerSource = `${id}:pointer`;
  const keySource = `${id}:key`;
  useEffect(
    () => () => {
      signal.end(pointerSource);
      signal.end(keySource);
    },
    [signal, pointerSource, keySource],
  );
  return useMemo(
    () => ({
      pointer: (pointerId: number) => signal.beginPointer(pointerSource, pointerId),
      key: () => signal.beginKey(keySource),
      endPointer: () => signal.end(pointerSource),
    }),
    [signal, pointerSource, keySource],
  );
}
