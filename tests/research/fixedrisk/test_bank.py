"""Replay path bank (piece 1): production equality, vector-Jacobian products, growth bound."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from portfoliosight.engine import ranges
from portfoliosight.research.fixedrisk.banks import replay_bank
from tests.research.fixedrisk.optimizer_data import synthetic_context

SEED = 20261013


@pytest.fixture(scope="module")
def ctx():
    return synthetic_context()


@pytest.fixture(scope="module")
def bank(ctx):
    return replay_bank(ctx, "replay", SEED)


def _mixes(n: int, count: int, seed: int = 3) -> np.ndarray:
    return np.random.default_rng(seed).dirichlet(np.ones(n), size=count)


def test_years_equal_production_simulated_years(ctx, bank):
    model = ranges.range_model(ctx.sample, ctx.mu_s, ctx.cov, SEED)
    mixes = _mixes(5, 6)
    expected = ranges.simulated_years(model, mixes)
    np.testing.assert_allclose(bank.years(mixes), expected, rtol=0, atol=1e-12)
    for j, w in enumerate(mixes):
        years, _ = bank.years_and_vjp(w)
        np.testing.assert_allclose(years, expected[:, j], rtol=0, atol=1e-12)
    assert bank.paths == ranges.PATHS and bank.engine == "replay" and bank.seed == SEED


def test_other_seed_gives_other_bank(ctx, bank):
    other = replay_bank(ctx, "replay", SEED + 1)
    w = np.full(5, 0.2)
    assert not np.allclose(other.years(w), bank.years(w))


@pytest.mark.parametrize("hot", [5, 500])  # the dense-row and run-difference branches
def test_vjp_equals_count_matrix_formula(bank, hot):
    w = _mixes(5, 1)[0]
    years, vjp = bank.years_and_vjp(w)
    rng = np.random.default_rng(hot)
    a = np.zeros(bank.paths)
    a[rng.choice(bank.paths, hot, replace=False)] = rng.normal(size=hot)
    g = 1.0 + bank.a_matrix @ w
    expected = bank.a_matrix.T @ (bank.counts.T @ (a * (1.0 + years)) / g)
    np.testing.assert_allclose(vjp(a), expected, rtol=1e-10, atol=1e-12)


def test_vjp_matches_central_differences(bank):
    w = _mixes(5, 1, seed=9)[0]
    a = np.random.default_rng(1).normal(size=bank.paths)
    _, vjp = bank.years_and_vjp(w)
    grad = vjp(a)
    h = 1e-6
    for i in range(5):
        e = np.zeros(5)
        e[i] = h
        fd = (a @ bank.years_and_vjp(w + e)[0] - a @ bank.years_and_vjp(w - e)[0]) / (2 * h)
        assert fd == pytest.approx(grad[i], rel=1e-6, abs=1e-8)


def test_growth_bound(ctx, bank):
    assert bank.growth_bound_ok
    sample = np.array(ctx.sample)
    sample[10, 0] = -1.5  # a day below -100% for fund 0: b_t0 <= 0
    broken = replay_bank(replace(ctx, sample=sample), "replay", SEED)
    assert not broken.growth_bound_ok
    with pytest.raises(ValueError):
        broken.years(np.array([1.0, 0, 0, 0, 0]))
    with pytest.raises(ValueError):
        broken.years_and_vjp(np.array([1.0, 0, 0, 0, 0]))
    assert np.isfinite(broken.years(np.array([0, 0.5, 0.5, 0, 0]))).all()


def test_rejects_other_engines(ctx):
    with pytest.raises(ValueError):
        replay_bank(ctx, "garch", SEED)  # type: ignore[arg-type]
