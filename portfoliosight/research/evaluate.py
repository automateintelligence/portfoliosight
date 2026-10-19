"""Fixed-weight evaluation at one origin: the training bank and the realized year (protocol 3-6, 8).

The experiment scores thousands of weight vectors at every origin, so the work is split into
objects that are built once and shared:

- `origin_model(records, ledger, month, menu)` -> `OriginModel`, the training side of one
  (menu, origin, lookback). From the records dated on or before the origin it rebuilds the
  ledger's training window with the production `build_returns`, `select_window` and
  `window_sample`; fits the production `estimate_moments` fixed-window estimator (Ledoit-Wolf
  shrunk correlation, ddof-1 volatilities, the 1e-4 floor on sigma; the fitted shrinkage is kept
  in `moments.shrinkage`); takes the risk-free rate and its source as the ledger does (SGOV, else
  TSP-G, else the 4% fallback, through the production `risk_free_rate`); and blends `mu_s` with
  the production `menu_beta_blend`, as `engine.builder` does for a tensor. It refuses a menu the
  ledger does not call training-eligible, the `ew` lookback (protocol 2 pins the fixed window),
  and records that do not reproduce the ledger's window start, complete rows or risk-free rate.
- `bank(model, seed)` -> `Bank`, one History-replay bank: the production `range_model` of the
  model's sample and moments, whose count matrix comes from the 2,000 x 252 stationary bootstrap
  (mean block 21) of `seed`, with the SHA-256 of that bootstrap's day indices. Replay is the only
  engine (`Literal["replay"]`); GARCH joins under its own locked replication (protocol 1).
- `realized_horizon(records, ledger, month, menu)` -> `Horizon`, the menu's daily returns on the
  252 horizon dates the ledger names, read from records cut at the horizon end (never after D*).
  A horizon that is not complete carries the ledger's named outcome (`mature_horizon_missing`,
  `administratively_immature`) and its reasons, and no returns.

A model and its banks hold no realized return, so a search handed them cannot see one (protocol 8,
leakage); only the realized leg reads a `Horizon`.

Training side. `simulate(model, bank, weights)` gives each mix's 2,000 simulated annual returns
through the production `simulated_years`: the mix's daily returns recentred on `mu_s'w / 252`,
`g_t = 1 + r_t'w - mean_s(r_s'w) + mu_s'w / 252` with the mean over the training rows, compounded
with the count-matrix identity. Before that call each mix's `g_t` is computed with the very
operations production uses. A mix with any `g_t <= 0` is never passed to production (which raises
on such a day): it gets the status `nonpositive_daily_growth`, the first training date with
`g_t <= 0`, and NaN for every figure; nothing is clipped. `evaluate(model, bank, weights)`
summarizes one bank; `summarize(simulations)` pools banks of distinct seeds for the same mixes (the
five independent banks' 10,000 outcomes). The figures, per mix: `bad`, `typical`, `good`, the
2.5th, 50th and 97.5th linear percentiles (`np.percentile`, as production); `mean`, the mean annual
outcome (correctly rounded, `math.fsum`); `es_25`, the mean of the worst `ceil(0.025 P)`
(`measures.es_25`); `p_loss` and `p_below_20`, the shares of outcomes below 0 and below -20%.

Bit-identical outcomes. The same weights on the same bank give the same bits whatever the batch
size, the order of the mixes, the caller or the state of production's caches. NumPy hands a
one-mix product to BLAS `gemv` and a many-mix product to `gemm`, which add in different orders
(1.2e-14 apart on a 23-fund, 1,260-row sample), and the search's local refinement scores one mix
at a time; so each mix is simulated on its own, through the same production call with the same
shapes. The percentiles take exact order statistics column by column and every other figure is
computed from one mix's outcomes. The sample is its frame's `to_numpy()` (column-major), as
`engine.builder` hands it to `estimate_moments` and `range_model`; the layout decides the last bit
of sigma. Cost: about 3 ms a mix at 2,000 paths, 1,260 rows and 23 funds on one BLAS thread.

Realized side. `realized(horizon, weights)` compounds each mix's daily returns at constant target
weights (protocol 3: `Y = prod_t(1 + sum_i w_i r_it) - 1`, frictionless daily rebalancing) and
gives `path_metrics`: the annual return; `loss`, `Y < 0`; `below_20`, `Y < -0.20`; the worst daily
return; the maximum drawdown along the 252-day wealth path (the largest fall from the running
peak, the initial wealth 1 included, as a positive fraction); and the realized annualized
volatility (`sqrt(252)` times the ddof-1 deviation of the daily returns). A horizon that is not
complete gives its status and no number. A day whose gross return is not positive cannot be
compounded and raises `ValueError`; only weights outside the long-only menu can produce one.

Calibration (protocol 6), for a forecast quantile `f` at level `q` and a realized return `y`:
`pinball`, `(q - 1[y < f]) (y - f)`; `at_or_below`, the PIT and coverage indicator `1[y <= f]`;
`breaches(y, bad, good)`, the counts of `y <= bad` (below Bad), `bad < y <= good` (inside) and
`y > good` (above Good), all on the `1[y <= f]` convention, so a tie with Bad is a breach;
`pit(y, outcomes)`, the share of simulated outcomes at or below `y`.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
import numpy.typing as npt
import pandas as pd

from portfoliosight.data.returns import build_returns, window_sample
from portfoliosight.engine import measures
from portfoliosight.engine.ranges import (
    PERCENTILES,
    RangeModel,
    bootstrap_index,
    frame_digest,
    range_model,
    sample_digest,
    simulated_years,
)
from portfoliosight.engine.stats import (
    RISK_FREE_SOURCES,
    TRADING_DAYS,
    Moments,
    estimate_moments,
    menu_beta_blend,
)
from portfoliosight.engine.windows import select_window
from portfoliosight.research.harness import (
    COMPLETE,
    HORIZON_DATES_SHORT,
    HORIZON_PAST_D_STAR,
    HORIZON_ROWS,
    HORIZON_VALUE_MISSING,
    PREDECESSOR_MISSING,
    Issue,
    Ledger,
    MenuOrigin,
    OriginRow,
    _record_dates,
    _risk_free,
    _stamp,
    _through,
)

Engine = Literal["replay"]
ENGINES: tuple[str, ...] = ("replay",)
OK = "ok"
NONPOSITIVE_DAILY_GROWTH = "nonpositive_daily_growth"  # protocol 5 step 5
LOSS_LINE = -0.20  # "annual loss beyond 20%": an annual return below -20%
FIGURES = ("bad", "typical", "good", "mean", "es_25", "p_loss", "p_below_20")  # of an Evaluation
_HORIZON_CODES = frozenset(
    {PREDECESSOR_MISSING, HORIZON_DATES_SHORT, HORIZON_PAST_D_STAR, HORIZON_VALUE_MISSING}
)

ModelKey = tuple[str, str, str, str]


@dataclass(frozen=True)
class OriginModel:
    """The training side of one (menu, origin, lookback); nothing in it postdates the origin."""

    menu: str
    funds: tuple[str, ...]  # fixed menu order
    month: str  # YYYY-MM, the ledger row
    origin: date
    lookback: str
    days: tuple[date, ...]  # the training rows' dates
    sample: np.ndarray  # T x N daily returns of the complete rows, column-major, read-only
    sample_sha256: str  # production `sample_digest` of funds, days and returns
    moments: Moments  # production `estimate_moments`, fixed window
    risk_free_rate: float
    risk_free_source: str  # SGOV | TSP-G | fallback
    mu_s: np.ndarray  # production `menu_beta_blend(moments.mu, moments.cov, risk_free_rate)`

    @property
    def key(self) -> ModelKey:
        """What a bank is drawn for: menu, ISO origin, lookback and the sample digest."""
        return (self.menu, self.origin.isoformat(), self.lookback, self.sample_sha256)


@dataclass(frozen=True)
class Bank:
    """One replay bank of an origin model: production History replay with one seed's paths."""

    engine: str
    seed: int
    model_key: ModelKey
    replay: RangeModel  # the model's sample and moments, and the seed's PATHS x T count matrix
    index_sha256: str  # of the PATHS x 252 day indices behind the counts, int32 little-endian

    @property
    def paths(self) -> int:
        return len(self.replay.counts)


@dataclass(frozen=True)
class Simulation:
    """Each mix's simulated annual returns on one bank."""

    model_key: ModelKey
    seed: int
    weights: np.ndarray  # M x N as evaluated, read-only
    status: tuple[str, ...]  # OK | NONPOSITIVE_DAILY_GROWTH, per mix
    ruin_day: tuple[date | None, ...]  # the first training date with g_t <= 0, per mix
    years: np.ndarray  # P x M, read-only; a column is NaN when its mix is not OK


@dataclass(frozen=True)
class Evaluation:
    """The figures of each mix on one bank or on several pooled; NaN where the status is not OK."""

    model_key: ModelKey
    seeds: tuple[int, ...]
    paths: int  # simulated annual outcomes behind each figure
    weights: np.ndarray
    status: tuple[str, ...]
    ruin_day: tuple[date | None, ...]
    bad: np.ndarray
    typical: np.ndarray
    good: np.ndarray
    mean: np.ndarray
    es_25: np.ndarray
    p_loss: np.ndarray
    p_below_20: np.ndarray


@dataclass(frozen=True)
class Horizon:
    """A menu's realized horizon at one origin, as the ledger names it."""

    menu: str
    funds: tuple[str, ...]
    month: str
    origin: date
    status: str  # the ledger outcome: COMPLETE | mature_horizon_missing | administratively_immature
    issues: tuple[Issue, ...]  # the ledger's horizon reasons when it is not complete
    days: tuple[date, ...]  # the 252 horizon dates; empty unless complete
    returns: np.ndarray | None  # 252 x N daily returns, read-only; None unless complete
    returns_sha256: str | None  # production `sample_digest` of funds, days and returns


@dataclass(frozen=True)
class PathMetrics:
    """Realized figures of each mix over one run of daily returns (M each)."""

    annual_return: np.ndarray
    loss: np.ndarray  # annual_return < 0
    below_20: np.ndarray  # annual_return < -0.20
    worst_day: np.ndarray
    max_drawdown: np.ndarray  # largest fall from the running peak, initial wealth included, >= 0
    volatility: np.ndarray  # sqrt(252) x the ddof-1 deviation of the daily returns


@dataclass(frozen=True)
class Realized:
    """The realized year of each mix at one origin, or the named reason there is none."""

    status: str  # the horizon's status
    weights: np.ndarray
    metrics: PathMetrics | None  # None unless the horizon is complete: never a partial number


@dataclass(frozen=True)
class Breaches:
    """Realized returns against a Bad-Good band, on the `1[y <= f]` convention."""

    below: int  # y <= bad
    inside: int  # bad < y <= good
    above: int  # y > good


# ---------------------------------------------------------------------------- the three inputs


def origin_model(
    records: Mapping[str, pd.DataFrame], ledger: Ledger, month: str, menu: str
) -> OriginModel:
    """The training side of ``menu`` at the ledger's ``month``; see the module docstring."""
    if ledger.lookback == "ew":
        raise ValueError("protocol 2 pins the fixed-window estimator; the ew lookback weights rows")
    row, entry, funds = _menu_row(ledger, month, menu)
    if not entry.training_eligible:
        reasons = ", ".join(issue.code for issue in entry.issues) or row.status
        raise ValueError(f"{menu} at {month} is not training-eligible: {reasons}")
    stamp = _stamp(row.origin)
    returns = build_returns({fund: _cut(records, fund, stamp) for fund in funds})
    start = select_window(returns, ledger.lookback, row.origin).start
    sources = [symbol for symbol in RISK_FREE_SOURCES if symbol in records]
    source, rate = _risk_free(
        records, {symbol: _record_dates(symbol, records[symbol]) for symbol in sources}, stamp
    )
    frame = window_sample(returns, list(funds), start, row.origin) if start else returns.iloc[:0]
    found = (start, len(frame), source, rate)
    wanted = (entry.window_start, entry.complete_rows, row.risk_free_source, row.risk_free_rate)
    if found != wanted:
        raise ValueError(
            f"{menu} at {month}: the records give window start, complete rows and risk-free "
            f"source and rate {found}, the ledger {wanted}; they are not the ledger's records"
        )
    sample = frame.to_numpy(dtype=float, copy=True)
    sample.setflags(write=False)
    moments = estimate_moments(sample)
    mu_s, _ = menu_beta_blend(moments.mu, moments.cov, rate)
    mu_s.setflags(write=False)
    return OriginModel(
        menu=menu,
        funds=funds,
        month=month,
        origin=row.origin,
        lookback=ledger.lookback,
        days=tuple(day.date() for day in pd.DatetimeIndex(frame.index)),
        sample=sample,
        sample_sha256=frame_digest(frame),
        moments=moments,
        risk_free_rate=rate,
        risk_free_source=source,
        mu_s=mu_s,
    )


def bank(model: OriginModel, seed: int, engine: Engine = "replay") -> Bank:
    """The replay bank of ``seed`` for ``model``: production `range_model`, its count matrix."""
    if engine not in ENGINES:
        raise ValueError(f"unknown engine {engine!r}; this harness evaluates {list(ENGINES)}")
    replay = range_model(model.sample, model.mu_s, model.moments.cov, seed)
    index = np.ascontiguousarray(bootstrap_index(len(model.sample), seed=seed), dtype="<i4")
    return Bank(
        engine=engine,
        seed=seed,
        model_key=model.key,
        replay=replay,
        index_sha256=hashlib.sha256(index.tobytes()).hexdigest(),
    )


def realized_horizon(
    records: Mapping[str, pd.DataFrame], ledger: Ledger, month: str, menu: str
) -> Horizon:
    """The realized horizon of ``menu`` at the ledger's ``month``; see the module docstring."""
    row, entry, funds = _menu_row(ledger, month, menu)
    if entry.outcome != COMPLETE:
        issues = tuple(issue for issue in entry.issues if issue.code in _HORIZON_CODES)
        return Horizon(menu, funds, month, row.origin, entry.outcome, issues, (), None, None)
    end = _stamp(entry.horizon_end)
    returns = build_returns({fund: _cut(records, fund, end) for fund in funds})
    after = np.asarray(pd.DatetimeIndex(returns.index) > _stamp(row.origin))
    block = returns.loc[after, list(funds)]
    days = tuple(day.date() for day in pd.DatetimeIndex(block.index))
    values = block.to_numpy(dtype=float, copy=True)
    span = (days[0], days[-1]) if days else (None, None)
    if (
        len(days) != HORIZON_ROWS
        or span != (entry.horizon_start, entry.horizon_end)
        or not np.isfinite(values).all()
    ):
        raise ValueError(
            f"{menu} at {month}: the records do not give the ledger's complete horizon "
            f"{entry.horizon_start} .. {entry.horizon_end}; they are not the ledger's records"
        )
    values.setflags(write=False)
    digest = sample_digest(list(funds), [day.isoformat() for day in days], values)
    return Horizon(menu, funds, month, row.origin, COMPLETE, (), days, values, digest)


def _menu_row(
    ledger: Ledger, month: str, menu: str
) -> tuple[OriginRow, MenuOrigin, tuple[str, ...]]:
    funds = dict(ledger.menus)[menu]
    row = ledger.row(month)
    return row, row.menu(menu), funds


def _cut(records: Mapping[str, pd.DataFrame], symbol: str, stamp: pd.Timestamp) -> pd.DataFrame:
    """The record's rows dated on or before ``stamp``."""
    record = records[symbol]
    return _through(record, _record_dates(symbol, record), stamp)


# --------------------------------------------------------------------------- training figures


def simulate(model: OriginModel, bank: Bank, weights: npt.ArrayLike) -> Simulation:
    """Each mix's simulated annual returns on ``bank``; rows of ``weights`` are mixes (or one)."""
    if bank.model_key != model.key:
        raise ValueError("the bank was drawn for another origin model")
    mixes = _mixes(len(model.funds), weights)
    years = np.full((bank.paths, len(mixes)), np.nan)
    status: list[str] = []
    ruin_day: list[date | None] = []
    for j in range(len(mixes)):
        mix = mixes[j : j + 1]  # one mix, the same shape on every call
        failed = np.flatnonzero(~(_growth(bank.replay, mix)[:, 0] > 0.0))
        if failed.size:
            status.append(NONPOSITIVE_DAILY_GROWTH)
            ruin_day.append(model.days[int(failed[0])])
            continue
        years[:, j] = simulated_years(bank.replay, mix)[:, 0]
        status.append(OK)
        ruin_day.append(None)
    years.setflags(write=False)
    return Simulation(model.key, bank.seed, mixes, tuple(status), tuple(ruin_day), years)


def _growth(replay: RangeModel, mixes: np.ndarray) -> np.ndarray:
    """The recentred daily growth (T x M) by the operations of production History replay.

    `ranges._replay_years` computes exactly this before it compounds, and raises unless every
    value is positive; the same operations on the same arrays give the same bits.
    """
    mu = mixes @ replay.mu_s
    daily = replay.sample @ mixes.T
    return 1.0 + daily - daily.mean(axis=0) + mu / TRADING_DAYS


def summarize(simulations: Sequence[Simulation]) -> Evaluation:
    """The figures of the mixes of ``simulations`` over all their outcomes, banks in order."""
    if not simulations:
        raise ValueError("summarize needs at least one simulation")
    first = simulations[0]
    seeds = tuple(simulation.seed for simulation in simulations)
    if len(set(seeds)) != len(seeds):
        raise ValueError(f"a bank is pooled twice: seeds {seeds}")
    for other in simulations[1:]:
        if other.model_key != first.model_key or not np.array_equal(other.weights, first.weights):
            raise ValueError("pooled simulations must share the same origin model and weights")
    years = np.concatenate([simulation.years for simulation in simulations], axis=0)
    paths, count = years.shape
    figures = {name: np.full(count, np.nan) for name in FIGURES}
    ok = np.array([status == OK for status in first.status], dtype=bool)
    if ok.any():
        kept = years[:, ok]
        # exact order statistics and an elementwise interpolation: each column on its own
        percentiles = np.percentile(kept, PERCENTILES, axis=0)
        for name, values in zip(("bad", "typical", "good"), percentiles, strict=True):
            figures[name][ok] = values
        figures["p_loss"][ok] = np.count_nonzero(kept < 0.0, axis=0) / paths
        figures["p_below_20"][ok] = np.count_nonzero(kept < LOSS_LINE, axis=0) / paths
        for j in np.flatnonzero(ok):
            outcomes = years[:, j]
            figures["mean"][j] = math.fsum(outcomes.tolist()) / paths
            figures["es_25"][j] = measures.es_25(outcomes)
    for values in figures.values():
        values.setflags(write=False)
    return Evaluation(
        model_key=first.model_key,
        seeds=seeds,
        paths=paths,
        weights=first.weights,
        status=first.status,
        ruin_day=first.ruin_day,
        **figures,
    )


def evaluate(model: OriginModel, bank: Bank, weights: npt.ArrayLike) -> Evaluation:
    """The figures of each mix of ``weights`` on one bank: `summarize([simulate(...)])`."""
    return summarize([simulate(model, bank, weights)])


def _mixes(funds: int, weights: npt.ArrayLike) -> np.ndarray:
    """A private, read-only M x N copy of the mixes (one mix may be given as a vector)."""
    mixes = np.array(np.atleast_2d(np.asarray(weights, dtype=float)), dtype=float, order="C")
    if mixes.ndim != 2 or mixes.shape[1] != funds or len(mixes) == 0:
        raise ValueError(f"weights must be M x {funds} with M >= 1, got shape {mixes.shape}")
    if not np.isfinite(mixes).all():
        raise ValueError("weights must be finite")
    mixes.setflags(write=False)
    return mixes


# ------------------------------------------------------------------------------------ realized


def realized(horizon: Horizon, weights: npt.ArrayLike) -> Realized:
    """The realized year of each mix over ``horizon``, or the horizon's status and no number."""
    mixes = _mixes(len(horizon.funds), weights)
    if horizon.status != COMPLETE or horizon.returns is None:
        return Realized(horizon.status, mixes, None)
    return Realized(COMPLETE, mixes, path_metrics(horizon.returns, mixes))


def path_metrics(returns: npt.ArrayLike, weights: npt.ArrayLike) -> PathMetrics:
    """Constant-weight figures of each mix over T x N daily returns (T >= 2); see the docstring."""
    daily_returns = np.asarray(returns, dtype=float)
    if daily_returns.ndim != 2 or len(daily_returns) < 2:
        raise ValueError(f"returns must be T x N with T >= 2 rows, got {daily_returns.shape}")
    if not np.isfinite(daily_returns).all():
        raise ValueError("returns must be finite")
    mixes = _mixes(daily_returns.shape[1], weights)
    annual, worst, drawdown, volatility = (np.empty(len(mixes)) for _ in range(4))
    for j, mix in enumerate(mixes):
        daily = daily_returns @ mix
        gross = 1.0 + daily
        if not (gross > 0.0).all():
            raise ValueError("a day that loses everything cannot be compounded")
        wealth = np.cumprod(gross)
        peak = np.maximum(np.maximum.accumulate(wealth), 1.0)
        annual[j] = wealth[-1] - 1.0
        worst[j] = daily.min()
        drawdown[j] = (1.0 - wealth / peak).max()
        volatility[j] = math.sqrt(TRADING_DAYS) * float(daily.std(ddof=1))
    return PathMetrics(
        annual_return=annual,
        loss=annual < 0.0,
        below_20=annual < LOSS_LINE,
        worst_day=worst,
        max_drawdown=drawdown,
        volatility=volatility,
    )


# --------------------------------------------------------------------------------- calibration


def pinball(q: float, actual: npt.ArrayLike, forecast: npt.ArrayLike) -> np.ndarray:
    """`(q - 1[y < f]) (y - f)` elementwise, ``actual`` y against the level-``q`` forecast f."""
    if not 0.0 < q < 1.0:
        raise ValueError(f"the quantile level must be in (0, 1), got {q}")
    y, f = _paired(actual, forecast)
    return (q - (y < f)) * (y - f)


def at_or_below(actual: npt.ArrayLike, forecast: npt.ArrayLike) -> np.ndarray:
    """The PIT and coverage indicator `1[y <= f]` of ``actual`` y, elementwise."""
    y, f = _paired(actual, forecast)
    return y <= f


def breaches(actual: npt.ArrayLike, bad: npt.ArrayLike, good: npt.ArrayLike) -> Breaches:
    """How many ``actual`` returns fall below Bad (at or below), inside, and above Good."""
    y, low = _paired(actual, bad)
    y, high = _paired(y, good)
    low = np.broadcast_to(low, y.shape)
    if (low > high).any():
        raise ValueError("Bad must not exceed Good")
    below = int(np.count_nonzero(y <= low))
    above = int(np.count_nonzero(y > high))
    return Breaches(below=below, inside=int(y.size) - below - above, above=above)


def pit(actual: float, outcomes: npt.ArrayLike) -> float:
    """The share of simulated ``outcomes`` at or below the ``actual`` (realized) return."""
    values = np.asarray(outcomes, dtype=float)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("outcomes must be a non-empty vector")
    y, values = _paired(actual, values)
    return float(np.count_nonzero(values <= y)) / values.size


def _paired(a: npt.ArrayLike, b: npt.ArrayLike) -> tuple[np.ndarray, np.ndarray]:
    x, y = np.broadcast_arrays(np.asarray(a, dtype=float), np.asarray(b, dtype=float))
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("realized returns and forecasts must be finite")
    return x, y
