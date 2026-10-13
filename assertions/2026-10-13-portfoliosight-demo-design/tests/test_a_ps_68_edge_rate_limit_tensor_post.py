"""A-PS-68 — the edge rate-limits `POST /api/tensors` and leaves polling alone.

Claim: 25 `POST /api/tensors` within 10 s from one IP (with the header) produce at least one 429
that lacks `x-ps-source` (edge, not application), and 25 `GET /api/tensors/{G}/{hash}/5y` within
10 s produce no edge 429.

Runs from the laptop against production with the standard library only. Needs `PS_GATE_SECRET`
and `CLOUDFLARE_API_TOKEN`; a missing variable is a failure naming it.

Dependency: the rate-limiting rule `ps-tensor-post` (spec 9.4), looked up through the Cloudflare
rulesets API; an authentication/permission error there fails with `BLOCKED:`.

Pinned interface (the product must provide exactly this):
- zone `portfoliosight.ai`, phase `http_ratelimit`: a rule whose `ref` or `description` is
  `ps-tensor-post`, `enabled: true`, action `block`;
- `GET /api/presets` (spec 6): the preset with id `guide2017` is the default; its `funds[].id`
  and `lookbacks["5y"].url` are used;
- every response that passed through the Worker carries `x-ps-source` (`r2` or `origin`,
  spec 9.3), including the application's own 429; an edge 429 carries none.

After a POST burst that reached the site the test waits 61 s so the application's 5-per-minute
limiter (spec 6) is clear again for whatever runs next.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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


BURST = 25
WINDOW_S = 10.0
TENSOR_PATH = re.compile(r"^/api/tensors/\d{4}-\d{2}-\d{2}-[0-9.]+/[0-9a-f]{16}/5y$")


def _burst(method: str, url: str, headers: dict[str, str], body: bytes | None):
    """Send BURST requests at once; return the responses and the wall time of the whole burst."""
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=BURST) as pool:
        futures = [pool.submit(_http, method, url, headers, body, 8.0) for _ in range(BURST)]
        responses = [future.result() for future in futures]
    return responses, time.monotonic() - started


def _classify(responses: list[_Resp]) -> dict[str, int]:
    """Count a burst by status and by the presence of x-ps-source (Worker-served or not)."""
    counts = {
        "total": len(responses),
        "no_response": 0,
        "edge_429": 0,
        "via_worker": 0,
        "ok_200": 0,
    }
    for resp in responses:
        via_worker = "x-ps-source" in resp.headers
        if resp.status == 0:
            counts["no_response"] += 1
        if via_worker:
            counts["via_worker"] += 1
        if resp.status == 429 and not via_worker:
            counts["edge_429"] += 1
        if resp.status == 200 and via_worker:
            counts["ok_200"] += 1
    return counts


def _default_preset(secret: str) -> tuple[str, bytes]:
    """The default preset's 5y tensor URL and the POST body that names the same menu."""
    resp = _reached(
        _http("GET", SITE + "/api/presets", {"x-ps-gate": secret, "Accept": "application/json"}),
        "GET /api/presets with the header",
    )
    assert resp.status == 200, f"GET /api/presets with the header: status {resp.status}"
    body = _json_or_none(resp.text)
    presets = body.get("presets") if isinstance(body, dict) else None
    assert isinstance(presets, list) and presets, "GET /api/presets: no presets list"
    chosen = [item for item in presets if isinstance(item, dict) and item.get("id") == "guide2017"]
    assert chosen, "GET /api/presets: the default preset `guide2017` is missing"
    preset = chosen[0]
    url = ((preset.get("lookbacks") or {}).get("5y") or {}).get("url")
    assert isinstance(url, str) and TENSOR_PATH.match(url), f"5y tensor url is {url!r}"
    ids = [fund.get("id") for fund in preset.get("funds") or [] if isinstance(fund, dict)]
    assert len(ids) >= 2 and all(isinstance(fund_id, str) for fund_id in ids), "preset funds"
    post = {
        "funds": [{"id": fund_id, "min": None, "max": None} for fund_id in ids],
        "lookback": "5y",
    }
    return url, json.dumps(post).encode("utf-8")


def test_a_ps_68_dependency_rule_ps_tensor_post_is_enabled():
    _env("PS_GATE_SECRET")
    rule = _require_rule("ps-tensor-post", "http_ratelimit", "block")
    assert "ratelimit" in rule, "rule ps-tensor-post carries no ratelimit parameters"
    assert "/api/tensors" in str(rule.get("expression") or ""), (
        "rule ps-tensor-post does not match the path /api/tensors"
    )


def test_a_ps_68_two_bursts_post_is_limited_at_the_edge_and_polling_is_not():
    secret = _env("PS_GATE_SECRET")
    _env("CLOUDFLARE_API_TOKEN")
    tensor_url, post_body = _default_preset(secret)
    read_headers = {"x-ps-gate": secret, "Accept": "application/json"}
    write_headers = {**read_headers, "Content-Type": "application/json"}

    # Polling burst first, so the edge's 10 s block on the POST path cannot touch it.
    gets, get_seconds = _burst("GET", SITE + tensor_url, read_headers, None)
    get_counts = _classify(gets)
    print(
        f"GET burst: {get_counts} in {get_seconds:.1f} s; statuses {sorted(r.status for r in gets)}"
    )

    posts, post_seconds = _burst("POST", SITE + "/api/tensors", write_headers, post_body)
    post_counts = _classify(posts)
    print(
        f"POST burst: {post_counts} in {post_seconds:.1f} s; "
        f"statuses {sorted(r.status for r in posts)}"
    )
    try:
        assert get_counts["total"] == BURST and post_counts["total"] == BURST
        assert get_seconds <= WINDOW_S, f"the GET burst took {get_seconds:.1f} s (> 10 s): void"
        assert post_seconds <= WINDOW_S, f"the POST burst took {post_seconds:.1f} s (> 10 s): void"
        assert get_counts["no_response"] == 0, (
            f"GET burst: requests without a response: {get_counts}"
        )
        assert post_counts["no_response"] == 0, (
            f"POST burst: requests without a response: {post_counts}"
        )

        assert get_counts["edge_429"] == 0, (
            f"polling was rate-limited at the edge: {get_counts['edge_429']} GET response(s) "
            "with status 429 and no x-ps-source"
        )
        assert get_counts["ok_200"] >= 1, (
            f"no GET of the preset's 5y tensor returned 200 through the Worker: {get_counts}"
        )

        assert post_counts["edge_429"] >= 1, (
            f"no POST was rate-limited at the edge (429 without x-ps-source): {post_counts}"
        )
        # Must-not-contain: all 25 POSTs reaching the origin.
        assert post_counts["via_worker"] != BURST, (
            "every POST carried x-ps-source: none was stopped"
        )
    finally:
        if post_counts["via_worker"] > 0:
            time.sleep(61)
