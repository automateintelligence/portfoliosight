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
    res = A.confirmatory_test(table, months, eligible=months, resamples=200)
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
    res = A.confirmatory_test(table, months, eligible=months, resamples=500)
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
    res = A.confirmatory_test(table, months, eligible=months, resamples=100)
    assert res["label"] == A.INCONCLUSIVE and res["blocking_cells"][0]["status"] == C.ANCHOR_FAILED
    table, months = _table(_const(0.02), _const(0.0),
                           statuses={(C.FRONTIER, 2, 5): C.INSUFFICIENT_STARTS})  # fmt: skip
    assert A.confirmatory_test(table, months, eligible=months, resamples=100)["label"] == A.PASS


def test_a_missing_outcome_at_an_eligible_cell_is_inconclusive():
    table, months = _table(_const(0.02), _const(0.0))
    cell = (table["arm"] == C.MIN_TDD) & table["pooled"] & (table["month"] == months[5])
    cell &= np.isclose(table["r_fraction"], C.RISK_FRACTIONS[2])
    table.loc[cell, "ret_m"] = np.nan  # one arm-3 outcome of 360 cells
    res = A.confirmatory_test(table, months, eligible=months, resamples=100)
    assert res["label"] == A.INCONCLUSIVE
    assert res["blocking_cells"] == [
        {"arm": C.MIN_TDD, "month": months[5], "rf": round(C.RISK_FRACTIONS[2], 6),
         "status": A.MISSING_OUTCOME}
    ]  # fmt: skip
    assert "Inconclusive: 1 eligible cells" in res["verdict_text"]


def test_eligible_origins_are_required():
    table, months = _table(_const(0.02), _const(0.0))
    with pytest.raises(TypeError):
        A.confirmatory_test(table, months, resamples=100)  # type: ignore[call-arg]


def test_an_eligible_origin_with_every_row_missing_is_inconclusive():
    table, months = _table(_const(0.02), _const(0.0))
    table = pd.DataFrame(table[table["month"] != months[7]])  # the whole origin vanished
    res = A.confirmatory_test(table, months, eligible=months, resamples=100)
    assert res["label"] == A.INCONCLUSIVE
    assert res["eligible_origins"] == K
    missing = {(c["arm"], c["month"]) for c in res["blocking_cells"]}
    assert missing == {(C.FRONTIER, months[7]), (C.MIN_TDD, months[7])}
    assert len(res["blocking_cells"]) == 2 * len(C.RISK_FRACTIONS)


def test_an_eligible_origin_with_every_outcome_missing_is_inconclusive():
    table, months = _table(_const(0.02), _const(0.0))
    gone = table["month"] == months[7]
    table.loc[gone, ["dd_m", "ret_m"]] = np.nan
    table.loc[gone, "complete"] = False
    res = A.confirmatory_test(table, months, eligible=months, resamples=100)
    assert res["label"] == A.INCONCLUSIVE and res["eligible_origins"] == K
    assert {c["status"] for c in res["blocking_cells"]} == {A.MISSING_OUTCOME}


def test_missing_outcomes_at_ineligible_origins_do_not_block():
    table, months = _table(_const(0.02), _const(0.0))
    late = table["month"].isin(months[:10])
    table.loc[late, ["dd_m", "ret_m"]] = np.nan  # origins without a complete realized year
    res = A.confirmatory_test(table, months, eligible=months[10:], resamples=100)
    assert res["label"] == A.PASS and res["blocking_cells"] == []
    assert res["eligible_origins"] == K - 10 and res["paired_cells"] == 6 * (K - 10)


def test_point_estimate_verdict_counts_a_zero_return_difference():
    table, months = _table(_const(0.02), _const(0.0))
    res = A.confirmatory_test(table, months, eligible=months, resamples=100)
    assert res["theta_ret"]["value"] == pytest.approx(0.0)
    assert res["point_estimate_verdict"] == A.PASS


def test_uneven_across_risk_flag():
    d_dd = _const(0.03)
    d_dd[:3] = -0.001  # three levels go the wrong way, the pooled test still passes
    table, months = _table(d_dd, _const(0.0))
    res = A.confirmatory_test(table, months, eligible=months, resamples=100)
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


def test_eligible_origins_come_from_the_frozen_cscv_months():
    parent = {"menus": {"research2003": {"cscv": {"months": ["2010-01", "2010-02"]}}}}
    assert A.eligible_origins(parent, "research2003") == ["2010-01", "2010-02"]
    for broken in ({"menus": {"research2003": {}}}, {"menus": {"research2003": {"cscv": {}}}}):
        with pytest.raises(ValueError, match="frozen eligible origins"):
            A.eligible_origins(broken, "research2003")


def _realized_rows(months, value, *, kind="main", lookback="3y", regime_of=None, lam_side=None):
    """Main-like rows of every arm with realized and model columns from `value(arm, j, o, col)`."""
    rows = []
    for arm in C.V3_ARMS:
        pooled = arm not in (C.FRONTIER, C.ENB_KNEE)
        lams = [C.LAMBDA] if arm == C.CRASH_PENALTY else [None]
        if lam_side is not None:
            if arm != C.CRASH_PENALTY:
                continue
            lams = [lam_side]
        for lam in lams:
            for j, rf in enumerate(C.RISK_FRACTIONS):
                for o, month in enumerate(months):
                    row = dict(sel_id=f"{arm}|{lam}|{kind}|{rf}|{month}", kind=kind,
                               lookback=lookback, month=month, r_fraction=rf, lam=lam, arm=arm,
                               pooled=pooled, status=C.OK, complete=True,
                               regime=regime_of(o) if regime_of else "calm")  # fmt: skip
                    for col in ("ret_m", "dd_m", "vol_m", "u1", "h", "tdd", "enb", "bad", "es_25"):
                        row[col] = value(arm, j, o, col)
                    rows.append(row)
    return pd.DataFrame(rows)


def test_regime_buckets_average_levels_then_origins_per_regime():
    months = month_labels(12)
    regime = lambda o: "equity drawdown" if o < 4 else "calm"  # noqa: E731

    def value(arm, j, o, col):
        if col == "dd_m":  # arm 3 falls 2 pp less in drawdown years, 1 pp more in calm years
            base = 0.30 if o < 4 else 0.08
            return base - (0.02 if o < 4 else -0.01) * (arm == C.MIN_TDD)
        if col == "ret_m":
            return (-0.2 if o < 4 else 0.1) + 0.01 * j
        return 0.1

    rows = A.locked_rows(_realized_rows(months, value, regime_of=regime))
    out = A.regime_buckets(rows, months, eligible=months[1:])
    by = {b["regime"]: b for b in out}
    assert by["equity drawdown"]["origins"] == 3 and by["calm"]["origins"] == 8
    assert by["equity drawdown"]["d_dd"] == pytest.approx(0.02)
    assert by["calm"]["d_dd"] == pytest.approx(-0.01)
    assert by["calm"]["d_ret"] == pytest.approx(0.0)
    assert by["equity drawdown"]["arms"][C.FRONTIER]["dd_m"] == pytest.approx(0.30)
    assert by["calm"]["arms"][C.FRONTIER]["ret_m"] == pytest.approx(0.1 + 0.01 * 2.5)
    assert by["rate shock"]["origins"] == 0 and by["rate shock"]["d_dd"] is None


def test_side_checks_summarize_each_lambda_and_the_five_year_lookback():
    months = month_labels(5)

    def value(arm, j, o, col):
        return 0.1 if col != "h" else 0.3

    def side(lam):
        return lambda arm, j, o, col: {"h": 0.3 - lam, "u1": lam}.get(col, 0.1)

    table = pd.concat(
        [
            _realized_rows(months, value),
            _realized_rows(months[:3], side(0.05), kind="side_lambda", lam_side=0.05),
            _realized_rows(months[:3], side(0.2), kind="side_lambda", lam_side=0.2),
            _realized_rows(months[:2], lambda a, j, o, c: 0.2, kind="sens_5y", lookback="5y"),
        ],
        ignore_index=True,
    )
    out = A.side_checks(table)
    lam = {row["lam"]: row for row in out["lambda"]["rows"]}
    assert out["lambda"]["months"] == months[:3]
    assert lam[0.05]["h"] == pytest.approx(0.25) and lam[0.2]["u1"] == pytest.approx(0.2)
    assert lam[C.LAMBDA]["h"] == pytest.approx(0.3) and lam[C.LAMBDA]["n"] == 18  # same months
    five = out["lookback_5y"]
    assert five["months"] == months[:2]
    assert {r["arm"] for r in five["arms_5y"]} == set(C.V3_ARMS)
    assert all(r["dd_m"] == pytest.approx(0.2) for r in five["arms_5y"])
    assert all(r["dd_m"] == pytest.approx(0.1) and r["n"] == 12 for r in five["arms_3y"])


def test_independent_banks_average_seeds_per_arm():
    months = month_labels(3)
    rows = A.locked_rows(_realized_rows(months, lambda a, j, o, c: 0.1))
    evaluated = pd.DataFrame(
        [{"sel_id": s, "test_seed": seed, "bad": 0.0, "es_25": 0.0, "u1": 0.0,
          "tdd": 0.1 + (0.02 if seed % 2 else 0.0)}
         for s in rows["sel_id"] for seed in (20261113, 20261114)]
    )  # fmt: skip
    out = {r["arm"]: r for r in A.independent_banks(rows, evaluated)}
    assert out[C.MIN_TDD]["tdd_train"] == pytest.approx(0.1)
    assert out[C.MIN_TDD]["tdd_independent"] == pytest.approx(0.11)
    assert out[C.MIN_TDD]["seeds"] == 2 and out[C.MIN_TDD]["n"] == 18


def test_run_facts_read_the_job_files(tmp_path):
    job = tmp_path / "research2003_replay"
    (job / "tasks").mkdir(parents=True)
    (job / "tasks" / "research2003_2010-01_replay.parquet").write_bytes(b"")
    (job / "job.json").write_text('{"status": "complete", "tasks_done": 1, "tasks_total": 2}')
    (job / "failures.jsonl").write_text('{"task": "x", "error": "boom"}\n')
    (job / "overrides.jsonl").write_text('{"reason": "owner approved"}\n')
    parent = {"menus": {"research2003": {"schedule": ["2010-01", "2010-02"]}},
              "amendments": [{"text": "GARCH job added"}]}  # fmt: skip
    facts = A.run_facts(job, parent, "research2003")
    assert facts["status"] == "complete" and facts["task_files"] == 1 and facts["schedule"] == 2
    assert not facts["complete"]  # one task file of two
    assert facts["failures"] == [{"task": "x", "error": "boom"}]
    assert facts["overrides"] == [{"reason": "owner approved"}]
    assert facts["amendments"] == [{"text": "GARCH job added"}]
