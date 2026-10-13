"""A-PS-08 — D_G follows the spec §4.2 calendar rule.

Claim: D_G is the most recent XNYS session whose close is at least 6 hours before the nightly's
scheduled start (02:00 America/Los_Angeles on the run date), computed with exchange_calendars,
independent of which funds are included.

Pinned interface (the product must provide exactly this):
- `portfoliosight.data.calendar.generation_date(run_at: datetime) -> datetime.date`. `run_at` is
  timezone-aware. The rule uses the scheduled start, 02:00 America/Los_Angeles on `run_at`'s
  Los Angeles calendar date, never `run_at`'s own time of day. The result is a plain
  `datetime.date` (not a `datetime`, not a pandas `Timestamp`). The function has exactly one
  required parameter and no parameter that carries funds, symbols, tickers or a universe.
- `portfoliosight.data.calendar.generation_id(d_g: date, engine_version: str) -> str`, equal to
  `f"{d_g.isoformat()}-{engine_version}"`.

The expected dates are both hard-coded here and recomputed with `exchange_calendars` ("XNYS"), so
neither a wrong product nor a wrong reference can pass alone.
"""

from __future__ import annotations

import importlib
import inspect
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
        pytest.fail(f"A-PS-08 red: cannot import {module}: {type(exc).__name__}: {exc}")


LA = ZoneInfo("America/Los_Angeles")
UTC = timezone.utc

# (label, run instant, expected D_G). The five situations of the assertion spec, hard-coded.
SITUATIONS = [
    ("Wednesday run -> Tuesday", datetime(2026, 10, 14, 2, 0, tzinfo=LA), date(2026, 10, 13)),
    ("Monday run -> prior Friday", datetime(2026, 10, 12, 2, 0, tzinfo=LA), date(2026, 10, 9)),
    (
        "day after Thanksgiving 2025 -> the session before the holiday",
        datetime(2025, 11, 28, 2, 0, tzinfo=LA),
        date(2025, 11, 26),
    ),
    (
        "day after the 1 p.m. ET early close of 2025-12-24 -> that session",
        datetime(2025, 12, 25, 2, 0, tzinfo=LA),
        date(2025, 12, 24),
    ),
    (
        "10:00 PT on the Wednesday -> same D_G as the 02:00 run",
        datetime(2026, 10, 14, 10, 0, tzinfo=LA),
        date(2026, 10, 13),
    ),
]

# More instants that pin "the scheduled start on run_at's Los Angeles date", also hard-coded.
EXTRA = [
    ("23:30 PT on the Wednesday", datetime(2026, 10, 14, 23, 30, tzinfo=LA), date(2026, 10, 13)),
    ("00:05 PT on the Wednesday", datetime(2026, 10, 14, 0, 5, tzinfo=LA), date(2026, 10, 13)),
    (
        "02:00 PT on the Wednesday given in UTC",
        datetime(2026, 10, 14, 9, 0, tzinfo=UTC),
        date(2026, 10, 13),
    ),
    (
        "05:00 UTC Wednesday is still Tuesday in Los Angeles",
        datetime(2026, 10, 14, 5, 0, tzinfo=UTC),
        date(2026, 10, 12),
    ),
    (
        "Saturday after the 2025-11-28 early close",
        datetime(2025, 11, 29, 2, 0, tzinfo=LA),
        date(2025, 11, 28),
    ),
    (
        "Independence Day 2025 after the 2025-07-03 early close",
        datetime(2025, 7, 4, 2, 0, tzinfo=LA),
        date(2025, 7, 3),
    ),
]


def _reference(xcals, pd, run_at: datetime) -> date:
    """Independent recomputation of spec §4.2 with exchange_calendars."""
    cal = xcals.get_calendar("XNYS")
    run_day = run_at.astimezone(LA).date()
    start = datetime(run_day.year, run_day.month, run_day.day, 2, 0, tzinfo=LA)
    cutoff = pd.Timestamp(start - timedelta(hours=6)).tz_convert("UTC")
    sessions = cal.sessions_in_range(
        pd.Timestamp(run_day - timedelta(days=15)), pd.Timestamp(run_day)
    )
    for session in reversed(sessions):
        if cal.session_close(session) <= cutoff:
            return session.date()
    raise AssertionError(f"reference found no session before {run_day}")


def _call(fn, run_at: datetime) -> date:
    try:
        result = fn(run_at)
    except Exception as exc:
        pytest.fail(f"A-PS-08 red: generation_date({run_at.isoformat()}) raised {exc!r}")
    assert isinstance(result, date), f"generation_date must return a date, got {type(result)}"
    assert not isinstance(result, datetime), (
        f"generation_date must return a plain datetime.date, got {type(result).__name__}"
    )
    return result


if _OUTER:

    def test_a_ps_08_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-08 is red inside the project virtualenv (output above)"

else:

    def test_reference_agrees_with_the_hard_coded_dates():
        """Guards the test itself: the library rule and the hand-picked dates must agree."""
        xcals = _need("exchange_calendars")
        pd = _need("pandas")
        for label, run_at, expected in SITUATIONS + EXTRA:
            assert _reference(xcals, pd, run_at) == expected, label

    def test_five_calendar_situations():
        xcals = _need("exchange_calendars")
        pd = _need("pandas")
        cal_mod = _need("portfoliosight.data.calendar")
        fn = getattr(cal_mod, "generation_date", None)
        assert callable(fn), "portfoliosight.data.calendar.generation_date is missing"
        checked = 0
        for label, run_at, expected in SITUATIONS + EXTRA:
            got = _call(fn, run_at)
            assert got == expected, f"{label}: expected {expected}, got {got}"
            assert got == _reference(xcals, pd, run_at), label
            # Must-not-contain: the same-day session (its close is after 02:00 PT).
            assert got != run_at.astimezone(LA).date(), f"{label}: same-day session returned"
            checked += 1
        assert checked == 11
        same_day = [_call(fn, run_at) for _, run_at, _ in (SITUATIONS[0], SITUATIONS[4])]
        assert same_day[0] == same_day[1], "02:00 PT and 10:00 PT runs must share one D_G"

    def test_every_run_day_of_2025_matches_the_rule():
        xcals = _need("exchange_calendars")
        pd = _need("pandas")
        cal_mod = _need("portfoliosight.data.calendar")
        fn = getattr(cal_mod, "generation_date", None)
        assert callable(fn), "portfoliosight.data.calendar.generation_date is missing"
        cal = xcals.get_calendar("XNYS")
        checked = 0
        distinct = set()
        day = date(2025, 1, 1)
        while day <= date(2025, 12, 31):
            for hour in (2, 15):
                run_at = datetime(day.year, day.month, day.day, hour, 0, tzinfo=LA)
                got = _call(fn, run_at)
                assert got == _reference(xcals, pd, run_at), f"run {run_at.isoformat()}: got {got}"
                assert cal.is_session(pd.Timestamp(got)), f"{got} is not an XNYS session"
                start = datetime(day.year, day.month, day.day, 2, 0, tzinfo=LA)
                close = cal.session_close(pd.Timestamp(got)).to_pydatetime()
                # Must-not-contain: a session closing less than 6 hours before 02:00 PT.
                assert not close > start - timedelta(hours=6), (
                    f"run {day}: session {got} closes less than 6 h before the scheduled start"
                )
                assert got < day
                distinct.add(got)
                checked += 1
            day += timedelta(days=1)
        assert checked == 730
        assert len(distinct) >= 249, "D_G must move with the run date across the year"

    def test_takes_no_fund_list():
        cal_mod = _need("portfoliosight.data.calendar")
        fn = getattr(cal_mod, "generation_date", None)
        assert callable(fn), "portfoliosight.data.calendar.generation_date is missing"
        params = list(inspect.signature(fn).parameters.values())
        required = [
            p
            for p in params
            if p.default is inspect.Parameter.empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert len(required) == 1, f"generation_date must take run_at only, has {params}"
        for p in params:
            assert p.kind not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ), f"generation_date must not accept *args/**kwargs ({p})"
            lowered = p.name.lower()
            for word in ("fund", "symbol", "ticker", "universe", "holding", "preset"):
                assert word not in lowered, f"generation_date must not take a fund list ({p.name})"

    def test_generation_string():
        cal_mod = _need("portfoliosight.data.calendar")
        fn = getattr(cal_mod, "generation_id", None)
        assert callable(fn), "portfoliosight.data.calendar.generation_id is missing"
        assert fn(date(2026, 10, 12), "0.1.0") == "2026-10-12-0.1.0"  # the spec §5.3 example
        assert fn(date(2025, 1, 3), "9.8.7") == "2025-01-03-9.8.7"
        assert fn(date(2025, 1, 3), "9.8.7") != fn(date(2025, 1, 6), "9.8.7")
        assert fn(date(2025, 1, 3), "9.8.7") != fn(date(2025, 1, 3), "9.8.8")
        gen_date = getattr(cal_mod, "generation_date", None)
        assert callable(gen_date), "portfoliosight.data.calendar.generation_date is missing"
        d_g = _call(gen_date, SITUATIONS[0][1])
        assert fn(d_g, "0.1.0") == "2026-10-13-0.1.0"
