"""A-PS-60 — a 23-fund build completes within the benchmark on KS-001.

Claim: with an idle queue, a `POST /api/tensors` for a fresh 23-fund key (the default preset's
funds with one cap override so the key is new) reaches `ready` within 30 s, with the grid 48 x 32
or the spec §4.12 fallback grid 32 x 24, and the runbook records the measured time.

Runs from the laptop against production (standard library only, no virtualenv needed).
Environment: `PS_GATE_SECRET` (never printed).

Fresh key on every run (the gate runs many times per generation): the first fund's override is
`max = 0.24 - k * 1e-6` with `k` the current second of the UTC day, so it lies in (0.1536, 0.24]
and two runs collide only when they start in the same second. If that key is already cached (first
response 200) the next four values of `k` are tried; five cached candidates fail the assertion.
Each green run costs one real build on KS-001 and one tensor object in R2 (deleted with its
generation).

Pinned interface (the product must provide exactly this):
- `GET https://portfoliosight.ai/api/health` -> 200 `{"queue": {"depth": int, "building": bool}}`.
- `GET https://portfoliosight.ai/api/presets` -> preset `guide2017` with 23 `funds` (`id`) and `hash`.
- `POST https://portfoliosight.ai/api/tensors` `{"funds": [{"id", "min", "max"}...], "lookback":
  "5y"}` -> 202 `{"status": "queued"|"building", "generation", "hash"}` for a new key, 200 for a
  cached one; `GET /api/tensors/{generation}/{hash}/5y` -> 202 while building, 200 with the tensor
  (spec §7: `frontier.x`, `grid.y`, `universe.hash`, `universe.funds`, `bounds.requested`).
- `docs/plans/2026-10-13-ks001-cloudflare-runbook.md` has one line that names the measured build
  time as `<number> s|sec|seconds` and the grid as `48x32` / `48 × 32` / `32x24`, or as
  `NX = 48 ... NY = 32` (`NX = 32 ... NY = 24`), with the time at most 30.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = ROOT / "docs" / "plans" / "2026-10-13-ks001-cloudflare-runbook.md"
SITE = "https://portfoliosight.ai"
BENCHMARK_S = 30.0
ALLOWED_GRIDS = {(48, 32), (32, 24)}
CANDIDATE_COUNT = 5


def _candidates() -> tuple[float, ...]:
    """Cap overrides for this run: 0.24 - k * 1e-6, k = second of the UTC day, then k+1 .. k+4."""
    second = int(time.time()) % 86_400
    return tuple(
        round(0.24 - ((second + step) % 86_400) * 1e-6, 6) for step in range(CANDIDATE_COUNT)
    )


HASH_RE = re.compile(r"^[0-9a-f]{16}$")
SECONDS_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:seconds|second|secs|sec|s)\b", re.I)
GRID_RE = re.compile(
    r"(?<!\d)(48|32)\s*[x×]\s*(32|24)(?!\d)|NX\s*=\s*(48|32)\b.*?NY\s*=\s*(32|24)\b", re.I
)
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
            pytest.fail(f"A-PS-60 red: {what} answered {self.status} with a body that is not JSON")


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(
            f"A-PS-60 red: environment variable {name} is not set "
            "(the caller loads ~/.secrets/portfoliosight.env)"
        )
    return value


def _http(method: str, url: str, *, payload=None, timeout: float = 20.0) -> _Resp:
    """One request with the gate header, redirects not followed; no connection = clean failure."""
    send = {"User-Agent": UA, "Accept": "application/json", "x-ps-gate": _env("PS_GATE_SECRET")}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        send["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method, headers=send, data=data)
    try:
        with _OPENER.open(request, timeout=timeout) as raw:
            return _Resp(raw.status, raw.headers, raw.read(8_000_000))
    except urllib.error.HTTPError as err:
        try:
            body = err.read(8_000_000)
        except (OSError, http.client.HTTPException):
            body = b""
        return _Resp(err.code, err.headers, body)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as err:
        reason = getattr(err, "reason", err)
        pytest.fail(f"A-PS-60 red: cannot reach {url}: {type(err).__name__}: {reason}")


def _runbook_records() -> list[tuple[float, tuple[int, int], str]]:
    """Every runbook line that carries both a duration in seconds and a grid size."""
    if not RUNBOOK.is_file():
        pytest.fail(f"A-PS-60 red: the runbook {RUNBOOK.relative_to(ROOT)} does not exist")
    records = []
    for line in RUNBOOK.read_text(encoding="utf-8").splitlines():
        grid = GRID_RE.search(line)
        if not grid:
            continue
        nx, ny = (grid.group(1), grid.group(2)) if grid.group(1) else (grid.group(3), grid.group(4))
        rest = line[: grid.start()] + " " + line[grid.end() :]
        seconds = SECONDS_RE.search(rest)
        if seconds:
            records.append((float(seconds.group(1)), (int(nx), int(ny)), line.strip()))
    return records


def _wait_for_idle_queue() -> None:
    deadline = time.monotonic() + 60.0
    last = None
    while True:
        resp = _http("GET", f"{SITE}/api/health")
        assert resp.status == 200, f"/api/health answered {resp.status}"
        queue = resp.json("/api/health").get("queue")
        assert isinstance(queue, dict), "/api/health has no queue object"
        last = (queue.get("depth"), queue.get("building"))
        if last == (0, False) and queue.get("building") is False:
            return
        if time.monotonic() >= deadline:
            pytest.fail(
                "A-PS-60 red: precondition not met, the build queue is not idle after 60 s "
                f"(depth, building) = {last}; the measurement needs depth 0 and building false"
            )
        time.sleep(5.0)


def _default_preset() -> dict:
    resp = _http("GET", f"{SITE}/api/presets")
    assert resp.status == 200, f"/api/presets answered {resp.status}"
    body = resp.json("/api/presets")
    presets = [p for p in body.get("presets", []) if isinstance(p, dict)]
    match = [p for p in presets if p.get("id") == "guide2017"]
    assert len(match) == 1, "/api/presets does not list exactly one preset with id guide2017"
    return match[0]


def _post(body: dict) -> _Resp:
    resp = _http("POST", f"{SITE}/api/tensors", payload=body)
    if resp.status == 429:  # the per-IP limiter (5 POSTs a minute): wait it out once
        wait = resp.header("retry-after")
        time.sleep(min(float(wait) if wait.isdigit() else 60.0, 65.0) + 1.0)
        resp = _http("POST", f"{SITE}/api/tensors", payload=body)
    return resp


def test_runbook_records_the_measured_build_time_and_grid():
    records = _runbook_records()
    assert records, (
        f"{RUNBOOK.relative_to(ROOT)} has no line with the measured seconds and the grid in "
        "effect (for example '23-fund build on KS-001: 14.2 s, grid 48x32')"
    )
    for seconds, grid, line in records:
        assert grid in ALLOWED_GRIDS, f"runbook names a grid that the spec does not allow: {line}"
        assert seconds > 0, f"runbook records a zero build time: {line}"
    in_budget = [r for r in records if r[0] <= BENCHMARK_S]
    assert in_budget, f"no recorded build time is within {BENCHMARK_S:.0f} s: {records}"
    # The measurement in force is the last one recorded (the re-measurement after a fallback).
    assert not records[-1][0] > BENCHMARK_S, f"the last recorded time is over budget: {records[-1]}"


def test_fresh_23_fund_build_reaches_ready_within_30_seconds():
    _env("PS_GATE_SECRET")
    _wait_for_idle_queue()
    preset = _default_preset()
    fund_ids = [f.get("id") for f in preset.get("funds", []) if isinstance(f, dict)]
    assert len(fund_ids) == 23 and len(set(fund_ids)) == 23, (
        f"the default preset lists {len(fund_ids)} funds, expected 23 distinct ids"
    )
    first = fund_ids[0]

    accepted = None
    cached = []
    for cap in _candidates():
        body = {
            "funds": [{"id": i, "min": None, "max": cap if i == first else None} for i in fund_ids],
            "lookback": "5y",
        }
        started = time.monotonic()
        resp = _post(body)
        if resp.status == 200:
            cached.append(cap)  # key already built in this generation: measurement would be void
            continue
        assert resp.status == 202, (
            f"POST /api/tensors with max={cap} on {first} answered {resp.status}, expected 202"
        )
        accepted = (cap, started, resp.json("POST /api/tensors"))
        break
    assert accepted is not None, (
        f"all {CANDIDATE_COUNT} cap candidates {cached} were already cached (first response 200): "
        "no fresh key left to measure in this generation"
    )
    cap, started, queued = accepted
    assert queued.get("status") in ("queued", "building"), (
        f"202 body status: {queued.get('status')!r}"
    )
    generation, key = queued.get("generation"), queued.get("hash")
    assert isinstance(generation, str) and generation, "202 body has no generation"
    assert isinstance(key, str) and HASH_RE.match(key), f"202 body hash is {key!r}, expected 16 hex"
    assert key != preset.get("hash"), "the cap override did not change the universe hash"

    url = f"{SITE}/api/tensors/{generation}/{key}/5y"
    polls = 0
    tensor_resp = None
    elapsed = 0.0
    while elapsed <= BENCHMARK_S + 15.0:
        time.sleep(1.0)
        resp = _http("GET", url)
        elapsed = time.monotonic() - started
        polls += 1
        if resp.status == 200:
            tensor_resp = resp
            break
        assert resp.status == 202, f"polling the build answered {resp.status} after {elapsed:.1f} s"
    assert tensor_resp is not None, f"the build was not ready after {elapsed:.1f} s ({polls} polls)"
    print(
        f"A-PS-60: measured {elapsed:.1f} s from POST to first 200 (cap max={cap}, {polls} polls)"
    )
    assert not elapsed > BENCHMARK_S, (
        f"build took {elapsed:.1f} s, over the {BENCHMARK_S:.0f} s benchmark"
    )

    tensor = tensor_resp.json(url)
    universe = tensor.get("universe") or {}
    assert universe.get("hash") == key, "the tensor's universe.hash is not the requested key"
    included = [f.get("id") for f in universe.get("funds", [])]
    excluded = [f.get("id") for f in universe.get("excluded", [])]
    assert set(included) | set(excluded) == set(fund_ids), (
        "the tensor is not for the 23 requested funds"
    )
    assert len(included) + len(excluded) == 23, "the tensor's funds plus excluded are not 23"
    if first in included:  # the override must be the one this run asked for (proves a real new key)
        requested = (tensor.get("bounds") or {}).get("requested") or []
        assert len(requested) == len(included), "bounds.requested does not follow universe.funds"
        got = requested[included.index(first)].get("max")
        assert got is not None and abs(got - cap) < 1e-12, (
            f"bounds.requested max for {first} is {got}"
        )
    grid = (
        len((tensor.get("frontier") or {}).get("x") or []),
        len((tensor.get("grid") or {}).get("y") or []),
    )
    assert grid in ALLOWED_GRIDS, (
        f"tensor grid is {grid}, expected (48, 32) or the fallback (32, 24)"
    )
    assert grid not in {(48, 24), (32, 32)}, f"tensor mixes the two grids: {grid}"

    records = _runbook_records()
    assert records, (
        f"{RUNBOOK.relative_to(ROOT)} has no line with the measured seconds and the grid"
    )
    assert records[-1][1] == grid, (
        f"the runbook's last recorded grid {records[-1][1]} is not the grid in effect {grid}"
    )
    assert records[-1][0] <= BENCHMARK_S, (
        f"the runbook's last recorded time is over budget: {records[-1]}"
    )
