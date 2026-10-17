"""One-year ranges: the stationary block bootstrap, the volatility model and the normal range."""

from __future__ import annotations

import numpy as np
import pytest

from portfoliosight.engine import ranges
from portfoliosight.engine.ranges import (
    DEFAULT_ENGINE,
    ENGINES,
    HORIZON_DAYS,
    MEAN_BLOCK_DAYS,
    PATHS,
    SEED,
    GarchRangeModel,
    RangeModel,
    bootstrap_index,
    garch_range_model,
    one_year_ranges,
    path_counts,
    range_model,
    simulated_years,
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


def test_sample_digest_names_the_exact_sample():
    funds, days = ["AAA", "BBB"], ["2026-01-02", "2026-01-05", "2026-01-06"]
    sample = np.array([[0.01, -0.02], [0.0, 0.003], [0.004, 0.001]])
    digest = ranges.sample_digest(funds, days, sample)
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert ranges.sample_digest(funds, days, sample.copy()) == digest
    nudged = sample.copy()
    nudged[1, 1] = np.nextafter(nudged[1, 1], 1.0)  # one bit of one return
    assert ranges.sample_digest(funds, days, nudged) != digest
    assert ranges.sample_digest(funds, days, sample[::-1]) != digest  # the order of the days
    assert ranges.sample_digest(["BBB", "AAA"], days, sample[:, ::-1]) != digest  # of the funds
    assert ranges.sample_digest(funds, ["2026-01-02", "2026-01-05", "2026-01-07"], sample) != digest
    with pytest.raises(ValueError, match="one row per day"):
        ranges.sample_digest(funds, days[:2], sample)


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


# ---- the volatility model's level and shape (simulation engines spec 4.5) -------------------

CHART_MU = np.array([0.03, 0.06, 0.09, 0.02])
CHART_SIGMA = np.array([0.05, 0.12, 0.22, 1e-4])  # the last fund is cash: sigma at the floor
CHART_CORR = np.array(
    [[1.0, 0.3, 0.2, 0.0], [0.3, 1.0, 0.7, 0.0], [0.2, 0.7, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
)
CHART_COV = np.outer(CHART_SIGMA, CHART_SIGMA) * CHART_CORR
SHAPE = (60, 25, 4)  # paths x days x funds: small enough to materialise every step


def _simulated(shape=SHAPE, seed: int = 4410) -> np.ndarray:
    """A small simulated panel of daily log returns: fat-tailed, correlated, the last constant."""
    rng = np.random.default_rng(seed)
    paths, days, funds = shape
    common = rng.standard_t(5, (paths, days, 1))
    own = rng.standard_t(5, (paths, days, funds))
    scale = np.array([0.004, 0.009, 0.015, 0.0])
    panel = 0.0004 + (0.6 * common + 0.8 * own) * scale
    panel[..., 3] = 1e-4
    return panel


@pytest.fixture(scope="module")
def garch_model() -> GarchRangeModel:
    return garch_range_model(_simulated(), CHART_MU, CHART_COV)


def _mixes() -> np.ndarray:
    rng = np.random.default_rng(4411)
    return np.vstack([rng.dirichlet(np.ones(4), size=6), np.eye(4)])  # the last row: cash alone


def _targets(model: GarchRangeModel) -> tuple[np.ndarray, ...]:
    """The chart's daily simple targets `m`, `s` and their lognormal equivalents in log space."""
    m, s = model.mu_s / 252.0, np.sqrt(np.diag(model.cov) / 252.0)
    log_var = np.log1p(s**2 / (1.0 + m) ** 2)
    return m, s, np.log1p(m) - log_var / 2.0, np.sqrt(log_var)


def _levelled(model: GarchRangeModel) -> np.ndarray:
    """Step 1, materialised: `R' = expm1(l')`, each fund at the chart's level in log space."""
    m, _, log_mean, log_sd = _targets(model)
    still = model.sd == 0
    scale = np.divide(log_sd, model.sd, out=np.zeros_like(log_sd), where=~still)
    levelled = np.expm1(log_mean + (model.panel - model.mean) * scale)
    levelled[..., still] = m[still]
    return levelled


def _mix_days(model: GarchRangeModel, w: np.ndarray) -> np.ndarray:
    """Step 2, materialised: the mix's simple days at the chart's mean and risk, P x H."""
    y = _levelled(model) @ w
    m_w, s_w = w @ model.mu_s / 252.0, np.sqrt(w @ model.cov @ w / 252.0)
    spread = 0.0 if np.ptp(y) == 0 else y.std()
    return np.full_like(y, m_w) if spread == 0 else m_w + (y - y.mean()) * (s_w / spread)


def test_engines_are_named_and_the_model_knows_its_own(garch_model):
    assert ENGINES == ("replay", "garch") and DEFAULT_ENGINE == "replay"
    assert ranges.SCALE == "sd" and ranges.RUIN == "absorb"
    assert RangeModel.engine == "replay" and GarchRangeModel.engine == "garch"
    assert garch_model.engine == "garch" and garch_model.seed == SEED
    sample = _normal_sample(300, np.array([0.1, 0.2]), 4412)
    replay = range_model(sample, np.array([0.05, 0.07]), np.cov(sample, rowvar=False) * 252)
    assert replay.engine == "replay" and replay.seed == SEED
    other = range_model(sample, replay.mu_s, replay.cov, seed=SEED + 4)
    assert other.seed == SEED + 4 and np.array_equal(
        other.counts[0], np.bincount(bootstrap_index(300, seed=SEED + 4)[0], minlength=300)
    )
    assert not np.array_equal(other.counts, replay.counts)
    assert path_counts(300, seed=SEED + 4) is path_counts(300, seed=SEED + 4)
    assert garch_range_model(_simulated(), CHART_MU, CHART_COV, seed=7).seed == 7


def test_pooled_statistics_are_those_of_every_path_and_day(garch_model, monkeypatch):
    flat = _simulated().reshape(-1, 4)
    assert np.abs(garch_model.mean - flat.mean(axis=0)).max() <= 1e-17
    live = flat[:, :3].std(axis=0)
    assert np.abs(garch_model.sd[:3] - live).max() <= 1e-12 * live.min()
    assert garch_model.sd[3] == 0.0  # cash: its simulated returns never vary
    levelled = _levelled(garch_model).reshape(-1, 4)
    assert np.abs(garch_model.level_mean - levelled.mean(axis=0)).max() <= 1e-15
    assert garch_model.level_mean[3] == CHART_MU[3] / 252.0  # cash: its daily target, exactly
    scale = np.abs(garch_model.level_cov).max()
    expected = np.cov(levelled, rowvar=False, ddof=0)
    assert np.abs(garch_model.level_cov - expected).max() <= 1e-12 * scale
    assert np.array_equal(garch_model.level_cov, garch_model.level_cov.T)
    assert not garch_model.level_cov[3].any()  # cash adds nothing to any mix's spread
    assert np.array_equal(garch_model.panel, _simulated()) and not garch_model.panel.flags.writeable
    monkeypatch.setattr(ranges, "WORK_BYTES", 2 * SHAPE[1] * SHAPE[2] * 8)  # two paths a chunk
    chunked = garch_range_model(_simulated(), CHART_MU, CHART_COV)
    assert np.abs(chunked.mean - garch_model.mean).max() <= 1e-17
    assert np.abs(chunked.sd - garch_model.sd).max() <= 1e-12 * live.min()
    assert np.abs(chunked.level_mean - garch_model.level_mean).max() <= 1e-17
    assert np.abs(chunked.level_cov - garch_model.level_cov).max() <= 1e-12 * scale


def test_a_fund_that_never_varies_is_constant_whatever_its_pooled_mean():
    """A full-size panel: the mean of 504,000 equal numbers is not exactly that number, so the
    deviation computed from it is rounding, never a volatility to scale up."""
    panel = np.empty((PATHS, HORIZON_DAYS, 2))
    panel[..., 0] = np.random.default_rng(4414).normal(4e-4, 0.01, (PATHS, HORIZON_DAYS))
    panel[..., 1] = 0.00015
    mu_s, sigma = np.array([0.10, 0.0389]), np.array([0.16, 1e-4])
    model = garch_range_model(panel, mu_s, np.diag(sigma**2))
    assert model.sd[1] == 0.0 and model.sd[0] > 0.009
    assert model.level_mean[1] == mu_s[1] / 252.0 and model.level_cov[1, 1] == 0.0
    cash = one_year_ranges(model, np.array([0.0, 1.0]))
    expected = np.expm1(HORIZON_DAYS * np.log1p(mu_s[1] / 252.0))
    for name in ("bad", "typical", "good"):
        assert abs(cash[name][0] - expected) <= 1e-12  # its expected return, every day


def test_step_one_gives_every_fund_the_chart_s_level_in_log_space(garch_model):
    """`l' = m~ + (l - mean) s~ / sd` with `(m~, s~)` the lognormal equivalents of the chart's
    daily `(m, s)`: a lognormal day `exp(l') - 1` has exactly the chart's mean and volatility."""
    m, s, log_mean, log_sd = _targets(garch_model)
    assert np.abs(np.expm1(log_mean + log_sd**2 / 2.0) - m).max() <= 1e-17
    lognormal_sd = np.sqrt(np.expm1(log_sd**2)) * np.exp(log_mean + log_sd**2 / 2.0)
    assert np.abs(lognormal_sd - s).max() <= 1e-15
    levelled = _levelled(garch_model).reshape(-1, 4)
    logs = np.log1p(levelled[:, :3])
    assert np.abs(logs.mean(axis=0) - log_mean[:3]).max() <= 1e-12
    assert np.abs(logs.std(axis=0) - log_sd[:3]).max() <= 1e-12
    assert (levelled > -1.0).all()  # a day in log space never loses everything
    assert (levelled[:, 3] == m[3]).all()  # a constant fund is its daily expected return


def test_step_two_pins_every_mix_to_the_chart_s_return_and_risk_in_simple_space():
    """One-day paths: a mix's year is its day, so the pooled mean and deviation of the years are
    those of its days, `m_w` and `s_w`, to rounding."""
    model = garch_range_model(_simulated((1500, 1, 4), seed=4415), CHART_MU, CHART_COV)
    mixes = _mixes()
    days = simulated_years(model, mixes)
    assert days.shape == (1500, len(mixes))
    for i, w in enumerate(mixes):
        m_w, s_w = w @ CHART_MU / 252.0, np.sqrt(w @ CHART_COV @ w / 252.0)
        assert abs(days[:, i].mean() - m_w) <= 1e-12
        if i < len(mixes) - 1:
            assert abs(days[:, i].std() - s_w) <= 1e-12
            direct = (_levelled(model) @ w).std()  # sd(y) without a pass: w' Sigma_R' w
            assert abs(np.sqrt(w @ model.level_cov @ w) - direct) <= 1e-12 * direct
        else:  # cash alone has no simulated spread: every day is its expected return
            assert np.ptp(days[:, i]) <= 1e-18


def test_step_two_decomposes_exactly_by_fund():
    """`y' = sum_n w_n [m_n + k_w (R'_n - mean R'_n)]`: each fund's own part of every simulated
    day (spec 5.3 needs it), with `k_w = s_w / sd(y)`."""
    model = garch_range_model(_simulated((1500, 1, 4), seed=4416), CHART_MU, CHART_COV)
    levelled = _levelled(model)[:, 0, :]
    m = CHART_MU / 252.0
    for w in _mixes()[:6]:
        k = np.sqrt(w @ CHART_COV @ w / 252.0) / np.sqrt(w @ model.level_cov @ w)
        parts = w * (m + k * (levelled - model.level_mean))  # P x N
        assert np.abs(simulated_years(model, w)[:, 0] - parts.sum(axis=1)).max() <= 1e-15


def test_years_compound_the_levelled_days(garch_model):
    mixes = _mixes()
    years = simulated_years(garch_model, mixes)
    assert years.shape == (SHAPE[0], len(mixes))
    for i, w in enumerate(mixes):
        days = _mix_days(garch_model, w)
        assert np.abs(years[:, i] - (np.prod(1.0 + days, axis=1) - 1.0)).max() <= 1e-12
        assert np.abs(years[:, i] - np.expm1(np.log1p(days).sum(axis=1))).max() <= 1e-12
    assert np.ptp(years[:, -1]) <= 1e-15  # cash alone: one year on every path


def test_chunked_compounding_equals_compounding_at_once(garch_model, monkeypatch):
    mixes = _mixes()
    at_once = simulated_years(garch_model, mixes)
    monkeypatch.setattr(ranges, "MIX_BLOCK", 3)
    # two paths a chunk: their levelled days (four funds) and their gross days (three mixes)
    monkeypatch.setattr(ranges, "WORK_BYTES", 2 * SHAPE[1] * (SHAPE[2] + 3) * 8)
    chunked = simulated_years(garch_model, mixes)
    assert np.abs(chunked - at_once).max() <= 1e-12
    for i, w in enumerate(mixes):
        one_shot = np.expm1(np.log1p(_mix_days(garch_model, w)).sum(axis=1))
        assert np.abs(chunked[:, i] - one_shot).max() <= 1e-12


def test_garch_ranges_are_the_percentiles_of_the_simulated_years(garch_model):
    mixes = _mixes()[:6]
    out = one_year_ranges(garch_model, mixes)
    bad, typical, good = np.percentile(
        simulated_years(garch_model, mixes), [2.5, 50.0, 97.5], axis=0
    )
    assert np.array_equal(out["bad"], bad) and np.array_equal(out["good"], good)
    assert np.array_equal(out["typical"], typical)
    assert (out["bad"] < out["typical"]).all() and (out["typical"] < out["good"]).all()
    assert out["ruined"].tolist() == [0] * 6  # no path lost everything
    mu, sigma = mixes @ CHART_MU, np.sqrt(np.einsum("ij,jk,ik->i", mixes, CHART_COV, mixes))
    assert np.abs(out["normal"]["mid"] - mu).max() <= 1e-15
    assert np.abs(out["normal"]["low"] - (mu - 1.96 * sigma)).max() <= 1e-15
    for i in (0, 5):  # one mix alone gives what it gives among others
        alone = one_year_ranges(garch_model, mixes[i])
        for name in ("bad", "typical", "good"):
            assert alone[name].shape == (1,) and abs(alone[name][0] - out[name][i]) <= 1e-12


def test_replay_years_are_the_bootstrap_s_compounded_paths(model):
    mixes = np.random.default_rng(4413).dirichlet(np.ones(4), size=5)
    years = simulated_years(model, mixes)
    assert years.shape == (PATHS, 5)
    out = one_year_ranges(model, mixes)
    assert np.array_equal(out["bad"], np.percentile(years, 2.5, axis=0))
    assert out["ruined"].tolist() == [0] * 5  # History replay raises instead of absorbing
    daily = model.sample @ mixes[2]
    daily = daily - daily.mean() + (model.mu_s @ mixes[2]) / 252.0
    direct = np.prod(1.0 + daily[bootstrap_index(ROWS)], axis=1) - 1.0
    assert np.abs(years[:, 2] - direct).max() <= 1e-12


def test_a_simulated_day_that_loses_everything_is_absorbed_and_counted():
    """A path whose levelled day reaches `1 + y' <= 0` is a total loss from that day on: its year
    is exactly -100%, and it is counted. No other path or mix is touched."""
    panel = _simulated()
    panel[7, 3, 0] = -2.0  # one log return far below every other
    wild = CHART_SIGMA.copy()
    wild[0] = 5.0  # a fund so risky that the levelled day loses more than everything
    model = garch_range_model(panel, CHART_MU, np.outer(wild, wild) * CHART_CORR)
    mixes = np.eye(4)[:2]
    days = _mix_days(model, mixes[0])
    lost = (1.0 + days <= 0.0).any(axis=1)
    assert lost[7] and lost.sum() == 1
    years = simulated_years(model, mixes)
    assert years[7, 0] == -1.0 and np.isfinite(years).all()
    kept = np.prod(1.0 + days[~lost], axis=1) - 1.0
    assert np.abs(years[~lost, 0] - kept).max() <= 1e-12 * np.abs(kept).max()
    out = one_year_ranges(model, mixes)
    assert out["ruined"].dtype.kind == "i" and out["ruined"].tolist() == [1, 0]
    assert (out["bad"] < out["typical"]).all() and (out["typical"] < out["good"]).all()
    calm = one_year_ranges(model, mixes[1])  # the other fund alone never loses everything
    assert calm["ruined"].tolist() == [0] and np.isfinite(calm["bad"]).all()


def test_garch_model_and_mix_are_checked(garch_model):
    panel = _simulated()
    with pytest.raises(ValueError, match="P x H x N"):
        garch_range_model(panel[0], CHART_MU, CHART_COV)
    with pytest.raises(ValueError, match="P x H x N"):
        garch_range_model(panel[:1, :1], CHART_MU, CHART_COV)
    with pytest.raises(ValueError, match="same funds"):
        garch_range_model(panel, CHART_MU[:3], CHART_COV)
    with pytest.raises(ValueError, match="same funds"):
        garch_range_model(panel, CHART_MU, CHART_COV[:3, :3])
    with pytest.raises(ValueError, match="moments must be finite"):
        garch_range_model(panel, np.where(np.arange(4) == 1, np.nan, CHART_MU), CHART_COV)
    holed = panel.copy()
    holed[3, 4, 1] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        garch_range_model(holed, CHART_MU, CHART_COV)
    with pytest.raises(ValueError, match="has 4 weights"):
        simulated_years(garch_model, np.array([0.5, 0.5]))
    with pytest.raises(ValueError, match="has 4 weights"):
        one_year_ranges(garch_model, np.zeros((2, 2, 4)))
    with pytest.raises(ValueError, match="weights must be finite"):
        one_year_ranges(garch_model, np.array([np.nan, 0.5, 0.5, 0.0]))
    # a chart volatility no fund has, on a panel with one far day: the levelled day overflows
    lone = np.random.default_rng(4417).normal(0.0, 0.01, (2000, 50, 1))
    lone[3, 7, 0] = 30.0
    with pytest.raises(ValueError, match="levelled .* not finite"):
        garch_range_model(lone, np.array([0.05]), np.array([[252.0 * 400.0]]))
