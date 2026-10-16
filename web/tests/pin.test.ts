// The pinned card (owner direction 2026-10-16): the pin state machine, where the pinned card sits,
// how a hover card keeps off it, and fund tickers that never sit on each other.
import { describe, expect, it } from "vitest";
import { placeFundLabels } from "../src/chart/Overlay";
import { avoidPinned, CLICK_SLOP, intersects, PIN_INSET, PIN_INSET_PHONE, PIN_START, pinnedPlacement, pinStep, POINT_CLEAR, type PinEvent, type PinState } from "../src/chart/pin";
import { makeScales } from "../src/chart/scales";

const run = (events: PinEvent[], from: PinState = PIN_START) => events.reduce(pinStep, from);
const click = (x = 100, y = 100): PinEvent[] => [{ type: "press", id: 1, x, y }, { type: "release", id: 1 }];

describe("pin state machine", () => {
  it("a click pins the card and a second click unpins it", () => {
    const once = run(click());
    expect(once.pinned).toBe(true);
    expect(once.press).toBeNull();
    expect(run(click(), once).pinned).toBe(false);
  });

  it("a press that moves less than the slop is still a click", () => {
    const s = run([{ type: "press", id: 1, x: 100, y: 100 }, { type: "move", id: 1, x: 100 + CLICK_SLOP - 1, y: 100 }, { type: "release", id: 1 }]);
    expect(s.pinned).toBe(true);
  });

  it("a drag never toggles the pin, in either state", () => {
    const drag: PinEvent[] = [{ type: "press", id: 1, x: 100, y: 100 }, { type: "move", id: 1, x: 104, y: 100 }, { type: "move", id: 1, x: 140, y: 120 }, { type: "move", id: 1, x: 101, y: 100 }, { type: "release", id: 1 }];
    expect(run(drag).pinned).toBe(false);
    const pinned = run(click());
    expect(run(drag, pinned).pinned).toBe(true);
  });

  it("only the pointer that began the press moves or ends it", () => {
    const pressed = run([{ type: "press", id: 1, x: 100, y: 100 }]);
    // a second finger lands, moves and lifts: nothing changes
    expect(run([{ type: "press", id: 2, x: 300, y: 300 }, { type: "move", id: 2, x: 340, y: 300 }, { type: "release", id: 2 }], pressed)).toBe(pressed);
    expect(run([{ type: "release", id: 1 }], pressed).pinned).toBe(true);
  });

  it("uses the drag's own measure: the larger of the two travels", () => {
    expect(run([{ type: "press", id: 1, x: 0, y: 0 }, { type: "move", id: 1, x: CLICK_SLOP - 1, y: CLICK_SLOP - 1 }, { type: "release", id: 1 }]).pinned).toBe(true);
    expect(run([{ type: "press", id: 1, x: 0, y: 0 }, { type: "move", id: 1, x: 0, y: CLICK_SLOP }, { type: "release", id: 1 }]).pinned).toBe(false);
  });

  it("a cancelled press does nothing", () => {
    expect(run([{ type: "press", id: 1, x: 1, y: 1 }, { type: "cancel", id: 1 }, { type: "release", id: 1 }]).pinned).toBe(false);
  });

  it("a press outside, or Escape, unpins; neither pins", () => {
    const pinned = run(click());
    expect(pinStep(pinned, { type: "outside" }).pinned).toBe(false);
    expect(pinStep(pinned, { type: "escape" }).pinned).toBe(false);
    expect(pinStep(PIN_START, { type: "outside" })).toBe(PIN_START);
    expect(pinStep(PIN_START, { type: "escape" })).toBe(PIN_START);
  });

  it("Enter or Space on the point (one key event) toggles the pin", () => {
    const on = pinStep(PIN_START, { type: "key" });
    expect(on.pinned).toBe(true);
    expect(pinStep(on, { type: "key" }).pinned).toBe(false);
  });

  it("moves that change nothing return the same state, so nothing re-renders", () => {
    const pressed = pinStep(PIN_START, { type: "press", id: 1, x: 0, y: 0 });
    expect(pinStep(pressed, { type: "move", id: 1, x: 1, y: 1 })).toBe(pressed);
    const dragged = pinStep(pressed, { type: "move", id: 1, x: 50, y: 0 });
    expect(pinStep(dragged, { type: "move", id: 1, x: 60, y: 0 })).toBe(dragged);
    expect(pinStep(PIN_START, { type: "move", id: 1, x: 60, y: 0 })).toBe(PIN_START);
  });
});

describe("pinned card placement", () => {
  const desktop = makeScales(1040, 560, { xMin: 0, xMax: 0.3, yMin: 0, yMax: 0.2 }, false);
  const phone = makeScales(380, 380, { xMin: 0, xMax: 0.3, yMin: 0, yMax: 0.2 }, true);
  const covers = (b: { left: number; top: number; width: number; height: number }, px: number, py: number) =>
    px + POINT_CLEAR > b.left && px - POINT_CLEAR < b.left + b.width && py + POINT_CLEAR > b.top && py - POINT_CLEAR < b.top + b.height;

  it("sits in the top-left of the plot on a wide chart, whatever the point does below it", () => {
    for (const [px, py] of [[700, 400], [300, 480], [980, 70], [500, 300]]) {
      const b = pinnedPlacement(desktop, { width: 260, height: 300 }, { px, py });
      expect(b.corner).toBe("top-left");
      expect(b.left).toBe(desktop.plot.left + PIN_INSET);
      expect(b.top).toBe(desktop.plot.top + PIN_INSET);
      expect(b.width).toBe(260);
    }
  });

  it("never runs past the chart frame on a narrow chart", () => {
    const narrow = makeScales(250, 300, { xMin: 0, xMax: 0.3, yMin: 0, yMax: 0.2 }, true);
    const b = pinnedPlacement(narrow, { width: 224, height: 200 }, { px: 240, py: 290 });
    expect(b.left + b.width).toBeLessThanOrEqual(narrow.width - PIN_INSET);
    expect(b.left).toBeGreaterThanOrEqual(0);
  });

  it("goes top-right, then bottom-left, then bottom-right, when the point would be under it", () => {
    const card = { width: 224, height: 150 };
    const tl = pinnedPlacement(phone, card, { px: phone.plot.right - 10, py: phone.plot.bottom - 10 });
    expect(tl.corner).toBe("top-left");
    const tr = pinnedPlacement(phone, card, { px: phone.plot.left + 30, py: phone.plot.top + 40 });
    expect(tr.corner).toBe("top-right");
    expect(covers(tr, phone.plot.left + 30, phone.plot.top + 40)).toBe(false);
    // a point near the top in the middle is under both top corners of a wide card
    const bl = pinnedPlacement(phone, card, { px: 190, py: phone.plot.top + 30 });
    expect(bl.corner).toBe("bottom-left");
    expect(covers(bl, 190, phone.plot.top + 30)).toBe(false);
  });

  it("on a phone uses the whole chart frame, so a card as tall as half the plot still leaves a point in the middle clear", () => {
    const frame = makeScales(358, 376, { xMin: 0, xMax: 0.3, yMin: 0, yMax: 0.2 }, true);
    const card = { width: 224, height: 170 };
    for (let px = frame.plot.left; px <= frame.plot.right; px += 8)
      for (let py = frame.plot.top; py <= frame.plot.bottom; py += 8) {
        const b = pinnedPlacement(frame, card, { px, py }, true);
        expect(covers(b, px, py), `point at ${px},${py}`).toBe(false);
        expect(b.left).toBeGreaterThanOrEqual(PIN_INSET_PHONE);
        expect(b.left + b.width).toBeLessThanOrEqual(frame.width - PIN_INSET_PHONE);
        expect(b.top + b.height).toBeLessThanOrEqual(frame.height - PIN_INSET_PHONE);
      }
    expect(pinnedPlacement(frame, card, { px: 300, py: 300 }, true)).toMatchObject({ corner: "top-left", left: PIN_INSET_PHONE, top: PIN_INSET_PHONE });
    const small = makeScales(288, 300, { xMin: 0, xMax: 0.3, yMin: 0, yMax: 0.2 }, true);
    expect(pinnedPlacement(small, { width: 300, height: 170 }, { px: 250, py: 250 }, true).width).toBe(288 - 2 * PIN_INSET_PHONE);
  });

  it("takes the corner farthest from the point when every corner would cover it", () => {
    const card = { width: 300, height: 300 };
    const b = pinnedPlacement(phone, card, { px: 100, py: 100 });
    expect(["top-left", "top-right", "bottom-left", "bottom-right"]).toContain(b.corner);
    const again = pinnedPlacement(phone, card, { px: 100, py: 100 });
    expect(again).toEqual(b);
  });
});

describe("a hover card keeps off the pinned card", () => {
  const pinned = { left: 62, top: 54, width: 260, height: 300 };
  const room = { width: 1040, height: 560 };

  it("stays where it is when it does not touch the pinned card", () => {
    const pref = { left: 600, top: 200, width: 232, height: 168 };
    expect(avoidPinned(pref, pinned, { px: 582, py: 182 }, room)).toEqual(pref);
    expect(avoidPinned(pref, null, { px: 582, py: 182 }, room)).toEqual(pref);
  });

  it("moves elsewhere, or does not show, when it would sit on the pinned card", () => {
    for (const [px, py] of [[100, 100], [200, 300], [330, 80], [80, 420]]) {
      const pref = { left: px + 18, top: py + 18, width: 232, height: 168 };
      const got = avoidPinned(pref, pinned, { px, py }, room);
      if (got) expect(intersects(got, pinned)).toBe(false);
    }
  });

  it("gives way entirely when there is nowhere else", () => {
    const tight = { width: 300, height: 320 };
    const big = { left: 4, top: 4, width: 292, height: 312 };
    expect(avoidPinned({ left: 30, top: 30, width: 232, height: 168 }, big, { px: 12, py: 12 }, tight)).toBeNull();
  });
});

describe("fund tickers", () => {
  const charW = 6;
  const boxes = (placed: ReturnType<typeof placeFundLabels>) =>
    placed
      .filter((f) => f.side)
      .map((f) => {
        const w = f.id.length * charW;
        const x0 = f.side === "right" ? f.px + 5 : f.px - 5 - w;
        return { x0, x1: x0 + w, y0: f.py - 6.5, y1: f.py + 6.5 };
      });

  it("never draw two tickers on top of each other, and hide only what would touch", () => {
    // the owner's phone screenshot: VBTAX/VGSTX, TIP/AGG and SCHF/VEA/EFA nearly on one spot
    const funds = [
      { id: "VBTAX", px: 120, py: 250 },
      { id: "VGSTX", px: 124, py: 247 },
      { id: "TIP", px: 90, py: 262 },
      { id: "AGG", px: 93, py: 266 },
      { id: "SCHF", px: 230, py: 180 },
      { id: "VEA", px: 233, py: 178 },
      { id: "EFA", px: 236, py: 183 },
      { id: "VTI", px: 300, py: 90 },
    ];
    const placed = placeFundLabels(funds, 380);
    const b = boxes(placed);
    for (let i = 0; i < b.length; i++)
      for (let j = i + 1; j < b.length; j++) expect(b[i].x0 < b[j].x1 && b[j].x0 < b[i].x1 && b[i].y0 < b[j].y1 && b[j].y0 < b[i].y1).toBe(false);
    expect(placed.find((f) => f.id === "VTI")!.side).toBe("right");
    expect(placed.filter((f) => f.side === null).length).toBeGreaterThan(0);
    expect(placed.map((f) => f.id)).toEqual(funds.map((f) => f.id));
  });

  it("goes left of its dot at the right edge", () => {
    expect(placeFundLabels([{ id: "VTI", px: 370, py: 50 }], 380)[0].side).toBe("left");
  });
});
