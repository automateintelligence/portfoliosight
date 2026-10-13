"""A-PS-54 — the page loads with the header on both viewports.

Claim: with `x-ps-gate: $PS_GATE_SECRET`, `GET https://portfoliosight.ai/` returns 200 and
`chart-canvas` is visible within 5 s on chromium-desktop (1366x900) and chromium-phone
("iPhone 13"), and the page's `/api/presets` response carries `x-ps-source: r2`.

Playwright leg run from pytest against production (standard library only, no virtualenv needed).
Environment: `PS_GATE_SECRET` (read by the embedded spec from `process.env`, never printed).

Pinned interface (the product must provide exactly this):
- `web/package.json` and `web/node_modules/.bin/playwright` (Playwright with chromium installed).
- `https://portfoliosight.ai/` answers 200 to a request that carries the `x-ps-gate` header, with
  no `cf-mitigated` header and without the text "PortfolioSight is in private preview".
- `data-testid="chart-canvas"` is a `<canvas>` that is visible within 5 s and painted (the heatmap).
- The page itself requests `/api/presets`; that response is 200 with `x-ps-source: r2`.
"""

# ruff: noqa: E501

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
BASE_URL = "https://portfoliosight.ai"

# "desktop" = chromium 1366x900, "phone" = chromium with the "iPhone 13" device profile.
PROJECTS = ("desktop", "phone")

CONFIG_TS = r"""
import { defineConfig, devices } from "@playwright/test";

const all = {
  desktop: { name: "desktop", use: { browserName: "chromium" as const, viewport: { width: 1366, height: 900 } } },
  phone: { name: "phone", use: { ...devices["iPhone 13"], browserName: "chromium" as const } },
};
const wanted = (process.env.PS_GATE_PROJECTS || "desktop").split(",");

export default defineConfig({
  testDir: ".",
  testMatch: process.env.PS_GATE_SPEC,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 120_000,
  outputDir: process.env.PS_GATE_OUTPUT,
  reporter: [["json", { outputFile: process.env.PS_GATE_REPORT }]],
  use: { baseURL: process.env.PS_GATE_BASE_URL },
  projects: wanted.map((name) => (all as any)[name]),
});
"""

# The whole Playwright spec lives in this frozen test; it is written to web/e2e/__gate__/ for
# the run and removed afterwards. The gate header is set inside the spec from the environment.
SPEC_TS = r"""
import { expect, test } from "@playwright/test";

test.use({ extraHTTPHeaders: { "x-ps-gate": process.env.PS_GATE_SECRET! } });

const siteHost = new URL(process.env.PS_GATE_BASE_URL!).hostname;

// 20 sample points (5 columns x 4 rows) over the chart canvas, read back through an offscreen
// 2D canvas so the check does not depend on the product canvas's own context type.
async function distinctColors(page: any): Promise<number> {
  return await page.getByTestId("chart-canvas").evaluate((el: HTMLCanvasElement) => {
    const w = el.width, h = el.height;
    if (!w || !h) return 0;
    const copy = document.createElement("canvas");
    copy.width = w; copy.height = h;
    const ctx = copy.getContext("2d")!;
    ctx.drawImage(el, 0, 0);
    const seen = new Set<string>();
    let samples = 0;
    for (const fx of [0.15, 0.325, 0.5, 0.675, 0.85]) {
      for (const fy of [0.2, 0.4, 0.6, 0.8]) {
        const d = ctx.getImageData(Math.floor(fx * w), Math.floor(fy * h), 1, 1).data;
        seen.add(`${d[0]},${d[1]},${d[2]},${d[3]}`);
        samples += 1;
      }
    }
    return samples === 20 ? seen.size : 0;
  });
}

test("page loads with the gate header", async ({ page, context }) => {
  expect(process.env.PS_GATE_SECRET, "PS_GATE_SECRET must be set").toBeTruthy();
  expect((await context.cookies()).length, "the context must start with no cookies").toBe(0);

  const presets: { status: number; source: string | undefined; mitigated: string | undefined }[] = [];
  const mitigated: string[] = [];
  page.on("response", (response: any) => {
    const url = new URL(response.url());
    const headers = response.headers();
    if (url.hostname === siteHost && headers["cf-mitigated"]) mitigated.push(url.pathname);
    if (url.hostname === siteHost && url.pathname === "/api/presets") {
      presets.push({ status: response.status(), source: headers["x-ps-source"], mitigated: headers["cf-mitigated"] });
    }
  });

  const started = Date.now();
  const nav = await page.goto("/", { waitUntil: "commit" });
  expect(nav, "navigation produced no response").not.toBeNull();
  expect(nav!.status(), "navigation status").not.toBe(403);
  expect(nav!.status(), "navigation status").toBe(200);
  expect(nav!.headers()["cf-mitigated"], "challenge on the navigation with the header present").toBeUndefined();
  expect(new URL(page.url()).hostname, "the page left the site host").toBe(siteHost);

  // chart-canvas visible within 5 s of the start of the navigation
  const left = Math.max(1, 5000 - (Date.now() - started));
  await expect(page.getByTestId("chart-canvas")).toBeVisible({ timeout: left });
  expect(Date.now() - started, "chart-canvas took longer than 5 s").toBeLessThanOrEqual(5500);

  // must-not-contain: the private-preview page or a challenge page with the header present
  await expect(page.getByText("PortfolioSight is in private preview")).toHaveCount(0);
  expect(await page.title()).not.toMatch(/just a moment/i);

  // the page's own /api/presets response: 200 from R2
  await expect.poll(() => presets.length, { timeout: 10_000, message: "no /api/presets response was logged" }).toBeGreaterThanOrEqual(1);
  for (const entry of presets) {
    expect(entry.status, "/api/presets status").toBe(200);
    expect(entry.source, "/api/presets x-ps-source").not.toBe("origin");
    expect(entry.source, "/api/presets x-ps-source").toBe("r2");
  }

  // the canvas is not blank: at least 3 distinct colors over 20 samples
  await expect.poll(() => distinctColors(page), { timeout: 10_000, message: "the chart canvas is blank (fewer than 3 distinct colors over 20 samples)" }).toBeGreaterThanOrEqual(3);
  expect(await distinctColors(page), "blank canvas").not.toBeLessThan(3);
  expect(mitigated, "responses carrying cf-mitigated with the header present").toEqual([]);
});
"""
EXPECTED_TITLES = {"page loads with the gate header"}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(port: int, proc: subprocess.Popen, seconds: float = 60.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and proc.poll() is None:
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.25)
    return False


def _run_playwright(
    name: str,
    spec_ts: str,
    projects: tuple[str, ...],
    base_url: str | None = None,
    extra_env: dict[str, str] | None = None,
    timeout: int = 900,
) -> dict[tuple[str, str], str]:
    """Run one embedded Playwright spec and return {(project, test title): status}.

    base_url=None: build the site and serve it with `vite preview` on a free local port (the
    spec mocks /api/* itself with page.route). Otherwise run against base_url (production).
    """
    assert (WEB / "package.json").is_file(), (
        "web/package.json is missing: the front end is not built yet"
    )
    bin_dir = WEB / "node_modules" / ".bin"
    assert (bin_dir / "playwright").exists(), (
        "web/node_modules/.bin/playwright is missing: run `npm ci` in web/"
    )
    preview = None
    gate_dir = WEB / "e2e" / "__gate__"
    spec = gate_dir / f"{name}.spec.ts"
    config = gate_dir / f"{name}.config.ts"
    report = None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.json"
        try:
            if base_url is None:
                assert (bin_dir / "vite").exists(), (
                    "web/node_modules/.bin/vite is missing: run `npm ci` in web/"
                )
                build = subprocess.run(
                    ["npm", "run", "build"], cwd=WEB, capture_output=True, text=True, timeout=600
                )
                assert build.returncode == 0, (
                    f"`npm run build` failed in web/:\n{build.stdout[-3000:]}{build.stderr[-3000:]}"
                )
                port = _free_port()
                preview = subprocess.Popen(
                    [
                        str(bin_dir / "vite"),
                        "preview",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--strictPort",
                    ],
                    cwd=WEB,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )
                assert _wait_for_port(port, preview), (
                    "`vite preview` did not start listening within 60 s"
                )
                base_url = f"http://127.0.0.1:{port}"
            gate_dir.mkdir(parents=True, exist_ok=True)
            spec.write_text(spec_ts, encoding="utf-8")
            config.write_text(CONFIG_TS, encoding="utf-8")
            env = dict(
                os.environ,
                PS_GATE_ROOT=str(ROOT),
                PS_GATE_BASE_URL=base_url,
                PS_GATE_REPORT=str(out),
                PS_GATE_OUTPUT=str(Path(tmp) / "results"),
                PS_GATE_SPEC=spec.name,
                PS_GATE_PROJECTS=",".join(projects),
                **(extra_env or {}),
            )
            proc = subprocess.run(
                [str(bin_dir / "playwright"), "test", "--config", f"e2e/__gate__/{config.name}"],
                cwd=WEB,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if out.exists():
                report = json.loads(out.read_text(encoding="utf-8"))
        finally:
            if preview is not None:
                preview.terminate()
                try:
                    preview.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    preview.kill()
            spec.unlink(missing_ok=True)
            config.unlink(missing_ok=True)
            if gate_dir.is_dir() and not any(gate_dir.iterdir()):
                gate_dir.rmdir()
    tail = proc.stdout[-6000:] + proc.stderr[-3000:]
    assert report is not None, f"Playwright wrote no JSON report:\n{tail}"
    statuses: dict[tuple[str, str], str] = {}

    def walk(suite: dict) -> None:
        for case in suite.get("specs", []):
            for run in case.get("tests", []):
                results = run.get("results", [])
                for result in results:
                    for error in result.get("errors", []):
                        print(
                            f"[{run.get('projectName')}] {case['title']}: {error.get('message', '')[:3000]}"
                        )
                final = results[-1]["status"] if results else "not-run"
                statuses[(run.get("projectName", ""), case["title"])] = (
                    final if len(results) == 1 else "retried"
                )
        for child in suite.get("suites", []):
            walk(child)

    for suite in report.get("suites", []):
        walk(suite)
    for error in report.get("errors", []):
        print("playwright error:", error.get("message", "")[:3000])
    return statuses


def test_a_ps_54_page_loads_with_header_on_both_viewports():
    if not os.environ.get("PS_GATE_SECRET", "").strip():
        pytest.fail(
            "A-PS-54 red: environment variable PS_GATE_SECRET is not set "
            "(the caller loads ~/.secrets/portfoliosight.env)"
        )
    statuses = _run_playwright("a_ps_54", SPEC_TS, PROJECTS, base_url=BASE_URL)
    expected = {(project, title) for project in PROJECTS for title in EXPECTED_TITLES}
    assert set(statuses) == expected, f"Playwright ran a different set of tests: {sorted(statuses)}"
    not_passed = {key: status for key, status in statuses.items() if status != "passed"}
    assert not not_passed, (
        f"Playwright legs not passed (failed, skipped, timed out or retried): {not_passed}"
    )
