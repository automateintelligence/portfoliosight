"""A-PS-56 — presets and tensors are served from R2 and a POST for the default preset resolves to the same tensor.

Claim: `GET /api/presets` carries `x-ps-source: r2`, a `generation`, and both presets with all six
lookbacks `ready` and `/api/...` URLs; the `guide2017` 5y URL returns a tensor that validates
against `portfoliosight/engine/tensor.schema.json` with `Cache-Control: public, max-age=86400,
immutable`, an `ETag` and `x-ps-source: r2`; a `POST /api/tensors` with the default preset's funds
and all-`null` caps returns 200 with a `url` whose body is byte-identical to that tensor.

Runs from the laptop against production, inside the project virtualenv (needs `jsonschema`).
Environment: `PS_GATE_SECRET` (never printed).

Pinned interface (the product must provide exactly this):
- `GET https://portfoliosight.ai/api/presets` -> 200, `x-ps-source: r2`, body `{"generation": G,
  "asof", "presets": [...]}` with preset ids exactly `guide2017` and `tsp`; each preset has `hash`
  (16 hex), `funds` (`id`), `lookbacks` with exactly `1y, 2y, 3y, 5y, 10y, ew`, each
  `{"status": "ready", "url": "/api/tensors/{G}/{hash}/{lookback}"}` (spec §6).
- `GET https://portfoliosight.ai/api/tensors/{G}/{hash}/5y` -> 200, `Cache-Control: public,
  max-age=86400, immutable`, an `ETag`, `x-ps-source: r2`, a spec §7 tensor.
- `portfoliosight/engine/tensor.schema.json` (JSON Schema, the contract of spec §7).
- `data/holdings/holdings_guide2017_step2.csv` column `Symbol`: the 23 funds of the default preset;
  FIENX is in the tensor's `universe.excluded` with reason
  "converted to an ETF; no data since 2024-10-30".
- `POST https://portfoliosight.ai/api/tensors` `{"funds": [{"id", "min": null, "max": null}...],
  "lookback": "5y"}` -> 200 `{"status": "ready", "generation", "hash", "url"}` (never 202 for the
  preset key).
"""

from __future__ import annotations

import csv
import functools
import http.client
import importlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
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
        pytest.fail(f"A-PS-56 red: cannot import {module}: {type(exc).__name__}: {exc}")


SITE = "https://portfoliosight.ai"
SCHEMA = ROOT / "portfoliosight" / "engine" / "tensor.schema.json"
HOLDINGS = ROOT / "data" / "holdings" / "holdings_guide2017_step2.csv"
LOOKBACKS = {"1y", "2y", "3y", "5y", "10y", "ew"}
GENERATION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[0-9.]+$")
HASH_RE = re.compile(r"^[0-9a-f]{16}$")
TENSOR_CACHE_CONTROL = "public, max-age=86400, immutable"
FIENX_REASON = "converted to an ETF; no data since 2024-10-30"
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
            pytest.fail(f"A-PS-56 red: {what} answered {self.status} with a body that is not JSON")


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(
            f"A-PS-56 red: environment variable {name} is not set "
            "(the caller loads ~/.secrets/portfoliosight.env)"
        )
    return value


def _http(method: str, url: str, *, payload=None, timeout: float = 30.0) -> _Resp:
    """One request with the gate header, redirects not followed; no connection = clean failure."""
    send = {"User-Agent": UA, "Accept": "application/json", "x-ps-gate": _env("PS_GATE_SECRET")}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        send["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method, headers=send, data=data)
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
        pytest.fail(f"A-PS-56 red: cannot reach {url}: {type(err).__name__}: {reason}")


@functools.lru_cache(maxsize=1)
def _presets() -> tuple[_Resp, dict]:
    resp = _http("GET", f"{SITE}/api/presets")
    assert resp.status == 200, f"/api/presets answered {resp.status}"
    body = resp.json("/api/presets")
    assert isinstance(body, dict), "/api/presets body is not a JSON object"
    return resp, body


def _preset(body: dict, preset_id: str) -> dict:
    match = [p for p in body.get("presets", []) if isinstance(p, dict) and p.get("id") == preset_id]
    assert len(match) == 1, f"/api/presets does not list exactly one preset with id {preset_id}"
    return match[0]


@functools.lru_cache(maxsize=1)
def _guide_tensor() -> tuple[_Resp, dict, dict]:
    _, body = _presets()
    preset = _preset(body, "guide2017")
    url = ((preset.get("lookbacks") or {}).get("5y") or {}).get("url")
    assert isinstance(url, str) and url.startswith("/api/tensors/"), f"guide2017 5y url is {url!r}"
    resp = _http("GET", SITE + url)
    assert resp.status == 200, f"GET {url} answered {resp.status}"
    return resp, body, preset


def _step2_symbols() -> set[str]:
    if not HOLDINGS.is_file():
        pytest.fail(f"A-PS-56 red: {HOLDINGS.relative_to(ROOT)} is missing")
    with HOLDINGS.open(newline="", encoding="utf-8") as handle:
        return {
            row["Symbol"].strip().upper() for row in csv.DictReader(handle) if row.get("Symbol")
        }


if _OUTER:

    def test_a_ps_56_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-56 is red inside the project virtualenv (output above)"

else:

    def test_presets_come_from_r2_with_both_presets_and_six_ready_lookbacks():
        resp, body = _presets()
        source = resp.header("x-ps-source")
        assert source != "origin", "/api/presets was served by the origin, not from R2"
        assert source == "r2", f"/api/presets x-ps-source is {source!r}, expected 'r2'"
        generation = body.get("generation")
        assert isinstance(generation, str) and GENERATION_RE.match(generation), (
            f"/api/presets generation is {generation!r}"
        )
        asof = body.get("asof")
        assert isinstance(asof, str) and generation.startswith(asof + "-"), (
            f"/api/presets asof {asof!r} is not the date part of generation {generation!r}"
        )
        presets = body.get("presets")
        assert isinstance(presets, list), "/api/presets has no presets list"
        ids = [p.get("id") for p in presets if isinstance(p, dict)]
        assert sorted(ids) == ["guide2017", "tsp"], (
            f"preset ids are {ids}, expected guide2017 and tsp"
        )
        hashes = set()
        urls = set()
        for preset in presets:
            pid = preset["id"]
            key = preset.get("hash")
            assert isinstance(key, str) and HASH_RE.match(key), f"{pid}: hash is {key!r}"
            hashes.add(key)
            lookbacks = preset.get("lookbacks")
            assert isinstance(lookbacks, dict), f"{pid}: lookbacks is not an object"
            assert set(lookbacks) == LOOKBACKS, f"{pid}: lookback ids are {sorted(lookbacks)}"
            for lookback, entry in lookbacks.items():
                status = entry.get("status") if isinstance(entry, dict) else None
                assert status == "ready", f"{pid}/{lookback}: status is {status!r}, not ready"
                url = entry.get("url")
                assert isinstance(url, str) and url.startswith(f"/api/tensors/{generation}/"), (
                    f"{pid}/{lookback}: url {url!r} does not start with /api/tensors/{generation}/"
                )
                assert url == f"/api/tensors/{generation}/{key}/{lookback}", (
                    f"{pid}/{lookback}: url {url!r} is not /api/tensors/{{G}}/{{hash}}/{{lookback}}"
                )
                assert "/v1/" not in url, f"{pid}/{lookback}: url exposes the service path"
                urls.add(url)
        assert len(hashes) == 2, "the two presets share one hash"
        assert len(urls) == 12, f"expected 12 distinct preset tensor URLs, found {len(urls)}"

    def test_guide2017_5y_tensor_is_schema_valid_immutable_and_from_r2():
        jsonschema = _need("jsonschema")
        resp, body, preset = _guide_tensor()
        source = resp.header("x-ps-source")
        assert source != "origin", "the preset tensor was served by the origin, not from R2"
        assert source == "r2", f"tensor x-ps-source is {source!r}, expected 'r2'"
        cache_control = resp.header("cache-control")
        assert cache_control == TENSOR_CACHE_CONTROL, f"tensor Cache-Control is {cache_control!r}"
        assert resp.header("etag"), "the tensor response has no ETag"

        if not SCHEMA.is_file():
            pytest.fail(f"A-PS-56 red: {SCHEMA.relative_to(ROOT)} is missing")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
        assert schema.get("required") or schema.get("properties"), (
            "tensor.schema.json constrains nothing (no required keys, no properties)"
        )
        tensor = resp.json("the guide2017 5y tensor")
        errors = sorted(
            validator_cls(schema).iter_errors(tensor), key=lambda e: list(e.absolute_path)
        )
        assert not errors, "tensor fails tensor.schema.json: " + "; ".join(
            f"{'/'.join(map(str, e.absolute_path))}: {e.message[:120]}" for e in errors[:5]
        )

        assert tensor.get("generation") == body.get("generation"), "tensor generation != presets'"
        assert tensor.get("asof") == body.get("asof"), "tensor asof != presets' asof"
        universe = tensor.get("universe") or {}
        assert universe.get("preset_id") == "guide2017", (
            f"preset_id is {universe.get('preset_id')!r}"
        )
        assert universe.get("hash") == preset.get("hash"), (
            "tensor universe.hash != the preset's hash"
        )
        assert (tensor.get("lookback") or {}).get("id") == "5y", "tensor lookback.id is not 5y"
        included = [f.get("id") for f in universe.get("funds", [])]
        excluded = {e.get("id"): e.get("reason") for e in universe.get("excluded", [])}
        step2 = _step2_symbols()
        assert len(step2) == 23, f"the Step 2 holdings file lists {len(step2)} symbols, expected 23"
        assert len(included) == len(set(included)), "universe.funds repeats an id"
        assert not set(included) & set(excluded), "a fund is both included and excluded"
        assert set(included) | set(excluded) == step2, (
            "funds plus excluded are not the 23 Step 2 funds; "
            f"missing {sorted(step2 - set(included) - set(excluded))}, "
            f"extra {sorted((set(included) | set(excluded)) - step2)}"
        )
        assert len(included) == 23 - len(excluded), "funds is not 23 minus excluded"
        assert "FIENX" in excluded, "FIENX is not in universe.excluded"
        assert "FIENX" not in included, "FIENX is listed as an included fund"
        assert excluded["FIENX"] == FIENX_REASON, f"FIENX reason is {excluded['FIENX']!r}"
        assert {f.get("id") for f in preset.get("funds", [])} == step2, (
            "the preset's funds in /api/presets are not the 23 Step 2 funds"
        )

    def test_post_for_the_default_preset_returns_200_and_the_same_bytes():
        tensor_resp, body, preset = _guide_tensor()
        fund_ids = [f.get("id") for f in preset.get("funds", []) if isinstance(f, dict)]
        assert len(fund_ids) == 23, f"the default preset lists {len(fund_ids)} funds, expected 23"
        request = {
            "funds": [{"id": i, "min": None, "max": None} for i in fund_ids],
            "lookback": "5y",
        }
        post = _http("POST", f"{SITE}/api/tensors", payload=request)
        assert post.status != 202, "the POST for the preset key was enqueued (202), not resolved"
        assert post.status == 200, f"POST /api/tensors answered {post.status}, expected 200"
        answer = post.json("POST /api/tensors")
        assert answer.get("status") == "ready", f"POST status is {answer.get('status')!r}"
        assert answer.get("hash") == preset.get("hash"), "POST hash != the preset's hash"
        assert answer.get("generation") == body.get("generation"), "POST generation != presets'"
        url = answer.get("url")
        assert isinstance(url, str) and url.startswith("/api/tensors/"), f"POST url is {url!r}"

        again = _http("GET", SITE + url)
        assert again.status == 200, f"GET {url} answered {again.status}"
        assert again.header("x-ps-source") != "origin", "the POST's url was served by the origin"
        assert again.header("x-ps-source") == "r2", "the POST's url was not served from R2"
        assert len(tensor_resp.body) > 10_000, "the preset tensor body is implausibly small"
        assert again.body == tensor_resp.body, (
            f"the POST's url body ({len(again.body)} bytes) is not byte-identical to the preset "
            f"tensor ({len(tensor_resp.body)} bytes)"
        )
        assert again.header("etag") and again.header("etag") == tensor_resp.header("etag"), (
            "the two tensor responses do not carry the same ETag"
        )
