"""One-year ranges: the stationary block bootstrap and the normal range beside it."""

from __future__ import annotations

import numpy as np
import pytest

from portfoliosight.engine import ranges
from portfoliosight.engine.ranges import (
    HORIZON_DAYS,
    MEAN_BLOCK_DAYS,
    PATHS,
    bootstrap_index,
    one_year_ranges,
    path_counts,
    range_model,
)

ROWS = 1260


def _normal_sample(rows: int, sigma: np.ndarray, seed: int) -> np.ndarray:
    """Independent normal daily returns with annual volatilities `sigma`."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.0003, sigma / np.sqrt(252.0), size=(rows, len(sigma)))


@pytest.fixture(scope="module")
def model():
    sigma = np.array([0.02, 0.08, 0.16, 0.22])
    sample = _normal_sample(ROWS, sigma, 4401)
    cov = np.cov(sample, rowvar=False) * 252.0
    return range_model(sample, np.array([0.03, 0.05, 0.08, 0.09]), cov)


def test_index_is_a_stationary_bootstrap_with_runs_of_twenty_one_days():
    index = bootstrap_index(ROWS)
    assert index.shape == (PATHS, HORIZON_DAYS) == (2000, 252) and index.dtype == np.int32
    assert index.min() >= 0 and index.max() <= ROWS - 1
    step = np.diff(index.astype(int), axis=1)
    follows = (step == 1) | (step == 1 - ROWS)  # the next day, or the first after the last
    assert abs(follows.mean() - (1.0 - 1.0 / MEAN_BLOCK_DAYS)) <= 0.002
    # memoryless: a run that has already lasted 30 days ends at the same rate as any other
    lasted = np.lib.stride_tricks.sliding_window_view(follows, 30, axis=1).all(axis=2)[:, :-1]
    ends_after = ~follows[:, 30:]
    assert abs(ends_after[lasted].mean() - 1.0 / MEAN_BLOCK_DAYS) <= 0.004
    lengths = []  # completed runs of the first paths: about 21 days, less what a year cuts off
    for row in follows[:300]:
        breaks = np.flatnonzero(~row)
        lengths.extend(np.diff(breaks).tolist())
    assert 17.0 <= np.mean(lengths) <= 21.0 and max(lengths) > 60
    assert np.any(step == 1 - ROWS)  # some run wrapped around the end of the sample
    first = np.bincount(index[:, 0], minlength=ROWS)  # a path starts anywhere
    assert first.max() <= 12 and (first > 0).mean() > 0.7
    days = np.bincount(index.ravel(), minlength=ROWS)  # and every day is used about equally
    assert abs(days.mean() - PATHS * HORIZON_DAYS / ROWS) <= 1e-9 and days.min() > 250


def test_index_is_fixed_by_its_seed_and_cannot_be_written_to():
    index = bootstrap_index(ROWS)
    assert bootstrap_index(ROWS) is index  # one matrix per sample length, shared by every mix
    fresh = bootstrap_index.__wrapped__(ROWS)
    assert np.array_equal(fresh, index)
    assert not np.array_equal(bootstrap_index.__wrapped__(ROWS, seed=1), index)
    assert not np.array_equal(bootstrap_index(ROWS - 1)[:, :50], index[:, :50])
    with pytest.raises(ValueError, match="read-only"):
        index[0, 0] = 1
    small = bootstrap_index.__wrapped__(5, paths=3, horizon=40, mean_block=4, seed=3)
    assert small.shape == (3, 40) and small.max() <= 4  # shorter than a path: it wraps
    for bad in ({"rows": 0}, {"rows": 5, "paths": 0}, {"rows": 5, "horizon": 0}):
        with pytest.raises(ValueError, match="at least 1"):
            bootstrap_index.__wrapped__(**{"rows": 5, **bad})
    with pytest.raises(ValueError, match="at least 1"):
        bootstrap_index.__wrapped__(5, mean_block=0)


def test_counts_are_the_multiplicities_of_the_index():
    counts, index = path_counts(ROWS), bootstrap_index(ROWS)
    assert counts.shape == (PATHS, ROWS) and (counts.sum(axis=1) == HORIZON_DAYS).all()
    for path in (0, 7, 1999):
        assert np.array_equal(counts[path], np.bincount(index[path], minlength=ROWS))
    assert path_counts(ROWS) is counts
    with pytest.raises(ValueError, match="read-only"):
        counts[0, 0] = 1.0


def test_ranges_compound_every_path_of_the_recentred_history(model):
    """The matrix product equals compounding each path day by day."""
    w = np.array([0.4, 0.3, 0.2, 0.1])
    out = one_year_ranges(model, w)
    daily = model.sample @ w
    daily = daily - daily.mean() + (model.mu_s @ w) / 252.0
    assert abs(daily.mean() * 252.0 - model.mu_s @ w) <= 1e-15  # the centre is the chart's
    year = np.prod(1.0 + daily[bootstrap_index(ROWS)], axis=1) - 1.0
    bad, typical, good = np.percentile(year, [2.5, 50.0, 97.5])
    assert abs(out["bad"][0] - bad) <= 1e-12 and abs(out["typical"][0] - typical) <= 1e-12
    assert abs(out["good"][0] - good) <= 1e-12
    sigma = float(np.sqrt(w @ model.cov @ w))
    normal = out["normal"]
    assert normal["mid"][0] == pytest.approx(model.mu_s @ w, abs=1e-15)
    assert normal["low"][0] == pytest.approx(model.mu_s @ w - 1.96 * sigma, abs=1e-15)
    assert normal["high"][0] == pytest.approx(model.mu_s @ w + 1.96 * sigma, abs=1e-15)


def test_ranges_are_ordered_centred_and_repeat_exactly(model):
    rng = np.random.default_rng(4402)
    mixes = rng.dirichlet(np.ones(4), size=25)
    out = one_year_ranges(model, mixes)
    for name in ("bad", "typical", "good"):
        assert out[name].shape == (25,)
    assert (out["bad"] < out["typical"]).all() and (out["typical"] < out["good"]).all()
    mu = mixes @ model.mu_s
    sigma = np.sqrt(np.einsum("ij,jk,ik->i", mixes, model.cov, mixes))
    # the typical year is the expected return less about half the variance, within sampling error
    centre = np.expm1(mu - sigma**2 / 2.0)
    assert np.abs(out["typical"] - centre).max() <= 0.15 * sigma.max()
    assert (np.abs(out["typical"] - centre) <= 0.15 * sigma + 1e-4).all()
    again = one_year_ranges(model, mixes)
    for name in ("bad", "typical", "good"):
        assert np.array_equal(again[name], out[name])
    # one mix at a time gives what it gives in a batch: mixes do not disturb each other
    for i in (0, 11, 24):
        alone = one_year_ranges(model, mixes[i])
        assert alone["bad"].shape == (1,)
        for name in ("bad", "typical", "good"):
            assert abs(alone[name][0] - out[name][i]) <= 1e-12
    # a riskier mix has a worse bad year and a better good one
    calm, wild = one_year_ranges(model, np.eye(4)[0]), one_year_ranges(model, np.eye(4)[3])
    assert wild["bad"][0] < calm["bad"][0] and wild["good"][0] > calm["good"][0]


def test_on_normal_history_the_bootstrap_agrees_with_the_normal_range():
    """Independent normal days: bad and good years within a few points of `mu -+ 1.96 sigma`.

    Two things keep them from sitting on it. Compounding skews a year, lifting the good one.
    And runs resampled from a finite history carry its accidental streaks, so the spread of a
    year is itself an estimate from a handful of years; the tolerances here are that noise.
    """
    sigma = np.array([0.04, 0.08])
    mu = np.array([0.03, 0.05])
    for seed in (4403, 4404, 4405, 4406):
        sample = _normal_sample(2520, sigma, seed)
        model = range_model(sample, mu, np.cov(sample, rowvar=False) * 252.0)
        out = one_year_ranges(model, np.eye(2))
        normal = out["normal"]
        assert (np.abs(out["bad"] - normal["low"]) <= 0.03).all()
        assert (np.abs(out["good"] - normal["high"]) <= 0.06).all()
        assert (np.abs(out["typical"] - normal["mid"]) <= 0.01).all()
        risk = np.sqrt(np.diag(model.cov))
        assert (np.abs(out["bad"] - normal["low"]) <= 0.4 * risk).all()
        assert (out["good"] - out["bad"] >= 3.0 * risk).all()  # about 3.92 sigma wide
        assert (out["good"] - out["bad"] <= 5.2 * risk).all()


def test_history_supplies_the_shape():
    """Days that come in streaks make a worse bad year than the same days shuffled would."""
    rng = np.random.default_rng(4406)
    out = {}
    for name, carry in (("independent", 0.0), ("streaky", 0.3)):
        shocks = rng.normal(0.0, 0.006, size=2520)
        series = np.zeros(2520)
        for day in range(1, 2520):
            series[day] = carry * series[day - 1] + shocks[day]
        series *= 0.006 / series.std()  # the same daily volatility either way
        sample = np.column_stack([series, 0.5 * series])
        model = range_model(sample, np.array([0.06, 0.03]), np.cov(sample, rowvar=False) * 252.0)
        out[name] = one_year_ranges(model, np.array([1.0, 0.0]))
    normal_low = out["independent"]["normal"]["low"][0]
    assert out["streaky"]["normal"]["low"][0] == pytest.approx(normal_low, abs=1e-12)
    assert abs(out["independent"]["bad"][0] - normal_low) <= 0.03
    assert out["streaky"]["bad"][0] < normal_low - 0.04  # the normal range cannot see streaks
    assert out["streaky"]["good"][0] > out["independent"]["good"][0] + 0.04


def test_model_and_mix_are_checked(model):
    sample = model.sample
    with pytest.raises(ValueError, match="T x N array"):
        range_model(sample[:1], model.mu_s, model.cov)
    with pytest.raises(ValueError, match="T x N array"):
        range_model(sample[:, 0], model.mu_s[:1], model.cov[:1, :1])
    with pytest.raises(ValueError, match="same funds"):
        range_model(sample, model.mu_s[:3], model.cov)
    with pytest.raises(ValueError, match="same funds"):
        range_model(sample, model.mu_s, model.cov[:3, :3])
    holed = sample.copy()
    holed[5, 1] = np.nan
    with pytest.raises(ValueError, match="missing or non-finite"):
        range_model(holed, model.mu_s, model.cov)
    with pytest.raises(ValueError, match="has 4 weights"):
        one_year_ranges(model, np.array([0.5, 0.5]))
    with pytest.raises(ValueError, match="has 4 weights"):
        one_year_ranges(model, np.zeros((2, 2, 4)))
    ruined = sample.copy()
    ruined[10, 3] = -1.5  # a day that loses more than everything
    broken = range_model(ruined, model.mu_s, model.cov)
    with pytest.raises(ValueError, match="cannot be compounded"):
        one_year_ranges(broken, np.eye(4)[3])
    assert np.isfinite(one_year_ranges(broken, np.eye(4)[0])["bad"]).all()  # another mix is fine


def test_method_is_declared():
    assert ranges.METHOD == {
        "name": "stationary block bootstrap",
        "horizon_days": 252,
        "paths": 2000,
        "mean_block_days": 21,
        "percentiles": [2.5, 50.0, 97.5],
        "percentile_method": "linear",
        "seed": ranges.SEED,
    }
