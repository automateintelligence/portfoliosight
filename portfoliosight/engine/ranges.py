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

The volatility model starts from a simulated panel `l` of the funds' daily log returns (`shape.py`:
2,000 paths of 252 days, one shared draw of real shock rows) and puts the chart's level on it in
two steps (simulation engines spec 4.5), with `m`, `s` the chart's daily mean and volatility:

1. per fund, in log space: `l' = m~ + (l - l_bar) * s~ / sd`, with `l_bar`, `sd` the fund's pooled
   mean and population deviation over every path and day of `l`, and `(m~, s~)` the lognormal
   equivalents of `(m, s)`: `s~^2 = ln(1 + s^2 / (1 + m)^2)`, `m~ = ln(1 + m) - s~^2 / 2`. Then
   `R' = expm1(l') > -1`. A fund whose simulated returns do not vary is its daily expected
   return, `R' = m` exactly;
2. per mix, in simple space: `y = w'R'`, `y' = m_w + k_w (y - w'R_bar)` with `k_w = s_w / sd(y)`,
   `sd(y)^2 = w' Sigma_R w` from the pooled mean `R_bar` and (ddof 0) covariance `Sigma_R` of `R'`
   (`y' = m_w` when `sd(y) = 0`). Every mix's days then have the chart's mean `m_w` and volatility
   `s_w` exactly, and `y'` is the sum over funds of `w_n [m_n + k_w (R'_n - R_bar_n)]`.

`R'` is a function of `l` fund by fund, so it is never stored: it is computed for a chunk of paths
at a time, twice for its moments (the mean, then the centred cross-products) and once for the
years. Each chunk's levelled days and the gross days `1 + y' = R' v + 1 + b` (`v = k_w w`, one
constant `b` per mix) of up to `MIX_BLOCK` mixes share at most `WORK_BYTES`; a matrix product
gives the gross days, their product over each path the year, `Y = prod(1 + y') - 1`. A path with
a day at or below -100% (`1 + y' <= 0`) is absorbed (`RUIN`): its year is exactly -100% and
`one_year_ranges` counts it. History replay raises on such a day instead.
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
WORK_BYTES = 64 * 2**20  # the volatility model's work buffers for a chunk of paths, at most
MIX_BLOCK = 1024  # at most this many mixes compounded together over each chunk of paths
SCALE = "sd"  # step 1 scales each fund's log returns by their pooled population deviation
RUIN = "absorb"  # a volatility-model path with a day at or below -100% is a total loss
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
    panel: np.ndarray  # P x H x N simulated daily log returns of the funds, read-only
    mean: np.ndarray  # each fund's mean log return over every path and day
    sd: np.ndarray  # their population deviation; 0 for a fund whose returns never vary
    level_mean: np.ndarray  # each fund's pooled mean of R', its levelled simple returns
    level_cov: np.ndarray  # the pooled (ddof 0) covariance of R' over every path and day
    mu_s: np.ndarray  # annual expected returns, the chart's
    cov: np.ndarray  # annual covariance, the chart's
    seed: int = SEED  # of the shock-row draw behind `panel`


@dataclass(frozen=True)
class _StepOne:
    """Step 1 of a model as arrays per fund: `R' = expm1(c + a l)`, and `R' = m` where `still`."""

    a: np.ndarray
    c: np.ndarray
    m: np.ndarray
    still: np.ndarray


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

    `panel` is `shape.simulate_panel`'s P x H x N array of daily log returns (drawn with `seed`);
    it is kept, not copied. Its pooled moments, and those of its levelled simple returns `R'`,
    are taken here once, in chunks of paths. Raises `ValueError` when a levelled return overflows
    (a chart volatility far beyond any fund's).
    """
    panel = np.asarray(panel, dtype=np.float64)
    if panel.ndim != 3 or panel.shape[0] * panel.shape[1] < 2 or panel.shape[2] < 1:
        raise ValueError("the simulated panel must be a P x H x N array with P x H >= 2")
    mu_s, cov = _chart_moments(mu_s, cov, panel.shape[2])
    if not (np.isfinite(mu_s).all() and np.isfinite(cov).all()):
        raise ValueError("the chart's moments must be finite")
    mean, spread, low, high = _pooled_spread(panel)
    # A fund varies when its simulated returns do: their exact range says so, where a deviation
    # taken from a pooled mean (itself rounded over every path and day) would not.
    peak = np.maximum(np.abs(low), np.abs(high))
    sd = np.where(high - low > ROUNDING_NOISE * peak, spread, 0.0)
    step = _step_one(mu_s, cov, mean, sd)
    level_mean, level_cov = _levelled_moments(panel, step)
    view = panel.view()
    view.setflags(write=False)
    return GarchRangeModel(
        panel=view,
        mean=mean,
        sd=sd,
        level_mean=level_mean,
        level_cov=level_cov,
        mu_s=mu_s,
        cov=cov,
        seed=seed,
    )


def simulated_years(model: RangeModel | GarchRangeModel, weights) -> np.ndarray:
    """The compounded one-year returns of each mix on every path of its engine: P x M.

    `weights` is M x N, or one mix as a vector of N. Under History replay a mix that loses
    everything on some sample day raises `ValueError`; under the volatility model such a path's
    year is -100% (`RUIN`).
    """
    return _years(model, _mixes(model, weights))[0]


def one_year_ranges(model: RangeModel | GarchRangeModel, weights) -> dict:
    """One-year ranges of each row of `weights` (M x N, or one mix as a vector of N).

    Returns `{"bad", "typical", "good", "normal": {"low", "mid", "high"}, "ruined"}` as arrays of
    M numbers: the 2.5th, 50th and 97.5th percentiles of the model's compounded one-year returns,
    the normal range `mu -+ 1.96 sigma` around `mu = mu_s'w`, the same for every engine, and how
    many of the mix's paths lost everything (always 0 under History replay, which raises
    `ValueError` for a mix that loses everything on some sample day).
    """
    mixes = _mixes(model, weights)
    mu = mixes @ model.mu_s
    sigma = np.sqrt(np.einsum("ij,jk,ik->i", mixes, model.cov, mixes))
    year, ruined = _years(model, mixes)
    percentiles = np.percentile(year, PERCENTILES, axis=0)
    spread = RANGE_Z * sigma
    return {
        "bad": percentiles[0],
        "typical": percentiles[1],
        "good": percentiles[2],
        "normal": {"low": mu - spread, "mid": mu, "high": mu + spread},
        "ruined": ruined,
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
    if not np.isfinite(mixes).all():
        raise ValueError("a mix's weights must be finite")
    return mixes


def _years(model: RangeModel | GarchRangeModel, mixes: np.ndarray) -> tuple[np.ndarray, ...]:
    """Each mix's years on every path (P x M) and how many of its paths were absorbed (M)."""
    if isinstance(model, GarchRangeModel):
        return _garch_years(model, mixes)
    return _replay_years(model, mixes), np.zeros(len(mixes), dtype=np.int64)


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


def _pooled_spread(panel: np.ndarray) -> tuple[np.ndarray, ...]:
    """Each fund's mean, population deviation, lowest and highest return over every path and day.

    Two passes over chunks of paths: the mean first, then the centred squares, so the deviation
    never loses digits to a difference of large sums.
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
    squares = np.zeros(funds)
    buffer = _work_buffer(chunks, days, funds)
    for part in chunks:
        rows = panel[part].reshape(-1, funds)
        centred = np.subtract(rows, mean, out=buffer[: len(rows)])
        squares += np.einsum("ij,ij->j", centred, centred)
    return mean, np.sqrt(squares / (paths * days)), low, high


def _step_one(mu_s: np.ndarray, cov: np.ndarray, mean: np.ndarray, sd: np.ndarray) -> _StepOne:
    """Step 1's per-fund arrays: the chart's daily targets matched to log space (lognormal)."""
    m = mu_s / TRADING_DAYS
    log_var = np.log1p(np.diag(cov) / TRADING_DAYS / (1.0 + m) ** 2)
    still = ~(sd > 0)
    a = np.divide(np.sqrt(log_var), sd, out=np.zeros_like(sd), where=~still)
    return _StepOne(a=a, c=np.log1p(m) - log_var / 2.0 - a * mean, m=m, still=still)


def _levelled(rows: np.ndarray, step: _StepOne, out: np.ndarray) -> np.ndarray:
    """Step 1 on rows of log returns (days x N), written into `out`: `R' = expm1(c + a l)`."""
    np.multiply(rows, step.a, out=out)
    out += step.c
    with np.errstate(over="ignore"):  # `_levelled_moments` reports an overflow as an error
        np.expm1(out, out=out)
    out[:, step.still] = step.m[step.still]
    return out


def _levelled_moments(panel: np.ndarray, step: _StepOne) -> tuple[np.ndarray, np.ndarray]:
    """The pooled mean and (ddof 0) covariance of `R'`, two passes over chunks of paths.

    A fund that never varies has `R' = m` exactly and so is given that mean exactly: its row and
    column of the covariance are then exactly zero, never rounding a mix's spread could feel.
    """
    paths, days, funds = panel.shape
    chunks = _path_chunks(paths, days * funds * 8)
    buffer = _work_buffer(chunks, days, funds)
    total = np.zeros(funds)
    for part in chunks:
        rows = panel[part].reshape(-1, funds)
        levelled = _levelled(rows, step, buffer[: len(rows)])
        if not np.isfinite(levelled).all():
            raise ValueError("a levelled simulated return is not finite")
        total += levelled.sum(axis=0)
    mean = total / (paths * days)
    mean[step.still] = step.m[step.still]
    scatter = np.zeros((funds, funds))
    for part in chunks:
        rows = panel[part].reshape(-1, funds)
        centred = _levelled(rows, step, buffer[: len(rows)])
        centred -= mean
        scatter += centred.T @ centred
    scatter /= paths * days
    return mean, (scatter + scatter.T) / 2.0


def _garch_terms(model: GarchRangeModel, mixes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each mix's weights on the levelled returns (M x N) and its daily constant (M)."""
    m_w = mixes @ (model.mu_s / TRADING_DAYS)
    s_w = np.sqrt(np.einsum("ij,jk,ik->i", mixes, model.cov, mixes) / TRADING_DAYS)
    sd_y = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", mixes, model.level_cov, mixes), 0.0))
    k = np.divide(s_w, sd_y, out=np.zeros_like(s_w), where=sd_y > 0)
    return k[:, None] * mixes, m_w - k * (mixes @ model.level_mean)


def _garch_years(model: GarchRangeModel, mixes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    weights, shift = _garch_terms(model, mixes)
    step = _step_one(model.mu_s, model.cov, model.mean, model.sd)
    paths, days, funds = model.panel.shape
    width = min(MIX_BLOCK, len(mixes))
    blocks = [slice(start, start + width) for start in range(0, len(mixes), width)]
    v = [np.ascontiguousarray(weights[block].T) for block in blocks]  # N x B each
    chunks = _path_chunks(paths, days * (funds + width) * 8)
    levelled_buffer = _work_buffer(chunks, days, funds)
    gross_buffer = _work_buffer(chunks, days, width).reshape(-1)  # each block's days contiguous
    years = np.empty((paths, len(mixes)))
    ruined = np.zeros(len(mixes), dtype=np.int64)
    for part in chunks:
        rows = model.panel[part].reshape(-1, funds)
        levelled = _levelled(rows, step, levelled_buffer[: len(rows)])
        for block, weights_t in zip(blocks, v, strict=True):
            gross_out = gross_buffer[: len(rows) * weights_t.shape[1]]
            gross = np.matmul(levelled, weights_t, out=gross_out.reshape(len(rows), -1))
            gross += 1.0 + shift[block]
            daily = gross.reshape(-1, days, weights_t.shape[1])
            product = daily.prod(axis=1)
            lost = daily.min(axis=1) <= 0.0  # a day that loses everything: the path is absorbed
            product[lost] = 0.0
            years[part, block] = product
            ruined[block] += lost.sum(axis=0)
    years -= 1.0
    return years, ruined
