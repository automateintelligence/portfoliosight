"""A-PS-26 — every /v1/* request without the gate secret is refused, in constant time.

Claim: every route under /v1/ returns 403 with the error envelope {"error": {"code": "forbidden",
...}} when x-ps-gate is absent or wrong, serves normally when it equals PS_GATE_SECRET, and the
comparison is hmac.compare_digest.

Pinned interface (the product must provide exactly this):
- `portfoliosight.api.app.create_app(*, store, clock, build_fn, start_worker)` (shared pin). The
  secret is `PS_GATE_SECRET` in the environment, set before `create_app` and still set while the
  requests run.
- The gate decision IS the return value of `hmac.compare_digest`, called at least once on every
  /v1/ request, including one with no `x-ps-gate` header (compare against an empty value rather
  than returning early). This file swaps `hmac.compare_digest` (and its alias
  `secrets.compare_digest`) for a counting wrapper before the product is imported, and in two legs
  forces the wrapper's answer: forced False must refuse the right secret, forced True must admit
  a wrong one. A decorative call next to `==` cannot pass that.
- `GET /v1/presets` serves `meta/{G}/presets.json` of the current generation and
  `GET /v1/symbols` serves `meta/symbols.json`, as stored.
- With the worker paused, a first valid `POST /v1/tensors` answers 202 and a GET of that key 202.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import io
import itertools
import json
import os
import secrets
import subprocess
import sys
import zlib
from datetime import date
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
        pytest.fail(f"A-PS-26 red: cannot import {module}: {type(exc).__name__}: {exc}")


# ---- shared fixture code (copied into every api-group gate file; keep in step) ----------------

LOOKBACKS = ("1y", "2y", "3y", "5y", "10y", "ew")
D_G = date(2026, 10, 7)  # a Wednesday, an ordinary XNYS session
HOLDINGS_CSV = ROOT / "data" / "holdings" / "holdings_guide2017_step2.csv"
TSP_CORE = ["TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I"]
_IP = itertools.count(1)


def _ip() -> str:
    """A fresh CF-Connecting-IP, so the per-IP limiter never couples unrelated requests."""
    n = next(_IP)
    return f"10.{(n >> 16) & 255}.{(n >> 8) & 255}.{n & 255}"


def _engine_version() -> str:
    version = getattr(_need("portfoliosight.engine"), "ENGINE_VERSION", None)
    if not isinstance(version, str) or not version:
        pytest.fail("A-PS-26 red: portfoliosight.engine.ENGINE_VERSION (str) is missing")
    return version


def _uhash(funds) -> str:
    """Spec §6 universe hash, computed here independently of the product."""
    rows = sorted(
        ({"id": f["id"], "min": f.get("min"), "max": f.get("max")} for f in funds),
        key=lambda f: f["id"],
    )
    canon = json.dumps({"schema": 2, "funds": rows}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _menu(ids, **caps):
    """Request funds for `ids`; caps as ID=(min, max)."""
    return [
        {"id": i, "min": caps.get(i, (None, None))[0], "max": caps.get(i, (None, None))[1]}
        for i in ids
    ]


class _RecStore:
    """Recording proxy over a store: logs every call to the five pinned methods."""

    def __init__(self, inner):
        self._inner = inner
        self.calls: list[tuple] = []

    def get(self, key):
        self.calls.append(("get", key))
        return self._inner.get(key)

    def put(self, key, data):
        self.calls.append(("put", key, bytes(data)))
        return self._inner.put(key, data)

    def exists(self, key):
        self.calls.append(("exists", key))
        return self._inner.exists(key)

    def list(self, prefix=""):
        self.calls.append(("list", prefix))
        return self._inner.list(prefix)

    def delete(self, key):
        self.calls.append(("delete", key))
        return self._inner.delete(key)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def puts(self, key=None):
        return [c for c in self.calls if c[0] == "put" and (key is None or c[1] == key)]


def _new_store(tmp_path, name="store"):
    local_store = getattr(_need("portfoliosight.data.store"), "LocalStore", None)
    if local_store is None:
        pytest.fail("A-PS-26 red: portfoliosight.data.store.LocalStore is missing")
    return _RecStore(local_store(tmp_path / name))


def _sessions(end: date, n: int):
    """The n XNYS sessions ending at `end` (plain weekdays if exchange_calendars is absent)."""
    pd = _need("pandas")
    try:
        cal = importlib.import_module("exchange_calendars").get_calendar("XNYS")
        idx = pd.DatetimeIndex(cal.sessions_window(pd.Timestamp(end), -n)).tz_localize(None)
    except Exception:
        idx = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    idx = pd.DatetimeIndex(idx).astype("datetime64[ns]")
    assert len(idx) == n and idx[-1] == pd.Timestamp(end), "gate fixture bug: session index"
    return idx


def _closes(symbol: str, n: int):
    """A deterministic synthetic close series: three shared factors plus own noise."""
    np = _need("numpy")
    factors = np.random.default_rng(7).normal(0.0, 0.006, size=(n, 3))
    rng = np.random.default_rng(zlib.crc32(symbol.encode()))
    if symbol == "TSP-G":
        r = 0.00015 + rng.normal(0.0, 0.0002, size=n)
    else:
        load = rng.uniform(-0.3, 1.0, size=3)
        r = (
            rng.uniform(0.0001, 0.0005)
            + factors @ load
            + rng.normal(0, rng.uniform(0.003, 0.008), n)
        )
    r[0] = 0.0
    return rng.uniform(20.0, 200.0) * np.cumprod(1.0 + r)


def _frame(symbol: str, dates, *, extra_row=None):
    """Canonical record frame; `extra_row` = (date, factor) appends one fully adjusted row."""
    pd = _need("pandas")
    close = _closes(symbol, len(dates))
    df = pd.DataFrame({"date": dates, "close": close})
    if extra_row is not None:
        tail = pd.DataFrame(
            {"date": [pd.Timestamp(extra_row[0])], "close": [close[-1] * extra_row[1]]}
        )
        df = pd.concat([df, tail], ignore_index=True)
    df["date"] = df["date"].astype("datetime64[ns]")
    df["tr_index"] = df["close"] / df["close"].iloc[0]
    df["div_cash"] = 0.0
    df["split_factor"] = 1.0
    return df


def _parquet(df) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def _seed_catalog(store, ids, dates, *, extra_row=None, short=()):
    """Write prices/*.parquet, meta/manifest.json and meta/symbols.json for `ids` (all `ok`).

    Symbols in `short` stop one session early (still inside the served rule, but not current).
    """
    frames, manifest, listing = {}, {}, []
    for sym in ids:
        df = _frame(sym, dates[:-1] if sym in short else dates, extra_row=extra_row)
        frames[sym] = df
        store.put(f"prices/{sym}.parquet", _parquet(df))
        tsp = sym.startswith("TSP-")
        last = df["date"].iloc[-1].date().isoformat()
        first = df["date"].iloc[0].date().isoformat()
        manifest[sym] = {
            "name": f"{sym} gate fund",
            "kind": "tsp" if tsp else "etf",
            "tier": 1,
            "income": False,
            "source": "tsp" if tsp else "seed+tiingo",
            "first_date": first,
            "last_date": last,
            "adjusted_through": last,
            "status": "ok",
            "reason": None,
            "fetched_at": "2026-10-08T08:00:00Z",
        }
        listing.append(
            {"id": sym, "name": manifest[sym]["name"], "kind": manifest[sym]["kind"], "tier": 1}
            | {"first_date": first}
        )
    store.put("meta/manifest.json", json.dumps({"symbols": manifest}).encode())
    symbols = {"catalog_at": "2026-10-08T08:00:00Z", "tiers_served": [1], "symbols": listing}
    store.put("meta/symbols.json", json.dumps(symbols).encode())
    return frames


def _seed_generation(store, g: str, asof: date, version: str, *, current=True, presets=None):
    """Hand-written published generation: only the pinned fields, plus placeholder presets."""
    gen = {"generation": g, "asof": asof.isoformat(), "engine_version": version}
    gen["created_at"] = "2026-10-08T09:00:00Z"
    store.put(f"meta/{g}/generation.json", json.dumps(gen).encode())
    body = presets or {"generation": g, "asof": asof.isoformat(), "presets": []}
    store.put(f"meta/{g}/presets.json", json.dumps(body).encode())
    if current:
        pointer = {"generation": g, "published_at": "2026-10-08T09:30:00Z"}
        store.put("meta/current.json", json.dumps(pointer).encode())
    return gen


def _manifest_symbols(store) -> dict:
    doc = json.loads(store.get("meta/manifest.json"))
    return doc["symbols"] if isinstance(doc.get("symbols"), dict) else doc


# ---- API harness ------------------------------------------------------------------------------

GATE = secrets.token_hex(24)  # a throwaway value for this run; never the real secret


def _hdr(**extra) -> dict:
    return {"x-ps-gate": GATE, "CF-Connecting-IP": _ip(), **extra}


def _make_app(store, monkeypatch, tmp_path, **kwargs):
    """create_app over `store` with the gate secret and a scratch cache dir in the environment."""
    monkeypatch.setenv("PS_GATE_SECRET", GATE)
    monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PS_CACHE_MAX_MB", "300")
    create_app = getattr(_need("portfoliosight.api.app"), "create_app", None)
    if create_app is None:
        pytest.fail("A-PS-26 red: portfoliosight.api.app.create_app is missing")
    kwargs.setdefault("clock", None)
    kwargs.setdefault("build_fn", None)
    kwargs.setdefault("start_worker", True)
    return create_app(store=store, **kwargs)


def _client(app):
    test_client = _need("fastapi.testclient").TestClient
    return test_client(app, raise_server_exceptions=False)


def _depth(client) -> int:
    """Queue depth as /v1/health reports it."""
    resp = client.get("/v1/health", headers=_hdr())
    assert resp.status_code == 200, f"GET /v1/health -> {resp.status_code}, expected 200"
    depth = resp.json().get("queue", {}).get("depth")
    assert isinstance(depth, int) and not isinstance(depth, bool), "health queue.depth is not int"
    return depth


def _error_code(resp):
    try:
        body = resp.json()
    except Exception:
        return None
    err = body.get("error") if isinstance(body, dict) else None
    return err.get("code") if isinstance(err, dict) else None


def _cache_tokens(resp) -> set:
    return {
        t.strip().lower() for t in resp.headers.get("cache-control", "").split(",") if t.strip()
    }


_REAL_COMPARE = hmac.compare_digest
_CD = {"calls": 0, "force": None}


def _counting_compare_digest(a, b):
    _CD["calls"] += 1
    result = _REAL_COMPARE(a, b)
    return result if _CD["force"] is None else _CD["force"]


if not _OUTER:
    hmac.compare_digest = _counting_compare_digest
    secrets.compare_digest = _counting_compare_digest


def _wrong_values() -> list[str]:
    flipped = ("0" if GATE[0] != "0" else "1") + GATE[1:]
    values = [flipped, GATE[:-1], GATE + "0", GATE.upper(), "", "wrong-value-entirely", GATE[::-1]]
    return [v for v in values if v != GATE]


def _send(client, method, path, body, gate):
    headers = {"CF-Connecting-IP": _ip()}
    if gate is not None:
        headers["x-ps-gate"] = gate
    before = _CD["calls"]
    resp = client.request(method, path, headers=headers, json=body)
    return resp, _CD["calls"] - before


if _OUTER:

    def test_a_ps_26_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-26 is red inside the project virtualenv (output above)"

else:

    def test_every_route_refuses_without_the_secret_and_serves_with_it(tmp_path, monkeypatch):
        version = _engine_version()
        g = f"{D_G.isoformat()}-{version}"
        store = _new_store(tmp_path)
        _seed_catalog(store, ["VTI", "BND", "VNQ"], _sessions(D_G, 400))
        presets = {
            "generation": g,
            "asof": D_G.isoformat(),
            "presets": [],
            "gate_marker": "a-ps-26",
        }
        _seed_generation(store, g, D_G, version, presets=presets)
        store.put("meta/status.json", json.dumps({"D_G": D_G.isoformat(), "errors": []}).encode())
        symbols_doc = json.loads(store.get("meta/symbols.json"))
        funds = _menu(["VTI", "BND", "VNQ"])
        post_body = {"funds": funds, "lookback": "1y"}
        tensor_path = f"/v1/tensors/{g}/{_uhash(funds)}/1y"
        routes = [
            ("GET", "/v1/health", None),
            ("GET", "/v1/presets", None),
            ("GET", "/v1/symbols", None),
            ("POST", "/v1/tensors", post_body),
            ("GET", tensor_path, None),
        ]
        wrong = _wrong_values()
        assert GATE not in wrong and len({len(GATE), len(wrong[0])}) == 1
        built = []
        app = _make_app(
            store,
            monkeypatch,
            tmp_path,
            start_worker=False,
            build_fn=lambda *a, **k: built.append(1),
        )
        _CD["force"] = None
        try:
            with _client(app) as client:
                puts_before = len(store.puts())
                refused = 0
                for method, path, body in routes:
                    for sent in [None] + wrong:
                        resp, compares = _send(client, method, path, body, sent)
                        label = f"{method} {path} with {'no header' if sent is None else 'a wrong value'}"
                        assert resp.status_code == 403, (
                            f"{label} -> {resp.status_code}, expected 403"
                        )
                        assert not 200 <= resp.status_code < 300
                        err = resp.json().get("error")
                        assert isinstance(err, dict) and err.get("code") == "forbidden", (
                            f"{label}: no envelope"
                        )
                        assert isinstance(err.get("message"), str) and "details" in err
                        assert GATE not in resp.text, (
                            f"{label}: the 403 body contains the expected secret"
                        )
                        assert GATE not in str(resp.headers)
                        if sent:
                            assert sent not in resp.text, (
                                f"{label}: the 403 body echoes the sent value"
                            )
                        assert compares >= 1, f"{label}: hmac.compare_digest was not called"
                        refused += 1
                assert refused == 5 * (1 + len(wrong)) >= 30
                assert len(store.puts()) == puts_before, "a refused request wrote to the store"

                # Right value: each route's normal answer.
                normal = {}
                for method, path, body in routes:
                    resp, compares = _send(client, method, path, body, GATE)
                    assert compares >= 1, f"{method} {path}: hmac.compare_digest was not called"
                    assert resp.status_code != 403, f"{method} {path} refused the right secret"
                    normal[(method, path)] = resp
                assert normal[("GET", "/v1/health")].status_code == 200
                assert normal[("GET", "/v1/health")].json()["queue"]["depth"] == 0, (
                    "a refused POST was enqueued"
                )
                assert normal[("GET", "/v1/presets")].status_code == 200
                assert normal[("GET", "/v1/presets")].json() == presets
                assert normal[("GET", "/v1/symbols")].status_code == 200
                assert normal[("GET", "/v1/symbols")].json() == symbols_doc
                posted = normal[("POST", "/v1/tensors")]
                assert posted.status_code == 202, f"POST /v1/tensors -> {posted.status_code}"
                assert posted.json()["hash"] == _uhash(funds)
                assert normal[("GET", tensor_path)].status_code == 202

                # The decision flows through compare_digest: force its answer both ways.
                _CD["force"] = False
                for method, path, body in routes:
                    resp, compares = _send(client, method, path, body, GATE)
                    assert resp.status_code == 403 and compares >= 1, (
                        f"{method} {path} admitted a request although hmac.compare_digest said no: "
                        "the gate does not decide with compare_digest"
                    )
                _CD["force"] = True
                for method, path, body in routes:
                    resp, compares = _send(client, method, path, body, wrong[0])
                    assert resp.status_code != 403 and compares >= 1, (
                        f"{method} {path} refused although hmac.compare_digest said yes: "
                        "another comparison is deciding"
                    )
                _CD["force"] = None
                resp, _ = _send(client, "GET", "/v1/health", None, wrong[0])
                assert resp.status_code == 403
        finally:
            _CD["force"] = None
        assert built == [], "the paused worker built something"
