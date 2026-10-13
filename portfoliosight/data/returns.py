"""From provider rows to the canonical record and to daily returns (spec 4.1, 5.3, 5.6).

Nothing here fills, interpolates or back-fills: a day without a price has no return, and neither
has the day after it.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

import numpy as np
import pandas as pd

BasisRule = Literal["post_split", "pre_split"]
# How the provider quotes a dividend that falls on a split day. Fixed by the recorded fixtures
# (tests/data/test_tiingo.py keeps the adjClose cross-check, so the rule cannot silently flip).
BASIS_RULE: BasisRule = "post_split"
RECORD_COLUMNS = ("date", "close", "tr_index", "div_cash", "split_factor")


def _growth(frame: pd.DataFrame, basis_rule: BasisRule) -> np.ndarray:
    """``1 + r_t`` per row of a date-sorted provider frame; the first element is 1.0."""
    if basis_rule not in ("post_split", "pre_split"):
        raise ValueError(f"unknown basis rule {basis_rule!r}")
    close = frame["close"].to_numpy(dtype=float)
    if np.isnan(close).any() or (close <= 0).any():
        days = pd.DatetimeIndex(frame.index).strftime("%Y-%m-%d")
        bad = days[int(np.argmax(np.isnan(close) | (close <= 0)))]
        raise ValueError(f"provider row dated {bad} has no positive close")
    split = frame["split_factor"].to_numpy(dtype=float)
    split = np.where(np.isnan(split), 1.0, split)
    div = frame["div_cash"].to_numpy(dtype=float)
    div = np.where(np.isnan(div), 0.0, div)
    basis = split if basis_rule == "post_split" else np.ones_like(split)
    growth = np.ones(len(close))
    growth[1:] = (close[1:] * split[1:] + div[1:] * basis[1:]) / close[:-1]
    return growth


def build_tr_index(frame: pd.DataFrame, *, basis_rule: BasisRule = BASIS_RULE) -> pd.Series:
    """Total-return index of a provider frame, built from close, div_cash and split_factor only.

    ``frame`` has a ``DatetimeIndex`` in increasing order and the columns ``close``, ``div_cash``,
    ``split_factor`` (an ``adj_close`` column is ignored). The result is 1.0 on the first row.
    """
    if frame.empty:
        return pd.Series(np.array([], dtype=float), index=frame.index, name="tr_index")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("provider frame must be sorted by date")
    growth = _growth(frame, basis_rule)
    tr = np.concatenate(([1.0], np.cumprod(growth[1:])))
    return pd.Series(tr, index=frame.index, name="tr_index")


def provider_rows_to_record(
    frame: pd.DataFrame, *, basis_rule: BasisRule = BASIS_RULE
) -> pd.DataFrame:
    """The canonical record (spec 5.3) of a provider frame: one row per priced day."""
    ordered = frame.sort_index()
    tr = build_tr_index(ordered, basis_rule=basis_rule)
    return pd.DataFrame(
        {
            "date": pd.DatetimeIndex(ordered.index).tz_localize(None).to_numpy(),
            "close": ordered["close"].to_numpy(dtype=float),
            "tr_index": tr.to_numpy(dtype=float),
            "div_cash": ordered["div_cash"].to_numpy(dtype=float),
            "split_factor": ordered["split_factor"].to_numpy(dtype=float),
        }
    )


def build_returns(records: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Daily returns on the union calendar of all records; NaN wherever a fund has no return.

    The value on day ``t`` is ``tr_index_t / tr_index_{t-1} - 1`` with ``t-1`` the previous day of
    the union calendar, so it is NaN when the fund has no index value on ``t`` or on ``t-1``.
    """
    series: dict[str, pd.Series] = {}
    for fund, record in records.items():
        index = pd.DatetimeIndex(pd.to_datetime(record["date"]), name="date")
        series[fund] = pd.Series(record["tr_index"].to_numpy(dtype=float), index=index)
    calendar = pd.DatetimeIndex([], name="date")
    for values in series.values():
        calendar = calendar.union(values.index)
    calendar = calendar.sort_values()
    calendar.name = "date"
    out = pd.DataFrame(index=calendar, columns=list(series), dtype=float)
    for fund, values in series.items():
        aligned = values.reindex(calendar)
        out[fund] = aligned / aligned.shift(1) - 1.0
    return out


def window_sample(returns: pd.DataFrame, funds: list[str], start: date, end: date) -> pd.DataFrame:
    """Rows of ``returns[funds]`` in ``start..end`` (inclusive) where every fund has a return."""
    index = pd.DatetimeIndex(returns.index)
    inside = (index >= pd.Timestamp(start)) & (index <= pd.Timestamp(end))
    window = returns.loc[inside, list(funds)]
    return window[window.notna().all(axis=1)]
