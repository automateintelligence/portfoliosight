// The selected mix's card can be pinned open (owner direction 2026-10-16). A click or tap on the
// selected point pins it; a second one, a press outside the chart and the sliders, or Escape
// unpins it. A press that travels further than CLICK_SLOP is a drag of the point, never a click.

/** px of pointer travel after which a press on the selected point is a drag, not a click. */
export const CLICK_SLOP = 6;

export type PinState = {
  pinned: boolean;
  /** The press in progress on the selected point: where it began, and whether it became a drag. */
  press: { x0: number; y0: number; dragged: boolean } | null;
};

export type PinEvent =
  | { type: "press"; x: number; y: number }
  | { type: "move"; x: number; y: number }
  | { type: "release" }
  | { type: "cancel" }
  | { type: "outside" }
  | { type: "escape" }
  | { type: "key" };

export const PIN_START: PinState = { pinned: false, press: null };

/** One step of the pin state machine. Returns the same object when nothing changes. */
export function pinStep(state: PinState, event: PinEvent): PinState {
  switch (event.type) {
    case "press":
      return { ...state, press: { x0: event.x, y0: event.y, dragged: false } };
    case "move": {
      const p = state.press;
      if (!p || p.dragged) return state;
      if (Math.hypot(event.x - p.x0, event.y - p.y0) < CLICK_SLOP) return state;
      return { ...state, press: { ...p, dragged: true } };
    }
    case "release": {
      const p = state.press;
      if (!p) return state;
      return { pinned: p.dragged ? state.pinned : !state.pinned, press: null };
    }
    case "cancel":
      return state.press ? { ...state, press: null } : state;
    case "outside":
    case "escape":
      return state.pinned ? { ...state, pinned: false } : state;
    case "key":
      return { ...state, pinned: !state.pinned };
  }
}

/** Elements a press on which keeps the card pinned: the chart frame, both sliders, the details toggle. */
export const KEEPS_PIN = "[data-keeps-pin]";

export type Box = { left: number; top: number; width: number; height: number };
export type Corner = "top-left" | "top-right" | "bottom-left" | "bottom-right";

/** Gap between the pinned card and the plot's edges (wide charts) or the chart frame's (phones). */
export const PIN_INSET = 6;
export const PIN_INSET_PHONE = 4;
/** How far around the selected point's centre the card must stay clear (the drawn reticle). */
export const POINT_CLEAR = 14;
export const PIN_WIDTH = { desktop: 260, phone: 340 } as const;
const CORNERS: Corner[] = ["top-left", "top-right", "bottom-left", "bottom-right"];

const covers = (b: Box, px: number, py: number) =>
  px + POINT_CLEAR > b.left && px - POINT_CLEAR < b.left + b.width && py + POINT_CLEAR > b.top && py - POINT_CLEAR < b.top + b.height;

/**
 * Where the pinned card sits: in a corner of an area, the plot (inset PIN_INSET) on a wide chart
 * and the whole chart frame (inset PIN_INSET_PHONE, over the axis titles) on a phone, where the
 * plot alone is too small for it. Its width is the card's own, capped to the area, so it never
 * leaves the chart. It goes to the first of top-left, top-right, bottom-left, bottom-right that
 * keeps the selected point clear (POINT_CLEAR px around its centre); if none does, to the corner
 * whose centre is farthest from the point. On a wide chart the top-left, above the frontier, is
 * always clear in practice, so the card stays there.
 */
export function pinnedPlacement(
  chart: { width: number; height: number; plot: { left: number; right: number; top: number; bottom: number } },
  card: { width: number; height: number },
  point: { px: number; py: number },
  phone = false,
): Box & { corner: Corner; clear: boolean } {
  const { plot } = chart;
  const area = phone
    ? { l: PIN_INSET_PHONE, t: PIN_INSET_PHONE, r: chart.width - PIN_INSET_PHONE, b: chart.height - PIN_INSET_PHONE }
    : { l: plot.left + PIN_INSET, t: plot.top + PIN_INSET, r: Math.min(plot.right, chart.width - PIN_INSET) - PIN_INSET, b: plot.bottom - PIN_INSET };
  const width = Math.max(0, Math.min(card.width, area.r - area.l));
  const height = Math.min(card.height, Math.max(0, (phone ? area.b : chart.height - PIN_INSET) - area.t));
  const left = { l: area.l, r: Math.max(area.l, area.r - width) };
  const top = { t: area.t, b: Math.max(area.t, area.b - height) };
  const at = (c: Corner): Box & { corner: Corner; clear: boolean } => ({
    corner: c,
    clear: true,
    left: c.endsWith("left") ? left.l : left.r,
    top: c.startsWith("top") ? top.t : top.b,
    width,
    height,
  });
  const boxes = CORNERS.map(at);
  const clear = boxes.find((b) => !covers(b, point.px, point.py));
  if (clear) return clear;
  const dist = (b: Box) => Math.hypot(b.left + b.width / 2 - point.px, b.top + b.height / 2 - point.py);
  return { ...boxes.reduce((best, b) => (dist(b) > dist(best) ? b : best)), clear: false };
}

/** True when two boxes share any area. */
export const intersects = (a: Box, b: Box) => a.left < b.left + b.width && b.left < a.left + a.width && a.top < b.top + b.height && b.top < a.top + a.height;

/**
 * Where a hover card goes when a card is pinned: its preferred place, else mirrored to the other
 * side of the pointer, else under (or over) the pinned card; null when every place would sit on
 * the pinned card, so the two never stack.
 */
export function avoidPinned(preferred: Box, pinned: Box | null, pointer: { px: number; py: number }, room: { width: number; height: number }): Box | null {
  if (!pinned || !intersects(preferred, pinned)) return preferred;
  const fit = (b: Box): Box => ({
    ...b,
    left: Math.max(4, Math.min(b.left, room.width - b.width - 4)),
    top: Math.max(4, Math.min(b.top, room.height - b.height - 4)),
  });
  const mirrored = fit({ ...preferred, left: preferred.left > pointer.px ? pointer.px - 18 - preferred.width : pointer.px + 18 });
  const below = fit({ ...preferred, top: pinned.top + pinned.height + 8 });
  const above = fit({ ...preferred, top: pinned.top - 8 - preferred.height });
  return [mirrored, below, above].find((b) => !intersects(b, pinned)) ?? null;
}
