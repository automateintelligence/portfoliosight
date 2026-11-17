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
`month_mixes`) and the two pre-registered lists (`E_EXCLUDED`, `U_EXCLUDED`).
"""

from __future__ import annotations

import math
from collections.abc import Callable
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
UNDECIDED = "the strict gap cannot be decided: a model return is missing"
RECIPES = (E, D, D10)


def _built(weights: Any) -> bool:
    """A row carries weights (a mix that was built), not None or a missing value."""
    return weights is not None and np.ndim(weights) == 1


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
      pool refutes it, or the gap or the return is missing, the row and its comparator fail.

    Each maximum is `-inf` when no row qualifies. `ValueError` naming the month when a pool row
    lacks `mu` or `sigma`, or an allowed row lacks a model measure or `dr2`."""
    out = A._frame(mixes.copy()).reset_index(drop=True)
    month = str(out["month"].iloc[0]) if len(out) else "?"
    try:
        for name in ("mu", "sigma"):
            if np.isnan(pool[name].to_numpy(dtype=float)).any():
                raise ValueError(f"main-pool row(s) lack {name}")
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
    rows = out.to_dict("records")
    for row in rows:
        mix, kept = row["mix"], row["status"] == KEPT
        row.update(pool_dr2_max=math.nan, pool_mu_bound=math.nan, pool_mu_at_risk=math.nan,
                   tie=False)  # fmt: skip
        if mix in dr2_max and _built(row["weights"]):
            row["pool_dr2_max"] = dr2_max[mix]
        if mix == U and kept:
            row["pool_mu_bound"] = _best(mu_all, sigma_all <= float(row["r"]))
        if mix in RECIPES and kept:
            row["pool_mu_at_risk"] = _best(mu_ok, sigma_ok <= float(row["sigma"]))
    _ties(rows)
    return pd.DataFrame(rows, columns=[*out.columns, *POOL_CHECKS])


def _ties(rows: list[dict[str, Any]]) -> None:
    """The strict gap: `mu(F(sigma(M))) - mu(M) > TOL`, else a tie the pool must not refute."""
    for row in rows:
        if row["mix"] not in RECIPES or row["status"] != KEPT:
            continue
        gap, bound, mu = float(row["mu_gap"]), float(row["pool_mu_at_risk"]), float(row["mu"])
        if gap > TOL:
            continue
        if gap <= TOL and bound <= mu + TOL:
            row["tie"] = True
            continue
        reason = REFUTED if gap <= TOL and bound > mu + TOL else UNDECIDED
        pair = (row["mix"], COMPARATOR[row["mix"]])
        for other in rows:
            if other["month"] == row["month"] and other["mix"] in pair:
                other.update(status=FAILED, reason=reason)
