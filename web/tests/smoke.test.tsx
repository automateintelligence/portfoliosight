// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "../src/App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("renders the chart container", () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: false, media: query, addEventListener: () => undefined, removeEventListener: () => undefined }));
  render(<App />);
  expect(screen.getByTestId("chart")).toBeTruthy();
});
