"""The suggested point on a column: a standard-error heuristic (spec 4.8).

Walking down from the frontier mix, a candidate is "within estimation noise" while the return it
gives up is at most one standard error of the paired daily return difference. The give-up uses
the shrunk means, the noise the sample deviation; it is a heuristic, not a significance test.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .stats import TRADING_DAYS

STANDARD_ERRORS = 1.0


def standard_error(d, omega=None) -> float:
    """Annualized standard error of a daily return difference `d`.

    `sqrt(252) * sd(d) / sqrt(T_eff / 252)`: with `omega=None` the sample deviation (ddof = 1)
    and `T_eff = T`; with observation weights the weighted deviation with the sample correction
    `1 / (1 - sum(omega^2))` and `T_eff = 1 / sum(omega^2)`.
    """
    d = np.asarray(d, dtype=float)
    if omega is None:
        deviation = float(d.std(ddof=1))
        t_eff = float(len(d))
    else:
        omega = np.asarray(omega, dtype=float)
        concentration = float((omega**2).sum())
        mean = omega @ d
        deviation = float(np.sqrt(omega @ (d - mean) ** 2 / (1.0 - concentration)))
        t_eff = 1.0 / concentration
    return float(np.sqrt(TRADING_DAYS) * deviation / np.sqrt(t_eff / TRADING_DAYS))


def suggested_floor(
    w_front,
    y_front: float,
    cand_w: Sequence,
    cand_y: Sequence[float],
    mu_s,
    returns,
    omega=None,
) -> float:
    """Return floor of the last candidate within one standard error of the frontier mix.

    `cand_w` / `cand_y` are the column's feasible cells and their floors from the top down to
    the most diversified one (empty for a collapsed ladder); `returns` is the window's T x N
    sample and `omega` its observation weights (`None` for a fixed window). The walk stops at
    the first candidate whose give-up `mu_s' (w_front - w_k)` exceeds its standard error, even
    if a lower one would pass; with no passing candidate the answer is `y_front`.
    """
    if len(cand_w) != len(cand_y):
        raise ValueError("the walk needs one floor per candidate")
    w_front = np.asarray(w_front, dtype=float)
    mu_s = np.asarray(mu_s, dtype=float)
    returns = np.asarray(returns, dtype=float)
    floor = float(y_front)
    for mix, candidate_floor in zip(cand_w, cand_y, strict=True):
        difference = w_front - np.asarray(mix, dtype=float)
        give_up = float(mu_s @ difference)
        if give_up > STANDARD_ERRORS * standard_error(returns @ difference, omega):
            break
        floor = float(candidate_floor)
    return floor
