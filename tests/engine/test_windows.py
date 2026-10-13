"""Lookback windows, inclusion, the 126-row floor and the exclusion reasons (spec 4.2, 5.6)."""

from __future__ import annotations

import re
from datetime import date
from typing import cast

import numpy as np
import pandas as pd
import pytest

from portfoliosight.engine import stats
from portfoliosight.engine.windows import (
    LOOKBACK_ROWS,
    MIN_ROWS,
    UNAVAILABLE_MESSAGE,
    renormalize_allocation,
    select_window,
)

ASOF = "2026-06-30"
DATE = r"\d{4}-\d{2}-\d{2}"
TEMPLATES = [
    r"no data",
    rf"converted to an ETF; no data since {DATE}",
    rf"no data since {DATE}",
    rf"corporate actions not yet verified after {DATE}",
    rf"history starts {DATE}, not enough for the [0-9A-Za-z-]+ view",
]
OK = {"status": "ok", "reason": None, "adjusted_through": ASOF, "last_date": ASOF}


def _frame(ids: list[str], rows: int = 1500, seed: int = 3501) -> pd.DataFrame:
    index = pd.bdate_range(end=ASOF, periods=rows, name="date")
    rng = np.random.default_rng(seed)
    return pd.DataFrame(rng.normal(0.0003, 0.01, (rows, len(ids))), index=index, columns=ids)


def _starting_at(frame: pd.DataFrame, fund: str, row: int) -> pd.DataFrame:
    frame.iloc[:row, frame.columns.get_loc(fund)] = np.nan
    return frame


def _sample(selection) -> pd.DataFrame:
    assert selection.sample is not None
    return selection.sample


def _day(frame: pd.DataFrame, row: int) -> date:
    return cast(pd.Timestamp, frame.index[row]).date()


def _reasons(selection) -> dict[str, str]:
    assert all(set(entry) == {"id", "reason"} for entry in selection.excluded)
    for entry in selection.excluded:
        assert any(re.fullmatch(t, entry["reason"]) for t in TEMPLATES), entry
    return {entry["id"]: entry["reason"] for entry in selection.excluded}


def test_lookback_ids_and_lengths():
    assert LOOKBACK_ROWS == {"1y": 252, "2y": 504, "3y": 756, "5y": 1260, "10y": 2520, "ew": 1260}
    assert MIN_ROWS == 126 and UNAVAILABLE_MESSAGE == "not enough shared history"
    frame = _frame(["AAA", "BBB"], rows=2600)
    for lookback, rows in LOOKBACK_ROWS.items():
        selection = select_window(frame, lookback, ASOF)
        assert selection.status == "ready" and selection.message == ""
        assert selection.lookback == lookback and selection.rows == rows == len(_sample(selection))
        assert selection.start == _day(frame, -rows) and selection.end == date(2026, 6, 30)
        assert _sample(selection).index[-1] == frame.index[-1]
        assert selection.funds == ["AAA", "BBB"] and selection.excluded == []
        if lookback == "ew":
            assert selection.omega is not None
            assert np.array_equal(selection.omega, stats.ew_weights(rows))
        else:
            assert selection.omega is None


@pytest.mark.parametrize(("lookback", "last_included"), [("5y", 126), ("1y", 25), ("10y", 252)])
def test_inclusion_boundary_is_ten_percent_of_the_window(lookback, last_included):
    frame = _frame(["AAA", "BBB", "EDGE", "LATE"], rows=2700)
    start = len(frame) - LOOKBACK_ROWS[lookback]
    _starting_at(frame, "EDGE", start + last_included)
    _starting_at(frame, "LATE", start + last_included + 1)
    selection = select_window(frame, lookback, ASOF)
    assert selection.funds == ["AAA", "BBB", "EDGE"]
    label = {"5y": "5-year", "1y": "1-year", "10y": "10-year"}[lookback]
    late_day = _day(frame, start + last_included + 1).isoformat()
    assert _reasons(selection) == {
        "LATE": f"history starts {late_day}, not enough for the {label} view"
    }
    # the sample is the intersection: it starts where the youngest included fund starts
    sample = _sample(selection)
    assert sample.index[0] == frame.index[start + last_included]
    assert selection.rows == LOOKBACK_ROWS[lookback] - last_included
    assert list(sample.columns) == selection.funds
    assert not sample.isna().any().any()
    assert selection.start == _day(frame, start)


def test_ew_view_has_its_own_name_in_the_reason():
    frame = _starting_at(_frame(["AAA", "BBB", "LATE"]), "LATE", 1400)
    reasons = _reasons(select_window(frame, "ew", ASOF))
    assert reasons["LATE"].endswith("not enough for the recent-weighted view")


def test_rows_after_asof_are_never_used():
    frame = _frame(["AAA", "BBB"], rows=1600)
    cut = pd.Timestamp(_day(frame, -41))
    selection = select_window(frame, "1y", cut.date())
    sample = _sample(selection)
    assert sample.index[-1] == cut and selection.end == cut.date()
    assert sample.index[0] == frame.index[-41 - 251]
    for asof in (cut, cut.isoformat(), str(cut.date())):
        assert _sample(select_window(frame, "1y", asof)).equals(sample)


def test_calendar_shorter_than_the_window_counts_positions_from_the_window_start():
    frame = _frame(["AAA", "BBB", "EDGE", "LATE"], rows=1200)  # 60 rows short of 5y
    _starting_at(frame, "EDGE", 66)  # position 126 of the window
    _starting_at(frame, "LATE", 67)  # position 127
    selection = select_window(frame, "5y", ASOF)
    assert selection.funds == ["AAA", "BBB", "EDGE"] and list(_reasons(selection)) == ["LATE"]
    assert selection.start == _day(frame, 0) and selection.rows == 1200 - 66
    # a menu of young funds: the one-year view builds, the five-year view is unavailable
    young = _frame(["AAA", "BBB", "CCC"], rows=300)
    assert select_window(young, "1y", ASOF).status == "ready"
    five = select_window(young, "5y", ASOF)
    assert five.status == "unavailable" and five.message == "not enough shared history"
    assert five.funds == [] and five.sample is None and five.rows == 0 and five.omega is None
    assert set(_reasons(five)) == {"AAA", "BBB", "CCC"}


def test_unserved_funds_are_excluded_with_a_catalog_reason():
    ids = ["AAA", "BBB", "ETF", "GONE", "NONE", "STALE", "PEND", "LOST", "ODD", "NEW", "MISSING"]
    frame = _frame(ids)
    catalog = {fund: dict(OK) for fund in ids if fund != "MISSING"}
    catalog["ETF"] = {
        "status": "unavailable",
        "reason": "converted to an ETF; no data since 2024-10-30",
        "adjusted_through": "2024-10-30",
        "last_date": "2024-10-30",
    }
    catalog["GONE"] = {"status": "unavailable", "reason": "no data since 2025-01-15"}
    catalog["NONE"] = {"status": "unavailable", "reason": "no data"}
    catalog["STALE"] = {
        "status": "stale",
        "reason": None,
        "adjusted_through": "2026-06-10",
        "last_date": ASOF,
    }
    catalog["PEND"] = {
        "status": "pending",
        "reason": "seeded; tail not refreshed",
        "adjusted_through": pd.Timestamp("2026-02-27"),
        "last_date": date(2026, 6, 29),
    }
    catalog["LOST"] = {
        "status": "unavailable",
        "reason": "HTTP 404",
        "adjusted_through": "2025-03-03",
        "last_date": date(2025, 3, 4),
    }
    catalog["ODD"] = {"status": "unavailable", "reason": 404, "last_date": pd.NaT}
    catalog["NEW"] = {"status": "pending", "reason": None, "last_date": "2026-06-29"}
    catalog["AAA"] = {  # the catalog's own sentence is kept as it is, date included
        "status": "pending",
        "reason": "corporate actions not yet verified after 2026-02-27",
        "adjusted_through": "2026-03-15",
    }
    selection = select_window(frame, "5y", ASOF, catalog)
    assert selection.status == "unavailable" and selection.funds == ["BBB"]
    assert _reasons(selection) == {
        "AAA": "corporate actions not yet verified after 2026-02-27",
        "ETF": "converted to an ETF; no data since 2024-10-30",
        "GONE": "no data since 2025-01-15",
        "NONE": "no data",
        "STALE": "corporate actions not yet verified after 2026-06-10",
        "PEND": "corporate actions not yet verified after 2026-02-27",
        "LOST": "no data since 2025-03-04",
        "ODD": "no data",
        "NEW": "no data since 2026-06-29",
        "MISSING": "no data",
    }
    assert [entry["id"] for entry in selection.excluded] == ["AAA", *ids[2:]]  # menu order
    # an unserved fund does not cut the sample, whatever its returns look like
    catalog["AAA"] = dict(OK)
    assert select_window(frame, "5y", ASOF, catalog).rows == 1260
    catalog["STALE"] = dict(OK)
    assert select_window(frame, "5y", ASOF, catalog).funds == ["AAA", "BBB", "STALE"]


def test_a_fund_without_any_return_has_no_data():
    frame = _frame(["AAA", "BBB", "EMPTY"])
    frame["EMPTY"] = np.nan
    selection = select_window(frame, "5y", ASOF)
    assert selection.funds == ["AAA", "BBB"] and _reasons(selection) == {"EMPTY": "no data"}
    nothing = select_window(frame, "5y", "1999-01-04")
    assert nothing.status == "unavailable" and nothing.start is None
    assert _reasons(nothing) == {"AAA": "no data", "BBB": "no data", "EMPTY": "no data"}


@pytest.mark.parametrize(
    ("shared", "status"),
    [(100, "unavailable"), (125, "unavailable"), (126, "ready"), (400, "ready")],
)
def test_window_needs_126_shared_rows(shared, status):
    frame = _frame(["AAA", "BBB", "GONE"])
    frame.iloc[240 + shared :, frame.columns.get_loc("GONE")] = np.nan
    selection = select_window(frame, "5y", ASOF)
    assert selection.status == status
    assert selection.funds == ["AAA", "BBB", "GONE"]  # served and old enough: included
    if status == "ready":
        assert selection.rows == shared == len(_sample(selection))
    else:
        assert selection.message == "not enough shared history" and selection.sample is None
        assert selection.rows == shared
    assert select_window(frame, "1y", _day(frame, 240 + shared - 1)).status == "ready"


def test_one_included_fund_is_not_a_menu():
    frame = _starting_at(_frame(["AAA", "LATE"]), "LATE", 1400)
    selection = select_window(frame, "5y", ASOF)
    assert selection.status == "unavailable" and selection.funds == ["AAA"]
    assert selection.message == "not enough shared history" and selection.sample is None


def test_bad_inputs_are_refused():
    frame = _frame(["AAA", "BBB"])
    with pytest.raises(ValueError, match="unknown lookback"):
        select_window(frame, "7y", ASOF)
    with pytest.raises(ValueError, match="asof must be a date"):
        select_window(frame, "5y", None)
    with pytest.raises(ValueError, match="DatetimeIndex"):
        select_window(frame.reset_index(drop=True), "5y", ASOF)
    with pytest.raises(ValueError, match="increasing"):
        select_window(frame.iloc[::-1], "5y", ASOF)
    with pytest.raises(ValueError, match="increasing"):
        select_window(pd.concat([frame.iloc[:5], frame.iloc[4:]]), "5y", ASOF)
    with pytest.raises(ValueError, match="more than once"):
        select_window(pd.concat([frame, frame[["AAA"]]], axis=1), "5y", ASOF)


def _renormalized(weights: dict, included: list[str]) -> tuple[dict[str, float], float]:
    kept, set_aside = renormalize_allocation(weights, included)
    assert kept is not None
    return kept, set_aside


def test_renormalize_allocation_reports_the_set_aside_share():
    included = ["AAA", "BBB", "CCC", "NEAR"]
    weights, set_aside = _renormalized({"AAA": 0.5, "LATE": 0.2, "CCC": 0.3}, included)
    assert abs(set_aside - 0.20) <= 1e-15 and list(weights) == ["AAA", "CCC"]
    assert abs(weights["AAA"] - 0.625) <= 1e-15 and abs(weights["CCC"] - 0.375) <= 1e-15
    dollars, set_aside = _renormalized({"AAA": 5000.0, "LATE": 2000, "CCC": 3000}, included)
    assert abs(set_aside - 0.20) <= 1e-15 and abs(dollars["AAA"] - 0.625) <= 1e-15
    whole, set_aside = _renormalized({"AAA": 0.4, "BBB": 0.6, "NEAR": 0.0}, included)
    assert set_aside == 0.0 and whole == {"AAA": 0.4, "BBB": 0.6, "NEAR": 0.0}
    # a mix held only in excluded funds has nothing to renormalize: no division by zero
    assert renormalize_allocation({"LATE": 3.0, "GONE": 1.0}, included) == (None, 1.0)
    assert renormalize_allocation({}, included) == (None, 0.0)
    assert renormalize_allocation({"AAA": 0.0}, included) == (None, 0.0)
    with pytest.raises(ValueError, match="negative"):
        renormalize_allocation({"AAA": 1.5, "BBB": -0.5}, included)
    with pytest.raises(ValueError, match="finite"):
        renormalize_allocation({"AAA": float("nan")}, included)
