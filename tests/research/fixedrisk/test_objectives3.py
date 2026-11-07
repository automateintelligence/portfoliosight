"""v3 objectives: path drawdowns, TDD, ENLC, the worst historical fall and the banks' path terms."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import objectives3 as O
from portfoliosight.research.fixedrisk.anchors import geometry
from portfoliosight.research.fixedrisk.banks import replay_bank

from .optimizer_data import synthetic_context, with_history


def _loop_drawdown(wealth_row: np.ndarray) -> float:
    """The definition, one day at a time: peak counted from the starting value 1."""
    peak, worst = 1.0, 0.0
    for value in wealth_row:
        peak = max(peak, value)
        worst = max(worst, 1.0 - value / peak)
    return worst


def test_path_drawdowns_match_an_explicit_daily_loop():
    rng = np.random.default_rng(3)
    wealth = np.cumprod(1.0 + rng.normal(0.0, 0.02, size=(50, 252)), axis=1)
    got = O.path_drawdowns(wealth)
    want = [_loop_drawdown(row) for row in wealth]
    np.testing.assert_allclose(got, want, rtol=0, atol=1e-15)


def test_path_drawdown_counts_the_peak_from_one():
    # falls straight away and never regains 1: the drawdown is from 1, not from the first day
    wealth = np.array([[0.9, 0.8, 0.85, 0.95]])
    assert O.path_drawdowns(wealth)[0] == pytest.approx(0.2)
    # rises first: the peak is the running maximum
    wealth = np.array([[1.2, 0.9, 1.0]])
    assert O.path_drawdowns(wealth)[0] == pytest.approx(0.25)


def test_tail_drawdown_is_the_mean_of_the_worst_hundred():
    d = np.arange(2000) / 2000.0
    rng = np.random.default_rng(0)
    shuffled = rng.permutation(d)
    assert O.tail_drawdown(shuffled) == pytest.approx(np.mean(d[-100:]), abs=1e-15)
    assert O.tail_drawdown(shuffled, tail=1) == pytest.approx(d[-1])


def _enlc_case(contrib_bad: np.ndarray, w: np.ndarray, paths: int = 300):
    """Years and fund sums whose worst 100 paths have mean contributions `contrib_bad`."""
    n = len(w)
    sums = np.zeros((paths, n))
    years = np.linspace(0.0, 1.0, paths)  # paths 0..99 are the bad years
    sums[:100] = contrib_bad / w
    sums[100:] = 1.0  # good years: every fund gains
    return years, sums


def test_enlc_single_loser_is_one():
    w = np.array([0.5, 0.3, 0.2])
    years, sums = _enlc_case(np.array([-0.1, 0.0, 0.0]), w)
    assert O.enlc(years, sums, w) == pytest.approx(1.0)


def test_enlc_equal_losers_counts_them():
    w = np.array([0.25, 0.25, 0.25, 0.25])
    years, sums = _enlc_case(np.array([-0.05, -0.05, -0.05, -0.05]), w)
    assert O.enlc(years, sums, w) == pytest.approx(4.0)


def test_enlc_hedge_takes_share_zero():
    w = np.array([0.4, 0.4, 0.2])
    # two equal losers and a fund that gained in the bad years (a hedge): ENLC = 2
    years, sums = _enlc_case(np.array([-0.05, -0.05, 0.08]), w)
    assert O.enlc(years, sums, w) == pytest.approx(2.0)


def test_enlc_known_unequal_shares():
    w = np.array([0.5, 0.5])
    years, sums = _enlc_case(np.array([-0.03, -0.01]), w)
    s = np.array([0.75, 0.25])
    assert O.enlc(years, sums, w) == pytest.approx(math.exp(-(s @ np.log(s))))


def test_enlc_undefined_when_nothing_loses():
    w = np.array([0.5, 0.5])
    years, sums = _enlc_case(np.array([0.01, 0.02]), w)
    assert math.isnan(O.enlc(years, sums, w))


def test_worst_fall_constant_weights():
    returns = np.array([[0.10, 0.0], [-0.20, -0.10], [0.05, 0.0], [-0.10, 0.20]])
    w = np.array([0.5, 0.5])
    wealth = np.cumprod(1.0 + returns @ w)
    assert O.worst_fall(returns, w) == pytest.approx(_loop_drawdown(wealth))


def test_worst_fall_never_reads_after_the_origin():
    ctx = synthetic_context(funds=4, rows=400)
    clean = with_history(ctx)
    leaked = with_history(ctx, extra_after=30)
    w = np.full(4, 0.25)
    h_clean = O.worst_fall(O.history_returns(clean), w)
    h_leaked = O.worst_fall(O.history_returns(leaked), w)
    assert h_clean == h_leaked
    assert len(O.history_returns(clean)) == len(ctx.sample) - 1  # the NaN row is dropped
    # the post-origin crash would have been the worst fall had it been read
    assert leaked.history is not None
    full = leaked.history.dropna().to_numpy()
    assert O.worst_fall(full, w) > h_clean + 0.3


# ------------------------------------------------------------------------- replay path terms


@pytest.fixture(scope="module")
def replay():
    ctx = synthetic_context(funds=5, rows=300)
    return ctx, replay_bank(ctx, "replay", 11)


def test_replay_path_terms_years_equal_the_bank_and_drawdowns_the_loop(replay):
    ctx, bank = replay
    w = np.array([0.1, 0.2, 0.3, 0.25, 0.15])
    years, drawdowns, sums = bank.path_terms(w)
    np.testing.assert_allclose(years, bank.years(w)[:, 0], rtol=0, atol=1e-12)
    g = 1.0 + bank.a_matrix @ w
    for p in (0, 7, 1999):
        wealth = np.cumprod(g[bank.index[p]])
        assert drawdowns[p] == pytest.approx(_loop_drawdown(wealth), abs=1e-14)
        assert wealth[-1] - 1.0 == pytest.approx(years[p], rel=1e-11)
    # fund sums: the additive year of every path is S w
    additive = bank.counts @ (bank.a_matrix @ w)
    np.testing.assert_allclose(sums @ w, additive, rtol=1e-12, atol=1e-14)
    assert sums.shape == (bank.paths, 5)


def test_replay_absorbed_paths_do_not_raise(replay):
    ctx, bank = replay
    a = bank.a_matrix.copy()
    a[5, 0] = -1.5  # one sample day on which fund 0 loses 150%
    broken = replace(bank, a_matrix=a, growth_bound_ok=False)
    w = np.array([0.9, 0.025, 0.025, 0.025, 0.025])
    years, drawdowns, _ = broken.path_terms(w)
    hit = (bank.index == 5).any(axis=1)
    assert hit.any() and not hit.all()
    assert (years[hit] == -1.0).all() and (drawdowns[hit] == 1.0).all()
    assert np.isfinite(years).all() and (drawdowns[~hit] < 1.0).all()


# ----------------------------------------------------------------------------- the scorer


def test_scorer_row_is_consistent(replay):
    ctx, bank = replay
    ctx = with_history(ctx)
    geo = geometry(ctx)
    r = geo.x(0.4)
    scorer = O.Scorer(geo, bank, O.history_returns(ctx), O.origin_basis(ctx), r)
    w = geo.project(np.full(5, 0.2), r, C.TAU_NARROW)
    assert w is not None
    row = scorer.evaluate(w)
    years, drawdowns, sums = bank.path_terms(w)
    i = O.INDEX
    assert row[i["in_narrow"]] == 1.0 and row[i["in_wide"]] == 1.0
    assert row[i["tdd"]] == pytest.approx(np.sort(drawdowns)[-100:].mean())
    assert row[i["u1"]] == pytest.approx(
        0.6 * row[i["bad"]] + 0.3 * row[i["typical"]] + 0.1 * row[i["good"]]
    )
    assert row[i["max_bad"]] == row[i["bad"]]
    assert row[i["enlc"]] == pytest.approx(O.enlc(years, sums, w))
    assert row[i["h"]] == pytest.approx(O.worst_fall(O.history_returns(ctx), w))
    assert 1.0 <= row[i["enb"]] <= 5.0 + 1e-9
    assert row[i["dd_median"]] <= row[i["dd_p95"]] <= row[i["tdd"]] + 1e-12
    again = scorer.evaluate(w.copy())
    assert again is row and scorer.calls == 2 and scorer.evaluations == 1
