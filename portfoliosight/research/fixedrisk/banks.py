"""History-replay path bank of the fixed-risk experiment (protocol §4, engine-specific gradients).

`replay_bank(ctx, engine, seed)` is production's History replay (`engine/ranges.py`) for one origin
and seed: the same stationary-bootstrap day indices and count matrix `C` (P x T) as
`range_model(ctx.sample, ctx.mu_s, ctx.cov, seed)`, so `years` equals `simulated_years`.

The search path (`years_and_vjp`) never forms `C @ log g` as a dense product: a bootstrap path is
a chain of runs of consecutive sample days, so its log-sum is a sum of prefix-sum differences over
its runs (about 13 runs per path), and the transpose product `C' u` is a difference array over the
same runs. With `A` the recentred daily returns plus `mu_s / 252` (T x N), `g = 1 + A w` and
`R = exp(C ln g) - 1`, the gradient of `sum_p a_p R_p` is `A' [C' (a * (1 + R)) / g]`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from scipy import sparse

from portfoliosight.engine import ranges
from portfoliosight.engine.stats import TRADING_DAYS

from .contracts import PRIMARY_SEED, Engine, OriginContext

DENSE_ROWS = 64  # a vjp with at most this many weighted paths uses their count rows directly


@dataclass(eq=False)
class ReplayBank:
    """History replay for one (menu, origin, lookback, seed), implementing `PathBank`."""

    seed: int
    paths: int
    growth_bound_ok: bool
    sample: np.ndarray = field(repr=False)  # T x N, as production holds it
    mu_s: np.ndarray = field(repr=False)
    shift: np.ndarray = field(repr=False)  # A = sample + shift: recentred, plus mu_s / 252
    a_matrix: np.ndarray = field(repr=False)  # A, T x N
    counts: np.ndarray = field(repr=False)  # C, P x T
    runs: sparse.csr_matrix = field(repr=False)  # S, P x (T + 1): +1 at run stops, -1 at starts
    runs_t: sparse.csr_matrix = field(repr=False)  # S'
    engine: Engine = "replay"

    def years(self, mixes: np.ndarray) -> np.ndarray:
        """Compounded years (P x M) of the rows of `mixes`, production's own arithmetic."""
        w = np.atleast_2d(np.asarray(mixes, dtype=float))
        daily = self.sample @ w.T
        growth = 1.0 + daily - daily.mean(axis=0) + (w @ self.mu_s) / TRADING_DAYS
        if not self.growth_bound_ok and not (growth > 0.0).all():
            raise ValueError("a day that loses everything cannot be compounded")
        return np.expm1(self.counts @ np.log(growth))

    def years_and_vjp(self, w: np.ndarray) -> tuple[np.ndarray, Callable[[np.ndarray], np.ndarray]]:
        g = 1.0 + self.a_matrix @ w
        if not self.growth_bound_ok and not (g > 0.0).all():
            raise ValueError("a day that loses everything cannot be compounded")
        prefix = np.empty(len(g) + 1)
        prefix[0] = 0.0
        np.cumsum(np.log(g), out=prefix[1:])
        years = np.expm1(self.runs @ prefix)  # C ln g = S L ln g, L the prefix sum
        gross = 1.0 + years

        def vjp(a: np.ndarray) -> np.ndarray:
            u = a * gross
            hot = np.flatnonzero(u)
            if len(hot) <= DENSE_ROWS:
                day = u[hot] @ self.counts[hot]
            else:  # C' u = L' S' u: a reversed cumulative sum of S' u
                s = self.runs_t @ u
                day = np.cumsum(s[:0:-1])[::-1]
            return (day / g) @ self.a_matrix

        return years, vjp


def replay_bank(ctx: OriginContext, engine: Engine = "replay", seed: int = PRIMARY_SEED):
    """Production History replay for `ctx` on the bootstrap of `seed` (protocol §3 engines)."""
    if engine != "replay":
        raise ValueError(f"replay_bank builds the replay engine only, got {engine!r}")
    model = ranges.range_model(ctx.sample, ctx.mu_s, ctx.cov, seed)
    sample = model.sample
    rows = len(sample)
    shift = -sample.mean(axis=0) + model.mu_s / TRADING_DAYS
    a_matrix = sample + shift
    b = 1.0 + a_matrix  # g_t = sum_i w_i b_ti when 1'w = 1 (protocol §4)
    index = ranges.bootstrap_index(rows, seed=seed)
    paths, horizon = index.shape
    breaks = np.ones((paths, horizon), dtype=bool)
    breaks[:, 1:] = index[:, 1:] != index[:, :-1] + 1
    ends = np.ones((paths, horizon), dtype=bool)
    ends[:, :-1] = breaks[:, 1:]
    seg_path = np.nonzero(breaks)[0]
    seg_start = index[breaks].astype(np.intp)
    seg_stop = index[ends].astype(np.intp) + 1
    runs = sparse.csr_matrix(
        (
            np.concatenate([np.ones(len(seg_path)), -np.ones(len(seg_path))]),
            (np.concatenate([seg_path, seg_path]), np.concatenate([seg_stop, seg_start])),
        ),
        shape=(paths, rows + 1),
    )
    runs.sum_duplicates()
    return ReplayBank(
        seed=seed,
        paths=paths,
        growth_bound_ok=bool(b.min() > 0.0),
        sample=sample,
        mu_s=model.mu_s,
        shift=shift,
        a_matrix=a_matrix,
        counts=model.counts,
        runs=runs,
        runs_t=runs.T.tocsr(),
    )
