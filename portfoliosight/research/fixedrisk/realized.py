"""Realized one-year outcomes of locked mixes (protocol v2 section 5).

Conventions, per selection and origin (each origin is a separate one-year cohort):

- daily: rebalanced to target every session (the v1 convention, used only for forecast calibration);
- monthly: funded at target weights from cash at the origin close; rebalanced to target at the close
  of the last session of each calendar month strictly inside the horizon; fully invested; no
  liquidation at the horizon end (the primary realized outcome);
- net: the monthly convention with `10 bp x one-way turnover` deducted from the cohort value at each
  rebalance (turnover `1/2 sum |w_target - w_drifted|`, drifted pre-trade holdings) and at the
  initial funding (turnover 1.0).

Everything takes arrays, Series and callables so the module does not import the data piece.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

HORIZON_DAYS = 252
COST_BP = 10.0
EQUITY_DRAWDOWN = 0.15  # SPY total-return peak-to-trough fall that labels a year "equity drawdown"
RATE_SHOCK_PP = 1.5  # DGS10 rise in percentage points (150 bp) that labels a year "rate shock"
EQUITY_DRAWDOWN_LABEL = "equity drawdown"
RATE_SHOCK_LABEL = "rate shock"
CALM_LABEL = "calm"
REGIMES = (EQUITY_DRAWDOWN_LABEL, RATE_SHOCK_LABEL, CALM_LABEL)
MULTI_YEARS = (3, 5)

# horizon(menu, month) -> (days, values T x N daily simple returns, holding order) or None
HorizonFn = Callable[[str, str], "tuple[Sequence[Any], np.ndarray, Sequence[str]] | None"]
# span(menu, month, n_days) -> (days, values n_days x N) from the same start as the horizon, or None
SpanFn = Callable[[str, str, int], "tuple[Sequence[Any], np.ndarray] | None"]

REALIZED_COLUMNS = (
    "complete",
    "horizon_end",
    "ret_daily",
    "dd_daily",
    "ret_m",
    "dd_m",
    "ret_net",
    "dd_net",
    "turnover",
    "real_m",
    "regime",
    "ret_3y",
    "ret_5y",
    "real_3y",
    "real_5y",
)


@dataclass(frozen=True)
class Outcomes:
    """Per-mix figures of one horizon: total return, maximum drawdown, summed rebalance turnover."""

    annual: np.ndarray
    drawdown: np.ndarray
    turnover: np.ndarray


def rebalance_positions(days: Sequence[Any]) -> np.ndarray:
    """Indices t of the last session of each calendar month strictly inside the horizon.

    Session t qualifies when session t+1 lies in another calendar month; the horizon's own last
    session never qualifies (no liquidation, nothing to rebalance into).
    """
    stamps = pd.DatetimeIndex(pd.to_datetime(list(days)))
    month = stamps.year * 12 + stamps.month
    return np.flatnonzero(np.asarray(month[1:]) != np.asarray(month[:-1]))


def _drawdown(wealth: np.ndarray) -> np.ndarray:
    peak = np.maximum(np.maximum.accumulate(wealth, axis=0), 1.0)
    return (1.0 - wealth / peak).max(axis=0)


def _mixes(weights: Any, n: int) -> np.ndarray:
    mixes = np.atleast_2d(np.asarray(weights, dtype=float))
    if mixes.shape[1] != n:
        raise ValueError(f"weights have {mixes.shape[1]} holdings, returns have {n}")
    return mixes


def daily_rebalanced(daily: np.ndarray, weights: Any) -> Outcomes:
    """Constant weights every session (v1 `path_metrics` convention)."""
    returns = np.asarray(daily, dtype=float)
    mixes = _mixes(weights, returns.shape[1])
    wealth = np.cumprod(1.0 + returns @ mixes.T, axis=0)
    return Outcomes(wealth[-1] - 1.0, _drawdown(wealth), np.zeros(len(mixes)))


def monthly_rebalanced(
    daily: np.ndarray, days: Sequence[Any], weights: Any, cost_bp: float = 0.0
) -> Outcomes:
    """Monthly rebalancing to target; `cost_bp` of one-way turnover charged (funding included)."""
    returns = np.asarray(daily, dtype=float)
    t_len = len(returns)
    if t_len != len(days):
        raise ValueError("days and returns differ in length")
    mixes = _mixes(weights, returns.shape[1])
    cost = cost_bp * 1e-4
    holdings = mixes * (1.0 - cost)  # funded from cash: one-way turnover 1.0
    wealth = np.empty((t_len, len(mixes)))
    turnover = np.zeros(len(mixes))
    start = 0
    for end in [*rebalance_positions(days).tolist(), t_len - 1]:
        grown = np.cumprod(1.0 + returns[start : end + 1], axis=0)  # L x N
        wealth[start : end + 1] = grown @ holdings.T
        if end < t_len - 1:
            held = holdings * grown[-1]
            value = held.sum(axis=1)
            trade = 0.5 * np.abs(mixes - held / value[:, None]).sum(axis=1)
            value = value * (1.0 - cost * trade)
            wealth[end] = value
            holdings = mixes * value[:, None]
            turnover += trade
        start = end + 1
    return Outcomes(wealth[-1] - 1.0, _drawdown(wealth), turnover)


def cpi_factor(cpi: pd.Series, origin: Any, end: Any) -> float:
    """CPI(month of the horizon end) / CPI(month of the origin); NaN if missing."""
    index = pd.PeriodIndex(pd.to_datetime(cpi.index), freq="M")
    levels = pd.Series(np.asarray(cpi, dtype=float), index=index)
    levels = levels[~levels.index.duplicated(keep="last")]
    try:
        num = float(levels.loc[pd.Timestamp(end).to_period("M")])
        den = float(levels.loc[pd.Timestamp(origin).to_period("M")])
    except KeyError:
        return math.nan
    return num / den if den > 0 and math.isfinite(num) else math.nan


def real_return(nominal: float, factor: float) -> float:
    """`(1 + nominal) / factor - 1`; NaN when the deflator is unavailable."""
    return (1.0 + nominal) / factor - 1.0 if math.isfinite(factor) and factor > 0 else math.nan


def _asof(series: pd.Series, stamp: pd.Timestamp) -> float:
    clean = series.dropna()
    clean = clean[clean.index <= stamp]
    return float(clean.iloc[-1]) if len(clean) else math.nan


def regime_label(
    spy_tr: pd.Series,
    dgs10: pd.Series,
    origin: Any,
    end: Any,
    *,
    drawdown_threshold: float = EQUITY_DRAWDOWN,
    rate_threshold_pp: float = RATE_SHOCK_PP,
) -> str:
    """Priority: equity drawdown (>= 15% SPY total-return fall inside the horizon), else rate shock
    (DGS10 up >= 150 bp from the last value on or before the origin to that at the horizon end),
    else calm. `dgs10` is in percent."""
    start, stop = pd.Timestamp(origin), pd.Timestamp(end)
    tr = spy_tr.copy()
    tr.index = pd.to_datetime(tr.index)
    tr = tr.dropna().sort_index()
    base = _asof(tr, start)
    inside = tr[(tr.index > start) & (tr.index <= stop)]
    path = np.concatenate([[base] if math.isfinite(base) else [], inside.to_numpy(dtype=float)])
    if len(path) >= 2:
        fall = float((1.0 - path / np.maximum.accumulate(path)).max())
        if fall >= drawdown_threshold:
            return EQUITY_DRAWDOWN_LABEL
    rates = dgs10.copy()
    rates.index = pd.to_datetime(rates.index)
    change = _asof(rates, stop) - _asof(rates, start)
    if math.isfinite(change) and change >= rate_threshold_pp - 1e-12:
        return RATE_SHOCK_LABEL
    return CALM_LABEL


def _empty(index: pd.Index) -> pd.DataFrame:
    frame = pd.DataFrame(index=index, columns=list(REALIZED_COLUMNS), dtype=object)
    frame["complete"] = False
    for name in REALIZED_COLUMNS:
        if name not in ("complete", "horizon_end", "regime"):
            frame[name] = np.nan
    return frame


def realized_table(
    selections: pd.DataFrame,
    horizon: HorizonFn,
    *,
    span: SpanFn | None = None,
    cpi: pd.Series | None = None,
    spy_tr: pd.Series | None = None,
    dgs10: pd.Series | None = None,
    cost_bp: float = COST_BP,
    horizon_days: int = HORIZON_DAYS,
    multi_years: Sequence[int] = MULTI_YEARS,
) -> pd.DataFrame:
    """One row per `sel_id` with the realized figures of every convention (see module docstring).

    `selections` needs sel_id, menu, month, origin and weights (holding order of the horizon).
    Rows whose horizon is missing or shorter than `horizon_days`, and rows without a locked mix
    (empty weights: a labelled outcome), have complete == False and NaN.
    """
    frame = _empty(pd.Index(selections["sel_id"].to_numpy(), name="sel_id"))
    has_mix = selections["weights"].map(lambda w: w is not None and len(w) > 0).astype(bool)
    for (menu, month), group in selections[has_mix].groupby(["menu", "month"], sort=True):
        hz = horizon(str(menu), str(month))
        if hz is None or len(hz[0]) < horizon_days:
            continue
        days, values = list(hz[0])[:horizon_days], np.asarray(hz[1], dtype=float)[:horizon_days]
        ids = group["sel_id"].to_numpy()
        mixes = np.vstack([np.asarray(w, dtype=float) for w in group["weights"]])
        origin = pd.Timestamp(group["origin"].iloc[0])
        end = pd.Timestamp(days[-1])
        daily = daily_rebalanced(values, mixes)
        gross = monthly_rebalanced(values, days, mixes)
        net = monthly_rebalanced(values, days, mixes, cost_bp)
        frame.loc[ids, "complete"] = True
        frame.loc[ids, "horizon_end"] = end
        frame.loc[ids, "ret_daily"] = daily.annual
        frame.loc[ids, "dd_daily"] = daily.drawdown
        frame.loc[ids, "ret_m"] = gross.annual
        frame.loc[ids, "dd_m"] = gross.drawdown
        frame.loc[ids, "ret_net"] = net.annual
        frame.loc[ids, "dd_net"] = net.drawdown
        frame.loc[ids, "turnover"] = gross.turnover
        if cpi is not None:
            factor = cpi_factor(cpi, origin, end)
            frame.loc[ids, "real_m"] = [real_return(x, factor) for x in gross.annual]
        if spy_tr is not None and dgs10 is not None:
            frame.loc[ids, "regime"] = regime_label(spy_tr, dgs10, origin, end)
        if span is None:
            continue
        for years in multi_years:
            need = years * horizon_days
            sp = span(str(menu), str(month), need)
            if sp is None or len(sp[0]) < need:
                continue
            s_days, s_values = list(sp[0])[:need], np.asarray(sp[1], dtype=float)[:need]
            total = monthly_rebalanced(s_values, s_days, mixes).annual
            frame.loc[ids, f"ret_{years}y"] = total
            if cpi is not None:
                factor = cpi_factor(cpi, origin, pd.Timestamp(s_days[-1]))
                frame.loc[ids, f"real_{years}y"] = [real_return(x, factor) for x in total]
    numeric = [c for c in REALIZED_COLUMNS if c not in ("complete", "horizon_end", "regime")]
    frame[numeric] = frame[numeric].astype(float)
    frame["complete"] = frame["complete"].astype(bool)
    return frame.reset_index()


def summary_by(frame: pd.DataFrame, by: str, columns: Mapping[str, str]) -> pd.DataFrame:
    """Mean of `columns` (name -> source column) over the complete rows of each `by` bucket."""
    done = frame[frame["complete"]]
    out = done.groupby(by).agg(n=("sel_id", "size"), **{k: (v, "mean") for k, v in columns.items()})
    return out
