"""Lookback windows: which funds are in, which are out and why (spec 4.2, 5.6).

The index of the returns frame is the universe calendar. A window is its last `length` rows
ending at `asof`; a fund is included when it is served and its first return falls on or before
`window_start + 0.10 * length`, counted in calendar rows. The sample is the rows of the window
on which every included fund has a return. Nothing is filled in: a fund that is left out is
listed with one of the five fixed reasons.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .stats import ew_weights

LOOKBACK_ROWS = {"1y": 252, "2y": 504, "3y": 756, "5y": 1260, "10y": 2520, "ew": 1260}
VIEW_NAMES = {
    "1y": "1-year",
    "2y": "2-year",
    "3y": "3-year",
    "5y": "5-year",
    "10y": "10-year",
    "ew": "recent-weighted",
}
MIN_ROWS = 126
MIN_FUNDS = 2
START_SLACK = (1, 10)  # a fund may start up to 1/10 of the window after the window does
UNAVAILABLE_MESSAGE = "not enough shared history"

_DATE = r"\d{4}-\d{2}-\d{2}"
_CATALOG_REASON = re.compile(  # the templates a catalog can state; they are kept verbatim
    rf"no data|no data since {_DATE}|converted to an ETF; no data since {_DATE}"
    rf"|corporate actions not yet verified after {_DATE}"
)


@dataclass(frozen=True)
class WindowSelection:
    """One (menu, lookback, asof) window."""

    status: str  # "ready" | "unavailable"
    message: str  # "" when ready, UNAVAILABLE_MESSAGE otherwise
    lookback: str
    funds: list[str]  # included ids, in column order
    excluded: list[dict[str, str]]  # {"id", "reason"}, in column order
    sample: pd.DataFrame | None  # complete rows of the window, included funds only
    start: date | None  # first calendar day of the window
    end: date  # asof
    rows: int  # rows of the intersection, also when they are too few
    omega: np.ndarray | None  # observation weights of the `ew` window


def select_window(
    returns: pd.DataFrame,
    lookback: str,
    asof,
    catalog: Mapping[str, Mapping[str, object]] | None = None,
) -> WindowSelection:
    """Apply the inclusion rule and the 126-row floor to one window.

    `returns` is the returns-parquet frame. `catalog` maps a fund id to its manifest entry
    (`status`, `reason`, `adjusted_through`, `last_date`); only `status == "ok"` is served, and
    with a catalog a fund it does not list is not served. Without a catalog every fund is served.
    """
    if lookback not in LOOKBACK_ROWS:
        raise ValueError(f"unknown lookback {lookback!r}; expected one of {list(LOOKBACK_ROWS)}")
    index = returns.index
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("returns must be indexed by a DatetimeIndex")
    if not (index.is_monotonic_increasing and index.is_unique):
        raise ValueError("the returns index must be strictly increasing")
    if not returns.columns.is_unique:
        raise ValueError("a fund is listed more than once in the returns columns")
    end = pd.Timestamp(asof)
    if not isinstance(end, pd.Timestamp):
        raise ValueError("asof must be a date")
    end = end.normalize()
    frame = returns.loc[index <= end]
    length = LOOKBACK_ROWS[lookback]
    start_row = len(frame) - length  # negative when the calendar is shorter than the window
    numerator, denominator = START_SLACK

    funds: list[str] = []
    excluded: list[dict[str, str]] = []
    for fund in frame.columns:
        if catalog is not None and _status(catalog.get(fund)) != "ok":
            excluded.append({"id": fund, "reason": _unserved_reason(catalog.get(fund))})
            continue
        has_return = frame[fund].notna().to_numpy()
        if not has_return.any():
            excluded.append({"id": fund, "reason": "no data"})
            continue
        first_row = int(has_return.argmax())
        if denominator * (first_row - start_row) > numerator * length:
            day = frame.index[first_row].date().isoformat()
            view = VIEW_NAMES[lookback]
            reason = f"history starts {day}, not enough for the {view} view"
            excluded.append({"id": fund, "reason": reason})
            continue
        funds.append(fund)

    window = frame.iloc[max(start_row, 0) :]
    start = window.index[0].date() if len(window) else None
    sample = window[funds].dropna() if len(funds) >= MIN_FUNDS else None
    rows = 0 if sample is None else len(sample)
    ready = rows >= MIN_ROWS
    return WindowSelection(
        status="ready" if ready else "unavailable",
        message="" if ready else UNAVAILABLE_MESSAGE,
        lookback=lookback,
        funds=funds,
        excluded=excluded,
        sample=sample if ready else None,
        start=start,
        end=end.date(),
        rows=rows,
        omega=ew_weights(rows) if ready and lookback == "ew" else None,
    )


def renormalize_allocation(
    weights: Mapping[str, float], included: Iterable[str]
) -> tuple[dict[str, float] | None, float]:
    """Rescale a current mix over the included funds and report the share set aside.

    `weights` may be in any unit (shares of 1, dollars). Returns `(weights, set_aside)`: the
    included holdings rescaled to sum to 1 and the fraction of the original total held in funds
    that are not included. A mix with nothing in included funds returns `(None, 1.0)`; an empty
    or all-zero mix returns `(None, 0.0)`.
    """
    amounts = {fund: float(amount) for fund, amount in weights.items()}
    if not all(np.isfinite(amount) for amount in amounts.values()):
        raise ValueError("allocation amounts must be finite")
    if any(amount < 0 for amount in amounts.values()):
        raise ValueError("allocation amounts must not be negative")
    total = sum(amounts.values())
    if total <= 0:
        return None, 0.0
    members = set(included)
    kept = {fund: amount for fund, amount in amounts.items() if fund in members}
    kept_total = sum(kept.values())
    if kept_total <= 0:
        return None, 1.0
    aside = sum(amount for fund, amount in amounts.items() if fund not in members)
    return {fund: amount / kept_total for fund, amount in kept.items()}, aside / total


def _status(entry: Mapping[str, object] | None) -> object:
    return None if entry is None else entry.get("status")


def _unserved_reason(entry: Mapping[str, object] | None) -> str:
    """One of the spec 5.6 templates for a fund the catalog does not serve."""
    if entry is None:
        return "no data"
    reason = entry.get("reason")
    if isinstance(reason, str) and _CATALOG_REASON.fullmatch(reason):
        return reason
    adjusted = _iso(entry.get("adjusted_through"))
    if entry.get("status") != "unavailable" and adjusted is not None:
        return f"corporate actions not yet verified after {adjusted}"
    last = _iso(entry.get("last_date"))
    return "no data" if last is None else f"no data since {last}"


def _iso(day) -> str | None:
    """ISO date of a catalog date in any of its forms; `None` when there is none."""
    stamp = None if day is None else pd.Timestamp(day)
    return stamp.date().isoformat() if isinstance(stamp, pd.Timestamp) else None
