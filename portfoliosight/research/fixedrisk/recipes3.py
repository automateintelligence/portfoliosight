"""The simple and diversification-driven recipes check of fixed-risk experiment v3, an exploratory
addendum (docs/plans/2026-11-11-diversification-vs-simple-mixes.md, "the protocol", built by
docs/plans/2026-11-15-diversification-vs-simple-mixes-build-plan.md). EXPLORATORY ONLY: no result
here is a finding.

Mixes of one start month, all from its training side and its recorded columns alone, never from a
realized outcome:

- F, the frontier mix with the weight limits, at the six risk settings (the recorded rows);
- U, the frontier mix with no weight limits, at the same risk as F;
- E, equal weight; D, the most-diversified mix under the menu's limits; D10, the same with a flat
  10% limit; each with a comparator, the exact-line frontier mix with the limits at the mix's own
  risk (`F@E`, `F@D`, `F@D10`).

This module so far holds the mixes (`most_diversified`, `frontier_exact`, `recorded_columns`,
`month_mixes`), the two pre-registered lists (`E_EXCLUDED`, `U_EXCLUDED`) and the model-side gates
judged before any realized outcome is read (`read_month_pool_dr2`, `month_pool_checks`, `gates`,
`model_side`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cvxpy as cp
import numpy as np
import pandas as pd

from portfoliosight.engine import caps, optimize, torsion
from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import anchors
from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import region3 as G

TOL = optimize.TOL  # 1e-6 in annual volatility and model return (protocol, "Inputs, fixed")
U_TOL = 2e-6  # U's risk match to F's recorded row: both sit on one line within TOL
D10_CAP = 0.10  # D10's flat limit on every holding

# Pre-registered in the protocol from its model-side check ("Cells at or above a frontier's top"):
# the start months whose equal-weight risk is at or above the limited top, and the U cells
# whose risk is at or above the unlimited top. The run must reproduce both (the list gate).
E_EXCLUDED = (
    "2008-11", "2008-12", "2009-01", "2009-02", "2009-03", "2009-04", "2009-05", "2009-06",
    "2009-07", "2009-08", "2009-09", "2009-10", "2009-11", "2009-12", "2010-01", "2010-02",
    "2010-03", "2010-04", "2010-05", "2010-06", "2010-08", "2010-09", "2010-10", "2020-03",
    "2020-05",
)  # fmt: skip
U_EXCLUDED = (("2008-09", 0.85), ("2010-08", 0.85))  # (start month, risk setting)

F, F_ARM1, U, E, D, D10 = "F", "F_arm1", "U", "E", "D", "D10"
COMPARATOR = {U: F, E: "F@E", D: "F@D", D10: "F@D10"}  # the row a mix is paired with
KEPT, EXCLUDED, FAILED = "kept", "excluded", "failed"
RECONSTRUCTION = "reconstruction"  # the reason of an F row whose rebuilt mix differs


def most_diversified(sigma: np.ndarray, cov: np.ndarray, hi) -> np.ndarray:
    """The most-diversified mix under `0 <= w <= hi`, `1'w = 1`: the highest diversification ratio
    `(sigma' w) / sqrt(w' cov w)` (Choueifaty and Coignard 2008).

    The paper's synthetic-asset form, one convex program: minimize `y' cov y` subject to
    `sigma' y = 1`, `y >= 0` and `y_i <= hi_i (1' y)` (the limits are linear in `y`), then
    `w = y / 1'y`. `hi` is one limit for every holding or one per holding. `SolveError` when
    Clarabel finds no optimal answer, as when the limits cannot sum to one.
    """
    sigma = np.asarray(sigma, dtype=float)
    limits = np.broadcast_to(np.asarray(hi, dtype=float), sigma.shape)
    y = cp.Variable(len(sigma))
    problem = cp.Problem(
        cp.Minimize(cp.norm(optimize.cholesky_factor(cov) @ y, 2)),
        [sigma @ y == 1, y >= 0, y <= cp.multiply(limits, cp.sum(y))],
    )
    solved = optimize.solve_with_retries(problem, y, "most-diversified mix")
    return solved / solved.sum()


def at_or_above_top(s: float, sigma_top: float) -> bool:
    """The exclusion rule: a risk `s` within `TOL` of a frontier's top, or above it, has no frontier
    mix to pair with (the last node is the max-return greedy fill)."""
    return s >= sigma_top - TOL


def risk_position(s: float, sigma_min: float, sigma_top: float) -> float:
    """`a = (s - sigma_min) / (sigma_top - sigma_min)`: a risk on the axis of the six settings."""
    return (s - sigma_min) / (sigma_top - sigma_min)


def frontier_exact(
    programs: optimize.MenuPrograms,
    lowest: np.ndarray,
    top: np.ndarray,
    s: float,
    sigma_min: float,
    sigma_top: float,
) -> np.ndarray | None:
    """`F(s)`, the exact-line frontier mix with the limits, at any risk `s`.

    `lowest` (the minimum-variance mix) when `s <= sigma_min + TOL`; `None` when `s` is at or
    above the top (`at_or_above_top`: the cell is excluded); otherwise `programs.frontier_point(s)`,
    moved toward `top` (the greedy fill) with `optimize.onto_risk` when it sits more than `TOL`
    inside the ceiling, so that `|sigma(F) - s| <= TOL`. There is no retry on the risk gap;
    `SolveError` propagates.
    """
    if s <= sigma_min + TOL:
        return lowest
    if at_or_above_top(s, sigma_top):
        return None
    mix = programs.frontier_point(s)
    if s - programs.sigma(mix) > TOL:
        mix = optimize.onto_risk(mix, top, s, programs.cov)
    return mix


# ---------------------------------------------------------------------- the recorded columns


@dataclass(frozen=True)
class Recorded:
    """What the run recorded for one start month at its six risk settings (3-year lookback)."""

    r: np.ndarray  # the six recorded risks, in `analysis3.RFS` order
    sigma_min: float  # risk of the limited minimum-variance mix
    sigma_top: float  # risk of the limited max-return greedy fill
    w_f: np.ndarray  # 6 x N, arm 1's frontier anchor
    w_app: np.ndarray  # 6 x N, the exact-line frontier row (`w_app_frontier`)


def _recorded_weights(value: Any) -> np.ndarray | None:
    if value is None or np.ndim(value) == 0 or np.size(value) == 0:
        return None
    return np.asarray(value, dtype=float)


def recorded_columns(columns: pd.DataFrame, month: str) -> Recorded:
    """The month's rows of the recorded column table with `lookback == C.LOOKBACK`, in
    `analysis3.RFS` order. The table also holds sensitivity (5-year) rows, which are not read.
    `ValueError` unless exactly the six settings are there, each once and with both weights."""
    rows = A._frame(
        columns.loc[(columns["month"].astype(str) == month) & (columns["lookback"] == C.LOOKBACK)]
    ).to_dict("records")
    by_setting: dict[float, list[dict[str, Any]]] = {}
    for row in rows:
        by_setting.setdefault(round(float(row["r_fraction"]), 6), []).append(row)
    if sorted(by_setting) != sorted(A.RFS) or any(len(v) != 1 for v in by_setting.values()):
        raise ValueError(
            f"{month}: the column table must hold each of the settings {A.RFS} exactly once at "
            f"lookback {C.LOOKBACK}; it holds {sorted((k, len(v)) for k, v in by_setting.items())}"
        )
    ordered = [by_setting[rf][0] for rf in A.RFS]
    weights: dict[str, list[np.ndarray]] = {"w_F": [], "w_app_frontier": []}
    for rf, row in zip(A.RFS, ordered, strict=True):
        for name, found in weights.items():
            w = _recorded_weights(row[name])
            if w is None:
                raise ValueError(f"{month}: setting {rf} has no {name}")
            found.append(w)
    first = ordered[0]
    return Recorded(
        r=np.array([float(row["r"]) for row in ordered]),
        sigma_min=float(first["sigma_min"]),
        sigma_top=float(first["sigma_top"]),
        w_f=np.vstack(weights["w_F"]),
        w_app=np.vstack(weights["w_app_frontier"]),
    )


# ------------------------------------------------------------------------------ the mixes

_BLANK: dict[str, Any] = {
    "month": None, "rf": math.nan, "mix": None, "r": math.nan, "comparator": None,
    "status": KEPT, "reason": "", "weights": None, "mu": math.nan, "sigma": math.nan,
    "a": math.nan, "enb": math.nan, "dr2": math.nan, "risk_gap": math.nan, "mu_gap": math.nan,
    "l1": math.nan, "breaks_limit": None, "rebuilt_mu_gap": math.nan,
    "rebuilt_sigma_gap": math.nan, "rebuilt_l1": math.nan, "ends_gap": math.nan,
}  # fmt: skip
LIMITED_FAILED = "the minimum-variance program with the weight limits failed"
UNLIMITED_FAILED = "the minimum-variance program with no weight limits failed"


class _Month:
    """One start month's mixes. The inputs are the training side and the recorded columns; no
    realized outcome is an argument, so none can be read."""

    def __init__(self, month: str, mu_s, cov, lower, upper, rec: Recorded) -> None:
        self.month, self.rec = month, rec
        self.mu = np.asarray(mu_s, dtype=float)
        self.cov = np.asarray(cov, dtype=float)
        self.lower = np.asarray(lower, dtype=float)
        self.upper = np.asarray(upper, dtype=float)
        self.n = len(self.mu)
        self.sigma = np.sqrt(np.diag(self.cov))
        try:
            self.basis: torsion.TorsionBasis | None = torsion.torsion_basis(self.cov)
        except torsion.TorsionError:
            self.basis = None
        self.limited = optimize.MenuPrograms(self.mu, self.cov, self.lower, self.upper)
        self.top = caps.greedy_fill(self.mu, self.lower, self.upper)
        self.lowest = self._solved(self.limited.min_variance)
        self.ends_gap = math.nan
        if self.lowest is not None:
            self.ends_gap = max(
                abs(self.limited.sigma(self.lowest) - rec.sigma_min),
                abs(self.limited.sigma(self.top) - rec.sigma_top),
            )
        zeros, ones = np.zeros(self.n), np.ones(self.n)
        self.unlimited = optimize.MenuPrograms(self.mu, self.cov, zeros, ones)
        self.top_u = caps.greedy_fill(self.mu, zeros, ones)
        self.sigma_top_u = self.unlimited.sigma(self.top_u)
        self.lowest_u = self._solved(self.unlimited.min_variance)
        self.sigma_min_u = (
            self.unlimited.sigma(self.lowest_u) if self.lowest_u is not None else math.nan
        )

    @staticmethod
    def _solved(program: Callable[[], np.ndarray]) -> np.ndarray | None:
        try:
            return program()
        except optimize.SolveError:
            return None

    def row(self, mix: str, w: np.ndarray | None, **fields: Any) -> dict[str, Any]:
        """A row of `mix` at weights `w` (None: not built), with its model figures."""
        out = {**_BLANK, "month": self.month, "mix": mix, "weights": w, **fields}
        if w is not None:
            risk = self.limited.sigma(w)
            out.update(
                mu=float(self.mu @ w),
                sigma=risk,
                a=risk_position(risk, self.rec.sigma_min, self.rec.sigma_top),
                enb=self._enb(w),
                dr2=anchors.dr2(w, self.sigma, self.cov),
            )
        return out

    def _enb(self, w: np.ndarray) -> float:
        if self.basis is None:
            return math.nan
        try:
            return torsion.enb(w, self.cov, self.basis)
        except torsion.TorsionError:
            return math.nan

    def f_rows(self) -> list[dict[str, Any]]:
        rows = []
        for j, rf in enumerate(A.RFS):
            r, w = float(self.rec.r[j]), self.rec.w_app[j]
            row = self.row(F, w, rf=rf, r=r, ends_gap=self.ends_gap)
            if self.lowest is None:
                row.update(status=FAILED, reason=LIMITED_FAILED)
            else:
                row.update(self._reconstruction(r, w))
            rows.append(row)
        return rows

    def _reconstruction(self, r: float, recorded: np.ndarray) -> dict[str, Any]:
        """The rebuilt `F(r)` against the recorded `w_app_frontier` row: model return and risk
        within `TOL`; the weight distance is reported, not gated."""
        assert self.lowest is not None
        try:
            rebuilt = frontier_exact(
                self.limited, self.lowest, self.top, r, self.rec.sigma_min, self.rec.sigma_top
            )
        except optimize.SolveError:
            rebuilt = None
        if rebuilt is None:
            return {"status": FAILED, "reason": RECONSTRUCTION}
        out: dict[str, Any] = {
            "rebuilt_mu_gap": abs(float(self.mu @ rebuilt) - float(self.mu @ recorded)),
            "rebuilt_sigma_gap": abs(self.limited.sigma(rebuilt) - self.limited.sigma(recorded)),
            "rebuilt_l1": float(np.abs(rebuilt - recorded).sum()),
        }
        if out["rebuilt_mu_gap"] > TOL or out["rebuilt_sigma_gap"] > TOL:
            out.update(status=FAILED, reason=RECONSTRUCTION)
        return out

    def arm_one_rows(self) -> list[dict[str, Any]]:
        return [
            self.row(F_ARM1, self.rec.w_f[j], rf=rf, r=float(self.rec.r[j]))
            for j, rf in enumerate(A.RFS)
        ]

    def u_rows(self, f_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for j, rf in enumerate(A.RFS):
            r, f = float(self.rec.r[j]), self.rec.w_app[j]
            cell = {"rf": rf, "r": r, "comparator": F}
            if at_or_above_top(r, self.sigma_top_u):
                reason = "the risk is at or above the top with no weight limits"
                rows.append(self.row(U, None, status=EXCLUDED, reason=reason, **cell))
                continue
            blocked = None
            if self.lowest is None:
                blocked = LIMITED_FAILED
            elif f_rows[j]["status"] == FAILED:
                blocked = "the F row of this setting failed"
            elif self.lowest_u is None:
                blocked = UNLIMITED_FAILED
            if blocked is not None:
                rows.append(self.row(U, None, status=FAILED, reason=blocked, **cell))
                continue
            assert self.lowest_u is not None
            try:
                w = frontier_exact(
                    self.unlimited, self.lowest_u, self.top_u, r, self.sigma_min_u, self.sigma_top_u
                )
            except optimize.SolveError as exc:
                rows.append(self.row(U, None, status=FAILED, reason=f"solver: {exc}", **cell))
                continue
            assert w is not None  # excluded above
            gap = abs(self.limited.sigma(w) - self.limited.sigma(f))
            row = self.row(
                U, w, risk_gap=gap, mu_gap=float(self.mu @ w - self.mu @ f),
                l1=float(np.abs(w - f).sum()),
                breaks_limit=not bool(G.in_domain(w, self.lower, self.upper)[0]), **cell,
            )  # fmt: skip
            if gap > U_TOL:
                row.update(status=FAILED, reason=f"risk gap {gap:.2e} above {U_TOL:.0e}")
            rows.append(row)
        return rows

    def recipe_rows(self) -> list[dict[str, Any]]:
        """E, D and D10, each followed by its comparator `F(sigma(M))` (none when the mix is
        excluded or cannot be solved)."""
        n = self.n
        builds: dict[str, Callable[[], np.ndarray]] = {
            E: lambda: np.full(n, 1.0 / n),
            D: lambda: most_diversified(self.sigma, self.cov, self.upper),
            D10: lambda: most_diversified(self.sigma, self.cov, np.full(n, D10_CAP)),
        }
        rows: list[dict[str, Any]] = []
        for name, build in builds.items():
            comparator = COMPARATOR[name]
            try:
                w = build()
            except optimize.SolveError as exc:
                rows.append(
                    self.row(
                        name, None, status=FAILED, reason=f"solver: {exc}", comparator=comparator
                    )
                )
                continue
            risk = self.limited.sigma(w)
            if at_or_above_top(risk, self.rec.sigma_top):
                reason = "the risk is at or above the top with the weight limits"
                rows.append(
                    self.row(name, w, status=EXCLUDED, reason=reason, comparator=comparator)
                )
                continue
            rows += self._pair(name, comparator, w, risk)
        return rows

    def _pair(self, name: str, comparator: str, w: np.ndarray, risk: float) -> list[dict[str, Any]]:
        mix = self.row(name, w, comparator=comparator)
        if self.lowest is None:
            return _failed_pair(mix, self.row(comparator, None), LIMITED_FAILED)
        try:
            found = frontier_exact(
                self.limited, self.lowest, self.top, risk, self.rec.sigma_min, self.rec.sigma_top
            )
        except optimize.SolveError as exc:
            return _failed_pair(mix, self.row(comparator, None), f"solver: {exc}")
        assert found is not None  # excluded above
        gap = abs(self.limited.sigma(found) - risk)
        mix.update(mu_gap=float(self.mu @ found - self.mu @ w), l1=float(np.abs(found - w).sum()))
        comp = self.row(comparator, found, risk_gap=gap)
        if gap > TOL:
            return _failed_pair(
                mix, comp, f"the comparator's risk gap {gap:.2e} is above {TOL:.0e}"
            )
        return [mix, comp]


def _failed_pair(mix: dict, comp: dict, reason: str) -> list[dict[str, Any]]:
    """A mix and its comparator, both failed: a cell fails when either cannot be built."""
    mix.update(status=FAILED, reason=reason)
    comp.update(status=FAILED, reason=reason)
    return [mix, comp]


def month_mixes(month: str, mu_s, cov, lower, upper, rec: Recorded) -> pd.DataFrame:
    """One start month's mixes, one row per mix and cell, from its training side (`mu_s`, `cov`,
    the weight limits) and the recorded columns (`rec`). F and arm 1 at the six settings (the
    recorded rows; F's rebuilt and gated against them), U at the same risks with no weight limits,
    E, D and D10 each with the frontier mix `F(sigma(M))` at its own risk as comparator. A row has
    `status` kept, excluded or failed, and why; `weights` is None for a mix not built. Columns:
    `month rf mix r comparator status reason weights mu sigma a enb dr2 risk_gap mu_gap l1
    breaks_limit rebuilt_mu_gap rebuilt_sigma_gap rebuilt_l1 ends_gap`."""
    built = _Month(month, mu_s, cov, lower, upper, rec)
    f_rows = built.f_rows()
    rows = [*f_rows, *built.arm_one_rows(), *built.u_rows(f_rows), *built.recipe_rows()]
    return pd.DataFrame(rows, columns=list(_BLANK))


# ------------------------------------------------------------------- the pool, with dr2

POOL_COLUMNS_DR2 = (*G.POOL_COLUMNS, "dr2")


def read_month_pool_dr2(path: Path) -> pd.DataFrame:
    """The rows `region3.read_month_pool` reads (the same path and the same `lookback`, `seed` and
    `lam` filters) with the diversification ratio squared `dr2` as one more column, before any
    domain filter."""
    return G.read_month_pool(path, columns=POOL_COLUMNS_DR2)


def _inside(pool: pd.DataFrame, lower, upper) -> np.ndarray:
    if pool.empty:
        return np.zeros(0, dtype=bool)
    return G.in_domain(np.vstack(pool["weights"].to_list()), lower, upper)


def allowed_mixes(pool: pd.DataFrame, lower, upper) -> pd.DataFrame:
    """The pool's distinct mixes inside the weight limits: `region3.in_domain`, then
    `region3.distinct_mixes` (which carries `dr2` through). `ValueError` when an allowed row lacks
    a model measure or `dr2`: such a row is never left out."""
    allowed = A._frame(pool.loc[_inside(pool, lower, upper)]).reset_index(drop=True)
    missing = int(np.isnan(allowed["dr2"].to_numpy(dtype=float)).sum())
    if missing:
        raise ValueError(f"{missing} allowed main-pool row(s) lack dr2")
    return G.distinct_mixes(allowed)


# ------------------------------------------------------- the pool checks of one start month

POOL_CHECKS = ("pool_dr2_max", "pool_mu_bound", "pool_mu_at_risk", "tie")
REFUTED = "the comparator missed a better recorded mix"
RECIPES = (E, D, D10)


POOL_MEASURES = ("mu", "sigma", "dr2")  # what the pool checks read of every pool row


def _all_finite(values: Iterable[Any]) -> bool:
    """Every value is a finite real number (not a bool, a string or None)."""
    return all(_real_finite(v) for v in values)


def _real_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float, np.integer, np.floating))
        and not isinstance(value, (bool, np.bool_))
        and math.isfinite(value)
    )


def _pool_problems(pool: pd.DataFrame, n: int) -> list[str]:
    """The pool's allow-list, before any domain filter: every row has finite `mu`, `sigma` and
    `dr2` and one vector of `n` finite weights. An empty pool has no problem (plan line 572)."""
    if pool.empty:
        return []
    problems = [
        f"main-pool row(s) lack a finite {name}"
        for name in POOL_MEASURES
        if not _all_finite(pool[name].to_list())
    ]
    try:
        stacked = np.vstack(pool["weights"].to_list()).astype(float)
        weights_ok = stacked.shape == (len(pool), n) and bool(np.isfinite(stacked).all())
    except (TypeError, ValueError):
        weights_ok = False
    if not weights_ok:
        problems.append(f"main-pool row(s) lack {n} finite weights")
    return problems


# ------------------------------------------------------ the allow-list of the model-side rows

STATUSES = (KEPT, EXCLUDED, FAILED)
ONE_PER_SETTING = (F, F_ARM1, U)
KNOWN = (*ONE_PER_SETTING, *RECIPES, *(COMPARATOR[m] for m in RECIPES))
WEIGHT_SUM_TOL = C.FEASIBILITY_TOL  # the budget rule of `region3.in_domain`
# What a row must hold, by status and mix: every row that carries weights (any status), one
# vector of finite weights summing to one and finite `mu`, `sigma` and `dr2`, plus its risk gap
# for U and a comparator; a kept row, or an excluded E, D or D10, carries weights and the
# finite numbers below. The names in `NONNEGATIVE` are distances, never below 0.
_BUILT_FINITE = ("mu", "sigma", "dr2")
_BUILT_GAP = (U, *(COMPARATOR[m] for m in RECIPES))
_KEPT_FINITE = {
    F: ("mu", "sigma", "r", "rebuilt_mu_gap", "rebuilt_sigma_gap"),
    F_ARM1: (),
    U: ("r", "mu", "sigma", "risk_gap", "mu_gap", "l1"),
    **dict.fromkeys(RECIPES, ("mu", "sigma", "a", "dr2", "mu_gap", "l1")),
    **dict.fromkeys((COMPARATOR[m] for m in RECIPES), ("mu", "sigma", "risk_gap")),
}
_EXCLUDED_FINITE = dict.fromkeys(RECIPES, ("sigma", "a", "dr2"))
NONNEGATIVE = ("r", "sigma", "risk_gap", "l1", "rebuilt_mu_gap", "rebuilt_sigma_gap")


def _carries(weights: Any) -> bool:
    """A row carries weights unless its weights cell is None or NaN (a mix not built)."""
    return not (weights is None or (isinstance(weights, float) and math.isnan(weights)))


def _weights_ok(weights: Any, n: int | None) -> bool:
    """One vector of finite weights summing to one within `WEIGHT_SUM_TOL`, of length `n` (any
    length when `n` is None)."""
    try:
        w = np.asarray(weights, dtype=float)
    except (TypeError, ValueError):
        return False
    return (
        w.ndim == 1
        and w.size > 0
        and (n is None or w.size == n)
        and bool(np.isfinite(w).all())
        and abs(math.fsum(w.tolist()) - 1.0) <= WEIGHT_SUM_TOL
    )


def _row_problems(row: Row, n: int | None) -> list[str]:
    """What `row` lacks of what it must hold (the allow-list above)."""
    mix, status = row["mix"], row["status"]
    carries = _carries(row["weights"])
    finite: list[str] = []
    if carries:
        finite += _BUILT_FINITE
        finite += ["risk_gap"] if mix in _BUILT_GAP else []
    needs_weights = status == KEPT or (status == EXCLUDED and mix in RECIPES)
    if status == KEPT:
        finite += _KEPT_FINITE.get(mix, ())
    elif status == EXCLUDED and mix in RECIPES:
        finite += _EXCLUDED_FINITE[mix]
    lacks = []
    if (carries or needs_weights) and not _weights_ok(row["weights"], n):
        lacks.append("weights")
    for name in dict.fromkeys(finite):
        value = row[name]
        if not _real_finite(value) or (name in NONNEGATIVE and value < 0):
            lacks.append(name)
    if mix == U and status == KEPT and not isinstance(row["breaks_limit"], (bool, np.bool_)):
        lacks.append("breaks_limit")
    return lacks


def _on_line(row: Row, tol: float) -> bool:
    gap = row["risk_gap"]
    return _real_finite(gap) and 0 <= gap <= tol


def _pairing(month: str, mix: str, here: list[Row]) -> str | None:
    """A kept mix has one kept comparator on its risk line (within `TOL`); an excluded one has
    none; a failed one has none or a failed one."""
    (row,) = [r for r in here if r["mix"] == mix]
    comps = [r for r in here if r["mix"] == COMPARATOR[mix]]
    statuses = sorted(str(r["status"]) for r in comps)
    allowed = {KEPT: [[KEPT]], EXCLUDED: [[]], FAILED: [[], [FAILED]]}.get(row["status"], [])
    if statuses not in allowed:
        return f"{month}: {mix} {row['status']} with comparator rows {statuses}"
    if row["status"] == KEPT and not _on_line(comps[0], TOL):
        return f"{month}: {mix} kept with its comparator off the risk line"
    return None


def _relationships(month: str, here: list[Row]) -> list[str]:
    """Each mix with its comparator: E, D and D10 at most once, paired (`_pairing`), and no
    comparator without its mix; a kept U with one F row at its setting and on that row's risk
    line within `U_TOL`."""
    problems = []
    for mix in RECIPES:
        count = sum(r["mix"] == mix for r in here)
        if count > 1:
            problems.append(f"{month}: {count} rows of {mix}")
        elif count == 0 and any(r["mix"] == COMPARATOR[mix] for r in here):
            problems.append(f"{month}: {COMPARATOR[mix]} without {mix}")
        elif count == 1 and (paired := _pairing(month, mix, here)):
            problems.append(paired)
    for u in (r for r in here if r["mix"] == U and r["status"] == KEPT):
        f = sum(r["mix"] == F and _rf(r) == _rf(u) for r in here)
        if f != 1 or not _on_line(u, U_TOL):
            problems.append(f"{month}: U {_rf(u)} kept with {f} F row(s) or off the risk line")
    return problems


def _width(month: str, here: list[Row], problems: list[str]) -> int | None:
    """The one length of the month's weight vectors; None, and a problem, when they differ."""
    lengths = sorted({int(np.size(r["weights"])) for r in here if _carries(r["weights"])})
    if len(lengths) > 1:
        problems.append(f"{month}: weight vectors of lengths {lengths}")
    return lengths[0] if len(lengths) == 1 else None


def allow_list(rows: list[Row], n: int | None = None) -> list[str]:
    """The one allow-list of the model-side rows, per start month: known mixes and statuses, the
    relationships (`_relationships`) and every row (`_row_problems`), with weight vectors of
    length `n` (the month's one length when `n` is None). `month_pool_checks` applies it to its
    input rows before any computation; `gates` applies it again."""
    problems: list[str] = []
    for month in sorted({str(r["month"]) for r in rows}):
        here = [r for r in rows if str(r["month"]) == month]
        unknown = sorted({str(r["mix"]) for r in here if r["mix"] not in KNOWN})
        if unknown:
            problems.append(f"{month}: unknown mixes {unknown}")
        statuses = sorted({str(r["status"]) for r in here if r["status"] not in STATUSES})
        if statuses:
            problems.append(f"{month}: unknown statuses {statuses}")
        width = n if n is not None else _width(month, here, problems)
        problems += _relationships(month, here)
        for row in here:
            if lacks := _row_problems(row, width):
                problems.append(f"{month}: {row['mix']} {_rf(row)} {row['status']} lacks {lacks}")
    return problems


def _best(values: np.ndarray, where: np.ndarray) -> float:
    """The largest of `values` where `where` holds; `-inf` when it holds nowhere."""
    return float(values[where].max()) if where.any() else -math.inf


def month_pool_checks(mixes: pd.DataFrame, pool: pd.DataFrame, lower, upper) -> pd.DataFrame:
    """`mixes` (one start month's `month_mixes`) with the pool's four columns, and the tie rule
    applied (protocol, check (b) on D and "Model-side gates"). `pool` is the month's
    `read_month_pool_dr2`, before any domain filter.

    - `pool_dr2_max`: every D row with weights, the largest `dr2` of the allowed mixes; every D10
      row with weights, the same over the allowed mixes within `D10_CAP` on every holding.
    - `pool_mu_bound`: kept U rows, the largest `mu` of every pool row with `sigma <= r`, no
      tolerance, rows that break a limit included.
    - `pool_mu_at_risk`: kept E, D and D10 rows, the largest `mu` of the allowed mixes with
      `sigma <= sigma(M)`.
    - `tie`: a kept E, D or D10 row whose model return gap `mu_gap` is at most `TOL` and which the
      pool does not refute (`pool_mu_at_risk <= mu + TOL`): kept, "on the frontier". When the
      pool refutes it, the row and its comparator fail.

    Before any computation or change, the rows pass `allow_list` and the pool `_pool_problems`;
    `ValueError` naming the month otherwise, and when an allowed row lacks a model measure. Each
    maximum is `-inf` when no row qualifies. A kept tie is paired with the mix itself: its
    comparator row takes M's weights and model figures, so its differences are 0 by construction
    (protocol line 269); the mix row keeps `l1`, its distance to `F(sigma(M))`."""
    out = A._frame(mixes.copy()).reset_index(drop=True)
    month = str(out["month"].iloc[0]) if len(out) else "?"
    rows: list[Row] = [{str(k): v for k, v in r.items()} for r in out.to_dict("records")]
    try:
        if problems := [*allow_list(rows, len(lower)), *_pool_problems(pool, len(lower))]:
            raise ValueError("; ".join(problems[:10]))
        allowed = allowed_mixes(pool, lower, upper)
    except ValueError as exc:
        raise ValueError(f"{month}: {exc}; the recipes check stops") from exc
    sigma_all = pool["sigma"].to_numpy(dtype=float)
    mu_all = pool["mu"].to_numpy(dtype=float)
    sigma_ok = allowed["sigma"].to_numpy(dtype=float)
    mu_ok = allowed["mu"].to_numpy(dtype=float)
    dr2_ok = allowed["dr2"].to_numpy(dtype=float)
    within_d10 = _inside(allowed, np.zeros(len(lower)), np.full(len(lower), D10_CAP))
    dr2_max = {D: _best(dr2_ok, np.ones(len(allowed), dtype=bool)), D10: _best(dr2_ok, within_d10)}
    for row in rows:
        mix, kept = row["mix"], row["status"] == KEPT
        row.update(pool_dr2_max=math.nan, pool_mu_bound=math.nan, pool_mu_at_risk=math.nan,
                   tie=False)  # fmt: skip
        if mix in dr2_max and _carries(row["weights"]):
            row["pool_dr2_max"] = dr2_max[mix]
        if mix == U and kept:
            row["pool_mu_bound"] = _best(mu_all, sigma_all <= row["r"])
        if mix in RECIPES and kept:
            row["pool_mu_at_risk"] = _best(mu_ok, sigma_ok <= row["sigma"])
    _ties(rows)
    return pd.DataFrame(rows, columns=[*out.columns, *POOL_CHECKS])


TIE_COPIED = ("weights", "mu", "sigma", "a", "enb", "dr2")  # what a tie's comparator takes from M


def _ties(rows: list[Row]) -> None:
    """The strict gap: `mu(F(sigma(M))) - mu(M) > TOL`, else a tie the pool must not refute. The
    rows passed the allow-list, so a kept mix has its numbers and one kept comparator on its risk
    line."""
    for row in rows:
        if row["mix"] not in RECIPES or row["status"] != KEPT or row["mu_gap"] > TOL:
            continue
        (comp,) = [r for r in rows if r["mix"] == COMPARATOR[row["mix"]]]
        if row["pool_mu_at_risk"] > row["mu"] + TOL:
            for other in (row, comp):
                other.update(status=FAILED, reason=REFUTED)
            continue
        row["tie"] = True
        comp.update({name: row[name] for name in TIE_COPIED}, risk_gap=0.0)


# -------------------------------------------------------------- the gates across months

L1_REPORT = 1e-4  # weight distance reported, never gated (protocol, reconstruction check)
TESTED = (U, E, D, D10)  # the mixes with a comparator, whose failed cells are counted
GATE_RECONSTRUCTION, GATE_LIST, GATE_CHECK_B = "reconstruction", "list gate", "check (b)"
GATE_U_RETURN, GATE_U_BOUND = "U return", "U pool bound"
GATE_FAILED, GATE_COVERAGE, GATE_STRUCTURE = "failed cells", "coverage", "structure"
Row = dict[str, Any]


def _num(value: Any) -> float:
    """A cell value as a float; NaN when it is missing."""
    return math.nan if value is None else float(value)


def _flag(value: Any) -> bool:
    return (
        value is not None and not (isinstance(value, float) and math.isnan(value)) and bool(value)
    )


def _rf(row: Row) -> float:
    return round(_num(row["rf"]), 6)


def _key(row: Row) -> Row:
    """A cell's name in a list: its month, and its setting for F and U."""
    if row["mix"] in (F, U):
        return {"month": str(row["month"]), "rf": _rf(row)}
    return {"month": str(row["month"])}


def _order(rows: Iterable[Row]) -> list[Row]:
    """Cells by month, then setting (none for E, D and D10)."""

    def key(r: Row) -> tuple[str, float]:
        rf = _num(r.get("rf"))
        return str(r["month"]), rf if math.isfinite(rf) else -1.0

    return sorted(rows, key=key)


def _share(part: int, whole: int) -> float:
    return part / whole if whole else math.nan


def _above(part: int, whole: int) -> bool:
    """More than 1% of `whole`, in integers; a check with nothing to judge cannot pass."""
    return whole == 0 or 100 * part > whole


def _finite(values: Iterable[float]) -> np.ndarray:
    x = np.asarray(list(values), dtype=float)
    return x[np.isfinite(x)]


def _largest(values: Iterable[float]) -> float:
    x = _finite(values)
    return float(x.max()) if len(x) else math.nan


def _f_failed(row: Row) -> bool:
    """An F cell fails the reconstruction check unless it is kept with both rebuilt gaps within
    `TOL`; a missing gap fails."""
    gaps_ok = _num(row["rebuilt_mu_gap"]) <= TOL and _num(row["rebuilt_sigma_gap"]) <= TOL
    return row["status"] != KEPT or not gaps_ok


def _judge_rows(rows: list[Row]) -> list[Row]:
    """`rows` (copies) with each kept cell's status re-derived from its tolerances: an F row
    fails when a rebuilt gap is not within `TOL`; a kept U fails when the F row of its setting
    failed or its risk gap is not within `U_TOL`; a kept E, D or D10 fails, with its comparator,
    when the comparator's risk gap is not within `TOL`. A row missing what it must hold is the
    structure gate's: it stops the run instead."""
    rows = [dict(r) for r in rows]
    for row in rows:
        if row["mix"] == F and row["status"] == KEPT and _f_failed(row):
            row.update(status=FAILED, reason=RECONSTRUCTION)
    f_failed = {(str(r["month"]), _rf(r)) for r in rows if r["mix"] == F and _f_failed(r)}
    comparators = {(str(r["month"]), r["mix"]): r for r in rows if r["mix"] in COMPARATOR.values()}
    for row in rows:
        mix = row["mix"]
        if mix not in TESTED or row["status"] != KEPT:
            continue
        reason = None
        if mix == U:
            if (str(row["month"]), _rf(row)) in f_failed:
                reason = "the F row of this setting failed"
            elif not _num(row["risk_gap"]) <= U_TOL:
                reason = f"the risk gap is not within {U_TOL:.0e}"
            if reason:
                row.update(status=FAILED, reason=reason)
            continue
        comp = comparators.get((str(row["month"]), COMPARATOR[mix]))
        if comp is not None and not _num(comp["risk_gap"]) <= TOL:
            reason = f"the comparator's risk gap is not within {TOL:.0e}"
            row.update(status=FAILED, reason=reason)
            comp.update(status=FAILED, reason=reason)
    return rows


def judge(cells: pd.DataFrame) -> pd.DataFrame:
    """`cells` with every status as the gates count it (`_judge_rows`), so a cell the gates count
    as failed is failed in the cells that later enter the paired statistics."""
    rows = [{str(k): v for k, v in r.items()} for r in cells.to_dict("records")]
    return pd.DataFrame(_judge_rows(rows), columns=list(cells.columns))


def _pool_columns(row: Row) -> tuple[str, ...]:
    """The pool maxima `month_pool_checks` gives `row`: `pool_dr2_max` on a D or D10 that carries
    weights, `pool_mu_bound` on a kept U, `pool_mu_at_risk` on a kept E, D or D10."""
    mix, kept = row["mix"], row["status"] == KEPT
    names = ("pool_dr2_max",) if mix in (D, D10) and _carries(row["weights"]) else ()
    names += ("pool_mu_bound",) if mix == U and kept else ()
    return names + (("pool_mu_at_risk",) if mix in RECIPES and kept else ())


def _pool_column_problems(rows: list[Row]) -> list[str]:
    """Every pool maximum a row holds is a number, finite or `-inf` (no pool row)."""
    problems = []
    for row in rows:
        bad = [
            name
            for name in _pool_columns(row)
            if not (_real_finite(row[name]) or row[name] == -math.inf)
        ]
        if bad:
            problems.append(f"{row['month']}: {row['mix']} {_rf(row)} lacks {bad}")
    return problems


def _structure(rows: list[Row]) -> tuple[list[str], str | None]:
    """The allow-list again (`allow_list`), every start month complete (F, arm 1 and U once at
    each of the six settings; E, D and D10 once), and the pool maxima (`_pool_column_problems`)."""
    problems: list[str] = []
    settings = sorted(round(rf, 6) for rf in A.RFS)
    for month in sorted({str(r["month"]) for r in rows}):
        here = [r for r in rows if str(r["month"]) == month]
        for mix in ONE_PER_SETTING:
            found = sorted(_rf(r) for r in here if r["mix"] == mix)
            if found != settings:
                problems.append(f"{month}: {mix} at settings {found}")
        problems += [f"{month}: no row of {m}" for m in RECIPES if all(r["mix"] != m for r in here)]
    problems += allow_list(rows)
    problems += _pool_column_problems(rows)
    return problems, "; ".join(problems[:10]) or None


def _reconstruction(rows: list[Row]) -> tuple[Row, str | None]:
    f = [r for r in rows if r["mix"] == F]
    failed = [r for r in f if _f_failed(r)]
    out = {
        "cells": len(f),
        "failed": len(failed),
        "share": _share(len(failed), len(f)),
        "largest_mu_gap": _largest(_num(r["rebuilt_mu_gap"]) for r in f),
        "largest_sigma_gap": _largest(_num(r["rebuilt_sigma_gap"]) for r in f),
        "l1_above": sum(_num(r["rebuilt_l1"]) > L1_REPORT for r in f),
        "failed_cells": [
            {**_key(r), "reason": r["reason"] or RECONSTRUCTION} for r in _order(failed)
        ],
    }
    stop = None
    if _above(len(failed), len(f)):
        stop = f"{len(failed)} of {len(f)} F cells failed the reconstruction (more than 1%)"
    return out, stop


def _exclusions(judged: list[Row], eligible: set[str]) -> Row:
    out = {}
    for mix in TESTED:
        here = [r for r in judged if r["mix"] == mix and str(r["month"]) in eligible]
        excluded = _order(r for r in here if r["status"] == EXCLUDED)
        other = _order(
            r
            for r in judged
            if r["mix"] == mix and str(r["month"]) not in eligible and r["status"] == EXCLUDED
        )
        names = (lambda r: _key(r)) if mix == U else (lambda r: str(r["month"]))
        out[mix] = {
            "cells": len(here),
            "excluded": len(excluded),
            "share": _share(len(excluded), len(here)),
            "list": [names(r) for r in excluded],
            "other_months": [names(r) for r in other],
        }
    return out


def _list_gate(
    judged: list[Row], eligible: set[str], expected, scope: set[str] | None
) -> tuple[Row, str | None]:
    e_expected_all, u_expected_all = expected if expected is not None else (E_EXCLUDED, U_EXCLUDED)
    wanted = (lambda m: True) if scope is None else (lambda m: m in scope)
    excluded = [r for r in judged if r["status"] == EXCLUDED and str(r["month"]) in eligible]
    e_run = sorted(str(r["month"]) for r in excluded if r["mix"] == E)
    e_expected = sorted(m for m in e_expected_all if wanted(m))
    u_run = {(str(r["month"]), _rf(r)) for r in excluded if r["mix"] == U}
    u_expected = [(m, round(float(rf), 6)) for m, rf in u_expected_all if wanted(m)]
    u_missing = [{"month": m, "rf": rf} for m, rf in u_expected if (m, rf) not in u_run]
    out = {
        "e_excluded": e_run,
        "e_expected": e_expected,
        "u_excluded": [{"month": m, "rf": rf} for m, rf in sorted(u_run)],
        "u_expected": [{"month": m, "rf": rf} for m, rf in u_expected],
        "u_missing": u_missing,
    }
    problems = []
    if e_run != e_expected:
        extra = sorted(set(e_run) - set(e_expected))
        lacking = sorted(set(e_expected) - set(e_run))
        problems.append(f"E's excluded months differ: not listed {extra}, not excluded {lacking}")
    if u_missing:
        problems.append(f"U's listed cells not excluded: {u_missing}")
    return out, "; ".join(problems) or None


def _check_b(rows: list[Row]) -> tuple[Row, list[str]]:
    out, stops = {}, []
    for mix in (D, D10):
        here = [r for r in rows if r["mix"] == mix]
        checked = [r for r in here if _carries(r["weights"]) or r["status"] in (KEPT, EXCLUDED)]
        judged_ids = {id(r) for r in checked}
        failed = [
            r
            for r in checked
            if not (
                _weights_ok(r["weights"], None)
                and _real_finite(r["dr2"])
                and _num(r["dr2"]) >= _num(r["pool_dr2_max"]) - TOL
            )
        ]
        margins = _finite(_num(r["dr2"]) - _num(r["pool_dr2_max"]) for r in checked)
        out[mix] = {
            "months": len(checked),
            "failed": [
                {
                    "month": str(r["month"]),
                    "dr2": _num(r["dr2"]),
                    "pool_dr2_max": _num(r["pool_dr2_max"]),
                }
                for r in _order(failed)
            ],  # fmt: skip
            "smallest_margin": float(margins.min()) if len(margins) else math.nan,
            "without_rows": sorted(
                str(r["month"]) for r in checked if _num(r["pool_dr2_max"]) == -math.inf
            ),
            "not_built": sorted(
                str(r["month"])
                for r in here
                if not _carries(r["weights"]) and id(r) not in judged_ids
            ),
        }
        if not checked:
            stops.append(f"{mix}: no start month to check")
        elif failed:
            stops.append(f"{mix}: {len(failed)} start month(s) below the pool's largest ratio")
    return out, stops


def _u_gates(rows: list[Row]) -> tuple[Row, Row, str | None, str | None]:
    kept = [r for r in rows if r["mix"] == U and r["status"] == KEPT]
    low = [r for r in kept if not _num(r["mu_gap"]) >= -TOL]
    below = [r for r in kept if not _num(r["mu"]) >= _num(r["pool_mu_bound"]) - TOL]
    u_return = {
        "cells": len(kept),
        "failed": [{**_key(r), "mu_gap": _num(r["mu_gap"])} for r in _order(low)],
    }
    u_bound = {
        "cells": len(kept),
        "failed": [
            {**_key(r), "mu": _num(r["mu"]), "pool_mu_bound": _num(r["pool_mu_bound"])}
            for r in _order(below)
        ],
        "without_rows": [_key(r) for r in _order(kept) if _num(r["pool_mu_bound"]) == -math.inf],
    }
    none = "no kept U cell to judge"
    stop_return = none if not kept else (f"{len(low)} kept U cell(s) below F" if low else None)
    stop_bound = (
        none if not kept else (f"{len(below)} kept U cell(s) below the pool" if below else None)
    )
    return u_return, u_bound, stop_return, stop_bound


def _u_limits(judged: list[Row], eligible: set[str]) -> Row:
    kept = [r for r in judged if r["mix"] == U and r["status"] == KEPT]
    kept = [r for r in kept if str(r["month"]) in eligible]
    return {
        "breaks_share": _share(sum(_flag(r["breaks_limit"]) for r in kept), len(kept)),
        "l1_above_share": _share(sum(_num(r["l1"]) > L1_REPORT for r in kept), len(kept)),
    }


def _strict_gap(rows: list[Row]) -> Row:
    out = {}
    for mix in RECIPES:
        here = [r for r in rows if r["mix"] == mix]
        out[mix] = {
            "ties_kept": sum(r["status"] == KEPT and _flag(r["tie"]) for r in here),
            "ties_refuted": sum(r["reason"] == REFUTED for r in here),
            "l1_below": sum(r["status"] == KEPT and _num(r["l1"]) < L1_REPORT for r in here),
        }
    return out


def _failed_cells(judged: list[Row], eligible: set[str]) -> tuple[Row, list[str]]:
    out, stops = {}, []
    for mix in TESTED:
        here = [r for r in judged if r["mix"] == mix and r["status"] in (KEPT, FAILED)]
        inside = [r for r in here if str(r["month"]) in eligible]
        failed = _order(r for r in inside if r["status"] == FAILED)
        other = _order(r for r in here if str(r["month"]) not in eligible and r["status"] == FAILED)
        out[mix] = {
            "cells": len(inside),
            "failed": len(failed),
            "share": _share(len(failed), len(inside)),
            "list": [{**_key(r), "reason": r["reason"]} for r in failed],
            "other_months": [{**_key(r), "reason": r["reason"]} for r in other],
        }
        if _above(len(failed), len(inside)):
            stops.append(f"{mix}: {len(failed)} of {len(inside)} kept or failed cells failed")
    return out, stops


def _risk_gap(rows: list[Row]) -> Row:
    out = {}
    for mix in TESTED:
        source, tol = (U, U_TOL) if mix == U else (COMPARATOR[mix], TOL)
        gaps = _finite(_num(r["risk_gap"]) for r in rows if r["mix"] == source)
        out[mix] = {
            "cells": len(gaps),
            "mean": float(gaps.mean()) if len(gaps) else math.nan,
            "largest": float(gaps.max()) if len(gaps) else math.nan,
            "above": int((gaps > tol).sum()),
        }
    return out


def _positions(here: list[Row]) -> Row:
    a = _finite(_num(r["a"]) for r in here)
    nearest = dict.fromkeys(A.RFS, 0)
    for r in here:
        if r["status"] != EXCLUDED and math.isfinite(_num(r["a"])):
            nearest[min(A.RFS, key=lambda rf: abs(_num(r["a"]) - rf))] += 1
    stats = {"mean": np.mean, "median": np.median}
    out: Row = {"months": len(a)}
    out.update({k: float(f(a)) if len(a) else math.nan for k, f in stats.items()})
    for name, q in (("p5", 5), ("p95", 95)):
        out[name] = float(np.percentile(a, q)) if len(a) else math.nan
    out["nearest"] = nearest
    out["at_or_above_top"] = sum(r["status"] == EXCLUDED for r in here)
    return out


def _risk_position(rows: list[Row], eligible: set[str]) -> Row:
    out = {}
    for mix in RECIPES:
        here = [r for r in rows if r["mix"] == mix and math.isfinite(_num(r["a"]))]
        out[mix] = {
            "eligible": _positions([r for r in here if str(r["month"]) in eligible]),
            "all": _positions(here),
        }
    return out


def _flagged(rows: list[Row]) -> list[Row]:
    """Start months with a failed F cell whose E, D or D10 cells are kept (protocol line 128)."""
    out = []
    for month in sorted({str(r["month"]) for r in rows}):
        here = [r for r in rows if str(r["month"]) == month]
        settings = sorted(_rf(r) for r in here if r["mix"] == F and _f_failed(r))
        kept = [m for m in RECIPES if any(r["mix"] == m and r["status"] == KEPT for r in here)]
        if settings and kept:
            out.append({"month": month, "settings": settings, "kept": kept})
    return out


def gates(
    cells: pd.DataFrame,
    eligible: Sequence[str],
    *,
    expected: tuple[Sequence[str], Sequence[tuple[str, float]]] | None = None,
    scope: Sequence[str] | None = None,
) -> dict[str, Any]:
    """The model-side gates over every start month's `month_pool_checks` rows (protocol, "Failed
    cells, one rule", the reconstruction check, check (b), the list gate and "Model-side gates"),
    judged before any realized outcome is read. `eligible` are the start months with a complete
    realized year; `expected` is (E's excluded months, U's excluded cells), `None` for the
    pre-registered `E_EXCLUDED` and `U_EXCLUDED`; `scope` restricts the expected lists and the
    coverage to the months chosen in a restricted run.

    Every gate fails closed: a value that is missing, a month whose rows are incomplete, repeated
    or of unknown status, or a gate with no cell to judge, stops. Failed cells are counted on the
    statuses `judge` derives.
    `stops` lists each gate that stops the run, as `{"gate": name, "detail": text}`."""
    rows: list[Row] = [{str(k): v for k, v in r.items()} for r in cells.to_dict("records")]
    chosen = set(eligible) if scope is None else set(eligible) & set(scope)
    present = {str(r["month"]) for r in rows}
    all_judged = _judge_rows(rows)
    judged = [r for r in all_judged if r["mix"] in TESTED]
    eligible_set = set(eligible)
    stops: list[dict[str, str]] = []

    def stop(gate: str, detail: str | None) -> None:
        if detail:
            stops.append({"gate": gate, "detail": detail})

    missing = sorted(chosen - present)
    stop(GATE_COVERAGE, f"eligible start months without cells: {missing}" if missing else None)
    structure, detail = _structure(rows)
    stop(GATE_STRUCTURE, detail)
    reconstruction, detail = _reconstruction(all_judged)
    stop(GATE_RECONSTRUCTION, detail)
    scope_set = None if scope is None else set(scope)
    list_gate, detail = _list_gate(judged, eligible_set, expected, scope_set)
    stop(GATE_LIST, detail)
    check_b, details = _check_b(rows)
    for detail in details:
        stop(GATE_CHECK_B, detail)
    u_return, u_bound, detail_return, detail_bound = _u_gates(rows)
    stop(GATE_U_RETURN, detail_return)
    stop(GATE_U_BOUND, detail_bound)
    failed_cells, details = _failed_cells(judged, eligible_set)
    for detail in details:
        stop(GATE_FAILED, detail)
    return {
        "coverage": {"missing": missing},
        "structure": {"problems": structure},
        "reconstruction": reconstruction,
        "exclusions": _exclusions(judged, eligible_set),
        "list_gate": list_gate,
        "check_b": check_b,
        "u_return": u_return,
        "u_pool_bound": u_bound,
        "u_limits": _u_limits(judged, eligible_set),
        "strict_gap": _strict_gap(rows),
        "failed_cells": failed_cells,
        "risk_gap": _risk_gap(rows),
        "risk_position": _risk_position(rows, eligible_set),
        "geometry": {
            "largest_ends_gap": _largest(_num(r["ends_gap"]) for r in rows if r["mix"] == F)
        },
        "flagged_months": _flagged(rows),
        "stops": stops,
    }


# -------------------------------------------------------------- the model side of a job


@dataclass(frozen=True)
class ModelSide:
    """Every start month's model-side cells (`month_pool_checks` rows with an `origin` column, the
    statuses as `judge` derives them) and the gates judged over them (`gates`)."""

    cells: pd.DataFrame
    checks: dict[str, Any]


def model_side(
    months: Sequence[str],
    context: Callable[[str], Any],
    columns: pd.DataFrame,
    pool_path: Callable[[str], Path],
    lower,
    upper,
    eligible: Sequence[str],
    *,
    expected: tuple[Sequence[str], Sequence[tuple[str, float]]] | None = None,
    restricted: bool = False,
    progress: Callable[[str], None] | None = None,
) -> ModelSide:
    """The model side of the recipes check, before any realized outcome is read (protocol,
    "Model-side gates, before any realized outcome is read"). Per start month: the recorded
    columns, the mixes, the pool with `dr2` and its checks; then the gates over all months
    (`scope=months` when the run is `restricted` to chosen months). `context(month)` gives the
    training side (`mu_s`, `cov`, `origin`). A month without pool rows is allowed; a pool row
    without a model measure stops with a `ValueError` naming the month. No realized outcome is an
    argument, so none can be read."""
    parts = []
    for month in months:
        ctx = context(month)
        mixes = month_mixes(
            month, ctx.mu_s, ctx.cov, lower, upper, recorded_columns(columns, month)
        )
        pool = read_month_pool_dr2(pool_path(month))
        part = month_pool_checks(mixes, pool, lower, upper)
        part["origin"] = ctx.origin
        parts.append(part)
        if progress is not None:
            progress(f"{month}: {len(pool)} main rows, {len(part)} model-side rows")
        del pool
    cells = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    checks = gates(cells, eligible, expected=expected, scope=list(months) if restricted else None)
    return ModelSide(cells=judge(cells) if parts else cells, checks=checks)
