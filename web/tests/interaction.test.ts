// @vitest-environment jsdom
// The app-level "interaction in progress" signal (a drag of a slider or of the chart's point, or a
// held key on one): sources begin and end it, and a pointer or key that is let go anywhere ends it.
import { describe, expect, it, vi } from "vitest";
import { createInteraction } from "../src/state/interaction";

const release = (type: "pointerup" | "pointercancel", pointerId: number) => {
  const e = new Event(type, { bubbles: true });
  Object.defineProperty(e, "pointerId", { value: pointerId });
  document.body.dispatchEvent(e);
};
const keyUp = (key = "ArrowRight") => document.body.dispatchEvent(new KeyboardEvent("keyup", { key, bubbles: true }));

describe("interaction signal", () => {
  it("is idle until a source begins and idle again when the source ends", () => {
    const sig = createInteraction();
    expect(sig.active()).toBe(false);
    sig.beginPointer("risk", 1);
    expect(sig.active()).toBe(true);
    sig.end("risk");
    expect(sig.active()).toBe(false);
  });

  it("stays active while any source is, and beginning or ending twice changes nothing", () => {
    const sig = createInteraction();
    sig.beginPointer("risk", 1);
    sig.beginPointer("risk", 1);
    sig.beginKey("div");
    sig.end("risk");
    expect(sig.active()).toBe(true);
    sig.end("risk");
    expect(sig.active()).toBe(true);
    sig.end("div");
    expect(sig.active()).toBe(false);
    sig.end("div");
    expect(sig.active()).toBe(false);
  });

  it("tells subscribers only when it turns on or off, and stops telling after they leave", () => {
    const sig = createInteraction();
    const heard = vi.fn();
    const leave = sig.subscribe(heard);
    sig.beginPointer("a", 1);
    sig.beginKey("b");
    expect(heard).toHaveBeenCalledTimes(1);
    sig.end("a");
    expect(heard).toHaveBeenCalledTimes(1);
    sig.end("b");
    expect(heard).toHaveBeenCalledTimes(2);
    leave();
    sig.beginKey("c");
    expect(heard).toHaveBeenCalledTimes(2);
  });

  it("ends a pointer drag when that pointer is released or cancelled anywhere, as a backstop for a lost capture", () => {
    const sig = createInteraction();
    sig.beginPointer("risk", 7);
    release("pointerup", 3);
    expect(sig.active(), "another pointer's release").toBe(true);
    release("pointerup", 7);
    expect(sig.active()).toBe(false);
    sig.beginPointer("risk", 7);
    release("pointercancel", 7);
    expect(sig.active()).toBe(false);
  });

  it("ends a held key when any key is released, wherever the focus has gone", () => {
    const sig = createInteraction();
    sig.beginKey("risk");
    keyUp("Tab");
    expect(sig.active()).toBe(false);
    // a pointer drag is not ended by a key
    sig.beginPointer("div", 1);
    keyUp();
    expect(sig.active()).toBe(true);
    sig.end("div");
  });

  it("ends everything when the window loses focus, since a release outside it is never heard", () => {
    const sig = createInteraction();
    sig.beginPointer("a", 1);
    sig.beginKey("b");
    window.dispatchEvent(new Event("blur"));
    expect(sig.active()).toBe(false);
  });
});
