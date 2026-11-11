"""The safety-measures check (docs/plans/2026-11-11-fixed-risk-v3-safety-measures-check.md) on
made-up wealth paths, cell tables and a small recorded job whose answers are known by hand: time
under water, the long-horizon fall, the worst-years tail, the surprises and their signs, every
label boundary of the four pass/fail tests, the three decision rules and determinism."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from portfoliosight.research import evidence
from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import ensemble3 as ENS
from portfoliosight.research.fixedrisk import realized as R
from portfoliosight.research.fixedrisk import region3 as G
from portfoliosight.research.fixedrisk import safety3 as S
from portfoliosight.research.fixedrisk.driver import DIGEST_KEY
from portfoliosight.research.fixedrisk.objectives3 import FIELDS
from portfoliosight.research.fixedrisk.pool import PoolBuffer, write_pool

from .synth import month_labels, origin_of

DIGEST = "digest-s"
MENU, ENGINE = "research2003", "replay"
BOUNDS = ((0.0, 0.0), (1.0, 1.0))  # the two-fund test menu
N5 = 5 * R.HORIZON_DAYS


def _bdays(n: int, month: str = "2010-01") -> list:
    return list(pd.bdate_range(origin_of(month) + pd.Timedelta(days=1), periods=n))


# ------------------------------------------------------------------------ time under water


@pytest.mark.parametrize(
    ("wealth", "sessions"),
    [
        ((1.1, 1.0, 1.05, 1.08, 1.2, 1.1, 1.3), 3),  # runs of 3 and 1 sessions
        ((1.1, 1.2, 1.0, 1.0, 1.0, 1.0), 4),  # still under water at the window end
        ((1.0, 1.01, 1.02, 1.5), 0),  # never below its start or its peak
        ((1.0, 1.0, 1.0), 0),  # flat at the start value: not below it
        ((0.99, 0.98, 1.0, 1.01, 1.005), 2),  # the peak is floored at the start value 1
        ((0.5, 0.6, 0.7, 0.8, 0.9), 5),  # never back to the start
    ],
)
def test_longest_time_under_water_in_sessions(wealth, sessions):
    assert S.under_water(np.array(wealth)[:, None]).tolist() == [sessions]


def test_time_under_water_is_per_mix():
    wealth = np.array([[1.1, 0.9], [1.0, 1.1], [1.2, 1.05], [1.1, 1.2]])
    # mix 0: under water at session 1 and 3 (one session each); mix 1: sessions 0 and 2
    assert S.under_water(wealth).tolist() == [1, 1]
    wealth[2, 0] = 1.05  # mix 0 now under water at sessions 1 and 2; back at its peak at 3
    assert S.under_water(wealth).tolist() == [2, 1]


def test_window_outcomes_of_hand_built_paths():
    n = 63
    r0 = np.zeros(n)
    r0[0], r0[1], r0[2] = 1.0, -0.5, 1.0  # wealth 2, 1, 2, 2, ...: fall 50%, one session
    r1 = np.zeros(n)
    r1[0], r1[42] = -0.5, 1.0  # wealth 0.5 for 42 sessions, then back to the start value 1
    daily = np.column_stack([r0, r1, np.zeros(n)])
    out = S.window_outcomes(daily, _bdays(n), [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0, 0, 1.0]])
    assert out["fall"].tolist() == [0.5, 0.5, 0.0]
    assert out["under_water"].tolist() == [1 / 21, 2.0, 0.0]
    assert out["return"].tolist() == [1.0, 0.0, 0.0]


def test_the_wealth_path_is_the_monthly_rebalanced_convention():
    rng = np.random.default_rng(3)
    n = 130  # six calendar months: five rebalances inside the window
    daily = rng.normal(0.0003, 0.01, size=(n, 3))
    days = _bdays(n)
    weights = rng.dirichlet(np.ones(3), size=4)
    path = S.wealth_path(daily, days, weights)
    for t in range(n):
        want = R.monthly_rebalanced(daily[: t + 1], days[: t + 1], weights).annual + 1.0
        assert path[t] == pytest.approx(want, rel=1e-13, abs=0.0)
    out = S.window_outcomes(daily, days, weights)
    direct = R.monthly_rebalanced(daily, days, weights)
    assert out["fall"].tolist() == direct.drawdown.tolist()
    assert out["return"].tolist() == direct.annual.tolist()


# ------------------------------------------------------------------------------ worst years


@pytest.mark.parametrize(
    ("n", "k"),
    [(1, 1), (9, 1), (10, 1), (11, 2), (20, 2), (30, 3), (31, 4), (230, 23), (234, 24)],
)
def test_tail_size_is_ten_percent_rounded_up(n, k):
    assert S.tail_size(n) == k


def test_tail_means_of_the_largest_and_the_lowest_tenth():
    x = np.array([0.05, np.nan, 0.30, 0.10, 0.20, 0.01, 0.02, 0.03, 0.04, 0.06, 0.07, 0.08])
    whole = np.arange(len(x))[None, :]  # 11 finite values: the 2 largest or lowest
    assert S.tail_mean(x, whole, largest=True)[0] == pytest.approx(0.25, abs=1e-15)
    assert S.tail_mean(x, whole, largest=False)[0] == pytest.approx(0.015, abs=1e-15)
    resampled = np.array([[2, 2, 3], [1, 1, 1]])  # a repeated value counts each time
    got = S.tail_mean(x, resampled, largest=True)
    assert got[0] == pytest.approx(0.30, abs=1e-15) and math.isnan(got[1])


# ---------------------------------------------------------------------- cell tables

BASE_F = {"mu": 0.07, "sigma": 0.12, "ret_1y": 0.05, "dd_1y": 0.20, "vol_1y": 0.10,
          "fall_3y": 0.30, "under_water_3y": 10.0, "ret_3y": 0.20, "fall_5y": 0.35,
          "under_water_5y": 12.0, "ret_5y": 0.40}  # fmt: skip
BASE_E = {"mu": 0.075, "sigma": 0.10, "ret_1y": 0.08, "dd_1y": 0.15, "vol_1y": 0.11,
          "fall_3y": 0.28, "under_water_3y": 8.0, "ret_3y": 0.18, "fall_5y": 0.30,
          "under_water_5y": 9.0, "ret_5y": 0.37}  # fmt: skip
FIVE = ("fall_5y", "under_water_5y", "ret_5y")


def _table(k: int, e: dict | None = None, five_months: int | None = None) -> pd.DataFrame:
    """F and E in every cell of `k` start months with constant values; the 5-year figures only
    in the first `five_months` start months."""
    rows = []
    for o, month in enumerate(month_labels(k)):
        for rf in A.RFS:
            for mix, values in ((S.F, BASE_F), (S.E, {**BASE_E, **(e or {})})):
                row = {"month": month, "rf": rf, "mix": mix, **values}
                if five_months is not None and o >= five_months:
                    row.update(dict.fromkeys(FIVE, np.nan))
                rows.append(row)
    return pd.DataFrame(rows)


def _assemble(table: pd.DataFrame, k: int) -> dict:
    return S.assemble(table, month_labels(k), resamples=50)


def test_signs_and_surprises_against_f():
    out = _assemble(_table(30), 30)
    e = out["mixes"][S.E]
    want = {
        "return_1y": 0.03,  # mix minus F
        "fall_3y": 0.02,  # F minus mix: E fell less
        "under_water_3y": 2.0,  # E under water for less time
        "return_3y": -0.02,
        "fall_5y": 0.05,
        "under_water_5y": 3.0,
        "return_5y": -0.03,
        "return_surprise": 0.015,  # |0.05 - 0.07| - |0.08 - 0.075|
        "volatility_surprise": 0.01,  # |0.10 - 0.12| - |0.11 - 0.10|
        "return_gap": 0.025,  # (0.08 - 0.075) - (0.05 - 0.07)
        "volatility_gap": 0.03,  # (0.11 - 0.10) - (0.10 - 0.12)
        "tail_fall": 0.05,
        "tail_return": 0.03,
    }
    for name, d in want.items():
        assert e[name]["difference"] == pytest.approx(d, abs=1e-12), name
        assert e[name]["interval_95"] == pytest.approx([d, d], abs=1e-12), name
        assert e[name]["start_months"] == 30 and e[name]["cells"] == 180, name
    assert e["return_surprise"]["mean"] == pytest.approx(0.005, abs=1e-12)
    assert e["return_surprise"]["mean_F"] == pytest.approx(0.02, abs=1e-12)
    assert e["return_gap"]["mean"] == pytest.approx(0.005, abs=1e-12)
    assert e["volatility_gap"]["mean_F"] == pytest.approx(-0.02, abs=1e-12)
    for name in ("return_1y", "return_3y", "return_5y", "tail_return"):
        assert e[name]["lower_95"] == pytest.approx(want[name], abs=1e-12)
    assert "lower_95" not in e["fall_5y"]
    f = out["mixes"][S.F]
    assert f["fall_5y"] == {"mean": pytest.approx(0.35, abs=1e-12), "start_months": 30,
                            "cells": 180}  # fmt: skip
    assert out["cells"][S.F] == 180 and out["cells"][S.L] == 0
    assert out["mixes"][S.L]["fall_5y"]["difference"] is None
    assert out["mixes"][S.L]["fall_5y"]["cells"] == 0


def test_p4_reports_the_part_of_the_difference_from_the_model_return():
    out = _assemble(_table(30), 30)
    p4 = out["p4_model_return"]
    assert p4["mu_F"] == pytest.approx(0.07) and p4["mu_E"] == pytest.approx(0.075)
    assert p4["mu_F_minus_mu_E"] == pytest.approx(-0.005, abs=1e-12)
    assert p4["cells"] == 180 and p4["start_months"] == 30
    assert p4["p4_difference"] == pytest.approx(0.015, abs=1e-12)


def test_the_mean_and_difference_use_the_cells_both_mixes_have():
    table = _table(30)
    gone = (table["mix"] == S.E) & (table["month"] == month_labels(30)[0])
    table.loc[gone, "fall_3y"] = np.nan
    table.loc[(table["mix"] == S.F) & (table["month"] == month_labels(30)[1]), "fall_3y"] = 0.9
    out = _assemble(table, 30)
    e = out["mixes"][S.E]["fall_3y"]
    assert e["start_months"] == 29 and e["cells"] == 174
    # start month 1 has F at 0.9: one of 29 start months with a difference of 0.62
    assert e["difference"] == pytest.approx((28 * 0.02 + 0.62) / 29, abs=1e-12)
    assert e["mean_F"] == pytest.approx((28 * 0.30 + 0.9) / 29, abs=1e-12)
    assert out["mixes"][S.F]["fall_3y"]["start_months"] == 30


def test_the_worst_years_rank_each_mix_on_its_own_outcomes_per_setting():
    k = 20  # two of 20 start months per setting
    months = month_labels(k)
    rows = []
    for o, month in enumerate(months):
        for j, rf in enumerate(A.RFS):
            dd_f = 0.40 + 0.01 * j if o < 2 else 0.10
            dd_e = 0.30 + 0.01 * j if o >= 18 else 0.10
            if j == 5 and o >= 16:
                dd_e = 0.90  # four bad years in the top setting
            rows.append({"month": month, "rf": rf, "mix": S.F, **BASE_F, "dd_1y": dd_f})
            rows.append({"month": month, "rf": rf, "mix": S.E, **BASE_E, "dd_1y": dd_e})
    out = _assemble(pd.DataFrame(rows), k)
    tail = out["mixes"][S.E]["tail_fall"]
    tail_f = np.mean([0.40 + 0.01 * j for j in range(6)])
    tail_e = (0.30 + 0.31 + 0.32 + 0.33 + 0.34 + 0.90) / 6  # each setting's own two worst
    assert tail["mean"] == pytest.approx(tail_e, abs=1e-12)
    assert tail["mean_F"] == pytest.approx(tail_f, abs=1e-12)
    assert tail["difference"] == pytest.approx(tail_f - tail_e, abs=1e-12)
    # inside each resample both tails are recomputed on the resampled start months
    grid_f = np.array([[r["dd_1y"] for r in rows if r["mix"] == S.F and r["rf"] == rf]
                       for rf in A.RFS])  # fmt: skip
    grid_e = np.array([[r["dd_1y"] for r in rows if r["mix"] == S.E and r["rf"] == rf]
                       for rf in A.RFS])  # fmt: skip
    index = evidence.resample_index(k, evidence.BLOCK, 50, evidence.BOOTSTRAP_SEED)
    draws = []
    for row in index:
        per = []
        for gf, ge in zip(grid_f, grid_e, strict=True):
            top = 2  # ten percent of 20, rounded up
            per.append(np.sort(gf[row])[-top:].mean() - np.sort(ge[row])[-top:].mean())
        draws.append(np.mean(per))
    want = np.percentile(draws, [2.5, 97.5])
    assert tail["interval_95"] == pytest.approx(want.tolist(), abs=1e-12)


# ------------------------------------------------------------------ the pass/fail tests


def _label(**kw):
    args = {"difference": 0.01, "interval": (0.001, 0.02), "return_lower": -0.025,
            "bar": 0.01, "return_line": -0.025, "months": 120, "min_months": 120}  # fmt: skip
    args.update(kw)
    interval = args.pop("interval")
    difference = args.pop("difference")
    return_lower = args.pop("return_lower")
    return S.pass_fail_label(difference, interval, return_lower, **args)["label"]


@pytest.mark.parametrize(
    ("kw", "label"),
    [
        ({}, S.LEAD),  # at the bar, at the return line, with 120 start months
        ({"difference": 0.0099999}, S.NO),  # just below the bar
        ({"difference": -0.5, "interval": (-0.6, -0.4)}, S.NO),
        ({"interval": (0.0, 0.02)}, S.INCONCLUSIVE),  # the interval touches 0
        ({"interval": (-0.001, 0.02)}, S.INCONCLUSIVE),  # the interval includes 0
        ({"interval": (None, None)}, S.INCONCLUSIVE),
        ({"return_lower": -0.0250001}, S.INCONCLUSIVE),  # the return condition fails
        ({"return_lower": None}, S.INCONCLUSIVE),
        ({"months": 119}, S.INCONCLUSIVE),  # fewer than 120 usable start months
        ({"months": 119, "difference": 0.0, "interval": (-0.1, 0.1)}, S.INCONCLUSIVE),
        ({"months": 3, "min_months": None}, S.LEAD),  # a one-year test has no minimum
        ({"difference": None, "interval": (None, None)}, S.INCONCLUSIVE),
    ],
)
def test_pass_fail_label_boundaries(kw, label):
    assert _label(**kw) == label


def test_the_four_tests_and_their_bars():
    tests = {k: (t.outcome, t.bar, t.return_outcome, t.return_line, t.min_months)
             for k, t in S.PASS_FAIL.items()}  # fmt: skip
    assert tests == {
        "P1": ("fall_5y", 0.010, "return_5y", -0.025, 120),
        "P2": ("under_water_5y", 3.0, "return_5y", -0.025, 120),
        "P3": ("tail_fall", 0.010, "return_1y", -0.005, None),
        "P4": ("return_surprise", 0.005, "return_1y", -0.005, None),
    }


def test_pass_fail_on_a_table():
    # E: 5-year fall 5 pp less, 3 months less under water, but 5-year return 3 pp lower
    out = _assemble(_table(130), 130)
    tests = out["pass_fail"]
    assert tests["P1"]["label"] == S.INCONCLUSIVE  # the return condition fails
    assert tests["P1"]["return_lower_95"] == pytest.approx(-0.03, abs=1e-12)
    assert tests["P1"]["return_condition"] is False
    assert tests["P2"]["label"] == S.INCONCLUSIVE
    assert tests["P2"]["difference"] == 3.0  # exactly at the bar
    assert tests["P3"]["label"] == S.LEAD and tests["P4"]["label"] == S.LEAD
    assert tests["P3"]["interval_98_75"] == pytest.approx([0.05, 0.05], abs=1e-12)
    assert tests["P3"]["return_lower_95"] == pytest.approx(0.03, abs=1e-12)
    assert out["decision"]["rule"] == "1"
    assert out["decision"]["leads"] == ["P3", "P4"]


def test_pass_fail_below_the_bars():
    e = {"ret_5y": 0.39, "fall_5y": 0.341, "under_water_5y": 9.1, "dd_1y": 0.191,
         "ret_1y": 0.05, "mu": 0.07}  # fmt: skip
    out = _assemble(_table(130, e), 130)
    assert [t["label"] for t in out["pass_fail"].values()] == [S.NO] * 4
    assert out["decision"] == {"rule": "3", "label": S.RULES["3"], "leads": []}


@pytest.mark.parametrize(("five", "label"), [(119, S.INCONCLUSIVE), (120, S.LEAD)])
def test_five_year_tests_need_120_usable_start_months(five, label):
    out = _assemble(_table(130, {"ret_5y": 0.39}, five_months=five), 130)
    for key in ("P1", "P2"):
        assert out["pass_fail"][key]["start_months"] == five
        assert out["pass_fail"][key]["label"] == label
    assert out["mixes"][S.E]["return_1y"]["start_months"] == 130


def test_the_pass_fail_interval_is_98_75_percent_with_the_outcomes_block():
    k = 130
    table = _table(k, {"ret_5y": 0.39})
    rng = np.random.default_rng(11)
    noise = rng.normal(0.0, 0.01, size=k)
    for o, month in enumerate(month_labels(k)):
        table.loc[(table["mix"] == S.E) & (table["month"] == month), "fall_5y"] = 0.30 + noise[o]
    out = _assemble(table, k)
    diff = np.array([0.05 - noise[o] for o in range(k)])  # equal in every setting of a month
    for block, level, got in (
        (60, 0.9875, out["pass_fail"]["P1"]["interval_98_75"]),
        (60, 0.95, out["mixes"][S.E]["fall_5y"]["interval_95"]),
    ):
        index = evidence.resample_index(k, block, 50, evidence.BOOTSTRAP_SEED)
        tail = 50.0 * (1.0 - level)
        want = np.percentile(diff[index].mean(axis=1), [tail, 100.0 - tail])
        assert got == pytest.approx(want.tolist(), abs=1e-12)
    index = evidence.resample_index(k, 24, 50, evidence.BOOTSTRAP_SEED)
    lower = np.percentile(np.full(k, 0.03)[index].mean(axis=1), 5.0)
    assert out["mixes"][S.E]["return_1y"]["lower_95"] == pytest.approx(lower, abs=1e-12)


@pytest.mark.parametrize(
    ("labels", "rule"),
    [
        ((S.LEAD, S.NO, S.NO, S.NO), "1"),
        ((S.NO, S.INCONCLUSIVE, S.LEAD, S.NO), "1"),
        ((S.NO, S.INCONCLUSIVE, S.NO, S.NO), "2"),
        ((S.INCONCLUSIVE,) * 4, "2"),
        ((S.NO,) * 4, "3"),
    ],
)
def test_decision_rules(labels, rule):
    got = S.decide(dict(zip(("P1", "P2", "P3", "P4"), labels, strict=True)))
    assert got["rule"] == rule and got["label"] == S.RULES[rule]
    assert got["leads"] == [k for k, v in zip(("P1", "P2", "P3", "P4"), labels, strict=True)
                            if v == S.LEAD]  # fmt: skip


# ------------------------------------------------------------------- end to end, one job

# Per risk setting j (r_j = 0.05 + 0.02 j): F_j = [a_j, 1 - a_j] with a_j = 0.3 + 0.1 j and model
# return 0.04 + 0.01 j; every other arm holds `SHIFT[arm]` less of fund 0, with its own model
# return and risk. The pool repeats the region check's test pool: F_j on the line and S_j =
# [a_j - 0.03, ...] below it with the higher ENB, so the region ENB pick is S_j, and the left tip
# is half way to F_{j-1}: [a_j - 0.05, ...]. Fund 0 rises, crashes and recovers every year.

SHIFT = {C.FRONTIER: 0.0, C.U1_ARM: 0.02, C.MIN_TDD: 0.04, C.CRASH_PENALTY: 0.06,
         C.MAX_ENLC: 0.08, C.ENB_KNEE: 0.10}  # fmt: skip


def _r(j: int) -> float:
    return 0.05 + 0.02 * j


def _a(j: int) -> float:
    return 0.3 + 0.1 * j


def _mu(j: int) -> float:
    return 0.04 + 0.01 * j


def _values(**kw) -> np.ndarray:
    v = np.zeros(len(FIELDS))
    for name, value in kw.items():
        v[FIELDS.index(name)] = value
    return v


def _pool() -> PoolBuffer:
    buf = PoolBuffer()
    for j, rf in enumerate(C.RISK_FRACTIONS):
        common = {"lookback": "3y", "r_fraction": rf, "r": _r(j), "start": -1, "call": -1,
                  "lam": None, "source": "search"}  # fmt: skip
        buf.add(**common, arm=C.FRONTIER, weights=np.array([_a(j), 1.0 - _a(j)]),
                values=_values(sigma=_r(j), mu=_mu(j), in_wide=1.0, tdd=0.3, enb=1.0,
                               h=0.3))  # fmt: skip
        buf.add(**common, arm=C.MIN_TDD, weights=np.array([_a(j) - 0.03, 1.03 - _a(j)]),
                values=_values(sigma=0.9 * _r(j), mu=_mu(j) - 0.004, in_wide=0.0, tdd=0.2,
                               enb=1.2, h=0.25))  # fmt: skip
    return buf


def _selections(month: str) -> pd.DataFrame:
    rows = []
    for j, rf in enumerate(C.RISK_FRACTIONS):
        for arm, shift in SHIFT.items():
            native = arm in (C.FRONTIER, C.ENB_KNEE)
            rows.append(
                {"sel_id": f"{month}|{rf}|{arm}", "kind": "main", "menu": MENU, "month": month,
                 "origin": origin_of(month).date(), "engine": ENGINE, "lookback": "3y",
                 "lam": C.LAMBDA if arm == C.CRASH_PENALTY else None, "r_fraction": rf,
                 "r": _r(j), "arm": arm, "pooled": not native,
                 "weights": [_a(j) - shift, 1.0 - _a(j) + shift], "status": C.OK,
                 "sigma": _r(j) * (1.0 - shift), "mu": _mu(j) - shift / 10.0, "enb": 1.0}
            )  # fmt: skip
        # arm 2's own program row: not the locked (pooled) selection, never read
        rows.append({**rows[-5], "sel_id": f"{month}|{rf}|U1-native", "pooled": False,
                     "weights": [1.0, 0.0]})  # fmt: skip
    return pd.DataFrame(rows)


def _write(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_table(table.replace_schema_metadata({DIGEST_KEY: DIGEST.encode()}), path)


def _job(tmp_path: Path, months: list[str], record: bool = True) -> Path:
    job = tmp_path / "run" / "research2003_replay"
    tasks = job / "tasks"
    for month in months:
        base = f"{MENU}_{month}_{ENGINE}"
        _write(tasks / f"{base}.parquet", _selections(month))
        _write(tasks / "columns" / f"{base}.parquet", pd.DataFrame({"month": [month]}))
        _write(tasks / "evaluated" / f"{base}.parquet", pd.DataFrame({"sel_id": ["x"]}))
        table = _pool().table(menu=MENU, month=month, origin=origin_of(month).date(),
                              engine=ENGINE, seed=C.PRIMARY_SEED)  # fmt: skip
        write_pool(tasks / "pool" / f"{base}.parquet", table, {DIGEST_KEY: DIGEST.encode()})
    if record:
        analysis = tmp_path / "run" / "analysis" / "analysis.json"
        analysis.parent.mkdir(parents=True)
        analysis.write_text("{}")
        ENS.record_analysis(job, analysis)
    return job


def _returns(n: int = N5) -> np.ndarray:
    year = np.r_[np.full(100, 0.002), np.full(30, -0.01), np.full(122, 0.001)]
    return np.column_stack([np.tile(year, 5)[:n], np.full(n, 0.0001)])


def _callables(lengths: Mapping[str, int]):
    """The horizon and span of each start month, with `lengths[month]` sessions recorded; the
    span hands back what exists, which may be fewer sessions than asked for."""

    def horizon(menu, month):
        n = lengths.get(month, 0)
        if n < R.HORIZON_DAYS:
            return None
        return _bdays(R.HORIZON_DAYS, month), _returns()[: R.HORIZON_DAYS], ("F0", "F1")

    def span(menu, month, n_days):
        n = min(lengths.get(month, 0), n_days)
        if n == 0:
            return None
        return _bdays(n, month), _returns()[:n]

    return horizon, span


def _parent(months, eligible):
    return {"digest": DIGEST, "menus": {MENU: {"schedule": months, "cscv": {"months": eligible}}}}


def _direct(a: float, month: str, n: int) -> tuple[float, float]:
    out = R.monthly_rebalanced(_returns(n), _bdays(n, month), [[a, 1.0 - a]])
    return float(out.annual[0]), float(out.drawdown[0])


def test_the_mixes_of_a_month(tmp_path):
    month = "2010-03"
    job = _job(tmp_path, [month], record=False)
    pool = G.read_month_pool(job / "tasks" / "pool" / f"{MENU}_{month}_{ENGINE}.parquet")
    mixes = S.month_mixes(pool, A.locked_rows(_selections(month)), month)
    by = {(m["rf"], m["mix"]): m for m in mixes}
    assert len(mixes) == 6 * 7 + 5  # six arms and the ENB pick per setting, L above 0.10
    for j, rf in enumerate(A.RFS):
        for name, arm in S.ARMS.items():
            assert by[(rf, name)]["weights"] == pytest.approx(
                [_a(j) - SHIFT[arm], 1.0 - _a(j) + SHIFT[arm]]
            )
            assert by[(rf, name)]["mu"] == pytest.approx(_mu(j) - SHIFT[arm] / 10.0)
        assert by[(rf, S.REGION_ENB)]["weights"] == pytest.approx([_a(j) - 0.03, 1.03 - _a(j)])
        assert by[(rf, S.REGION_ENB)]["mu"] == pytest.approx(_mu(j) - 0.004)
        assert by[(rf, S.REGION_ENB)]["sigma"] == pytest.approx(0.9 * _r(j))
        if j == 0:
            assert (rf, S.L) not in by
            continue
        assert by[(rf, S.L)]["weights"] == pytest.approx([_a(j) - 0.05, 1.05 - _a(j)])
        assert math.isnan(by[(rf, S.L)]["mu"]) and math.isnan(by[(rf, S.L)]["sigma"])


def test_the_enb_pick_and_the_left_tip_are_the_region_checks(tmp_path):
    month = "2010-03"
    job = _job(tmp_path, [month], record=False)
    pool = G.read_month_pool(job / "tasks" / "pool" / f"{MENU}_{month}_{ENGINE}.parquet")
    rows = A.locked_rows(_selections(month))
    horizon, span = _callables({month: N5})
    mixes = S.month_mixes(pool, rows, month)
    cells = S.month_outcomes(mixes, menu=MENU, month=month, origin=origin_of(month).date(),
                             horizon=horizon, span=span).set_index(["rf", "mix"])  # fmt: skip
    frontier = A._frame(rows.loc[(rows["arm"] == C.FRONTIER).to_numpy()])
    picks, _ = G.month_cells(pool, frontier, menu=MENU, month=month, horizon=horizon)
    region = picks.set_index(["rf", "name"])
    for rf in A.RFS:
        pick = region.loc[(rf, G.RULE_NAMES_ID["enb"])]
        assert cells.loc[(rf, S.REGION_ENB), "record"] == pick["record"]
        assert cells.loc[(rf, S.REGION_ENB), "dd_1y"] == pytest.approx(pick["dd"], abs=1e-14)
        assert cells.loc[(rf, S.REGION_ENB), "ret_1y"] == pytest.approx(pick["ret"], abs=1e-14)
        if rf == A.RFS[0]:
            continue
        assert cells.loc[(rf, S.L), "dd_1y"] == pytest.approx(region.loc[(rf, G.L), "dd"],
                                                              abs=1e-14)  # fmt: skip


def test_month_outcomes_leave_out_windows_without_every_session(tmp_path):
    month = "2010-04"
    job = _job(tmp_path, [month], record=False)
    pool = G.read_month_pool(job / "tasks" / "pool" / f"{MENU}_{month}_{ENGINE}.parquet")
    mixes = S.month_mixes(pool, A.locked_rows(_selections(month)), month)
    origin = origin_of(month).date()
    for sessions, has in ((N5, (3, 5)), (N5 - 1, (3,)), (3 * 252, (3,)), (3 * 252 - 1, ())):
        horizon, span = _callables({month: sessions})
        cells = S.month_outcomes(mixes, menu=MENU, month=month, origin=origin, horizon=horizon,
                                 span=span)  # fmt: skip
        assert np.isfinite(cells["ret_1y"]).all()
        for years in (3, 5):
            for col in (f"fall_{years}y", f"under_water_{years}y", f"ret_{years}y"):
                assert bool(np.isfinite(cells[col]).all()) == (years in has), (sessions, col)
                assert bool(np.isfinite(cells[col]).any()) == (years in has), (sessions, col)


def test_month_outcomes_against_direct_computations(tmp_path):
    month = "2010-05"
    job = _job(tmp_path, [month], record=False)
    pool = G.read_month_pool(job / "tasks" / "pool" / f"{MENU}_{month}_{ENGINE}.parquet")
    sel = _selections(month)
    horizon, span = _callables({month: N5})
    cells = S.month_outcomes(S.month_mixes(pool, A.locked_rows(sel), month), menu=MENU,
                             month=month, origin=origin_of(month).date(), horizon=horizon,
                             span=span).set_index(["rf", "mix"])  # fmt: skip
    analysed = A.realized_outcomes(sel, horizon, span=span).set_index("sel_id")
    for j, rf in enumerate(A.RFS):
        for name, arm in S.ARMS.items():
            a = _a(j) - SHIFT[arm]
            cell = cells.loc[(rf, name)]
            row = analysed.loc[f"{month}|{rf}|{arm}"]
            assert cell["ret_1y"] == pytest.approx(row["ret_m"], abs=1e-14)
            assert cell["dd_1y"] == pytest.approx(row["dd_m"], abs=1e-14)
            assert cell["vol_1y"] == pytest.approx(row["vol_m"], abs=1e-14)
            assert cell["ret_3y"] == pytest.approx(row["ret_3y"], abs=1e-14)
            assert cell["ret_5y"] == pytest.approx(row["ret_5y"], abs=1e-14)
            for years in (3, 5):
                ret, dd = _direct(a, month, years * 252)
                assert cell[f"ret_{years}y"] == pytest.approx(ret, abs=1e-14)
                assert cell[f"fall_{years}y"] == pytest.approx(dd, abs=1e-14)
                path = S.wealth_path(_returns(years * 252), _bdays(years * 252, month),
                                     [[a, 1.0 - a]])  # fmt: skip
                months_under = S.under_water(path)[0] / 21.0
                assert cell[f"under_water_{years}y"] == pytest.approx(months_under, abs=1e-14)


def test_safety_job_reads_no_outcome_before_the_analysis_digest_is_recorded(tmp_path):
    months = month_labels(2)
    job = _job(tmp_path, months, record=False)

    def never(*args):
        raise AssertionError("a realized outcome was read before the digest was recorded")

    with pytest.raises(ValueError, match="no analysis digest recorded"):
        S.safety_job(job, _parent(months, months), MENU, ENGINE, never, never, bounds=BOUNDS,
                     commit="c0ffee")  # fmt: skip


def test_safety_job_end_to_end(tmp_path):
    months = month_labels(5)
    eligible = months[:4]
    lengths = dict(zip(eligible, (N5, N5, 1000, 300), strict=True))
    job = _job(tmp_path, months)
    horizon, span = _callables(lengths)
    out = S.safety_job(job, _parent(months, eligible), MENU, ENGINE, horizon, span,
                       bounds=BOUNDS, commit="c0ffee", resamples=50)  # fmt: skip
    assert out["label"] == S.EXPLORATORY and out["spec"] == S.SPEC
    assert out["code_commit"] == "c0ffee" and out["parent_digest"] == DIGEST
    assert out["analysis_sha256"] == ENS.sha256_file(tmp_path / "run" / "analysis" /
                                                     "analysis.json")  # fmt: skip
    assert out["months"] == eligible and out["months_restricted"] is False
    assert out["cells"][S.F] == 24 and out["cells"][S.L] == 20
    assert out["cells"][S.REGION_ENB] == 24 and out["domain_removed_rows"] == 0
    e = out["mixes"][S.E]
    assert e["return_1y"]["start_months"] == 4
    assert e["fall_3y"]["start_months"] == 3 and e["fall_5y"]["start_months"] == 2
    assert e["fall_5y"]["cells"] == 12

    def mean(value, months, n):  # equal weight over the settings, then over the start months
        return np.mean([np.mean([value(j, m, n) for j in range(6)]) for m in months])

    def fall(j, m, n):
        return _direct(_a(j), m, n)[1] - _direct(_a(j) - 0.1, m, n)[1]

    def gain(j, m, n):
        return _direct(_a(j) - 0.1, m, n)[0] - _direct(_a(j), m, n)[0]

    assert e["fall_5y"]["difference"] == pytest.approx(mean(fall, eligible[:2], N5), abs=1e-12)
    assert e["return_5y"]["difference"] == pytest.approx(mean(gain, eligible[:2], N5),
                                                         abs=1e-12)  # fmt: skip
    assert e["fall_3y"]["difference"] == pytest.approx(mean(fall, eligible[:3], 756), abs=1e-12)
    surprise_f = mean(lambda j, m, n: abs(_direct(_a(j), m, n)[0] - _mu(j)), eligible, 252)
    surprise_e = mean(lambda j, m, n: abs(_direct(_a(j) - 0.1, m, n)[0] - (_mu(j) - 0.01)),
                      eligible, 252)  # fmt: skip
    assert e["return_surprise"]["mean_F"] == pytest.approx(np.mean(surprise_f), abs=1e-12)
    assert e["return_surprise"]["mean"] == pytest.approx(np.mean(surprise_e), abs=1e-12)
    assert out["p4_model_return"]["mu_F_minus_mu_E"] == pytest.approx(0.01, abs=1e-12)
    assert out["mixes"][S.L]["return_surprise"]["cells"] == 0
    assert out["mixes"][S.L]["fall_3y"]["cells"] == 15
    for key in ("P1", "P2"):
        assert out["pass_fail"][key]["label"] == S.INCONCLUSIVE
        assert out["pass_fail"][key]["reason"] == S.TOO_FEW_MONTHS
    assert out["decision"]["rule"] in ("1", "2")


def test_safety_job_is_deterministic(tmp_path):
    months = month_labels(3)
    job = _job(tmp_path, months)
    horizon, span = _callables(dict.fromkeys(months, N5))
    parent = _parent(months, months)
    first, second = (
        json.dumps(S.safety_job(job, parent, MENU, ENGINE, horizon, span, bounds=BOUNDS,
                                commit="c0ffee", resamples=50), indent=2)
        for _ in range(2)
    )  # fmt: skip
    assert first == second


def test_safety_job_restricted_to_some_months(tmp_path):
    months = month_labels(4)
    job = _job(tmp_path, months)
    horizon, span = _callables(dict.fromkeys(months, N5))
    out = S.safety_job(job, _parent(months, months), MENU, ENGINE, horizon, span,
                       bounds=BOUNDS, commit="c0ffee", months=[months[1]],
                       resamples=50)  # fmt: skip
    assert out["months"] == [months[1]] and out["months_restricted"] is True
    assert out["cells"][S.F] == 6
    with pytest.raises(ValueError, match="not eligible"):
        S.safety_job(job, _parent(months, months[:2]), MENU, ENGINE, horizon, span,
                     bounds=BOUNDS, commit="c0ffee", months=[months[3]])  # fmt: skip


def test_record_safety_adds_its_digest_after_the_analysis(tmp_path):
    job = _job(tmp_path, month_labels(1))
    path = tmp_path / "safety_check.json"
    path.write_text("{}")
    S.record_safety(job, path)
    record = json.loads((job / ENS.RECORD_FILE).read_text())
    assert set(record) == {"analysis", "safety"}
    assert ENS.verified_entry(job, "safety") == path.resolve()
