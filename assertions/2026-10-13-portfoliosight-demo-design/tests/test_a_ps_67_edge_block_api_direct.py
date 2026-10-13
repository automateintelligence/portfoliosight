"""A-PS-67 — a headerless request to `api.portfoliosight.ai` is blocked at the edge.

Claim: `GET https://api.portfoliosight.ai/v1/health` without the header is refused by
Cloudflare's block action and never reaches FastAPI; with the header it returns the origin's 200.

Runs from the laptop against production with the standard library only. Needs `PS_GATE_SECRET`
and `CLOUDFLARE_API_TOKEN`; a missing variable is a failure naming it.

Dependency: the WAF custom rule `ps-block-api-direct` (spec 9.4), looked up through the
Cloudflare rulesets API; an authentication/permission error there fails with `BLOCKED:`.

Pinned interface (the product must provide exactly this):
- zone `portfoliosight.ai`, phase `http_request_firewall_custom`: a rule whose `ref` or
  `description` is `ps-block-api-direct`, `enabled: true`, action `block`, keyed on `x-ps-gate`;
- `GET https://api.portfoliosight.ai/v1/health` with the header: 200 `application/json` with
  `status == "ok"`, `generation` (`YYYY-MM-DD-<engine version>`), `asof` (ISO date) and an
  integer `queue.depth` (spec 6);
- the application's own refusal envelope is `{"error": {"code": "forbidden", ...}}` (spec 6) and
  must NOT be what a headerless caller sees.
"""

from __future__ import annotations

import datetime as dt
import http.client
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

import pytest

SITE = "https://portfoliosight.ai"
API = "https://api.portfoliosight.ai"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
MAX_BODY = 8 * 1024 * 1024
SECRET_NAMES = (
    "PS_GATE_SECRET",
    "CLOUDFLARE_API_TOKEN",
    "PS_SHARE_TEST_RECIPIENT",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "TIINGO_API_KEY",
)


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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102, PLR0913
        return None


@dataclass
class _Resp:
    status: int  # 0 = no HTTP response at all (DNS, connect, TLS, timeout)
    headers: dict[str, str]
    body: bytes
    error: str = ""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


def _http(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 20.0,
) -> _Resp:
    """One request through a fresh opener: no cookie jar, no redirect following, explicit timeout."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        url, data=body, method=method, headers={"User-Agent": UA, **(headers or {})}
    )
    try:
        with opener.open(request, timeout=timeout) as resp:
            found = {key.lower(): value for key, value in resp.headers.items()}
            return _Resp(resp.status, found, resp.read(MAX_BODY))
    except urllib.error.HTTPError as err:
        with err:
            found = {key.lower(): value for key, value in err.headers.items()}
            return _Resp(err.code, found, err.read(MAX_BODY))
    except (urllib.error.URLError, OSError, http.client.HTTPException) as err:
        reason = getattr(err, "reason", err)
        return _Resp(0, {}, b"", _scrub(f"{type(err).__name__}: {reason}"))


def _reached(resp: _Resp, what: str) -> _Resp:
    """Fail cleanly when a request produced no HTTP response (today: nothing is deployed)."""
    if resp.status == 0:
        pytest.fail(
            f"{what}: no HTTP response ({resp.error}); the site is not deployed or not reachable",
            pytrace=False,
        )
    return resp


def _json_or_none(text: str):
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, (dict, list)) else None


CF_API = "https://api.cloudflare.com/client/v4"
ZONE = "portfoliosight.ai"
CF_AUTH_CODES = {10000, 9109, 9106, 9103, 6003, 6111}
CF_AUTH_TEXT = re.compile(
    r"authenticat|permission|not authorized|unauthorized|invalid access token|invalid request headers",
    re.IGNORECASE,
)


def _cf_auth_problem(status: int, payload: dict) -> bool:
    """True when a Cloudflare API answer means the token lacks (or lost) the permission."""
    if status in (401, 403):
        return True
    for error in payload.get("errors") or []:
        if not isinstance(error, dict):
            continue
        if error.get("code") in CF_AUTH_CODES or CF_AUTH_TEXT.search(str(error.get("message"))):
            return True
    return False


def _cf_get(path: str, token: str) -> dict:
    resp = _http(
        "GET",
        CF_API + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        timeout=30.0,
    )
    if resp.status == 0:
        pytest.fail(f"Cloudflare API not reachable for GET {path}: {resp.error}", pytrace=False)
    payload = _json_or_none(resp.text)
    if not isinstance(payload, dict):
        payload = {}
    errors = [error for error in payload.get("errors") or [] if isinstance(error, dict)]
    codes = [error.get("code") for error in errors]
    if _cf_auth_problem(resp.status, payload):
        pytest.fail(
            f"BLOCKED: the Cloudflare token cannot read GET {path} (HTTP {resp.status}, error codes "
            f"{codes}); `Zone > Zone WAF > Edit` is missing or was withdrawn",
            pytrace=False,
        )
    if resp.status != 200 or payload.get("success") is not True:
        messages = _scrub("; ".join(str(error.get("message")) for error in errors))[:500]
        pytest.fail(
            f"Cloudflare API GET {path}: HTTP {resp.status}, codes {codes}: {messages}",
            pytrace=False,
        )
    return payload


def _find_rule(rules: list[dict], name: str) -> dict | None:
    """The rule whose `ref` is `name` or whose `description` carries `name` as a whole token."""
    token = re.compile(rf"(?<![\w-]){re.escape(name)}(?![\w-])")
    for rule in rules:
        if rule.get("ref") == name or token.search(str(rule.get("description") or "")):
            return rule
    return None


def _require_rule(name: str, phase: str, action: str) -> dict:
    """Dependency check: the named rule exists in the zone's entry-point ruleset and is enabled.

    Prints what it found (never the rule expression: it holds the gate secret).
    """
    token = _env("CLOUDFLARE_API_TOKEN")
    zones = _cf_get(f"/zones?name={ZONE}", token).get("result") or []
    if not zones:
        pytest.fail(f"BLOCKED: the Cloudflare token cannot see the zone {ZONE}", pytrace=False)
    zone_id = zones[0]["id"]
    rulesets = _cf_get(f"/zones/{zone_id}/rulesets", token).get("result") or []
    entry = [item for item in rulesets if item.get("phase") == phase and item.get("kind") == "zone"]
    assert entry, (
        f"no zone entry-point ruleset for phase {phase} ({len(rulesets)} ruleset(s) listed): "
        f"the rule {name} has not been created"
    )
    rules: list[dict] = []
    for item in entry:
        detail = _cf_get(f"/zones/{zone_id}/rulesets/{item['id']}", token).get("result") or {}
        rules.extend(rule for rule in detail.get("rules") or [] if isinstance(rule, dict))
    rule = _find_rule(rules, name)
    assert rule is not None, f"rule {name} not found among {len(rules)} rule(s) of phase {phase}"
    print(
        f"dependency check: rule {name} id={rule.get('id')} phase={phase} "
        f"enabled={rule.get('enabled')} action={rule.get('action')}"
    )
    assert rule.get("enabled") is True, f"rule {name} exists but is not enabled"
    assert rule.get("action") == action, (
        f"rule {name} has action {rule.get('action')!r}, spec 9.4 says {action!r}"
    )
    return rule


HEALTH = API + "/v1/health"
BLOCK_PAGE = re.compile(r"cf-ray|ray id|1020|access denied", re.IGNORECASE)
GENERATION = re.compile(r"^\d{4}-\d{2}-\d{2}-[0-9.]+$")


def test_a_ps_67_dependency_rule_ps_block_api_direct_is_enabled():
    _env("PS_GATE_SECRET")
    rule = _require_rule("ps-block-api-direct", "http_request_firewall_custom", "block")
    keyed_on_header = "x-ps-gate" in str(rule.get("expression") or "")
    assert keyed_on_header, "rule ps-block-api-direct does not test the x-ps-gate header"


def test_a_ps_67_headerless_health_is_blocked_by_cloudflare_not_by_the_application():
    _env("PS_GATE_SECRET")
    _env("CLOUDFLARE_API_TOKEN")
    resp = _reached(_http("GET", HEALTH), "headerless GET api /v1/health")
    assert resp.status == 403, f"headerless /v1/health: status {resp.status}, expected 403"
    content_type = resp.headers.get("content-type", "")
    assert content_type.lower().startswith("text/html"), (
        f"headerless /v1/health: content-type {content_type!r}, expected Cloudflare's text/html"
    )
    assert resp.headers.get("server", "").lower() == "cloudflare", (
        f"headerless /v1/health: server header {resp.headers.get('server')!r}, expected cloudflare"
    )
    assert BLOCK_PAGE.search(resp.text), (
        "headerless /v1/health: the body is not Cloudflare's block page "
        "(no Ray ID reference, no 1020 / Access denied marker)"
    )
    # Must-not-contain: the application's envelope would prove the origin was reached.
    envelope = _json_or_none(resp.text)
    assert envelope is None, "headerless /v1/health: a JSON body came back (origin reached)"
    assert '"forbidden"' not in resp.text, "headerless /v1/health: the application's envelope"
    assert "x-ps-source" not in resp.headers


def test_a_ps_67_with_the_header_the_origin_answers_200_json():
    secret = _env("PS_GATE_SECRET")
    _env("CLOUDFLARE_API_TOKEN")
    resp = _reached(
        _http("GET", HEALTH, {"x-ps-gate": secret, "Accept": "application/json"}),
        "GET api /v1/health with the header",
    )
    assert resp.status == 200, f"/v1/health with the header: status {resp.status}, expected 200"
    content_type = resp.headers.get("content-type", "")
    assert content_type.lower().startswith("application/json"), f"content-type {content_type!r}"
    body = _json_or_none(resp.text)
    assert isinstance(body, dict), "/v1/health with the header: the body is not a JSON object"
    assert "error" not in body, "/v1/health with the header returned an error envelope"
    assert body.get("status") == "ok", f"status field is {body.get('status')!r}"
    generation = body.get("generation")
    assert isinstance(generation, str) and GENERATION.match(generation), (
        f"generation {generation!r} does not match YYYY-MM-DD-<version>"
    )
    asof = body.get("asof")
    try:
        parsed = dt.date.fromisoformat(asof) if isinstance(asof, str) else None
    except ValueError:
        parsed = None
    assert parsed is not None, f"asof {asof!r} is not an ISO date"
    queue = body.get("queue")
    depth = queue.get("depth") if isinstance(queue, dict) else None
    assert isinstance(depth, int) and not isinstance(depth, bool), f"queue.depth is {depth!r}"
