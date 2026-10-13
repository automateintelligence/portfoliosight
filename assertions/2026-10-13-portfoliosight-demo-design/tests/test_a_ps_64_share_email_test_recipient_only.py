# ruff: noqa: E501
"""A-PS-64 — share by email sends the fixed message to the test recipient only.

Claim: with `PS_SHARE_TEST_RECIPIENT` set, opening `share-open`, entering that address only, and
clicking `share-send` makes `POST /api/share` return 202 and `share-status` read "Sent"; a
malformed address returns 400 without sending; a `url` on another host returns 400; while preview
is on the dialog shows the preview notice.

Playwright (desktop project) against https://portfoliosight.ai with the `x-ps-gate` header set
inside the embedded spec from `PS_GATE_SECRET`.

In this gate an absent `PS_SHARE_TEST_RECIPIENT` is a FAILURE (`BLOCKED: ... is not set`), not
the skip the assertion text grants the product's own smoke test: a skip would read green without
sending anything. The recipient is the only address in any request this test issues and is never
printed (comparisons are reduced to booleans before they are asserted).

Requests carrying a valid `x-ps-gate` header are exempt from the per-IP share caps (coordinator
decision; the global daily cap still applies), so this test does not depend on any per-IP
allowance: a 429 on the real send is a failure, and no per-IP cap is asserted here.

Pinned interface (the product must provide exactly this), beyond the spec 10 test ids:
- `share-open` opens an element with ARIA role `dialog` (a native <dialog> qualifies) holding
  `share-email` (an input, or a wrapper of one), `share-send` and `share-status`;
- while preview is on (A-PS-61) the dialog text matches /private preview/i;
- `POST /api/share` body `{"to", "url"}`; 202 on success; refusals are 400 with the code
  (`invalid_recipient` / `invalid_url`) at `error.code` (spec 6 envelope), or as a bare `error`
  or `code` string.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
SITE = "https://portfoliosight.ai"
PROJECTS = ("desktop",)
SECRET_NAMES = ("PS_GATE_SECRET", "PS_SHARE_TEST_RECIPIENT", "CLOUDFLARE_API_TOKEN")

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

SPEC_TS = r"""
import { expect, test, type Page } from "@playwright/test";

test.use({ extraHTTPHeaders: { "x-ps-gate": process.env.PS_GATE_SECRET ?? "" } });
test.describe.configure({ mode: "serial" });

// Never interpolate RECIPIENT into a message, a title or an expect() argument that gets printed.
const RECIPIENT = process.env.PS_SHARE_TEST_RECIPIENT ?? "";
const ORIGIN = "https://portfoliosight.ai";
const ADDRESS = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;

type Share = { to: unknown; url: unknown; raw: string; status: number | null };

function watchShares(page: Page): Share[] {
  const shares: Share[] = [];
  const pending = new Map<unknown, Share>();
  page.on("request", (request) => {
    if (request.method() !== "POST" || new URL(request.url()).pathname !== "/api/share") return;
    let body: any = null;
    try { body = request.postDataJSON(); } catch { body = null; }
    const entry: Share = { to: body?.to, url: body?.url, raw: request.postData() ?? "", status: null };
    shares.push(entry);
    pending.set(request, entry);
  });
  page.on("response", (response) => {
    const entry = pending.get(response.request());
    if (entry) entry.status = response.status();
  });
  return shares;
}

async function loadDefault(page: Page): Promise<void> {
  const response = await page.goto("/");
  expect(response?.status(), "GET / with the gate header").toBe(200);
  await expect(page.getByTestId("chart-canvas")).toBeVisible({ timeout: 15_000 });
}

function errorCode(body: any): unknown {
  if (body && typeof body.error === "object" && body.error !== null) return body.error.code;
  return body?.error ?? body?.code;
}

async function refused(page: Page, data: { to: string; url: string }, code: string): Promise<void> {
  const response = await page.request.post("/api/share", { headers: { Origin: ORIGIN }, data });
  const status = response.status();
  // Must-not-contain: a 202 for an invalid case.
  expect(status === 202, `a 202 for the ${code} case`).toBe(false);
  expect(status, `status for the ${code} case`).toBe(400);
  let body: any = null;
  try { body = await response.json(); } catch { body = null; }
  expect(errorCode(body), `error code for the ${code} case`).toBe(code);
}

test("a malformed address is refused with 400 invalid_recipient", async ({ page }) => {
  await loadDefault(page);
  const current = page.url();
  expect(new URL(current).origin).toBe(ORIGIN);
  await refused(page, { to: "not-an-address", url: current }, "invalid_recipient");
});

test("a url on another host is refused with 400 invalid_url", async ({ page }) => {
  await loadDefault(page);
  await refused(page, { to: RECIPIENT, url: "https://example.com/" }, "invalid_url");
});

test("the dialog sends to the test recipient only and reads Sent", async ({ page }) => {
  const shares = watchShares(page);
  await loadDefault(page);
  await page.getByTestId("share-open").first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(/private preview/i);

  const field = dialog.getByTestId("share-email");
  const tag = await field.evaluate((el) => el.tagName);
  const input = tag === "INPUT" ? field : field.locator("input").first();
  await input.fill(RECIPIENT);
  expect(shares.length, "share requests before Send").toBe(0);
  await dialog.getByTestId("share-send").click();

  await expect.poll(() => shares.length, { timeout: 10_000 }).toBeGreaterThanOrEqual(1);
  await expect.poll(() => shares[0].status, { timeout: 30_000 }).not.toBeNull();
  expect(shares[0].status, "POST /api/share status").toBe(202);
  await expect(dialog.getByTestId("share-status")).toHaveText("Sent", { timeout: 10_000 });
  await page.waitForTimeout(1_000);
  expect(shares.length, "POST /api/share requests for one click").toBe(1);

  const toIsRecipient = shares[0].to === RECIPIENT;
  expect(toIsRecipient, "the request's `to` equals PS_SHARE_TEST_RECIPIENT exactly").toBe(true);
  // Must-not-contain: any recipient other than the env value in any request the test issued.
  const others = shares.flatMap((share) => share.raw.match(ADDRESS) ?? []).filter((address) => address !== RECIPIENT).length;
  expect(others, "addresses other than the test recipient in share requests").toBe(0);
  const sharedUrl = new URL(String(shares[0].url));
  expect(sharedUrl.origin).toBe(ORIGIN);
  expect(sharedUrl.host).not.toBe("example.com");
});
"""
EXPECTED_TITLES = {
    "a malformed address is refused with 400 invalid_recipient",
    "a url on another host is refused with 400 invalid_url",
    "the dialog sends to the test recipient only and reads Sent",
}


def _scrub(text: str) -> str:
    """Replace every secret value by its variable name before anything is printed or asserted."""
    for name in SECRET_NAMES:
        value = os.environ.get(name, "").strip()
        if len(value) >= 4:
            text = text.replace(value, f"<{name}>")
    return text


def _env(name: str, blocked: bool = False) -> str:
    """A required environment variable; its absence is a failure that names the variable."""
    value = os.environ.get(name, "").strip()
    if not value:
        prefix = "BLOCKED: " if blocked else ""
        pytest.fail(
            f"{prefix}{name} is not set (the caller loads ~/.secrets/portfoliosight.env)",
            pytrace=False,
        )
    return value


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


def _playwright(
    name: str,
    spec_ts: str,
    titles: set[str],
    extra_env: dict[str, str] | None = None,
    timeout: int = 900,
) -> str:
    """Run the embedded spec against production; scrub secrets from everything that is shown.

    Returns the scrubbed Playwright error output. Fails unless exactly `titles` ran and passed.
    """
    captured = io.StringIO()
    statuses: dict[tuple[str, str], str] = {}
    problem = ""
    try:
        with contextlib.redirect_stdout(captured):
            statuses = _run_playwright(
                name, spec_ts, PROJECTS, base_url=SITE, extra_env=extra_env, timeout=timeout
            )
    except AssertionError as err:
        problem = str(err) or "the Playwright wrapper failed"
    except subprocess.TimeoutExpired:
        problem = f"Playwright did not finish within {timeout} s"
    except OSError as err:
        problem = f"Playwright could not be started: {type(err).__name__}: {err}"
    output = _scrub(captured.getvalue())
    print(output)
    if problem:
        pytest.fail(_scrub(problem), pytrace=False)
    blocked = re.search(r"BLOCKED: [^\n]*", output)
    if blocked:
        pytest.fail(blocked.group(0)[:300], pytrace=False)
    expected = {(project, title) for project in PROJECTS for title in titles}
    assert set(statuses) == expected, f"Playwright ran a different set of tests: {sorted(statuses)}"
    not_passed = {key: status for key, status in statuses.items() if status != "passed"}
    assert not not_passed, (
        f"Playwright legs not passed (failed, skipped, timed out or retried): {not_passed}"
    )
    return output


def test_a_ps_64_playwright():
    secret = _env("PS_GATE_SECRET")
    recipient = _env("PS_SHARE_TEST_RECIPIENT", blocked=True)
    bare = re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", recipient) is not None
    assert bare, "PS_SHARE_TEST_RECIPIENT is not one bare address (value not shown)"
    output = _playwright("a_ps_64", SPEC_TS, EXPECTED_TITLES, timeout=600)
    leaked = secret in output or recipient in output
    assert not leaked, "the gate secret or the test recipient reached the test output"
