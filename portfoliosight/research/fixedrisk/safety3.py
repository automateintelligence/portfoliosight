"""The safety-measures check of fixed-risk experiment v3, an exploratory addendum
(docs/plans/2026-11-11-fixed-risk-v3-safety-measures-check.md). EXPLORATORY ONLY: the fourth look
at the same 234 start months; no result here is a finding.

Mixes per cell (an eligible start month and one of the six risk settings; main settings only):

- F (arm 1) and E (arm 6, the app's Optimized point), and arms 2 to 5, each the arm's locked row
  (`analysis3.locked_rows`) with a usable label;
- the region check's ENB pick, rule (0, 1, 0): `region3.rule_picks` over the cell's region
  (`region3.region_positions` of the month's allowed distinct main-pool mixes, as `region3`
  reads them);
- the region check's yardstick L (`region3.left_tip_t`, `region3.left_tip`; none at 0.10).

Outcomes per cell, from each mix's weights at the start month with the monthly-rebalanced
convention of `realized.monthly_rebalanced` without costs (`month_outcomes`): the one-year
return, drawdown and volatility (`realized.realized_table`, as `v3-analyze` computes them); for
H = 3 and 5 years, only when all `H * 252` sessions exist, the maximum drawdown (peak floored at
the start value), the longest time under water (`under_water`, in months of 21 sessions, a run
open at the window end counted to the end) and the compounded return. The surprises are
`|ret_1y - mu|` and `|vol_1y - sigma|` with the mix's model figures; the signed gaps are
`ret_1y - mu` and `vol_1y - sigma`.

Across cells (`assemble`): per mix and outcome, the paired difference against F on the cells both
have, averaged as the region check averages them (the settings of a start month equally, then
the start months), with the moving-block bootstrap over the job's schedule (2,000 resamples, seed
20261201; block 24 for one-year outcomes, 36 for 3-year and 60 for 5-year ones); the worst-years
tail (`tail_level_mean`) is each mix's own mean of its largest 10% (rounded up) one-year drawdowns
or lowest 10% returns per setting, averaged over the settings, recomputed inside each resample.
Then the four pass/fail tests of E against F (`PASS_FAIL`, `pass_fail_label`, two-sided 98.75%
intervals) and the decision (`decide`).
"""

from __future__ import annotations

import json
import math
import os
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from portfoliosight.research import evidence
from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import ensemble3 as ENS
from portfoliosight.research.fixedrisk import realized as R
from portfoliosight.research.fixedrisk import region3 as G

EXPLORATORY = "EXPLORATORY"
SPEC = "docs/plans/2026-11-11-fixed-risk-v3-safety-measures-check.md"
NOTICE = (
    "Exploratory safety-measures check (addendum of 2026-11-11): the fourth look at the same 234 "
    "start months, computed after the v3 result and the region check; no result here is a "
    "finding, and a lead is at most a candidate for one confirmation on the held-out TSP menu."
)
SESSIONS_PER_MONTH = 21
YEARS = (3, 5)
BLOCKS = {1: evidence.BLOCK, 3: 36, 5: 60}  # start months per block, by outcome horizon in years
TAIL_DIVISOR = 10  # the largest (or lowest) 10%, rounded up
LEVEL = 0.95
LOWER_LEVEL = 0.90  # its interval's lower end is the one-sided 95% lower bound
TEST_LEVEL = 0.9875  # four tests, each with a two-sided 98.75% interval
MIN_FIVE_YEAR_MONTHS = 120
FULL_STEM = "safety_check"  # a full run's result: safety_check.json, then safety_check_2.json

F, E = "F", "E"
REGION_ENB = "region_enb"
L = G.L
ARMS = {F: C.FRONTIER, E: C.ENB_KNEE, C.U1_ARM: C.U1_ARM, C.MIN_TDD: C.MIN_TDD,
        C.CRASH_PENALTY: C.CRASH_PENALTY, C.MAX_ENLC: C.MAX_ENLC}  # fmt: skip
MIXES = (*ARMS, REGION_ENB, L)
MIX_NAMES = {
    F: "arm 1, the frontier mix",
    E: "arm 6, the app's Optimized point",
    C.U1_ARM: "arm 2",
    C.MIN_TDD: "arm 3",
    C.CRASH_PENALTY: "arm 4, at the main penalty weight",
    C.MAX_ENLC: "arm 5",
    REGION_ENB: "the region check's ENB pick, rule (0, 1, 0)",
    L: "the region check's yardstick: F moved 50 bp of model return toward the next lower "
    "setting; none at 0.10",
}
ENB_RULE = np.array([next(w for w, name in G.RULE_NAMES.items() if name == "enb")])
CELL_COLUMNS = ("mu", "sigma", "ret_1y", "dd_1y", "vol_1y", "fall_3y", "under_water_3y", "ret_3y",
                "fall_5y", "under_water_5y", "ret_5y")  # fmt: skip

F_MINUS_MIX = "F minus mix"  # positive: the mix fell less, was under water less, surprised less
MIX_MINUS_F = "mix minus F"


@dataclass(frozen=True)
class Outcome:
    """A reported outcome: the cell column it reads, its bootstrap block, the sign of its
    difference against F, whether it is a return (a one-sided lower bound is reported) and, for
    the worst years, which tail ("largest" or "smallest") of the one-year values it averages."""

    column: str
    block: int
    sign: str
    is_return: bool = False
    tail: str | None = None


OUTCOMES: dict[str, Outcome] = {
    "return_1y": Outcome("ret_1y", BLOCKS[1], MIX_MINUS_F, is_return=True),
    "return_3y": Outcome("ret_3y", BLOCKS[3], MIX_MINUS_F, is_return=True),
    "return_5y": Outcome("ret_5y", BLOCKS[5], MIX_MINUS_F, is_return=True),
    "fall_3y": Outcome("fall_3y", BLOCKS[3], F_MINUS_MIX),
    "fall_5y": Outcome("fall_5y", BLOCKS[5], F_MINUS_MIX),
    "under_water_3y": Outcome("under_water_3y", BLOCKS[3], F_MINUS_MIX),
    "under_water_5y": Outcome("under_water_5y", BLOCKS[5], F_MINUS_MIX),
    "return_surprise": Outcome("return_surprise", BLOCKS[1], F_MINUS_MIX),
    "volatility_surprise": Outcome("volatility_surprise", BLOCKS[1], F_MINUS_MIX),
    "return_gap": Outcome("return_gap", BLOCKS[1], MIX_MINUS_F),
    "volatility_gap": Outcome("volatility_gap", BLOCKS[1], MIX_MINUS_F),
    "tail_fall": Outcome("dd_1y", BLOCKS[1], F_MINUS_MIX, tail="largest"),
    "tail_return": Outcome("ret_1y", BLOCKS[1], MIX_MINUS_F, is_return=True, tail="smallest"),
}


@dataclass(frozen=True)
class PassFail:
    """A pass/fail test of E against F: the outcome and its bar, the return outcome whose
    one-sided 95% lower bound must reach `return_line`, and the minimum of usable start months."""

    outcome: str
    bar: float
    return_outcome: str
    return_line: float
    min_months: int | None


PASS_FAIL: dict[str, PassFail] = {
    "P1": PassFail("fall_5y", 0.010, "return_5y", -0.025, MIN_FIVE_YEAR_MONTHS),
    "P2": PassFail("under_water_5y", 3.0, "return_5y", -0.025, MIN_FIVE_YEAR_MONTHS),
    "P3": PassFail("tail_fall", 0.010, "return_1y", -0.005, None),
    "P4": PassFail("return_surprise", 0.005, "return_1y", -0.005, None),
}
LEAD, INCONCLUSIVE, NO = "lead", "inconclusive", "no"
TOO_FEW_MONTHS = f"fewer than {MIN_FIVE_YEAR_MONTHS} usable start months"
NO_CELLS = "no paired cells"
BELOW_BAR = "the difference is below the bar"
INTERVAL_ZERO = "the 98.75% interval includes 0"
RETURN_FAILS = "the return condition fails"
REACHED = "the difference reaches the bar, its interval is above 0 and the return condition holds"
RULES = {
    "1": "At least one lead: still not a finding. That measure alone becomes a candidate for one "
    "confirmation on the held-out TSP menu, which needs a new run. The owner decides.",
    "2": "No lead and at least one inconclusive: closed as not provable with this history. No "
    "further experiment on these start months.",
    "3": 'All four "no": closed. A more diversified mix gave no protection on these measures '
    "either.",
}
INTERPRETATIONS = (
    "Every mix's mean and its difference against F use the cells where both have the outcome; "
    "`mean_F` is F on those cells, and F's own entry uses every cell F has.",
    "Usable start months of a test are the start months with at least one cell where E and F "
    "both have the test's outcome.",
    "The worst-years tail is taken per risk setting over the start months both mixes have, then "
    "averaged over the settings that have any (five for L).",
    "L has no recorded model return or risk, so its surprises and signed gaps are empty.",
    "The signed gaps are realized minus model; their difference against F is mix minus F.",
    "A 98.75% interval whose lower end is exactly 0 includes 0.",
    "A test without any paired cell is labelled inconclusive.",
    "The bootstrap index is the job's whole schedule, as in the region check; each block length "
    "draws its own resamples from seed 20261201.",
    "Time under water is in months of 21 sessions, not rounded.",
)


# ------------------------------------------------------------------------ one wealth path


def under_water(wealth: Any) -> np.ndarray:
    """Per mix (column of a sessions x mixes array), the longest run of consecutive sessions on
    which wealth is below its running peak, the peak floored at the start value 1; a run still
    open at the last session counts to the end."""
    w = np.asarray(wealth, dtype=float)
    w = w[:, None] if w.ndim == 1 else w
    below = w < np.maximum(np.maximum.accumulate(w, axis=0), 1.0)
    run = np.zeros(w.shape[1], dtype=np.int64)
    longest = np.zeros(w.shape[1], dtype=np.int64)
    for row in below:
        run = np.where(row, run + 1, 0)
        longest = np.maximum(longest, run)
    return longest


def wealth_path(daily: Any, days: Sequence[Any], weights: Any) -> np.ndarray:
    """The sessions x mixes wealth from 1 of `realized.monthly_rebalanced` without costs: funded
    at the target weights, rebalanced to them at the close of the last session of each calendar
    month strictly inside the window, no liquidation at its end."""
    returns = np.asarray(daily, dtype=float)
    t_len = len(returns)
    if t_len != len(days):
        raise ValueError("days and returns differ in length")
    mixes = np.atleast_2d(np.asarray(weights, dtype=float))
    if mixes.shape[1] != returns.shape[1]:
        raise ValueError(f"weights have {mixes.shape[1]} holdings, returns have {returns.shape[1]}")
    holdings = mixes.copy()
    wealth = np.empty((t_len, len(mixes)))
    start = 0
    for end in [*R.rebalance_positions(days).tolist(), t_len - 1]:
        grown = np.cumprod(1.0 + returns[start : end + 1], axis=0)
        wealth[start : end + 1] = grown @ holdings.T
        if end < t_len - 1:
            value = (holdings * grown[-1]).sum(axis=1)
            wealth[end] = value
            holdings = mixes * value[:, None]
        start = end + 1
    return wealth


def window_outcomes(daily: Any, days: Sequence[Any], weights: Any) -> dict[str, np.ndarray]:
    """Per mix over the whole window: the compounded return and maximum drawdown of
    `realized.monthly_rebalanced` without costs, and the longest time under water in months."""
    out = R.monthly_rebalanced(daily, days, weights)
    months = under_water(wealth_path(daily, days, weights)) / SESSIONS_PER_MONTH
    return {"return": out.annual, "fall": out.drawdown, "under_water": months}


# --------------------------------------------------------------------------- worst years


def tail_size(n: Any) -> Any:
    """Ten percent of `n`, rounded up (at least 1), in integer arithmetic."""
    count = np.asarray(n, dtype=np.int64)
    return np.maximum(-(-count // TAIL_DIVISOR), 1)


def tail_mean(x: Any, index: np.ndarray, *, largest: bool) -> np.ndarray:
    """Per resample (row of `index` into the K-vector `x`), the mean of the largest (or lowest)
    10% of its finite values, rounded up, a repeated value counted each time; NaN when none."""
    sign = -1.0 if largest else 1.0
    ordered = np.sort(sign * np.asarray(x, dtype=float)[index], axis=1)  # NaN sorts last
    finite = np.isfinite(ordered)
    n = finite.sum(axis=1)
    k = tail_size(n)
    sums = np.cumsum(np.where(finite, ordered, 0.0), axis=1)
    rows = np.arange(ordered.shape[0])
    return np.where(n > 0, sign * sums[rows, k - 1] / k, np.nan)


def tail_level_mean(grid: Any, index: np.ndarray, *, largest: bool) -> np.ndarray:
    """`tail_mean` of each risk setting (row of a levels x K grid), averaged over the settings
    that have a value, per resample."""
    rows = np.asarray(grid, dtype=float)
    per_level = np.vstack([tail_mean(row, index, largest=largest) for row in rows])
    return evidence._masked_mean(per_level, axis=0)


# ------------------------------------------------------------------------- one start month


def _float(value: Any) -> float:
    return math.nan if value is None else float(value)


def month_mixes(pool: pd.DataFrame, rows: pd.DataFrame, month: str) -> list[dict[str, Any]]:
    """The mixes of one start month, per risk setting: the six arms' locked rows (`rows`, from
    `analysis3.locked_rows`, with a usable label), L and the region check's ENB pick. `pool`
    holds the month's allowed main-pool rows, read as `region3.region_job` reads them. Each mix
    has its `weights`, model `mu` and `sigma` (NaN for L) and pool `record` (-1 unless a pool
    mix)."""
    keep = (rows["month"].astype(str) == month).to_numpy() & rows["status"].isin(
        C.V3_USABLE
    ).to_numpy()
    sel = A._frame(rows.loc[keep])
    by = {(str(r["arm"]), round(float(r["r_fraction"]), 6)): r for r in sel.to_dict("records")}
    mixes = G.distinct_mixes(pool)
    model = {name: mixes[name].to_numpy(dtype=float) for name in G.MODEL}
    out: list[dict[str, Any]] = []
    for j, rf in enumerate(A.RFS):
        for name, arm in ARMS.items():
            row = by.get((arm, rf))
            w = None if row is None else G._weights(row)
            if row is None or w is None:
                continue
            mu, sigma = _float(row.get("mu")), _float(row.get("sigma"))
            out.append({"rf": rf, "mix": name, "record": -1, "weights": w, "mu": mu,
                        "sigma": sigma})  # fmt: skip
        f = by.get((C.FRONTIER, rf))
        w_f = None if f is None else G._weights(f)
        if f is None or w_f is None:
            continue
        mu_f = float(f["mu"])
        lower = by.get((C.FRONTIER, A.RFS[j - 1])) if j else None
        w_lower = None if lower is None else G._weights(lower)
        if lower is not None and w_lower is not None:
            t = G.left_tip_t(mu_f, float(lower["mu"]))
            out.append({"rf": rf, "mix": L, "record": -1, "weights": G.left_tip(w_f, w_lower, t),
                        "mu": math.nan, "sigma": math.nan})  # fmt: skip
        region = G.region_positions(mixes, mu_f, float(f["r"]))
        if len(region):
            g = G.rule_picks(model["tdd"][region], model["enb"][region], model["h"][region],
                             model["mu"][region], ENB_RULE)[0]  # fmt: skip
            p = int(region[g])
            out.append({"rf": rf, "mix": REGION_ENB, "record": int(mixes.at[p, "record"]),
                        "weights": np.asarray(mixes.at[p, "weights"], dtype=float),
                        "mu": float(model["mu"][p]),
                        "sigma": float(model["sigma"][p])})  # fmt: skip
    return out


def month_outcomes(
    mixes: Sequence[Mapping[str, Any]],
    *,
    menu: str,
    month: str,
    origin: Any,
    horizon: R.HorizonFn,
    span: R.SpanFn,
) -> pd.DataFrame:
    """One row per mix of `month_mixes` (month, rf, mix, record and `CELL_COLUMNS`): the
    one-year outcomes of `realized.realized_table` and, when the span holds all `H * 252`
    sessions, the H-year fall, time under water (months) and compounded return."""
    columns = ["month", "rf", "mix", "record", *CELL_COLUMNS]
    if not mixes:
        return pd.DataFrame(columns=columns)
    weights = np.vstack([np.asarray(m["weights"], dtype=float) for m in mixes])
    frame = pd.DataFrame(
        {"sel_id": [str(i) for i in range(len(mixes))], "menu": menu, "month": month,
         "origin": [origin] * len(mixes), "weights": [list(w) for w in weights]}
    )  # fmt: skip
    one = R.realized_table(frame, horizon, multi_years=())
    out = pd.DataFrame(
        {
            "month": month,
            "rf": [float(m["rf"]) for m in mixes],
            "mix": [str(m["mix"]) for m in mixes],
            "record": [int(m["record"]) for m in mixes],
            "mu": [float(m["mu"]) for m in mixes],
            "sigma": [float(m["sigma"]) for m in mixes],
            "ret_1y": one["ret_m"].to_numpy(dtype=float),
            "dd_1y": one["dd_m"].to_numpy(dtype=float),
            "vol_1y": one["vol_m"].to_numpy(dtype=float),
        }
    )
    for years in YEARS:
        need = years * R.HORIZON_DAYS
        got = {k: np.full(len(mixes), np.nan) for k in ("fall", "under_water", "return")}
        sp = span(menu, month, need)
        if sp is not None and len(sp[0]) >= need:
            values = np.asarray(sp[1], dtype=float)[:need]
            got = window_outcomes(values, list(sp[0])[:need], weights)
        out[f"fall_{years}y"] = got["fall"]
        out[f"under_water_{years}y"] = got["under_water"]
        out[f"ret_{years}y"] = got["return"]
    return A._frame(out[columns])


# --------------------------------------------------------------------------- across months


def with_surprises(cells: pd.DataFrame) -> pd.DataFrame:
    """`cells` with the signed gaps (realized minus model) and the surprises (their sizes)."""
    out = cells.copy()

    def col(name: str) -> np.ndarray:
        return np.asarray(pd.to_numeric(out[name], errors="coerce"), dtype=float)

    out["return_gap"] = col("ret_1y") - col("mu")
    out["volatility_gap"] = col("vol_1y") - col("sigma")
    out["return_surprise"] = np.abs(out["return_gap"].to_numpy(dtype=float))
    out["volatility_surprise"] = np.abs(out["volatility_gap"].to_numpy(dtype=float))
    return out


def _level_statistic(outcome: Outcome, grid: np.ndarray) -> evidence.Statistic:
    """The statistic of one mix's (levels x K) grid: the start-month mean of the settings' mean,
    or the settings' mean of the tail means."""
    if outcome.tail is None:
        return lambda index: evidence.origin_mean(grid, index)
    largest = outcome.tail == "largest"
    return lambda index: tail_level_mean(grid, index, largest=largest)


@dataclass(frozen=True)
class Paired:
    """A mix against F on the cells both have: the two statistics, the difference statistic
    (signed as the outcome says), the paired cells and their start months."""

    mix: evidence.Statistic
    ref: evidence.Statistic
    difference: evidence.Statistic
    cells: int
    months: int
    mask: np.ndarray


def paired(outcome: Outcome, ref: np.ndarray, grid: np.ndarray) -> Paired:
    """A mix's (levels x K) grid of `outcome` against F's (`ref`) on the cells both have."""
    ok = np.isfinite(ref) & np.isfinite(grid)
    f = np.where(ok, ref, np.nan)
    m = np.where(ok, grid, np.nan)
    sign = 1.0 if outcome.sign == MIX_MINUS_F else -1.0
    mix, base = _level_statistic(outcome, m), _level_statistic(outcome, f)
    if outcome.tail is None:
        d = np.where(ok, sign * (m - f), np.nan)

        def difference(index: np.ndarray) -> np.ndarray:
            return evidence.origin_mean(d, index)
    else:

        def difference(index: np.ndarray) -> np.ndarray:
            return sign * (mix(index) - base(index))

    months = evidence._count(np.where(ok, 0.0, np.nan))
    return Paired(mix, base, difference, int(ok.sum()), months, ok)


def compare(
    boot: evidence.Bootstrap, outcome: Outcome, ref: np.ndarray, grid: np.ndarray
) -> dict[str, Any]:
    """A mix's mean, F's mean and their difference with its two-sided 95% interval (and, for a
    return, its one-sided 95% lower bound) over the cells both have."""
    p = paired(outcome, ref, grid)
    block = boot.blocks[0]
    e = boot.estimate(p.difference, LEVEL, p.months)
    entry: dict[str, Any] = {
        "mean": evidence._point(p.mix, boot.n),
        "mean_F": evidence._point(p.ref, boot.n),
        "difference": e.value,
        "interval_95": list(e.intervals[block]),
        "start_months": p.months,
        "cells": p.cells,
    }
    if outcome.is_return:
        entry["lower_95"] = boot.estimate(p.difference, LOWER_LEVEL, p.months).lower(block)
    return entry


def describe(boot: evidence.Bootstrap, outcome: Outcome, grid: np.ndarray) -> dict[str, Any]:
    """F's own mean over every cell it has."""
    return {"mean": evidence._point(_level_statistic(outcome, grid), boot.n),
            "start_months": evidence._count(grid),
            "cells": int(np.isfinite(grid).sum())}  # fmt: skip


def pass_fail_label(
    difference: float | None,
    interval: Sequence[float | None],
    return_lower: float | None,
    *,
    bar: float,
    return_line: float,
    months: int,
    min_months: int | None,
) -> dict[str, str]:
    """The spec's label of one test: lead, inconclusive or no, and why."""
    if min_months is not None and months < min_months:
        return {"label": INCONCLUSIVE, "reason": TOO_FEW_MONTHS}
    if difference is None:
        return {"label": INCONCLUSIVE, "reason": NO_CELLS}
    if difference < bar:
        return {"label": NO, "reason": BELOW_BAR}
    low = interval[0]
    if low is None or low <= 0.0:
        return {"label": INCONCLUSIVE, "reason": INTERVAL_ZERO}
    if return_lower is None or return_lower < return_line:
        return {"label": INCONCLUSIVE, "reason": RETURN_FAILS}
    return {"label": LEAD, "reason": REACHED}


def decide(labels: Mapping[str, str]) -> dict[str, Any]:
    """The decision rules fixed in the spec, from the four tests' labels."""
    leads = [k for k, v in labels.items() if v == LEAD]
    if leads:
        rule = "1"
    elif any(v == INCONCLUSIVE for v in labels.values()):
        rule = "2"
    else:
        rule = "3"
    return {"rule": rule, "label": RULES[rule], "leads": leads}


def assemble(
    cells: pd.DataFrame,
    months: Sequence[str],
    *,
    resamples: int = evidence.RESAMPLES,
    seed: int = evidence.BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Every mix's outcomes against F, the four tests and the decision over the (levels x
    months) cells of `cells` (month, rf, mix and `CELL_COLUMNS`); `months` is the chronological
    index of the bootstrap."""
    months = [str(m) for m in months]
    boots = {b: evidence.Bootstrap(len(months), blocks=(b,), resamples=resamples, seed=seed)
             for b in sorted({o.block for o in OUTCOMES.values()})}  # fmt: skip
    frame = with_surprises(cells) if len(cells) else cells
    names = sorted({o.column for o in OUTCOMES.values()} | {"mu"})

    def grid(mix: str, column: str) -> np.ndarray:
        if not len(frame):
            return np.full((len(A.RFS), len(months)), np.nan)
        return G._grid(A._frame(frame.loc[(frame["mix"] == mix).to_numpy()]), column, months)

    grids = {mix: {c: grid(mix, c) for c in names} for mix in MIXES}
    table: dict[str, Any] = {}
    for mix in MIXES:
        entry = {}
        for name, o in OUTCOMES.items():
            if mix == F:
                entry[name] = describe(boots[o.block], o, grids[F][o.column])
            else:
                entry[name] = compare(boots[o.block], o, grids[F][o.column], grids[mix][o.column])
        table[mix] = entry

    tests: dict[str, Any] = {}
    for key, test in PASS_FAIL.items():
        o = OUTCOMES[test.outcome]
        p = paired(o, grids[F][o.column], grids[E][o.column])
        e = boots[o.block].estimate(p.difference, TEST_LEVEL, p.months)
        interval = e.intervals[o.block]
        ret = table[E][test.return_outcome]["lower_95"]
        verdict = pass_fail_label(e.value, interval, ret, bar=test.bar,
                                  return_line=test.return_line, months=p.months,
                                  min_months=test.min_months)  # fmt: skip
        tests[key] = {
            "outcome": test.outcome,
            "bar": test.bar,
            "difference": e.value,
            "interval_98_75": list(interval),
            "start_months": p.months,
            "cells": p.cells,
            "min_start_months": test.min_months,
            "return_outcome": test.return_outcome,
            "return_lower_95": ret,
            "return_line": test.return_line,
            "return_condition": ret is not None and ret >= test.return_line,
            **verdict,
        }

    surprise = paired(OUTCOMES["return_surprise"], grids[F]["return_surprise"],
                      grids[E]["return_surprise"])  # fmt: skip
    mu_f = np.where(surprise.mask, grids[F]["mu"], np.nan)
    mu_e = np.where(surprise.mask, grids[E]["mu"], np.nan)
    n = len(months)
    p4 = {
        "cells": surprise.cells,
        "start_months": surprise.months,
        "mu_F": evidence._point(lambda i: evidence.origin_mean(mu_f, i), n),
        "mu_E": evidence._point(lambda i: evidence.origin_mean(mu_e, i), n),
        "mu_F_minus_mu_E": evidence._point(lambda i: evidence.origin_mean(mu_f - mu_e, i), n),
        "p4_difference": tests["P4"]["difference"],
    }
    return {
        "cells": {mix: int(np.isfinite(grids[mix]["ret_1y"]).sum()) for mix in MIXES},
        "mixes": table,
        "pass_fail": tests,
        "p4_model_return": p4,
        "decision": decide({k: v["label"] for k, v in tests.items()}),
    }


# -------------------------------------------------------------------------------- one job


def record_safety(job_dir: Path, safety_path: Path) -> dict[str, Any]:
    """Add the safety check's SHA-256 to the job's analysis record, after its analysis entry."""
    record = ENS._read_record(job_dir)
    if "analysis" not in record:
        raise ValueError(f"{Path(job_dir) / ENS.RECORD_FILE} has no analysis entry")
    record["safety"] = ENS._entry(safety_path)
    ENS._write_record(job_dir, record)
    return record


def check_output(run_dir: Path, out: Path | None, *, restricted: bool) -> None:
    """A ValueError unless the run may write where it is asked to, checked before anything is
    computed. A full run takes no output path: `write_result` names its file. A run restricted
    to some start months needs one: a new file in an existing folder outside the run directory."""
    if not restricted:
        if out is not None:
            raise ValueError("a full run names its own result file in <run-dir>/analysis; an "
                             "output path is for a run restricted to start months")  # fmt: skip
        return
    if out is None:
        raise ValueError("a run restricted to some start months needs an output path")
    path = Path(out)
    if path.resolve().is_relative_to(Path(run_dir).resolve()):
        raise ValueError(f"{path} is inside the run directory; a restricted run writes outside it")
    if path.exists() or path.is_symlink():
        raise ValueError(f"{path} exists; the safety check replaces no file")
    if not path.parent.is_dir():
        raise ValueError(f"{path.parent} is not an existing folder")


def _publish(folder: Path, text: str) -> Path:
    """Write `text` under the first free name of `folder` (safety_check.json, then
    safety_check_2.json, ...): complete or absent, and never in place of an existing file."""
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{FULL_STEM}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    with tmp.open("x") as handle:
        handle.write(text)
    try:
        number = 1
        while True:
            path = folder / (f"{FULL_STEM}.json" if number == 1 else f"{FULL_STEM}_{number}.json")
            try:
                os.link(tmp, path)  # fails when the name is taken; never replaces
                return path
            except FileExistsError:
                number += 1
    finally:
        tmp.unlink()


def write_result(
    run_dir: Path, job_dir: Path, body: Mapping[str, Any], out: Path | None, *, restricted: bool
) -> Path:
    """Write a run's result and hand back its path; no existing file is replaced. A full run's
    result gets the first free name in `<run-dir>/analysis` and is then recorded
    (`record_safety`), so the record names a file whose bytes never change afterward and an
    earlier recorded result stays as it was. A restricted run's result goes to `out`, created
    exclusively, and is not recorded."""
    check_output(run_dir, out, restricted=restricted)
    text = json.dumps(body, indent=2, default=str) + "\n"
    if restricted:
        assert out is not None
        path = Path(out)
        with path.open("x") as handle:
            handle.write(text)
        return path
    path = _publish(Path(run_dir) / "analysis", text)
    record_safety(job_dir, path)
    return path


def _definitions(resamples: int) -> dict[str, Any]:
    return {
        "mixes": MIX_NAMES,
        "outcomes": {name: asdict(o) for name, o in OUTCOMES.items()},
        "pass_fail": {key: asdict(t) for key, t in PASS_FAIL.items()},
        "sessions_per_year": R.HORIZON_DAYS,
        "sessions_per_month": SESSIONS_PER_MONTH,
        "tail": "the largest 10% (rounded up) of one-year drawdowns, or the lowest 10% of "
        "one-year returns, per risk setting over the start months; then averaged over the "
        "settings",
        "levels": {"interval": LEVEL, "one_sided_lower": 0.95, "pass_fail": TEST_LEVEL},
        "resamples": resamples,
        "seed": evidence.BOOTSTRAP_SEED,
        "convention": "realized.monthly_rebalanced without costs, from the mix's weights",
    }


def safety_job(
    job_dir: Path,
    parent: Mapping[str, Any],
    menu: str,
    engine: str,
    horizon: R.HorizonFn,
    span: R.SpanFn,
    *,
    bounds: tuple[Sequence[float], Sequence[float]],
    commit: str,
    analysis_path: Path | None = None,
    months: Sequence[str] | None = None,
    resamples: int = evidence.RESAMPLES,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """The safety check of one job; refuses to read a realized outcome before the confirmatory
    analysis' digest is recorded (`ensemble3.verified_entry`). `bounds` are the menu's (lower,
    upper) weight bounds in holding order (pool rows outside them are left out and counted, as
    in the region check); `commit` is the running code's commit. `months` restricts the eligible
    start months (a smoke run); the bootstrap index stays the job's schedule."""
    from portfoliosight.research.fixedrisk.driver3 import base_paths

    job_dir = Path(job_dir)
    analysis = ENS.verified_entry(job_dir, "analysis", analysis_path)
    schedule = [str(m) for m in parent["menus"][menu]["schedule"]]
    eligible = set(A.eligible_origins(parent, menu))
    if months is not None:
        unknown = sorted({str(m) for m in months} - eligible)
        if unknown:
            raise ValueError(f"not eligible start months of {menu}: {unknown}")
    wanted = eligible if months is None else {str(m) for m in months}
    chosen = [m for m in schedule if m in wanted]
    tables = A.load_tables(job_dir, parent["digest"])
    rows = A.locked_rows(tables["selections"])
    rows = A._frame(rows.loc[rows["arm"].isin(list(ARMS.values())).to_numpy()])
    parts = []
    removed = 0
    for month in chosen:
        path = base_paths(job_dir / "tasks", f"{menu}_{month}_{engine}")["pool"]
        pool = G.read_month_pool(path)
        allowed = G.in_domain(np.vstack(pool["weights"].to_list()), *bounds) if len(pool) else \
            np.zeros(0, dtype=bool)  # fmt: skip
        removed += int((~allowed).sum())
        pool = A._frame(pool.loc[allowed]).reset_index(drop=True)
        missing = G._undefined(pool)
        if missing:
            raise ValueError(
                f"{month}: {missing} allowed main-pool row(s) lack a model measure "
                "(mu, sigma, tdd, enb or h); the safety check stops"
            )
        here = A._frame(rows.loc[(rows["month"].astype(str) == month).to_numpy()])
        origin = here["origin"].iloc[0] if len(here) else None
        mixes = month_mixes(pool, rows, month)
        part = month_outcomes(mixes, menu=menu, month=month, origin=origin, horizon=horizon,
                              span=span)  # fmt: skip
        parts.append(part)
        if progress is not None:
            progress(f"{month}: {len(pool)} main rows, {len(part)} mixes")
        del pool
    cells = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    body = assemble(cells, schedule, resamples=resamples)
    return {
        "label": EXPLORATORY,
        "notice": NOTICE,
        "spec": SPEC,
        "job": job_dir.name,
        "code_commit": commit,
        "parent_digest": parent["digest"],
        "analysis_sha256": ENS.sha256_file(analysis),
        "months": chosen,
        "months_restricted": months is not None,
        "domain_removed_rows": removed,
        "definitions": _definitions(resamples),
        "interpretations": list(INTERPRETATIONS),
        **body,
    }
