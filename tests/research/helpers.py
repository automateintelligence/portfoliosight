"""Synthetic price records and origin models shared by the harness, evaluation and search tests.

A record is the canonical price-record frame (`date`, `close`, `tr_index`, `div_cash`,
`split_factor`) of one total-return index. `random_indices` draws seeded daily returns, so a
training window has non-degenerate moments; tests/test_backtest_ranges.py builds its ledger-only
records from constant growth with the same `record`. `synthetic_model` builds an origin model
straight from a seeded sample, without records or a ledger, for the search tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from portfoliosight.engine.ranges import sample_digest
from portfoliosight.engine.stats import estimate_moments, menu_beta_blend
from portfoliosight.research.evaluate import OriginModel


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


def synthetic_model(
    funds: Sequence[str],
    rows: int,
    seed: int,
    *,
    shocks: Mapping[tuple[int, int], float] | None = None,
    rate: float = 0.04,
) -> OriginModel:
    """An origin model of ``rows`` seeded daily returns of ``funds``, fitted by production.

    Each fund's return is ``drift + beta * f + vol * e`` with one common factor ``f``; drift,
    beta and vol are drawn per fund from the same generator. ``shocks`` overwrites single returns,
    ``{(row, fund index): return}``, to plant a ruinous day. The moments are production
    `estimate_moments` (fixed window), ``mu_s`` the production `menu_beta_blend` at ``rate``; the
    sample is column-major, as `origin_model` holds it.
    """
    rng = np.random.default_rng(seed)
    n = len(funds)
    drift = rng.uniform(1e-4, 6e-4, n)
    beta = rng.uniform(0.2, 1.0, n)
    vol = rng.uniform(0.004, 0.015, n)
    factor = 0.008 * rng.standard_normal(rows)
    values = drift + beta * factor[:, None] + vol * rng.standard_normal((rows, n))
    for (row, fund), value in (shocks or {}).items():
        values[row, fund] = value
    sample = np.asfortranarray(values)
    sample.setflags(write=False)
    days = tuple(day.date() for day in pd.bdate_range("2020-01-02", periods=rows))
    moments = estimate_moments(sample)
    mu_s, _ = menu_beta_blend(moments.mu, moments.cov, rate)
    mu_s.setflags(write=False)
    return OriginModel(
        menu="synthetic",
        funds=tuple(funds),
        month=f"{days[-1]:%Y-%m}",
        origin=days[-1],
        lookback="5y",
        days=days,
        sample=sample,
        sample_sha256=sample_digest(list(funds), [day.isoformat() for day in days], sample),
        moments=moments,
        risk_free_rate=rate,
        risk_free_source="fallback",
        mu_s=mu_s,
    )
