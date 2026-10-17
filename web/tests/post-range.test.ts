// POST /api/range (engines spec 7): the body names the engine only when it is not the tensor's
// default, the answer carries `engine` and `loss_sources: null`, and an answer for another engine
// is never shown as this one's.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { postRange } from "../src/api/http";

const key = { generation: "2026-10-16-0.3.0", hash: "a".repeat(16), lookback: "5y" };
const W = [0.25, 0.75];
let sent: { url: string; body: Record<string, unknown> }[] = [];
let answer: () => Response;

beforeEach(() => {
  sent = [];
  answer = () => new Response(JSON.stringify({ bad: -0.1, typical: 0.04, good: 0.2 }), { status: 200 });
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    sent.push({ url, body: JSON.parse(init.body as string) });
    return answer();
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("postRange", () => {
  it("sends the body as before when no engine is named: tensor key and weights only", async () => {
    const range = await postRange(key, W, null);
    expect(range).toEqual({ low: -0.1, typical: 0.04, high: 0.2 });
    expect(sent).toHaveLength(1);
    expect(sent[0].url).toBe("/api/range");
    expect(sent[0].body).toEqual({ generation: key.generation, hash: key.hash, lookback: "5y", weights: W });
    expect(Object.keys(sent[0].body)).not.toContain("engine");
  });

  it("names the engine when it is not the default", async () => {
    answer = () => new Response(JSON.stringify({ engine: "garch", bad: -0.2, typical: 0.03, good: 0.25, loss_sources: null }), { status: 200 });
    expect(await postRange(key, W, "garch")).toEqual({ low: -0.2, typical: 0.03, high: 0.25 });
    expect(sent[0].body).toEqual({ generation: key.generation, hash: key.hash, lookback: "5y", weights: W, engine: "garch" });
  });

  it("tolerates the answer's engine and loss_sources when none was asked for, and a null block", async () => {
    answer = () => new Response(JSON.stringify({ engine: "replay", bad: -0.1, typical: 0.04, good: 0.2, loss_sources: null }), { status: 200 });
    expect(await postRange(key, W, null)).toEqual({ low: -0.1, typical: 0.04, high: 0.2 });
    answer = () => new Response(JSON.stringify({ bad: -0.1, typical: 0.04, good: 0.2, loss_sources: { n_eff: 3.2, top: [], hedges: [] } }), { status: 200 });
    expect(await postRange(key, W, null)).toEqual({ low: -0.1, typical: 0.04, high: 0.2 });
  });

  it("does not show another engine's answer as the one asked for", async () => {
    answer = () => new Response(JSON.stringify({ engine: "replay", bad: -0.1, typical: 0.04, good: 0.2, loss_sources: null }), { status: 200 });
    expect(await postRange(key, W, "garch")).toBeNull();
    // a service that ignores the field (it names no engine) cannot vouch for the figure either
    answer = () => new Response(JSON.stringify({ bad: -0.1, typical: 0.04, good: 0.2 }), { status: 200 });
    expect(await postRange(key, W, "garch")).toBeNull();
  });

  it("cannot answer on a refusal, an unknown engine in the answer, or a broken body", async () => {
    answer = () => new Response(JSON.stringify({ error: { code: "range_unavailable" } }), { status: 409 });
    expect(await postRange(key, W, "garch")).toBeNull();
    answer = () => new Response(JSON.stringify({ error: { code: "invalid_request" } }), { status: 422 });
    expect(await postRange(key, W, "garch")).toBeNull();
    answer = () => new Response(JSON.stringify({ engine: "vine", bad: -0.1, typical: 0.04, good: 0.2 }), { status: 200 });
    expect(await postRange(key, W, null)).toBeNull();
    answer = () => new Response("nope", { status: 200 });
    expect(await postRange(key, W, null)).toBeNull();
  });
});
