"""A-PS-33 — the API surface is exactly the spec §6 table.

Claim: the FastAPI application's routes under /v1/ are exactly GET /v1/health, GET /v1/presets,
GET /v1/symbols, POST /v1/tensors, GET /v1/tensors/{G}/{hash}/{lookback}, with the path constraints
G = \\d{4}-\\d{2}-\\d{2}-[0-9.]+ and hash = [0-9a-f]{16} enforced, and the application registers no
other route whose path contains login, auth, account, signup, pay or checkout.

Pinned interface (the product must provide exactly this):
- `portfoliosight.api.app.create_app(*, store, clock, build_fn, start_worker)` (shared pin);
  `PS_GATE_SECRET` from the environment; requests carry `x-ps-gate` and `CF-Connecting-IP`.
- The five routes are registered directly on the app (`app.routes`, each with `.path` and
  `.methods`), with GET routes registered for GET only (no HEAD/OPTIONS twin, as FastAPI's
  `@app.get` does). Path parameter names are free: `{name}` / `{name:conv}` is compared as `{}`.
- No registered route path may contain `auth`: FastAPI's default `/docs/oauth2-redirect` breaks
  this, so the app must turn the interactive docs off (or at least
  `swagger_ui_oauth2_redirect_url=None`).
- A tensor GET whose `G` or `hash` segment is malformed is refused (400, 404 or 422) before any
  call to the store.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import itertools
import json
import os
import re
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
        pytest.fail(f"A-PS-33 red: cannot import {module}: {type(exc).__name__}: {exc}")


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
        pytest.fail("A-PS-33 red: portfoliosight.engine.ENGINE_VERSION (str) is missing")
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
        pytest.fail("A-PS-33 red: portfoliosight.data.store.LocalStore is missing")
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
        pytest.fail("A-PS-33 red: portfoliosight.api.app.create_app is missing")
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


EXPECTED_ROUTES = {
    ("GET", "/v1/health"),
    ("GET", "/v1/presets"),
    ("GET", "/v1/symbols"),
    ("POST", "/v1/tensors"),
    ("GET", "/v1/tensors/{}/{}/{}"),
}
FORBIDDEN = re.compile(r"login|auth|account|signup|pay|checkout", re.IGNORECASE)
GOOD_HASH = "0123456789abcdef"


def _seeded_app(tmp_path, monkeypatch):
    version = _engine_version()
    g = f"{D_G.isoformat()}-{version}"
    store = _new_store(tmp_path)
    _seed_catalog(store, ["VTI", "BND", "VNQ"], _sessions(D_G, 400))
    _seed_generation(store, g, D_G, version)
    app = _make_app(store, monkeypatch, tmp_path, start_worker=False)
    return store, g, app


def _route_set(app) -> set:
    found = set()
    for route in app.routes:
        path = getattr(route, "path", "") or ""
        if not path.startswith("/v1"):
            continue
        norm = re.sub(r"\{[^}]*\}", "{}", path)
        methods = getattr(route, "methods", None)
        if not methods:  # a Mount or WebSocket under /v1 is a route the table does not have
            found.add((type(route).__name__, norm))
        for method in methods or ():
            found.add((method, norm))
    return found


if _OUTER:

    def test_a_ps_33_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-33 is red inside the project virtualenv (output above)"

else:

    def test_route_set_is_exactly_the_five(tmp_path, monkeypatch):
        _, g, app = _seeded_app(tmp_path, monkeypatch)
        routes = _route_set(app)
        assert routes == EXPECTED_ROUTES, (
            f"extra: {sorted(routes - EXPECTED_ROUTES)}; missing: {sorted(EXPECTED_ROUTES - routes)}"
        )
        assert len(routes) == 5 and not (routes - EXPECTED_ROUTES), (
            "a sixth /v1/ route is registered"
        )
        paths = [getattr(r, "path", "") or "" for r in app.routes]
        assert len(paths) >= 5
        bad = [p for p in paths if FORBIDDEN.search(p)]
        assert not bad, f"routes with a forbidden token: {bad}"
        with _client(app) as client:
            for path in ("/login", "/auth", "/account", "/signup", "/pay", "/checkout"):
                for prefix in ("", "/v1"):
                    resp = client.get(prefix + path, headers=_hdr())
                    assert resp.status_code in (403, 404), (
                        f"GET {prefix + path} -> {resp.status_code}"
                    )
                    assert not 200 <= resp.status_code < 300
            unlisted = [
                ("DELETE", f"/v1/tensors/{g}/{GOOD_HASH}/5y"),
                ("PUT", f"/v1/tensors/{g}/{GOOD_HASH}/5y"),
                ("POST", "/v1/presets"),
                ("POST", "/v1/symbols"),
                ("POST", "/v1/health"),
                ("DELETE", "/v1/tensors"),
                ("GET", "/v1/tensors"),
                ("GET", f"/v1/tensors/{g}"),
                ("GET", "/v1/jobs"),
                ("GET", "/v1/"),
            ]
            for method, path in unlisted:
                resp = client.request(method, path, headers=_hdr())
                assert resp.status_code in (404, 405), f"{method} {path} -> {resp.status_code}"
                assert resp.status_code != 200

    def test_malformed_tensor_paths_never_reach_the_store(tmp_path, monkeypatch):
        store, g, app = _seeded_app(tmp_path, monkeypatch)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-[0-9.]+", g)
        malformed = [
            "/v1/tensors/2026-10-12-0.1.0/zz/5y",  # the spec's bad hash
            "/v1/tensors/bad/0123456789abcdef/5y",  # the spec's bad G
            f"/v1/tensors/{g}/zz/5y",
            f"/v1/tensors/{g}/0123456789abcde/5y",  # 15 hex
            f"/v1/tensors/{g}/0123456789abcdef0/5y",  # 17 hex
            f"/v1/tensors/{g}/0123456789ABCDEF/5y",  # upper case
            f"/v1/tensors/{g}/0123456789abcdeg/5y",  # not hex
            f"/v1/tensors/{g}/meta.current.json/5y",
            f"/v1/tensors/bad/{GOOD_HASH}/5y",
            f"/v1/tensors/2026-10-7-0.1.0/{GOOD_HASH}/5y",
            f"/v1/tensors/20261007-0.1.0/{GOOD_HASH}/5y",
            f"/v1/tensors/2026-10-07-/{GOOD_HASH}/5y",
            f"/v1/tensors/2026-10-07-0.1.0a/{GOOD_HASH}/5y",
            f"/v1/tensors/x{g}/{GOOD_HASH}/5y",
            f"/v1/tensors/{g}x/{GOOD_HASH}/5y",
            f"/v1/tensors/current/{GOOD_HASH}/5y",
        ]
        # Objects sitting where an unvalidated path would look must never be served.
        store.put(f"tensors/{g}/zz/5y.json", b'{"planted": true}')
        store.put(f"tensors/bad/{GOOD_HASH}/5y.json", b'{"planted": true}')
        with _client(app) as client:
            # Control: the app really reads through this store, and a well-formed unknown key is a 404.
            before = len(store.calls)
            assert client.get("/v1/presets", headers=_hdr()).status_code == 200
            assert len(store.calls) > before, "the app does not read through the store it was given"
            ok = client.get(f"/v1/tensors/{g}/{GOOD_HASH}/5y", headers=_hdr())
            assert ok.status_code == 404 and _error_code(ok) == "unknown_tensor", (
                f"well-formed, never-requested key -> {ok.status_code} {_error_code(ok)}"
            )
            checked = 0
            for path in malformed:
                before = len(store.calls)
                resp = client.get(path, headers=_hdr())
                assert resp.status_code in (400, 404, 422), f"GET {path} -> {resp.status_code}"
                assert not 200 <= resp.status_code < 300 and "planted" not in resp.text
                touched = store.calls[before:]
                assert touched == [], f"GET {path} touched the store: {[c[:2] for c in touched]}"
                assert not [c for c in touched if c[0] == "get"]
                checked += 1
        assert checked == len(malformed) >= 16
