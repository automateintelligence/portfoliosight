"""Budget ledger and the limits probe (spec 5.2, 5.4; A-PS-06 legs 1, 2, 4, 5, 6)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from portfoliosight.data import budget, limits
from portfoliosight.data.providers.base import RateLimited, SymbolMeta
from portfoliosight.data.store import LocalStore

ENV_NAMES = ("PS_PROVIDER_REQ_PER_HOUR", "PS_PROVIDER_REQ_PER_DAY", "PS_PROVIDER_SYMBOLS_PER_MONTH")


class Clock:
    def __init__(self, *start):
        self.now = datetime(*start, tzinfo=UTC)
        self.slept: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def store(tmp_path):
    return LocalStore(tmp_path / "store")


def _ledger(store, clock, hour=10, day=25, month=30) -> budget.BudgetLedger:
    return budget.BudgetLedger(store, clock, clock.sleep, budget.Limits(hour, day, month))


def test_hour_budget_sleeps_to_the_top_of_the_next_hour(store):
    clock = Clock(2026, 3, 14, 12, 5)
    ledger = _ledger(store, clock)
    for i in range(10):
        ledger.before_request(f"S{i}")
    assert clock.slept == []
    ledger.before_request("S10")
    assert clock.slept == [55 * 60.0] and clock.now == datetime(2026, 3, 14, 13, 0, tzinfo=UTC)
    doc = json.loads(store.get("meta/budget.json"))
    assert set(doc) == {"limits", "hours", "days", "months"}
    assert doc["limits"] == {"req_per_hour": 10, "req_per_day": 25, "unique_symbols_per_month": 30}
    assert doc["hours"] == {"2026-03-14T12": 10, "2026-03-14T13": 1}
    assert doc["days"] == {"2026-03-14": 11}
    assert doc["months"] == {"2026-03": sorted(f"S{i}" for i in range(11))}


def test_day_budget_raises_and_a_new_ledger_resumes_the_count(store):
    clock = Clock(2026, 3, 14, 12, 5)
    ledger = _ledger(store, clock)
    for i in range(25):
        ledger.before_request(f"S{i:02d}")
    assert len(clock.slept) == 2
    with pytest.raises(budget.BudgetSpent) as spent:
        ledger.before_request("S25")
    assert spent.value.scope == "day" and "day budget spent" in str(spent.value)
    slept_before = list(clock.slept)
    # A new run the same day: the persisted count still refuses, without sleeping.
    again = _ledger(store, clock)
    with pytest.raises(budget.BudgetSpent):
        again.before_request("S00")
    assert clock.slept == slept_before
    clock.now = datetime(2026, 3, 15, 0, 0, tzinfo=UTC)
    again.before_request("S25")
    assert again.days == {"2026-03-14": 25, "2026-03-15": 1}


def test_month_budget_refuses_new_symbols_only(store):
    clock = Clock(2026, 3, 14, 12, 5)
    ledger = _ledger(store, clock, hour=100, day=100, month=3)
    for symbol in ("A", "B", "C", "A", "B"):
        ledger.before_request(symbol)
    with pytest.raises(budget.BudgetSpent) as spent:
        ledger.before_request("D")
    assert spent.value.scope == "month"
    ledger.before_request("C")  # a symbol already fetched this month passes
    assert ledger.months == {"2026-03": ["A", "B", "C"]} and ledger.days["2026-03-14"] == 6
    clock.now = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    ledger.before_request("D")
    assert ledger.months["2026-04"] == ["D"]


def test_two_ledgers_on_one_store_share_the_counts(store):
    """The nightly and a one-time job spending the same budget see each other's requests."""
    clock = Clock(2026, 3, 14, 12, 5)
    nightly, backfill = _ledger(store, clock, hour=4, day=6), _ledger(store, clock, hour=4, day=6)
    for i in range(2):
        nightly.before_request(f"N{i}")
        backfill.before_request(f"B{i}")
    assert clock.slept == []
    nightly.before_request("N2")  # the fifth request of the hour waits for the next hour
    assert clock.slept == [55 * 60.0]
    backfill.before_request("B2")
    with pytest.raises(budget.BudgetSpent) as spent:
        nightly.before_request("N3")
    assert spent.value.scope == "day"
    doc = json.loads(store.get("meta/budget.json"))
    assert doc["days"] == {"2026-03-14": 6}
    assert doc["hours"] == {"2026-03-14T12": 4, "2026-03-14T13": 2}
    assert doc["months"]["2026-03"] == ["B0", "B1", "B2", "N0", "N1", "N2"]


def test_old_buckets_are_pruned(store):
    clock = Clock(2026, 1, 10, 8, 0)
    ledger = _ledger(store, clock, hour=100, day=100, month=100)
    ledger.before_request("A")
    for month, day in ((2, 10), (3, 10), (4, 10), (4, 20)):
        clock.now = datetime(2026, month, day, 8, 0, tzinfo=UTC)
        ledger.before_request("A")
    assert sorted(ledger.months) == ["2026-02", "2026-03", "2026-04"]
    assert sorted(ledger.days) == ["2026-03-10", "2026-04-10", "2026-04-20"]
    assert sorted(ledger.hours) == ["2026-04-20T08"]


def test_a_clock_that_does_not_advance_is_an_error(store):
    clock = Clock(2026, 3, 14, 12, 5)
    ledger = budget.BudgetLedger(store, clock, lambda seconds: None, budget.Limits(1, 9, 9))
    ledger.before_request("A")
    with pytest.raises(RuntimeError, match="clock did not advance"):
        ledger.before_request("B")


def test_limits_file_wins_over_env_and_env_over_defaults(store, monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    assert limits.load_limits(store) == budget.Limits(45, 900, 450) == limits.STARTER
    assert limits.plan_tier(store) == "starter"
    for name, value in zip(ENV_NAMES, ("7", "12", "40"), strict=True):
        monkeypatch.setenv(name, value)
    assert limits.load_limits(store) == budget.Limits(7, 12, 40)
    store.put(
        "meta/provider_limits.json", json.dumps({"req_per_hour": 10, "tier": "Power"}).encode()
    )
    assert limits.load_limits(store) == budget.Limits(10, 12, 40)
    assert limits.plan_tier(store) == "power"
    store.put("meta/provider_limits.json", b"[]")
    assert limits.load_limits(store) == budget.Limits(7, 12, 40)


class FakeProvider:
    def __init__(self, clock, rate_limit_at=None):
        self.clock, self.rate_limit_at = clock, rate_limit_at
        self.calls: list[datetime] = []

    def fetch_meta(self, symbol):
        self.calls.append(self.clock.now)
        if self.rate_limit_at is not None and len(self.calls) >= self.rate_limit_at:
            raise RateLimited("429")
        return SymbolMeta(name=symbol, first_date=None, last_date=date(2026, 3, 13), kind="etf")


def _probe(store, clock, provider, ledger=None, **kwargs):
    ledger = ledger or _ledger(store, clock, hour=10, day=900, month=450)
    return ledger, limits.measure_limits(
        store=store,
        ledger=ledger,
        provider=provider,
        clock=clock,
        sleep=clock.sleep,
        symbol="VTI",
        **kwargs,
    )


def test_probe_without_429_makes_exactly_60_requests_in_the_window(store):
    clock = Clock(2026, 3, 14, 12, 5)
    provider = FakeProvider(clock)
    ledger, recorded = _probe(store, clock, provider)  # hourly ingestion limit is 10
    assert len(provider.calls) == 60
    assert (provider.calls[-1] - provider.calls[0]).total_seconds() <= 600
    assert max(clock.slept) < 60, "the probe must not sleep to the next hour"
    doc = json.loads(store.get("meta/provider_limits.json"))
    assert set(doc) == {
        "provider",
        "tier",
        "req_per_hour",
        "req_per_day",
        "unique_symbols_per_month",
        "measured_on",
        "method",
    }
    assert doc["provider"] == "tiingo" and doc["method"] == "probe"
    assert doc["measured_on"] == "2026-03-14"
    assert doc["tier"] == "at least 60/10 min" and "60" in doc["tier"]
    assert (doc["req_per_hour"], doc["req_per_day"], doc["unique_symbols_per_month"]) == (
        45,
        900,
        450,
    )
    assert recorded is not None and recorded.model_dump() == doc
    # Every probe request was counted, and ingestion later in the same hour waits for them.
    assert ledger.hours == {"2026-03-14T12": 60} and ledger.days == {"2026-03-14": 60}
    assert ledger.months == {"2026-03": ["VTI"]}
    before = len(clock.slept)
    ledger.before_request("VTI")
    assert len(clock.slept) == before + 1 and clock.now.hour == 13 and clock.now.minute == 0


def test_probe_stops_at_the_first_429_and_records_starter(store):
    clock = Clock(2026, 3, 14, 12, 5)
    provider = FakeProvider(clock, rate_limit_at=37)
    ledger, recorded = _probe(store, clock, provider)
    assert len(provider.calls) == 37
    assert recorded is not None and recorded.tier == "starter"
    assert (recorded.req_per_hour, recorded.req_per_day) == (45, 900)
    assert recorded.unique_symbols_per_month == 450 and ledger.days == {"2026-03-14": 37}


def test_probe_honours_the_daily_budget_and_writes_nothing(store):
    clock = Clock(2026, 3, 14, 12, 5)
    provider = FakeProvider(clock)
    ledger, recorded = _probe(store, clock, provider, ledger=_ledger(store, clock, day=20))
    assert recorded is None and len(provider.calls) == 20
    assert not store.exists("meta/provider_limits.json")
    with pytest.raises(budget.BudgetSpent):
        ledger.before_request("VTI")


def test_probe_bounds_are_enforced_by_the_ledger(store):
    clock = Clock(2026, 3, 14, 12, 5)
    ledger = _ledger(store, clock, hour=1, day=500, month=10)
    with ledger.probe(max_requests=3, window_seconds=600):
        for _ in range(3):
            ledger.before_request("VTI")
        with pytest.raises(budget.BudgetSpent) as spent:
            ledger.before_request("VTI")
        assert spent.value.scope == "probe"
    with ledger.probe(max_requests=60, window_seconds=600):
        clock.now += timedelta(seconds=601)
        with pytest.raises(budget.BudgetSpent):
            ledger.before_request("VTI")
    assert clock.slept == []


def test_probe_with_a_self_accounting_provider_counts_once(store):
    clock = Clock(2026, 3, 14, 12, 5)
    ledger = _ledger(store, clock, hour=10, day=900, month=450)

    class Hooked(FakeProvider):
        def fetch_meta(self, symbol):
            ledger.before_request(symbol)
            return super().fetch_meta(symbol)

    provider = Hooked(clock)
    _probe(store, clock, provider, ledger=ledger, account=False)
    assert len(provider.calls) == 60 and ledger.days == {"2026-03-14": 60}
