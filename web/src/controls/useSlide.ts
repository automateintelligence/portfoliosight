import { useCallback, useRef, type PointerEvent as ReactPointerEvent } from "react";
import { useHold } from "../state/interaction";

/**
 * Pointer drag on a slider track: calls `onPoint(clientX, clientY)` on press and on every move.
 * The drag is an interaction in progress for the whole app from the press until it is released,
 * cancelled or loses capture (so the Funds table holds its order meanwhile).
 */
export function useSlide(onPoint: (clientX: number, clientY: number) => void, disabled: boolean) {
  const active = useRef(false);
  const hold = useHold();
  const onPointerDown = useCallback(
    (e: ReactPointerEvent<HTMLElement>) => {
      if (disabled || (e.pointerType === "mouse" && e.button !== 0)) return;
      active.current = true;
      hold.pointer(e.pointerId);
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch {
        // capture is a convenience; the drag still works while the pointer stays on the track
      }
      e.currentTarget.focus({ preventScroll: true });
      onPoint(e.clientX, e.clientY);
    },
    [disabled, onPoint, hold],
  );
  const onPointerMove = useCallback(
    (e: ReactPointerEvent<HTMLElement>) => {
      if (active.current && !disabled) onPoint(e.clientX, e.clientY);
    },
    [disabled, onPoint],
  );
  const end = useCallback(() => {
    active.current = false;
    hold.endPointer();
  }, [hold]);
  return { onPointerDown, onPointerMove, onPointerUp: end, onPointerCancel: end, onLostPointerCapture: end };
}
