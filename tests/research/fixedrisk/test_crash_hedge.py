"""The behavioural test of the region check addendum (2026-11-09): on a made-up menu with a planted
crash hedge (a fund that rises on the days the others crash, at equal volatility and lower
return), the lowest-simulated-drawdown search (arm 3) puts more weight on the hedge than the
frontier search (arm 1) and reaches a lower simulated tail drawdown at the same risk."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import numpy as np
import pytest

from portfoliosight.engine.stats import estimate_moments, menu_beta_blend
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import search3 as S
from portfoliosight.research.fixedrisk.anchors import geometry
from portfoliosight.research.fixedrisk.banks import replay_bank
from portfoliosight.research.fixedrisk.contracts import MenuSpec, OriginContext
from portfoliosight.research.fixedrisk.knee import knee_columns

from .optimizer_data import with_history

ROWS = 756  # the 3-year lookback
HEDGE = 3  # funds 0-2 are equity-like, fund 3 the hedge
RF = (0.55,)
CALLS = 96
CRASHES = 8  # episodes of 5 consecutive days
DAILY_VOL = 0.01


def hedge_context(seed: int = 11) -> OriginContext:
    """Three correlated equity-like funds that fall 4% a day through each crash episode and a
    hedge that rises 4% a day through the same days; every fund scaled to the same daily
    volatility, the hedge given the lowest drift."""
    rng = np.random.default_rng(seed)
    common = rng.normal(size=ROWS)
    idio = rng.normal(size=(ROWS, 3))
    equity = 0.6 * common[:, None] + 0.8 * idio
    hedge = rng.normal(size=ROWS)
    crash = np.zeros(ROWS, dtype=bool)
    for start in rng.choice(np.arange(20, ROWS - 20, 80), CRASHES, replace=False):
        crash[start : start + 5] = True
    raw = np.column_stack([equity, hedge])
    raw = raw / raw.std(axis=0) * 0.005
    raw[crash, :3] = -0.04
    raw[crash, HEDGE] = 0.04
    sample = (raw - raw.mean(axis=0)) / raw.std(axis=0) * DAILY_VOL
    sample = sample + np.array([6e-4, 6e-4, 6e-4, 1e-4])
    moments = estimate_moments(sample)
    rf = 0.03
    mu_s = menu_beta_blend(moments.mu, moments.cov, rf)[0]
    funds = sample.shape[1]
    menu = MenuSpec("hedge", tuple(f"F{i}" for i in range(funds)), (0.0,) * funds,
                    (0.6,) * funds)  # fmt: skip
    sample.setflags(write=False)
    origin = date(2020, 1, 31)
    return OriginContext(
        menu=menu,
        month="2020-01",
        origin=origin,
        lookback="3y",
        days=tuple(origin - timedelta(days=ROWS - i) for i in range(ROWS)),
        sample=sample,
        mu_hat=moments.mu,
        mu_s=mu_s,
        cov=moments.cov,
        sigma=moments.sigma,
        risk_free_rate=rf,
        inputs_sha256=hashlib.sha256(sample.tobytes()).hexdigest(),
    )


@pytest.fixture(scope="module")
def searched():
    ctx = with_history(hedge_context())
    bank = replay_bank(ctx, "replay", C.PRIMARY_SEED)
    geo = geometry(ctx)
    knee = knee_columns(ctx, {a: geo.x(a) for a in RF}, nx=12)
    out = S.search_origin_v3(ctx, bank, arms=(C.FRONTIER, C.MIN_TDD), risk_fractions=RF,
                             calls=CALLS, knee=knee)  # fmt: skip
    return ctx, out


def test_the_menu_is_what_it_claims(searched):
    ctx, _ = searched
    vols = np.sqrt(np.diag(ctx.cov))
    assert np.ptp(vols) == pytest.approx(0.0, abs=1e-12)  # equal volatility
    assert ctx.mu_s[HEDGE] < ctx.mu_s[:HEDGE].min()  # lower return
    corr = ctx.cov / np.outer(vols, vols)
    assert corr[HEDGE, :HEDGE].max() < 0.0


def test_the_lowest_drawdown_search_holds_more_of_the_hedge_and_falls_less(searched):
    _, out = searched
    pick = {(s["arm"], s["pooled"]): s for s in out.selections}
    frontier = pick[(C.FRONTIER, False)]
    lowest = pick[(C.MIN_TDD, True)]
    assert frontier["status"] == C.OK and lowest["status"] == C.OK
    w_f, w_l = np.asarray(frontier["weights"]), np.asarray(lowest["weights"])
    tdd = S.INDEX["tdd"]
    tdd_f, tdd_l = float(frontier["values"][tdd]), float(lowest["values"][tdd])
    detail = f"hedge weight {w_l[HEDGE]:.4f} vs {w_f[HEDGE]:.4f}; tdd {tdd_l:.5f} vs {tdd_f:.5f}"
    assert w_l[HEDGE] > w_f[HEDGE], detail
    assert tdd_l < tdd_f, detail


# ------------------------------------------------------------- correction 6: hedge and decoy

# The second menu adds a decoy (fund 4) that matches the hedge (fund 3) in volatility, model
# return and full-sample covariance with each equity-like fund, so no variance-based measure can
# tell them apart. The hedge's offset comes in the clustered crash episodes; the decoy's comes on
# ordinary days, spread out, and it does nothing on crash days. Crash days carry a quarter of an
# equity-like fund's variance and half of the hedge's.
DECOY = 4
EQUITY_CRASH_SHARE = 0.25
HEDGE_CRASH_SHARE = 0.5


def decoy_context(seed: int = 11) -> tuple[OriginContext, np.ndarray]:
    """The menu with the hedge and the decoy, and the crash-day mask."""
    rng = np.random.default_rng(seed)
    crash = np.zeros(ROWS, dtype=bool)
    for start in rng.choice(np.arange(20, ROWS - 20, 80), CRASHES, replace=False):
        crash[start : start + 5] = True
    n_crash, n_ord = int(crash.sum()), int((~crash).sum())
    ordinary = ~crash
    # equity-like funds: a common and an own factor on ordinary days, a common fall on crash days
    equity = 0.6 * rng.normal(size=(ROWS, 1)) + 0.8 * rng.normal(size=(ROWS, 3))
    fall = np.sqrt(EQUITY_CRASH_SHARE / (1.0 - EQUITY_CRASH_SHARE) * n_ord / n_crash)
    equity[crash] = -fall
    # the hedge: own noise on ordinary days, a rise on crash days
    hedge = rng.normal(size=ROWS)
    rise = np.sqrt(HEDGE_CRASH_SHARE / (1.0 - HEDGE_CRASH_SHARE) * n_ord / n_crash)
    hedge[crash] = rise
    raw = np.column_stack([equity, hedge])
    sample = (raw - raw.mean(axis=0)) / raw.std(axis=0, ddof=1) * DAILY_VOL
    sample = sample + np.array([6e-4, 6e-4, 6e-4, 1e-4])
    # the decoy: the hedge's mean, its cross products with the equity-like funds and its
    # variance, from ordinary-day moves against those funds plus ordinary-day noise
    centered = sample - sample.mean(axis=0)
    eq, h = centered[:, :3], centered[:, HEDGE]
    target = eq.T @ h  # cross products with each equity-like fund
    q = eq[ordinary] - eq[ordinary].mean(axis=0)  # sums to zero over the ordinary days
    b = np.linalg.solve(q.T @ q, target)
    against = q @ b
    basis = np.column_stack([q, np.ones(n_ord)])
    noise = rng.normal(size=n_ord)
    noise -= basis @ np.linalg.lstsq(basis, noise, rcond=None)[0]
    room = float(h @ h) - float(against @ against)
    if room <= 0.0:
        raise ValueError(f"the decoy cannot match the hedge's variance (short by {-room})")
    d = np.zeros(ROWS)
    d[ordinary] = against + noise * np.sqrt(room / float(noise @ noise))
    decoy = sample[:, HEDGE].mean() + d
    sample = np.column_stack([sample, decoy])
    moments = estimate_moments(sample)
    rf = 0.03
    mu_s = menu_beta_blend(moments.mu, moments.cov, rf)[0]
    funds = sample.shape[1]
    menu = MenuSpec("decoy", tuple(f"F{i}" for i in range(funds)), (0.0,) * funds,
                    (0.6,) * funds)  # fmt: skip
    sample.setflags(write=False)
    origin = date(2020, 1, 31)
    ctx = OriginContext(
        menu=menu,
        month="2020-01",
        origin=origin,
        lookback="3y",
        days=tuple(origin - timedelta(days=ROWS - i) for i in range(ROWS)),
        sample=sample,
        mu_hat=moments.mu,
        mu_s=mu_s,
        cov=moments.cov,
        sigma=moments.sigma,
        risk_free_rate=rf,
        inputs_sha256=hashlib.sha256(sample.tobytes()).hexdigest(),
    )
    return with_history(ctx), crash


@pytest.fixture(scope="module")
def decoy_menu():
    ctx, crash = decoy_context()
    return ctx, crash, replay_bank(ctx, "replay", C.PRIMARY_SEED)


def test_the_decoy_matches_the_hedge_in_every_variance_based_figure(decoy_menu):
    ctx, crash, _ = decoy_menu
    x = np.asarray(ctx.sample)
    sample_cov = np.cov(x, rowvar=False)
    assert sample_cov[DECOY, DECOY] == pytest.approx(sample_cov[HEDGE, HEDGE], rel=1e-12)
    assert sample_cov[DECOY, :HEDGE] == pytest.approx(sample_cov[HEDGE, :HEDGE], rel=1e-10)
    assert x[:, DECOY].mean() == pytest.approx(x[:, HEDGE].mean(), rel=1e-12)
    assert ctx.cov[DECOY, DECOY] == pytest.approx(ctx.cov[HEDGE, HEDGE], rel=1e-12)
    assert ctx.cov[DECOY, :HEDGE] == pytest.approx(ctx.cov[HEDGE, :HEDGE], rel=1e-10)
    assert ctx.mu_s[DECOY] == pytest.approx(ctx.mu_s[HEDGE], abs=1e-12)
    assert ctx.mu_s[HEDGE] < ctx.mu_s[:HEDGE].min()
    vols = np.sqrt(np.diag(ctx.cov))
    assert np.ptp(vols) == pytest.approx(0.0, abs=1e-12)
    # the hedge rises through the crash days; the decoy sits at its mean there and moves
    # against the equity-like funds on ordinary days instead
    assert bool((x[crash, HEDGE] > 0.0).all())
    assert x[crash, DECOY] == pytest.approx(np.full(int(crash.sum()), x[:, DECOY].mean()),
                                            abs=1e-15)  # fmt: skip
    ordinary = ~crash
    assert np.corrcoef(x[ordinary, DECOY], x[ordinary, :HEDGE].mean(axis=1))[0, 1] < 0.0


def test_swapping_hedge_and_decoy_keeps_the_risk_and_the_hedge_falls_less(decoy_menu):
    from portfoliosight.research.fixedrisk.objectives3 import Scorer, history_returns, origin_basis

    ctx, _, bank = decoy_menu
    geo = geometry(ctx)
    hedged = np.array([0.2, 0.2, 0.2, 0.3, 0.1])
    decoyed = np.array([0.2, 0.2, 0.2, 0.1, 0.3])
    assert geo.risk(hedged) == pytest.approx(geo.risk(decoyed), rel=1e-12)
    scorer = Scorer(geo, bank, history_returns(ctx), origin_basis(ctx), geo.risk(hedged))
    tdd = S.INDEX["tdd"]
    tdd_h = float(scorer.evaluate(hedged)[tdd])
    tdd_d = float(scorer.evaluate(decoyed)[tdd])
    assert tdd_h < tdd_d, f"tdd hedge-heavy {tdd_h:.5f} vs decoy-heavy {tdd_d:.5f}"


def test_the_lowest_drawdown_search_prefers_the_hedge_to_the_decoy(decoy_menu):
    ctx, _, bank = decoy_menu
    geo = geometry(ctx)
    knee = knee_columns(ctx, {a: geo.x(a) for a in RF}, nx=12)
    out = S.search_origin_v3(ctx, bank, arms=(C.FRONTIER, C.MIN_TDD), risk_fractions=RF,
                             calls=CALLS, knee=knee)  # fmt: skip
    pick = {(s["arm"], s["pooled"]): s for s in out.selections}
    frontier, lowest = pick[(C.FRONTIER, False)], pick[(C.MIN_TDD, True)]
    assert frontier["status"] == C.OK and lowest["status"] == C.OK
    w_f, w_l = np.asarray(frontier["weights"]), np.asarray(lowest["weights"])
    tdd = S.INDEX["tdd"]
    tdd_f, tdd_l = float(frontier["values"][tdd]), float(lowest["values"][tdd])
    detail = f"weights {np.round(w_l, 4)} vs frontier {np.round(w_f, 4)}; tdd {tdd_l} vs {tdd_f}"
    assert w_l[HEDGE] > w_l[DECOY], detail
    assert tdd_l < tdd_f, detail
