"""Stress windows: per-fund buy-and-hold returns over three fixed episodes (spec 4.10).

A fund's return over a window runs from its last price on or before the window's start to its
last price on or before the window's end. If either of those prices is more than three trading
sessions old, the fund did not trade through the window and the answer is `None`: nothing is
interpolated, back-filled or borrowed from another fund.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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


def stress_returns(
    tr_by_fund: Mapping[str, pd.Series | Sequence[pd.Series]], sessions: Iterable | None = None
) -> dict:
    """The tensor's `stress` object: one list of returns per window, in mapping order.

    `tr_by_fund` maps a fund id to its total-return index on the dates it has a verified price
    (NaN rows are dropped). A fund known only in pieces, as from `segments_from_returns`, is a
    list of such series; a return is never taken across two pieces. `sessions` are the trading
    sessions the three-session rule counts; left out, they are the XNYS sessions.
    """
    calendar = _xnys_sessions() if sessions is None else pd.DatetimeIndex(list(sessions))
    days = calendar.to_numpy()
    histories = [_history(record) for record in tr_by_fund.values()]
    return {
        window_id: {
            "label": window.label,
            "start": window.start,
            "end": window.end,
            "r": [_window_return(history, window, days) for history in histories],
        }
        for window_id, window in WINDOWS.items()
    }


def segments_from_returns(returns: pd.Series) -> list[pd.Series]:
    """Total-return records recoverable from one column of a returns frame.

    A fund has a return on a calendar day only when it has a price on that day and on the day
    before, so a missing return hides the growth across it. Each run of consecutive returns is
    therefore its own record, starting at 1.0 on the calendar day before the run (a day the fund
    has a price) when the frame holds that day.
    """
    known = returns.notna().to_numpy()
    values = returns.to_numpy(dtype=float)
    segments = []
    row = 0
    while row < len(known):
        if not known[row]:
            row += 1
            continue
        stop = row
        while stop < len(known) and known[stop]:
            stop += 1
        growth = np.cumprod(1.0 + values[row:stop])
        if row > 0:
            segment = pd.Series(
                np.concatenate([[1.0], growth]), index=returns.index[row - 1 : stop]
            )
        else:
            segment = pd.Series(growth, index=returns.index[row:stop])
        segments.append(segment)
        row = stop
    return segments


def _history(record: pd.Series | Sequence[pd.Series]) -> list[pd.Series]:
    """A fund's records as clean, date-ordered series."""
    pieces = [record] if isinstance(record, pd.Series) else list(record)
    for piece in pieces:
        if not isinstance(piece.index, pd.DatetimeIndex):
            raise ValueError("a total-return index must be indexed by a DatetimeIndex")
    cleaned = [piece.dropna().sort_index() for piece in pieces]
    return sorted((piece for piece in cleaned if len(piece)), key=lambda piece: piece.index[0])


def _window_return(
    history: list[pd.Series], window: StressWindow, days: np.ndarray
) -> float | None:
    start = _price_near(history, np.datetime64(window.start, "ns"), days)
    end = _price_near(history, np.datetime64(window.end, "ns"), days)
    if start is None or end is None or start[0] != end[0]:
        return None
    return end[1] / start[1] - 1.0


def _price_near(
    history: list[pd.Series], day: np.datetime64, days: np.ndarray
) -> tuple[int, float] | None:
    """`(record, price)` for the last price on or before `day`.

    `None` when there is no such price or more than three sessions have passed since it.
    """
    found = None
    for number, piece in enumerate(history):
        priced = piece.index.to_numpy()
        position = int(np.searchsorted(priced, day, side="right")) - 1
        if position >= 0:
            found = (number, priced[position], float(piece.iloc[position]))
    if found is None:
        return None
    number, priced_on, price = found
    sessions_since = int(np.searchsorted(days, day, side="right")) - int(
        np.searchsorted(days, priced_on, side="right")
    )
    if sessions_since > COVERAGE_SESSIONS:
        return None
    return number, price


@lru_cache(maxsize=1)
def _xnys_sessions() -> pd.DatetimeIndex:
    import exchange_calendars  # deferred: only the default calendar needs it

    calendar = exchange_calendars.get_calendar(
        "XNYS", start=_CALENDAR_SPAN[0], end=_CALENDAR_SPAN[1]
    )
    return pd.DatetimeIndex(calendar.sessions.tz_localize(None))
