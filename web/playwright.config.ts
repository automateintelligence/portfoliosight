import { defineConfig, devices } from "@playwright/test";

// Two kinds of run share this file.
//
// Local (`npm run e2e:local`, `npm run screenshots`): the built site under `vite preview`, with
// /api proxied to mock/server.mjs. Loopback only, no gate header.
//
// Production smoke (`scripts/smoke.sh`, `scripts/smoke_preview.sh`; projects chromium-desktop
// and chromium-phone): the specs of e2e/smoke.spec.ts and e2e/preview.spec.ts against
// PS_BASE_URL. The gate header is put on by a route for the site's own origin only (e2e/helpers.ts),
// never by `extraHTTPHeaders`; traces, video, HAR and automatic screenshots stay off because they
// could carry the header, and the reporter redacts every line it prints.
//   PS_SMOKE=1          a production run: no local servers are started.
//   PS_SMOKE_DRY_RUN=1  the same specs against the local preview and mock, without the header.
const PREVIEW_PORT = Number(process.env.PS_PREVIEW_PORT || 4179);
const MOCK_PORT = Number(process.env.PS_MOCK_PORT || 8791);
const localURL = `http://127.0.0.1:${PREVIEW_PORT}`;
const production = process.env.PS_SMOKE === "1";
const dryRun = process.env.PS_SMOKE_DRY_RUN === "1";
const smokeURL = dryRun ? localURL : process.env.PS_BASE_URL || "https://portfoliosight.ai";

const desktop = { browserName: "chromium" as const, viewport: { width: 1366, height: 900 } };
const phone = { ...devices["iPhone 13"], browserName: "chromium" as const };
const quiet = { trace: "off" as const, video: "off" as const, screenshot: "off" as const };
const smokeSpecs = /(smoke|preview)\.spec\.ts/;
// Not for the phone: checks that never open a page or that are about the desktop layout, and the
// ones that cost a build, a provider request or an email (each runs once, on the desktop).
const desktopOnly = /DoD-(02|03|12|14|18|2[1-9]|3[01])\b|private preview/;

export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e/artifacts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 90_000,
  // Whenever a secret is in the environment, nothing but the redacting reporter prints.
  reporter: production || dryRun || process.env.PS_GATE_SECRET ? [["./e2e/redacting-reporter.ts"]] : [["list"]],
  use: { baseURL: localURL, ...quiet },
  projects: [
    { name: "local-desktop", testDir: "e2e/local", testIgnore: /screenshots\.spec\.ts/, use: desktop },
    // Checks of desktop-only layout (the strip's bar, the sidebar) carry @desktop-only in their title.
    { name: "local-phone", testDir: "e2e/local", testIgnore: /screenshots\.spec\.ts/, grepInvert: /@desktop-only/, use: phone },
    { name: "shots-desktop", testDir: "e2e/local", testMatch: /screenshots\.spec\.ts/, use: desktop },
    // The owner-feedback views are desktop views; the phone project takes the first screens only.
    { name: "shots-phone", testDir: "e2e/local", testMatch: /screenshots\.spec\.ts/, grepInvert: /owner feedback 1 views/, use: phone },
    // DoD 4 is the phone layout: it runs only on the phone.
    { name: "chromium-desktop", testMatch: smokeSpecs, grepInvert: /DoD-04\b/, use: { ...desktop, ...quiet, baseURL: smokeURL } },
    { name: "chromium-phone", testMatch: smokeSpecs, grepInvert: desktopOnly, use: { ...phone, ...quiet, baseURL: smokeURL } },
  ],
  webServer: production
    ? undefined
    : [
        {
          command: `node mock/server.mjs`,
          env: { PS_MOCK_PORT: String(MOCK_PORT) },
          url: `http://127.0.0.1:${MOCK_PORT}/api/health`,
          reuseExistingServer: false,
        },
        {
          command: `npx vite preview --host 127.0.0.1 --port ${PREVIEW_PORT} --strictPort`,
          env: { PS_MOCK_PORT: String(MOCK_PORT) },
          url: localURL,
          reuseExistingServer: false,
        },
      ],
});
