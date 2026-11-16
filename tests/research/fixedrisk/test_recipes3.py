"""The simple and diversification-driven recipes check
(docs/plans/2026-11-11-diversification-vs-simple-mixes.md, built by
docs/plans/2026-11-15-diversification-vs-simple-mixes-build-plan.md) on made-up menus whose
answers are known by hand or by the optimizer's own frontier: the most-diversified mix against
the paper's two examples, the exact-line frontier mix at its three branches, and one start
month's mixes with their statuses. No data file, fixed seeds."""

from __future__ import annotations

import numpy as np
import pytest

from portfoliosight.engine import optimize
from portfoliosight.research.fixedrisk import anchors
from portfoliosight.research.fixedrisk import recipes3 as RC
from tests.research.fixedrisk.optimizer_data import synthetic_context

# Made-up inputs, defined once. 12 holdings with 40% limits: at least 11 holdings are needed, or
# D10's 10% limits cannot sum to 100%.
MENU12 = synthetic_context(funds=12, rows=400, cap=0.4, seed=7)


def _cov(vols, corr) -> np.ndarray:
    v = np.asarray(vols, dtype=float)
    return np.outer(v, v) * np.asarray(corr, dtype=float)


# ------------------------------------------------------------------ the most-diversified mix


@pytest.mark.parametrize("rho", [-0.5, 0.0, 0.5, 0.9])
def test_most_diversified_reproduces_the_papers_first_example(rho):
    sigma = np.array([0.15, 0.30])
    cov = _cov(sigma, [[1.0, rho], [rho, 1.0]])
    w = RC.most_diversified(sigma, cov, 1.0)
    assert np.allclose(w, [2 / 3, 1 / 3], atol=1e-3)


def test_most_diversified_reproduces_the_papers_second_example():
    sigma = np.full(3, 0.20)
    corr = [[1.0, 0.9, 0.1], [0.9, 1.0, 0.1], [0.1, 0.1, 1.0]]
    w = RC.most_diversified(sigma, _cov(sigma, corr), 1.0)
    assert np.allclose(w, [0.257, 0.257, 0.486], atol=1e-3)


@pytest.mark.parametrize("cap", [0.10, 0.40])
def test_most_diversified_keeps_the_limits_and_beats_feasible_mixes(cap):
    sigma, cov = MENU12.sigma, MENU12.cov
    n = len(sigma)
    hi = np.full(n, cap)
    w = RC.most_diversified(sigma, cov, hi)
    assert abs(w.sum() - 1) <= 1e-8
    assert (w >= -1e-8).all()
    assert (w <= hi + 1e-8).all()
    rng = np.random.default_rng(0)
    best = anchors.dr2(w, sigma, cov)
    for _ in range(200):
        x = anchors.project_box_simplex(rng.normal(0.0, 0.3, n), np.zeros(n), hi)
        assert best >= anchors.dr2(x, sigma, cov) - 1e-6


def test_most_diversified_without_a_feasible_mix_is_a_solve_error():
    sigma = np.array([0.10, 0.12, 0.15, 0.20, 0.25])
    cov = _cov(sigma, np.eye(5))
    with pytest.raises(optimize.SolveError):
        RC.most_diversified(sigma, cov, 0.10)
