"""The one-time name backfill (spec 5.4): the lake's names first, then Tiingo's within budget."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from portfoliosight.data import budget
from portfoliosight.data import lake as lake_mod
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.providers.base import ProviderError, RateLimited, SymbolMeta
from portfoliosight.data.store import LocalStore
from tests.data.test_sync_lake import _load_script

backfill_names = _load_script("backfill_names")
MONTH = "2026-10"
ENV_NAMES = ("PS_PROVIDER_REQ_PER_HOUR", "PS_PROVIDER_REQ_PER_DAY", "PS_PROVIDER_SYMBOLS_PER_MONTH")


@pytest.fixture(autouse=True)
def limits(monkeypatch):
    for name, value in zip(ENV_NAMES, ("2", "3", "450"), strict=True):
        monkeypatch.setenv(name, value)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 15, 18, 10, tzinfo=UTC)
        self.slept: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


class Provider:
    """Tiingo's meta, accounting each request through ``before_request`` as the adapter does."""

    def __init__(self, names: dict[str, str | None], fail: frozenset[str] = frozenset()):
        self.names, self.fail = names, fail
        self.before_request = None
        self.asked: list[str] = []

    def fetch_meta(self, symbol):
        if self.before_request is not None:
            self.before_request(symbol)
        self.asked.append(symbol)
        if symbol in self.fail:
            raise ProviderError(f"Tiingo answered 500 for {symbol}")
        name = self.names.get(symbol)
        return None if name is None else SymbolMeta(name, None, None, "etf")


def _entry(name: str, source: str = "seed+tiingo", status: str = "ok", kind="etf") -> dict:
    return {
        "name": name,
        "kind": kind,
        "tier": 3,
        "source": source,
        "first_date": "2026-01-02",
        "last_date": "2026-10-14",
        "adjusted_through": "2026-10-14",
        "status": status,
    }


@pytest.fixture
def lake(tmp_path):
    root = tmp_path / "lake"
    (root / lake_mod.FUNDAMENTALS_DIR).mkdir(parents=True)
    (root / lake_mod.FUNDAMENTALS_DIR / "QQQ.json").write_text(
        json.dumps({"General": {"Name": "Invesco QQQ Trust, Series 1"}})
    )
    (root / lake_mod.FUNDAMENTALS_DIR / "AAPL.json").write_text(
        json.dumps({"General": {"Name": "Apple Inc."}})
    )
    (root / "symbols").mkdir()
    (root / lake_mod.LISTING_FILE).write_text(
        "Code,Name,Country,Exchange,Currency,Type,Isin\nSTALE,Stale Fund ETF,USA,NYSE,USD,ETF,\n"
    )
    return root


@pytest.fixture
def store(tmp_path):
    store = LocalStore(tmp_path / "store")
    entries = {
        "QQQ": _entry("QQQ"),  # the lake names it
        "STALE": _entry("STALE", status="stale"),  # the lake names it, served or not
        "AAPL": _entry("AAPL", source="lake", kind="stock"),  # the sync's: left alone
        "VTI": _entry("Vanguard Total Stock Market ETF"),  # named already
        "T1": _entry("T1"),  # Tiingo names these three
        "T2": _entry(""),
        "T3": _entry("T3"),
        "NEWB": _entry("NEWB"),  # not fetched this month: left to the nightly
        "PEND": _entry("PEND", source="seed", status="pending"),  # not served: not asked
        "TSP-G": _entry("TSP-G", source="tsp"),  # not Tiingo's
    }
    store_mod.put_json(store, manifest_mod.MANIFEST_KEY, {"symbols": entries})
    fetched = ["QQQ", "STALE", "T1", "T2", "T3", "VTI"]
    store_mod.put_json(
        store, budget.BUDGET_KEY, {"hours": {}, "days": {}, "months": {MONTH: fetched}}
    )
    return store


def _run(store, lake, provider, clock, **kwargs) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = backfill_names.backfill(
        store=store,
        lake=lake,
        provider=provider,
        clock=clock,
        sleep=clock.sleep,
        emit=lines.append,
        **kwargs,
    )
    return code, lines


def _names(store) -> dict[str, str]:
    stored = store_mod.get_json(store, manifest_mod.MANIFEST_KEY)["symbols"]
    return {symbol: entry["name"] for symbol, entry in stored.items()}


def test_lake_names_first_then_tiingo_within_the_ledger(lake, store):
    clock = Clock()
    provider = Provider({"T1": "Tee One Fund", "T2": " Tee Two ETF ", "T3": "T3"})
    code, lines = _run(store, lake, provider, clock)
    assert code == 0, lines
    names = _names(store)
    assert names["QQQ"] == "Invesco QQQ Trust, Series 1" and names["STALE"] == "Stale Fund ETF"
    assert names["AAPL"] == "AAPL"  # the lake sync names its own entries
    assert names["VTI"] == "Vanguard Total Stock Market ETF"
    assert names["T1"] == "Tee One Fund" and names["T2"] == "Tee Two ETF"
    assert names["T3"] == "T3"  # Tiingo had no name either: the ticker stays
    assert names["NEWB"] == "NEWB" and names["PEND"] == "PEND" and names["TSP-G"] == "TSP-G"
    assert provider.asked == ["T1", "T2", "T3"]
    # Two requests an hour: the third waited for the next hour; all three are in the ledger.
    assert clock.slept == [50 * 60.0]
    ledger = store_mod.get_json(store, budget.BUDGET_KEY)
    assert ledger["days"] == {"2026-10-15": 3}
    assert ledger["hours"] == {"2026-10-15T18": 2, "2026-10-15T19": 1}
    assert "8 entries the lake sync does not keep have no name" in lines
    assert any("1 not fetched this month are left to the nightly" in line for line in lines)
    listed = {
        r["id"]: r["name"] for r in store_mod.get_json(store, manifest_mod.SYMBOLS_KEY)["symbols"]
    }
    assert listed["QQQ"] == "Invesco QQQ Trust, Series 1" and listed["T1"] == "Tee One Fund"
    assert provider.before_request is None  # the hook is handed back
    # The day's three requests are spent: a rerun today asks nothing; tomorrow it asks only for
    # what is still unnamed.
    provider.asked.clear()
    code, lines = _run(store, lake, provider, clock)
    assert code == 0 and provider.asked == [] and any("day budget spent" in x for x in lines)
    clock.now += timedelta(days=1)
    assert _run(store, lake, provider, clock)[0] == 0
    assert provider.asked == ["T3"]


def test_a_spent_day_stops_cleanly_and_keeps_the_names_found(lake, store):
    store_mod.put_json(
        store,
        budget.BUDGET_KEY,
        {"hours": {}, "days": {"2026-10-15": 2}, "months": {MONTH: ["T1", "T2", "T3"]}},
    )
    provider = Provider({"T1": "Tee One Fund", "T2": "Tee Two ETF"})
    code, lines = _run(store, lake, provider, Clock())
    assert code == 0 and provider.asked == ["T1"]
    assert any("day budget spent at T2" in line for line in lines)
    names = _names(store)
    assert names["T1"] == "Tee One Fund" and names["T2"] == ""
    assert store_mod.get_json(store, budget.BUDGET_KEY)["days"] == {"2026-10-15": 3}


def test_a_failed_request_is_reported_and_the_run_goes_on(lake, store):
    provider = Provider({"T2": "Tee Two ETF"}, fail=frozenset({"T1"}))
    code, lines = _run(store, lake, provider, Clock())
    assert code == 1 and provider.asked == ["T1", "T2", "T3"]
    assert "T1: Tiingo answered 500 for T1" in lines
    assert _names(store)["T2"] == "Tee Two ETF"


def test_dry_run_and_lake_only_ask_nothing(lake, store):
    before = store.get(manifest_mod.MANIFEST_KEY)
    provider = Provider({"T1": "Tee One Fund"})
    code, lines = _run(store, lake, provider, Clock(), dry_run=True)
    assert code == 0 and provider.asked == [] and "dry run: nothing written" in lines
    assert store.get(manifest_mod.MANIFEST_KEY) == before
    code, lines = _run(store, lake, None, Clock())
    assert code == 0 and _names(store)["QQQ"] == "Invesco QQQ Trust, Series 1"
    assert _names(store)["T1"] == "T1"


def test_a_name_written_meanwhile_is_kept(lake, store):
    stored = store_mod.get_json(store, manifest_mod.MANIFEST_KEY)
    stored["symbols"]["T1"]["name"] = "Named Meanwhile Fund"
    stored["symbols"]["T2"]["source"] = "lake"
    store_mod.put_json(store, manifest_mod.MANIFEST_KEY, stored)
    named = backfill_names.write_names(
        store, {"T1": "Tee One Fund", "T2": "Tee Two ETF", "T3": "Tee Three"}, Clock()()
    )
    assert named == ["T3"]
    names = _names(store)
    assert (
        names["T1"] == "Named Meanwhile Fund" and names["T2"] == "" and names["T3"] == "Tee Three"
    )


@pytest.mark.parametrize(
    ("error", "says"),
    [
        (RateLimited("Tiingo answered 429 for T1"), "Tiingo rate limit at T1"),
        (store_mod.ConcurrentUpdate("meta/budget.json kept changing"), "kept changing at T1"),
    ],
)
def test_a_rate_limit_or_a_busy_ledger_stops_cleanly(lake, store, error, says):
    class Stopping(Provider):
        def fetch_meta(self, symbol):
            raise error

    provider = Stopping({})
    code, lines = _run(store, lake, provider, Clock())
    assert code == 0 and any(says in line for line in lines)
    assert provider.before_request is None
    assert _names(store)["QQQ"] == "Invesco QQQ Trust, Series 1"  # the lake's names are kept


def test_main_reads_the_store_from_the_environment(lake, store, tmp_path, monkeypatch):
    monkeypatch.setenv("PS_STORE", "local")
    monkeypatch.setenv("PS_LOCAL_STORE_DIR", str(tmp_path / "store"))
    assert backfill_names.main(["--lake", str(lake), "--lake-only", "--dry-run"]) == 0
    assert _names(store)["QQQ"] == "QQQ"  # dry run
    assert backfill_names.main(["--lake", str(lake), "--lake-only"]) == 0
    assert _names(store)["QQQ"] == "Invesco QQQ Trust, Series 1"
    monkeypatch.setenv("PS_STORE", "nowhere")
    assert backfill_names.main(["--lake-only"]) == 2
