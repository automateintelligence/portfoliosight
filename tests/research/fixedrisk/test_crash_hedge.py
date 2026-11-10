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
