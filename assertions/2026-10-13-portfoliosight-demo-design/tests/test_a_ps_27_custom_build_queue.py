"""A-PS-27 — a custom build runs to ready, is deduplicated, retries a failure at most three
times, and never overwrites a key.

Claim: POST /v1/tensors for a new key returns 202 queued with a position, polling
GET /v1/tensors/{G}/{hash}/{lookback} returns 202 then 200 with the tensor, ETag and
Cache-Control: public, max-age=86400, immutable; a second POST for the same key returns its state
without a second job; a job that raises yields 409 failed with attempts, is re-enqueued by a later
POST up to 3 attempts, and the third failure returns retry: false; a tensor key once written is
never overwritten; URLs in responses are public /api/... paths.

Pinned interface (the product must provide exactly this):
- `portfoliosight.api.app.create_app(*, store, clock, build_fn, start_worker)` (shared pin);
  `PS_GATE_SECRET` and `PS_CACHE_DIR` from the environment.
- `portfoliosight.api.queue.build_job`: the default `build_fn`. The worker calls `build_fn` once
  per attempt; it builds one tensor and writes `tensors/{G}/{hash}/{lookback}.json` to the store,
  and it does not write when the key already exists (calling it again with the same arguments
  performs no `put`). This file wraps it with a `*args, **kwargs` pass-through; the 16-hex universe
  hash must be among the call's argument values (positional or keyword, or one level inside a
  dict / tuple / dataclass argument). Nothing else about the signature is assumed.
- A build needs only: `meta/current.json`, `meta/{G}/generation.json` with `generation`, `asof`,
  `engine_version`, `meta/manifest.json`, and the `prices/*.parquet` of the requested funds
  (three synthetic symbols, 400 sessions ending at D_G = 2026-10-07, all `ok`).
- Job state is observed from outside: HTTP answers, `queue` in `GET /v1/health` (`building` is
  true while `build_fn` runs), the number of `build_fn` calls per key, and the store's `put` log.
- A failed job answers 409 `{"status": "failed", "error": str, "attempts": int, "retry": bool}`
  on GET; a POST for a failed key with attempts < 3 re-enqueues it (202, or 409 with the old
  state); with attempts = 3 it answers 409 `retry: false` and enqueues nothing.
- Non-200 answers of the tensor routes carry `Cache-Control: no-store`.
- The built tensor declares `schema` 3 and validates against the contract of schema 3,
  `portfoliosight/engine/tensor.schema.json`, loaded by
  `portfoliosight.engine.tensor.load_schema(3)`.
"""

from __future__ import annotations

import dataclasses
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
import threading
import time
import types
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
        pytest.fail(f"A-PS-27 red: cannot import {module}: {type(exc).__name__}: {exc}")


TENSOR_SCHEMA = 3  # what the engine writes: `schema` of portfoliosight/engine/tensor.schema.json


def _assert_written_contract(tensor: dict, what: str) -> None:
    """A freshly built tensor declares schema 3 and validates against that shipped contract."""
    jsonschema = _need("jsonschema")
    contract = _need("portfoliosight.engine.tensor").load_schema(TENSOR_SCHEMA)
    assert (contract.get("properties") or {}).get("schema") == {"const": TENSOR_SCHEMA}, (
        f"the contract loaded for schema {TENSOR_SCHEMA} is not that schema's"
    )
    assert tensor.get("schema") == TENSOR_SCHEMA, (
        f"{what} declares schema {tensor.get('schema')!r}, not {TENSOR_SCHEMA}"
    )
    validator = jsonschema.Draft202012Validator(contract)
    errors = sorted(validator.iter_errors(tensor), key=lambda e: list(e.absolute_path))
    assert not errors, f"{what} fails the schema {TENSOR_SCHEMA} contract: " + "; ".join(
        f"{'/'.join(map(str, e.absolute_path))}: {e.message[:120]}" for e in errors[:5]
    )


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
        pytest.fail("A-PS-27 red: portfoliosight.engine.ENGINE_VERSION (str) is missing")
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
        pytest.fail("A-PS-27 red: portfoliosight.data.store.LocalStore is missing")
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
        pytest.fail("A-PS-27 red: portfoliosight.api.app.create_app is missing")
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


SYMBOLS = ["VTI", "BND", "VNQ"]
_HASH_RE = re.compile(r"[0-9a-f]{16}")
BUILD_DEADLINE_S = 300.0


def _hashes_in(args, kwargs) -> set:
    values = list(args) + list(kwargs.values())
    for v in list(values):
        if isinstance(v, dict):
            values.extend(v.values())
        elif isinstance(v, (list, tuple)):
            values.extend(v)
        elif dataclasses.is_dataclass(v) or isinstance(v, types.SimpleNamespace):
            values.extend(vars(v).values())
    return {v for v in values if isinstance(v, str) and _HASH_RE.fullmatch(v)}


class _WrappedBuild:
    """Pass-through around the real builder: counts calls per hash, can hold or fail one hash."""

    def __init__(self, real, *, hold: str, fail: str):
        self.real, self.hold, self.fail = real, hold, fail
        self.calls: list[tuple] = []  # (hashes, args, kwargs)
        self.entered = threading.Event()
        self.release = threading.Event()

    def count(self, h: str) -> int:
        return sum(1 for hashes, _, _ in self.calls if h in hashes)

    def __call__(self, *args, **kwargs):
        hashes = _hashes_in(args, kwargs)
        self.calls.append((hashes, args, kwargs))
        if self.fail in hashes:
            raise RuntimeError("gate fault: injected build failure")
        if self.hold in hashes:
            self.entered.set()
            self.release.wait(timeout=120)
        return self.real(*args, **kwargs)


def _poll(client, path, want, deadline_s, *, attempts=None):
    """GET `path` until the status is `want` (and, if given, body.attempts == attempts)."""
    end = time.monotonic() + deadline_s
    seen = []
    while time.monotonic() < end:
        resp = client.get(path, headers=_hdr())
        seen.append(resp.status_code)
        if resp.status_code == want and (
            attempts is None or resp.json().get("attempts") == attempts
        ):
            return resp, seen
        if resp.status_code not in (200, 202, 409):
            pytest.fail(f"A-PS-27 red: GET {path} -> {resp.status_code} while waiting for {want}")
        time.sleep(0.2)
    pytest.fail(
        f"A-PS-27 red: GET {path} never reached {want} in {deadline_s:.0f} s; saw {seen[-5:]}"
    )


def _wait(predicate, deadline_s, what):
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.05)
    pytest.fail(f"A-PS-27 red: timed out after {deadline_s:.0f} s waiting for {what}")


if _OUTER:

    def test_a_ps_27_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-27 is red inside the project virtualenv (output above)"

else:

    def test_build_dedupe_retry_and_immutability(tmp_path, monkeypatch):
        version = _engine_version()
        g = f"{D_G.isoformat()}-{version}"
        store = _new_store(tmp_path)
        _seed_catalog(store, SYMBOLS, _sessions(D_G, 400))
        _seed_generation(store, g, D_G, version)
        real = getattr(_need("portfoliosight.api.queue"), "build_job", None)
        assert real is not None, "A-PS-27 red: portfoliosight.api.queue.build_job is missing"

        funds = _menu(SYMBOLS)
        bad_funds = _menu(["VTI", "BND"])
        h, bad = _uhash(funds), _uhash(bad_funds)
        assert h != bad
        key, bad_key = f"tensors/{g}/{h}/1y.json", f"tensors/{g}/{bad}/1y.json"
        path, bad_path = f"/v1/tensors/{g}/{h}/1y", f"/v1/tensors/{g}/{bad}/1y"
        public_url = f"/api/tensors/{g}/{h}/1y"
        wrapped = _WrappedBuild(real, hold=h, fail=bad)
        app = _make_app(store, monkeypatch, tmp_path, build_fn=wrapped, start_worker=True)
        texts = []

        def post(body_funds):
            resp = client.post(
                "/v1/tensors", json={"funds": body_funds, "lookback": "1y"}, headers=_hdr()
            )
            texts.append(resp.text)
            return resp

        try:
            with _client(app) as client:
                # (5) never requested in G
                never = client.get(f"/v1/tensors/{g}/0123456789abcdef/1y", headers=_hdr())
                assert never.status_code == 404 and _error_code(never) == "unknown_tensor"
                assert client.get(path, headers=_hdr()).status_code == 404

                # (1) first POST: queued, with a position
                first = post(funds)
                assert first.status_code == 202, f"first POST -> {first.status_code}, expected 202"
                body = first.json()
                assert body["status"] in ("queued", "building"), body["status"]
                assert isinstance(body["position"], int) and not isinstance(body["position"], bool)
                assert body["generation"] == g
                assert re.fullmatch(r"[0-9a-f]{16}", body["hash"]) and body["hash"] == h
                assert _cache_tokens(first) == {"no-store"}

                # (2) while it builds: 202 on GET, a second POST joins the same job
                _wait(wrapped.entered.is_set, 30, "the worker to call build_fn for the new key")
                pending = client.get(path, headers=_hdr())
                texts.append(pending.text)
                assert pending.status_code == 202, f"GET while building -> {pending.status_code}"
                assert pending.json()["status"] in ("queued", "building")
                assert _cache_tokens(pending) == {"no-store"}
                assert "etag" not in pending.headers
                health = client.get("/v1/health", headers=_hdr()).json()["queue"]
                assert health["building"] is True and health["depth"] in (0, 1), f"queue: {health}"
                second = post(funds)
                assert second.status_code == 202 and second.json()["hash"] == h
                assert second.json()["status"] in ("queued", "building")
                health = client.get("/v1/health", headers=_hdr()).json()["queue"]
                assert health["depth"] in (0, 1), f"a duplicate POST grew the queue: {health}"
                assert wrapped.count(h) == 1, "two jobs for one key"
                assert not store.exists(key)

                wrapped.release.set()
                ready, seen = _poll(client, path, 200, BUILD_DEADLINE_S)
                assert set(seen) <= {202, 200} and seen[-1] == 200
                first_bytes = ready.content
                tensor = ready.json()
                _assert_written_contract(tensor, "the custom tensor")
                assert tensor["generation"] == g
                assert tensor["asof"] == D_G.isoformat() and tensor["lookback"]["id"] == "1y"
                assert tensor["universe"]["hash"] == h
                assert {f["id"] for f in tensor["universe"]["funds"]} == set(SYMBOLS)
                assert len(tensor["frontier"]["x"]) == 48 and len(tensor["mu_s"]) == 3
                assert ready.headers.get("etag"), "the 200 carries no ETag"
                assert _cache_tokens(ready) == {"public", "max-age=86400", "immutable"}
                assert "no-store" not in ready.headers["cache-control"]
                assert wrapped.count(h) == 1, "two jobs for one key"

                third = post(funds)
                assert third.status_code == 200, (
                    f"POST after ready -> {third.status_code}, expected 200"
                )
                done = third.json()
                assert done["status"] == "ready" and done["hash"] == h and done["generation"] == g
                assert done["url"] == public_url and re.match(r"^/api/tensors/", done["url"])
                assert not done["url"].startswith("/v1/")
                assert wrapped.count(h) == 1, "a POST for a ready key started another job"

                # (4) exactly one write; a forced second build writes nothing
                assert len(store.puts(key)) == 1, f"{len(store.puts(key))} writes of the ready key"
                stored = store.get(key)
                _, args, kwargs = next(c for c in wrapped.calls if h in c[0])
                try:
                    real(*args, **kwargs)  # the same job again, straight into the real builder
                except Exception:
                    pass  # refusing loudly is fine; writing is not
                assert len(store.puts(key)) == 1, "a second build of an existing key wrote it again"
                assert store.get(key) == stored, "the stored tensor changed"
                again = client.get(path, headers=_hdr())
                assert again.status_code == 200 and again.content == first_bytes, (
                    "the served tensor is not byte-identical to the first one"
                )
                assert again.headers.get("etag") == ready.headers.get("etag")

                # (3) the faulty key: three attempts, then no more
                for attempt in (1, 2, 3):
                    resp = post(bad_funds)
                    assert resp.status_code in (202, 409), (
                        f"POST {attempt} of the failing key -> {resp.status_code}"
                    )
                    assert resp.status_code != 200
                    failed, _ = _poll(client, bad_path, 409, 60, attempts=attempt)
                    texts.append(failed.text)
                    state = failed.json()
                    assert state["status"] == "failed" and state["attempts"] == attempt
                    assert state["retry"] is (attempt < 3), (
                        f"attempt {attempt}: retry = {state['retry']}"
                    )
                    assert isinstance(state["error"], str)
                    assert _cache_tokens(failed) == {"no-store"}
                    assert wrapped.count(bad) == attempt, (
                        f"{wrapped.count(bad)} build_fn calls for the failing key after attempt {attempt}"
                    )
                for _ in range(2):
                    fourth = post(bad_funds)
                    assert fourth.status_code == 409, (
                        f"POST after three failures -> {fourth.status_code}"
                    )
                    assert fourth.status_code != 202
                    final = fourth.json()
                    assert final["status"] == "failed" and final["attempts"] == 3
                    assert final["retry"] is False
                time.sleep(1.0)
                assert wrapped.count(bad) == 3, "a fourth attempt was enqueued"
                idle = client.get("/v1/health", headers=_hdr()).json()["queue"]
                assert idle["depth"] == 0 and idle["building"] is False, f"queue not idle: {idle}"
                assert client.get(bad_path, headers=_hdr()).json()["attempts"] == 3
                assert store.puts(bad_key) == [] and not store.exists(bad_key)

                # nothing else was written, and the ready key is still the first write
                assert [c[1] for c in store.puts() if c[1].startswith("tensors/")] == [key]
                assert len(wrapped.calls) == 4
        finally:
            wrapped.release.set()
        assert texts and not [t for t in texts if '"/v1/' in t or "/v1/tensors" in t], (
            "a response carries a /v1/ URL"
        )
