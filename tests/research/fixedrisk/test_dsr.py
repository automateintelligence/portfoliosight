import math
from statistics import NormalDist

import numpy as np
import pytest

from portfoliosight.research.fixedrisk import dsr

GAMMA = 0.5772156649015329
INV = NormalDist().inv_cdf
CDF = NormalDist().cdf


def test_hand_computation_two_orthogonal_trials():
    x = np.array([1.0, 2.0, 3.0, 4.0]) * 0.01
    y = np.array([2.0, 1.0, 1.0, 2.0]) * 0.01  # exactly uncorrelated with x
    out = dsr.deflated_sharpe(np.column_stack([x, y]))
    sr_x = 0.025 / (0.01 * math.sqrt(5 / 3))
    sr_y = 0.015 / (0.01 * math.sqrt(1 / 3))
    var = (sr_x - sr_y) ** 2 / 2
    assert out.n_eff == pytest.approx(2.0)
    sr0 = math.sqrt(var) * ((1 - GAMMA) * INV(0.5) + GAMMA * INV(1 - 1 / (2 * math.e)))
    assert out.sr == pytest.approx(sr_x) and out.trial_variance == pytest.approx(var)
    assert out.sr0 == pytest.approx(sr0)
    skew, kurt = 0.0, 1.64
    stat = (sr_x - sr0) * math.sqrt(3) / math.sqrt(1 - skew * sr_x + (kurt - 1) / 4 * sr_x**2)
    assert out.skew == pytest.approx(0.0, abs=1e-12) and out.kurtosis == pytest.approx(kurt)
    assert out.dsr == pytest.approx(CDF(stat))


def test_n_eff_below_two_gives_zero_benchmark():
    x = np.array([1.0, 2.0, 3.0, 5.0]) * 0.01
    out = dsr.deflated_sharpe(np.column_stack([x, 2 * x]))  # perfectly correlated
    assert out.n_eff == pytest.approx(1.0) and out.sr0 == 0.0


def test_participation_ratio_clipped():
    rng = np.random.default_rng(0)
    base = rng.normal(size=(30, 1))
    assert dsr.participation_ratio(
        np.repeat(base, 5, axis=1) + 1e-9 * rng.normal(size=(30, 5))
    ) == pytest.approx(1.0, abs=1e-3)
    assert dsr.participation_ratio(rng.normal(size=(5000, 25))) == pytest.approx(20.0, abs=0.0)


def test_zero_sd_trials_dropped_and_counted():
    x = np.array([1.0, 2.0, 3.0, 4.0]) * 0.01
    y = np.array([2.0, 1.0, 1.0, 2.0]) * 0.01
    z = np.full(4, 0.01)
    out = dsr.deflated_sharpe(np.column_stack([x, y, z]))
    assert out.trials_dropped == 1 and out.trials_used == 2
    assert out.n_eff == pytest.approx(2.0)
    flat = dsr.deflated_sharpe(np.column_stack([z, x]), primary=0)
    assert flat.dsr is None and "zero standard deviation" in flat.reason


def test_too_few_observations_and_nonfinite():
    assert dsr.deflated_sharpe(np.ones((2, 3))).dsr is None
    with pytest.raises(ValueError):
        dsr.deflated_sharpe(np.array([[1.0, np.nan], [1, 2], [3, 4]]))
