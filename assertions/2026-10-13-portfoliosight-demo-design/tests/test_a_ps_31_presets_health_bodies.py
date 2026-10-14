"""A-PS-31 — presets and health bodies match data/presets.json and the holdings CSV.

Claim: GET /v1/presets returns the two presets of data/presets.json with the spec §6 shape, where
guide2017.allocation is Qty x Price per symbol from data/holdings/holdings_guide2017_step2.csv in
"$" with 18 non-zero of 23 entries and tsp.allocation is null; GET /v1/health returns the §6 fields.

Pinned interface (the product must provide exactly this):
- `portfoliosight.api.app.create_app(*, store, clock, build_fn, start_worker)` (shared pin);
  `PS_GATE_SECRET` from the environment; requests carry `x-ps-gate` and `CF-Connecting-IP`.
- The published generation is produced here by the product's own nightly,
  `portfoliosight.jobs.nightly.run(*, store, now, providers, build_fn=None)` (pinned in A-PS-30),
  over 28 synthetic canonical records, with a fast `build_fn` that writes placeholder tensors
  (this assertion reads presets and health only). `now` = 2026-10-08 02:00 America/Los_Angeles,
  so G = "2026-10-07-" + `portfoliosight.engine.ENGINE_VERSION`.
- `data/presets.json`: JSON whose preset objects (a top-level list, or a list under `presets`)
  carry `id` and `name`.
- `GET /v1/presets` serves `meta/{G}/presets.json` of the current generation; `nightly` in
  `GET /v1/health` is the content of `meta/status.json`.
- A preset's `hash` is the spec §6 universe hash of its funds with every cap `null`.
"""

from __future__ import annotations

import csv
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
import types
import zlib
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
        pytest.fail(f"A-PS-31 red: cannot import {module}: {type(exc).__name__}: {exc}")


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
        pytest.fail("A-PS-31 red: portfoliosight.engine.ENGINE_VERSION (str) is missing")
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
        pytest.fail("A-PS-31 red: portfoliosight.data.store.LocalStore is missing")
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
        pytest.fail("A-PS-31 red: portfoliosight.api.app.create_app is missing")
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


# ---- nightly harness --------------------------------------------------------------------------

NOW = datetime(2026, 10, 8, 2, 0, tzinfo=ZoneInfo("America/Los_Angeles"))  # fixes D_G = 2026-10-07
_HASH_RE = re.compile(r"[0-9a-f]{16}")


class _Interrupt(BaseException):
    """Stands in for the process dying mid-run (not an Exception, so a per-tensor retry or
    `except Exception` in the product cannot swallow it)."""


def _guide_ids() -> list[str]:
    assert HOLDINGS_CSV.exists(), f"A-PS-31 red: {HOLDINGS_CSV.relative_to(ROOT)} is missing"
    with HOLDINGS_CSV.open(newline="") as fh:
        ids = [row["Symbol"].strip() for row in csv.DictReader(fh)]
    assert len(ids) == 23 and len(set(ids)) == 23, "the Step 2 CSV must list 23 distinct symbols"
    return ids


def _preset_hashes() -> dict:
    """Independent universe hashes of the two presets (requested policy: all defaults)."""
    return {"guide2017": _uhash(_menu(_guide_ids())), "tsp": _uhash(_menu(TSP_CORE))}


def _expected_keys(g: str) -> set:
    return {f"tensors/{g}/{h}/{lb}.json" for h in _preset_hashes().values() for lb in LOOKBACKS}


def _key_of(args, kwargs):
    """(universe hash, lookback) of one build_fn call, found among its argument values.

    Looks at the positional and keyword values, and one level into dicts, sequences and plain
    objects, so the product is free to choose the callable's signature.
    """
    values = list(args) + list(kwargs.values())
    for v in list(values):
        if isinstance(v, dict):
            values.extend(v.values())
        elif isinstance(v, (list, tuple)):
            values.extend(v)
        elif dataclasses.is_dataclass(v) or isinstance(v, types.SimpleNamespace):
            values.extend(vars(v).values())
    strings = [v for v in values if isinstance(v, str)]
    hashes = [s for s in strings if _HASH_RE.fullmatch(s)]
    lookbacks = [s for s in strings if s in LOOKBACKS]
    return (hashes[0], lookbacks[0]) if hashes and lookbacks else None


class _Builder:
    """A `build_fn` for the nightly.

    Fast path: writes a minimal placeholder tensor to `tensors/{G}/{hash}/{lookback}.json`
    (never over an existing key). Keys in `real_keys` go to the real builder instead. After
    `abort_after` calls, every further call raises `_Interrupt`.
    """

    def __init__(self, store, g, asof, *, abort_after=None, real=None, real_keys=()):
        self.store, self.g, self.asof = store, g, asof
        self.abort_after, self.real, self.real_keys = abort_after, real, set(real_keys)
        self.calls: list = []
        self.unreadable: list[str] = []
        self.aborted = False

    def __call__(self, *args, **kwargs):
        key = _key_of(args, kwargs)
        if key is None:
            self.unreadable.append(
                f"args={[type(a).__name__ for a in args]} kwargs={sorted(kwargs)}"
            )
            raise RuntimeError("gate build_fn: no universe hash / lookback among the arguments")
        if self.abort_after is not None and len(self.calls) >= self.abort_after:
            self.aborted = True
            raise _Interrupt()
        self.calls.append(key)
        if key in self.real_keys:
            return self.real(*args, **kwargs)
        skey = f"tensors/{self.g}/{key[0]}/{key[1]}.json"
        if not self.store.exists(skey):
            doc = {"schema": 2, "generation": self.g, "asof": self.asof.isoformat()}
            doc |= {
                "universe": {"hash": key[0]},
                "lookback": {"id": key[1]},
                "gate_placeholder": True,
            }
            self.store.put(skey, json.dumps(doc).encode())
        return None


class _FakeProvider:
    """A PriceProvider (spec §5.1) that replays the seeded records, or fails on demand."""

    def __init__(self, name, frames, *, fail=False):
        self.name, self._frames, self._fail = name, frames, fail
        self.calls: list[str] = []

    def fetch_daily(self, symbol, start, end=None):
        pd = _need("pandas")
        self.calls.append(symbol)
        if self._fail:
            raise RuntimeError(f"gate fault: {self.name} fetch failed (HTTP 503)")
        cols = ["close", "adj_close", "div_cash", "split_factor"]
        if symbol not in self._frames:
            return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="date"), dtype=float)
        df = self._frames[symbol]
        out = pd.DataFrame({"close": df["close"].to_numpy()}, index=pd.DatetimeIndex(df["date"]))
        out["adj_close"] = out["close"]
        out["div_cash"] = 0.0
        out["split_factor"] = 1.0
        out.index.name = "date"
        out = out[out.index >= pd.Timestamp(start)]
        return out if end is None else out[out.index <= pd.Timestamp(end)]

    def fetch_meta(self, symbol):
        self.calls.append(symbol)
        if self._fail:
            raise RuntimeError(f"gate fault: {self.name} fetch failed (HTTP 503)")
        if symbol not in self._frames:
            return None
        df = self._frames[symbol]
        fields = {"name": f"{symbol} gate fund", "kind": "tsp" if self.name == "tsp" else "etf"}
        fields |= {"first_date": df["date"].iloc[0].date(), "last_date": df["date"].iloc[-1].date()}
        try:
            meta_cls = importlib.import_module("portfoliosight.data.providers.base").SymbolMeta
            return meta_cls(**fields)
        except Exception:
            return types.SimpleNamespace(**fields)


def _providers(frames, *, tsp_fails=False) -> dict:
    tiingo = {s: f for s, f in frames.items() if not s.startswith("TSP-")}
    tsp = {s: f for s, f in frames.items() if s.startswith("TSP-")}
    return {
        "tiingo": _FakeProvider("tiingo", tiingo),
        "tsp": _FakeProvider("tsp", tsp, fail=tsp_fails),
    }


def _nightly_env(store, monkeypatch, tmp_path):
    """Scratch cache, a dummy provider key, and a provider budget that never makes the job sleep."""
    monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PS_CACHE_MAX_MB", "300")
    monkeypatch.setenv("TIINGO_API_KEY", "gate-not-a-real-key")
    monkeypatch.setenv("PS_PROVIDER_REQ_PER_HOUR", "9000")
    monkeypatch.setenv("PS_PROVIDER_REQ_PER_DAY", "90000")
    monkeypatch.setenv("PS_PROVIDER_SYMBOLS_PER_MONTH", "100000")
    limits = {"provider": "tiingo", "tier": "power", "req_per_hour": 9000, "req_per_day": 90000}
    limits |= {
        "unique_symbols_per_month": 100000,
        "measured_on": "2026-10-07",
        "method": "documented",
    }
    store.put("meta/provider_limits.json", json.dumps(limits).encode())


def _run_nightly(store, providers, build_fn, *, interrupted=False):
    """Call the pinned nightly entry point; an `_Interrupt` is the only tolerated exception."""
    run = getattr(_need("portfoliosight.jobs.nightly"), "run", None)
    if run is None:
        pytest.fail("A-PS-31 red: portfoliosight.jobs.nightly.run is missing")
    try:
        run(store=store, now=NOW, providers=providers, build_fn=build_fn)
    except _Interrupt:
        if not interrupted:
            raise
    except Exception as exc:
        pytest.fail(f"A-PS-31 red: the nightly raised {type(exc).__name__}: {exc}")


def _generation_id() -> str:
    return f"{D_G.isoformat()}-{_engine_version()}"


N_ROWS = 2700
PRESETS_JSON = ROOT / "data" / "presets.json"


def _csv_allocation() -> dict:
    """Qty x Price per symbol, read here from the committed CSV."""
    with HOLDINGS_CSV.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {r["Symbol"].strip(): round(float(r["Qty"]) * float(r["Price"]), 2) for r in rows}


def _published_app(tmp_path, monkeypatch):
    g = _generation_id()
    store = _new_store(tmp_path)
    _nightly_env(store, monkeypatch, tmp_path)
    frames = _seed_catalog(store, _guide_ids() + TSP_CORE, _sessions(D_G, N_ROWS))
    builder = _Builder(store, g, D_G)
    _run_nightly(store, _providers(frames), builder)
    assert not builder.unreadable, (
        f"build_fn arguments carry no hash/lookback: {builder.unreadable[:2]}"
    )
    assert json.loads(store.get("meta/current.json"))["generation"] == g, (
        "the nightly did not publish G"
    )
    assert set(store.list(f"tensors/{g}/")) == _expected_keys(g)
    app = _make_app(store, monkeypatch, tmp_path, start_worker=False)
    return store, g, app


if _OUTER:

    def test_a_ps_31_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-31 is red inside the project virtualenv (output above)"

else:

    def test_presets_body(tmp_path, monkeypatch):
        store, g, app = _published_app(tmp_path, monkeypatch)
        alloc = _csv_allocation()
        guide = _guide_ids()
        assert len(alloc) == 23 and sum(1 for v in alloc.values() if v != 0) == 18
        assert PRESETS_JSON.exists(), "A-PS-31 red: data/presets.json is missing"
        declared = json.loads(PRESETS_JSON.read_text())
        declared = declared["presets"] if isinstance(declared, dict) else declared
        declared = {p["id"]: p["name"] for p in declared}
        with _client(app) as client:
            resp = client.get("/v1/presets", headers=_hdr())
        assert resp.status_code == 200, f"GET /v1/presets -> {resp.status_code}"
        assert _cache_tokens(resp) == {"public", "max-age=300"}, resp.headers.get("cache-control")
        body = resp.json()
        assert body == json.loads(store.get(f"meta/{g}/presets.json")), (
            "body is not meta/{G}/presets.json"
        )
        assert body["generation"] == g and body["asof"] == D_G.isoformat()
        presets = body["presets"]
        assert [p["id"] for p in presets] == ["guide2017", "tsp"]
        assert {p["id"]: p["name"] for p in presets} == declared, (
            "presets differ from data/presets.json"
        )
        assert not [p["id"] for p in presets if p["id"] not in declared]
        hashes = _preset_hashes()

        first = presets[0]
        assert first["name"] == "Example Portfolio"
        assert len(first["funds"]) == 23 and {f["id"] for f in first["funds"]} == set(guide)
        assert all(isinstance(f["name"], str) and f["name"] for f in first["funds"])
        assert first["allocation_unit"] == "$"
        assert set(first["allocation"]) == set(guide), "allocation must cover the 23 symbols"
        for sym in guide:
            got = first["allocation"][sym]
            assert not isinstance(got, bool) and abs(got - alloc[sym]) < 1e-9, (
                f"allocation[{sym}] = {got}, the CSV gives {alloc[sym]}"
            )
        assert sum(1 for v in first["allocation"].values() if v != 0) == 18
        assert sum(1 for v in first["allocation"].values() if v == 0) == 5

        second = presets[1]
        assert second["name"] == "TSP (G, F, C, S, I)"
        assert [f["id"] for f in second["funds"]] == TSP_CORE
        assert second["allocation"] is None, "the TSP preset must not carry an allocation"
        assert second["allocation_unit"] is None

        for preset in presets:
            h = preset["hash"]
            assert h == hashes[preset["id"]], f"{preset['id']}: hash {h} != {hashes[preset['id']]}"
            assert set(preset["lookbacks"]) == set(LOOKBACKS)
            for lb in LOOKBACKS:
                want = {"status": "ready", "url": f"/api/tensors/{g}/{h}/{lb}"}
                assert preset["lookbacks"][lb] == want, (
                    f"{preset['id']}/{lb}: {preset['lookbacks'][lb]}"
                )
                assert not preset["lookbacks"][lb]["url"].startswith("/v1/")
                assert store.exists(f"tensors/{g}/{h}/{lb}.json")
        assert "/v1/" not in resp.text, "a /v1/ path leaked into the presets body"

    def test_health_body(tmp_path, monkeypatch):
        store, g, app = _published_app(tmp_path, monkeypatch)
        with _client(app) as client:
            resp = client.get("/v1/health", headers=_hdr())
        assert resp.status_code == 200, f"GET /v1/health -> {resp.status_code}"
        assert _cache_tokens(resp) == {"no-store"}, resp.headers.get("cache-control")
        assert "public" not in resp.headers.get("cache-control", "")
        body = resp.json()
        assert body["status"] == "ok"
        assert isinstance(body["version"], str) and body["version"]
        assert body["generation"] == g
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", body["asof"]) and body["asof"] == D_G.isoformat()
        behind = body["asof_trading_days_behind"]
        assert isinstance(behind, int) and not isinstance(behind, bool) and behind >= 0
        assert isinstance(body["queue"]["depth"], int) and body["queue"]["depth"] == 0
        assert body["queue"]["building"] is False
        status = json.loads(store.get("meta/status.json"))
        assert isinstance(status, dict) and status, "meta/status.json is empty after a nightly run"
        assert body["nightly"] == status, "health.nightly is not the content of meta/status.json"
        assert body["nightly"] is not None
