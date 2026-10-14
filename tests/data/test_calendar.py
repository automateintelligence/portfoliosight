"""D_G and trading-day arithmetic (spec 4.2, 5.2; A-PS-08)."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from portfoliosight.data import calendar

LA = ZoneInfo("America/Los_Angeles")


@pytest.mark.parametrize(
    ("label", "run_at", "expected"),
    [
        ("Wednesday -> Tuesday", datetime(2026, 10, 14, 2, 0, tzinfo=LA), date(2026, 10, 13)),
        ("Monday -> prior Friday", datetime(2026, 10, 12, 2, 0, tzinfo=LA), date(2026, 10, 9)),
        ("after Thanksgiving", datetime(2025, 11, 28, 2, 0, tzinfo=LA), date(2025, 11, 26)),
        ("after an early close", datetime(2025, 12, 25, 2, 0, tzinfo=LA), date(2025, 12, 24)),
        ("10:00 PT same day", datetime(2026, 10, 14, 10, 0, tzinfo=LA), date(2026, 10, 13)),
        ("UTC instant", datetime(2026, 10, 14, 9, 0, tzinfo=UTC), date(2026, 10, 13)),
        (
            "still Tuesday in LA",
            datetime(2026, 10, 14, 5, 0, tzinfo=UTC),
            date(2026, 10, 12),
        ),
        ("Saturday", datetime(2026, 3, 14, 12, 5, tzinfo=UTC), date(2026, 3, 13)),
    ],
)
def test_generation_date(label, run_at, expected):
    got = calendar.generation_date(run_at)
    assert got == expected, label
    assert type(got) is date


def test_generation_date_needs_an_aware_instant_and_takes_no_fund_list():
    with pytest.raises(ValueError, match="timezone-aware"):
        calendar.generation_date(datetime(2026, 10, 14, 2, 0))
    assert list(inspect.signature(calendar.generation_date).parameters) == ["run_at"]


def test_generation_id():
    assert calendar.generation_id(date(2026, 10, 12), "0.1.0") == "2026-10-12-0.1.0"


def test_trading_days_behind_counts_sessions():
    monday = date(2026, 3, 9)
    assert calendar.trading_days_behind(monday, monday) == 0
    assert calendar.trading_days_behind(date(2026, 3, 10), monday) == 0
    assert calendar.trading_days_behind(date(2026, 3, 6), monday) == 1  # Friday
    assert calendar.trading_days_behind(date(2026, 3, 7), monday) == 1  # Saturday
    assert calendar.trading_days_behind(date(2026, 3, 4), monday) == 3
    # Thanksgiving 2025 is not a session.
    assert calendar.trading_days_behind(date(2025, 11, 26), date(2025, 11, 28)) == 1


def test_within_trading_days_boundary():
    monday = date(2026, 3, 9)
    assert calendar.session_back(monday, 3) == date(2026, 3, 4)
    assert calendar.within_trading_days(date(2026, 3, 4), monday, 3) is True
    assert calendar.within_trading_days(date(2026, 3, 3), monday, 3) is False
    assert calendar.within_trading_days(monday, monday, 0) is True
    # A non-session D counts back from the session before it.
    assert calendar.session_back(date(2026, 3, 8), 0) == date(2026, 3, 6)
