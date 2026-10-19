"""Synthetic price records shared by the harness and evaluation tests.

A record is the canonical price-record frame (`date`, `close`, `tr_index`, `div_cash`,
`split_factor`) of one total-return index. `random_indices` draws seeded daily returns, so a
training window has non-degenerate moments; tests/test_backtest_ranges.py builds its ledger-only
records from constant growth with the same `record`.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


def record(index: pd.Series) -> pd.DataFrame:
    """The price record of a total-return index whose own index holds the dates."""
    values = index.to_numpy(dtype=float)
    return pd.DataFrame(
        {
            "date": pd.DatetimeIndex(index.index),
            "close": 100.0 * values,
            "tr_index": values,
            "div_cash": 0.0,
            "split_factor": 1.0,
        }
    )


def random_indices(
    days: pd.DatetimeIndex, drift_vol: Mapping[str, tuple[float, float]], seed: int
) -> dict[str, pd.Series]:
    """One total-return index per symbol on ``days``, starting at 1.0, drawn in symbol order.

    The daily return of a symbol is ``drift + vol * z`` with ``z`` standard normal from one
    generator seeded with ``seed``; the first day has no return.
    """
    rng = np.random.default_rng(seed)
    out = {}
    for symbol, (drift, vol) in drift_vol.items():
        r = drift + vol * rng.standard_normal(len(days))
        out[symbol] = pd.Series(np.concatenate(([1.0], np.cumprod(1.0 + r[1:]))), index=days)
    return out
