"""Search objectives (piece 1): linear quantiles, kernel quantiles, gradients, figures."""

from __future__ import annotations

import math

import numpy as np
import pytest

from portfoliosight.engine import measures
from portfoliosight.research.fixedrisk.agreement import fdcheck
from portfoliosight.research.fixedrisk.banks import replay_bank
from portfoliosight.research.fixedrisk.contracts import ARMS, QUANTILES
from portfoliosight.research.fixedrisk.objective import (
    Evaluator,
    arm_value,
    exact_quantile,
    exact_quantiles,
    figures,
    kernel_quantile,
    kernel_weights,
    linear_point,
)
from tests.research.fixedrisk.optimizer_data import synthetic_context


@pytest.fixture(scope="module")
def bank():
    return replay_bank(synthetic_context(), "replay", 20261013)


@pytest.mark.parametrize("paths", [2000, 1999, 7])
def test_exact_quantiles_equal_numpy_linear(paths):
    rng = np.random.default_rng(paths)
    for _ in range(20):
        years = rng.normal(0.05, 0.1, size=paths)
        values, _ = exact_quantiles(years)
        expected = np.percentile(years, [2.5, 50, 97.5], method="linear")
        np.testing.assert_array_equal(values, expected)
        for q, e in zip(QUANTILES, expected, strict=True):
            assert exact_quantile(years, q)[0] == e


def test_linear_point_for_2000_paths():
    j, f = linear_point(2000, 0.025)
    assert j == 49 and f == pytest.approx(0.975)  # 0.025 R_(50) + 0.975 R_(51), 1-based


def test_exact_weights_two_paths_and_ties():
    years = np.random.default_rng(0).normal(size=2000)
    value, idx, w = exact_quantile(years, 0.025)
    assert len(idx) == 2 and w.sum() == pytest.approx(1.0)
    assert value == pytest.approx(float(w @ years[idx]))
    order = np.argsort(years)
    years[order[49]] = years[order[50]] = years[order[48]]  # three paths tied at ranks 49..51
    value, idx, w = exact_quantile(years, 0.025)
    a = np.zeros(2000)
    np.add.at(a, idx, w)  # both interpolated ranks spread over the three tied paths
    assert np.count_nonzero(a) == 3 and np.allclose(a[a != 0], 1.0 / 3.0)
    assert value == np.percentile(years, 2.5)


def test_kernel_weights_shape():
    first, w = kernel_weights(2000, 0.5)
    assert w.sum() == pytest.approx(1.0)
    u = (first + np.arange(len(w))) / 1999
    assert np.all(np.abs(u - 0.5) <= 0.04 + 1e-12)
    assert u @ w == pytest.approx(0.5, abs=1e-12)  # centred on q in the rank coordinate
    first, w = kernel_weights(2000, 0.025)
    assert first == 0 and w.sum() == pytest.approx(1.0)  # truncated by the lower end
    years = np.sort(np.random.default_rng(1).normal(size=2000))
    assert kernel_quantile(years, 0.5)[0] == pytest.approx(np.percentile(years, 50), abs=0.01)


def test_figures_are_exact(bank):
    years = bank.years(np.full(5, 0.2))[:, 0]
    fig = figures(years)
    assert (fig.bad, fig.typical, fig.good) == tuple(np.percentile(years, [2.5, 50, 97.5]))
    assert fig.es_25 == measures.es_25(years)
    assert fig.mean == pytest.approx(years.mean(), abs=1e-15)
    assert fig.utility("U1") == pytest.approx(0.6 * fig.bad + 0.3 * fig.typical + 0.1 * fig.good)


@pytest.mark.parametrize("mode", ["exact", "kernel"])
def test_evaluation_values(bank, mode):
    w = np.array([0.1, 0.3, 0.2, 0.25, 0.15])
    ev = Evaluator(bank, mode).evaluate(w)
    years = bank.years_and_vjp(w)[0]
    np.testing.assert_array_equal(ev.exact, np.percentile(years, [2.5, 50, 97.5]))
    for arm in ARMS:
        assert arm_value(ev.exact, arm) == pytest.approx(figures(years).utility(arm))
        a = ev.path_weights(arm)
        assert a @ years == pytest.approx(ev.value(arm), abs=1e-14)
        assert a.sum() == pytest.approx(sum(ARMS[arm]))


@pytest.mark.parametrize("mode", ["exact", "kernel"])
@pytest.mark.parametrize("arm", ["U1", "B"])
def test_gradient_matches_central_differences(bank, mode, arm):
    ev_ = Evaluator(bank, mode)
    rng = np.random.default_rng(5)
    w = 0.5 * np.full(5, 0.2) + 0.5 * rng.dirichlet(np.ones(5))
    base = ev_.evaluate(w)
    grad = base.gradient(arm)
    checked = 0
    for _ in range(40):
        d = rng.normal(size=5)
        d -= d.mean()
        d /= np.linalg.norm(d)
        h = 1e-6
        plus, minus = ev_.evaluate(w + h * d), ev_.evaluate(w - h * d)
        a = base.path_weights(arm)
        if not (
            np.array_equal(plus.path_weights(arm), a) and np.array_equal(minus.path_weights(arm), a)
        ):
            continue  # a rank crossing: the derivative does not exist there
        fd = (plus.value(arm) - minus.value(arm)) / (2 * h)
        assert grad @ d == pytest.approx(fd, rel=1e-4, abs=1e-8)
        checked += 1
    assert checked >= 5  # the kernel window's 160 paths cross ranks often at h = 1e-6


def test_fdcheck_passes_on_replay(bank):
    ctx = synthetic_context()
    result = fdcheck(bank, ctx, mixes=2, directions=10)
    assert result.passed and result.failed == 0
    assert result.checked + result.small + result.skipped == 2 * 3 * 2 * 10
    assert result.max_rel_error <= 1e-4
    assert math.isfinite(result.max_rel_error)
