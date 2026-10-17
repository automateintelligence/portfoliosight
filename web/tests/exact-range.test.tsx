// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const postRange = vi.fn();
vi.mock("../src/api/http", () => ({ postRange: (...args: unknown[]) => postRange(...args) }));

const { SETTLE_MS, forgetExactRanges, useExactRange } = await import("../src/state/useExactRange");

const key = { generation: "g1", hash: "a".repeat(64), lookback: "5y" };
const answerFor = (w: ArrayLike<number>) => ({ low: -w[0], typical: w[0] / 2, high: w[0] });

beforeEach(() => {
  vi.useFakeTimers();
  forgetExactRanges();
  postRange.mockReset();
  postRange.mockImplementation(async (_k: unknown, w: ArrayLike<number>) => answerFor(w));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const settle = () => act(async () => {
  await vi.advanceTimersByTimeAsync(SETTLE_MS + 1);
});

it("asks nothing without weights or a tensor", async () => {
  const { result } = renderHook(({ k, w }) => useExactRange(k, w), { initialProps: { k: key as typeof key | null, w: null as number[] | null } });
  await settle();
  expect(result.current).toBeNull();
  expect(postRange).not.toHaveBeenCalled();
});

it("asks once the weights rest, shows the answer, and serves the same mix from memory", async () => {
  const { result } = renderHook(() => useExactRange(key, [0.2, 0.8]));
  expect(result.current).toBeNull();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(SETTLE_MS - 50);
  });
  expect(postRange).not.toHaveBeenCalled();
  await settle();
  expect(postRange).toHaveBeenCalledTimes(1);
  expect(result.current).toEqual(answerFor([0.2]));
  const again = renderHook(() => useExactRange(key, [0.2, 0.8]));
  expect(again.result.current).toEqual(answerFor([0.2]));
  await settle();
  expect(postRange).toHaveBeenCalledTimes(1);
});

it("a move before the weights rest drops the earlier mix, and a late answer for it is not shown", async () => {
  let release: (v: unknown) => void = () => undefined;
  postRange.mockImplementationOnce((_k: unknown, _w: unknown, _e: unknown, signal: AbortSignal) => new Promise((resolve) => {
    release = resolve;
    signal.addEventListener("abort", () => resolve(null));
  }));
  const { result, rerender } = renderHook(({ w }) => useExactRange(key, w), { initialProps: { w: [0.1, 0.9] } });
  await settle();
  expect(postRange).toHaveBeenCalledTimes(1);
  rerender({ w: [0.3, 0.7] });
  release(answerFor([0.1]));
  await settle();
  expect(postRange).toHaveBeenCalledTimes(2);
  expect(postRange.mock.calls[1][1]).toEqual([0.3, 0.7]);
  expect(result.current).toEqual(answerFor([0.3]));
});

it("remembers that the service could not answer and does not ask again", async () => {
  postRange.mockResolvedValue(null);
  const { result, rerender } = renderHook(({ w }) => useExactRange(key, w), { initialProps: { w: [0.5, 0.5] } });
  await settle();
  expect(result.current).toBeNull();
  rerender({ w: [0.4, 0.6] });
  await settle();
  rerender({ w: [0.5, 0.5] });
  await settle();
  expect(postRange).toHaveBeenCalledTimes(2);
});

it("a mix that stays on screen keeps its answer after many other mixes have been asked", async () => {
  const held = renderHook(() => useExactRange(key, [0.25, 0.75]));
  await settle();
  expect(held.result.current).toEqual(answerFor([0.25]));
  const other = renderHook(({ w }) => useExactRange(key, w), { initialProps: { w: [0.001, 0.999] } });
  for (let i = 1; i <= 70; i++) {
    other.rerender({ w: [i / 1000, 1 - i / 1000] });
    await settle();
  }
  held.rerender();
  expect(held.result.current).toEqual(answerFor([0.25]));
});

it("asks the default engine with no engine named, and another engine by name", async () => {
  renderHook(() => useExactRange(key, [0.2, 0.8]));
  renderHook(() => useExactRange(key, [0.2, 0.8], "garch"));
  await settle();
  expect(postRange).toHaveBeenCalledTimes(2);
  expect(postRange.mock.calls.map((call) => call[2]).sort()).toEqual(["garch", null]);
});

it("keeps one answer per engine: the same mix under another engine is asked again and never served from the first", async () => {
  postRange.mockImplementation(async (_k: unknown, w: ArrayLike<number>, engine: string | null) => ({ ...answerFor(w), typical: engine === "garch" ? -1 : 1 }));
  const { result, rerender } = renderHook(({ e }) => useExactRange(key, [0.2, 0.8], e), { initialProps: { e: null as "garch" | null } });
  await settle();
  expect(result.current?.typical).toBe(1);
  rerender({ e: "garch" });
  // until the answer for the new engine arrives, the old engine's figure is not shown
  expect(result.current).toBeNull();
  await settle();
  expect(postRange).toHaveBeenCalledTimes(2);
  expect(result.current?.typical).toBe(-1);
  rerender({ e: null });
  expect(result.current?.typical).toBe(1);
  await settle();
  expect(postRange).toHaveBeenCalledTimes(2);
});

it("an answer that arrives after the engine changed is dropped", async () => {
  let release: (v: unknown) => void = () => undefined;
  postRange.mockImplementationOnce(() => new Promise((resolve) => (release = resolve)));
  const { result, rerender } = renderHook(({ e }) => useExactRange(key, [0.2, 0.8], e), { initialProps: { e: null as "garch" | null } });
  await settle();
  rerender({ e: "garch" });
  release({ low: 9, typical: 9, high: 9 });
  await settle();
  expect(result.current).toEqual(answerFor([0.2]));
});
