"""v3 report hooks: the confirmatory test on synthetic data with known answers, Newey-West, rank
agreement, CSCV across six arms and the ensemble screen's candidates and picks."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from portfoliosight.research import evidence
from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import cscv

from .synth import month_labels

K = 60


def _table(d_dd, d_ret, *, base_dd=0.10, base_ret=0.05, statuses=None, months=None):
    """Arm 1 (native rows) and arm 3 (pooled rows) with dd_m(arm 1) - dd_m(arm 3) = d_dd[a, o]
    and ret_m(arm 3) - ret_m(arm 1) = d_ret[a, o]."""
    months = months or month_labels(d_dd.shape[1])
    rows = []
    for j, rf in enumerate(C.RISK_FRACTIONS):
        for o, month in enumerate(months):
            common = dict(kind="main", lookback="3y", month=month, r_fraction=rf, lam=None,
                          complete=True, sigma=0.1, tdd=0.2)  # fmt: skip
            status = (statuses or {}).get((C.FRONTIER, j, o), C.OK)
            rows.append({**common, "arm": C.FRONTIER, "pooled": False, "status": status,
                         "dd_m": base_dd, "ret_m": base_ret})  # fmt: skip
            dd3, ret3 = base_dd - d_dd[j, o], base_ret + d_ret[j, o]
            rows.append({**common, "arm": C.MIN_TDD, "pooled": True, "status": C.OK,
                         "dd_m": dd3, "ret_m": ret3})  # fmt: skip
            rows.append({**common, "arm": C.MIN_TDD, "pooled": False, "status": C.OK,
                         "dd_m": 9.0, "ret_m": 9.0})  # native rows must be ignored  # fmt: skip
    return pd.DataFrame(rows), months


def _const(x):
    return np.full((6, K), x)


@pytest.mark.parametrize(
    ("d_dd", "d_ret", "label"),
    [
        (0.02, -0.001, A.PASS),
        (0.005, -0.001, A.FAIL_DD),  # interval above zero, below the 1 pp relevance filter
        (0.02, -0.01, A.FAIL_RET),
        (-0.01, -0.01, A.FAIL_BOTH),
    ],
)
def test_constant_differences_give_exact_answers(d_dd, d_ret, label):
    table, months = _table(_const(d_dd), _const(d_ret))
    res = A.confirmatory_test(table, months, resamples=200)
    assert res["theta_dd"]["value"] == pytest.approx(d_dd)
    assert res["theta_ret"]["value"] == pytest.approx(d_ret)
    assert res["theta_dd"]["interval"]["24"] == pytest.approx([d_dd, d_dd])
    assert res["theta_ret_p5"]["24"] == pytest.approx(d_ret)
    assert res["label"] == label
    assert res["eligible_origins"] == K and res["paired_cells"] == 6 * K
    if label == A.PASS:
        assert "95% interval above zero" in res["verdict_text"]
        assert "at least 1 pp" not in res["verdict_text"].replace("at least the 1 pp", "")


def test_bootstrap_matches_a_direct_computation():
    rng = np.random.default_rng(4)
    d_dd = rng.normal(0.012, 0.02, size=(6, K))
    d_ret = rng.normal(-0.001, 0.01, size=(6, K))
    table, months = _table(d_dd, d_ret)
    res = A.confirmatory_test(table, months, resamples=500)
    per_origin_dd = d_dd.mean(axis=0)
    per_origin_ret = d_ret.mean(axis=0)
    assert res["theta_dd"]["value"] == pytest.approx(per_origin_dd.mean())
    index = evidence.resample_index(K, 24, 500, evidence.BOOTSTRAP_SEED)
    draws_dd = per_origin_dd[index].mean(axis=1)
    draws_ret = per_origin_ret[index].mean(axis=1)
    assert res["theta_dd"]["interval"]["24"] == pytest.approx(
        list(np.percentile(draws_dd, [2.5, 97.5]))
    )
    assert res["theta_ret_p5"]["24"] == pytest.approx(np.percentile(draws_ret, 5.0))
    a = np.percentile(draws_dd, 2.5) > 0 and per_origin_dd.mean() >= 0.01
    b = np.percentile(draws_ret, 5.0) >= -0.005
    assert (res["A"], res["B"]) == (a, b)
    # the relative change: per cell over arm 1's drawdown (0.10), pooled the same way
    assert res["relative_dd"]["value"] == pytest.approx((d_dd / 0.10).mean())
    assert set(res["sensitivities"]) == {"12", "36"}


def test_only_eligible_origins_enter():
    d_dd = _const(0.02)
    d_dd[:, :10] = -0.5  # origins without a complete year must not count
    table, months = _table(d_dd, _const(0.0))
    res = A.confirmatory_test(table, months, eligible=months[10:], resamples=100)
    assert res["theta_dd"]["value"] == pytest.approx(0.02)
    assert res["eligible_origins"] == K - 10


def test_a_blocking_label_on_arm_1_is_inconclusive_and_usable_warnings_are_not():
    table, months = _table(_const(0.02), _const(0.0),
                           statuses={(C.FRONTIER, 2, 5): C.ANCHOR_FAILED})  # fmt: skip
    res = A.confirmatory_test(table, months, resamples=100)
    assert res["label"] == A.INCONCLUSIVE and res["blocking_cells"][0]["status"] == C.ANCHOR_FAILED
    table, months = _table(_const(0.02), _const(0.0),
                           statuses={(C.FRONTIER, 2, 5): C.INSUFFICIENT_STARTS})  # fmt: skip
    assert A.confirmatory_test(table, months, resamples=100)["label"] == A.PASS


def test_uneven_across_risk_flag():
    d_dd = _const(0.03)
    d_dd[:3] = -0.001  # three levels go the wrong way, the pooled test still passes
    table, months = _table(d_dd, _const(0.0))
    res = A.confirmatory_test(table, months, resamples=100)
    assert res["label"] == A.PASS and res["uneven_across_risk"]


def test_newey_west_against_the_formula():
    x = np.array([0.1, -0.2, 0.3, 0.05, -0.1, 0.2, 0.0, 0.15])
    mean, se = A.newey_west(x, lag=2)
    d = x - x.mean()
    n = len(x)
    gamma = [float(d[k:] @ d[: n - k]) / n for k in range(3)]
    s = gamma[0] + 2 * (1 - 1 / 3) * gamma[1] + 2 * (1 - 2 / 3) * gamma[2]
    assert mean == pytest.approx(x.mean()) and se == pytest.approx(math.sqrt(s / n))
    assert A.newey_west(x, lag=0)[1] == pytest.approx(math.sqrt(np.var(x) / n))


def _six_arm_rows(months, tdd_of, dd_of):
    rows = []
    for arm_i, arm in enumerate(C.V3_ARMS):
        pooled = arm not in (C.FRONTIER, C.ENB_KNEE)
        for rf in C.RISK_FRACTIONS:
            for o, month in enumerate(months):
                rows.append(dict(kind="main", lookback="3y", month=month, r_fraction=rf,
                                 lam=C.LAMBDA if arm == C.CRASH_PENALTY else None, arm=arm,
                                 pooled=pooled, status=C.OK, complete=True,
                                 tdd=tdd_of(arm_i, o), dd_m=dd_of(arm_i, o)))  # fmt: skip
    return A.locked_rows(pd.DataFrame(rows))


def test_rank_agreement_is_one_when_orders_agree():
    months = month_labels(30)
    rows = _six_arm_rows(months, lambda i, o: 0.1 + 0.01 * i, lambda i, o: 0.05 + 0.02 * i + o)
    out = A.rank_agreement(rows, months, resamples=50)
    for level in out["by_level"]:
        assert level["spearman"] == pytest.approx(1.0) and level["kendall"] == pytest.approx(1.0)
    rows = _six_arm_rows(months, lambda i, o: 0.1 + 0.01 * i, lambda i, o: 0.5 - 0.02 * i)
    level = A.rank_agreement(rows, months, resamples=50)["by_level"][0]
    assert level["spearman"] == pytest.approx(-1.0) and level["kendall"] == pytest.approx(-1.0)


def test_cscv_across_six_arms_uses_k_over_seven():
    months = month_labels(120)
    stamps = pd.period_range(months[0], periods=len(months), freq="M").to_timestamp(how="end")
    origins = [s.date() for s in stamps]
    ends = [pd.Timestamp(o) + pd.Timedelta(days=20) for o in origins]  # short, non-overlapping
    frozen = cscv.frozen_record(months, origins, [e.date() for e in ends])
    rng = np.random.default_rng(1)
    # arm index 2 (min_tdd) always has the lowest realized drawdown
    rows = _six_arm_rows(
        months, lambda i, o: 0.1,
        lambda i, o: 0.05 + (0.0 if i == 2 else 0.05) + 0.001 * rng.random(),
    )  # fmt: skip
    res = A.cscv_arms(rows, frozen)
    assert res is not None and res.evaluable
    assert all(r["chosen"] == 2 and r["rank"] == 6.0 for r in res.evaluable)
    assert all(r["omega"] == pytest.approx(6 / 7) for r in res.evaluable)


def test_simplex_grid_has_126_points():
    w = A.simplex_weights()
    assert w.shape == (126, 6) and np.allclose(w.sum(axis=1), 1.0)
    assert len({tuple(r) for r in w}) == 126


def _pool_rows():
    base = dict(lookback="3y", r_fraction=0.4, in_wide=True, mu=0.05, u1=0.0, tdd=0.2, h=0.3,
                enlc=2.0, enb=3.0)  # fmt: skip
    return pd.DataFrame(
        [
            {**base, "record": 0, "lam": None, "weights": [0.5, 0.5], "u1": 0.01},
            # the same mix after rounding to 1e-9: represented by record 0
            {**base, "record": 1, "lam": None, "weights": [0.5 + 1e-12, 0.5 - 1e-12], "u1": 0.9},
            {**base, "record": 2, "lam": C.LAMBDA, "weights": [0.6, 0.4], "u1": 0.02},
            {**base, "record": 3, "lam": 0.05, "weights": [0.7, 0.3], "u1": 0.5},  # side check
            {**base, "record": 4, "lam": None, "weights": [0.8, 0.2], "in_wide": False},
            {**base, "record": 5, "lam": None, "weights": [0.9, 0.1], "enlc": np.nan},
            {**base, "record": 6, "lam": None, "weights": [0.3, 0.7], "u1": 0.02},
        ]
    )


def test_ensemble_candidates_are_distinct_main_wide_band_mixes_with_average_ranks():
    cand = A.ensemble_candidates(_pool_rows())
    assert sorted(cand["record"]) == [0, 2, 6]
    ranks = dict(zip(cand["record"], cand["rank_u1"], strict=True))
    assert ranks[0] == pytest.approx(1 / 3)
    assert ranks[2] == pytest.approx(2.5 / 3) and ranks[6] == pytest.approx(2.5 / 3)  # a tie
    np.testing.assert_allclose(cand["rank_tdd"], 2 / 3)  # all equal: the average rank


def test_ensemble_picks_tie_to_the_lowest_record():
    cand = A.ensemble_candidates(_pool_rows())
    weights = np.zeros((2, 6))
    weights[0, 1] = 1.0  # U1 only: records 2 and 6 tie, 2 wins
    weights[1, 0] = 1.0  # mu only: every candidate ties, record 0 wins
    picks = A.ensemble_picks(cand, weights)
    assert picks.set_index("combination")["record"].to_dict() == {0: 2, 1: 0}


def test_dsr_arms_puts_arm_3_first_and_uses_the_disjoint_months():
    months = month_labels(30)
    rng = np.random.default_rng(2)
    noise = rng.normal(0, 0.01, size=(6, 30))
    rows = _six_arm_rows(months, lambda i, o: 0.1, lambda i, o: 0.1 + noise[i, o])
    out = A.dsr_arms(rows, months[::3])
    assert out["trials"][0] == C.MIN_TDD and len(out["trials"]) == 5
    assert out["intervals"] == 10 and out["n"] == 10


def test_ensemble_rows_score_against_arm_1():
    pool = _pool_rows().assign(menu="research2003", month="2010-01", origin=None,
                               engine="replay", sigma=0.1)  # fmt: skip
    cand = A.ensemble_candidates(pool)
    weights = np.zeros((1, 6))
    weights[0, 1] = 1.0
    rows = A.ensemble_rows(A.ensemble_picks(cand, weights), pool)
    assert list(rows["arm"]) == ["ensemble_0"] and rows["weights"].iloc[0] == [0.6, 0.4]
    assert rows["status"].iloc[0] == C.OK and bool(rows["pooled"].iloc[0])
