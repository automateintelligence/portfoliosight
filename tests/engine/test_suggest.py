"""The suggested point: the knee of ENB gained against return given up, or the peak."""

from __future__ import annotations

import numpy as np
import pytest

from portfoliosight.engine import suggest
from portfoliosight.engine.suggest import balanced_level, suggested_level


def test_knee_is_the_level_farthest_above_the_chord():
    returns = np.array([0.10, 0.09, 0.08, 0.07, 0.06])
    enbs = np.array([2.0, 3.6, 4.4, 4.8, 5.0])  # quick gains first, little at the end
    g = (returns[0] - returns) / (returns[0] - returns[-1])
    e = (enbs - enbs[0]) / (enbs[-1] - enbs[0])
    assert np.allclose(e - g, [0.0, 0.2833333, 0.3, 0.1833333, 0.0])
    assert balanced_level(returns, enbs) == int(np.argmax(e - g)) == 2
    # the perpendicular distance to the chord from (0, 0) to (1, 1) is (e - g) / sqrt(2)
    distance = np.abs(e - g) / np.sqrt(2.0)
    assert int(np.argmax(distance)) == 2


def test_knee_is_unchanged_by_the_units_of_either_axis():
    rng = np.random.default_rng(4301)
    for _ in range(50):
        levels = int(rng.integers(3, 15))
        returns = np.sort(rng.uniform(0.01, 0.12, levels))[::-1]
        enbs = np.sort(rng.uniform(1.0, 20.0, levels))
        knee = balanced_level(returns, enbs)
        assert 0 <= knee <= levels - 1
        assert balanced_level(100.0 * returns + 3.0, 7.0 * enbs - 2.0) == knee
        g = (returns[0] - returns) / (returns[0] - returns[-1])
        e = (enbs - enbs[0]) / (enbs[-1] - enbs[0])
        assert (e - g)[knee] == (e - g).max() >= 0.0  # both ends are on the chord


def test_knee_uses_the_returns_the_mixes_really_earn():
    """Levels that hold the same mix are one point of the curve, wherever their floors were."""
    returns = np.array([0.10, 0.099, 0.099, 0.099, 0.06])
    enbs = np.array([2.0, 3.5, 3.5, 3.5, 4.0])
    assert balanced_level(returns, enbs) == 1  # the first of the repeated levels


def test_a_tie_goes_to_the_level_that_gives_up_less():
    returns = np.array([1.0, 0.75, 0.5, 0.25, 0.0])
    enbs = np.array([1.0, 5.0, 7.0, 8.0, 9.0])  # e - g = 0, 1/4, 1/4, 1/8, 0, exactly
    assert balanced_level(returns, enbs) == 1


def test_a_curve_below_the_chord_has_its_knee_at_the_frontier_mix():
    returns = np.array([0.10, 0.09, 0.08, 0.07])
    enbs = np.array([1.0, 1.2, 1.6, 4.0])  # slow gains first: never above the chord
    assert balanced_level(returns, enbs) == 0


def test_ladders_without_a_curve():
    flat = np.full(5, 3.0)
    falling = np.array([0.10, 0.09, 0.08, 0.07, 0.06])
    assert balanced_level(falling, flat) == 0  # collapsed: nothing gained
    assert balanced_level(np.full(5, 0.05), flat) == 0
    free = np.array([2.0, 3.0, 3.0, 3.0, 3.0])
    assert balanced_level(np.full(5, 0.05), free) == 4  # gained for no return at all: take it
    assert balanced_level(0.05 + np.array([0.0, 5e-9, 5e-9, 5e-9, 5e-9]), free) == 4
    assert balanced_level(falling, flat + np.array([0, 0, 0, 0, 5e-7])) == 0  # within tolerance
    for returns, enbs in (([0.1], [1.0]), ([0.1, 0.09], [1.0]), ([[0.1, 0.09]], [[1.0, 2.0]])):
        with pytest.raises(ValueError, match="one return and one ENB per level"):
            balanced_level(returns, enbs)


def test_default_point_selects_the_knee_or_the_peak():
    returns = np.array([0.10, 0.09, 0.08, 0.07, 0.06])
    enbs = np.array([2.0, 3.6, 4.4, 4.8, 5.0])
    assert suggest.DEFAULT_POINT == "balanced" and suggest.POINTS == ("balanced", "peak")
    assert suggested_level(returns, enbs) == balanced_level(returns, enbs) == 2
    assert suggested_level(returns, enbs, "balanced") == 2
    assert suggested_level(returns, enbs, "peak") == 4
    flat = np.full(5, 3.0)
    assert suggested_level(returns, flat, "peak") == 0  # nothing to walk to
    assert suggested_level(np.full(5, 0.05), np.array([2.0, 3, 3, 3, 3]), "peak") == 4
    with pytest.raises(ValueError, match="unknown point 'knee'"):
        suggested_level(returns, enbs, "knee")
