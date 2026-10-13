"""A-PS-06 — the provider budget ledger stops, sleeps and resumes at the configured limits.

Claim: the downloader reads limits from meta/provider_limits.json (else the env fallbacks
45/900/450), counts requests per UTC hour and day and unique symbols per month in
meta/budget.json, sleeps to the next hour when the hourly budget is spent, exits cleanly when the
daily or monthly budget is spent, and resumes on the next run from where it stopped.

Pinned interface (the product must provide exactly this):
- `portfoliosight.data.download.run(mode, *, store, providers, clock, sleep, symbols=None,
  tiers=None) -> int`: `mode` is `"measure-limits" | "catch-up" | "refresh"`; `providers` maps a
  provider name to a provider (`"tiingo"` serves every id that does not start with `TSP-`);
  `clock()` returns an aware UTC datetime and is the only source of time; `sleep(seconds)` is the
  only way the run waits; `symbols`, when given, is the configured nightly set in priority order
  (no repo universe file is consulted; name/kind/tier come from the manifest entry); the return
  value is the exit code, 0 on a clean run including a run stopped by the daily or monthly budget.
  `D_G` is `portfoliosight.data.calendar.generation_date(clock())`.
- One provider request = one call of `fetch_daily` or `fetch_meta`; in `refresh` a symbol that
  has a record costs exactly one request, and a symbol current at `D_G` costs none.
- Limits: `meta/provider_limits.json` keys `req_per_hour, req_per_day, unique_symbols_per_month`
  win over the environment; without the file, `PS_PROVIDER_REQ_PER_HOUR`, `PS_PROVIDER_REQ_PER_DAY`,
  `PS_PROVIDER_SYMBOLS_PER_MONTH` (defaults 45, 900, 450).
- `meta/budget.json` = `{"limits": {"req_per_hour", "req_per_day", "unique_symbols_per_month"},
  "hours": {"YYYY-MM-DDTHH": n}, "days": {"YYYY-MM-DD": n}, "months": {"YYYY-MM": [ids...]}}`,
  all keys in UTC.
- A run stopped by the daily budget says "daily budget spent" (any case) on stdout, stderr or
  through `logging`.
- `measure-limits`: up to 60 `fetch_meta` calls for the one symbol in `symbols`, within ten
  minutes of clock time; the provider signals HTTP 429 by raising
  `portfoliosight.data.providers.base.RateLimited` (an `Exception` subclass taking a message); the
  probe stops at the first 429 and writes `meta/provider_limits.json` with exactly the keys
  `provider, tier, req_per_hour, req_per_day, unique_symbols_per_month, measured_on, method`:
  a 429 gives `tier: "starter"` with 45/900/450; no 429 gives a tier string that contains "60"
  and is neither "starter" nor "power"; `method: "probe"`, `measured_on` = the clock's UTC date.
- `portfoliosight.data.providers.base.SymbolMeta(name=, first_date=, last_date=, kind=)`.
- `portfoliosight.data.store.LocalStore`, the canonical record and the manifest (shared pins).
"""

from __future__ import annotations

import importlib
import io
import json
import logging
import math
import os
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
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
        pytest.fail(f"A-PS-06 red: cannot import {module}: {type(exc).__name__}: {exc}")


SYMBOLS = [f"S{i:03d}" for i in range(1, 101)]  # the configured nightly set, in priority order
RECORD_START = date(2025, 11, 3)
RECORD_END = date(2026, 3, 6)  # every symbol starts one week behind
ENV_NAMES = (
    "PS_PROVIDER_REQ_PER_HOUR",
    "PS_PROVIDER_REQ_PER_DAY",
    "PS_PROVIDER_SYMBOLS_PER_MONTH",
)
LIMIT_KEYS = ("req_per_hour", "req_per_day", "unique_symbols_per_month")
_SESSIONS: list[date] = []


def _sessions() -> list[date]:
    if not _SESSIONS:
        xc = _need("exchange_calendars")
        cal = xc.get_calendar("XNYS")
        _SESSIONS.extend(s.date() for s in cal.sessions_in_range("2025-10-01", "2026-06-30"))
    return _SESSIONS


def _expected_dg(run_at: datetime) -> date:
    """Spec section 4.2, recomputed here: last XNYS close >= 6 h before 02:00 Los Angeles."""
    from zoneinfo import ZoneInfo

    pd = _need("pandas")
    xc = _need("exchange_calendars")
    la = ZoneInfo("America/Los_Angeles")
    la_day = run_at.astimezone(la).date()
    cutoff = pd.Timestamp(datetime.combine(la_day, time(2, 0), tzinfo=la) - timedelta(hours=6))
    cal = xc.get_calendar("XNYS")
    lo = pd.Timestamp(la_day - timedelta(days=15))
    for session in reversed(cal.sessions_in_range(lo, pd.Timestamp(la_day))):
        if cal.session_close(session) <= cutoff.tz_convert("UTC"):
            return session.date()
    pytest.fail("A-PS-06: no XNYS session found in the 15 days before the run date")


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _close(symbol: str, day: date) -> float:
    seed = sum(ord(c) for c in symbol)
    return (
        80.0 + seed % 40 + 0.02 * (day.toordinal() % 500) + math.sin(day.toordinal() * 0.7 + seed)
    )


class _Clock:
    def __init__(self, events: list):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.events = events
        self.sleeps = 0

    def __call__(self) -> datetime:
        return self.now

    def set(self, y, m, d, hh, mm):
        self.now = datetime(y, m, d, hh, mm, tzinfo=timezone.utc)

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > 20_000:
            pytest.fail("A-PS-06: runaway sleep loop in the downloader (20,000 sleeps)")
        self.events.append(("sleep", self.now, float(seconds)))
        self.now += timedelta(seconds=max(float(seconds), 0.0))


class _FakeProvider:
    """Records every call; serves a deterministic price history through `available`."""

    name = "tiingo"

    def __init__(self, clock: _Clock, events: list, rate_limit_at: int | None = None):
        self.clock = clock
        self.events = events
        self.available = RECORD_END
        self.rate_limit_at = rate_limit_at
        self.calls: list[tuple] = []  # (kind, symbol, start, at)

    def _count(self, kind, symbol, start):
        self.calls.append((kind, symbol, start, self.clock.now))
        self.events.append(("call", self.clock.now, symbol))
        if len(self.calls) > 2_000:
            pytest.fail("A-PS-06: runaway provider loop in the downloader (2,000 calls)")
        if self.rate_limit_at is not None and len(self.calls) >= self.rate_limit_at:
            base = _need("portfoliosight.data.providers.base")
            raise base.RateLimited("429 Too Many Requests")

    def fetch_daily(self, symbol, start, end=None):
        pd = _need("pandas")
        start = _as_date(start)
        self._count("daily", symbol, start)
        stop = min(self.available, _as_date(end)) if end is not None else self.available
        days = [d for d in _sessions() if start <= d <= stop]
        closes = [_close(symbol, d) for d in days]
        return pd.DataFrame(
            {
                "close": closes,
                "adj_close": closes,
                "div_cash": [0.0] * len(days),
                "split_factor": [1.0] * len(days),
            },
            index=pd.DatetimeIndex(pd.to_datetime(days), name="date"),
            dtype=float,
        )

    def fetch_meta(self, symbol):
        self._count("meta", symbol, None)
        base = _need("portfoliosight.data.providers.base")
        return base.SymbolMeta(
            name=f"{symbol} Fund", first_date=RECORD_START, last_date=self.available, kind="etf"
        )


def _seeded_store(tmp_path, symbols):
    """A LocalStore holding a record and a manifest entry for every symbol, one week behind."""
    pd = _need("pandas")
    np = _need("numpy")
    store = _need("portfoliosight.data.store").LocalStore(tmp_path / "store")
    days = [d for d in _sessions() if RECORD_START <= d <= RECORD_END]
    entries = {}
    for symbol in symbols:
        closes = np.array([_close(symbol, d) for d in days])
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(days),
                "close": closes,
                "tr_index": closes / closes[0],
                "div_cash": np.zeros(len(days)),
                "split_factor": np.ones(len(days)),
            }
        )
        buf = io.BytesIO()
        frame.to_parquet(buf, index=False)
        store.put(f"prices/{symbol}.parquet", buf.getvalue())
        entries[symbol] = {
            "name": f"{symbol} Fund",
            "kind": "etf",
            "tier": 2,
            "income": False,
            "source": "tiingo",
            "first_date": days[0].isoformat(),
            "last_date": days[-1].isoformat(),
            "adjusted_through": days[-1].isoformat(),
            "status": "stale",
            "reason": None,
            "fetched_at": "2026-03-07T10:00:00+00:00",
        }
    store.put("meta/manifest.json", json.dumps({"symbols": entries}).encode())
    return store


def _put_limits(store, hour, day, month):
    doc = {
        "provider": "tiingo",
        "tier": "starter",
        "req_per_hour": hour,
        "req_per_day": day,
        "unique_symbols_per_month": month,
        "measured_on": "2026-03-01",
        "method": "probe",
    }
    store.put("meta/provider_limits.json", json.dumps(doc).encode())


def _go(mode, store, provider, clock, symbols, capsys, caplog) -> tuple[int, str, list]:
    """One downloader run. Returns (exit code, everything it said, the provider calls it made)."""
    download = _need("portfoliosight.data.download")
    caplog.clear()
    capsys.readouterr()
    first = len(provider.calls)
    try:
        code = download.run(
            mode,
            store=store,
            providers={"tiingo": provider},
            clock=clock,
            sleep=clock.sleep,
            symbols=list(symbols),
        )
    except SystemExit as exc:
        pytest.fail(f"A-PS-06 red: download.run({mode!r}) raised SystemExit({exc.code!r})")
    except Exception as exc:
        pytest.fail(f"A-PS-06 red: download.run({mode!r}) raised {exc!r}")
    out = capsys.readouterr()
    said = "\n".join([out.out, out.err, caplog.text])
    assert isinstance(code, int), f"run() must return the exit code as int, got {code!r}"
    return code, said, provider.calls[first:]


def _ledger(store) -> dict:
    try:
        doc = json.loads(store.get("meta/budget.json"))
    except KeyError:
        pytest.fail("A-PS-06 red: meta/budget.json was not written")
    for key in ("limits", "hours", "days", "months"):
        assert key in doc, f"meta/budget.json lacks {key!r}"
    return doc


def _assert_within(calls, hour, day, month):
    """Must-not-contain: a provider call beyond any limit, counted from the fake's own log."""
    per_hour = Counter(at.strftime("%Y-%m-%dT%H") for _, _, _, at in calls)
    per_day = Counter(at.strftime("%Y-%m-%d") for _, _, _, at in calls)
    per_month: dict[str, set] = {}
    for _, symbol, _, at in calls:
        per_month.setdefault(at.strftime("%Y-%m"), set()).add(symbol)
    assert not [k for k, n in per_hour.items() if n > hour], (
        f"hourly limit {hour} exceeded: {per_hour}"
    )
    assert not [k for k, n in per_day.items() if n > day], f"daily limit {day} exceeded: {per_day}"
    over = {k: len(v) for k, v in per_month.items() if len(v) > month}
    assert not over, f"monthly unique-symbol limit {month} exceeded: {over}"
    return per_hour, per_day, per_month


def _assert_slept_to_next_hour(events, calls, index):
    """Between call number `index` and the next one: a sleep, no call, and the top of the hour."""
    at_before, at_after = calls[index - 1][3], calls[index][3]
    positions = [i for i, e in enumerate(events) if e[0] == "call"]
    lo = max(i for i in positions if events[i][1] == at_before)
    hi = min(i for i in positions if i > lo)
    between = events[lo + 1 : hi]
    assert between, f"no sleep between call {index} and call {index + 1}"
    assert all(e[0] == "sleep" for e in between), "a provider call happened during the wait"
    next_hour = at_before.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    assert next_hour <= at_after < next_hour + timedelta(minutes=5), (
        f"call {index + 1} at {at_after:%H:%M:%S}; expected just after {next_hour:%H:%M}"
    )
    assert sum(e[2] for e in between) >= (next_hour - at_before).total_seconds() - 1


if _OUTER:

    def test_a_ps_06_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-06 is red inside the project virtualenv (output above)"

else:

    def test_file_limits_hour_sleep_day_stop_resume_and_month(
        tmp_path, monkeypatch, capsys, caplog
    ):
        caplog.set_level(logging.DEBUG)
        for name, value in zip(ENV_NAMES, ("3", "4", "5")):  # the file must win over these
            monkeypatch.setenv(name, value)
        store = _seeded_store(tmp_path, SYMBOLS)
        _put_limits(store, 10, 25, 30)
        events: list = []
        clock = _Clock(events)
        provider = _FakeProvider(clock, events)

        # Day 1, Saturday: D_G is Friday 2026-03-13 and every symbol is a week behind.
        clock.set(2026, 3, 14, 12, 5)
        assert _expected_dg(clock.now) == date(2026, 3, 13)
        provider.available = date(2026, 3, 13)
        code, said, calls = _go("refresh", store, provider, clock, SYMBOLS, capsys, caplog)
        assert code == 0, f"a run stopped by the daily budget must exit 0, got {code}"
        assert len(calls) == 25, f"{len(calls)} provider calls on day 1; the daily budget is 25"
        assert [c[1] for c in calls] == SYMBOLS[:25], "day 1 must walk the priority order"
        assert "daily budget spent" in said.lower(), (
            f"no 'daily budget spent' message in: {said[-400:]!r}"
        )
        per_hour, _, _ = _assert_within(provider.calls, 10, 25, 30)
        assert per_hour == {"2026-03-14T12": 10, "2026-03-14T13": 10, "2026-03-14T14": 5}, per_hour
        _assert_slept_to_next_hour(events, calls, 10)  # (1) the 11th call waits for 13:00
        _assert_slept_to_next_hour(events, calls, 20)
        for kind, symbol, start, _ in calls:
            assert kind == "daily" and start == RECORD_END - timedelta(days=7), (
                symbol,
                kind,
                start,
            )
        ledger = _ledger(store)
        assert ledger["days"].get("2026-03-14") == 25, f"ledger day count: {ledger['days']}"
        assert (
            ledger["hours"].get("2026-03-14T12") == 10 and ledger["hours"].get("2026-03-14T14") == 5
        )
        assert sorted(ledger["months"].get("2026-03", [])) == SYMBOLS[:25], ledger["months"]
        assert {k: ledger["limits"].get(k) for k in LIMIT_KEYS} == dict(
            zip(LIMIT_KEYS, (10, 25, 30))
        )
        assert ledger["limits"].get("req_per_hour") != 3, (
            "env fallback used although the file exists"
        )

        # (3a) a rerun the same day makes no provider call.
        clock.set(2026, 3, 14, 18, 30)
        code, said, calls = _go("refresh", store, provider, clock, SYMBOLS, capsys, caplog)
        assert code == 0 and calls == [], f"same-day rerun made {len(calls)} provider calls"
        assert _ledger(store)["days"].get("2026-03-14") == 25

        # (3b) next day, same D_G: it continues with the 26th symbol; (4) and stops at 30 unique.
        clock.set(2026, 3, 15, 12, 5)
        assert _expected_dg(clock.now) == date(2026, 3, 13)
        code, said, calls = _go("refresh", store, provider, clock, SYMBOLS, capsys, caplog)
        assert code == 0, f"a run stopped by the monthly budget must exit 0, got {code}"
        assert calls, "the next-day run fetched nothing"
        assert calls[0][1] == SYMBOLS[25], f"resumed at {calls[0][1]}, expected {SYMBOLS[25]}"
        assert calls[0][1] != SYMBOLS[0], "the run started over from the first symbol"
        assert [c[1] for c in calls] == SYMBOLS[25:30], (
            f"day 2 fetched {[c[1] for c in calls]}; the monthly budget allows only {SYMBOLS[25:30]}"
        )
        assert not {c[1] for c in calls} & set(SYMBOLS[30:]), "a 31st new symbol was fetched"
        ledger = _ledger(store)
        assert sorted(ledger["months"].get("2026-03", [])) == SYMBOLS[:30], ledger["months"]
        assert ledger["days"].get("2026-03-15") == 5 and ledger["days"].get("2026-03-14") == 25

        # (4) with the month spent, a previously fetched symbol is still refreshed.
        clock.set(2026, 3, 17, 12, 5)
        assert _expected_dg(clock.now) == date(2026, 3, 16)
        provider.available = date(2026, 3, 16)
        code, said, calls = _go("refresh", store, provider, clock, SYMBOLS, capsys, caplog)
        assert code == 0, f"exit code {code}"
        assert [c[1] for c in calls] == SYMBOLS[:25], (
            f"day 3 fetched {len(calls)} symbols starting {[c[1] for c in calls][:3]}; expected the "
            "25 previously fetched symbols the daily budget allows"
        )
        assert not {c[1] for c in calls} - set(SYMBOLS[:30]), (
            "a new symbol was fetched past the cap"
        )
        assert "daily budget spent" in said.lower()
        ledger = _ledger(store)
        assert len(set(ledger["months"].get("2026-03", []))) == 30
        assert ledger["days"].get("2026-03-17") == 25
        _assert_within(provider.calls, 10, 25, 30)
        assert len(provider.calls) == 55, f"{len(provider.calls)} provider calls over the four runs"

    def test_env_fallbacks_when_there_is_no_limits_file(tmp_path, monkeypatch, capsys, caplog):
        caplog.set_level(logging.DEBUG)
        cases = [
            # (env values or None for unset, expected limits, expected calls per hour bucket)
            ((None, None, None), (45, 900, 450), [45, 45, 10]),
            (("7", "12", "40"), (7, 12, 40), [7, 5]),
            (("50", "60", "9"), (50, 60, 9), [9]),
        ]
        for n, (env, limits, buckets) in enumerate(cases):
            for name, value in zip(ENV_NAMES, env):
                if value is None:
                    monkeypatch.delenv(name, raising=False)
                else:
                    monkeypatch.setenv(name, value)
            store = _seeded_store(tmp_path / f"case{n}", SYMBOLS)
            assert not store.exists("meta/provider_limits.json")
            events: list = []
            clock = _Clock(events)
            provider = _FakeProvider(clock, events)
            clock.set(2026, 3, 14, 12, 5)
            provider.available = date(2026, 3, 13)
            code, said, calls = _go("refresh", store, provider, clock, SYMBOLS, capsys, caplog)
            assert code == 0, f"limits {limits}: exit code {code}"
            per_hour, _, _ = _assert_within(provider.calls, *limits)
            assert [per_hour[k] for k in sorted(per_hour)] == buckets, (
                f"limits {limits}: calls per hour {dict(per_hour)}, expected {buckets}"
            )
            assert [c[1] for c in calls] == SYMBOLS[: sum(buckets)], f"limits {limits}: order"
            ledger = _ledger(store)
            got = {k: ledger["limits"].get(k) for k in LIMIT_KEYS}
            assert got == dict(zip(LIMIT_KEYS, limits)), f"ledger limits {got}, expected {limits}"
            assert sum(ledger["days"].values()) == sum(buckets), ledger["days"]
            if limits[1] == 12:
                assert "daily budget spent" in said.lower()
            if n == 0:
                assert len(calls) == 100 and "daily budget spent" not in said.lower()
                _assert_slept_to_next_hour(events, calls, 45)

    def test_measure_limits_records_the_probe(tmp_path, monkeypatch, capsys, caplog):
        caplog.set_level(logging.DEBUG)
        store_mod = _need("portfoliosight.data.store")
        expected_keys = {"provider", "tier", "measured_on", "method", *LIMIT_KEYS}
        for label, rate_limit_at, n_calls in (("429 on the 37th", 37, 37), ("no 429", None, 60)):
            store = store_mod.LocalStore(tmp_path / label.replace(" ", "_"))
            events: list = []
            clock = _Clock(events)
            clock.set(2026, 3, 14, 12, 5)
            provider = _FakeProvider(clock, events, rate_limit_at=rate_limit_at)
            code, said, calls = _go(
                "measure-limits", store, provider, clock, ["VTI"], capsys, caplog
            )
            assert code == 0, f"{label}: exit code {code}"
            assert len(calls) == n_calls, f"{label}: {len(calls)} probe calls, expected {n_calls}"
            assert not len(calls) > 60, f"{label}: more than 60 probes"
            assert {c[0] for c in calls} == {"meta"}, f"{label}: the probe must use meta requests"
            assert {c[1] for c in calls} == {"VTI"}, f"{label}: the probe must use one symbol"
            span = (calls[-1][3] - calls[0][3]).total_seconds()
            assert span <= 600, f"{label}: probes spread over {span:.0f} s, limit is ten minutes"
            try:
                doc = json.loads(store.get("meta/provider_limits.json"))
            except KeyError:
                pytest.fail(f"A-PS-06 red: {label}: meta/provider_limits.json was not written")
            assert set(doc) == expected_keys, f"{label}: keys {sorted(doc)}"
            assert doc["provider"] == "tiingo" and doc["method"] == "probe", doc
            assert doc["method"] != "documented"
            assert doc["measured_on"] == "2026-03-14", doc["measured_on"]
            for key in LIMIT_KEYS:
                assert isinstance(doc[key], int) and doc[key] > 0, f"{label}: {key}={doc[key]!r}"
            if rate_limit_at is not None:
                assert doc["tier"] == "starter", f"{label}: tier {doc['tier']!r}"
                assert [doc[k] for k in LIMIT_KEYS] == [45, 900, 450], doc
            else:
                tier = str(doc["tier"]).lower()
                assert tier != "starter", "no 429 in 60 probes must not be recorded as Starter"
                assert tier != "power", "Power needs the owner's confirmation, not a probe"
                assert "60" in tier, f"tier {doc['tier']!r} must say 'at least 60/10 min'"
