import { defineConfig, devices } from "@playwright/test";

// Local runs only: the built site under `vite preview`, with /api proxied to mock/server.mjs.
// Nothing here can reach production: the base URL is loopback and no gate header is set.
const PREVIEW_PORT = Number(process.env.PS_PREVIEW_PORT || 4179);
const MOCK_PORT = Number(process.env.PS_MOCK_PORT || 8791);
const baseURL = `http://127.0.0.1:${PREVIEW_PORT}`;

const desktop = { browserName: "chromium" as const, viewport: { width: 1366, height: 900 } };
const phone = { ...devices["iPhone 13"], browserName: "chromium" as const };

export default defineConfig({
  testDir: "e2e/local",
  outputDir: "e2e/artifacts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 90_000,
  reporter: [["list"]],
  use: { baseURL, trace: "off", video: "off", screenshot: "off" },
  projects: [
    { name: "local-desktop", testIgnore: /screenshots\.spec\.ts/, use: desktop },
    { name: "local-phone", testIgnore: /screenshots\.spec\.ts/, use: phone },
    { name: "shots-desktop", testMatch: /screenshots\.spec\.ts/, use: desktop },
    { name: "shots-phone", testMatch: /screenshots\.spec\.ts/, use: phone },
  ],
  webServer: [
    {
      command: `node mock/server.mjs`,
      env: { PS_MOCK_PORT: String(MOCK_PORT) },
      url: `http://127.0.0.1:${MOCK_PORT}/api/health`,
      reuseExistingServer: false,
    },
    {
      command: `npx vite preview --host 127.0.0.1 --port ${PREVIEW_PORT} --strictPort`,
      env: { PS_MOCK_PORT: String(MOCK_PORT) },
      url: baseURL,
      reuseExistingServer: false,
    },
  ],
});
