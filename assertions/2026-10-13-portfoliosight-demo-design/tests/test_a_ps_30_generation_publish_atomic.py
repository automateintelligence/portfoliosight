"""A-PS-30 — a generation is published only when complete, and never half-visible.

Claim: the nightly writes meta/{G}/generation.json once, builds each missing preset tensor with
D_G passed in, switches meta/current.json only after all 12 keys exist, resumes an interrupted run
without rewriting anything under meta/{G}/, skips to the post-publication steps when current.json
already points at G, deletes generations older than the previous one, and marks TSP stale (not
failed) when the tsp.gov fetch breaks.

Pinned interface (the product must provide exactly this):
- `portfoliosight.jobs.nightly.run(*, store, now, providers, build_fn=None)`: one nightly run
  (spec §5.4 steps 1-7) against `store`. `now` is a timezone-aware datetime standing for the run's
  start; D_G and G derive from it (here 2026-10-08 02:00 America/Los_Angeles, so D_G = 2026-10-07
  and G = "2026-10-07-" + `portfoliosight.engine.ENGINE_VERSION`). `providers` is
  `{"tiingo": <PriceProvider>, "tsp": <PriceProvider>}` (spec §5.1 Protocol; TSP-* symbols go to
  "tsp", everything else to "tiingo"); the run uses these and never the network. A provider that
  returns an empty frame / `None` meta means "no data"; one that raises is a failed fetch.
- `build_fn` is called once per preset tensor that is missing, and it is what writes
  `tensors/{G}/{hash}/{lookback}.json` to the store; `None` means the default,
  `portfoliosight.api.queue.build_job` (the same callable the API worker uses). The 16-hex
  universe hash and the lookback id must be among the call's argument values (positional or
  keyword, or one level inside a dict / tuple / dataclass argument); nothing else about its
  signature is assumed. An exception that is not an `Exception` subclass (a dying process)
  must propagate out of `run`, or at least stop the run from publishing.
- Preset tensor keys are `tensors/{G}/{universe hash of the preset's funds, all defaults}/{lb}.json`
  for the 23 Step 2 symbols and for TSP-G/F/C/S/I, six lookbacks each.
- Provider budget: the run honours `meta/provider_limits.json` (spec §5.2) and the
  `PS_PROVIDER_*` variables, so with the large limits set here it never sleeps. Scratch files go
  under `PS_CACHE_DIR`. `meta/status.json` carries an `errors` entry (spec §5.3).
- Store, manifest, canonical record, `meta/current.json`, `meta/{G}/generation.json`: shared pins.
- A real preset tensor declares `schema` 3 and validates against the contract of schema 3,
  `portfoliosight/engine/tensor.schema.json`, loaded by
  `portfoliosight.engine.tensor.load_schema(3)`.

Which leg uses which builder:
- interrupt, resume, skip, prune, first run, TSP failure: a fast fake `build_fn` (placeholder
  tensors); these legs are about orchestration only.
- asof / "no row after D_G" leg: real builds. Store B (every record carries an extra, fully
  adjusted row dated D_G + 1 with a 3x price) runs with `build_fn=None`, all 12 tensors real.
  Store A (no extra row) builds two keys for real (guide2017 1y, tsp ew) and the rest fake; the
  two must equal B's after dropping build telemetry and the manifest's per-fund dates.
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
        pytest.fail(f"A-PS-30 red: cannot import {module}: {type(exc).__name__}: {exc}")


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
        pytest.fail("A-PS-30 red: portfoliosight.engine.ENGINE_VERSION (str) is missing")
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
        pytest.fail("A-PS-30 red: portfoliosight.data.store.LocalStore is missing")
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


# ---- nightly harness --------------------------------------------------------------------------

NOW = datetime(2026, 10, 8, 2, 0, tzinfo=ZoneInfo("America/Los_Angeles"))  # fixes D_G = 2026-10-07
_HASH_RE = re.compile(r"[0-9a-f]{16}")


class _Interrupt(BaseException):
    """Stands in for the process dying mid-run (not an Exception, so a per-tensor retry or
    `except Exception` in the product cannot swallow it)."""


def _guide_ids() -> list[str]:
    assert HOLDINGS_CSV.exists(), f"A-PS-30 red: {HOLDINGS_CSV.relative_to(ROOT)} is missing"
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
        pytest.fail("A-PS-30 red: portfoliosight.jobs.nightly.run is missing")
    try:
        run(store=store, now=NOW, providers=providers, build_fn=build_fn)
    except _Interrupt:
        if not interrupted:
            raise
    except Exception as exc:
        pytest.fail(f"A-PS-30 red: the nightly raised {type(exc).__name__}: {exc}")


def _generation_id() -> str:
    return f"{D_G.isoformat()}-{_engine_version()}"


N_ROWS = 2700  # more than the 10y window (2520 sessions), so all six lookbacks can build
PREV_SESSIONS = 3


def _put_index(store, key) -> list[int]:
    return [i for i, c in enumerate(store.calls) if c[0] == "put" and c[1] == key]


def _old_generation(store, g, asof, version, *, current):
    _seed_generation(store, g, asof, version, current=current)
    store.put(f"tensors/{g}/{'ab' * 8}/5y.json", json.dumps({"generation": g}).encode())
    store.put(f"tensors/{g}/{'cd' * 8}/1y.json", json.dumps({"generation": g}).encode())


def _scrub(tensor: dict) -> dict:
    out = json.loads(json.dumps(tensor))
    out.pop("built_at", None)
    out.pop("build_seconds", None)
    for fund in out["universe"]["funds"] + out["universe"].get("excluded", []):
        fund.pop("fetched_at", None)
        fund.pop("adjusted_through", None)
    return out


if _OUTER:

    def test_a_ps_30_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-30 is red inside the project virtualenv (output above)"

else:

    def test_interrupt_resume_skip_and_prune(tmp_path, monkeypatch):
        version = _engine_version()
        g = _generation_id()
        store = _new_store(tmp_path)
        _nightly_env(store, monkeypatch, tmp_path)
        dates = _sessions(D_G, N_ROWS)
        frames = _seed_catalog(store, _guide_ids() + TSP_CORE, dates)
        d_old, d_prev = dates[-3].date(), dates[-2].date()
        g_old, g_prev = f"{d_old.isoformat()}-{version}", f"{d_prev.isoformat()}-{version}"
        _old_generation(store, g_old, d_old, version, current=False)
        _old_generation(store, g_prev, d_prev, version, current=True)
        prev_keys = {
            k: store.get(k)
            for k in store.list(f"meta/{g_prev}/") + store.list(f"tensors/{g_prev}/")
        }
        assert len(prev_keys) == 4 and len(store.list(f"tensors/{g_old}/")) == 2
        pointer_before = store.get("meta/current.json")
        expected = _expected_keys(g)
        assert len(expected) == 12
        start = len(store.calls)

        # (1) interrupted after the 5th preset tensor
        first = _Builder(store, g, D_G, abort_after=5)
        _run_nightly(store, _providers(frames), first, interrupted=True)
        assert not first.unreadable, (
            f"build_fn arguments carry no hash/lookback: {first.unreadable[:2]}"
        )
        assert first.aborted and len(first.calls) == 5, (
            f"the nightly made {len(first.calls)} build_fn calls before the injected interrupt, expected 5"
        )
        built = set(store.list(f"tensors/{g}/"))
        assert len(built) == 5 and built <= expected, f"after the interrupt: {sorted(built)}"
        assert store.exists(f"meta/{g}/generation.json"), (
            "generation.json was not written before building"
        )
        gen_bytes = store.get(f"meta/{g}/generation.json")
        gen = json.loads(gen_bytes)
        assert gen["generation"] == g and gen["asof"] == D_G.isoformat()
        assert gen["engine_version"] == version
        assert not store.exists(f"meta/{g}/presets.json"), (
            "presets.json exists after 5 of 12 tensors"
        )
        assert store.get("meta/current.json") == pointer_before, (
            "current.json changed in a half-built run"
        )
        assert json.loads(store.get("meta/current.json"))["generation"] != g

        # (2) rerun: 7 more, presets.json once, pointer switched last
        second = _Builder(store, g, D_G)
        _run_nightly(store, _providers(frames), second)
        assert len(second.calls) == 7, (
            f"the rerun built {len(second.calls)} tensors, expected the 7 missing"
        )
        assert not (set(second.calls) & set(first.calls)), (
            "the rerun rebuilt a tensor that already existed"
        )
        assert set(store.list(f"tensors/{g}/")) == expected
        assert store.exists(f"meta/{g}/presets.json")
        assert json.loads(store.get("meta/current.json"))["generation"] == g
        assert len(_put_index(store, f"meta/{g}/generation.json")) == 1, "generation.json rewritten"
        assert len(_put_index(store, f"meta/{g}/presets.json")) == 1, (
            "presets.json not written exactly once"
        )
        assert store.get(f"meta/{g}/generation.json") == gen_bytes
        for key in expected:
            assert len(_put_index(store, key)) == 1, f"{key} was written more than once"
        switches = [
            i
            for i in _put_index(store, "meta/current.json")
            if i >= start and json.loads(store.calls[i][2]).get("generation") == g
        ]
        assert switches, "no put of meta/current.json pointing at the new generation"
        last_needed = max(max(_put_index(store, k)) for k in expected | {f"meta/{g}/presets.json"})
        assert min(switches) > last_needed, (
            "current.json was switched before the 12th tensor / presets.json"
        )
        removed = [c[1] for c in store.calls if c[0] == "delete"]
        assert not [k for k in removed if k.startswith((f"meta/{g}/", f"tensors/{g}/"))]
        presets = json.loads(store.get(f"meta/{g}/presets.json"))
        assert presets["generation"] == g and len(presets["presets"]) == 2

        # (5) prune: the oldest generation is gone, the previous one is intact
        assert store.list(f"meta/{g_old}/") == [] and store.list(f"tensors/{g_old}/") == [], (
            "the generation older than the previous one was not deleted"
        )
        for key, data in prev_keys.items():
            assert store.exists(key) and store.get(key) == data, f"previous generation lost {key}"
        status = json.loads(store.get("meta/status.json"))
        assert isinstance(status, dict) and D_G.isoformat() in json.dumps(status)

        # (4) third run: already published, zero builds, nothing under G touched
        mark = len(store.calls)
        third = _Builder(store, g, D_G)
        _run_nightly(store, _providers(frames), third)
        assert third.calls == [] and not third.unreadable, (
            f"a published generation was rebuilt: {third.calls}"
        )
        touched = [c[1] for c in store.calls[mark:] if c[0] in ("put", "delete")]
        assert not [k for k in touched if k.startswith((f"meta/{g}/", f"tensors/{g}/"))], (
            "a run on a published generation rewrote keys of that generation"
        )
        assert json.loads(store.get("meta/current.json"))["generation"] == g
        assert set(store.list(f"tensors/{g}/")) == expected
        for key, data in prev_keys.items():
            assert store.exists(key) and store.get(key) == data, (
                f"a run on a published generation deleted the previous generation's {key}"
            )

    def test_first_run_interrupted_leaves_no_pointer(tmp_path, monkeypatch):
        g = _generation_id()
        store = _new_store(tmp_path)
        _nightly_env(store, monkeypatch, tmp_path)
        frames = _seed_catalog(store, _guide_ids() + TSP_CORE, _sessions(D_G, N_ROWS))
        first = _Builder(store, g, D_G, abort_after=5)
        _run_nightly(store, _providers(frames), first, interrupted=True)
        assert first.aborted and len(first.calls) == 5 and not first.unreadable
        assert not store.exists("meta/current.json"), (
            "current.json exists after a half-built first run"
        )
        assert not store.exists(f"meta/{g}/presets.json")
        assert store.exists(f"meta/{g}/generation.json")
        assert len(store.list(f"tensors/{g}/")) == 5
        assert not _put_index(store, "meta/current.json")
        _run_nightly(store, _providers(frames), _Builder(store, g, D_G))
        assert json.loads(store.get("meta/current.json"))["generation"] == g
        assert set(store.list(f"tensors/{g}/")) == _expected_keys(g)
        assert len(_put_index(store, f"meta/{g}/generation.json")) == 1

    def test_tsp_fetch_failure_marks_stale_and_still_publishes(tmp_path, monkeypatch):
        g = _generation_id()
        store = _new_store(tmp_path)
        _nightly_env(store, monkeypatch, tmp_path)
        guide = _guide_ids()
        # TSP records stop one session before D_G, so the refresh has to call tsp.gov.
        frames = _seed_catalog(store, guide + TSP_CORE, _sessions(D_G, N_ROWS), short=TSP_CORE)
        providers = _providers(frames, tsp_fails=True)
        builder = _Builder(store, g, D_G)
        _run_nightly(store, providers, builder)  # must finish: a TSP failure is not a failed run
        assert providers["tsp"].calls, "the nightly never asked the TSP provider for anything"
        symbols = _manifest_symbols(store)
        for sym in TSP_CORE:
            assert symbols[sym]["status"] == "stale", (
                f"{sym} is {symbols[sym]['status']!r}, expected stale"
            )
            assert symbols[sym]["status"] not in ("failed", "unavailable", "ok")
        assert [symbols[s]["status"] for s in guide] == ["ok"] * 23, (
            "a TSP failure changed other symbols"
        )
        status = json.loads(store.get("meta/status.json"))
        assert status.get("errors"), "meta/status.json records no error after the TSP fetch failed"
        assert "tsp" in json.dumps(status["errors"]).lower(), "the recorded error does not name TSP"
        assert not builder.unreadable
        assert set(store.list(f"tensors/{g}/")) == _expected_keys(g)
        assert json.loads(store.get("meta/current.json"))["generation"] == g, (
            "current.json was not switched although all 12 keys exist"
        )

    def test_every_tensor_is_pinned_to_d_g_and_ignores_later_rows(tmp_path, monkeypatch):
        np = _need("numpy")
        pd = _need("pandas")
        g = _generation_id()
        ids = _guide_ids() + TSP_CORE
        dates = _sessions(D_G, N_ROWS)
        next_day = pd.Timestamp(D_G) + pd.Timedelta(days=1)  # Thursday 2026-10-08
        hashes = _preset_hashes()

        store_b = _new_store(tmp_path, "store_b")
        _nightly_env(store_b, monkeypatch, tmp_path)
        frames_b = _seed_catalog(store_b, ids, dates, extra_row=(next_day, 3.0))
        # The extra row is big enough to move the 1y sample mean if it leaked in.
        probe = frames_b["VTI"]["tr_index"].pct_change().to_numpy()
        assert abs(252 * np.mean(probe[-252:]) - 252 * np.mean(probe[-253:-1])) > 1.0
        assert (
            frames_b["VTI"]["date"].iloc[-1] == next_day
            and frames_b["VTI"]["date"].iloc[-2] == dates[-1]
        )
        _run_nightly(store_b, _providers(frames_b), None)  # default builder: 12 real tensors
        assert set(store_b.list(f"tensors/{g}/")) == _expected_keys(g)
        assert json.loads(store_b.get("meta/current.json"))["generation"] == g
        assert json.loads(store_b.get(f"meta/{g}/generation.json"))["asof"] == D_G.isoformat()
        close_on_dg = {s: float(f["close"].iloc[-2]) for s, f in frames_b.items()}
        tensors_b, funds_checked = {}, 0
        for preset, h in hashes.items():
            members = set(TSP_CORE if preset == "tsp" else _guide_ids())
            for lb in LOOKBACKS:
                t = json.loads(store_b.get(f"tensors/{g}/{h}/{lb}.json"))
                tensors_b[(h, lb)] = t
                assert t["asof"] == D_G.isoformat(), f"{preset}/{lb}: asof {t['asof']} != D_G"
                assert t["asof"] != next_day.date().isoformat()
                assert t["generation"] == g
                _assert_written_contract(t, f"{preset}/{lb}")
                assert t["universe"]["hash"] == h and t["lookback"]["id"] == lb
                assert t["lookback"]["end"] <= D_G.isoformat(), (
                    f"{preset}/{lb}: window ends after D_G"
                )
                assert len(t["universe"]["funds"]) >= 2
                for fund in t["universe"]["funds"]:
                    assert fund["id"] in members
                    want = close_on_dg[fund["id"]]
                    assert abs(fund["last_close"] - want) <= 1e-9 * want, (
                        f"{fund['id']}: last_close {fund['last_close']} is not the close on D_G"
                    )
                    funds_checked += 1
        assert len(tensors_b) == 12 and funds_checked >= 100, f"only {funds_checked} funds checked"

        store_a = _new_store(tmp_path, "store_a")
        _nightly_env(store_a, monkeypatch, tmp_path)
        frames_a = _seed_catalog(store_a, ids, dates)
        assert frames_a["VTI"]["date"].iloc[-1] == dates[-1]
        real = getattr(_need("portfoliosight.api.queue"), "build_job", None)
        assert real is not None, "A-PS-30 red: portfoliosight.api.queue.build_job is missing"
        real_keys = {(hashes["guide2017"], "1y"), (hashes["tsp"], "ew")}
        builder = _Builder(store_a, g, D_G, real=real, real_keys=real_keys)
        _run_nightly(store_a, _providers(frames_a), builder)
        assert not builder.unreadable and real_keys <= set(builder.calls)
        for h, lb in sorted(real_keys):
            t_a = json.loads(store_a.get(f"tensors/{g}/{h}/{lb}.json"))
            assert "gate_placeholder" not in t_a, "the real builder did not write this key"
            assert t_a["asof"] == D_G.isoformat()
            assert _scrub(t_a) == _scrub(tensors_b[(h, lb)]), (
                f"tensor {h}/{lb} differs when the records carry a row dated D_G + 1: "
                "a price row after D_G influenced the build"
            )
            assert t_a["mu_sample"] == tensors_b[(h, lb)]["mu_sample"]
