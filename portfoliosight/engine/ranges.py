"""One-year ranges of a mix (spec 4.9; simulation engines spec 4). Every range method lives here.

`one_year_ranges(model, weights)` is the single entry: the builder calls it for every mix the
tensor carries and the API calls it for a mix a visitor entered. The model names its engine
(`model.engine`): `RangeModel` is History replay (`replay`), `GarchRangeModel` the volatility
model (`garch`). Both return the same figures, so the page reads every engine the same way;
`simulated_years` is the level below, the compounded years themselves.

History replay is a stationary block bootstrap (Politis & Romano 1994) of the mix's own daily
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

The volatility model starts from a simulated panel `R` of the funds' daily returns (`shape.py`:
2,000 paths of 252 days, one shared draw of real shock rows) and puts the chart's level on it in
two affine steps (simulation engines spec 4.5), with `m`, `s` the chart's daily mean and
volatility and `R_bar`, `sd` each fund's pooled mean and population deviation over every path and
day of `R`:

1. per fund, `R' = m + (R - R_bar) * s / sd` (a fund whose simulated returns do not vary is its
   daily expected return);
2. per mix, `y = w'R'` has mean `m_w`; `y' = m_w + k_w (y - m_w)` with `k_w = s_w / sd(y)`, and
   `sd(y)^2 = (w a)' Sigma_R (w a)` from the pooled covariance `Sigma_R` of `R`, `a = s / sd`
   (`y' = m_w` when `sd(y) = 0`).

Both steps are affine, so a mix's day is `v'R + b` with `v = k_w (w a)` and one constant `b` per
mix: `R'` is never formed. Up to `MIX_BLOCK` mixes are compounded together over chunks of paths,
each chunk's days in one buffer of at most `WORK_BYTES`: the gross days `1 + y'` of every mix
from one matrix product (a few paths against many mixes, the shape BLAS does well), then their
product over each path, `Y = prod(1 + y') - 1`. A day at or below -100% raises, as for History
replay.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import ClassVar

import numpy as np

from .stats import RANGE_Z, ROUNDING_NOISE, TRADING_DAYS

PATHS = 2000
HORIZON_DAYS = TRADING_DAYS
MEAN_BLOCK_DAYS = 21
PERCENTILES = (2.5, 50.0, 97.5)
SEED = 20261013
ENGINES = ("replay", "garch")  # the engines a build can compute, in the order they are reported
DEFAULT_ENGINE = "replay"
WORK_BYTES = 64 * 2**20  # the largest temporary array the volatility model's ranges allocate
MIX_BLOCK = 1024  # at most this many mixes compounded together over each chunk of paths
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
    """History replay for one (menu, lookback); built once, used for every mix."""

    engine: ClassVar[str] = "replay"
    sample: np.ndarray  # T x N daily returns of the lookback sample, unweighted
    mu_s: np.ndarray  # annual expected returns, the chart's
    cov: np.ndarray  # annual covariance, the chart's
    counts: np.ndarray  # PATHS x T: how often each sample day occurs in each path
    seed: int = SEED  # of the day indices behind `counts`


@dataclass(frozen=True)
class GarchRangeModel:
    """The volatility model for one (menu, lookback): a simulated panel and its pooled moments."""

    engine: ClassVar[str] = "garch"
    panel: np.ndarray  # P x H x N simulated daily returns of the funds, read-only
    mean: np.ndarray  # each fund's mean over every path and day
    sd: np.ndarray  # each fund's population deviation; 0 for one whose returns never vary
    cov_sim: np.ndarray  # the funds' pooled (ddof 0) covariance over every path and day
    mu_s: np.ndarray  # annual expected returns, the chart's
    cov: np.ndarray  # annual covariance, the chart's
    seed: int = SEED  # of the shock-row draw behind `panel`


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
def path_counts(rows: int, seed: int = SEED) -> np.ndarray:
    """How often each of `rows` sample days occurs in each bootstrap path: PATHS x rows, read-only.

    Row `i` holds the multiplicities of `bootstrap_index(rows, seed=seed)[i]`, so it sums to the
    horizon.
    """
    index = bootstrap_index(rows, seed=seed)
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


def range_model(sample, mu_s, cov, seed: int = SEED) -> RangeModel:
    """History replay for one (menu, lookback) from its sample and the chart's moments."""
    sample = np.asarray(sample, dtype=float)
    if sample.ndim != 2 or sample.shape[0] < 2:
        raise ValueError("the sample must be a T x N array with T >= 2")
    mu_s, cov = _chart_moments(mu_s, cov, sample.shape[1])
    if not np.isfinite(sample).all():
        raise ValueError("the sample holds missing or non-finite returns")
    counts = path_counts(len(sample), seed)
    return RangeModel(sample=sample, mu_s=mu_s, cov=cov, counts=counts, seed=seed)


def garch_range_model(panel, mu_s, cov, seed: int = SEED) -> GarchRangeModel:
    """The volatility model for one (menu, lookback) from a simulated panel and the chart's moments.

    `panel` is `shape.simulate_panel`'s P x H x N array (drawn with `seed`); it is kept, not
    copied. Its pooled mean and covariance are taken here once, in chunks of paths.
    """
    panel = np.asarray(panel, dtype=np.float64)
    if panel.ndim != 3 or panel.shape[0] * panel.shape[1] < 2 or panel.shape[2] < 1:
        raise ValueError("the simulated panel must be a P x H x N array with P x H >= 2")
    mu_s, cov = _chart_moments(mu_s, cov, panel.shape[2])
    mean, cov_sim, low, high = _pooled_moments(panel)
    # A fund varies when its simulated returns do: their exact spread says so, where a deviation
    # taken from a pooled mean (itself rounded over every path and day) would not.
    peak = np.maximum(np.abs(low), np.abs(high))
    sd = np.where(high - low > ROUNDING_NOISE * peak, np.sqrt(np.diag(cov_sim)), 0.0)
    view = panel.view()
    view.setflags(write=False)
    return GarchRangeModel(
        panel=view, mean=mean, sd=sd, cov_sim=cov_sim, mu_s=mu_s, cov=cov, seed=seed
    )


def simulated_years(model: RangeModel | GarchRangeModel, weights) -> np.ndarray:
    """The compounded one-year returns of each mix on every path of its engine: P x M.

    `weights` is M x N, or one mix as a vector of N. Raises `ValueError` for a mix that loses
    everything on some simulated day.
    """
    mixes = _mixes(model, weights)
    if isinstance(model, GarchRangeModel):
        return _garch_years(model, mixes)
    return _replay_years(model, mixes)


def one_year_ranges(model: RangeModel | GarchRangeModel, weights) -> dict:
    """One-year ranges of each row of `weights` (M x N, or one mix as a vector of N).

    Returns `{"bad", "typical", "good", "normal": {"low", "mid", "high"}}` as arrays of M
    numbers: the 2.5th, 50th and 97.5th percentiles of the model's compounded one-year returns,
    and the normal range `mu -+ 1.96 sigma` around `mu = mu_s'w`, the same for every engine.
    Raises `ValueError` for a mix that loses everything on some simulated day.
    """
    mixes = _mixes(model, weights)
    mu = mixes @ model.mu_s
    sigma = np.sqrt(np.einsum("ij,jk,ik->i", mixes, model.cov, mixes))
    year = simulated_years(model, mixes)
    percentiles = np.percentile(year, PERCENTILES, axis=0)
    spread = RANGE_Z * sigma
    return {
        "bad": percentiles[0],
        "typical": percentiles[1],
        "good": percentiles[2],
        "normal": {"low": mu - spread, "mid": mu, "high": mu + spread},
    }


def _chart_moments(mu_s, cov, funds: int) -> tuple[np.ndarray, np.ndarray]:
    mu_s = np.asarray(mu_s, dtype=float)
    cov = np.asarray(cov, dtype=float)
    if mu_s.shape != (funds,) or cov.shape != (funds, funds):
        raise ValueError("the sample and the moments must describe the same funds")
    return mu_s, cov


def _mixes(model: RangeModel | GarchRangeModel, weights) -> np.ndarray:
    mixes = np.atleast_2d(np.asarray(weights, dtype=float))
    if mixes.ndim != 2 or mixes.shape[1] != len(model.mu_s):
        raise ValueError(f"a mix of this menu has {len(model.mu_s)} weights")
    return mixes


def _replay_years(model: RangeModel, mixes: np.ndarray) -> np.ndarray:
    mu = mixes @ model.mu_s
    daily = model.sample @ mixes.T  # T x M
    growth = 1.0 + daily - daily.mean(axis=0) + mu / TRADING_DAYS
    if not (growth > 0.0).all():
        raise ValueError("a day that loses everything cannot be compounded")
    return np.expm1(model.counts @ np.log(growth))  # PATHS x M


def _path_chunks(paths: int, bytes_per_path: int) -> list[slice]:
    """Runs of whole paths whose buffer of `bytes_per_path` each stays within `WORK_BYTES`."""
    step = max(1, WORK_BYTES // bytes_per_path)
    return [slice(start, min(start + step, paths)) for start in range(0, paths, step)]


def _work_buffer(chunks: list[slice], days: int, width: int) -> np.ndarray:
    """One buffer for every chunk's days: allocated once, so the pages are touched once."""
    return np.empty((max(part.stop - part.start for part in chunks) * days, width))


def _pooled_moments(panel: np.ndarray) -> tuple[np.ndarray, ...]:
    """Each fund's mean, the pooled (ddof 0) covariance, and each fund's lowest and highest return.

    Two passes over chunks of paths: the mean first, then the centred cross-products, so the
    covariance never loses digits to a difference of large sums.
    """
    paths, days, funds = panel.shape
    chunks = _path_chunks(paths, days * funds * 8)
    total = np.zeros(funds)
    low, high = np.full(funds, np.inf), np.full(funds, -np.inf)
    for part in chunks:
        rows = panel[part].reshape(-1, funds)
        if not np.isfinite(rows).all():
            raise ValueError("the simulated panel holds non-finite returns")
        total += rows.sum(axis=0)
        low, high = np.minimum(low, rows.min(axis=0)), np.maximum(high, rows.max(axis=0))
    mean = total / (paths * days)
    scatter = np.zeros((funds, funds))
    buffer = _work_buffer(chunks, days, funds)
    for part in chunks:
        rows = panel[part].reshape(-1, funds)
        centred = np.subtract(rows, mean, out=buffer[: len(rows)])
        scatter += centred.T @ centred
    scatter /= paths * days
    return mean, (scatter + scatter.T) / 2.0, low, high


def _garch_terms(model: GarchRangeModel, mixes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each mix's effective weights on the raw panel (M x N) and its daily constant (M)."""
    m = model.mu_s / TRADING_DAYS
    s = np.sqrt(np.diag(model.cov) / TRADING_DAYS)
    a = np.divide(s, model.sd, out=np.zeros_like(s), where=model.sd > 0)
    c = m - a * model.mean
    m_w = mixes @ m
    s_w = np.sqrt(np.einsum("ij,jk,ik->i", mixes, model.cov, mixes) / TRADING_DAYS)
    u = mixes * a
    sd_y = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", u, model.cov_sim, u), 0.0))
    k = np.divide(s_w, sd_y, out=np.zeros_like(s_w), where=sd_y > 0)
    return k[:, None] * u, m_w + k * (mixes @ c - m_w)


def _garch_years(model: GarchRangeModel, mixes: np.ndarray) -> np.ndarray:
    weights, shift = _garch_terms(model, mixes)
    paths, days, funds = model.panel.shape
    years = np.empty((paths, len(mixes)))
    for start in range(0, len(mixes), MIX_BLOCK):
        block = slice(start, start + MIX_BLOCK)
        v = np.ascontiguousarray(weights[block].T)  # N x B
        width = v.shape[1]
        chunks = _path_chunks(paths, days * width * 8)
        buffer = _work_buffer(chunks, days, width)
        for part in chunks:
            rows = model.panel[part].reshape(-1, funds)
            gross = np.matmul(rows, v, out=buffer[: len(rows)])
            gross += 1.0 + shift[block]
            if not gross.min() > 0.0:
                raise ValueError("a day that loses everything cannot be compounded")
            years[part, block] = gross.reshape(-1, days, width).prod(axis=1)
    years -= 1.0
    return years
