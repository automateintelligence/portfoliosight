"""A-PS-57 — the nightly is fresh: `asof` equals `D_G`, the run finished clean, twelve tensors exist, the cache is under its cap, and the page says which date it shows.

Claim: the current generation's `asof` equals the test's own `D_G` for the check day (the most
recent XNYS session whose close is at least 6 hours before 02:00 America/Los_Angeles of the check
day), `/api/health.nightly` shows that run finished with zero errors, the generation holds the 12
preset tensors, the KS-001 cache volume is at most 300 MB, the timer is enabled, and the page's
details line "prices through {asof}" shows the same date.

Runs from the laptop against production at or after 08:00 America/Los_Angeles (earlier runs fail
with `BLOCKED:`), inside the project virtualenv (needs `exchange_calendars`; `D_G` is computed here,
never through product code). Environment: `PS_GATE_SECRET` (never printed); optional
`PS_KS001_SSH_HOST` (default `KS-001-jeff`).

Pinned interface (the product must provide exactly this):
- `GET https://portfoliosight.ai/api/health` -> 200 `{"generation", "asof": "YYYY-MM-DD",
  "asof_trading_days_behind": int, "nightly": {"finished": ISO-8601 instant with offset or "Z",
  "D_G": "YYYY-MM-DD", "errors": [] | 0 | {}}}` (`nightly` = `meta/status.json`, spec §5.3, §6).
- `GET https://portfoliosight.ai/api/presets` -> two presets x six lookbacks, each `ready` with a
  `url`; `HEAD https://portfoliosight.ai{url}` -> 200 for all 12.
- KS-001 over ssh: container `portfoliosight-api` with the cache at `/app/cache`; systemd unit
  `portfoliosight-nightly.timer`.
- Page: clicking `data-testid="details-toggle"` turns details on; only then the page text contains
  `prices through YYYY-MM-DD` (ISO date, the tensor's `asof`).
- `web/package.json` and `web/node_modules/.bin/playwright` for the details leg.
"""

# ruff: noqa: E501

from __future__ import annotations

import http.client
import importlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
WEB = ROOT / "web"


def _project_python() -> Path | None:
    """The project's virtualenv interpreter: this checkout's, else the main checkout's (worktree)."""
    roots = [ROOT]
    dot_git = ROOT / ".git"
    if dot_git.is_file():  # linked worktree: "gitdir: <main>/.git/worktrees/<name>"
        roots.append(Path(dot_git.read_text().split(":", 1)[1].strip()).parents[2])
    for root in roots:
        candidate = root / ".venv" / "bin" / "python"
        if candidate.exists():
            return candidate
    return None


_VENV_PY = _project_python()
_OUTER = (
    os.environ.get("PS_GATE_INNER") != "1"
    and _VENV_PY is not None
    and Path(sys.prefix).resolve() != _VENV_PY.parents[1].resolve()
)


def _need(module: str):
    """Import a product (or dev-dependency) module, failing the test cleanly when it is absent."""
    try:
        return importlib.import_module(module)
    except Exception as exc:  # ImportError, or an import-time crash in the product
        pytest.fail(f"A-PS-57 red: cannot import {module}: {type(exc).__name__}: {exc}")


SITE = "https://portfoliosight.ai"
PT = ZoneInfo("America/Los_Angeles")
LOOKBACKS = {"1y", "2y", "3y", "5y", "10y", "ew"}
CACHE_CAP_MB = 300
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 portfoliosight-gate"
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


class _Resp:
    def __init__(self, status: int, headers, body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    def header(self, name: str) -> str:
        return (self.headers.get(name) or "").strip()

    def json(self, what: str):
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            pytest.fail(f"A-PS-57 red: {what} answered {self.status} with a body that is not JSON")


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(
            f"A-PS-57 red: environment variable {name} is not set "
            "(the caller loads ~/.secrets/portfoliosight.env)"
        )
    return value


def _http(method: str, url: str, *, timeout: float = 30.0) -> _Resp:
    """One request with the gate header, redirects not followed; no connection = clean failure."""
    send = {"User-Agent": UA, "Accept": "application/json", "x-ps-gate": _env("PS_GATE_SECRET")}
    request = urllib.request.Request(url, method=method, headers=send)
    try:
        with _OPENER.open(request, timeout=timeout) as raw:
            return _Resp(raw.status, raw.headers, raw.read(16_000_000))
    except urllib.error.HTTPError as err:
        try:
            body = err.read(16_000_000)
        except (OSError, http.client.HTTPException):
            body = b""
        return _Resp(err.code, err.headers, body)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as err:
        reason = getattr(err, "reason", err)
        pytest.fail(f"A-PS-57 red: cannot reach {url}: {type(err).__name__}: {reason}")


def _check_day(now: datetime | None = None) -> date:
    """The check day in Los Angeles; the assertion is only meaningful from 08:00 PT on."""
    now = (now or datetime.now(timezone.utc)).astimezone(PT)
    if now.hour < 8:
        pytest.fail(
            f"BLOCKED: A-PS-57 must run at or after 08:00 America/Los_Angeles; it is {now:%H:%M} "
            "there now (the 02:00 nightly needs time to finish)"
        )
    return now.date()


def _reference_sessions(check_day: date) -> tuple[date, date]:
    """(D_G, the session before D_G) by the spec §4.2 rule, computed here with exchange_calendars.

    D_G = the most recent XNYS session whose close is at least 6 hours before the nightly's
    scheduled start, 02:00 America/Los_Angeles on the check day.
    """
    xcals = _need("exchange_calendars")
    calendar = xcals.get_calendar("XNYS")
    start = datetime.combine(check_day, dtime(2, 0), tzinfo=PT)
    cutoff = start.astimezone(timezone.utc) - timedelta(hours=6)
    first = (check_day - timedelta(days=21)).isoformat()
    sessions = list(calendar.sessions_in_range(first, check_day.isoformat()))
    assert len(sessions) >= 8, "the XNYS calendar returned too few sessions for a three-week span"
    qualifying = []
    for session in sessions:
        close = calendar.session_close(session).to_pydatetime()
        if close.tzinfo is None:
            close = close.replace(tzinfo=timezone.utc)
        if close <= cutoff:
            qualifying.append(session.date())
    assert len(qualifying) >= 2, "no XNYS session closes 6 hours before the scheduled start"
    return qualifying[-1], qualifying[-2]


def _health() -> dict:
    resp = _http("GET", f"{SITE}/api/health")
    assert resp.status == 200, f"/api/health answered {resp.status}"
    body = resp.json("/api/health")
    assert isinstance(body, dict), "/api/health body is not a JSON object"
    return body


def _finished_day_pt(value) -> date:
    """`nightly.finished` as a Los Angeles calendar date (a bare ISO date is taken as given)."""
    assert isinstance(value, str) and value, (
        f"nightly.finished is {value!r}, expected an ISO instant"
    )
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pytest.fail(f"A-PS-57 red: nightly.finished {value!r} is not ISO-8601")
    assert instant.tzinfo is not None, f"nightly.finished {value!r} carries no UTC offset"
    return instant.astimezone(PT).date()


def _ssh(command: str) -> str:
    host = os.environ.get("PS_KS001_SSH_HOST", "KS-001-jeff")
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        pytest.fail("A-PS-57 red: the ssh client is not installed on this machine")
    except subprocess.TimeoutExpired:
        pytest.fail(f"A-PS-57 red: `{command}` over ssh to {host} did not finish within 60 s")
    if proc.returncode == 255:
        pytest.fail(f"A-PS-57 red: cannot reach {host} over ssh: {proc.stderr.strip()[-300:]}")
    assert proc.returncode == 0 or proc.stdout.strip(), (
        f"`{command}` on {host} exited {proc.returncode}: {proc.stderr.strip()[-300:]}"
    )
    return proc.stdout.strip()


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

# The details leg. Written to web/e2e/__gate__/ for the run and removed afterwards. The gate header
# is set inside the spec from the environment; PS_GATE_EXPECT_ASOF is the test's own D_G.
SPEC_TS = r"""
import { expect, test } from "@playwright/test";

test.use({ extraHTTPHeaders: { "x-ps-gate": process.env.PS_GATE_SECRET! } });

test("details line shows prices through the generation date", async ({ page }) => {
  const expected = process.env.PS_GATE_EXPECT_ASOF!;
  expect(expected, "PS_GATE_EXPECT_ASOF").toMatch(/^\d{4}-\d{2}-\d{2}$/);
  expect(process.env.PS_GATE_SECRET, "PS_GATE_SECRET must be set").toBeTruthy();

  const health = await page.request.get("/api/health");
  expect(health.status(), "/api/health status").toBe(200);
  const asof: string = (await health.json()).asof;
  expect(asof, "the API's asof is not the test's D_G").toBe(expected);

  const nav = await page.goto("/");
  expect(nav!.status(), "navigation status").toBe(200);
  await expect(page.getByTestId("chart-canvas")).toBeVisible({ timeout: 15_000 });

  const pattern = /prices through\s+(\d{4}-\d{2}-\d{2})/g;
  const before = (await page.locator("body").innerText()).match(pattern) ?? [];
  expect(before, "the details line is shown before details are turned on").toEqual([]);

  await page.getByTestId("details-toggle").click();
  await expect(page.locator("body")).toContainText(/prices through\s+\d{4}-\d{2}-\d{2}/, { timeout: 10_000 });
  const text = await page.locator("body").innerText();
  const dates = [...text.matchAll(pattern)].map((m) => m[1]);
  expect(dates.length, "no 'prices through {asof}' line with details on").toBeGreaterThanOrEqual(1);
  for (const shown of dates) {
    expect(shown, "the page's date differs from the API's asof").toBe(asof);
  }
  expect(text).toContain(`prices through ${expected}`);
});
"""
EXPECTED_TITLES = {"details line shows prices through the generation date"}


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


if _OUTER:

    def test_a_ps_57_in_project_venv():
        env = dict(os.environ, PS_GATE_INNER="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        proc = subprocess.run(
            [
                str(_VENV_PY),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                __file__,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        print(proc.stdout[-8000:], proc.stderr[-2000:])
        assert proc.returncode == 0, "A-PS-57 is red inside the project virtualenv (output above)"

else:

    def test_asof_equals_the_reference_generation_date():
        _env("PS_GATE_SECRET")
        d_g, previous = _reference_sessions(_check_day())
        health = _health()
        asof = health.get("asof")
        assert asof != previous.isoformat(), (
            f"stale: asof is {asof}, the session before D_G; expected {d_g.isoformat()}"
        )
        assert asof == d_g.isoformat(), f"asof is {asof!r}, expected D_G = {d_g.isoformat()}"
        behind = health.get("asof_trading_days_behind")
        assert isinstance(behind, int) and not isinstance(behind, bool), (
            f"asof_trading_days_behind is {behind!r}, expected an int"
        )
        assert behind == 0, f"asof_trading_days_behind is {behind}, expected 0"
        generation = health.get("generation")
        assert isinstance(generation, str) and generation.startswith(d_g.isoformat() + "-"), (
            f"generation {generation!r} is not '{d_g.isoformat()}-<engine version>'"
        )

    def test_nightly_finished_today_with_zero_errors():
        _env("PS_GATE_SECRET")
        check_day = _check_day()
        d_g, _ = _reference_sessions(check_day)
        health = _health()
        nightly = health.get("nightly")
        assert isinstance(nightly, dict) and nightly, "/api/health has no nightly status object"
        finished = _finished_day_pt(nightly.get("finished"))
        assert finished == check_day, (
            f"nightly.finished is {finished} in Los Angeles, expected today {check_day}"
        )
        assert "errors" in nightly, "nightly status has no errors field"
        errors = nightly["errors"]
        assert errors is not None and not isinstance(errors, (str, bool)), (
            f"nightly.errors is {errors!r}, expected an empty list or 0"
        )
        assert not errors, (
            f"the nightly run recorded errors ({len(errors) if hasattr(errors, '__len__') else errors})"
        )
        assert nightly.get("D_G") == health.get("asof"), (
            f"nightly.D_G {nightly.get('D_G')!r} != asof {health.get('asof')!r}"
        )
        assert nightly.get("D_G") == d_g.isoformat(), (
            f"nightly.D_G {nightly.get('D_G')!r} is not the reference D_G {d_g.isoformat()}"
        )

    def test_generation_holds_the_twelve_preset_tensors():
        _env("PS_GATE_SECRET")
        d_g, _ = _reference_sessions(_check_day())
        resp = _http("GET", f"{SITE}/api/presets")
        assert resp.status == 200, f"/api/presets answered {resp.status}"
        body = resp.json("/api/presets")
        generation = body.get("generation")
        assert isinstance(generation, str) and generation.startswith(d_g.isoformat() + "-"), (
            f"/api/presets generation {generation!r} is not today's generation"
        )
        urls = []
        for preset in body.get("presets", []):
            lookbacks = preset.get("lookbacks") or {}
            assert set(lookbacks) == LOOKBACKS, f"{preset.get('id')}: lookbacks {sorted(lookbacks)}"
            for lookback, entry in lookbacks.items():
                assert entry.get("status") == "ready", (
                    f"{preset.get('id')}/{lookback} is {entry.get('status')!r}, not ready"
                )
                url = entry.get("url")
                assert isinstance(url, str) and url.startswith(f"/api/tensors/{generation}/"), (
                    f"{preset.get('id')}/{lookback}: url {url!r} is not in generation {generation}"
                )
                urls.append(url)
        assert len(urls) == 12 and len(set(urls)) == 12, (
            f"expected 12 distinct ready preset tensor URLs, found {len(set(urls))}"
        )
        missing = []
        for url in urls:
            head = _http("HEAD", SITE + url)
            if head.status != 200:
                missing.append((url, head.status))
        assert not missing, f"preset tensors that do not answer 200 to HEAD: {missing}"

    def test_ks001_cache_is_under_its_cap_and_the_timer_is_enabled():
        _check_day()
        out = _ssh("docker exec portfoliosight-api du -sm /app/cache")
        match = re.match(r"^(\d+)\s+/app/cache\s*$", out.splitlines()[-1] if out else "")
        assert match, (
            f"unexpected `du -sm /app/cache` output from the api container: {out[-200:]!r}"
        )
        megabytes = int(match.group(1))
        assert not megabytes > CACHE_CAP_MB, (
            f"KS-001 cache is {megabytes} MB, over the {CACHE_CAP_MB} MB cap"
        )
        state = _ssh("systemctl is-enabled portfoliosight-nightly.timer")
        assert state != "disabled", "portfoliosight-nightly.timer is disabled"
        assert state == "enabled", (
            f"`systemctl is-enabled portfoliosight-nightly.timer` printed {state!r}"
        )

    def test_details_line_shows_the_same_date():
        _env("PS_GATE_SECRET")
        d_g, _ = _reference_sessions(_check_day())
        statuses = _run_playwright(
            "a_ps_57",
            SPEC_TS,
            ("desktop",),
            base_url=SITE,
            extra_env={"PS_GATE_EXPECT_ASOF": d_g.isoformat()},
        )
        expected = {("desktop", title) for title in EXPECTED_TITLES}
        assert set(statuses) == expected, (
            f"Playwright ran a different set of tests: {sorted(statuses)}"
        )
        not_passed = {key: status for key, status in statuses.items() if status != "passed"}
        assert not not_passed, (
            f"Playwright legs not passed (failed, skipped, timed out or retried): {not_passed}"
        )
