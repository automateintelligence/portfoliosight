"""The generation date ``D_G`` and trading-day arithmetic on the XNYS calendar (spec 4.2, 5.2)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

EXCHANGE = "XNYS"
SCHEDULE_ZONE = ZoneInfo("America/Los_Angeles")
SCHEDULED_START = time(2, 0)
SETTLE = timedelta(hours=6)
_LOOKBACK = timedelta(days=15)


@lru_cache(maxsize=1)
def _calendar() -> xcals.ExchangeCalendar:
    return xcals.get_calendar(EXCHANGE)


def _iso(stamp: object) -> str:
    """The calendar date of a session label as an ISO string."""
    return str(stamp)[:10]


def generation_date(run_at: datetime) -> date:
    """``D_G``: the latest XNYS session that closed at least 6 hours before the scheduled start.

    The scheduled start is 02:00 America/Los_Angeles on ``run_at``'s Los Angeles date, whatever
    time of day ``run_at`` itself is, so a rerun later the same day gets the same ``D_G``.
    """
    if run_at.tzinfo is None:
        raise ValueError("run_at must be timezone-aware")
    run_day = run_at.astimezone(SCHEDULE_ZONE).date()
    start = datetime.combine(run_day, SCHEDULED_START, tzinfo=SCHEDULE_ZONE)
    cutoff = pd.Timestamp(start - SETTLE).tz_convert("UTC")
    calendar = _calendar()
    sessions = calendar.sessions_in_range((run_day - _LOOKBACK).isoformat(), run_day.isoformat())
    for session in reversed([_iso(stamp) for stamp in sessions]):
        if calendar.session_close(session) <= cutoff:
            return date.fromisoformat(session)
    raise RuntimeError(f"no {EXCHANGE} session in the {_LOOKBACK.days} days before {run_day}")


def refresh_deadline(run_at: datetime, minutes_before: int) -> datetime:
    """The first instant after ``run_at`` that is ``minutes_before`` a scheduled start (UTC).

    Each scheduled start is 02:00 America/Los_Angeles (on a spring-forward day, where 02:00 does
    not exist, the instant 02:00 PST, i.e. 03:00 PDT); the lead is subtracted in elapsed time.
    A run started inside the lead of the next start gets the deadline of the start after it.
    """
    if run_at.tzinfo is None:
        raise ValueError("run_at must be timezone-aware")
    if not 0 <= minutes_before < 24 * 60:
        raise ValueError(f"minutes_before must be in [0, 1440), not {minutes_before}")
    started = run_at.astimezone(UTC)
    run_day = run_at.astimezone(SCHEDULE_ZONE).date()
    lead = timedelta(minutes=minutes_before)
    for offset in range(3):
        start = datetime.combine(run_day + timedelta(days=offset), SCHEDULED_START, SCHEDULE_ZONE)
        deadline = start.astimezone(UTC) - lead
        if deadline > started:
            return deadline
    raise AssertionError("unreachable: a start within two days lies beyond any lead")


def generation_id(d_g: date, engine_version: str) -> str:
    """``G = {D_G}-{engine_version}``."""
    return f"{d_g.isoformat()}-{engine_version}"


@lru_cache(maxsize=4096)
def session_back(d_g: date, n: int) -> date:
    """The session ``n`` sessions before the last session on or before ``d_g``."""
    calendar = _calendar()
    anchor = calendar.date_to_session(d_g.isoformat(), direction="previous")
    return date.fromisoformat(_iso(calendar.sessions_window(anchor, -(n + 1))[0]))


def trading_days_behind(d: date, d_g: date) -> int:
    """How many XNYS sessions lie after ``d`` up to and including ``d_g`` (0 when ``d >= d_g``)."""
    if d >= d_g:
        return 0
    sessions = _calendar().sessions_in_range((d + timedelta(days=1)).isoformat(), d_g.isoformat())
    return len(sessions)


def within_trading_days(d: date, d_g: date, n: int) -> bool:
    """True when ``d`` is on or after the session ``n`` sessions before ``d_g``."""
    return d >= session_back(d_g, n)
