"""A-PS-55 — the origin gate, the www redirect and the disabled `workers.dev` host.

Claim: `GET https://api.portfoliosight.ai/v1/health` without the `x-ps-gate` header returns 403 and
with it returns 200 JSON with `generation` and `asof`; `GET https://www.portfoliosight.ai/?u=tsp`
(with the header) returns 301 to `https://portfoliosight.ai/?u=tsp`; the Worker's `workers.dev`
hostname does not serve the site.

Runs from the laptop against production (standard library only, no virtualenv needed).
Environment: `PS_GATE_SECRET`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` (never printed).

Pinned interface (the product must provide exactly this):
- `GET https://api.portfoliosight.ai/v1/health`: 403 without `x-ps-gate`; with it 200,
  `content-type: application/json`, body `{"status": "ok", "generation": "<asof>-<engine version>",
  "asof": "YYYY-MM-DD", "queue": {"depth": int, ...}, ...}` (spec §6).
- `https://www.portfoliosight.ai/<path>?<query>` answers 301 with `Location` = the same path and
  query on `https://portfoliosight.ai` (spec §9.3).
- The Worker is named `portfoliosight` with `workers_dev: false`: the account's
  `https://portfoliosight.<subdomain>.workers.dev/` gives a connection error or 404 (the subdomain
  is read from `GET /accounts/{CLOUDFLARE_ACCOUNT_ID}/workers/subdomain` of the Cloudflare API).
- `GET https://portfoliosight.ai/` with the header answers 200 (control: the Worker is deployed).
"""

from __future__ import annotations

import http.client
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date

import pytest

API_HEALTH = "https://api.portfoliosight.ai/v1/health"
WWW_URL = "https://www.portfoliosight.ai/?u=tsp"
APEX_TARGET = "https://portfoliosight.ai/?u=tsp"
APEX_ROOT = "https://portfoliosight.ai/"
GENERATION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[0-9.]+$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SUBDOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
PREVIEW_TEXT = "PortfolioSight is in private preview"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 portfoliosight-gate"
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a 3xx comes back as the response itself, never followed


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
            pytest.fail(f"A-PS-55 red: {what} answered {self.status} with a body that is not JSON")


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(
            f"A-PS-55 red: environment variable {name} is not set "
            "(the caller loads ~/.secrets/portfoliosight.env)"
        )
    return value


def _http(
    method: str,
    url: str,
    *,
    gate: bool = False,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    unreachable_ok: bool = False,
) -> _Resp | None:
    """One request, redirects not followed. A connection failure is a clean test failure."""
    send = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.8"}
    if gate:
        send["x-ps-gate"] = _env("PS_GATE_SECRET")
    send.update(headers or {})
    request = urllib.request.Request(url, method=method, headers=send)
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
        if unreachable_ok:
            return None
        reason = getattr(err, "reason", err)
        pytest.fail(f"A-PS-55 red: cannot reach {url}: {type(err).__name__}: {reason}")


def test_health_without_the_header_is_403():
    _env("PS_GATE_SECRET")  # the whole assertion needs it; fail on the variable first
    resp = _http("GET", API_HEALTH)
    assert resp.status != 200, "the health route answered 200 without the x-ps-gate header"
    assert resp.status == 403, f"expected 403 without the header, got {resp.status}"
    assert b'"generation"' not in resp.body, "the headerless 403 body carries health data"


def test_health_with_the_header_is_200_json():
    resp = _http("GET", API_HEALTH, gate=True)
    assert resp.status == 200, f"expected 200 with the header, got {resp.status}"
    content_type = resp.header("content-type").lower()
    assert content_type.split(";")[0].strip() == "application/json", (
        f"content-type is {content_type!r}, expected application/json"
    )
    body = resp.json(API_HEALTH)
    assert isinstance(body, dict), "health body is not a JSON object"
    assert body.get("status") == "ok", f"health status is {body.get('status')!r}"
    generation = body.get("generation")
    assert isinstance(generation, str) and GENERATION_RE.match(generation), (
        f"generation {generation!r} does not match ^\\d{{4}}-\\d{{2}}-\\d{{2}}-[0-9.]+$"
    )
    asof = body.get("asof")
    assert isinstance(asof, str) and ISO_DATE_RE.match(asof), f"asof {asof!r} is not an ISO date"
    try:
        date.fromisoformat(asof)
    except ValueError:
        pytest.fail(f"A-PS-55 red: asof {asof!r} is not a real calendar date")
    assert generation.startswith(asof + "-"), (
        f"generation {generation!r} is not '{asof}-<engine version>' (spec §5.3)"
    )
    queue = body.get("queue")
    assert isinstance(queue, dict), "health body has no queue object"
    depth = queue.get("depth")
    assert isinstance(depth, int) and not isinstance(depth, bool), (
        f"queue.depth is {depth!r}, expected an int"
    )
    assert depth >= 0, f"queue.depth is negative: {depth}"


def test_www_redirects_301_to_the_apex_with_path_and_query():
    resp = _http("GET", WWW_URL, gate=True)
    assert resp.status != 200, "www served a page directly instead of redirecting"
    assert resp.status == 301, f"expected 301 from {WWW_URL}, got {resp.status}"
    location = resp.header("location")
    assert location == APEX_TARGET, f"Location is {location!r}, expected {APEX_TARGET!r}"
    assert b'data-testid="chart' not in resp.body, "the www response body carries the page"


def _workers_dev_subdomain() -> str:
    account = _env("CLOUDFLARE_ACCOUNT_ID")
    token = _env("CLOUDFLARE_API_TOKEN")
    url = "https://api.cloudflare.com/client/v4/accounts/{account}/workers/subdomain"
    resp = _http(
        "GET",
        url.format(account=account),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    shown = url.format(account="<CLOUDFLARE_ACCOUNT_ID>")
    assert resp.status == 200, (
        f"Cloudflare API {shown} answered {resp.status}: cannot read the workers.dev subdomain "
        "(check CLOUDFLARE_API_TOKEN's Workers Scripts read permission)"
    )
    body = resp.json(shown)
    subdomain = (body.get("result") or {}).get("subdomain") if isinstance(body, dict) else None
    assert isinstance(subdomain, str) and SUBDOMAIN_RE.match(subdomain), (
        "Cloudflare API returned no usable workers.dev subdomain for the account"
    )
    return subdomain


def test_workers_dev_hostname_does_not_serve_the_site():
    _env("PS_GATE_SECRET")
    subdomain = _workers_dev_subdomain()
    # Control: the Worker is really deployed, so a 404 on workers.dev means "disabled", not "absent".
    apex = _http("GET", APEX_ROOT, gate=True)
    assert apex.status == 200, (
        f"control failed: {APEX_ROOT} with the header answered {apex.status}, so the Worker is "
        "not deployed and the workers.dev check would be vacuous"
    )
    host = f"https://portfoliosight.{subdomain}.workers.dev/"
    checked = 0
    for gate in (False, True):  # with the header too: a preview-gated Worker would hide behind 403
        resp = _http("GET", host, gate=gate, unreachable_ok=True)
        checked += 1
        if resp is None:
            continue  # connection error: the hostname is not served
        label = "with" if gate else "without"
        assert resp.status != 200, f"workers.dev hostname answered 200 {label} the gate header"
        assert resp.status == 404, (
            f"workers.dev hostname answered {resp.status} {label} the gate header; "
            "expected a connection error or 404"
        )
        assert b'data-testid="chart' not in resp.body, "workers.dev response carries the page"
        assert PREVIEW_TEXT.encode() not in resp.body, (
            "workers.dev response is the Worker's preview page: the Worker is reachable there"
        )
    assert checked == 2
