"""A-PS-07 — served means current.

Claim: a symbol's manifest status is ok exactly when last_date >= D - 3 and adjusted_through >= D - 3
trading days; seeded symbols are pending until their first tail refresh; a served symbol that
falls behind becomes stale and recovers to ok on the next successful refresh; meta/symbols.json
lists ok symbols only with tiers_served derived from them; unavailable symbols are retried on the
first run of each month.

Pinned interface (the product must provide exactly this):
- `portfoliosight.data.manifest.status_for(entry, d_g) -> str`: a pure function over one manifest
  entry (ISO date strings) and `d_g` (`datetime.date`): `"pending"` when `entry["source"] ==
  "seed"` (never tail-refreshed), else `"ok"` when `last_date` and `adjusted_through` are both on
  or after the XNYS session three sessions before `d_g`, else `"stale"`.
- `portfoliosight.data.download.run(mode, *, store, providers, clock, sleep, symbols=None,
  tiers=None) -> int` (see A-PS-03/A-PS-06): `refresh` visits every symbol of `symbols` whatever
  its status, except that an `unavailable` symbol is requested only when the run's date is the
  1st of a month; a symbol whose provider returns an empty frame is `unavailable`; after a
  successful tail refresh a seed's `source` becomes `"seed+tiingo"`; the run recomputes every
  visited symbol's status against `D_G = calendar.generation_date(clock())`, keeps manifest
  entries that are outside `symbols`, and rewrites `meta/manifest.json` and `meta/symbols.json`.
- `meta/symbols.json` = `{"catalog_at": iso, "tiers_served": [int...], "symbols": [{"id", "name",
  "kind", "tier", "first_date"}]}` listing exactly the manifest's `ok` ids.
- `portfoliosight.data.providers.base.SymbolMeta(name=, first_date=, last_date=, kind=)`;
  `portfoliosight.data.store.LocalStore`; the canonical record and the manifest (shared pins).
"""

from __future__ import annotations

import importlib
import io
import json
import math
import os
import subprocess
import sys
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
        pytest.fail(f"A-PS-07 red: cannot import {module}: {type(exc).__name__}: {exc}")


RECORD_START = date(2025, 11, 3)
NOT_SERVED = ("pending", "stale", "unavailable")
_SESSIONS: list[date] = []


def _sessions() -> list[date]:
    if not _SESSIONS:
        xc = _need("exchange_calendars")
        cal = xc.get_calendar("XNYS")
        _SESSIONS.extend(s.date() for s in cal.sessions_in_range("2025-10-01", "2026-12-31"))
    return _SESSIONS


def _back(day: date, n: int) -> date:
    """The XNYS session n sessions before `day` (itself a session)."""
    sessions = _sessions()
    return sessions[sessions.index(day) - n]


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
    pytest.fail("A-PS-07: no XNYS session found in the 15 days before the run date")


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
    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.sleeps = 0

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > 20_000:
            pytest.fail("A-PS-07: runaway sleep loop in the downloader (20,000 sleeps)")
        self.now += timedelta(seconds=max(float(seconds), 0.0))


class _FakeProvider:
    """Per-symbol availability; ids in `gone` answer like a 404 (empty frame, no meta)."""

    name = "tiingo"

    def __init__(self, gone=()):
        self.available: dict[str, date] = {}
        self.gone = set(gone)
        self.calls: list[tuple[str, str]] = []

    def _count(self, kind, symbol):
        self.calls.append((kind, symbol))
        if len(self.calls) > 2_000:
            pytest.fail("A-PS-07: runaway provider loop in the downloader (2,000 calls)")

    def fetch_daily(self, symbol, start, end=None):
        pd = _need("pandas")
        self._count("daily", symbol)
        days: list[date] = []
        if symbol not in self.gone:
            stop = self.available[symbol]
            if end is not None:
                stop = min(stop, _as_date(end))
            days = [d for d in _sessions() if _as_date(start) <= d <= stop]
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
        self._count("meta", symbol)
        if symbol in self.gone:
            return None
        base = _need("portfoliosight.data.providers.base")
        return base.SymbolMeta(
            name=f"{symbol} Fund",
            first_date=RECORD_START,
            last_date=self.available[symbol],
            kind="etf",
        )


def _put_record(store, symbol: str, prices_through: date, adjusted_through: date):
    pd = _need("pandas")
    np = _need("numpy")
    days = [d for d in _sessions() if RECORD_START <= d <= prices_through]
    closes = np.array([_close(symbol, d) for d in days])
    tr = closes / closes[0]
    tr[np.array([d > adjusted_through for d in days])] = np.nan  # price-only rows
    seeded = prices_through != adjusted_through
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(days),
            "close": closes,
            "tr_index": tr,
            "div_cash": np.full(len(days), np.nan if seeded else 0.0),
            "split_factor": np.full(len(days), np.nan if seeded else 1.0),
        }
    )
    buf = io.BytesIO()
    frame.to_parquet(buf, index=False)
    store.put(f"prices/{symbol}.parquet", buf.getvalue())


def _entry(name, kind, tier, source, status, last, adjusted, reason=None) -> dict:
    return {
        "name": name,
        "kind": kind,
        "tier": tier,
        "income": False,
        "source": source,
        "first_date": RECORD_START.isoformat() if last else None,
        "last_date": last.isoformat() if last else None,
        "adjusted_through": adjusted.isoformat() if adjusted else None,
        "status": status,
        "reason": reason,
        "fetched_at": "2026-02-21T10:00:00+00:00" if source != "seed" and last else None,
    }


def _manifest(store) -> dict:
    doc = json.loads(store.get("meta/manifest.json"))
    assert isinstance(doc.get("symbols"), dict), "meta/manifest.json must be {'symbols': {...}}"
    return doc["symbols"]


def _check_catalog(store, want_status: dict[str, str], step: str):
    """The manifest statuses, and symbols.json as exactly the ok ids with their tiers."""
    entries = _manifest(store)
    got_status = {symbol: entries.get(symbol, {}).get("status") for symbol in want_status}
    assert got_status == want_status, f"{step}: statuses {got_status}, expected {want_status}"
    try:
        catalog = json.loads(store.get("meta/symbols.json"))
    except KeyError:
        pytest.fail(f"A-PS-07 red: {step}: meta/symbols.json was not written")
    for key in ("catalog_at", "tiers_served", "symbols"):
        assert key in catalog, f"{step}: meta/symbols.json lacks {key!r}"
    listed = [s["id"] for s in catalog["symbols"]]
    assert len(listed) == len(set(listed)), f"{step}: duplicate ids in symbols.json"
    ok_ids = {s for s, status in want_status.items() if status == "ok"}
    assert set(listed) == ok_ids, (
        f"{step}: symbols.json lists {sorted(listed)}, ok ids are {sorted(ok_ids)}"
    )
    for symbol, status in want_status.items():
        if status in NOT_SERVED:
            assert symbol not in listed, f"{step}: {status} symbol {symbol} is in symbols.json"
    assert set(listed) == {s for s, e in entries.items() if e.get("status") == "ok"}, (
        f"{step}: symbols.json disagrees with the manifest it was derived from"
    )
    want_tiers = sorted({entries[s]["tier"] for s in ok_ids})
    assert catalog["tiers_served"] == want_tiers, (
        f"{step}: tiers_served {catalog['tiers_served']}, expected {want_tiers}"
    )
    for row in catalog["symbols"]:
        entry = entries[row["id"]]
        for key in ("name", "kind", "tier", "first_date"):
            assert row.get(key) == entry[key], (
                f"{step}: symbols.json {row['id']}.{key} = {row.get(key)!r}"
            )
    return entries


if _OUTER:

    def test_a_ps_07_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-07 is red inside the project virtualenv (output above)"

else:

    def test_status_rule_boundaries_on_the_xnys_calendar():
        manifest = _need("portfoliosight.data.manifest")
        sessions = _sessions()
        days = [d for d in sessions if date(2026, 1, 12) <= d <= date(2026, 12, 4)][::4]
        assert len(days) >= 50
        cases = 0
        for d_g in days:
            assert _back(d_g, 3) < d_g and _back(d_g, 4) < _back(d_g, 3)
            for a in range(0, 7):  # last_date is a sessions behind D
                for b in range(0, 7):  # adjusted_through is b sessions behind D
                    for source, prior in (("tiingo", "ok"), ("seed+tiingo", "stale")):
                        entry = _entry("F", "etf", 2, source, prior, _back(d_g, a), _back(d_g, b))
                        want = "ok" if a <= 3 and b <= 3 else "stale"
                        try:
                            got = manifest.status_for(entry, d_g)
                        except Exception as exc:
                            pytest.fail(f"A-PS-07 red: status_for raised {exc!r}")
                        assert got == want, (
                            f"D={d_g} last_date=D-{a} adjusted_through=D-{b} ({source}): "
                            f"{got!r}, expected {want!r}"
                        )
                        cases += 1
            # The two boundary days by name.
            at3 = _entry("F", "etf", 2, "tiingo", "ok", d_g, _back(d_g, 3))
            at4 = _entry("F", "etf", 2, "tiingo", "ok", d_g, _back(d_g, 4))
            assert manifest.status_for(at3, d_g) == "ok"
            assert manifest.status_for(at4, d_g) != "ok", (
                f"adjusted_through = D-4 served at D={d_g}"
            )
            late = _entry("F", "etf", 2, "tiingo", "ok", _back(d_g, 4), d_g)
            assert manifest.status_for(late, d_g) != "ok", f"last_date = D-4 served at D={d_g}"
            # A seed that was never tail-refreshed is pending however recent its prices are.
            seed = _entry("F", "stock", 3, "seed", "pending", d_g, _back(d_g, 40))
            assert manifest.status_for(seed, d_g) == "pending"
            fresh_seed = _entry("F", "stock", 3, "seed", "pending", d_g, d_g)
            assert manifest.status_for(fresh_seed, d_g) != "ok", "an unrefreshed seed was served"
        assert cases == len(days) * 98, f"{cases} boundary cases checked"
        # Trading days, not calendar days: over a weekend D-3 sessions is five calendar days back.
        monday = date(2026, 3, 9)
        assert _back(monday, 3) == date(2026, 3, 4)
        weekend = _entry("F", "etf", 1, "tiingo", "ok", date(2026, 3, 4), date(2026, 3, 4))
        assert manifest.status_for(weekend, monday) == "ok", "D-3 must count XNYS sessions"

    def test_statuses_and_catalog_over_a_sequence_of_days(tmp_path):
        store = _need("portfoliosight.data.store").LocalStore(tmp_path / "store")
        download = _need("portfoliosight.data.download")
        feb20, feb23, feb26, feb27 = (date(2026, 2, d) for d in (20, 23, 26, 27))
        # Independent calendar facts the sequence relies on.
        assert _back(feb26, 3) == feb23 and _back(feb27, 4) == feb23 and _back(feb27, 3) != feb23

        _put_record(store, "OKA", feb20, feb20)
        _put_record(store, "STL", date(2026, 2, 6), date(2026, 2, 6))
        _put_record(store, "SEED", feb20, date(2026, 1, 30))
        _put_record(store, "SEED2", feb20, feb20)  # seeded today: prices and adjustments recent
        entries = {
            "OKA": _entry("Oka ETF", "etf", 1, "tiingo", "ok", feb20, feb20),
            "STL": _entry(
                "Stale Fund",
                "mutual_fund",
                2,
                "tiingo",
                "stale",
                date(2026, 2, 6),
                date(2026, 2, 6),
            ),
            "SEED": _entry("Seeded Co", "stock", 3, "seed", "pending", feb20, date(2026, 1, 30)),
            "SEED2": _entry("Seeded Two", "stock", 3, "seed", "pending", feb20, feb20),
            "GONE": _entry(
                "Gone Fund", "mutual_fund", 2, "tiingo", "unavailable", None, None, "no data"
            ),
        }
        store.put("meta/manifest.json", json.dumps({"symbols": entries}).encode())
        provider = _FakeProvider(gone={"GONE"})
        clock = _Clock()

        def run(day: date, symbols, expect_dg: date, available: dict) -> list[tuple[str, str]]:
            clock.now = datetime.combine(day, time(12, 5), tzinfo=timezone.utc)
            assert _expected_dg(clock.now) == expect_dg, "test calendar: unexpected D_G"
            provider.available.update(available)
            first = len(provider.calls)
            try:
                code = download.run(
                    "refresh",
                    store=store,
                    providers={"tiingo": provider},
                    clock=clock,
                    sleep=clock.sleep,
                    symbols=list(symbols),
                )
            except Exception as exc:
                pytest.fail(f"A-PS-07 red: download.run('refresh') on {day} raised {exc!r}")
            assert code == 0, f"refresh on {day} exited {code}"
            return provider.calls[first:]

        def touched(calls, symbol) -> int:
            return sum(1 for _, s in calls if s == symbol)

        full = ["OKA", "GONE", "STL", "SEED"]

        # Monday 02-23 (D_G = Fri 02-20): the seeds are outside the set; STL's provider is behind.
        calls = run(
            date(2026, 2, 23),
            ["OKA", "GONE", "STL"],
            feb20,
            {"OKA": feb20, "STL": date(2026, 2, 6)},
        )
        want = {
            "OKA": "ok",
            "STL": "stale",
            "SEED": "pending",
            "SEED2": "pending",
            "GONE": "unavailable",
        }
        now = _check_catalog(store, want, "02-23")
        assert now["SEED"]["last_date"] == feb20.isoformat(), (
            "test setup: SEED's prices are current"
        )
        assert touched(calls, "STL") >= 1, "refresh must visit a stale symbol"
        assert touched(calls, "GONE") == 0, "an unavailable symbol was requested on the 23rd"
        assert touched(calls, "SEED") == 0 and touched(calls, "SEED2") == 0

        # Tuesday 02-24 (D_G = 02-23): pending -> ok after the tail refresh; stale -> ok.
        everyone = {"OKA": feb23, "STL": feb23, "SEED": feb23}
        calls = run(date(2026, 2, 24), full, feb23, everyone)
        want = {"OKA": "ok", "STL": "ok", "SEED": "ok", "SEED2": "pending", "GONE": "unavailable"}
        now = _check_catalog(store, want, "02-24")
        assert touched(calls, "SEED") >= 1 and touched(calls, "STL") >= 1
        assert now["SEED"]["source"] == "seed+tiingo", f"SEED source {now['SEED']['source']!r}"
        assert now["SEED"]["adjusted_through"] == feb23.isoformat()
        assert now["SEED2"]["source"] == "seed" and now["SEED2"]["adjusted_through"] == "2026-02-20"
        assert touched(calls, "GONE") == 0 and touched(calls, "SEED2") == 0

        # Friday 02-27 (D_G = 02-26): STL's provider stays at 02-23 = D-3 sessions: still ok.
        calls = run(date(2026, 2, 27), full, feb26, {"OKA": feb26, "SEED": feb26})
        now = _check_catalog(store, want, "02-27")
        assert now["STL"]["last_date"] == feb23.isoformat() == now["STL"]["adjusted_through"]
        assert touched(calls, "GONE") == 0

        # Saturday 02-28 (D_G = 02-27): STL is now four sessions behind: ok -> stale.
        calls = run(date(2026, 2, 28), full, feb27, {"OKA": feb27, "SEED": feb27})
        want = {
            "OKA": "ok",
            "STL": "stale",
            "SEED": "ok",
            "SEED2": "pending",
            "GONE": "unavailable",
        }
        now = _check_catalog(store, want, "02-28")
        assert now["STL"]["status"] != "ok" and now["STL"]["last_date"] == feb23.isoformat()
        assert touched(calls, "STL") >= 1, "refresh must keep visiting the lagging symbol"
        assert touched(calls, "GONE") == 0

        # Sunday 03-01 (D_G = 02-27): one successful fetch restores STL; the 1st retries GONE.
        calls = run(date(2026, 3, 1), full, feb27, {"STL": feb27})
        want = {"OKA": "ok", "STL": "ok", "SEED": "ok", "SEED2": "pending", "GONE": "unavailable"}
        now = _check_catalog(store, want, "03-01")
        assert touched(calls, "STL") >= 1, "the stale symbol was not refetched"
        assert now["STL"]["last_date"] == feb27.isoformat()
        assert touched(calls, "GONE") >= 1, "an unavailable symbol must be retried on the 1st"
        assert now["GONE"]["reason"], "an unavailable symbol must carry a reason"

        # Monday 03-02 (D_G = 02-27): not the 1st any more.
        calls = run(date(2026, 3, 2), full, feb27, {})
        _check_catalog(store, want, "03-02")
        assert touched(calls, "GONE") == 0, "an unavailable symbol was requested on the 2nd"
        assert not store.exists("prices/GONE.parquet"), "a record was invented for a 404 symbol"
