"""A-PS-61 — private preview is on in production and no keyless path yields data.

Claim: the deployed Worker's `PS_PRIVATE_PREVIEW` var is "1", the committed `web/wrangler.jsonc`
says the same, and no request lacking the gate secret (no header, no valid `ps_preview` cookie)
receives data from `/`, `/api/presets`, `/api/symbols` or a tensor URL.

Runs from the laptop against production with the standard library, `git` and `wrangler`. Needs
`PS_GATE_SECRET` (only to learn a real tensor URL), `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID` (for wrangler); a missing variable is a failure naming it.

The spec's "a deployed var of 0 while the commercial license is not recorded" leg reduces here to:
the deployed var must be "1". (Opening to the public is an owner decision that changes this
assertion together with the spec.)

Pinned interface (the product must provide exactly this):
- `web/wrangler.jsonc`, committed, with `name: "portfoliosight"` and
  `vars.PS_PRIVATE_PREVIEW: "1"` (JSONC: comments and trailing commas allowed);
- `wrangler deployments list` and `wrangler versions view <id>` work from `web/` with the account
  token (`--json` preferred, text output accepted) and show the plain-text binding
  `PS_PRIVATE_PREVIEW`;
- `GET /api/presets` (spec 6): the preset `guide2017` with `lookbacks["5y"].url`;
- every keyless request is answered 403 by Cloudflare's challenge (`cf-mitigated: challenge`) or
  by the Worker's page containing "private preview".
If the active deployment's or version's annotations (`workers/message`, `workers/tag`) carry a
commit SHA of this repository, `web/wrangler.jsonc` at that commit is checked as well.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
CONFIG = WEB / "wrangler.jsonc"
VAR = "PS_PRIVATE_PREVIEW"

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


def _strip_jsonc(text: str) -> str:
    """JSONC -> JSON: drop // and /* */ comments and trailing commas, leaving strings untouched."""
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        char = text[i]
        if in_string:
            out.append(char)
            if char == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif char == '"':
                in_string = False
            i += 1
        elif char == '"':
            in_string = True
            out.append(char)
            i += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(char)
            i += 1
    cleaned = "".join(out)
    result: list[str] = []
    i, n = 0, len(cleaned)
    in_string = False
    while i < n:
        char = cleaned[i]
        if in_string:
            result.append(char)
            if char == "\\" and i + 1 < n:
                result.append(cleaned[i + 1])
                i += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            result.append(char)
        elif char == ",":
            j = i + 1
            while j < n and cleaned[j].isspace():
                j += 1
            if not (j < n and cleaned[j] in "}]"):
                result.append(char)
        else:
            result.append(char)
        i += 1
    return "".join(result)


def _preview_var(jsonc_text: str, where: str) -> str:
    try:
        config = json.loads(_strip_jsonc(jsonc_text))
    except ValueError as err:
        pytest.fail(f"{where} is not valid JSONC: {err}", pytrace=False)
    assert isinstance(config, dict), f"{where}: the top level is not an object"
    assert config.get("name") == "portfoliosight", f"{where}: name is {config.get('name')!r}"
    variables = config.get("vars")
    assert isinstance(variables, dict) and VAR in variables, f"{where}: vars.{VAR} is missing"
    return variables[VAR]


def _git(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        pytest.fail(f"git {' '.join(args[:2])} could not run: {type(err).__name__}", pytrace=False)


def _wrangler(*args: str) -> tuple[int, str, str]:
    """Run wrangler from web/; returns (exit code, scrubbed stdout, scrubbed stderr)."""
    local = WEB / "node_modules" / ".bin" / "wrangler"
    binary = str(local) if local.exists() else shutil.which("wrangler")
    if not binary:
        pytest.fail(
            "wrangler is not installed (no web/node_modules/.bin/wrangler, none on PATH)",
            pytrace=False,
        )
    env = dict(os.environ, CI="1", WRANGLER_SEND_METRICS="false", NO_COLOR="1", FORCE_COLOR="0")
    try:
        proc = subprocess.run(
            [binary, *args], cwd=WEB, env=env, capture_output=True, text=True, timeout=180
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"`wrangler {' '.join(args[:2])}` did not finish within 180 s", pytrace=False)
    except OSError as err:
        pytest.fail(f"wrangler could not be started: {type(err).__name__}: {err}", pytrace=False)
    return proc.returncode, _scrub(proc.stdout), _scrub(proc.stderr)


VERSION_ID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def _active_version(listing_json: str | None, listing_text: str) -> str | None:
    """The version id carrying the most traffic in the newest deployment."""
    data = _json_or_none(listing_json) if listing_json else None
    if isinstance(data, dict):
        data = data.get("deployments") or data.get("items") or data.get("result")
    if isinstance(data, list):
        deployments = [item for item in data if isinstance(item, dict) and item.get("versions")]
        if deployments:
            newest = max(deployments, key=lambda item: str(item.get("created_on") or ""))
            versions = [item for item in newest["versions"] if isinstance(item, dict)]
            if versions:
                top = max(versions, key=lambda item: float(item.get("percentage") or 0))
                found = top.get("version_id") or top.get("id")
                if isinstance(found, str) and re.fullmatch(VERSION_ID, found):
                    return found
    # Text output lists deployments oldest first: "(100%) <version id>".
    pairs = re.findall(rf"\((\d+(?:\.\d+)?)%\)\s+({VERSION_ID})", listing_text)
    if pairs:
        last_block = [pairs[-1]]
        return max(last_block, key=lambda pair: float(pair[0]))[1]
    return None


def _binding_value(view_json: str | None, view_text: str) -> str | None:
    """The deployed value of the plain-text binding PS_PRIVATE_PREVIEW, from JSON or text output."""
    data = _json_or_none(view_json) if view_json else None
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("name") == VAR:
                for key in ("text", "value", "json"):
                    if key in node:
                        return str(node[key])
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    match = re.search(rf"{VAR}[^\w\n]*([\w.\-]+)", view_text)
    return match.group(1) if match else None


def _annotated_shas(*documents: str | None) -> list[str]:
    found: list[str] = []
    for document in documents:
        data = _json_or_none(document) if document else None
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("workers/message", "workers/tag") and isinstance(value, str):
                        found.extend(re.findall(r"\b[0-9a-f]{7,40}\b", value))
                    else:
                        stack.append(value)
            elif isinstance(node, list):
                stack.extend(node)
    return found


def _need_config() -> None:
    if not CONFIG.is_file():
        pytest.fail("web/wrangler.jsonc is missing: the Worker is not built yet", pytrace=False)


def test_a_ps_61_committed_wrangler_config_has_preview_on():
    _env("PS_GATE_SECRET")
    _need_config()
    working = _preview_var(CONFIG.read_text(encoding="utf-8"), "web/wrangler.jsonc")
    assert working == "1", f"web/wrangler.jsonc: vars.{VAR} is {working!r}, expected the string '1'"
    shown = _git("show", "HEAD:web/wrangler.jsonc")
    assert shown.returncode == 0, "web/wrangler.jsonc is not committed at HEAD"
    committed = _preview_var(shown.stdout, "HEAD:web/wrangler.jsonc")
    assert committed == "1", f"HEAD:web/wrangler.jsonc: vars.{VAR} is {committed!r}"
    assert committed != "0", "the committed config opens the site to the public"


def test_a_ps_61_deployed_worker_var_is_1():
    _env("PS_GATE_SECRET")
    _env("CLOUDFLARE_API_TOKEN")
    _env("CLOUDFLARE_ACCOUNT_ID")
    _need_config()
    code, out, err = _wrangler("deployments", "list", "--json")
    listing_json, listing_text = (out, out) if code == 0 else (None, "")
    version = _active_version(listing_json, listing_text)
    if version is None:
        code, out, err = _wrangler("deployments", "list")
        listing_json, listing_text = None, out
        version = _active_version(None, out) if code == 0 else None
    assert version is not None, (
        f"`wrangler deployments list` named no active version (exit {code}): {(out + err)[-1200:]}"
    )

    code, out, err = _wrangler("versions", "view", version, "--json")
    view_json, view_text = (out, out) if code == 0 else (None, "")
    value = _binding_value(view_json, view_text)
    if value is None:
        code, out, err = _wrangler("versions", "view", version)
        view_json = None
        value = _binding_value(None, out) if code == 0 else None
    assert value is not None, (
        f"`wrangler versions view {version}` does not list {VAR} (exit {code}): "
        f"{(out + err)[-1200:]}"
    )
    print(f"deployed version {version}: {VAR} = {value!r}")
    # The license leg reduces to this: while this assertion stands, the deployed var must be "1".
    assert value != "0", f"the deployed Worker has {VAR}=0: the site is open to the public"
    assert value == "1", f"the deployed Worker has {VAR}={value!r}, expected '1'"

    checked_shas = 0
    for sha in _annotated_shas(listing_json, view_json):
        if _git("cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            continue
        shown = _git("show", f"{sha}:web/wrangler.jsonc")
        assert shown.returncode == 0, f"web/wrangler.jsonc does not exist at deployed commit {sha}"
        at_sha = _preview_var(shown.stdout, f"{sha}:web/wrangler.jsonc")
        assert at_sha == "1", f"{sha}:web/wrangler.jsonc has vars.{VAR}={at_sha!r}"
        checked_shas += 1
    print(f"deployed-commit configs checked: {checked_shas}")


def _tensor_url(secret: str) -> str:
    resp = _reached(
        _http("GET", SITE + "/api/presets", {"x-ps-gate": secret, "Accept": "application/json"}),
        "GET /api/presets with the header (to learn a tensor URL)",
    )
    assert resp.status == 200, f"GET /api/presets with the header: status {resp.status}"
    body = _json_or_none(resp.text)
    presets = body.get("presets") if isinstance(body, dict) else None
    assert isinstance(presets, list) and presets, "GET /api/presets: no presets list"
    chosen = [item for item in presets if isinstance(item, dict) and item.get("id") == "guide2017"]
    assert chosen, "GET /api/presets: the default preset `guide2017` is missing"
    url = ((chosen[0].get("lookbacks") or {}).get("5y") or {}).get("url")
    pattern = r"/api/tensors/\d{4}-\d{2}-\d{2}-[0-9.]+/[0-9a-f]{16}/5y"
    assert isinstance(url, str) and re.fullmatch(pattern, url), f"5y tensor url is {url!r}"
    return url


def test_a_ps_61_no_keyless_request_receives_data():
    secret = _env("PS_GATE_SECRET")
    tensor_url = _tensor_url(secret)
    # Control: with the key the tensor path does yield data, so its absence below means something.
    keyed = _reached(_http("GET", SITE + tensor_url, {"x-ps-gate": secret}), "keyed tensor GET")
    assert keyed.status == 200, f"keyed GET of the tensor: status {keyed.status}, expected 200"
    assert isinstance(_json_or_none(keyed.text), dict), "keyed GET of the tensor: not JSON"

    keyless = {
        "no credentials": {},
        "wrong x-ps-gate header": {"x-ps-gate": "not-the-key-0000000000000000"},
        "forged ps_preview cookie": {"Cookie": "ps_preview=not-the-key-0000000000000000"},
    }
    checked = 0
    for path in ("/", "/api/presets", "/api/symbols", tensor_url):
        for label, headers in keyless.items():
            what = f"GET {path} with {label}"
            resp = _reached(_http("GET", SITE + path, headers), what)
            lowered = resp.text.lower()
            assert resp.status != 200, f"{what}: 200 on a keyless path"
            assert resp.status == 403, f"{what}: status {resp.status}, expected 403"
            challenged = resp.headers.get("cf-mitigated") == "challenge"
            preview_page = "private preview" in lowered
            assert challenged or preview_page, (
                f"{what}: neither Cloudflare's challenge nor the private-preview page"
            )
            assert "x-ps-source" not in resp.headers, f"{what}: x-ps-source header (data path)"
            assert _json_or_none(resp.text) is None, f"{what}: a JSON body was served"
            assert "<canvas" not in lowered, f"{what}: a <canvas element was served"
            assert "chart-canvas" not in lowered, f"{what}: the chart-canvas marker was served"
            checked += 1
    assert checked == 12, f"only {checked} of 12 keyless requests were checked"
