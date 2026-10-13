"""Stress windows: buy-and-hold returns that are never fabricated (spec 4.10)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from portfoliosight.engine.stress import COVERAGE_SESSIONS, WINDOWS, stress_returns

EXPECTED = {
    "gfc2008": ("2008 financial crisis", "2008-09-01", "2009-03-09"),
    "covid2020": ("COVID crash, Feb–Mar 2020", "2020-02-19", "2020-03-23"),
    "rates2022": ("2022 rate shock", "2022-01-03", "2022-10-12"),
}


def _series(seed: int, start: str = "2007-01-02", end: str = "2023-12-29") -> pd.Series:
    index = pd.bdate_range(start, end, name="date")
    rng = np.random.default_rng(seed)
    return pd.Series(np.cumprod(1.0 + rng.normal(0.0003, 0.012, len(index))), index=index)


def _at(series: pd.Series, day: str) -> float:
    return float(series.loc[:day].iloc[-1])


def _without(series: pd.Series, first: str, last: str) -> pd.Series:
    return series.drop(series.loc[first:last].index)


def _own(series: pd.Series, start: str, end: str) -> float:
    return _at(series, end) / _at(series, start) - 1.0


def test_windows_are_the_three_of_the_spec():
    assert COVERAGE_SESSIONS == 3
    assert {wid: (w.label, w.start, w.end) for wid, w in WINDOWS.items()} == EXPECTED
    assert list(WINDOWS) == ["gfc2008", "covid2020", "rates2022"]
    out = stress_returns({"FULL": _series(4001)})
    assert list(out) == list(EXPECTED)
    for wid, (label, start, end) in EXPECTED.items():
        assert set(out[wid]) == {"label", "start", "end", "r"}
        assert (out[wid]["label"], out[wid]["start"], out[wid]["end"]) == (label, start, end)
    assert stress_returns({}) == {
        wid: {"label": label, "start": start, "end": end, "r": []}
        for wid, (label, start, end) in EXPECTED.items()
    }


def test_full_history_fund_gets_the_buy_and_hold_return():
    full = _series(4002)
    out = stress_returns({"FULL": full})
    for wid, (_, start, end) in EXPECTED.items():
        value = out[wid]["r"][0]
        assert isinstance(value, float) and abs(value - _own(full, start, end)) <= 1e-12
    # 2008-09-01 is a market holiday: the start price is the last one on or before it
    without = full.drop(pd.Timestamp("2008-09-01"))
    value = stress_returns({"FULL": without})["gfc2008"]["r"][0]
    assert abs(value - (_at(without, "2009-03-09") / _at(without, "2008-08-29") - 1.0)) <= 1e-12


def test_a_fund_without_a_price_near_an_endpoint_gets_none():
    gap = _series(4003)
    funds = {
        "FULL": _series(4004),
        "LATE": _series(4005, start="2010-01-04"),
        "INSIDE": _series(4006, start="2008-11-03"),  # exists at the end of 2008 but not the start
        "GAP": _without(gap, "2020-02-10", "2020-02-24"),
        "OCT7": _series(4007, end="2022-10-07"),  # 3 sessions before 2022-10-12
        "OCT6": _series(4008, end="2022-10-06"),  # 4 sessions before: one too many
        "EMPTY": pd.Series([], index=pd.DatetimeIndex([], name="date"), dtype=float),
    }
    out = stress_returns(funds)
    ids = list(funds)
    r = {wid: dict(zip(ids, out[wid]["r"], strict=True)) for wid in EXPECTED}
    nulls = sorted((wid, fund) for wid in EXPECTED for fund in ids if r[wid][fund] is None)
    assert nulls == sorted(
        [
            ("gfc2008", "LATE"),
            ("gfc2008", "INSIDE"),
            ("covid2020", "GAP"),
            ("rates2022", "OCT6"),
            ("gfc2008", "EMPTY"),
            ("covid2020", "EMPTY"),
            ("rates2022", "EMPTY"),
        ]
    )
    for wid, (_, start, end) in EXPECTED.items():
        for fund in ids:
            if r[wid][fund] is not None:
                assert abs(r[wid][fund] - _own(funds[fund], start, end)) <= 1e-12
    # the covered OCT7 return ends at its own last price, not at an invented one
    last = float(funds["OCT7"].iloc[-1])
    assert abs(r["rates2022"]["OCT7"] - (last / _at(funds["OCT7"], "2022-01-03") - 1.0)) <= 1e-12
    fabricated = _at(funds["GAP"], "2020-03-23") / _at(funds["GAP"], "2020-02-19") - 1.0
    assert np.isfinite(fabricated)  # computable, and still not reported


def test_three_session_boundary_on_the_start_side():
    base = _series(4009)
    # sessions before 2022-01-03: 12-31, 12-30, 12-29, 12-28 (all open)
    three = _without(base, "2021-12-30", "2022-01-03")
    four = _without(base, "2021-12-29", "2022-01-03")
    out = stress_returns({"THREE": three, "FOUR": four})["rates2022"]["r"]
    expected = _at(three, "2022-10-12") / _at(three, "2021-12-29") - 1.0
    assert out[0] is not None and abs(out[0] - expected) <= 1e-12
    assert out[1] is None


def test_unverified_rows_and_order_do_not_matter():
    full = _series(4010)
    holed = full.copy()
    holed.loc["2020-03-17":"2020-03-23"] = np.nan  # price-only rows carry no index: 5 sessions
    assert stress_returns({"X": holed})["covid2020"]["r"] == [None]
    kept = full.copy()
    kept.loc["2020-03-19":"2020-03-23"] = np.nan  # 3 sessions: still covered
    value = stress_returns({"X": kept})["covid2020"]["r"][0]
    assert abs(value - (_at(full, "2020-03-18") / _at(full, "2020-02-19") - 1.0)) <= 1e-12
    shuffled = full.sample(frac=1.0, random_state=7)
    assert stress_returns({"X": shuffled}) == stress_returns({"X": full})


def test_sessions_can_be_supplied_by_the_caller():
    full = _series(4011, end="2022-10-06")
    assert stress_returns({"X": full})["rates2022"]["r"] == [None]
    sparse = pd.DatetimeIndex(["2022-01-03", "2022-10-06", "2022-10-12"])  # a calendar of 3 days
    value = stress_returns({"X": full}, sessions=sparse)["rates2022"]["r"][0]
    assert abs(value - _own(full, "2022-01-03", "2022-10-12")) <= 1e-12
    as_dates = [day.date() for day in sparse]
    assert stress_returns({"X": full}, sessions=as_dates)["rates2022"]["r"] == [value]
    with pytest.raises(ValueError, match="DatetimeIndex"):
        stress_returns({"X": pd.Series([1.0, 1.1], index=[0, 1])})
