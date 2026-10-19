"""The rolling-origin harness: origins ledger and evidence gate (protocol 4 and 8; plan 6.1).

Every fixture is synthetic: a few funds priced on the XNYS sessions of the installed
`exchange_calendars` (real holidays), with chosen days removed or added. The expected dates and
counts were worked out from the session list by hand and are written here as literals; no
expectation comes from the code under test. CLI tests read snapshots written by the freeze
script's own `build_snapshot` into `tmp_path`; the real mirror and snapshot root are never opened.

Calendar facts the literals rest on: 2024 has 252 XNYS sessions (2024-01-02 .. 2024-12-31); 2023
and 2025 have 250 (2025-01-09 was closed); August 2023 has 23 sessions; Good Friday closed
2024-03-29 and 2018-03-30; Memorial Day closed 2021-05-31. The 252nd session after 2025-09-30 is
2026-10-01, after 2025-10-31 it is 2026-11-03, after 2022-07-11 it is 2023-07-12, after 2023-07-31
it is 2024-07-31.
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from types import ModuleType

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from portfoliosight.data.returns import build_returns
from portfoliosight.engine.windows import select_window
from portfoliosight.research import harness
from portfoliosight.research.harness import (
    COMPLETE,
    COMPLETE_ROWS_SHORT,
    FUND_AFTER_START,
    HORIZON_DATES_SHORT,
    HORIZON_MISSING,
    HORIZON_PAST_D_STAR,
    HORIZON_VALUE_MISSING,
    IMMATURE,
    MATURE,
    ORIGIN_PRICE_MISSING,
    PREDECESSOR_MISSING,
    PREHISTORY,
    TRAINING_INELIGIBLE,
    UNION_ROWS_SHORT,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "backtest_ranges.py"
FREEZE = ROOT / "scripts" / "freeze_research_inputs.py"

BASE_D_STAR = date(2026, 10, 1)
MENUS = {"tsp": ("TSP-G", "TSP-F"), "example": ("X", "Y", "Z")}
BASE_FIRST = {"TSP-G": "2021-01-04", "TSP-F": "2021-01-04", "X": "2021-01-04", "Y": "2021-01-04"}
BASE_FIRST["Z"] = "2022-07-11"  # the last fund to start: the inception case
GROWTH = {"TSP-G": 1e-4, "TSP-F": 2e-4, "X": 3e-4, "Y": 4e-4, "Z": 5e-4, "SGOV": 1.5e-4}
LONG_D_STAR = date(2026, 10, 16)
LONG_MENUS = {"tsp": ("TSP-G", "TSP-F"), "example": ("X", "Y")}

TSP = ["TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I"]
# fmt: off
EXAMPLE = [
    "VTI", "VTV", "VOE", "VB", "VBR", "VEA", "SCHF", "VWO", "VNQ", "VBIAX", "SCHO", "BND",
    "AGG", "TIP", "VTIP", "LQD", "VWOB", "PCY", "EFA", "LTPZ", "EDV", "VGSTX", "DBJP",
]
# The 40 quarter-end origins of spec 10 (last XNYS session of each quarter, 2015-12 .. 2025-09).
QUARTER_ENDS = [
    "2015-12-31", "2016-03-31", "2016-06-30", "2016-09-30", "2016-12-30", "2017-03-31",
    "2017-06-30", "2017-09-29", "2017-12-29", "2018-03-29", "2018-06-29", "2018-09-28",
    "2018-12-31", "2019-03-29", "2019-06-28", "2019-09-30", "2019-12-31", "2020-03-31",
    "2020-06-30", "2020-09-30", "2020-12-31", "2021-03-31", "2021-06-30", "2021-09-30",
    "2021-12-31", "2022-03-31", "2022-06-30", "2022-09-30", "2022-12-30", "2023-03-31",
    "2023-06-30", "2023-09-29", "2023-12-29", "2024-03-28", "2024-06-28", "2024-09-30",
    "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30",
]
YEAR_ENDS = [
    "2015-12-31", "2016-12-30", "2017-12-29", "2018-12-31", "2019-12-31", "2020-12-31",
    "2021-12-31", "2022-12-30", "2023-12-29", "2024-12-31",
]
# fmt: on
LEDGER_COLUMNS = [
    "lookback",
    "origins",
    "month",
    "origin",
    "status",
    "training_eligible",
    "realized_denominator",
    "maturity_session",
    "mature",
    "risk_free_source",
    "risk_free_rate",
    "month_issues",
    "menu",
    "funds",
    "origin_priced",
    "union_rows",
    "window_start",
    "window_rows",
    "complete_rows",
    "menu_training_eligible",
    "outcome",
    "horizon_start",
    "horizon_end",
    "horizon_rows",
    "disjoint",
    "overlap_prev_dates",
    "overlap_origins",
    "menu_issues",
]  # fmt: skip


# ----------------------------------------------------------------------------------- fixtures


@functools.cache
def _xnys() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        xcals.get_calendar("XNYS", start="2015-01-01", end="2027-12-31").sessions
    )


def _days(first: str, last: str | date) -> pd.DatetimeIndex:
    sessions = _xnys()
    inside = (sessions >= pd.Timestamp(first)) & (sessions <= pd.Timestamp(last))
    return pd.DatetimeIndex(sessions[inside])


def _shifted(day: str, sessions: int) -> str:
    """The XNYS session ``sessions`` sessions after (or before, when negative) ``day``."""
    values = _xnys().to_numpy()
    position = int(np.searchsorted(values, pd.Timestamp(day).to_datetime64()))
    assert pd.Timestamp(values[position]) == pd.Timestamp(day), f"{day} is not a session"
    return pd.Timestamp(values[position + sessions]).strftime("%Y-%m-%d")


def _record(days: pd.DatetimeIndex, growth: float) -> pd.DataFrame:
    tr = (1.0 + growth) ** np.arange(len(days), dtype=float)
    return pd.DataFrame(
        {
            "date": pd.DatetimeIndex(days),
            "close": 100.0 * tr,
            "tr_index": tr,
            "div_cash": 0.0,
            "split_factor": 1.0,
        }
    )


def _fund(
    first: str, last: str | date, growth: float, drop: Iterable[str] = (), add: Iterable[str] = ()
) -> pd.DataFrame:
    days = _days(first, last)
    removed = pd.DatetimeIndex(list(drop))
    assert removed.isin(days).all(), "a dropped day must be one of the fund's sessions"
    return _record(pd.DatetimeIndex(days.drop(removed).union(pd.DatetimeIndex(list(add)))), growth)


def _base(
    *,
    last: str | date = BASE_D_STAR,
    drop: dict[str, list[str]] | None = None,
    add: dict[str, list[str]] | None = None,
    sgov_first: str | None = None,
) -> dict[str, pd.DataFrame]:
    drop, add = drop or {}, add or {}
    records = {
        fund: _fund(first, last, GROWTH[fund], drop.get(fund, ()), add.get(fund, ()))
        for fund, first in BASE_FIRST.items()
    }
    if sgov_first is not None:
        records["SGOV"] = _fund(sgov_first, last, GROWTH["SGOV"])
    return records


def _ledger(
    records: dict[str, pd.DataFrame],
    *,
    d_star: date = BASE_D_STAR,
    lookback: str = "1y",
    menus: dict[str, tuple[str, ...]] = MENUS,
) -> harness.Ledger:
    return harness.build_ledger(records, _xnys(), d_star, menus, lookback)


def _long(drop_x: Iterable[str] = ()) -> dict[str, pd.DataFrame]:
    return {
        fund: _fund("2015-01-02", LONG_D_STAR, GROWTH[fund], drop_x if fund == "X" else ())
        for fund in ("TSP-G", "TSP-F", "X", "Y")
    }


@pytest.fixture(scope="module")
def base() -> harness.Ledger:
    return _ledger(_base())


@pytest.fixture(scope="module")
def long5y() -> harness.Ledger:
    return _ledger(_long(), d_star=LONG_D_STAR, lookback="5y", menus=LONG_MENUS)


def _codes(issues) -> list[tuple[str, str | None, date | None]]:
    return [(issue.code, issue.fund, issue.day) for issue in issues]


def _d(text: str) -> date:
    return date.fromisoformat(text)


def _month_range(first: str, last: str) -> list[str]:
    return [str(p) for p in pd.period_range(first, last, freq="M")]


# --------------------------------------------------------------------------- months, statuses


def test_every_month_is_present_with_its_status(base: harness.Ledger) -> None:
    months = [row.month for row in base.rows]
    assert months == _month_range("2021-01", "2026-09")  # 69 months, none dropped
    statuses = {row.month: row.status for row in base.rows}
    expected = {
        **dict.fromkeys(_month_range("2021-01", "2022-06"), PREHISTORY),
        **dict.fromkeys(_month_range("2022-07", "2023-06"), TRAINING_INELIGIBLE),
        **dict.fromkeys(_month_range("2023-07", "2025-09"), MATURE),
        **dict.fromkeys(_month_range("2025-10", "2026-09"), IMMATURE),
    }
    assert statuses == expected
    for row in base.rows:  # every excluded month carries a named reason
        if row.status in (PREHISTORY, ORIGIN_PRICE_MISSING):
            assert row.issues
        if row.status == TRAINING_INELIGIBLE:
            assert any(menu.issues and not menu.training_eligible for menu in row.menus)


def test_prehistory_boundary_is_the_last_fund_to_start(base: harness.Ledger) -> None:
    assert (base.boundary_month, base.boundary_fund, base.boundary_date) == (
        "2022-07",
        "Z",
        _d("2022-07-11"),
    )
    june = base.row("2022-06")
    assert _codes(june.issues) == [(PREHISTORY, "Z", _d("2022-07-11"))]
    # Prehistory months still carry their per-menu facts: the TSP menu is descriptive there.
    assert june.menu("tsp").training_eligible
    assert not june.menu("example").training_eligible


def test_inception_needs_the_fund_at_the_window_start_without_slack(base: harness.Ledger) -> None:
    june = base.row("2023-06")
    example = june.menu("example")
    assert june.origin == _d("2023-06-30")
    assert example.window_start == _d("2022-06-30")
    assert example.union_rows >= 252 and example.complete_rows >= 227
    assert _codes(example.issues) == [(FUND_AFTER_START, "Z", _d("2022-07-12"))]
    # Production's 10% inception slack would admit Z here (its first return is 7 rows in).
    truncated = {f: _base()[f].loc[lambda r: r["date"] <= "2023-06-30"] for f in MENUS["example"]}
    assert select_window(build_returns(truncated), "1y", _d("2023-06-30")).funds == ["X", "Y", "Z"]
    july = base.row("2023-07").menu("example")
    assert (july.window_start, july.window_rows, july.complete_rows) == (_d("2022-07-29"), 252, 252)
    assert july.training_eligible and july.issues == ()


def test_month_end_on_a_holiday_takes_the_last_session(base: harness.Ledger) -> None:
    assert base.row("2024-03").origin == _d("2024-03-28")  # Good Friday 2024-03-29
    assert base.row("2021-05").origin == _d("2021-05-28")  # Memorial Day 2021-05-31
    assert base.row("2022-12").origin == _d("2022-12-30")
    assert base.row("2026-09").origin == _d("2026-09-30")


def test_administrative_maturity_is_the_252nd_session_on_or_before_d_star(
    base: harness.Ledger,
) -> None:
    september = base.row("2025-09")
    assert (september.maturity_session, september.mature) == (_d("2026-10-01"), True)
    assert september.status == MATURE
    october = base.row("2025-10")
    assert (october.maturity_session, october.mature, october.status) == (
        _d("2026-11-03"),
        False,
        IMMATURE,
    )
    assert october.training_eligible and not october.in_realized_panel
    assert {menu.outcome for menu in october.menus} == {IMMATURE}
    assert october.menu("tsp").horizon_end is None


def test_horizon_is_the_next_252_union_dates_across_january(base: harness.Ledger) -> None:
    december = base.row("2023-12").menu("example")
    assert (december.horizon_start, december.horizon_end, december.horizon_rows) == (
        _d("2024-01-02"),
        _d("2024-12-31"),
        252,
    )
    later = base.row("2024-12").menu("tsp")  # crosses 2025-01-01 and the 2025-01-09 closure
    assert (later.horizon_start, later.horizon_end, later.outcome) == (
        _d("2025-01-02"),
        _d("2026-01-05"),
        COMPLETE,
    )


# ------------------------------------------------------------------- intervals and overlaps


def test_greedy_disjoint_intervals_and_exact_overlaps(base: harness.Ledger) -> None:
    for menu in MENUS:
        members = [row.origin for row in base.rows if row.menu(menu).disjoint]
        assert members == [_d("2023-07-31"), _d("2024-08-30"), _d("2025-09-30")]
    first = base.row("2023-07").menu("tsp")
    assert (first.overlap_prev_dates, first.overlap_origins) == (0, 11)
    # August 2023 has 23 sessions: consecutive 252-date horizons share 252 - 23 dates.
    assert base.row("2023-08").menu("tsp").overlap_prev_dates == 229
    assert base.row("2024-06").menu("example").overlap_origins == 23
    outside = base.row("2025-10").menu("tsp")
    assert (outside.disjoint, outside.overlap_prev_dates, outside.overlap_origins) == (
        False,
        None,
        None,
    )


def test_year_end_cohorts_are_not_automatically_disjoint(base: harness.Ledger) -> None:
    year_ends = harness.select_origins(base, "year-end")
    months = [row.month for row in year_ends.rows]
    assert months == ["2021-12", "2022-12", "2023-12", "2024-12", "2025-12"]
    assert year_ends.row("2025-12").status == IMMATURE
    # 2023-12-29's horizon ends 2024-12-31, so the next year-end origin is not strictly later:
    # the two cohorts share no return date, but the later one starts from the earlier one's last
    # price, and the greedy rule retains only an origin strictly after the retained horizon end.
    assert [row.origin for row in year_ends.rows if row.menu("tsp").disjoint] == [_d("2023-12-29")]
    nxt = year_ends.row("2024-12").menu("tsp")
    assert (nxt.disjoint, nxt.overlap_prev_dates, nxt.overlap_origins) == (False, 0, 0)


# -------------------------------------------------------------------------------- risk-free


def test_risk_free_source_follows_sgov_then_tsp_g_then_fallback(base: harness.Ledger) -> None:
    december = base.row("2021-12")  # 2021-12-31 is TSP-G's 251st return day
    assert (december.risk_free_source, december.risk_free_rate) == ("fallback", 0.04)
    january = base.row("2022-01")
    assert january.risk_free_source == "TSP-G"
    np.testing.assert_allclose(january.risk_free_rate, (1 + GROWTH["TSP-G"]) ** 252 - 1, rtol=1e-12)
    with_sgov = _ledger(_base(sgov_first="2023-01-30"))  # 252 returns by 2024-01-31, 231 before
    assert with_sgov.row("2023-12").risk_free_source == "TSP-G"
    sgov = with_sgov.row("2024-01")
    assert sgov.risk_free_source == "SGOV"
    np.testing.assert_allclose(sgov.risk_free_rate, (1 + GROWTH["SGOV"]) ** 252 - 1, rtol=1e-12)


# -------------------------------------------------------------------- missing and added days


def test_missing_training_day_also_loses_the_next_return() -> None:
    ledger = _ledger(_base(drop={"X": ["2024-02-15"]}))
    march = ledger.row("2024-03").menu("example")
    assert (march.union_rows, march.window_rows, march.complete_rows) == (814, 252, 250)
    assert march.training_eligible


def test_missing_future_day_makes_the_mature_horizon_incomplete() -> None:
    ledger = _ledger(_base(drop={"X": ["2024-02-15"]}))
    missing = _month_range("2023-07", "2024-01")
    for row in ledger.rows:
        if row.status != MATURE:
            continue
        example = row.menu("example")
        if row.month in missing:
            assert example.outcome == HORIZON_MISSING
            assert _codes(example.issues) == [(HORIZON_VALUE_MISSING, "X", _d("2024-02-15"))]
        else:
            assert example.outcome == COMPLETE
        assert row.menu("tsp").outcome == COMPLETE
    members = [row.origin for row in ledger.rows if row.menu("example").disjoint]
    assert members == [_d("2024-02-29"), _d("2025-03-31")]
    cov = harness.coverage(ledger)
    assert (cov.menu("example").complete, cov.menu("example").missing) == (20, 7)
    assert cov.gate("example_completeness").met is False
    assert cov.gate("tsp_completeness").met is True


def test_origin_price_missing_is_a_named_coverage_failure() -> None:
    ledger = _ledger(_base(drop={"Y": ["2024-03-28"]}))
    march = ledger.row("2024-03")
    assert march.status == ORIGIN_PRICE_MISSING
    assert _codes(march.issues) == [(ORIGIN_PRICE_MISSING, "Y", _d("2024-03-28"))]
    example = march.menu("example")
    assert not example.origin_priced and march.menu("tsp").origin_priced
    # The realized horizon needs the predecessor price too: no quote is backdated.
    assert example.outcome == HORIZON_MISSING
    assert _codes(example.issues) == [(PREDECESSOR_MISSING, "Y", _d("2024-03-28"))]
    cov = harness.coverage(ledger)
    assert cov.counts[ORIGIN_PRICE_MISSING] == 1 and cov.mature == 26
    # A whole menu closed at the origin: the date is not on its calendar at all.
    day = _d("2024-03-28")
    closed = {"TSP-G": ["2024-03-28"], "TSP-F": ["2024-03-28"]}
    march = _ledger(_base(drop=closed)).row("2024-03")
    assert _codes(march.issues) == [(ORIGIN_PRICE_MISSING, f, day) for f in ("TSP-G", "TSP-F")]
    tsp = march.menu("tsp")
    assert not tsp.origin_priced and tsp.horizon_start == _d("2024-04-01")
    assert _codes(tsp.issues) == [(PREDECESSOR_MISSING, f, day) for f in ("TSP-G", "TSP-F")]


def test_maturity_needs_sessions_past_d_star() -> None:
    records = _base()
    # The list ends 2026-12-31, after D*: a 252nd session beyond it is certainly after D*.
    ledger = harness.build_ledger(
        records, _days("2021-01-01", "2026-12-31"), BASE_D_STAR, MENUS, "1y"
    )
    assert ledger.row("2025-09").maturity_session == _d("2026-10-01")
    january = ledger.row("2026-01")
    assert (january.maturity_session, january.status) == (None, IMMATURE)
    # A list that stops at D* cannot decide the maturity of 2025-10-31.
    with pytest.raises(ValueError, match="2025-10-31 cannot be decided"):
        harness.build_ledger(records, _days("2021-01-01", BASE_D_STAR), BASE_D_STAR, MENUS, "1y")


def test_read_snapshot_hashes_the_bytes_it_reads(snapshot: Path, freeze: ModuleType) -> None:
    inputs = harness.read_snapshot(snapshot, freeze.verify_snapshot)
    assert (inputs.d_star, inputs.root) == (BASE_D_STAR, snapshot.resolve())
    assert inputs.menus == {"example": tuple(EXAMPLE), "tsp": tuple(TSP)}
    assert len(inputs.records) == 29 and inputs.sessions[0] == pd.Timestamp("2021-01-04")
    manifest = freeze.verify_snapshot(snapshot)
    forged = {
        **manifest,
        "files": [
            {**entry, "sha256": "0" * 64} if entry["path"] == "prices/VTI.parquet" else entry
            for entry in manifest["files"]
        ],
    }
    with pytest.raises(harness.SnapshotChanged, match="prices/VTI.parquet"):
        harness.read_snapshot(snapshot, lambda path: forged)


def test_union_calendar_horizon_counts_dates_not_xnys_sessions() -> None:
    ledger = _ledger(_base(add={"TSP-G": ["2024-03-29"], "TSP-F": ["2024-03-29"]}))
    march = ledger.row("2024-03")
    assert march.origin == _d("2024-03-28")
    tsp, example = march.menu("tsp"), march.menu("example")
    assert (tsp.horizon_start, tsp.horizon_end) == (_d("2024-03-29"), _d("2025-03-31"))
    assert (example.horizon_start, example.horizon_end) == (_d("2024-04-01"), _d("2025-04-01"))
    assert tsp.outcome == example.outcome == COMPLETE


def test_mature_horizon_short_of_union_dates() -> None:
    closed = {"TSP-G": ["2025-10-13", "2025-11-11"], "TSP-F": ["2025-10-13", "2025-11-11"]}
    ledger = _ledger(_base(drop=closed))
    tsp = ledger.row("2025-09").menu("tsp")
    assert (tsp.outcome, tsp.horizon_start, tsp.horizon_end, tsp.horizon_rows) == (
        HORIZON_MISSING,
        _d("2025-10-01"),
        None,
        250,
    )
    assert _codes(tsp.issues) == [(HORIZON_DATES_SHORT, None, None)]
    assert ledger.row("2025-09").menu("example").outcome == COMPLETE
    assert ledger.row("2025-08").menu("tsp").horizon_end == _d("2026-09-03")
    assert harness.coverage(ledger).menu("tsp").complete == 26


def test_mature_horizon_past_d_star_never_reads_later_data(base: harness.Ledger) -> None:
    closed = {"TSP-G": ["2025-10-13", "2025-11-11"], "TSP-F": ["2025-10-13", "2025-11-11"]}
    ledger = _ledger(_base(last="2026-10-08", drop=closed))
    september = ledger.row("2025-09")
    tsp = september.menu("tsp")
    assert (tsp.outcome, tsp.horizon_end, tsp.horizon_rows) == (
        HORIZON_MISSING,
        _d("2026-10-05"),
        252,
    )
    assert _codes(tsp.issues) == [(HORIZON_PAST_D_STAR, None, _d("2026-10-05"))]
    example = september.menu("example")
    assert (example.outcome, example.horizon_end) == (COMPLETE, _d("2026-10-01"))
    assert ledger.row("2025-10").status == IMMATURE
    # Prices after the origin change no training fact of that origin.
    before = base.row("2025-09")
    for name in MENUS:
        old, new = before.menu(name), september.menu(name)
        assert (old.union_rows, old.window_start, old.complete_rows, old.training_eligible) == (
            new.union_rows,
            new.window_start,
            new.complete_rows,
            new.training_eligible,
        )
    assert (before.risk_free_source, before.risk_free_rate) == (
        september.risk_free_source,
        september.risk_free_rate,
    )


def test_undercovered_window_is_rejected_at_ninety_percent() -> None:
    holes = [_shifted("2024-06-28", -240 + 3 * k) for k in range(13)]
    kept = _ledger(_base(drop={"X": holes[:12]})).row("2024-06")
    assert kept.menu("example").complete_rows == 228 and kept.status == MATURE
    rejected = _ledger(_base(drop={"X": holes})).row("2024-06")
    example = rejected.menu("example")
    assert example.complete_rows == 226 and not example.training_eligible
    assert _codes(example.issues) == [(COMPLETE_ROWS_SHORT, None, None)]
    assert rejected.status == TRAINING_INELIGIBLE
    assert rejected.menu("tsp").training_eligible  # the other menu alone never qualifies


def test_short_union_calendar_and_late_existence() -> None:
    records = {fund: _fund("2024-01-02", "2025-06-30", GROWTH[fund]) for fund in BASE_FIRST}
    ledger = _ledger(records, d_star=date(2025, 6, 30))
    assert [row.month for row in ledger.rows] == _month_range("2024-01", "2025-06")
    october = ledger.row("2024-10").menu("tsp")  # 211 rows: 210 complete, under 227
    assert (october.union_rows, october.complete_rows) == (211, 210)
    assert [code for code, _, _ in _codes(october.issues)] == [
        UNION_ROWS_SHORT,
        FUND_AFTER_START,
        FUND_AFTER_START,
        COMPLETE_ROWS_SHORT,
    ]
    november = ledger.row("2024-11").menu("tsp")  # 231 rows: 230 complete, enough
    assert (november.union_rows, november.complete_rows) == (231, 230)
    assert [code for code, _, _ in _codes(november.issues)] == [
        UNION_ROWS_SHORT,
        FUND_AFTER_START,
        FUND_AFTER_START,
    ]
    december = ledger.row("2024-12").menu("tsp")  # 252 union rows, but no return on row 0
    assert december.union_rows == 252 and december.complete_rows == 251
    assert _codes(december.issues) == [
        (FUND_AFTER_START, "TSP-G", _d("2024-01-03")),
        (FUND_AFTER_START, "TSP-F", _d("2024-01-03")),
    ]
    assert ledger.row("2025-01").menu("tsp").training_eligible
    assert ledger.row("2025-01").status == IMMATURE


def test_prices_after_an_origin_never_change_its_training_facts(base: harness.Ledger) -> None:
    records = _base()
    shocked = records["X"].copy()
    later = shocked["date"] > pd.Timestamp("2024-03-28")
    shocked.loc[later, "tr_index"] = shocked.loc[later, "tr_index"] * 1.5
    records["X"] = shocked
    records["Y"] = records["Y"].loc[records["Y"]["date"] <= pd.Timestamp("2025-01-15")]
    records["Y"] = pd.concat(
        [records["Y"], _fund("2025-01-21", BASE_D_STAR, GROWTH["Y"])], ignore_index=True
    )
    after = _ledger(records).row("2024-03")
    before = base.row("2024-03")
    assert (after.status, after.risk_free_source, after.risk_free_rate) == (
        before.status,
        before.risk_free_source,
        before.risk_free_rate,
    )
    for name in MENUS:
        old, new = before.menu(name), after.menu(name)
        assert (old.union_rows, old.window_start, old.window_rows, old.complete_rows) == (
            new.union_rows,
            new.window_start,
            new.window_rows,
            new.complete_rows,
        )
        assert old.training_eligible == new.training_eligible
    assert before.menu("example").outcome == COMPLETE
    assert after.menu("example").outcome == HORIZON_MISSING  # Y lacks 2025-01-16 and -17


# ------------------------------------------------------------------- five-year window, §10


def test_five_year_window_thresholds(long5y: harness.Ledger) -> None:
    december = long5y.row("2019-12").menu("example")
    assert december.union_rows == 1258 and UNION_ROWS_SHORT in [i.code for i in december.issues]
    january = long5y.row("2020-01").menu("example")
    assert (january.union_rows, january.window_rows, january.complete_rows) == (1279, 1260, 1260)
    assert january.training_eligible
    holes = [_shifted("2022-06-30", -1200 + 3 * k) for k in range(64)]
    for count, rows, eligible in ((63, 1134, True), (64, 1132, False)):
        ledger = _ledger(_long(holes[:count]), d_star=LONG_D_STAR, lookback="5y", menus=LONG_MENUS)
        june = ledger.row("2022-06").menu("example")
        assert (june.window_start, june.complete_rows) == (_d("2017-06-29"), rows)
        assert june.training_eligible is eligible


def test_validation_origins_are_derived_subsets(long5y: harness.Ledger) -> None:
    quarters = harness.validation_origins(long5y, "quarter-end")
    assert [row.origin.isoformat() for row in quarters.rows] == QUARTER_ENDS
    assert quarters.origins == "quarter-end"
    for menu in LONG_MENUS:
        members = [row.origin.isoformat() for row in quarters.rows if row.menu(menu).disjoint]
        assert members == ["2020-03-31", "2021-06-30", "2022-09-30", "2023-12-29", "2025-03-31"]
    years = harness.validation_origins(long5y, "year-end")
    assert [row.origin.isoformat() for row in years.rows] == YEAR_ENDS
    members = [row.origin.isoformat() for row in years.rows if row.menu("tsp").disjoint]
    assert members == ["2020-12-31", "2022-12-30", "2024-12-31"]
    monthly = harness.validation_origins(long5y, "monthly")
    assert len(monthly.rows) == 141
    with pytest.raises(ValueError, match="2015-12"):
        harness.validation_origins(_ledger(_base()), "quarter-end")
    with pytest.raises(ValueError, match="weekly"):
        harness.select_origins(long5y, "weekly")
    with pytest.raises(ValueError, match="weekly"):
        harness.validation_origins(long5y, "weekly")
    with pytest.raises(ValueError, match="monthly ledger"):
        harness.select_origins(years, "monthly")


# --------------------------------------------------------------------------------- coverage


def test_coverage_reports_every_gate(base: harness.Ledger) -> None:
    cov = harness.coverage(base)
    assert (cov.months, cov.scheduled, cov.mature) == (69, 39, 27)
    assert cov.counts == {
        PREHISTORY: 18,
        ORIGIN_PRICE_MISSING: 0,
        TRAINING_INELIGIBLE: 12,
        IMMATURE: 12,
        MATURE: 27,
    }
    for menu in MENUS:
        summary = cov.menu(menu)
        assert (summary.complete, summary.missing, summary.unexplained, summary.disjoint) == (
            27,
            0,
            0,
            3,
        )
        assert cov.gate(f"{menu}_completeness").value == 1.0
        assert cov.gate(f"{menu}_completeness").met is True
        assert cov.gate(f"{menu}_disjoint_intervals").met is False
    assert (cov.gate("mature_origins").value, cov.gate("mature_origins").met) == (27, False)
    assert cov.gate("scheduled_origins").met is True
    assert cov.met is False
    for lookup in (base.row, base.rows[0].menu, cov.menu, cov.gate):
        with pytest.raises(KeyError):
            lookup("nope")


def test_coverage_gates_met_and_the_resource_ceiling(long5y: harness.Ledger) -> None:
    cov = harness.coverage(long5y)
    assert (cov.scheduled, cov.mature) == (81, 69)
    assert [cov.menu(m).disjoint for m in LONG_MENUS] == [6, 6]
    assert all(gate.met for gate in cov.gates) and cov.met is True
    wide = harness.coverage(_ledger(_long(), d_star=LONG_D_STAR, lookback="1y", menus=LONG_MENUS))
    assert (wide.scheduled, wide.mature) == (129, 117)
    assert wide.gate("scheduled_origins").met is False and wide.met is False
    subset = harness.coverage(harness.validation_origins(long5y, "year-end"))
    assert subset.months == 10 and subset.met is None
    assert {gate.met for gate in subset.gates} == {None}


def test_ledger_frame_has_the_documented_schema(base: harness.Ledger) -> None:
    frame = harness.ledger_frame(base)
    assert list(frame.columns) == LEDGER_COLUMNS
    assert len(frame) == 69 * 2
    row = frame[(frame["month"] == "2024-03") & (frame["menu"] == "example")].iloc[0]
    assert row["origin"] == pd.Timestamp("2024-03-28") and row["status"] == MATURE
    assert row["funds"] == "X,Y,Z" and row["horizon_end"] == pd.Timestamp("2025-04-01")
    prehistory = frame[frame["month"] == "2021-01"].iloc[0]
    assert json.loads(prehistory["month_issues"])[0]["code"] == PREHISTORY
    assert pd.isna(frame[frame["month"] == "2026-09"].iloc[0]["horizon_end"])


def test_inputs_are_validated() -> None:
    with pytest.raises(ValueError, match="lookback"):
        _ledger(_base(), lookback="7y")
    with pytest.raises(ValueError, match="W"):
        _ledger(_base(), menus={"tsp": ("TSP-G", "W")})
    records = _base()
    duplicated = {**records, "X": pd.concat([records["X"], records["X"].iloc[[5]]])}
    with pytest.raises(ValueError, match="X: price record dates"):
        _ledger(duplicated)
    with pytest.raises(ValueError, match="at least one menu"):
        _ledger(records, menus={})
    with pytest.raises(ValueError, match="once each"):
        _ledger(records, menus={"tsp": ("TSP-G", "TSP-G")})
    with pytest.raises(ValueError, match="lacks"):
        _ledger({**records, "X": records["X"].drop(columns="tr_index")})
    with pytest.raises(ValueError, match="no rows"):
        _ledger({**records, "X": records["X"].iloc[:0]})
    sessions = _xnys()
    gap = pd.DatetimeIndex(sessions[(sessions < "2021-02-01") | (sessions > "2021-02-28")])
    with pytest.raises(ValueError, match="no session in 2021-02"):
        harness.build_ledger(records, gap, BASE_D_STAR, MENUS, "1y")
    with pytest.raises(ValueError, match="strictly increasing"):
        harness.build_ledger(records, sessions[::-1], BASE_D_STAR, MENUS, "1y")
    with pytest.raises(ValueError, match="not a date"):
        harness.build_ledger(records, [None, *sessions], BASE_D_STAR, MENUS, "1y")
    empty = _ledger(records, d_star=date(2021, 1, 15))  # no month-end on or before D*
    assert empty.rows == () and harness.select_origins(empty, "year-end").rows == ()
    assert harness.coverage(empty).months == 0 and harness.coverage(empty).met is False
    assert len(harness.ledger_frame(empty)) == 0


# ---------------------------------------------------------------------------------- the CLI


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    return _load("backtest_ranges", SCRIPT)


@pytest.fixture(scope="module")
def freeze() -> ModuleType:
    return _load("freeze_research_inputs", FREEZE)


def _close(path: Path) -> None:
    for top, dirs, files in os.walk(path, topdown=False):
        for name in (*files, *dirs):
            entry = Path(top) / name
            entry.chmod(entry.stat().st_mode & ~0o222)
    path.chmod(path.stat().st_mode & ~0o222)


def _snapshot(
    base: Path, freeze: ModuleType, records: dict[str, pd.DataFrame], d_star: date
) -> Path:
    """A snapshot written by the freeze script's own builder from in-memory inputs."""
    sources, catalog = [], {}
    for symbol, frame in records.items():
        buffer = io.BytesIO()
        frame.to_parquet(buffer, index=False)
        read = functools.partial(bytes, buffer.getvalue())
        sources.append(freeze.Source(f"prices/{symbol}.parquet", "mirror", read))
        last = frame["date"].max().date().isoformat()
        catalog[symbol] = {
            "name": symbol,
            "kind": "tsp" if symbol.startswith("TSP-") else "etf",
            "tier": 1,
            "source": "tsp" if symbol.startswith("TSP-") else "tiingo",
            "first_date": frame["date"].min().date().isoformat(),
            "last_date": last,
            "adjusted_through": last,
            "status": "ok",
        }
    presets = {"presets": [{"id": "tsp", "funds": TSP}, {"id": "guide2017", "funds": EXAMPLE}]}
    for path, body in (
        ("meta/manifest.json", {"symbols": catalog}),
        ("meta/lake.json", {"symbols": {}}),
        ("data/presets.json", presets),
    ):
        read = functools.partial(bytes, json.dumps(body).encode())
        sources.append(freeze.Source(path, "mirror", read))
    work = base / ".work"
    work.mkdir(parents=True)
    digest = freeze.build_snapshot(
        work,
        sources=sorted(sources, key=lambda source: source.path),
        mirror=base / "mirror",
        head="0" * 40,
        repo_dirty=False,
        d_star=d_star,
        calendar_end=date(2027, 12, 31),
    )
    final = base / f"{d_star.isoformat()}-{digest[:12]}"
    work.rename(final)
    _close(final)
    return final


def _menu_records(first: dict[str, str], last: date) -> dict[str, pd.DataFrame]:
    records = {}
    for number, symbol in enumerate([*TSP, *EXAMPLE, "SGOV"]):
        start = first.get(symbol, "2021-01-04")
        records[symbol] = _record(_days(start, last), 1e-4 * (1 + number % 7))
    return records


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory: pytest.TempPathFactory, freeze: ModuleType) -> Path:
    records = _menu_records({"VWOB": "2022-07-11", "SGOV": "2023-01-30"}, BASE_D_STAR)
    return _snapshot(tmp_path_factory.mktemp("snap"), freeze, records, BASE_D_STAR)


@pytest.fixture(scope="module")
def long_snapshot(tmp_path_factory: pytest.TempPathFactory, freeze: ModuleType) -> Path:
    records = _menu_records({f: "2015-01-02" for f in [*TSP, *EXAMPLE]}, LONG_D_STAR)
    records.pop("SGOV")
    return _snapshot(tmp_path_factory.mktemp("long"), freeze, records, LONG_D_STAR)


def test_cli_ledger_writes_the_table(cli: ModuleType, snapshot: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "origins.parquet"
    assert (
        cli.main(["ledger", "--store-dir", str(snapshot), "--lookbacks", "1y", "--out", str(out)])
        == 0
    )
    frame = pd.read_parquet(out)
    assert list(frame.columns) == LEDGER_COLUMNS
    assert sorted(set(frame["menu"])) == ["example", "tsp"] and len(frame) == 69 * 2
    statuses = frame.loc[frame["menu"] == "tsp", "status"].value_counts().to_dict()
    assert statuses == {PREHISTORY: 18, TRAINING_INELIGIBLE: 12, MATURE: 27, IMMATURE: 12}
    sgov = frame[(frame["month"] == "2024-01") & (frame["menu"] == "tsp")].iloc[0]
    assert sgov["risk_free_source"] == "SGOV"
    assert frame[frame["month"] == "2023-12"].iloc[0]["risk_free_source"] == "TSP-G"


def test_cli_coverage_prints_and_writes_the_gates(
    cli: ModuleType, snapshot: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "coverage.json"
    args = ["coverage", "--store-dir", str(snapshot), "--lookbacks", "1y"]
    assert cli.main([*args, "--out", str(out)]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert "scheduled common training-eligible origins: 39 (<= 120: met)" in printed
    assert "mature common training-eligible origins: 27 (>= 60: NOT met)" in printed
    assert "tsp complete outcomes: 27 of 27 = 100.0% (>= 95%: met)" in printed
    assert "example disjoint intervals: 3 (>= 5: NOT met)" in printed
    assert "evidence gate: NOT met" in printed
    report = json.loads(out.read_text(encoding="utf-8"))
    assert [entry["lookback"] for entry in report] == ["1y"]
    assert report[0]["mature"] == 27 and report[0]["met"] is False
    # A narrower fixed menu is its own ledger: the TSP funds start 2021-01-04, so no prehistory.
    assert cli.main([*args, "--menus", "tsp", "--lookbacks", "5y,1y"]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert "scheduled common training-eligible origins: 57 (<= 120: met)" in printed
    assert "mature common training-eligible origins: 45 (>= 60: NOT met)" in printed
    assert "tsp disjoint intervals: 4 (>= 5: NOT met)" in printed
    assert not any(line.startswith("example") for line in printed)


def test_cli_quarter_end_origins(cli: ModuleType, long_snapshot: Path, tmp_path: Path) -> None:
    out = tmp_path / "quarters.csv"
    argv = ["ledger", "--store-dir", str(long_snapshot), "--origins", "quarter-end"]
    assert cli.main([*argv, "--menus", "tsp", "--out", str(out)]) == 0
    frame = pd.read_csv(out)
    assert list(frame["origin"]) == QUARTER_ENDS
    assert set(frame["lookback"]) == {"5y"} and set(frame["menu"]) == {"tsp"}
    assert set(frame["origins"]) == {"quarter-end"}


def test_cli_refuses_a_snapshot_that_fails_verification(
    cli: ModuleType, snapshot: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = snapshot / "prices" / "VTI.parquet"
    mode = target.stat().st_mode
    target.chmod(mode | stat.S_IWUSR)
    try:
        out = tmp_path / "origins.parquet"
        args = ["ledger", "--store-dir", str(snapshot), "--lookbacks", "1y", "--out", str(out)]
        assert cli.main(args) == 6
    finally:
        target.chmod(mode)
    assert "prices/VTI.parquet: writable" in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize(
    "extra",
    [["--lookbacks", "7y"], ["--menus", "nope"], ["--origins", "weekly"], ["--lookbacks", ""]],
)
def test_cli_rejects_unknown_arguments(
    cli: ModuleType, snapshot: Path, tmp_path: Path, extra: list[str]
) -> None:
    out = tmp_path / "origins.parquet"
    with pytest.raises(SystemExit) as raised:
        cli.main(["ledger", "--store-dir", str(snapshot), "--out", str(out), *extra])
    assert raised.value.code == 2 and not out.exists()


def test_cli_refuses_to_write_into_the_snapshot(
    cli: ModuleType, snapshot: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = snapshot / "origins.parquet"
    assert cli.main(["ledger", "--store-dir", str(snapshot), "--out", str(out)]) == 2
    assert "inside" in capsys.readouterr().err


# The harness's half of A-SE-02: the CLI runs in a child with the store, provider, lake and QSE
# modules blocked as tests/test_dependencies.py blocks them (`None` in sys.modules), and an audit
# hook records, and refuses, any import of them, any socket call, any open under the mirror, the
# lake, the secrets or the real snapshot root, and any write outside the output directory, even
# when the calling code catches the error. A control run proves the hook sees caught attempts.
BLOCKED_MODULES = [
    "boto3",
    "botocore",
    "requests",
    "urllib3",
    "yfinance",
    "qse",
    "portfoliosight.data.store",
    "portfoliosight.data.manifest",
    "portfoliosight.data.lake",
    "portfoliosight.data.providers",
    "portfoliosight.data.download",
    "portfoliosight.data.secrets",
]
FORBIDDEN_ROOTS = [
    "/mnt/d/portfoliosight-data",
    os.path.expanduser("~/tft-quantile-forecaster"),
    os.path.expanduser("~/.secrets"),
    os.path.expanduser("~/portfoliosight-research"),
]
BLOCKED_CHILD = r"""
import json, os, sys
root, argv, forbidden, blocked, writable, control = (
    sys.argv[1], json.loads(sys.argv[2]), json.loads(sys.argv[3]), json.loads(sys.argv[4]),
    sys.argv[5], sys.argv[6] == "1",
)
sys.path.insert(0, root)
for name in blocked:
    sys.modules[name] = None
attempts = []
WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

def hook(event, args):
    if event == "import":
        if any(args[0] == name or args[0].startswith(name + ".") for name in blocked):
            attempts.append(["import", args[0]])
    elif event.startswith("socket."):
        attempts.append([event])
        raise PermissionError(event)
    elif event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        path = os.path.abspath(os.fsdecode(args[0]))
        inside = any(path == p or path.startswith(p + os.sep) for p in forbidden)
        writes = isinstance(args[2], int) and args[2] & WRITE
        if inside or (writes and not path.startswith(writable + os.sep)):
            attempts.append(["open", path])
            raise PermissionError(path)

sys.addaudithook(hook)
import importlib.util
script = os.path.join(root, "scripts", "backtest_ranges.py")
spec = importlib.util.spec_from_file_location("backtest_ranges", script)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
codes = [module.main(args) for args in argv]
if control:
    import socket
    probes = (
        lambda: __import__("boto3"),
        lambda: socket.create_connection(("127.0.0.1", 9), timeout=1),
        lambda: open(os.path.join(forbidden[0], "probe"), "rb"),
    )
    for probe in probes:
        try:
            probe()
        except Exception:
            pass
print(json.dumps({"codes": codes, "attempts": attempts}))
"""


def _run_blocked(argv: list[list[str]], writable: Path, control: bool) -> dict:
    env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
    env["MKL_NUM_THREADS"] = "1"
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            BLOCKED_CHILD,
            str(ROOT),
            json.dumps(argv),
            json.dumps(FORBIDDEN_ROOTS),
            json.dumps(BLOCKED_MODULES),
            str(writable),
            "1" if control else "0",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_harness_runs_with_store_provider_and_qse_routes_blocked(
    snapshot: Path, tmp_path: Path
) -> None:
    out = tmp_path / "run"
    argv = [
        ["ledger", "--store-dir", str(snapshot), "--lookbacks", "1y", "--out", f"{out}/o.parquet"],
        ["coverage", "--store-dir", str(snapshot), "--lookbacks", "1y", "--out", f"{out}/c.json"],
    ]
    report = _run_blocked(argv, out, control=False)
    assert report == {"codes": [0, 0], "attempts": []}
    assert len(pd.read_parquet(out / "o.parquet")) == 69 * 2
    assert json.loads((out / "c.json").read_text(encoding="utf-8"))[0]["mature"] == 27
    control = _run_blocked([], out, control=True)
    assert [attempt[0] for attempt in control["attempts"]] == [
        "import",
        "socket.getaddrinfo",
        "open",
    ]


# --------------------------------------------------------------------------------- boundary


def _imports(source: str, path: Path) -> list[str]:
    """Absolute names a module at ``path`` imports, relative imports resolved."""
    package = list(path.relative_to(ROOT).with_suffix("").parts[:-1])
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join([*base, *(node.module or "").split(".")]).strip(".")
            found += [module] + [f"{module}.{alias.name}" for alias in node.names]
    return found


def _research(names: list[str]) -> list[str]:
    return [name for name in names if name.split(".")[:2] == ["portfoliosight", "research"]]


def test_production_packages_never_import_research() -> None:
    planted = ROOT / "portfoliosight" / "engine" / "probe.py"
    for source in (
        "from ..research import harness",
        "from .. import research",
        "import portfoliosight.research.harness as h",
    ):
        assert _research(_imports(source, planted)), source
    assert not _research(_imports("from . import stats\nimport numpy", planted))
    scanned = 0
    for package in ("engine", "api", "jobs"):
        for path in sorted((ROOT / "portfoliosight" / package).rglob("*.py")):
            scanned += 1
            assert not _research(_imports(path.read_text(encoding="utf-8"), path)), path
    assert scanned >= 20
