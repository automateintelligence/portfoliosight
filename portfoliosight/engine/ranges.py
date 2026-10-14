"""One-year ranges of a mix (spec 4.9). The range method lives here and nowhere else.

`one_year_ranges(model, weights)` is the single entry: the builder calls it for every mix the
tensor carries and the API calls it for a mix a visitor entered. Replacing the method (the
roadmap's filtered historical simulation, then copulas) changes `range_model` and the body of
`one_year_ranges`; what they return, and so the page, stays as it is.

The method today is a stationary block bootstrap (Politis & Romano 1994) of the mix's own daily
history, at constant weights:

1. `r_t = w'R_t` over the lookback sample, recentred: the sample mean is taken out and the mix's
   daily expected return `mu_s'w / 252` put in. The centre is then the chart's expected return;
   history supplies only the shape (fat tails, runs of bad days).
2. 2,000 one-year paths of 252 days, each a chain of runs of consecutive sample days. A run ends
   with probability 1/21 a day (mean length 21 days), the next one starts on a uniformly drawn
   day, and a run that reaches the last day continues on the first.
3. Each path compounds to a one-year return; the 2.5th, 50th and 97.5th percentiles (NumPy's
   default, linear between order statistics) are the bad, typical and good year.

What the numbers are and are not. Recentring fixes the mean of the daily returns, not of the
compounded year: the typical year sits below `mu_s'w` by roughly half the history's own
variance (about `exp(mu - sigma^2 / 2) - 1`), and that variance is the sample's, not the chart's
shrunk one. With 2,000 paths the 2.5th percentile carries a simulation error of about 0.06
standard deviations of the yearly return (roughly 0.6 points for a mix with 10% risk); the
shared day indices make two mixes comparable, they do not remove that error.

The day indices of step 2 are drawn once per sample length from a fixed seed and used for every
mix, so two mixes differ by their weights alone and a build repeats exactly. Compounding a path
is `exp(sum ln(1 + r))`, and the sum over a path is the path's day counts times the days' log
returns, so all paths of all mixes come from one matrix product. The normal range
`mu -+ 1.96 sigma` is returned beside the bootstrap one, for the details view.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from .stats import RANGE_Z, TRADING_DAYS

PATHS = 2000
HORIZON_DAYS = TRADING_DAYS
MEAN_BLOCK_DAYS = 21
PERCENTILES = (2.5, 50.0, 97.5)
SEED = 20261013
METHOD = {
    "name": "stationary block bootstrap",
    "horizon_days": HORIZON_DAYS,
    "paths": PATHS,
    "mean_block_days": MEAN_BLOCK_DAYS,
    "percentiles": list(PERCENTILES),
    "percentile_method": "linear",
    "seed": SEED,
}


@dataclass(frozen=True)
class RangeModel:
    """What the range method needs for one (menu, lookback); built once, used for every mix."""

    sample: np.ndarray  # T x N daily returns of the lookback sample, unweighted
    mu_s: np.ndarray  # annual expected returns, the chart's
    cov: np.ndarray  # annual covariance, the chart's
    counts: np.ndarray  # PATHS x T: how often each sample day occurs in each path


@lru_cache(maxsize=8)
def bootstrap_index(
    rows: int,
    paths: int = PATHS,
    horizon: int = HORIZON_DAYS,
    mean_block: int = MEAN_BLOCK_DAYS,
    seed: int = SEED,
) -> np.ndarray:
    """The shared day indices of a stationary block bootstrap: `paths` x `horizon`, read-only.

    Row `i` is one synthetic path through a sample of `rows` days. Its first day is uniform;
    every later day is the day after the one before it (the last day is followed by the first)
    unless a new run starts there, which happens with probability `1 / mean_block` and lands on
    a uniform day. Run lengths are therefore geometric with mean `mean_block`.
    """
    if rows < 1 or paths < 1 or horizon < 1 or mean_block < 1:
        raise ValueError("rows, paths, horizon and mean_block must all be at least 1")
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, rows, size=(paths, horizon))
    fresh = rng.random((paths, horizon)) < 1.0 / mean_block
    fresh[:, 0] = True
    # the position of each day's run start along its path, then the offset inside the run
    day = np.broadcast_to(np.arange(horizon), (paths, horizon))
    run_start = np.maximum.accumulate(np.where(fresh, day, 0), axis=1)
    index = (np.take_along_axis(starts, run_start, axis=1) + day - run_start) % rows
    index = index.astype(np.int32)
    index.setflags(write=False)
    return index


@lru_cache(maxsize=4)
def path_counts(rows: int) -> np.ndarray:
    """How often each of `rows` sample days occurs in each bootstrap path: PATHS x rows, read-only.

    Row `i` holds the multiplicities of `bootstrap_index(rows)[i]`, so it sums to the horizon.
    """
    index = bootstrap_index(rows)
    counts = np.zeros((len(index), rows))
    np.add.at(counts, (np.arange(len(index))[:, None], index), 1.0)
    counts.setflags(write=False)
    return counts


def sample_digest(funds: Sequence[str], days: Sequence[str], sample) -> str:
    """SHA-256 of a window's sample: its fund ids, its days and every return, in order.

    The tensor carries it (``lookback.sample_sha256``) so that a range asked for later can be
    proved to come from the very sample the build used; it says nothing about the returns.
    """
    values = np.ascontiguousarray(np.asarray(sample, dtype="<f8"))
    if values.shape != (len(days), len(funds)):
        raise ValueError("a sample has one row per day and one column per fund")
    digest = hashlib.sha256()
    digest.update("\x1f".join(funds).encode())
    digest.update(b"\x1e")
    digest.update("\x1f".join(days).encode())
    digest.update(b"\x1e")
    digest.update(values.tobytes())
    return digest.hexdigest()


def frame_digest(sample) -> str:
    """`sample_digest` of a window sample held as a frame: dated rows, one column per fund."""
    days = [stamp.date().isoformat() for stamp in sample.index]
    return sample_digest([str(fund) for fund in sample.columns], days, sample.to_numpy())


def range_model(sample, mu_s, cov) -> RangeModel:
    """The model for one (menu, lookback) from its sample and the chart's moments."""
    sample = np.asarray(sample, dtype=float)
    mu_s = np.asarray(mu_s, dtype=float)
    cov = np.asarray(cov, dtype=float)
    if sample.ndim != 2 or sample.shape[0] < 2:
        raise ValueError("the sample must be a T x N array with T >= 2")
    funds = sample.shape[1]
    if mu_s.shape != (funds,) or cov.shape != (funds, funds):
        raise ValueError("the sample and the moments must describe the same funds")
    if not np.isfinite(sample).all():
        raise ValueError("the sample holds missing or non-finite returns")
    return RangeModel(sample=sample, mu_s=mu_s, cov=cov, counts=path_counts(len(sample)))


def one_year_ranges(model: RangeModel, weights) -> dict:
    """One-year ranges of each row of `weights` (M x N, or one mix as a vector of N).

    Returns `{"bad", "typical", "good", "normal": {"low", "mid", "high"}}` as arrays of M
    numbers: the bootstrap's 2.5th, 50th and 97.5th percentiles of the compounded one-year
    return, and the normal range `mu -+ 1.96 sigma` around `mu = mu_s'w`. Raises `ValueError`
    for a mix that loses everything on some day of its recentred history.
    """
    mixes = np.atleast_2d(np.asarray(weights, dtype=float))
    if mixes.ndim != 2 or mixes.shape[1] != len(model.mu_s):
        raise ValueError(f"a mix of this menu has {len(model.mu_s)} weights")
    mu = mixes @ model.mu_s
    sigma = np.sqrt(np.einsum("ij,jk,ik->i", mixes, model.cov, mixes))
    daily = model.sample @ mixes.T  # T x M
    growth = 1.0 + daily - daily.mean(axis=0) + mu / TRADING_DAYS
    if not (growth > 0.0).all():
        raise ValueError("a day that loses everything cannot be compounded")
    year = np.expm1(model.counts @ np.log(growth))  # PATHS x M
    percentiles = np.percentile(year, PERCENTILES, axis=0)
    spread = RANGE_Z * sigma
    return {
        "bad": percentiles[0],
        "typical": percentiles[1],
        "good": percentiles[2],
        "normal": {"low": mu - spread, "mid": mu, "high": mu + spread},
    }
