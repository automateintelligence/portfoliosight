"""D_G and trading-day arithmetic (spec 4.2, 5.2; A-PS-08)."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta
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


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def _la(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=LA)


@pytest.mark.parametrize(
    ("label", "run_at", "minutes", "expected"),
    [
        ("scheduled 02:00 start", _la(2026, 10, 14, 2, 0), 30, _utc(2026, 10, 15, 8, 30)),
        ("manual 21:50 start", _la(2026, 10, 13, 21, 50), 30, _utc(2026, 10, 14, 8, 30)),
        ("manual, before 01:30", _la(2026, 10, 14, 1, 0), 30, _utc(2026, 10, 14, 8, 30)),
        ("manual, after 01:30", _la(2026, 10, 14, 1, 45), 30, _utc(2026, 10, 15, 8, 30)),
        ("start exactly at 01:30", _la(2026, 10, 14, 1, 30), 30, _utc(2026, 10, 15, 8, 30)),
        ("UTC instant", _utc(2026, 10, 14, 9, 0), 30, _utc(2026, 10, 15, 8, 30)),
        ("lead of 90 minutes", _la(2026, 10, 14, 2, 0), 90, _utc(2026, 10, 15, 7, 30)),
        ("lead of 0 minutes", _la(2026, 10, 14, 2, 0), 0, _utc(2026, 10, 15, 9, 0)),
        # Spring forward (2026-03-08): 01:30 is still PST; the next morning's is PDT.
        ("eve of spring forward", _la(2026, 3, 7, 2, 0), 30, _utc(2026, 3, 8, 9, 30)),
        ("day of spring forward", _la(2026, 3, 8, 3, 0), 30, _utc(2026, 3, 9, 8, 30)),
        # 02:00 does not exist that day: the timer fires at 03:00 PDT, which is 02:00 PST.
        ("spring forward, lead 0", _la(2026, 3, 7, 2, 0), 0, _utc(2026, 3, 8, 10, 0)),
        # Fall back (2026-11-01): 01:00-02:00 happens twice and 02:00 PST is the start, so the
        # deadline is the second 01:30 (PST), 30 minutes before it.
        ("eve of fall back", _la(2026, 10, 31, 2, 0), 30, _utc(2026, 11, 1, 9, 30)),
        ("01:45 PDT on fall back", _utc(2026, 11, 1, 8, 45), 30, _utc(2026, 11, 1, 9, 30)),
        ("01:45 PST on fall back", _utc(2026, 11, 1, 9, 45), 30, _utc(2026, 11, 2, 9, 30)),
        ("day of fall back", _la(2026, 11, 1, 2, 0), 30, _utc(2026, 11, 2, 9, 30)),
    ],
)
def test_refresh_deadline(label, run_at, minutes, expected):
    got = calendar.refresh_deadline(run_at, minutes)
    assert got == expected, label
    assert got.utcoffset() == timedelta(0) and got > run_at


@pytest.mark.parametrize("minutes", [-1, 24 * 60])
def test_refresh_deadline_refuses_a_lead_outside_one_day(minutes):
    with pytest.raises(ValueError, match="minutes"):
        calendar.refresh_deadline(_utc(2026, 10, 14, 9, 0), minutes)


def test_refresh_deadline_needs_an_aware_instant():
    with pytest.raises(ValueError, match="timezone-aware"):
        calendar.refresh_deadline(datetime(2026, 10, 14, 2, 0), 30)
