"""A-PS-59 — every served symbol is current and the runbook records the licensing decision.

Claim: every symbol in `/api/symbols` has manifest `status: ok` with `adjusted_through` and
`last_date` within 3 XNYS trading days of `D_G`, no `pending` or `unavailable` symbol appears,
`tiers_served` equals the tiers present, and `docs/plans/2026-10-13-ks001-cloudflare-runbook.md`
records the spec §9.6 personal-use decision with a date.

Runs from the laptop against production and R2, inside the project virtualenv (needs `boto3` and
`exchange_calendars`). Environment: `PS_GATE_SECRET`, `CLOUDFLARE_ACCOUNT_ID`,
`CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY` (never printed). The manifest is
read with the test's own boto3 client; `D_G` is the date part of `/api/presets`'s generation.

Pinned interface (the product must provide exactly this):
- `GET https://portfoliosight.ai/api/symbols` -> 200 `{"tiers_served": [int...], "symbols":
  [{"id", "tier", ...}]}` listing exactly the manifest's `status == "ok"` symbols (spec §6).
- `GET https://portfoliosight.ai/api/presets` -> `generation` = `{D_G}-{engine version}`, `asof` = `D_G`.
- `meta/manifest.json` in bucket `portfoliosight-data`: per-symbol `status`, `tier`, `last_date`,
  `adjusted_through` (ISO dates); `{"symbols": {id: entry}}` or a top-level id-keyed object.
- The 16 TSP ids of spec §5.5 are served.
- The runbook has, after a line that names step 3 ("step 3", "§9.5", or a list item / heading
  numbered `3.`), a line matching `personal use.*2026-MM-DD` or `2026-MM-DD.*personal use`
  (case-insensitive) whose date is a real calendar date.
"""

# ruff: noqa: E501

from __future__ import annotations

import http.client
import importlib
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


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
        pytest.fail(f"A-PS-59 red: cannot import {module}: {type(exc).__name__}: {exc}")


BUCKET = "portfoliosight-data"
SECRET_NAMES = (
    "PS_GATE_SECRET",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
    "TIINGO_API_KEY",
)


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(
            f"A-PS-59 red: environment variable {name} is not set "
            "(the caller loads ~/.secrets/portfoliosight.env)"
        )
    return value


def _scrub(text: str) -> str:
    """Replace every secret value from the environment by its variable name before printing."""
    for name in SECRET_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            text = text.replace(value, f"<{name}>")
    return text


def _r2_endpoint() -> str:
    return f"https://{_env('CLOUDFLARE_ACCOUNT_ID')}.r2.cloudflarestorage.com"


def _r2_client():
    """The test's own S3 client for R2, built from the environment (not the product's store)."""
    key_id = _env("CLOUDFLARE_R2_ACCESS_KEY_ID")
    secret = _env("CLOUDFLARE_R2_SECRET_ACCESS_KEY")
    endpoint = _r2_endpoint()
    boto3 = _need("boto3")
    config = _need("botocore.config").Config(
        connect_timeout=10, read_timeout=60, retries={"max_attempts": 2}
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        config=config,
    )


def _r2_get(client, key: str) -> bytes:
    try:
        return client.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except Exception as exc:  # botocore ClientError / connection errors
        pytest.fail(
            f"A-PS-59 red: cannot read s3://{BUCKET}/{key} from R2: "
            f"{type(exc).__name__}: {_scrub(str(exc))[:300]}"
        )


def _manifest_entries(document) -> dict[str, dict]:
    """Per-symbol entries of meta/manifest.json: `{"symbols": {id: entry}}` or a top-level id dict."""
    assert isinstance(document, dict), "meta/manifest.json is not a JSON object"
    symbols = document.get("symbols")
    entries = symbols if isinstance(symbols, dict) else document
    return {key: value for key, value in entries.items() if isinstance(value, dict)}


def _read_manifest(client) -> dict[str, dict]:
    raw = _r2_get(client, "meta/manifest.json")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        pytest.fail("A-PS-59 red: meta/manifest.json in R2 is not JSON")
    return _manifest_entries(document)


SITE = "https://portfoliosight.ai"
RUNBOOK = ROOT / "docs" / "plans" / "2026-10-13-ks001-cloudflare-runbook.md"
SAMPLE = 20
MAX_TRADING_DAYS_BEHIND = 3
TSP_IDS = (
    "TSP-G TSP-F TSP-C TSP-S TSP-I TSP-LINC TSP-L2030 TSP-L2035 TSP-L2040 TSP-L2045 "
    "TSP-L2050 TSP-L2055 TSP-L2060 TSP-L2065 TSP-L2070 TSP-L2075"
).split()
GENERATION_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-[0-9.]+$")
DECISION_RE = re.compile(
    r"personal use.*?(2026-\d{2}-\d{2})|(2026-\d{2}-\d{2}).*personal use", re.IGNORECASE
)
STEP3_RE = re.compile(r"\bstep\s*3\b|§\s*9\.5|^\s*(?:#{1,6}\s*)?(?:[-*]\s*)?3[.)]\s", re.IGNORECASE)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 portfoliosight-gate"
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get_json(path: str):
    """GET a page-origin API path with the gate header; no connection = clean failure."""
    url = SITE + path
    send = {"User-Agent": UA, "Accept": "application/json", "x-ps-gate": _env("PS_GATE_SECRET")}
    request = urllib.request.Request(url, method="GET", headers=send)
    try:
        with _OPENER.open(request, timeout=30.0) as raw:
            status, body = raw.status, raw.read(32_000_000)
    except urllib.error.HTTPError as err:
        pytest.fail(f"A-PS-59 red: GET {url} answered {err.code}, expected 200")
    except (urllib.error.URLError, OSError, http.client.HTTPException) as err:
        reason = getattr(err, "reason", err)
        pytest.fail(f"A-PS-59 red: cannot reach {url}: {type(err).__name__}: {reason}")
    assert status == 200, f"GET {url} answered {status}, expected 200"
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        pytest.fail(f"A-PS-59 red: GET {url} answered a body that is not JSON")


def _generation_date() -> date:
    presets = _get_json("/api/presets")
    generation = presets.get("generation") if isinstance(presets, dict) else None
    match = GENERATION_RE.match(generation) if isinstance(generation, str) else None
    assert match, f"/api/presets generation is {generation!r}"
    assert presets.get("asof") == match.group(1), (
        f"/api/presets asof {presets.get('asof')!r} is not the date part of {generation!r}"
    )
    return date.fromisoformat(match.group(1))


def _oldest_allowed(d_g: date) -> date:
    """The XNYS session 3 trading days before D_G (computed here with exchange_calendars)."""
    calendar = _need("exchange_calendars").get_calendar("XNYS")
    first = (d_g - timedelta(days=21)).isoformat()
    sessions = [s.date() for s in calendar.sessions_in_range(first, d_g.isoformat())]
    assert sessions and sessions[-1] == d_g, f"D_G {d_g} is not an XNYS session"
    assert len(sessions) > MAX_TRADING_DAYS_BEHIND, "the XNYS calendar returned too few sessions"
    return sessions[-1 - MAX_TRADING_DAYS_BEHIND]


def _catalog_and_manifest() -> tuple[dict, dict[str, dict]]:
    """/api/symbols and the manifest, re-read once if they disagree (the nightly rewrites both)."""
    _env("PS_GATE_SECRET")
    client = _r2_client()
    catalog, manifest = {}, {}
    for attempt in range(2):
        catalog = _get_json("/api/symbols")
        manifest = _read_manifest(client)
        assert isinstance(catalog, dict) and isinstance(catalog.get("symbols"), list), (
            "/api/symbols has no symbols list"
        )
        listed = {s.get("id") for s in catalog["symbols"]}
        served = {k for k, v in manifest.items() if v.get("status") == "ok"}
        if listed == served or attempt == 1:
            break
        time.sleep(15.0)
    return catalog, manifest


def _as_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _decision_dates(text: str) -> list[date]:
    """Dates of runbook lines that record the personal-use decision under the step 3 heading."""
    found = []
    under_step3 = False
    for line in text.splitlines():
        if STEP3_RE.search(line):
            under_step3 = True
        match = DECISION_RE.search(line)
        if match and under_step3:
            parsed = _as_date(match.group(1) or match.group(2))
            if parsed is not None:
                found.append(parsed)
    return found


if _OUTER:

    def test_a_ps_59_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-59 is red inside the project virtualenv (output above)"

else:

    def test_listed_symbols_are_exactly_the_manifest_ok_symbols():
        catalog, manifest = _catalog_and_manifest()
        ids = [s.get("id") for s in catalog["symbols"]]
        assert len(ids) == len(set(ids)), "/api/symbols repeats an id"
        listed = set(ids)
        served = {k for k, v in manifest.items() if v.get("status") == "ok"}
        assert len(listed) >= SAMPLE + len(TSP_IDS), (
            f"/api/symbols lists only {len(listed)} symbols; the catalog is not populated"
        )
        not_ok = sorted(listed - served)
        assert not not_ok, (
            f"{len(not_ok)} listed symbols are not status ok in the manifest, e.g. "
            f"{[(s, (manifest.get(s) or {}).get('status')) for s in not_ok[:5]]}"
        )
        unlisted = sorted(served - listed)
        assert not unlisted, (
            f"{len(unlisted)} ok symbols are missing from /api/symbols, e.g. {unlisted[:5]}"
        )
        assert listed == served
        hidden = {
            k for k, v in manifest.items() if v.get("status") in ("pending", "unavailable", "stale")
        }
        assert not listed & hidden, (
            f"pending/unavailable/stale symbols are listed: {sorted(listed & hidden)[:5]}"
        )

    def test_sampled_symbols_and_all_tsp_funds_are_within_three_trading_days():
        catalog, manifest = _catalog_and_manifest()
        d_g = _generation_date()
        oldest = _oldest_allowed(d_g)
        listed = sorted({s.get("id") for s in catalog["symbols"] if isinstance(s.get("id"), str)})
        missing_tsp = [i for i in TSP_IDS if i not in listed]
        assert not missing_tsp, f"TSP ids missing from /api/symbols: {missing_tsp}"
        pool = [i for i in listed if i not in TSP_IDS]
        assert len(pool) >= SAMPLE, (
            f"only {len(pool)} non-TSP symbols are listed, cannot sample {SAMPLE}"
        )
        seed = f"A-PS-59:{datetime.now(timezone.utc):%Y-%m-%d}"
        chosen = random.Random(seed).sample(pool, SAMPLE) + list(TSP_IDS)
        print(
            f"A-PS-59: D_G {d_g}, oldest allowed {oldest}, sample seed {seed!r}: {chosen[:SAMPLE]}"
        )
        catalog_tier = {s.get("id"): s.get("tier") for s in catalog["symbols"]}
        problems = []
        checked = 0
        for symbol in chosen:
            entry = manifest.get(symbol)
            checked += 1
            if not isinstance(entry, dict):
                problems.append(f"{symbol}: no manifest entry")
                continue
            if entry.get("status") != "ok":
                problems.append(f"{symbol}: status {entry.get('status')!r}")
            for field in ("adjusted_through", "last_date"):
                value = _as_date(entry.get(field))
                if value is None:
                    problems.append(f"{symbol}: {field} is {entry.get(field)!r}")
                elif value < oldest:
                    problems.append(
                        f"{symbol}: {field} {value} is older than {oldest} (D_G - 3 sessions)"
                    )
            if entry.get("tier") != catalog_tier.get(symbol):
                problems.append(
                    f"{symbol}: tier {catalog_tier.get(symbol)!r} listed, {entry.get('tier')!r} in manifest"
                )
        assert checked == SAMPLE + len(TSP_IDS), (
            f"checked {checked} symbols, expected {SAMPLE + len(TSP_IDS)}"
        )
        assert not problems, f"{len(problems)} problems among the sampled symbols: {problems[:10]}"

    def test_tiers_served_equals_the_tiers_present():
        catalog, _ = _catalog_and_manifest()
        tiers = catalog.get("tiers_served")
        assert isinstance(tiers, list) and tiers, f"tiers_served is {tiers!r}"
        assert len(tiers) == len(set(tiers)), f"tiers_served repeats a tier: {tiers}"
        present = {s.get("tier") for s in catalog["symbols"]}
        assert present <= {1, 2, 3}, (
            f"symbols carry tiers outside 1..3: {sorted(map(str, present))}"
        )
        assert not set(tiers) - present, (
            f"tiers_served names a tier with no listed symbol: {sorted(set(tiers) - present)}"
        )
        assert set(tiers) == present, (
            f"tiers_served {sorted(tiers)} != tiers present {sorted(present)}"
        )

    def test_runbook_records_the_personal_use_decision_with_a_date():
        if not RUNBOOK.is_file():
            pytest.fail(f"A-PS-59 red: the runbook {RUNBOOK.relative_to(ROOT)} does not exist")
        dates = _decision_dates(RUNBOOK.read_text(encoding="utf-8"))
        assert dates, (
            f"{RUNBOOK.relative_to(ROOT)} has no line under step 3 matching "
            "'personal use ... 2026-MM-DD' (the dated spec §9.6 decision)"
        )
        today = datetime.now(timezone.utc).date() + timedelta(days=1)
        assert not [d for d in dates if d > today], (
            f"the recorded decision date is in the future: {dates}"
        )
        assert min(dates) >= date(2026, 10, 13), (
            f"the decision is dated before it was made (2026-10-13): {dates}"
        )
