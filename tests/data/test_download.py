"""The downloader: catch-up, refresh, status transitions, budgets and the CLI (spec 5.2, 5.4)."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest
import responses

from portfoliosight.data import download
from portfoliosight.data import store as store_mod
from portfoliosight.data.providers import tiingo, tsp
from portfoliosight.data.providers.base import ProviderError, RateLimited, SymbolMeta
from portfoliosight.data.store import LocalStore
from portfoliosight.data.universe import load_tiers

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SESSIONS = [
    date.fromisoformat(str(s)[:10])
    for s in xcals.get_calendar("XNYS").sessions_in_range("2025-10-01", "2026-12-31")
]
RECORD_START = date(2025, 11, 3)
ENV_NAMES = ("PS_PROVIDER_REQ_PER_HOUR", "PS_PROVIDER_REQ_PER_DAY", "PS_PROVIDER_SYMBOLS_PER_MONTH")


@pytest.fixture(autouse=True)
def default_limits(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


class Clock:
    def __init__(self, day: date, hour: int = 12, minute: int = 5):
        self.now = datetime.combine(day, time(hour, minute), tzinfo=UTC)
        self.slept: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


def _close(symbol: str, day: date) -> float:
    return 50.0 + sum(map(ord, symbol)) % 40 + 0.03 * (day.toordinal() % 400)


class FakeProvider:
    """Deterministic prices through ``available[symbol]``; ids in ``gone`` have no data."""

    name = "tiingo"

    def __init__(self, default_available: date | None = None, gone=(), kind="etf"):
        self.available: dict[str, date] = {}
        self.default_available = default_available
        self.gone, self.kind = set(gone), kind
        self.calls: list[tuple[str, str, date | None]] = []
        self.fail: dict[str, Exception] = {}

    def _through(self, symbol: str) -> date:
        through = self.available.get(symbol, self.default_available)
        assert through is not None, f"test setup: no availability for {symbol}"
        return through

    def fetch_daily(self, symbol, start, end=None):
        self.calls.append(("daily", symbol, start))
        if symbol in self.fail:
            raise self.fail[symbol]
        days = []
        if symbol not in self.gone:
            days = [d for d in SESSIONS if max(start, RECORD_START) <= d <= self._through(symbol)]
        closes = [_close(symbol, d) for d in days]
        return pd.DataFrame(
            {
                "close": closes,
                "adj_close": closes,
                "div_cash": [0.0] * len(days),
                "split_factor": [1.0] * len(days),
            },
            index=pd.DatetimeIndex(pd.to_datetime([d.isoformat() for d in days]), name="date"),
            dtype=float,
        )

    def fetch_meta(self, symbol):
        self.calls.append(("meta", symbol, None))
        if symbol in self.gone:
            return None
        return SymbolMeta(f"{symbol} Fund", RECORD_START, self._through(symbol), self.kind)


def _put_record(store, symbol: str, prices_through: date, adjusted_through: date) -> None:
    days = [d for d in SESSIONS if RECORD_START <= d <= prices_through]
    closes = np.array([_close(symbol, d) for d in days])
    tr = closes / closes[0]
    tr[np.array([d > adjusted_through for d in days])] = np.nan
    seeded = prices_through != adjusted_through
    record = pd.DataFrame(
        {
            "date": pd.to_datetime([d.isoformat() for d in days]),
            "close": closes,
            "tr_index": tr,
            "div_cash": np.nan if seeded else 0.0,
            "split_factor": np.nan if seeded else 1.0,
        }
    )
    store_mod.put_record(store, symbol, record)


def _entry(source="tiingo", status="ok", last=None, adjusted=None, name="Fund", **over) -> dict:
    entry = {
        "name": name,
        "kind": "etf",
        "tier": 2,
        "income": False,
        "source": source,
        "first_date": RECORD_START.isoformat() if last else None,
        "last_date": last.isoformat() if last else None,
        "adjusted_through": adjusted.isoformat() if adjusted else None,
        "status": status,
        "reason": None,
        "fetched_at": None if source == "seed" else "2026-02-01T10:00:00+00:00",
    }
    entry.update(over)
    return entry


def _seed_store(tmp_path, entries: dict[str, dict], records: dict[str, tuple[date, date]]):
    store = LocalStore(tmp_path / "store")
    for symbol, (prices_through, adjusted_through) in records.items():
        _put_record(store, symbol, prices_through, adjusted_through)
    store.put("meta/manifest.json", json.dumps({"symbols": entries}).encode())
    return store


def _manifest(store) -> dict:
    return json.loads(store.get("meta/manifest.json"))["symbols"]


def _listed(store) -> list[str]:
    return [row["id"] for row in json.loads(store.get("meta/symbols.json"))["symbols"]]


def _go(mode, store, provider, clock, symbols, **kwargs) -> tuple[int, list]:
    first = len(provider.calls)
    code = download.run(
        mode,
        store=store,
        providers={"tiingo": provider, **kwargs.pop("more_providers", {})},
        clock=clock,
        sleep=clock.sleep,
        symbols=symbols,
        **kwargs,
    )
    return code, provider.calls[first:]


FEB20, FEB23, FEB26, FEB27 = (date(2026, 2, d) for d in (20, 23, 26, 27))


def test_catch_up_end_to_end_with_the_recorded_fixtures(tmp_path, monkeypatch):
    """catch-up --symbols VTI,VBIAX,SGOV,TSP-G against a LocalStore, HTTP replayed."""
    monkeypatch.setenv("TIINGO_API_KEY", "unit-test-key")
    as_of = "2026-03-31"  # the provider's last row in this replay; D_G for the run below
    rows = {
        "VTI": json.loads((FIXTURES / "provider" / "VTI.json").read_text()),
        "VBIAX": json.loads((FIXTURES / "provider" / "VBIAX.json").read_text()),
    }
    rows["SGOV"] = [r for r in rows["VBIAX"] if r["date"][:10] >= "2020-05-28"]
    metas = {
        "VTI": json.loads((FIXTURES / "provider" / "meta_VTI.json").read_text()),
        "VBIAX": json.loads((FIXTURES / "provider" / "meta_VBIAX.json").read_text()),
        "SGOV": {
            "name": "iShares 0-3 Month Treasury Bond ETF",
            "exchangeCode": "NYSE ARCA",
            "startDate": "2020-05-28",
            "endDate": as_of,
        },
    }
    requested: list[str] = []

    def serve(request):
        path = urlparse(request.url).path
        symbol = path.split("/")[3]
        requested.append(path)
        if path.endswith("/prices"):
            start = parse_qs(urlparse(request.url).query)["startDate"][0]
            body = [r for r in rows[symbol] if start <= r["date"][:10] <= as_of]
        else:
            body = metas[symbol]
        return (200, {"Content-Type": "application/json"}, json.dumps(body))

    store = LocalStore(tmp_path / "store")
    clock = Clock(date(2026, 4, 1))
    provider = tiingo.TiingoProvider()
    with responses.RequestsMock() as mock:
        mock.add_callback(responses.GET, re.compile(r"https://api\.tiingo\.com/.*"), callback=serve)
        mock.add(
            responses.GET,
            tsp.CSV_URL,
            body=(FIXTURES / "tsp" / "tsp-fund-price-history.csv").read_text(),
        )
        code = download.run(
            "catch-up",
            store=store,
            providers={"tiingo": provider, "tsp": tsp.TspProvider()},
            clock=clock,
            sleep=clock.sleep,
            symbols=["VTI", "VBIAX", "SGOV", "TSP-G"],
        )
    assert code == 0
    assert store.list("prices/") == [
        "prices/SGOV.parquet",
        "prices/TSP-G.parquet",
        "prices/VBIAX.parquet",
        "prices/VTI.parquet",
    ]
    # Non-seeded symbols cost two requests each: the history, then the meta.
    assert requested == [
        "/tiingo/daily/VTI/prices",
        "/tiingo/daily/VTI",
        "/tiingo/daily/VBIAX/prices",
        "/tiingo/daily/VBIAX",
        "/tiingo/daily/SGOV/prices",
        "/tiingo/daily/SGOV",
    ]
    entries = _manifest(store)
    assert {s: e["status"] for s, e in entries.items()} == dict.fromkeys(entries, "ok")
    assert {s: e["source"] for s, e in entries.items()} == {
        "VTI": "tiingo",
        "VBIAX": "tiingo",
        "SGOV": "tiingo",
        "TSP-G": "tsp",
    }
    assert entries["VTI"]["name"] == metas["VTI"]["name"] and entries["VTI"]["kind"] == "etf"
    assert entries["VBIAX"]["kind"] == "mutual_fund" and entries["TSP-G"]["kind"] == "tsp"
    assert entries["TSP-G"]["name"] == "G Fund" and entries["TSP-G"]["tier"] == 1
    for symbol, first in (("VTI", "2001-05-31"), ("SGOV", "2020-05-28"), ("TSP-G", "2026-01-02")):
        entry = entries[symbol]
        assert entry["first_date"] == first
        assert entry["last_date"] == entry["adjusted_through"] == as_of
        assert entry["reason"] is None and entry["fetched_at"].startswith("2026-04-01T12:05")
    record = store_mod.get_record(store, "TSP-G")
    assert record["tr_index"].iloc[0] == 1.0 and np.isfinite(record["tr_index"]).all()
    assert sorted(_listed(store)) == ["SGOV", "TSP-G", "VBIAX", "VTI"]
    # The adapter accounted every HTTP attempt itself; tsp.gov is not a budgeted provider.
    ledger = json.loads(store.get("meta/budget.json"))
    assert ledger["days"] == {"2026-04-01": 6}
    assert ledger["months"] == {"2026-04": ["SGOV", "VBIAX", "VTI"]}
    assert provider.before_request is None and provider.retry_on_429 is True


def test_catch_up_refreshes_pending_seeds_and_leaves_served_symbols(tmp_path):
    entries = {
        "SEED": _entry(
            "seed", "pending", FEB20, date(2026, 1, 30), name="Seeded Co", kind="stock", tier=3
        ),
        "BARE": _entry(
            "seed", "pending", FEB20, date(2026, 1, 30), name="BARE", kind="stock", tier=3
        ),
        "OKA": _entry("tiingo", "ok", FEB20, FEB20),
    }
    records = {
        "SEED": (FEB20, date(2026, 1, 30)),
        "BARE": (FEB20, date(2026, 1, 30)),
        "OKA": (FEB20, FEB20),
    }
    store = _seed_store(tmp_path, entries, records)
    provider = FakeProvider(default_available=FEB23)
    code, calls = _go(
        "catch-up", store, provider, Clock(date(2026, 2, 24)), ["OKA", "SEED", "BARE", "NEW"]
    )
    assert code == 0
    # A seeded tail is one request from adjusted_through - 7 days, and one more for its name
    # when it has none; a symbol without a record costs history + meta; OKA is not touched.
    assert calls == [
        ("daily", "SEED", date(2026, 1, 23)),
        ("daily", "BARE", date(2026, 1, 23)),
        ("meta", "BARE", None),
        ("daily", "NEW", download.FULL_HISTORY_START),
        ("meta", "NEW", None),
    ]
    now = _manifest(store)
    assert now["SEED"]["status"] == "ok" and now["SEED"]["source"] == "seed+tiingo"
    assert now["SEED"]["adjusted_through"] == now["SEED"]["last_date"] == "2026-02-23"
    assert now["SEED"]["name"] == "Seeded Co" and now["SEED"]["kind"] == "stock"
    # The meta request names it and keeps the kind the seed recorded.
    assert now["BARE"]["name"] == "BARE Fund" and now["BARE"]["kind"] == "stock"
    assert now["BARE"]["source"] == "seed+tiingo" and now["BARE"]["status"] == "ok"
    assert now["NEW"]["source"] == "tiingo" and now["NEW"]["tier"] == 3
    assert now["NEW"]["name"] == "NEW Fund" and now["NEW"]["kind"] == "etf"
    assert now["OKA"]["adjusted_through"] == "2026-02-20" and now["OKA"]["status"] == "ok"
    seed = store_mod.get_record(store, "SEED")
    assert np.isfinite(seed["tr_index"]).all() and str(seed["date"].iloc[-1])[:10] == "2026-02-23"
    assert seed["div_cash"].iloc[-1] == 0.0 and np.isnan(seed["div_cash"].iloc[0])
    # A second catch-up has nothing left to do.
    again = ["OKA", "SEED", "BARE", "NEW"]
    assert _go("catch-up", store, provider, Clock(date(2026, 2, 24), 13), again) == (0, [])
    # A refresh spends a meta request on a symbol that has no name, and none on one that has.
    store.put(
        "meta/manifest.json",
        json.dumps({"symbols": {**now, "BARE": {**now["BARE"], "name": "BARE"}}}).encode(),
    )
    provider.default_available = FEB26
    code, calls = _go("refresh", store, provider, Clock(FEB27), ["BARE", "SEED"])
    assert code == 0 and calls == [
        ("daily", "BARE", date(2026, 2, 16)),
        ("meta", "BARE", None),
        ("daily", "SEED", date(2026, 2, 16)),
    ]
    assert _manifest(store)["BARE"]["name"] == "BARE Fund"


def test_a_catalog_write_keeps_a_name_another_writer_stored(tmp_path):
    """A walk that loaded an entry without a name does not write over the name another writer
    (the lake sync, the name backfill) stored for it while the walk ran."""
    entries = {"BARE": _entry("tiingo", "ok", FEB20, FEB20, name="BARE")}
    store = _seed_store(tmp_path, entries, {"BARE": (FEB20, FEB20)})

    class NamingProvider(FakeProvider):
        def fetch_daily(self, symbol, start, end=None):
            stored = json.loads(store.get("meta/manifest.json"))
            stored["symbols"]["BARE"]["name"] = "Bare Holdings Inc."
            store.put("meta/manifest.json", json.dumps(stored).encode())
            return super().fetch_daily(symbol, start, end)

        def fetch_meta(self, symbol):
            self.calls.append(("meta", symbol, None))
            return None

    provider = NamingProvider(default_available=FEB23)
    code, _ = _go("refresh", store, provider, Clock(date(2026, 2, 24)), ["BARE"])
    assert code == 0
    assert _manifest(store)["BARE"]["name"] == "Bare Holdings Inc."
    listed = json.loads(store.get("meta/symbols.json"))["symbols"]
    assert [row["name"] for row in listed] == ["Bare Holdings Inc."]


def test_empty_tail_makes_a_served_symbol_unavailable_and_keeps_its_record(tmp_path):
    store = _seed_store(
        tmp_path, {"OKA": _entry("tiingo", "ok", FEB20, FEB20)}, {"OKA": (FEB20, FEB20)}
    )
    before = store.get("prices/OKA.parquet")
    provider = FakeProvider(gone={"OKA"})
    code, calls = _go("refresh", store, provider, Clock(date(2026, 2, 24)), ["OKA"])
    assert code == 0 and len(calls) == 1
    entry = _manifest(store)["OKA"]
    assert entry["status"] == "unavailable" and entry["reason"] == "no data since 2026-02-20"
    assert store.get("prices/OKA.parquet") == before and _listed(store) == []
    # Not the 1st: left alone. On the 1st with data again: its tail is spliced and it is served.
    assert _go("refresh", store, provider, Clock(date(2026, 2, 25)), ["OKA"])[1] == []
    provider.gone.clear()
    provider.available["OKA"] = FEB27
    code, calls = _go("refresh", store, provider, Clock(date(2026, 3, 1)), ["OKA"])
    assert calls == [("daily", "OKA", date(2026, 2, 13))]
    assert _manifest(store)["OKA"]["status"] == "ok"


def test_record_missing_from_the_store_is_fetched_in_full(tmp_path):
    store = _seed_store(tmp_path, {"LOST": _entry("tiingo", "ok", FEB20, FEB20)}, {})
    provider = FakeProvider(default_available=FEB23)
    code, calls = _go("refresh", store, provider, Clock(date(2026, 2, 24)), ["LOST"])
    assert code == 0 and calls == [("daily", "LOST", download.FULL_HISTORY_START)]
    assert store.exists("prices/LOST.parquet")
    assert _manifest(store)["LOST"]["adjusted_through"] == "2026-02-23"


def test_daily_budget_stops_cleanly_and_the_next_day_continues(tmp_path, monkeypatch, caplog):
    for name, value in zip(ENV_NAMES, ("50", "3", "50"), strict=True):
        monkeypatch.setenv(name, value)
    symbols = [f"S{i}" for i in range(1, 6)]
    behind = date(2026, 3, 6)
    store = _seed_store(
        tmp_path,
        {s: _entry("tiingo", "stale", behind, behind) for s in symbols},
        dict.fromkeys(symbols, (behind, behind)),
    )
    provider = FakeProvider(default_available=date(2026, 3, 13))
    caplog.set_level(logging.INFO)
    code, calls = _go("refresh", store, provider, Clock(date(2026, 3, 14)), symbols)
    assert code == 0 and [c[1] for c in calls] == ["S1", "S2", "S3"]
    assert "daily budget spent" in caplog.text
    assert sorted(_listed(store)) == ["S1", "S2", "S3"]
    code, calls = _go("refresh", store, provider, Clock(date(2026, 3, 14), 18), symbols)
    assert code == 0 and calls == []
    code, calls = _go("refresh", store, provider, Clock(date(2026, 3, 15)), symbols)
    assert code == 0 and [c[1] for c in calls] == ["S4", "S5"]
    assert sorted(_listed(store)) == symbols


class _SlowProvider(FakeProvider):
    """Each daily fetch takes ``minutes`` on ``clock``."""

    def __init__(self, clock: Clock, minutes: int, **kwargs):
        super().__init__(**kwargs)
        self.clock, self.minutes = clock, minutes

    def fetch_daily(self, symbol, start, end=None):
        self.clock.now += timedelta(minutes=self.minutes)
        return super().fetch_daily(symbol, start, end)


def test_deadline_stops_the_walk_between_symbols_and_the_next_run_continues(tmp_path, caplog):
    symbols = [f"S{i}" for i in range(1, 6)]
    behind = date(2026, 3, 6)
    store = _seed_store(
        tmp_path,
        {s: _entry("tiingo", "stale", behind, behind) for s in symbols},
        dict.fromkeys(symbols, (behind, behind)),
    )
    clock = Clock(date(2026, 3, 14), 12, 5)
    provider = _SlowProvider(clock, 10, default_available=date(2026, 3, 13))
    report = download.RunReport()
    caplog.set_level(logging.INFO)
    # S3 starts at 12:25, before the deadline, and runs past it: it is finished, not cut off.
    deadline = clock.now + timedelta(minutes=25)
    code, calls = _go("refresh", store, provider, clock, symbols, report=report, deadline=deadline)
    assert code == 0 and report.exit_code == 0
    assert [c[1] for c in calls] == ["S1", "S2", "S3"]
    assert report.stopped == download.DEADLINE_REACHED
    assert "deadline" in caplog.text and "stopping at S4" in caplog.text
    assert sorted(_listed(store)) == ["S1", "S2", "S3"]
    assert _manifest(store)["S3"]["adjusted_through"] == "2026-03-13"
    report = download.RunReport()
    later = clock.now + timedelta(days=1)
    code, calls = _go("refresh", store, provider, clock, symbols, report=report, deadline=later)
    assert code == 0 and [c[1] for c in calls] == ["S4", "S5"] and report.stopped is None
    assert sorted(_listed(store)) == symbols


def test_a_deadline_already_passed_visits_nothing_and_still_writes_the_catalog(tmp_path):
    behind = date(2026, 3, 6)
    store = _seed_store(
        tmp_path, {"S1": _entry("tiingo", "stale", behind, behind)}, {"S1": (behind, behind)}
    )
    clock = Clock(date(2026, 3, 14))
    provider = FakeProvider(default_available=date(2026, 3, 13))
    report = download.RunReport()
    code, calls = _go("refresh", store, provider, clock, ["S1"], report=report, deadline=clock.now)
    assert code == 0 and calls == [] and report.stopped == download.DEADLINE_REACHED
    assert store.exists("meta/symbols.json")


def test_monthly_budget_skips_new_symbols_but_refreshes_seen_ones(tmp_path, monkeypatch, caplog):
    for name, value in zip(ENV_NAMES, ("50", "50", "2"), strict=True):
        monkeypatch.setenv(name, value)
    symbols = ["S1", "S2", "S3", "S4"]
    behind = date(2026, 3, 6)
    store = _seed_store(
        tmp_path,
        {s: _entry("tiingo", "stale", behind, behind) for s in symbols},
        dict.fromkeys(symbols, (behind, behind)),
    )
    provider = FakeProvider(default_available=date(2026, 3, 13))
    caplog.set_level(logging.INFO)
    order = ["S3", "S1", "S2", "S4"]
    code, calls = _go("refresh", store, provider, Clock(date(2026, 3, 14)), order)
    assert code == 0 and [c[1] for c in calls] == ["S3", "S1"]
    assert caplog.text.count("monthly budget spent") == 1
    provider.default_available = date(2026, 3, 16)
    code, calls = _go(
        "refresh", store, provider, Clock(date(2026, 3, 17)), ["S2", "S4", "S1", "S3"]
    )
    assert code == 0 and [c[1] for c in calls] == ["S1", "S3"]


def test_catalog_is_rewritten_after_each_tier_group(tmp_path):
    behind = date(2026, 3, 6)
    tiers = {
        "T1": (1, False),
        "INC": (2, True),
        "INC2": (2, True),
        "REST": (2, False),
        "STK": (3, False),
    }
    entries = {
        s: _entry("tiingo", "stale", behind, behind, tier=t, income=i)
        for s, (t, i) in tiers.items()
    }
    inner = _seed_store(tmp_path, entries, dict.fromkeys(tiers, (behind, behind)))

    class Recording:
        def __init__(self):
            self.catalog_writes: list[list[str]] = []

        def put(self, key, data):
            inner.put(key, data)
            if key == "meta/symbols.json":
                self.catalog_writes.append([row["id"] for row in json.loads(data)["symbols"]])

        def __getattr__(self, name):
            return getattr(inner, name)

    store = Recording()
    provider = FakeProvider(default_available=date(2026, 3, 13))
    code, _ = _go("refresh", store, provider, Clock(date(2026, 3, 14)), list(tiers))
    assert code == 0
    assert store.catalog_writes == [
        ["T1"],
        ["INC", "INC2", "T1"],
        ["INC", "INC2", "REST", "T1"],
        ["INC", "INC2", "REST", "STK", "T1"],
    ]


def test_provider_errors_are_counted_and_the_run_goes_on(tmp_path, caplog):
    behind = date(2026, 3, 6)
    symbols = ["BAD", "GOOD", "TSP-G"]
    store = _seed_store(
        tmp_path,
        {s: _entry("tiingo", "stale", behind, behind) for s in symbols[:2]},
        dict.fromkeys(symbols[:2], (behind, behind)),
    )
    provider = FakeProvider(default_available=date(2026, 3, 13))
    provider.fail["BAD"] = ProviderError("Tiingo answered 500 for BAD")
    code, calls = _go("refresh", store, provider, Clock(date(2026, 3, 14)), symbols)
    assert code == 1 and [c[1] for c in calls] == ["BAD", "GOOD"]
    assert "BAD: ProviderError: Tiingo answered 500 for BAD" in caplog.text
    assert "no 'tsp' provider was given for TSP-G" in caplog.text
    now = _manifest(store)
    assert now["GOOD"]["status"] == "ok" and now["BAD"]["status"] == "stale"
    assert "TSP-G" not in now


def test_refused_rows_record_nothing_and_are_asked_for_again(tmp_path):
    store = LocalStore(tmp_path / "store")

    class Corrupt(FakeProvider):
        broken = True
        row = 3

        def fetch_daily(self, symbol, start, end=None):
            frame = super().fetch_daily(symbol, start, end)
            if self.broken:
                frame.iloc[self.row, frame.columns.get_loc("close")] = float("inf")
            return frame

    provider = Corrupt(default_available=FEB23)
    code, calls = _go("catch-up", store, provider, Clock(date(2026, 2, 24)), ["NEW"])
    assert code == 1 and len(calls) == 1
    assert _manifest(store) == {} and store.list("prices/") == [] and _listed(store) == []
    # Not the 1st of a month: the symbol is still asked for, and served once its rows are sound.
    provider.broken = False
    code, calls = _go("catch-up", store, provider, Clock(date(2026, 2, 25)), ["NEW"])
    assert code == 0 and [c[0] for c in calls] == ["daily", "meta"]
    assert _manifest(store)["NEW"]["status"] == "ok"
    # The same corruption in a tail leaves the stored record and its dates untouched.
    provider.broken, provider.row = True, -1
    provider.default_available = FEB27
    before = store.get("prices/NEW.parquet")
    code, _ = _go("refresh", store, provider, Clock(date(2026, 2, 28)), ["NEW"])
    assert code == 1 and store.get("prices/NEW.parquet") == before
    assert _manifest(store)["NEW"]["adjusted_through"] == "2026-02-23"


def test_failed_upload_leaves_no_entry_and_the_next_run_retries(tmp_path):
    inner = LocalStore(tmp_path / "store")

    class Flaky(LocalStore):
        failing = True

        def put(self, key: str, data: bytes) -> None:
            if self.failing and key.startswith("prices/"):
                raise OSError("upload failed")
            super().put(key, data)

    store = Flaky(inner.root)
    provider = FakeProvider(default_available=FEB23)
    # The failed write is the symbol's error: the run goes on and ends with status 1.
    code, _ = _go("catch-up", store, provider, Clock(date(2026, 2, 24)), ["NEW"])
    assert code == 1
    # The catalog was still written on the way out, and it does not name the symbol.
    assert _manifest(store) == {} and _listed(store) == []
    store.failing = False
    code, calls = _go("catch-up", store, provider, Clock(date(2026, 2, 25)), ["NEW"])
    assert code == 0 and [c[0] for c in calls] == ["daily", "meta"]
    assert _manifest(store)["NEW"]["status"] == "ok" and store.exists("prices/NEW.parquet")


def test_persistent_rate_limit_stops_the_run_cleanly(tmp_path, caplog):
    behind = date(2026, 3, 6)
    symbols = ["S1", "S2", "S3"]
    store = _seed_store(
        tmp_path,
        {s: _entry("tiingo", "stale", behind, behind) for s in symbols},
        dict.fromkeys(symbols, (behind, behind)),
    )
    provider = FakeProvider(default_available=date(2026, 3, 13))
    provider.fail["S2"] = RateLimited("Tiingo answered 429 for S2")
    code, calls = _go("refresh", store, provider, Clock(date(2026, 3, 14)), symbols)
    assert code == 0 and [c[1] for c in calls] == ["S1", "S2"]
    assert "rate limit persists" in caplog.text
    assert _manifest(store)["S1"]["status"] == "ok"


def test_meta_request_stopped_by_the_budget_keeps_the_record(tmp_path, monkeypatch):
    for name, value in zip(ENV_NAMES, ("50", "1", "50"), strict=True):
        monkeypatch.setenv(name, value)
    store = LocalStore(tmp_path / "store")
    provider = FakeProvider(default_available=FEB23)
    code, calls = _go("catch-up", store, provider, Clock(date(2026, 2, 24)), ["NEW"])
    assert code == 0 and calls == [("daily", "NEW", download.FULL_HISTORY_START)]
    entry = _manifest(store)["NEW"]
    assert entry["name"] == "NEW" and entry["status"] == "ok" and store.exists("prices/NEW.parquet")
    # The next catch-up makes up the missing meta request, and only that.
    provider.kind = "mutual_fund"
    code, calls = _go("catch-up", store, provider, Clock(date(2026, 2, 25)), ["NEW"])
    assert code == 0 and calls == [("meta", "NEW", None)]
    entry = _manifest(store)["NEW"]
    assert entry["name"] == "NEW Fund" and entry["kind"] == "mutual_fund"
    assert _go("catch-up", store, provider, Clock(date(2026, 2, 26)), ["NEW"])[1] == []


def test_default_set_is_the_universe_priority_order(tmp_path):
    store = LocalStore(tmp_path / "store")
    provider = FakeProvider(default_available=FEB23)
    tsp_provider = FakeProvider(default_available=FEB20, kind="tsp")
    tsp_provider.name = "tsp"
    clock = Clock(date(2026, 2, 24))
    code = download.run(
        "catch-up",
        store=store,
        providers={"tiingo": provider, "tsp": tsp_provider},
        clock=clock,
        sleep=clock.sleep,
        tiers=(1,),
    )
    assert code == 0
    universe = load_tiers()
    fetched = [c[1] for c in provider.calls if c[0] == "daily"]
    assert fetched == [s for s in universe.tier1 if not s.startswith("TSP-")]
    assert [c[1] for c in tsp_provider.calls if c[0] == "daily"] == list(universe.tier1[23:])
    now = _manifest(store)
    assert len(now) == 39 and now["BND"]["income"] is True and now["BND"]["tier"] == 1
    assert now["EFA"]["status"] == "ok" and now["TSP-G"]["source"] == "tsp"
    assert now["TSP-G"]["kind"] == "tsp" and now["VTI"]["kind"] == "etf"
    # 23 funds cost two requests each; the 16 TSP funds are not budgeted.
    assert json.loads(store.get("meta/budget.json"))["days"] == {"2026-02-24": 46}
    assert len(_listed(store)) == 39  # every tier 1 fund is served
    assert {entry["reason"] for entry in now.values()} == {None}


def test_a_fund_whose_data_ended_is_not_served_and_the_universe_says_why(tmp_path, monkeypatch):
    """FIENX (tier 2) was converted to an ETF: the catalog keeps it with the reason, unserved."""
    for name, value in zip(ENV_NAMES, ("2000", "5000", "1000"), strict=True):
        monkeypatch.setenv(name, value)  # room for the whole of tier 2 in one run
    universe = load_tiers()
    assert "FIENX" in universe.tier2 and "FIENX" not in universe.tier1
    store = LocalStore(tmp_path / "store")
    provider = FakeProvider(default_available=FEB23)
    provider.available["FIENX"] = date(2025, 12, 30)  # its data ended; the universe says why
    clock = Clock(date(2026, 2, 24))
    code = download.run(
        "catch-up",
        store=store,
        providers={"tiingo": provider},
        clock=clock,
        sleep=clock.sleep,
        tiers=(2,),
    )
    assert code == 0 and clock.slept == []
    now = _manifest(store)
    assert set(now) == set(universe.tier2) - set(universe.tier1) and len(now) == 317 - 23
    assert now["FIENX"]["status"] == "stale" and now["FIENX"]["tier"] == 2
    assert now["FIENX"]["reason"] == "converted to an ETF; no data since 2025-12-30"
    assert [symbol for symbol, entry in now.items() if entry["status"] != "ok"] == ["FIENX"]
    assert sorted(_listed(store)) == sorted(set(now) - {"FIENX"})
    # A later refresh with an explicit set (no universe at hand) keeps the note.
    code = download.run(
        "refresh",
        store=store,
        providers={"tiingo": provider},
        clock=clock,
        sleep=clock.sleep,
        symbols=["FIENX"],
    )
    assert code == 0
    assert _manifest(store)["FIENX"]["reason"] == "converted to an ETF; no data since 2025-12-30"


def test_measure_limits_through_run(tmp_path):
    store = LocalStore(tmp_path / "store")

    class Probe(FakeProvider):
        retry_on_429 = True
        before_request: Any = None

        def fetch_meta(self, symbol):
            assert self.retry_on_429 is False
            self.before_request(symbol)
            return super().fetch_meta(symbol)

    provider = Probe(default_available=FEB23)
    clock = Clock(date(2026, 3, 14))
    code = download.run(
        "measure-limits",
        store=store,
        providers={"tiingo": provider},
        clock=clock,
        sleep=clock.sleep,
    )
    assert code == 0 and [c[:2] for c in provider.calls] == [("meta", "VTI")] * 60
    assert provider.retry_on_429 is True and provider.before_request is None
    limits = json.loads(store.get("meta/provider_limits.json"))
    assert limits["tier"] == "at least 60/10 min" and limits["measured_on"] == "2026-03-14"
    assert json.loads(store.get("meta/budget.json"))["days"] == {"2026-03-14": 60}
    assert not store.exists("meta/manifest.json")
    assert (
        download.run("measure-limits", store=store, providers={}, clock=clock, sleep=clock.sleep)
        == 2
    )
    with pytest.raises(ValueError, match="mode must be one of"):
        download.run("sideways", store=store, providers={}, clock=clock, sleep=clock.sleep)


def test_measure_limits_stopped_by_the_daily_budget_exits_1(tmp_path, monkeypatch):
    monkeypatch.setenv("PS_PROVIDER_REQ_PER_DAY", "5")
    store = LocalStore(tmp_path / "store")
    provider = FakeProvider(default_available=FEB23)
    clock = Clock(date(2026, 3, 14))
    code = download.run(
        "measure-limits",
        store=store,
        providers={"tiingo": provider},
        clock=clock,
        sleep=clock.sleep,
        symbols=["SPY"],
    )
    assert code == 1 and [c[:2] for c in provider.calls] == [("meta", "SPY")] * 5
    assert not store.exists("meta/provider_limits.json")


def test_cli(tmp_path, monkeypatch, capsys):
    made: list[FakeProvider] = []

    def fake_tiingo():
        made.append(FakeProvider(default_available=date(2020, 1, 1)))
        return made[-1]

    monkeypatch.setattr(tiingo, "TiingoProvider", fake_tiingo)
    monkeypatch.setattr(tsp, "TspProvider", lambda: FakeProvider(default_available=FEB20))
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: None)
    monkeypatch.setenv("PS_STORE", "local")
    monkeypatch.setenv("PS_LOCAL_STORE_DIR", str(tmp_path / "store"))
    # The CLI waits with the real time.sleep: keep this run far below every limit.
    monkeypatch.setenv("PS_PROVIDER_REQ_PER_HOUR", "100000")
    monkeypatch.setenv("PS_PROVIDER_REQ_PER_DAY", "100000")
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    store = LocalStore(tmp_path / "store")

    assert download.main(["--mode", "catch-up", "--symbols", "vti, agg,AAAU"]) == 0
    assert [c[:2] for c in made[-1].calls] == [
        ("daily", "VTI"),
        ("daily", "AGG"),
        ("daily", "AAAU"),
    ]
    now = _manifest(store)
    # No rows after 2025-11-03 from this provider: no data, and tiers come from the universe.
    assert {s: (e["status"], e["tier"], e["income"]) for s, e in now.items()} == {
        "VTI": ("unavailable", 1, False),
        "AGG": ("unavailable", 1, True),
        "AAAU": ("unavailable", 3, False),
    }
    assert now["AAAU"]["kind"] == "stock"

    assert download.main(["--mode", "refresh", "--tiers", "3"]) == 0
    universe = load_tiers()
    wanted = list(universe.tier3_only()[:130])
    assert [c[1] for c in made[-1].calls if c[0] == "daily"] == [s for s in wanted if s != "AAAU"]

    # Measured last: the limits file it writes (45/900/450) would win over the environment.
    assert download.main(["--mode", "measure-limits", "--symbols", "spy"]) == 0
    assert {c[:2] for c in made[-1].calls} == {("meta", "SPY")}

    monkeypatch.delenv("PS_LOCAL_STORE_DIR")
    assert download.main(["--mode", "refresh"]) == 2
    assert "download not run" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        download.main(["--mode", "sideways"])


class _Raising(FakeProvider):
    """A provider whose every call raises something that is not a ``ProviderError``."""

    def __init__(self, name: str, error: Exception):
        super().__init__(default_available=date(2026, 3, 13))
        self.name, self.error = name, error

    def fetch_daily(self, symbol, start, end=None):
        self.calls.append(("daily", symbol, start))
        raise self.error

    def fetch_meta(self, symbol):
        self.calls.append(("meta", symbol, None))
        raise self.error


def test_report_lists_refreshed_tiers_and_failed_symbols(tmp_path):
    behind = date(2026, 3, 6)
    store = _seed_store(
        tmp_path,
        {
            "BAD": _entry("tiingo", "stale", behind, behind),
            "GOOD": _entry("tiingo", "stale", behind, behind, tier=1),
        },
        {"BAD": (behind, behind), "GOOD": (behind, behind)},
    )
    provider = FakeProvider(default_available=date(2026, 3, 13))
    provider.fail["BAD"] = ProviderError("Tiingo answered 500 for BAD")
    report = download.RunReport()
    code, _ = _go(
        "refresh", store, provider, Clock(date(2026, 3, 14)), ["BAD", "GOOD", "NEW"], report=report
    )
    assert code == 1 and report.exit_code == 1 and report.stopped is None
    assert report.refreshed == {1: 1, 3: 1}
    assert report.errors == [
        {
            "symbol": "BAD",
            "provider": "tiingo",
            "error": "ProviderError: Tiingo answered 500 for BAD",
        }
    ]


def test_any_exception_from_a_provider_is_a_failed_fetch_of_that_symbol(tmp_path, caplog):
    recent = date(2026, 3, 12)
    store = _seed_store(
        tmp_path,
        {"VTI": _entry("tiingo", "ok", recent, recent)},
        {"VTI": (recent, recent)},
    )
    provider = _Raising("tiingo", RuntimeError("connection dropped"))
    report = download.RunReport()
    code, calls = _go("refresh", store, provider, Clock(date(2026, 3, 14)), ["VTI", "NEW"])
    assert code == 1 and [call[1] for call in calls] == ["VTI", "NEW"]
    _go("refresh", store, provider, Clock(date(2026, 3, 14)), ["VTI"], report=report)
    assert report.errors[0]["error"] == (
        "ProviderError: tiingo fetch failed: RuntimeError: connection dropped"
    )
    # A Tiingo failure leaves the status to the dates: one session behind is still served.
    assert _manifest(store)["VTI"]["status"] == "ok" and "NEW" not in _manifest(store)


def test_failed_tsp_fetch_marks_due_funds_stale_until_a_fetch_succeeds(tmp_path):
    recent, d_g = date(2026, 3, 12), date(2026, 3, 13)
    entries = {
        "TSP-G": _entry("tsp", "ok", recent, recent, kind="tsp", tier=1),
        "TSP-C": _entry("tsp", "ok", d_g, d_g, kind="tsp", tier=1),
        "VTI": _entry("tiingo", "ok", recent, recent),
    }
    store = _seed_store(
        tmp_path,
        entries,
        {s: (e_last, e_last) for s, e_last in (("TSP-G", recent), ("TSP-C", d_g), ("VTI", recent))},
    )
    clock = Clock(date(2026, 3, 14))
    broken = {"tsp": _Raising("tsp", RuntimeError("tsp.gov answered 503"))}
    tiingo_ok = FakeProvider(default_available=d_g)
    report = download.RunReport()
    code, _ = _go(
        "refresh",
        store,
        tiingo_ok,
        clock,
        ["TSP-G", "TSP-C", "TSP-L2030", "VTI"],
        more_providers=broken,
        report=report,
    )
    now = _manifest(store)
    assert code == 1
    assert now["TSP-G"]["status"] == "stale"
    assert now["TSP-G"]["reason"] == "corporate actions not yet verified after 2026-03-12"
    assert now["TSP-C"]["status"] == "ok"  # current at D_G: no fetch was due, none failed
    assert now["VTI"]["status"] == "ok" and "TSP-L2030" not in now
    assert [error["symbol"] for error in report.errors] == ["TSP-G", "TSP-L2030"]
    assert "TSP-G" not in _listed(store)
    # A later pass over other symbols rewrites the catalog and keeps the mark.
    _go("refresh", store, tiingo_ok, clock, ["VTI"])
    assert _manifest(store)["TSP-G"]["status"] == "stale"
    # The fetch that succeeds restores it.
    working = FakeProvider(default_available=d_g)
    working.name = "tsp"
    _go("refresh", store, tiingo_ok, clock, ["TSP-G"], more_providers={"tsp": working})
    restored = _manifest(store)["TSP-G"]
    assert restored["status"] == "ok" and restored["reason"] is None
    assert restored["last_date"] == d_g.isoformat()
