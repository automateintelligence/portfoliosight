// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { plain, rateWaitLine } from "../src/copy";

type Call = { method: string; path: string };
let calls: Call[] = [];
let tensorAnswer: () => Response;

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
const refusal = (retryAfter?: string) =>
  json(429, { error: { code: "rate_limited", message: "Too many requests; try again in a minute.", details: null } }, retryAfter === undefined ? {} : { "retry-after": retryAfter });
const posts = () => calls.filter((c) => c.method === "POST");
const seconds = (n: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(n * 1000);
  });

beforeEach(() => {
  calls = [];
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
  vi.stubGlobal("fetch", async (input: string, init?: RequestInit) => {
    const path = new URL(input, "https://portfoliosight.ai").pathname;
    calls.push({ method: (init?.method ?? "GET").toUpperCase(), path });
    if (path === "/api/presets") return json(200, { presets: [] });
    if (path === "/api/symbols") return json(200, { symbols: [{ id: "VTI" }, { id: "BND" }] });
    if (path === "/api/tensors") return tensorAnswer();
    return json(404, {});
  });
  window.history.replaceState(null, "", "/?f=VTI,BND");
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function open() {
  render(<App />);
  await seconds(0);
}

describe("the page and a build refused for too many requests", () => {
  it("shows the wait going down in plain words, then the chart's build is sent again with no click", async () => {
    let first = true;
    tensorAnswer = () => {
      if (first) {
        first = false;
        return refusal("3");
      }
      return json(202, { status: "queued", generation: "g", hash: "h", position: 0, eta_s: 5 });
    };
    await open();
    expect(screen.getByTestId("rate-wait-line").textContent).toBe(rateWaitLine(3));
    expect(screen.getByTestId("rate-wait-line").textContent).toBe("Too many charts in a minute. Trying again in 3 s.");
    expect(screen.queryByTestId("build-retry")).toBeNull();
    await seconds(1);
    expect(screen.getByTestId("rate-wait-line").textContent).toBe(rateWaitLine(2));
    await seconds(2);
    expect(posts()).toHaveLength(2);
    expect(screen.queryByTestId("rate-wait-notice")).toBeNull();
    expect(screen.getByTestId("building-notice")).toBeTruthy();
  });

  it("refused again, it shows today's Retry button with the message, and sends nothing more by itself", async () => {
    tensorAnswer = () => refusal("2");
    await open();
    await seconds(2);
    expect(posts()).toHaveLength(2);
    expect(screen.queryByTestId("rate-wait-notice")).toBeNull();
    const notice = screen.getByTestId("building-notice");
    expect(notice.textContent).toContain(plain.buildFailed);
    expect(notice.textContent).toContain(plain.rateLimited);
    expect(screen.getByTestId("build-retry").textContent).toBe(plain.retry);
    await seconds(300);
    expect(posts()).toHaveLength(2);
  });

  it("without a Retry-After it shows the Retry button with the message at once", async () => {
    tensorAnswer = () => refusal();
    await open();
    expect(screen.queryByTestId("rate-wait-notice")).toBeNull();
    expect(screen.getByTestId("building-notice").textContent).toContain(plain.rateLimited);
    expect(screen.getByTestId("build-retry")).toBeTruthy();
    await seconds(300);
    expect(posts()).toHaveLength(1);
  });

  it("leaving the page stops the countdown: nothing is sent afterwards", async () => {
    tensorAnswer = () => refusal("3");
    render(<App />);
    await seconds(0);
    await seconds(1);
    expect(screen.getByTestId("rate-wait-line").textContent).toBe(rateWaitLine(2));
    cleanup(); // the app unmounts
    await seconds(120);
    expect(posts()).toHaveLength(1);
  });

  it("the browser's pagehide stops the countdown too, and a page restored from memory shows the button", async () => {
    tensorAnswer = () => refusal("3");
    await open();
    await seconds(1);
    act(() => {
      window.dispatchEvent(new Event("pagehide"));
    });
    expect(screen.queryByTestId("rate-wait-notice")).toBeNull();
    expect(screen.getByTestId("build-retry")).toBeTruthy();
    await seconds(120);
    expect(posts()).toHaveLength(1);
  });

  it("a page that comes back from the browser's memory counts down again for a build the visitor starts", async () => {
    tensorAnswer = () => refusal("3");
    await open();
    act(() => {
      window.dispatchEvent(new Event("pagehide"));
    });
    expect(screen.getByTestId("build-retry")).toBeTruthy();
    act(() => {
      window.dispatchEvent(new Event("pageshow"));
    });
    await act(async () => {
      screen.getByTestId("build-retry").click();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(posts()).toHaveLength(2);
    expect(screen.getByTestId("rate-wait-line").textContent).toBe(rateWaitLine(3));
  });

  it("the screen reader is told once; the per-second line is kept out of the live region", async () => {
    tensorAnswer = () => refusal("3");
    await open();
    const line = screen.getByTestId("rate-wait-line");
    const live = screen.getByTestId("rate-wait-live");
    expect(line.getAttribute("aria-hidden")).toBe("true");
    expect(live.getAttribute("role")).toBe("status");
    expect(live.textContent).toBe(plain.rateWaiting);
    await seconds(2);
    expect(screen.getByTestId("rate-wait-line").textContent).toBe(rateWaitLine(1));
    expect(screen.getByTestId("rate-wait-live").textContent, "the announced text does not change with the count").toBe(plain.rateWaiting);
    expect(screen.getByTestId("rate-wait-notice").getAttribute("role")).toBeNull();
  });
});
