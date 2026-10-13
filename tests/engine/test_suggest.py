"""The suggested point: a one-standard-error walk down the column (spec 4.8)."""

from __future__ import annotations

import numpy as np
import pytest

from portfoliosight.engine.stats import ew_weights
from portfoliosight.engine.suggest import standard_error, suggested_floor


def _se(d, omega=None) -> float:
    d = np.asarray(d, float)
    if omega is None:
        sd, t_eff = d.std(ddof=1), float(len(d))
    else:
        mean = omega @ d
        sd = float(np.sqrt(omega @ (d - mean) ** 2 / (1 - (omega**2).sum())))
        t_eff = 1.0 / (omega**2).sum()
    return float(np.sqrt(252.0) * sd / np.sqrt(t_eff / 252.0))


def _column():
    rng = np.random.default_rng(3901)
    r = rng.normal(0.0, 1.0, (600, 4)) * np.array([0.004, 0.008, 0.012, 0.02])
    w_front = np.array([0.7, 0.3, 0.0, 0.0])
    cands = [
        np.array([0.6, 0.3, 0.1, 0.0]),
        np.array([0.5, 0.3, 0.1, 0.1]),
        np.array([0.3, 0.2, 0.1, 0.4]),
    ]
    diffs = np.array([w_front - c for c in cands])
    ses = np.array([_se(r @ d) for d in diffs])
    return r, w_front, cands, diffs, ses


def _mu_for(diffs, give_ups):
    """Expected returns under which candidate k gives up exactly give_ups[k]."""
    return np.linalg.lstsq(np.atleast_2d(diffs), np.atleast_1d(give_ups), rcond=None)[0]


def test_standard_error_is_the_annualized_paired_deviation_over_years():
    rng = np.random.default_rng(3902)
    d = rng.normal(0.0001, 0.004, 900)
    assert abs(standard_error(d) - np.sqrt(252.0) * d.std(ddof=1) / np.sqrt(900 / 252.0)) <= 1e-15
    assert standard_error(d) == _se(d)
    omega = ew_weights(900)
    assert standard_error(d, omega) == _se(d, omega)
    assert abs(standard_error(d, np.full(900, 1 / 900)) - standard_error(d)) <= 1e-15
    assert abs(standard_error(d, omega) - standard_error(d)) > 1e-6
    assert standard_error(np.zeros(50)) == 0.0


def test_walk_stops_at_the_first_failure_even_if_a_lower_candidate_would_pass():
    r, w_front, cands, diffs, ses = _column()
    y_front, floors = 0.09, [0.08, 0.07, 0.06]
    mu_s = _mu_for(diffs, ses * np.array([0.5, 1.5, 0.5]))
    give_up = diffs @ mu_s
    assert give_up[0] <= ses[0] and give_up[1] > ses[1] and give_up[2] <= ses[2]
    assert suggested_floor(w_front, y_front, cands, floors, mu_s, r) == floors[0]
    assert suggested_floor(w_front, y_front, cands, floors, _mu_for(diffs, ses * 0.5), r) == 0.06
    last_fails = _mu_for(diffs, ses * np.array([0.5, 0.5, 1.5]))
    assert suggested_floor(w_front, y_front, cands, floors, last_fails, r) == floors[1]
    first_fails = _mu_for(diffs, ses * np.array([1.5, 0.5, 0.5]))
    assert suggested_floor(w_front, y_front, cands, floors, first_fails, r) == y_front


def test_collapsed_ladder_and_identical_candidate():
    r, w_front, cands, _, _ = _column()
    mu_s = np.array([0.03, 0.05, 0.07, 0.09])
    assert suggested_floor(w_front, 0.09, [], [], mu_s, r) == 0.09
    # a candidate equal to the frontier mix gives up nothing against no noise: it passes
    assert suggested_floor(w_front, 0.09, [w_front.copy()], [0.09], mu_s, r) == 0.09
    assert suggested_floor(w_front, 0.09, [w_front.copy()], [0.085], mu_s, r) == 0.085
    with pytest.raises(ValueError, match="one floor per candidate"):
        suggested_floor(w_front, 0.09, cands, [0.08], mu_s, r)


def test_threshold_is_exactly_one_standard_error():
    r, w_front, cands, diffs, ses = _column()
    for scale, expected in ((0.98, 0.08), (1.0 - 1e-9, 0.08), (1.02, 0.09)):
        mu_s = _mu_for(diffs[:1], ses[:1] * scale)
        assert suggested_floor(w_front, 0.09, cands[:1], [0.08], mu_s, r) == expected
    # more history shrinks the noise: the same give-up stops being "within noise"
    mu_s = _mu_for(diffs[:1], ses[:1] * 0.8)
    assert suggested_floor(w_front, 0.09, cands[:1], [0.08], mu_s, r) == 0.08
    long = np.vstack([r, r, r])
    assert _se(long @ diffs[0]) < 0.8 * ses[0]
    assert suggested_floor(w_front, 0.09, cands[:1], [0.08], mu_s, long) == 0.09


def test_ew_window_uses_t_eff_and_the_weighted_deviation():
    rng = np.random.default_rng(3903)
    rows = 1260
    vol = np.linspace(0.002, 0.02, rows)[:, None]  # recent rows are much noisier
    r = rng.normal(0.0, 1.0, (rows, 3)) * vol
    omega = ew_weights(rows)
    w_front, cand, y_front, floor = np.array([0.8, 0.2, 0.0]), np.array([0.4, 0.3, 0.3]), 0.08, 0.05
    diff = w_front - cand
    d = r @ diff
    se_ew = _se(d, omega)
    mean = omega @ d
    sd_w = np.sqrt(omega @ (d - mean) ** 2 / (1 - (omega**2).sum()))
    se_with_t = np.sqrt(252.0) * sd_w / np.sqrt(rows / 252.0)  # wrong: T instead of T_eff
    se_plain = _se(d)  # wrong: ignores omega
    assert se_with_t < 0.9 * se_ew and abs(se_plain - se_ew) > 0.05 * se_ew

    def mu_for(give_up):
        return diff * give_up / (diff @ diff)

    def walk(give_up, weights=None):
        return suggested_floor(w_front, y_front, [cand], [floor], mu_for(give_up), r, omega=weights)

    assert walk(float(np.sqrt(se_with_t * se_ew)), omega) == floor  # passes only with T_eff
    assert walk(0.98 * se_ew, omega) == floor and walk(1.02 * se_ew, omega) == y_front
    uniform = np.full(rows, 1.0 / rows)
    between = 0.5 * (_se(d, uniform) + se_ew)
    assert walk(between, omega) != walk(between, uniform)
    assert walk(between, uniform) == walk(between)
