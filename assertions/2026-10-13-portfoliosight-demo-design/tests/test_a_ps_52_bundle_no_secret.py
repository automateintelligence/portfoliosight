"""A-PS-52 — the bundle carries no secret, no gate header and no origin host.

Claim: `web/dist` after `npm run build` contains none of the secret values from
`~/.secrets/portfoliosight.env` (`PS_ADMIN_SECRET` included, 2026-10-15), neither the strings
`x-ps-gate`, `PS_GATE_SECRET`, `x-ps-tier`, `PS_ADMIN_SECRET` nor `ps_admin`, nor the host
`api.portfoliosight.ai`; every API call in the bundle targets a same-origin `/api/` path.

Pinned interface (the product must provide exactly this): `web/package.json` with a `build`
script that writes the site to `web/dist` (an `index.html` plus at least one JavaScript file);
`web/node_modules` installed; `npm` on PATH. Secret values are read from the environment (the
caller loads the env file).
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "web"
DIST = WEB / "dist"
# The seven credentials of the env file. PS_SHARE_TEST_RECIPIENT is left out on purpose: it is an
# e-mail address, not a credential, and may equal an address the page legitimately shows.
SECRET_NAMES = (
    "PS_GATE_SECRET",
    "PS_ADMIN_SECRET",
    "TIINGO_API_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
)
FORBIDDEN = (
    "x-ps-gate",
    "PS_GATE_SECRET",
    "x-ps-tier",
    "PS_ADMIN_SECRET",
    "ps_admin",
    "api.portfoliosight.ai",
    "MAILCHANNELS",
)
CODE_SUFFIXES = {".js", ".mjs", ".cjs", ".html", ".htm"}
ABSOLUTE_API = re.compile(rb"https?://[^\s\"'`<>()\\]*/api/", re.IGNORECASE)
ORIGIN_PATH = re.compile(rb"/v1/")
_BUILT: dict = {}


def _secret_values() -> dict[str, bytes]:
    """Secret values by variable name; never printed. Fewer than five would make the scan vacuous."""
    values = {name: os.environ.get(name, "").strip() for name in SECRET_NAMES}
    usable = {name: value.encode() for name, value in values.items() if len(value) >= 8}
    if len(usable) < 5:
        absent = sorted(set(SECRET_NAMES) - set(usable))
        pytest.fail(
            f"A-PS-52 red: secret env not loaded ({len(usable)} of {len(SECRET_NAMES)} values "
            f"usable, need >= 5; missing or too short: {absent})"
        )
    return usable


def _bundle() -> list[tuple[str, bytes]]:
    """A fresh `npm run build`, then (relative path, bytes) of every file under web/dist."""
    if "files" in _BUILT:
        return _BUILT["files"]
    if not (WEB / "package.json").is_file():
        pytest.fail("A-PS-52 red: web/package.json does not exist (no front end to build)")
    if not (WEB / "node_modules").is_dir():
        pytest.fail("A-PS-52 red: web/node_modules is missing; run `npm ci` in web/ first")
    env = dict(os.environ)
    env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    started = time.time()
    try:
        proc = subprocess.run(
            ["npm", "run", "build"], cwd=WEB, env=env, capture_output=True, text=True, timeout=540
        )
    except FileNotFoundError:
        pytest.fail("A-PS-52 red: `npm` is not on PATH")
    except subprocess.TimeoutExpired:
        pytest.fail("A-PS-52 red: `npm run build` did not finish within 540 s")
    assert proc.returncode == 0, (
        f"A-PS-52 red: `npm run build` exited {proc.returncode}:\n"
        + (proc.stdout[-2000:] + "\n" + proc.stderr[-2000:]).strip()
    )
    index = DIST / "index.html"
    if not index.is_file():
        pytest.fail("A-PS-52 red: the build wrote no web/dist/index.html")
    assert index.stat().st_mtime >= started - 2, (
        "A-PS-52 red: web/dist/index.html is older than this build; the bundle is not fresh"
    )
    files = [
        (path.relative_to(DIST).as_posix(), path.read_bytes())
        for path in sorted(DIST.rglob("*"))
        if path.is_file()
    ]
    _BUILT["files"] = files
    return files


def _hits(files, needle: bytes, *, fold: bool = False) -> list[str]:
    needle = needle.lower() if fold else needle
    return [name for name, data in files if needle in (data.lower() if fold else data)]


def test_scan_reads_the_real_bundle():
    files = _bundle()
    scripts = [name for name, _ in files if Path(name).suffix in (".js", ".mjs")]
    assert scripts, f"A-PS-52 red: web/dist holds no JavaScript file ({len(files)} files)"
    found = _hits(files, b"/api/presets")
    assert found, "A-PS-52 red: no file under web/dist mentions /api/presets; not the real bundle"
    assert any(Path(name).suffix in (".js", ".mjs") for name in found), (
        f"A-PS-52 red: /api/presets appears only outside the bundle's JavaScript: {found}"
    )


def test_no_secret_value_in_any_bundle_file():
    values = _secret_values()
    files = _bundle()
    assert len(files) >= 2
    leaked = {}
    for name, value in values.items():
        found = _hits(files, value)
        if found:
            leaked[name] = (len(found), found[:5])
    assert not leaked, f"A-PS-52 red: secret values in web/dist (variable: count, files): {leaked}"


def test_no_gate_header_secret_name_origin_host_or_mail_key_in_any_bundle_file():
    files = _bundle()
    found = {token: _hits(files, token.encode(), fold=True) for token in FORBIDDEN}
    found = {token: names for token, names in found.items() if names}
    assert not found, f"A-PS-52 red: forbidden strings in web/dist: {found}"


def test_every_api_call_is_same_origin():
    files = _bundle()
    code = [(name, data) for name, data in files if Path(name).suffix in CODE_SUFFIXES]
    assert code, "A-PS-52 red: no script or page in web/dist to check"
    absolute = {
        name: [m.decode(errors="replace")[:120] for m in ABSOLUTE_API.findall(data)[:3]]
        for name, data in code
        if ABSOLUTE_API.search(data)
    }
    assert not absolute, f"A-PS-52 red: the bundle calls an absolute API URL: {absolute}"
    origin = [name for name, data in code if ORIGIN_PATH.search(data)]
    assert not origin, f"A-PS-52 red: the bundle addresses the origin's /v1/ paths: {origin}"
    assert any(b"/api/" in data for _, data in code)
