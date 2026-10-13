"""Stress windows: per-fund buy-and-hold returns over three fixed episodes (spec 4.10).

A fund's return over a window runs from its last price on or before the window's start to its
last price on or before the window's end. If either of those prices is more than three trading
sessions old, the fund did not trade through the window and the answer is `None`: nothing is
interpolated, back-filled or borrowed from another fund.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

COVERAGE_SESSIONS = 3


@dataclass(frozen=True)
class StressWindow:
    label: str
    start: str
    end: str


WINDOWS = {
    "gfc2008": StressWindow("2008 financial crisis", "2008-09-01", "2009-03-09"),
    "covid2020": StressWindow("COVID crash, Feb–Mar 2020", "2020-02-19", "2020-03-23"),
    "rates2022": StressWindow("2022 rate shock", "2022-01-03", "2022-10-12"),
}
_CALENDAR_SPAN = ("2008-08-01", "2022-10-31")  # the three windows, with room before the first


def stress_returns(tr_by_fund: Mapping[str, pd.Series], sessions: Iterable | None = None) -> dict:
    """The tensor's `stress` object: one list of returns per window, in mapping order.

    `tr_by_fund` maps a fund id to its total-return index on the dates it has a verified price
    (NaN rows are dropped). `sessions` are the trading sessions the three-session rule counts;
    left out, they are the XNYS sessions.
    """
    calendar = _xnys_sessions() if sessions is None else pd.DatetimeIndex(list(sessions))
    days = calendar.to_numpy()
    histories = [_history(series) for series in tr_by_fund.values()]
    return {
        window_id: {
            "label": window.label,
            "start": window.start,
            "end": window.end,
            "r": [_window_return(history, window, days) for history in histories],
        }
        for window_id, window in WINDOWS.items()
    }


def _history(series: pd.Series) -> pd.Series:
    if not isinstance(series.index, pd.DatetimeIndex):
        raise ValueError("a total-return index must be indexed by a DatetimeIndex")
    return series.dropna().sort_index()


def _window_return(history: pd.Series, window: StressWindow, days: np.ndarray) -> float | None:
    start = _price_near(history, np.datetime64(window.start, "ns"), days)
    end = _price_near(history, np.datetime64(window.end, "ns"), days)
    if start is None or end is None:
        return None
    return end / start - 1.0


def _price_near(history: pd.Series, day: np.datetime64, days: np.ndarray) -> float | None:
    """The last price on or before `day`, unless more than three sessions have passed since."""
    priced = history.index.to_numpy()
    position = int(np.searchsorted(priced, day, side="right")) - 1
    if position < 0:
        return None
    sessions_since = int(np.searchsorted(days, day, side="right")) - int(
        np.searchsorted(days, priced[position], side="right")
    )
    if sessions_since > COVERAGE_SESSIONS:
        return None
    return float(history.iloc[position])


@lru_cache(maxsize=1)
def _xnys_sessions() -> pd.DatetimeIndex:
    import exchange_calendars  # deferred: only the default calendar needs it

    calendar = exchange_calendars.get_calendar(
        "XNYS", start=_CALENDAR_SPAN[0], end=_CALENDAR_SPAN[1]
    )
    return pd.DatetimeIndex(calendar.sessions.tz_localize(None))
