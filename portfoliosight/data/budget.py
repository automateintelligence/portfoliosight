"""The provider request ledger ``meta/budget.json`` (spec 5.2, 5.4).

Counts requests per UTC hour and day and unique symbols per month. ``before_request`` is called
before every HTTP attempt, retries included, so accounting always precedes the request. Each
request is counted by a conditional read-modify-write of the stored ledger, so two processes
spending the same budget (the nightly and a one-time job) see each other's requests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from portfoliosight.data import store as store_mod

BUDGET_KEY = "meta/budget.json"
_KEEP_HOURS = timedelta(hours=48)
_KEEP_DAYS = timedelta(days=62)
_KEEP_MONTHS = 3


@dataclass(frozen=True)
class Limits:
    """The limits in force: requests per hour and day, unique symbols per month."""

    req_per_hour: int
    req_per_day: int
    unique_symbols_per_month: int


class BudgetSpent(Exception):
    """The daily (``"day"``) or monthly (``"month"``) budget, or a probe's own bound, is spent."""

    def __init__(self, scope: str):
        super().__init__(f"{scope} budget spent")
        self.scope = scope


class _HourSpent(Exception):
    """The hourly budget is spent; the request waits for the next UTC hour."""


@dataclass
class _Probe:
    max_requests: int
    deadline: datetime
    requests: int = 0


class BudgetLedger:
    """Enforces the limits and persists the counts after every request."""

    def __init__(
        self,
        store: store_mod.Store,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
        limits: Limits,
    ):
        self._store = store
        self._clock = clock
        self._sleep = sleep
        self.limits = limits
        self._probe: _Probe | None = None
        try:
            saved = store_mod.get_json(store, BUDGET_KEY)
        except KeyError:
            saved = {}
        self.hours: dict[str, int] = {}
        self.days: dict[str, int] = {}
        self.months: dict[str, list[str]] = {}
        self._load(saved)

    def _load(self, saved: Any) -> None:
        """Take the counts of the stored ledger (``None`` or ``{}`` when there is none)."""
        saved = saved if isinstance(saved, dict) else {}
        self.hours = dict(saved.get("hours", {}))
        self.days = dict(saved.get("days", {}))
        self.months = {month: list(symbols) for month, symbols in saved.get("months", {}).items()}

    def _now(self) -> datetime:
        return self._clock().astimezone(UTC)

    def before_request(self, symbol: str) -> None:
        """Account one request for ``symbol``, waiting or refusing first when a budget is spent.

        Sleeps to the top of the next UTC hour when the hourly budget is spent; raises
        ``BudgetSpent("day")`` or ``BudgetSpent("month")`` when those are. A symbol already
        fetched this month never trips the monthly budget. The counts checked and incremented
        are the stored ones, read again for every request.
        """
        for _ in range(4):
            now = self._now()
            try:
                store_mod.update_json(
                    self._store, BUDGET_KEY, lambda saved, now=now: self._count(saved, symbol, now)
                )
            except _HourSpent:
                next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                self._sleep((next_hour - now).total_seconds())
                continue
            if self._probe is not None:
                self._probe.requests += 1
            return
        raise RuntimeError("the clock did not advance past the hour while waiting")

    def _count(self, saved: Any, symbol: str, now: datetime) -> dict[str, Any]:
        """The stored ledger with one more request for ``symbol``, or the reason it must wait."""
        self._load(saved)
        hour_key, day_key, month_key = _keys(now)
        if self.days.get(day_key, 0) >= self.limits.req_per_day:
            raise BudgetSpent("day")
        seen = self.months.get(month_key, [])
        if symbol not in seen and len(seen) >= self.limits.unique_symbols_per_month:
            raise BudgetSpent("month")
        if self._probe is not None:
            if self._probe.requests >= self._probe.max_requests or now > self._probe.deadline:
                raise BudgetSpent("probe")
        elif self.hours.get(hour_key, 0) >= self.limits.req_per_hour:
            raise _HourSpent
        self.hours[hour_key] = self.hours.get(hour_key, 0) + 1
        self.days[day_key] = self.days.get(day_key, 0) + 1
        if symbol not in seen:
            self.months[month_key] = sorted([*seen, symbol])
        return self._document(now)

    @contextmanager
    def probe(self, max_requests: int = 60, window_seconds: float = 600) -> Iterator[None]:
        """The bounded limits probe: up to ``max_requests`` within ``window_seconds``.

        Inside it the hourly ingestion limit does not apply (and nothing sleeps to the next
        hour), every request is still counted, and the daily and monthly budgets still hold. On
        exit the ordinary limits are in force again and see the probe's requests.
        """
        deadline = self._now() + timedelta(seconds=window_seconds)
        self._probe = _Probe(max_requests=max_requests, deadline=deadline)
        try:
            yield
        finally:
            self._probe = None

    def _document(self, now: datetime) -> dict[str, Any]:
        """The ledger to store, its old buckets pruned."""
        hour_floor = (now - _KEEP_HOURS).strftime("%Y-%m-%dT%H")
        day_floor = (now - _KEEP_DAYS).strftime("%Y-%m-%d")
        self.hours = {key: n for key, n in self.hours.items() if key >= hour_floor}
        self.days = {key: n for key, n in self.days.items() if key >= day_floor}
        for month in sorted(self.months)[:-_KEEP_MONTHS]:
            del self.months[month]
        return {
            "limits": asdict(self.limits),
            "hours": self.hours,
            "days": self.days,
            "months": self.months,
        }


def _keys(now: datetime) -> tuple[str, str, str]:
    return now.strftime("%Y-%m-%dT%H"), now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
