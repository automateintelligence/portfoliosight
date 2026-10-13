"""A-PS-28 — bad requests are refused with the specified codes and nothing is enqueued.

Claim: POST /v1/tensors returns 400 unknown_symbols listing every unknown id; 422 invalid_request
for duplicates, more than 30 funds, fewer than 2, a bad lookback, or a cap policy failing spec §4.4;
429 for the 6th POST from one IP within a minute and for the 61st /v1/* request within a minute;
503 busy when 20 jobs are queued; 413 (or 422) for a body over 16 KB; and in every refused case the
job table is unchanged.

Pinned interface (the product must provide exactly this):
- `portfoliosight.api.app.create_app(*, store, clock, build_fn, start_worker)` (shared pin).
  `start_worker=False` leaves accepted jobs queued. `clock()` returns epoch seconds and is the
  only time source of the limiter (a fake clock is advanced by 61 s to reopen a window).
- The limiter key is the `CF-Connecting-IP` request header.
- Errors use the envelope `{"error": {"code", "message", "details"}}`; `unknown_symbols` puts
  the ids in `error.details.symbols`; 429 is `rate_limited`; 503 is `busy`. A cap refusal names
  the offending fund id in the error (message or details); a refusal for the sum of the minimums
  or maximums contains the word "sum".
- "Job table unchanged" is observed from outside: `queue.depth` in `GET /v1/health`, no call to
  `build_fn`, no `tensors/` write, and `GET /v1/tensors/{G}/{hash}/{lookback}` of the refused key
  still answering 404 `unknown_tensor` (hash = spec §6 formula, computed here).
- A queued job answers 202 with `status: "queued"`, the spec §6 hash, and an int `position`
  that differs between jobs queued at the same time.
- The 16 KB limit counts request body bytes (16 * 1024); a valid body padded with JSON
  whitespace to 15 KB is served, the same body padded to 17 KB is refused.
"""

from __future__ import annotations

import hashlib
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
        pytest.fail(f"A-PS-28 red: cannot import {module}: {type(exc).__name__}: {exc}")


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
        pytest.fail("A-PS-28 red: portfoliosight.engine.ENGINE_VERSION (str) is missing")
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
        pytest.fail("A-PS-28 red: portfoliosight.data.store.LocalStore is missing")
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
        pytest.fail("A-PS-28 red: portfoliosight.api.app.create_app is missing")
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


KNOWN = (
    "VTI VOO SPY IVV SCHB ITOT SPTM VV SCHX IWB VUG VTV IWF IWD SCHG SCHV VO IJH MDY SCHM VOE VOT "
    "IWR VB IJR IWM SCHA VBR VBK VXF RSP QQQ"
).split()


class _Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self) -> float:
        return self.t


class _Rig:
    """An app over a 32-symbol catalog with the worker paused."""

    def __init__(self, tmp_path, monkeypatch):
        version = _engine_version()
        self.g = f"{D_G.isoformat()}-{version}"
        self.store = _new_store(tmp_path)
        _seed_catalog(self.store, KNOWN, _sessions(D_G, 300))
        _seed_generation(self.store, self.g, D_G, version)
        self.clock = _Clock()
        self.built: list = []
        self.app = _make_app(
            self.store,
            monkeypatch,
            tmp_path,
            clock=self.clock,
            start_worker=False,
            build_fn=lambda *a, **k: self.built.append((a, k)),
        )

    def post(self, client, funds, lookback="5y", ip=None):
        body = {"funds": funds, "lookback": lookback}
        return client.post(
            "/v1/tensors", json=body, headers=_hdr(**{"CF-Connecting-IP": ip or _ip()})
        )

    def unknown(self, client, funds, lookback="5y") -> bool:
        resp = client.get(f"/v1/tensors/{self.g}/{_uhash(funds)}/{lookback}", headers=_hdr())
        return resp.status_code == 404 and _error_code(resp) == "unknown_tensor"

    def quiet(self) -> bool:
        return self.built == [] and not [
            c for c in self.store.puts() if c[1].startswith("tensors/")
        ]


def _distinct_menus(n: int) -> list[tuple[list, str]]:
    """n distinct (funds, lookback) keys over three symbols: 4 subsets x 6 lookbacks."""
    subsets = [["VTI", "VOO"], ["VTI", "SPY"], ["VOO", "SPY"], ["VTI", "VOO", "SPY"]]
    keys = [(_menu(ids), lb) for lb in LOOKBACKS for ids in subsets]
    assert len({(_uhash(f), lb) for f, lb in keys}) == 24 and n <= 24
    return keys[:n]


if _OUTER:

    def test_a_ps_28_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-28 is red inside the project virtualenv (output above)"

else:

    def test_invalid_inputs_get_their_codes_and_nothing_is_enqueued(tmp_path, monkeypatch):
        rig = _Rig(tmp_path, monkeypatch)
        two = ["VTI", "VOO"]
        cases = [
            # (label, funds, lookback, status, code, text the error must name)
            ("two unknown ids", _menu(["VTI", "ZZZQ", "QQQX"]), "5y", 400, "unknown_symbols", None),
            ("only unknown ids", _menu(["NOPE", "ZZZQ"]), "5y", 400, "unknown_symbols", None),
            ("one unknown id", _menu(["VTI", "VOO", "XXNOPE"]), "1y", 400, "unknown_symbols", None),
            ("duplicate fund", _menu(["VTI", "VOO", "VTI"]), "5y", 422, "invalid_request", None),
            ("31 funds", _menu(KNOWN[:31]), "5y", 422, "invalid_request", None),
            ("one fund", _menu(["VTI"]), "5y", 422, "invalid_request", None),
            ("no funds", [], "5y", 422, "invalid_request", None),
            ("lookback 4y", _menu(two), "4y", 422, "invalid_request", None),
            ("lookback empty", _menu(two), "", 422, "invalid_request", None),
            ("lookback 5Y", _menu(two), "5Y", 422, "invalid_request", None),
            ("min above max", _menu(two, VOO=(0.5, 0.2)), "5y", 422, "invalid_request", "VOO"),
            ("max above 1", _menu(two, VTI=(None, 1.5)), "5y", 422, "invalid_request", "VTI"),
            ("negative min", _menu(two, VOO=(-0.1, None)), "5y", 422, "invalid_request", "VOO"),
            (
                "sum of min above 1",
                _menu(two, VTI=(0.6, None), VOO=(0.6, None)),
                "5y",
                422,
                "invalid_request",
                "sum",
            ),
            (
                "sum of max below 1",
                _menu(two, VTI=(None, 0.4), VOO=(None, 0.4)),
                "5y",
                422,
                "invalid_request",
                "sum",
            ),
        ]
        with _client(rig.app) as client:
            assert _depth(client) == 0
            for label, funds, lookback, status, code, names in cases:
                before = _depth(client)
                resp = rig.post(client, funds, lookback)
                assert resp.status_code != 202 and resp.status_code != 200, f"{label}: accepted"
                assert resp.status_code == status, f"{label}: {resp.status_code}, expected {status}"
                assert _error_code(resp) == code, (
                    f"{label}: code {_error_code(resp)}, expected {code}"
                )
                err = resp.json()["error"]
                assert isinstance(err.get("message"), str) and "details" in err
                if code == "unknown_symbols":
                    sent = {f["id"] for f in funds} - set(KNOWN)
                    got = err["details"]["symbols"]
                    assert sorted(got) == sorted(sent), (
                        f"{label}: details.symbols {got}, expected {sorted(sent)}"
                    )
                    assert not (set(got) & set(KNOWN)), (
                        f"{label}: a known symbol was reported unknown"
                    )
                if names:
                    assert names.lower() in json.dumps(err).lower(), (
                        f"{label}: the error does not name {names}"
                    )
                assert _depth(client) == before, f"{label}: queue depth changed"
                assert rig.quiet(), f"{label}: something was built or written"
                if (
                    2 <= len(funds) <= 30
                    and len({f["id"] for f in funds}) == len(funds)
                    and lookback in LOOKBACKS
                ):
                    assert rig.unknown(client, funds, lookback), (
                        f"{label}: a job exists for the refused key"
                    )
            assert _depth(client) == 0
            # Controls: the same shapes, valid, are accepted (2 and 30 funds are inside the limits).
            for funds in (
                _menu(two),
                _menu(KNOWN[:30]),
                _menu(two, VTI=(0.1, 0.7), VOO=(0.2, 0.9)),
            ):
                ok = rig.post(client, funds)
                assert ok.status_code == 202, f"valid {len(funds)}-fund request -> {ok.status_code}"
                assert ok.json()["hash"] == _uhash(funds)
            assert _depth(client) == 3
            # One menu, two lookbacks: the same hash, two jobs.
            again = rig.post(client, _menu(two), "1y")
            assert again.status_code == 202 and again.json()["hash"] == _uhash(_menu(two))
            assert _depth(client) == 4
        assert rig.built == []

    def test_post_limiter_admits_five_per_ip_per_minute(tmp_path, monkeypatch):
        rig = _Rig(tmp_path, monkeypatch)
        keys = _distinct_menus(8)
        ip_a, ip_b = "203.0.113.7", "198.51.100.9"
        with _client(rig.app) as client:
            for funds, lb in keys[:5]:
                resp = rig.post(client, funds, lb, ip=ip_a)
                assert resp.status_code == 202, f"POST within the limit -> {resp.status_code}"
            assert _depth(client) == 5
            funds6, lb6 = keys[5]
            sixth = rig.post(client, funds6, lb6, ip=ip_a)
            assert sixth.status_code == 429, (
                f"6th POST from one IP -> {sixth.status_code}, expected 429"
            )
            assert sixth.status_code != 202 and _error_code(sixth) == "rate_limited"
            assert _depth(client) == 5 and rig.unknown(client, funds6, lb6) and rig.quiet()
            # A second IP is independent (the limiter is keyed on CF-Connecting-IP, nothing else).
            other = rig.post(client, funds6, lb6, ip=ip_b)
            assert other.status_code == 202, f"another IP was limited too: {other.status_code}"
            assert other.status_code != 429 and _depth(client) == 6
            still = rig.post(client, keys[6][0], keys[6][1], ip=ip_a)
            assert still.status_code == 429 and _depth(client) == 6
            # The window is one minute on the injected clock.
            rig.clock.t += 61.0
            later = rig.post(client, keys[6][0], keys[6][1], ip=ip_a)
            assert later.status_code == 202, (
                f"POST after 61 s on the fake clock -> {later.status_code}"
            )
            assert _depth(client) == 7
        assert rig.built == []

    def test_request_limiter_admits_sixty_per_ip_per_minute(tmp_path, monkeypatch):
        rig = _Rig(tmp_path, monkeypatch)
        ip_a, ip_b = "203.0.113.50", "198.51.100.51"
        paths = ["/v1/health", "/v1/symbols", "/v1/presets"]
        with _client(rig.app) as client:
            for n in range(60):
                resp = client.get(paths[n % 3], headers=_hdr(**{"CF-Connecting-IP": ip_a}))
                assert resp.status_code == 200, f"request {n + 1} of 60 -> {resp.status_code}"
            over = client.get("/v1/health", headers=_hdr(**{"CF-Connecting-IP": ip_a}))
            assert over.status_code == 429, (
                f"61st request in a minute -> {over.status_code}, expected 429"
            )
            assert _error_code(over) == "rate_limited"
            limited_post = rig.post(client, _menu(["VTI", "VOO"]), ip=ip_a)
            assert limited_post.status_code == 429 and limited_post.status_code != 202
            other = client.get("/v1/health", headers=_hdr(**{"CF-Connecting-IP": ip_b}))
            assert other.status_code == 200, f"another IP was limited too: {other.status_code}"
            assert other.status_code != 429 and other.json()["queue"]["depth"] == 0
            assert rig.unknown(client, _menu(["VTI", "VOO"])) and rig.quiet()
            rig.clock.t += 61.0
            again = client.get("/v1/health", headers=_hdr(**{"CF-Connecting-IP": ip_a}))
            assert again.status_code == 200, f"after 61 s on the fake clock -> {again.status_code}"

    def test_twenty_queued_jobs_make_the_next_post_busy(tmp_path, monkeypatch):
        rig = _Rig(tmp_path, monkeypatch)
        keys = _distinct_menus(22)
        with _client(rig.app) as client:
            positions = []
            for funds, lb in keys[:20]:
                resp = rig.post(client, funds, lb)
                assert resp.status_code == 202, (
                    f"job {len(positions) + 1} of 20 -> {resp.status_code}"
                )
                body = resp.json()
                assert body["status"] == "queued" and body["generation"] == rig.g
                assert body["hash"] == _uhash(funds), "the response hash is not the spec §6 hash"
                assert isinstance(body["position"], int) and not isinstance(body["position"], bool)
                positions.append(body["position"])
            assert len(set(positions)) == 20, f"queue positions are not distinct: {positions}"
            assert _depth(client) == 20
            seen = client.get(
                f"/v1/tensors/{rig.g}/{_uhash(keys[0][0])}/{keys[0][1]}", headers=_hdr()
            )
            assert seen.status_code == 202, f"GET of a queued key -> {seen.status_code}"
            for funds, lb in keys[20:22]:
                busy = rig.post(client, funds, lb)
                assert busy.status_code == 503, (
                    f"POST with 20 queued -> {busy.status_code}, expected 503"
                )
                assert busy.status_code != 202 and _error_code(busy) == "busy"
                assert _depth(client) == 20, "queue depth changed after a 503"
                assert rig.unknown(client, funds, lb), "the refused job exists"
            assert rig.quiet()

    def test_body_over_16_kb_is_refused(tmp_path, monkeypatch):
        rig = _Rig(tmp_path, monkeypatch)
        funds = _menu(["VTI", "VOO", "SPY"])
        core = json.dumps({"funds": funds, "lookback": "5y"})
        assert json.loads(core[:-1] + " " * 100 + "}") == json.loads(core)

        def padded(size: int) -> bytes:
            return (core[:-1] + " " * (size - len(core)) + "}").encode()

        big, small = padded(17 * 1024), padded(15 * 1024)
        assert (
            len(big) == 17 * 1024
            and len(small) == 15 * 1024
            and json.loads(big) == json.loads(core)
        )
        json_headers = {"content-type": "application/json"}
        with _client(rig.app) as client:
            for label, payload in (
                ("padded valid JSON", big),
                ("17 KB of non-JSON", b"x" * (17 * 1024)),
            ):
                resp = client.post("/v1/tensors", content=payload, headers=_hdr(**json_headers))
                assert resp.status_code in (413, 422), (
                    f"{label}: {resp.status_code}, expected 413 or 422"
                )
                assert resp.status_code != 202 and resp.status_code != 200
                assert isinstance(_error_code(resp), str), f"{label}: no error envelope"
                assert _depth(client) == 0 and rig.quiet()
                assert rig.unknown(client, funds), f"{label}: the oversize request created a job"
            under = client.post("/v1/tensors", content=small, headers=_hdr(**json_headers))
            assert under.status_code == 202, (
                f"a 15 KB valid body -> {under.status_code}, expected 202"
            )
            assert under.json()["hash"] == _uhash(funds) and _depth(client) == 1
