"""Locked selections and the evidence tables of the experiment (protocol 5 steps 7-8, 6 and 9).

The experiment runner (`research.experiment`) schedules cells and runs them; this module turns a
searched cell into rows and evaluates what was locked. In order of use:

1. `choose(cell, coefficients)`: the union selections of one searched cell. For each measure the
   cell scored (DR², and ENB in Stage 2) and each evaluated allowance `ALLOWANCES` (the primary
   2.5 bp and the protocol 7 (a) sweep 0, 5 and 10 bp, all from the same union pool, no new
   search) `preference.select`, and the filtered pool's unconstrained most diversified member.
2. `search_table(spec, cell, chosen, model)`: every row of the cell for `search.parquet`, one
   long table whose `kind` says what a row is: `cell` (status, failure class, ceilings, hashes,
   the local guard reference, pool sizes), `anchor`, `arm` (failure, calls, native results),
   `start` (COBYLA's raw report) and `candidate` (every attempted proposal, its evaluation, DR²
   and ENB, and its flags in the union pool: dominated, `w_r`, admissible and the guards it fails
   relative to the union `w_R` at the primary allowance, `stage_b`, native winners).
3. `lock_rows(spec, profile, cell, chosen, model)`: the selections fixed before any independent
   draw or realized return is read, one row per role: `R` (the union `w_R`: R's selection and the
   max-U white-line candidate), `R+D` (and `R+E`) at each allowance with its sacrifice, binding
   guards and excluding guards, each arm's native selection (`R:native`, ...), the max-`mu_s`
   frontier anchor at the cell's ceiling (`frontier`, the other white-line candidate), the three
   return-agnostic references (`mdp` at the cell's ceiling, `min_variance`, `equal_weight`) and
   the pool's unconstrained most diversified member (`pool_max_dr2`, `pool_max_enb`). Each row
   carries its exact weights, risk and residuals, optimization-bank B/T/G/U/mean/`ES_2.5`, DR²,
   `mu_s'w` (`expected_return`) and the model and bank digests it was chosen on.
4. `write_locked` writes those rows and returns the SHA-256 of the file; `read_locked` refuses a
   file whose bytes no longer have that digest (`LockedFileChanged`).
5. `evaluate_group(task)` evaluates the locked rows of one (profile, menu, origin): it reads the
   locked file and nothing of the search. It replays every row on its own optimization bank
   (whose figures must equal the locked ones bit for bit, `InvarianceError` otherwise), on the
   five independent banks `TEST_SEEDS` one by one and pooled (10,000 outcomes; pooled within one
   optimizer seed's selection, never across optimizer seeds), and over the realized horizon, and
   scores calibration: pinball loss and `1[y <= f]` for each training and pooled-test quantile,
   and the PIT of the realized return among the pooled outcomes.
6. `finish_outcomes(rows, ...)`: the outcomes table in canonical order, with the cross-row
   columns: `forecast_error` (realized annual return minus `mu_s'w`), `paired_realized_difference`
   (an `R+D` or `R+E` row's realized annual return minus `R`'s in the same cell),
   `turnover_prev` (`0.5 L1` to the same role at the previous scheduled origin, one per
   prescribed ceiling the row stands for) and `seed_l1` (L1 to the same role of each other
   optimizer seed).
7. `forecast_error_diagnostic(frame)`: per menu and prescribed risk cell, the correlation across
   mature origins of `w_R`'s forecast error with the paired realized difference (protocol 6,
   mechanism (a)) and its sign. The block-bootstrap interval belongs to the report.

Realized definitions (`DEFINITIONS`, also written to the manifest): maximum drawdown
`max_t 1 - W_t / max(1, max_{s<=t} W_s)` along the 252-day wealth path; realized volatility
`sqrt(252)` times the ddof-1 standard deviation of the 252 daily returns.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from portfoliosight.engine import measures, preference
from portfoliosight.engine.preference import Candidate, Selection
from portfoliosight.engine.torsion import enb, torsion_basis
from portfoliosight.research import evaluate
from portfoliosight.research.evaluate import COMPLETE, OK, Horizon, OriginModel
from portfoliosight.research.search import (
    FEASIBILITY_TOL,
    PATH_SEEDS,
    PRIMARY_ALLOWANCE,
    Budget,
    CellSearch,
    InvarianceError,
    Scored,
)

TEST_SEEDS = (20261113, 20261114, 20261115, 20261116, 20261117)  # protocol 5 step 8
PRIMARY_SEED = PATH_SEEDS[0]
ALLOWANCES = (PRIMARY_ALLOWANCE, 0.0, 0.0005, 0.001)  # 2.5 bp primary, then 0, 5, 10 bp
QUANTILES = (("bad", 0.025), ("typical", 0.50), ("good", 0.975))
MEASURE_ARMS = {"R+D": "dr2", "R+E": "enb"}
ROLES = (
    "R",
    "R+D",
    "R+E",
    "R:native",
    "R+D:native",
    "R+E:native",
    "frontier",
    "mdp",
    "min_variance",
    "equal_weight",
    "pool_max_dr2",
    "pool_max_enb",
)
DEFINITIONS = {
    "annual_return": "prod_t(1 + sum_i w_i r_it) - 1 over the 252 horizon days, constant weights",
    "max_drawdown": "max_t 1 - W_t / max(1, max_{s<=t} W_s), W_t the wealth after day t",
    "volatility": "sqrt(252) * std(ddof=1) of the 252 daily portfolio returns",
    "es_25": "mean of the worst ceil(0.025 P) of P annual outcomes (50 of 2,000; 250 of 10,000)",
    "utility": "U = k_B B + k_T T + k_G G, k = (0.60, 0.30, 0.10) unless a profile says otherwise",
    "dr2": "(sum_i w_i sigma_i)^2 / (w' Sigma w), production estimate_moments, fixed window",
    "forecast_error": "realized annual return minus mu_s'w",
    "turnover_prev": "0.5 * L1(w_t - w_previous scheduled origin), same role, ceiling and seed",
}

# cell statuses beyond the search's failure classes
OK_CELL = "ok"
TRAINING_INELIGIBLE = "training_ineligible"  # a sensitivity lookback without a training window
RESOURCE_BREACH = "resource_breach"  # the cell crossed a resource ceiling: the run stopped
UNATTEMPTED = "unattempted"  # never started: the run stopped first
INTERRUPTED = "interrupted"  # running when the run stopped


class LockedFileChanged(RuntimeError):
    """The locked selections file no longer has the digest recorded when it was written."""


@dataclass(frozen=True)
class Profile:
    """One configuration of search and selection: Stage 1, Stage 2 or one sensitivity setting."""

    name: str
    lookback: str
    budget: Budget
    coefficients: tuple[float, float, float]
    arms: tuple[str, ...]
    seeds: tuple[int, ...]
    origins: str  # "scheduled": every scheduled origin; "sensitivity": the six indexed ones


@dataclass(frozen=True)
class CellSpec:
    """One scheduled cell: a distinct (menu, origin, ceiling, optimizer seed) of a profile."""

    profile: str
    menu: str
    month: str
    origin: date
    lookback: str
    ceiling_id: str  # the distinct cell's fixed id (x25, x50, x100)
    fraction: float
    seed: int
    stands_for: tuple[str, ...]  # the prescribed ceilings whose results this cell's stand for
    weight: float  # aggregation weight within the origin: 1/3 per prescribed ceiling
    key: str  # canonical compact JSON [menu, ISO origin, ceiling id, seed]
    sha256: str  # of the key's UTF-8 bytes
    menu_index: int = -1  # position in the (profile, menu) hash order
    order: int = -1  # position in the whole run
    arm_order: tuple[str, ...] = ()
    preset: str | None = None  # a named failure decided before any search
    preset_detail: str | None = None


def cell_key(menu: str, origin: date, ceiling_id: str, seed: int) -> str:
    """The timing contract's canonical key: UTF-8 compact JSON `[menu, ISO origin, id, seed]`."""
    return json.dumps([menu, origin.isoformat(), ceiling_id, seed], separators=(",", ":"))


# ---------------------------------------------------------------------------------- selection


@dataclass(frozen=True)
class Chosen:
    """The union selections of one cell, by (measure, allowance), and the widest members."""

    coefficients: tuple[float, float, float]
    selections: Mapping[tuple[str, float], Selection]
    widest: Mapping[str, Candidate]  # the filtered pool's unconstrained max-measure member

    @property
    def primary(self) -> Selection:
        return self.selections[("dr2", PRIMARY_ALLOWANCE)]


def choose(
    cell: CellSearch,
    coefficients: Sequence[float] = preference.COEFFICIENTS,
    allowances: Sequence[float] = ALLOWANCES,
) -> Chosen:
    """`preference.select` on the union pool for every measure scored and every allowance."""
    if cell.failure is not None:
        raise ValueError(
            f"cell {cell.menu} {cell.origin} failed ({cell.failure}): nothing to select"
        )
    if PRIMARY_ALLOWANCE not in allowances:
        raise ValueError("the evaluated allowances must include the primary 2.5 bp")
    k = preference.checked_coefficients(coefficients)
    selections: dict[tuple[str, float], Selection] = {}
    widest: dict[str, Candidate] = {}
    for measure in cell.measures:
        first = preference.select(cell.pool(measure), PRIMARY_ALLOWANCE, k)
        for allowance in allowances:
            # the filtered pool is its own filtered pool: the same w_R and admissible sets
            chosen = (
                first
                if allowance == PRIMARY_ALLOWANCE
                else preference.select(first.pool, allowance, k)
            )
            selections[(measure, allowance)] = chosen
        widest[measure] = preference.select_diversified(first.pool, k)
    return Chosen(k, selections, widest)


# ------------------------------------------------------------------------------------- tables

_F = pa.float64()
_I = pa.int64()
_S = pa.string()
_B = pa.bool_()
_D = pa.date32()
_FL = pa.list_(pa.float64())
_SL = pa.list_(pa.string())
_IL = pa.list_(pa.int64())

_IDENTITY = [
    ("profile", _S),
    ("cell_key", _S),
    ("cell_sha256", _S),
    ("menu", _S),
    ("month", _S),
    ("origin", _D),
    ("lookback", _S),
    ("ceiling_id", _S),
    ("fraction", _F),
    ("seed", _I),
]
SEARCH_SCHEMA = pa.schema(
    _IDENTITY
    + [
        ("kind", _S),  # cell | anchor | arm | start | candidate
        ("row", _I),  # candidate: position in the cell's archive
        # cell
        ("cell_status", _S),
        ("error", _S),
        ("error_detail", _S),
        ("schedule_order", _I),
        ("menu_index", _I),
        ("arm_order", _SL),
        ("stands_for", _SL),
        ("aggregation_weight", _F),
        ("generator_seed", _I),
        ("coefficients", _FL),
        ("budget", _S),
        ("allowance", _F),
        ("shrinkage", _F),
        ("ceiling", _F),
        ("sigma_min", _F),
        ("sigma_top", _F),
        ("collapsed", _B),
        ("w_min", _FL),
        ("w_top", _FL),
        ("bank_sha256", _S),
        ("sobol_sha256", _S),
        ("broad_sha256", _S),
        ("cell_digest", _S),
        ("model_inputs_sha256", _S),
        ("reference", _S),  # JSON: the R+D local guard reference (broad archive's max U)
        ("pool_size", _I),
        ("filtered_size", _I),
        ("admissible_size", _I),
        ("selected_guards", _S),  # JSON: binding guards of the primary R+D selection
        ("sacrifice", _F),
        # anchor, arm, start, candidate
        ("source", _S),
        ("arm", _S),
        ("name", _S),
        ("index", _I),
        ("call", _I),
        ("anchor_ceiling", _F),
        ("solver_status", _S),
        ("off_ceiling", _B),
        ("repeat", _B),
        ("calls", _I),
        ("cobyla_status", _I),
        ("success", _B),
        ("message", _S),
        ("nfev", _I),
        ("fun", _F),
        ("maxcv", _F),
        ("x", _FL),
        ("budget_exhausted", _B),
        ("feasible", _I),
        ("refined", _I),
        ("trace", _FL),
        ("measure", _S),
        ("evaluations", _I),
        ("invalid", _I),
        ("failed_starts", _I),
        ("native_reference", _FL),
        ("native_selection", _FL),
        ("failure", _S),
        # candidate
        ("cached", _B),
        ("status", _S),
        ("ruin_day", _D),
        ("weights", _FL),
        ("risk", _F),
        ("bound_residual", _F),
        ("sum_residual", _F),
        ("risk_residual", _F),
        ("violation", _F),
        ("penalty", _F),
        ("objective", _F),
        ("local_guards", _S),
        ("bad", _F),
        ("typical", _F),
        ("good", _F),
        ("utility", _F),
        ("mean", _F),
        ("es_25", _F),
        ("dr2", _F),
        ("enb", _F),
        ("expected_return", _F),
        ("in_pool", _B),
        ("dominated", _B),
        ("w_r", _B),
        ("admissible", _B),
        ("failed_guards", _S),
        ("stage_b", _B),
        ("stage_b_enb", _B),
        ("native_winner", _SL),
    ]
)

LOCKED_SCHEMA = pa.schema(
    [
        ("selection_id", _S),
        *_IDENTITY,
        ("stands_for", _SL),
        ("aggregation_weight", _F),
        ("primary", _B),
        ("role", _S),
        ("allowance", _F),
        ("coefficients", _FL),
        ("weights", _FL),
        ("source_row", _I),
        ("status", _S),
        ("ruin_day", _D),
        ("risk", _F),
        ("ceiling", _F),
        ("within_ceiling", _B),
        ("bound_residual", _F),
        ("sum_residual", _F),
        ("risk_residual", _F),
        ("train_bad", _F),
        ("train_typical", _F),
        ("train_good", _F),
        ("train_utility", _F),
        ("train_mean", _F),
        ("train_es_25", _F),
        ("dr2", _F),
        ("enb", _F),
        ("expected_return", _F),
        ("sacrifice", _F),
        ("guards", _S),
        ("excluding_guards", _S),
        ("failed_guards", _S),
        ("admissible", _B),
        ("model_inputs_sha256", _S),
        ("train_bank_sha256", _S),
    ]
)

_FIGURES = ("bad", "typical", "good", "utility", "mean", "es_25", "p_loss", "p_below_20")
OUTCOMES_SCHEMA = pa.schema(
    list(LOCKED_SCHEMA)
    + [
        ("train_status", _S),
        ("train_paths", _I),
        ("train_p_loss", _F),
        ("train_p_below_20", _F),
        ("test_status", _S),
        ("test_paths", _I),
        *[(f"test_{name}", _F) for name in _FIGURES],
        ("bank_seeds", _IL),
        ("bank_index_sha256", _SL),
        *[(f"bank_{name}", _FL) for name in _FIGURES],
        ("realized_status", _S),
        ("horizon_start", _D),
        ("horizon_end", _D),
        ("realized_sha256", _S),
        ("annual_return", _F),
        ("loss", _B),
        ("below_20", _B),
        ("worst_day", _F),
        ("max_drawdown", _F),
        ("volatility", _F),
        ("forecast_error", _F),
        ("paired_role", _S),
        ("paired_realized_difference", _F),
        *[
            (f"{forecast}_{score}_{name}", _B if score == "at_or_below" else _F)
            for forecast in ("train", "test")
            for score in ("pinball", "at_or_below")
            for name, _ in QUANTILES
        ],
        ("test_pit", _F),
        ("turnover_prev", _FL),
        ("seed_l1_seeds", _IL),
        ("seed_l1", _FL),
    ]
)
CROSS_ROW = (
    "forecast_error",
    "paired_role",
    "paired_realized_difference",
    "turnover_prev",
    "seed_l1_seeds",
    "seed_l1",
)
EVALUATED_SCHEMA = pa.schema([f for f in OUTCOMES_SCHEMA if f.name not in CROSS_ROW])


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _weights(values: Sequence[float]) -> list[float]:
    return [float(x) for x in values]


def _identity(spec: CellSpec) -> dict[str, Any]:
    return {
        "profile": spec.profile,
        "cell_key": spec.key,
        "cell_sha256": spec.sha256,
        "menu": spec.menu,
        "month": spec.month,
        "origin": spec.origin,
        "lookback": spec.lookback,
        "ceiling_id": spec.ceiling_id,
        "fraction": spec.fraction,
        "seed": spec.seed,
    }


def _expected(model: OriginModel, weights: Sequence[float]) -> float:
    """`mu_s'w`: one dot product of two vectors, the same bits wherever it is taken."""
    return float(model.mu_s @ np.asarray(weights, dtype=float))


def cell_row(
    spec: CellSpec,
    status: str,
    error: str | None = None,
    detail: str | None = None,
    *,
    profile: Profile | None = None,
) -> dict[str, Any]:
    """The `cell` row of a cell that has no search to describe (not run, or stopped)."""
    row = {
        **_identity(spec),
        "kind": "cell",
        "cell_status": status,
        "error": error,
        "error_detail": detail,
        "schedule_order": spec.order,
        "menu_index": spec.menu_index,
        "arm_order": list(spec.arm_order),
        "stands_for": list(spec.stands_for),
        "aggregation_weight": spec.weight,
    }
    if profile is not None:
        row["coefficients"] = list(profile.coefficients)
        row["budget"] = _json(vars(profile.budget))
    return row


def status_table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    """Search rows as a table of `SEARCH_SCHEMA`."""
    return pa.Table.from_pylist(list(rows), schema=SEARCH_SCHEMA)


def search_table(
    spec: CellSpec,
    profile: Profile,
    cell: CellSearch,
    chosen: Chosen | None,
    model: OriginModel,
) -> pa.Table:
    """Every row of one searched cell for `search.parquet` (see the module docstring)."""
    ident = _identity(spec)
    status = OK_CELL if cell.failure is None else cell.failure
    top = cell_row(spec, status, cell.error, cell.error_detail, profile=profile)
    ceilings = cell.ceilings
    reference = cell.reference
    top.update(
        {
            "generator_seed": cell.generator_seed,
            "allowance": cell.allowance,
            "shrinkage": cell.shrinkage,
            "ceiling": cell.ceiling,
            "bank_sha256": cell.bank_sha256,
            "sobol_sha256": cell.sobol_sha256,
            "broad_sha256": cell.broad_sha256,
            "cell_digest": cell.digest(),
            "model_inputs_sha256": model.inputs_sha256,
            "pool_size": len(cell.pool_rows),
        }
    )
    if ceilings is not None:
        top.update(
            {
                "sigma_min": ceilings.sigma_min,
                "sigma_top": ceilings.sigma_top,
                "collapsed": ceilings.collapsed,
                "w_min": _weights(ceilings.w_min),
                "w_top": _weights(ceilings.w_top),
            }
        )
    if reference is not None:
        top["reference"] = _json(
            {
                "weights": list(reference.weights),
                "bad": reference.bad,
                "typical": reference.typical,
                "good": reference.good,
            }
        )
    rows: list[dict[str, Any]] = [top]
    for i, anchor in enumerate(cell.anchors):
        rows.append(
            {
                **ident,
                "kind": "anchor",
                "name": anchor.name,
                "index": i,
                "anchor_ceiling": anchor.ceiling,
                "solver_status": anchor.solver_status,
                "weights": None if anchor.weights is None else _weights(anchor.weights),
                "risk": anchor.risk,
                "off_ceiling": anchor.off_ceiling,
                "error": anchor.error,
            }
        )
    for arm in cell.arms:
        rows.append(
            {
                **ident,
                "kind": "arm",
                "arm": arm.label,
                "measure": arm.measure,
                "error": arm.error,
                "error_detail": arm.error_detail,
                "failure": arm.failure,
                "allowance": arm.allowance,
                "calls": arm.calls,
                "evaluations": arm.evaluations,
                "invalid": arm.invalid,
                "failed_starts": arm.failed_starts,
                "native_reference": None
                if arm.native_reference is None
                else _weights(arm.native_reference.weights),
                "native_selection": None
                if arm.native_selection is None
                else _weights(arm.native_selection.weights),
            }
        )
        for start in arm.starts:
            rows.append(
                {
                    **ident,
                    "kind": "start",
                    "arm": arm.label,
                    "index": start.index,
                    "weights": _weights(start.start),
                    "repeat": start.repeat,
                    "calls": start.calls,
                    "cobyla_status": start.status,
                    "success": start.success,
                    "message": start.message,
                    "nfev": start.nfev,
                    "fun": start.fun,
                    "maxcv": start.maxcv,
                    "x": None if start.x is None else _weights(start.x),
                    "budget_exhausted": start.budget_exhausted,
                    "feasible": start.feasible,
                    "refined": start.refined,
                    "trace": list(start.trace),
                    "failure": start.failure,
                }
            )
    flags = _pool_flags(cell, chosen)
    natives: dict[tuple[float, ...], list[str]] = {}
    for arm in cell.arms:
        if arm.native_selection is not None:
            natives.setdefault(arm.native_selection.weights, []).append(arm.label)
    in_pool = set(cell.pool_rows)
    for i, attempt in enumerate(cell.rows):
        s = attempt.scored
        row = {
            **ident,
            "kind": "candidate",
            "row": i,
            "source": attempt.source,
            "arm": attempt.arm,
            "name": attempt.name,
            "index": attempt.index,
            "call": attempt.call,
            "cached": attempt.cached,
            "status": s.status,
            "ruin_day": s.ruin_day,
            "weights": _weights(s.weights),
            "risk": s.risk,
            "bound_residual": s.bound_residual,
            "sum_residual": s.sum_residual,
            "risk_residual": s.risk_residual,
            "violation": s.violation,
            "penalty": s.penalty,
            "objective": attempt.objective,
            "local_guards": None if attempt.local_guards is None else _json(attempt.local_guards),
            "bad": s.bad,
            "typical": s.typical,
            "good": s.good,
            "utility": s.utility,
            "mean": s.mean,
            "es_25": s.es_25,
            "dr2": attempt.dr2,
            "enb": attempt.enb,
            "expected_return": _expected(model, s.weights),
            "failure": attempt.failure,
            "in_pool": i in in_pool,
        }
        if i in in_pool:
            row.update(flags.get(s.weights, {}))
            row["native_winner"] = natives.get(s.weights, [])
        rows.append(row)
    if chosen is not None:
        primary = chosen.primary
        top.update(
            {
                "filtered_size": len(primary.pool),
                "admissible_size": len(primary.admissible),
                "selected_guards": _json(sorted(primary.guards)),
                "sacrifice": primary.sacrifice,
            }
        )
    return pa.Table.from_pylist(rows, schema=SEARCH_SCHEMA)


def _pool_flags(cell: CellSearch, chosen: Chosen | None) -> dict[tuple[float, ...], dict]:
    """Per pool member: dominated, w_R, admissible, failed guards, Stage B winners (primary)."""
    if chosen is None:
        return {}
    primary = chosen.primary
    filtered = {c.weights for c in primary.pool}
    admissible = {c.weights for c in primary.admissible}
    reference = primary.reference
    enb_pick = chosen.selections.get(("enb", PRIMARY_ALLOWANCE))
    flags = {}
    for candidate in cell.pool("dr2"):
        failed = preference.failed_guards(
            candidate, reference, PRIMARY_ALLOWANCE, chosen.coefficients
        )
        flags[candidate.weights] = {
            "dominated": candidate.weights not in filtered,
            "w_r": candidate.weights == reference.weights,
            "admissible": candidate.weights in admissible,
            "failed_guards": _json(list(failed)),
            "stage_b": candidate.weights == primary.selected.weights,
            "stage_b_enb": None
            if enb_pick is None
            else candidate.weights == enb_pick.selected.weights,
        }
    return flags


# ------------------------------------------------------------------------------------ the lock


def lock_rows(
    spec: CellSpec,
    profile: Profile,
    cell: CellSearch,
    chosen: Chosen,
    model: OriginModel,
    primary_seed: int = PRIMARY_SEED,
) -> list[dict[str, Any]]:
    """The cell's locked selections, one row per role (see the module docstring)."""
    if cell.ceiling is None or cell.bank_sha256 is None:
        raise ValueError("a cell without a ceiling or a bank has no selection to lock")
    k = chosen.coefficients
    found: dict[tuple[float, ...], tuple[int, Scored]] = {}
    for i, attempt in enumerate(cell.rows):
        found.setdefault(attempt.scored.weights, (i, attempt.scored))
    anchors = {anchor.name: anchor for anchor in cell.anchors}
    reference = chosen.primary.reference
    basis = torsion_basis(model.moments.cov) if "enb" in cell.measures else None
    inputs_sha256 = model.inputs_sha256
    picks: list[tuple[str, float | None, tuple[float, ...], Selection | None]] = [
        ("R", None, reference.weights, None)
    ]
    for label, measure in MEASURE_ARMS.items():
        if measure in cell.measures:
            for allowance in ALLOWANCES:
                chosen_at = chosen.selections[(measure, allowance)]
                picks.append((label, allowance, chosen_at.selected.weights, chosen_at))
    for arm in cell.arms:
        if arm.native_selection is not None:
            allowance = None if arm.measure is None else arm.allowance
            picks.append((f"{arm.label}:native", allowance, arm.native_selection.weights, None))
    for role, name in (
        ("frontier", f"frontier_{spec.ceiling_id}"),
        ("mdp", f"mdp_{spec.ceiling_id}"),
        ("min_variance", "min_variance"),
        ("equal_weight", "equal_weight"),
    ):
        anchor = anchors[name]
        if anchor.weights is None:
            raise ValueError(f"anchor {name} has no weights in a cell that did not fail")
        picks.append((role, None, anchor.weights, None))
    for measure, member in chosen.widest.items():
        picks.append((f"pool_max_{measure}", None, member.weights, None))

    rows = []
    for role, allowance, weights, selection in picks:
        source_row, s = found[weights]
        guard_allowance = PRIMARY_ALLOWANCE if allowance is None else allowance
        failed = None
        if s.status == OK:
            candidate = Candidate(s.weights, s.bad, s.typical, s.good)
            failed = preference.failed_guards(candidate, reference, guard_allowance, k)
        w = np.asarray(weights, dtype=float)
        try:
            dr2 = measures.dr2_from(w, model.moments.sigma, model.moments.cov)
        except measures.UndefinedMeasure:
            dr2 = None
        rows.append(
            {
                "selection_id": hashlib.sha256(
                    _json([spec.profile, spec.key, role, allowance]).encode("utf-8")
                ).hexdigest(),
                **_identity(spec),
                "stands_for": list(spec.stands_for),
                "aggregation_weight": spec.weight,
                "primary": spec.seed == primary_seed,
                "role": role,
                "allowance": allowance,
                "coefficients": list(k),
                "weights": _weights(weights),
                "source_row": source_row,
                "status": s.status,
                "ruin_day": s.ruin_day,
                "risk": s.risk,
                "ceiling": cell.ceiling,
                "within_ceiling": s.risk <= cell.ceiling + FEASIBILITY_TOL,
                "bound_residual": s.bound_residual,
                "sum_residual": s.sum_residual,
                "risk_residual": s.risk_residual,
                "train_bad": s.bad,
                "train_typical": s.typical,
                "train_good": s.good,
                "train_utility": s.utility,
                "train_mean": s.mean,
                "train_es_25": s.es_25,
                "dr2": dr2,
                "enb": None if basis is None else enb(w, model.moments.cov, basis),
                "expected_return": _expected(model, weights),
                "sacrifice": None if selection is None else selection.sacrifice,
                "guards": None if selection is None else _json(sorted(selection.guards)),
                "excluding_guards": None
                if selection is None
                else _json(list(selection.excluding_guards)),
                "failed_guards": None if failed is None else _json(list(failed)),
                "admissible": None if failed is None else not failed,
                "model_inputs_sha256": inputs_sha256,
                "train_bank_sha256": cell.bank_sha256,
            }
        )
    return rows


def cell_sort_key(cell: CellSpec, profiles: Sequence[str], menus: Sequence[str]) -> tuple:
    """Canonical order of cells, and so of locked and outcome rows: profile, menu, month,
    ceiling, seed (within a cell `lock_rows` already lists the roles in `ROLES` and allowance
    order)."""
    return (
        profiles.index(cell.profile),
        menus.index(cell.menu),
        cell.month,
        cell.fraction,
        cell.seed,
    )


def lock_table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    """Locked rows as a table of `LOCKED_SCHEMA`."""
    return pa.Table.from_pylist(list(rows), schema=LOCKED_SCHEMA)


def write_locked(table: pa.Table, path: Path) -> str:
    """Write the locked selections; returns the SHA-256 of the bytes written."""
    buffer = io.BytesIO()
    pq.write_table(table.cast(LOCKED_SCHEMA), buffer)
    data = buffer.getvalue()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def read_locked(path: str | Path, sha256: str) -> pa.Table:
    """The locked selections, refused unless the file still has the digest of its writing."""
    data = Path(path).read_bytes()
    found = hashlib.sha256(data).hexdigest()
    if found != sha256:
        raise LockedFileChanged(f"{path}: SHA-256 {found}, locked as {sha256}")
    return pq.read_table(io.BytesIO(data))


# ------------------------------------------------------------------------------ evaluation


@dataclass(frozen=True)
class EvaluationTask:
    """The locked rows of one (profile, menu, origin) and what they are evaluated on."""

    profile: str
    menu: str
    month: str
    model: OriginModel
    horizon: Horizon
    locked: str  # the locked selections file
    locked_sha256: str
    test_seeds: tuple[int, ...] = TEST_SEEDS


def _hexes(values: Sequence[float]) -> tuple[str, ...]:
    return tuple(float(value).hex() for value in values)


def evaluate_group(task: EvaluationTask) -> pa.Table:
    """Every locked row of the task's group on its training bank, the test banks and history.

    The rows come back in the locked file's order, as a table of `EVALUATED_SCHEMA`.
    """
    table = read_locked(task.locked, task.locked_sha256)
    want = (task.profile, task.menu, task.month)
    group = (
        (pc.field("profile") == task.profile)
        & (pc.field("menu") == task.menu)
        & (pc.field("month") == task.month)
    )
    rows = table.filter(group).to_pylist()
    if not rows:
        raise ValueError(f"no locked selection for {want}")
    model = task.model
    digest = model.inputs_sha256
    stale = {row["model_inputs_sha256"] for row in rows} - {digest}
    if stale:
        raise ValueError(f"{want}: the locked rows were chosen on another origin model {stale}")
    mixes = np.array([row["weights"] for row in rows], dtype=float)

    simulations = []
    bank_hashes = []
    for seed in task.test_seeds:
        drawn = evaluate.bank(model, seed)
        bank_hashes.append(drawn.index_sha256)
        simulations.append(evaluate.simulate(model, drawn, mixes))
        del drawn
    per_bank = [evaluate.summarize([simulation]) for simulation in simulations]
    pooled = evaluate.summarize(simulations)

    training: dict[int, evaluate.Evaluation] = {}
    positions: dict[int, list[int]] = {}
    for j, row in enumerate(rows):
        positions.setdefault(row["seed"], []).append(j)
    for seed, where in sorted(positions.items()):
        drawn = evaluate.bank(model, seed)
        recorded = {rows[j]["train_bank_sha256"] for j in where}
        if recorded != {drawn.index_sha256}:
            raise InvarianceError(
                f"{want} seed {seed}: optimization bank {recorded} redrawn as {drawn.index_sha256}"
            )
        training[seed] = evaluate.evaluate(model, drawn, mixes[where])
    realized = evaluate.realized(task.horizon, mixes)
    metrics = realized.metrics
    horizon = task.horizon

    out = []
    for j, row in enumerate(rows):
        k = row["coefficients"]
        seed = row["seed"]
        local = positions[seed].index(j)
        figures = training[seed]
        train = {name: float(getattr(figures, name)[local]) for name in evaluate.FIGURES}
        train["utility"] = preference.utility(train["bad"], train["typical"], train["good"], k)
        if row["status"] == OK:
            locked = [
                row[f"train_{name}"]
                for name in ("bad", "typical", "good", "utility", "mean", "es_25")
            ]
            redrawn = [
                train[name] for name in ("bad", "typical", "good", "utility", "mean", "es_25")
            ]
            if _hexes(locked) != _hexes(redrawn):
                raise InvarianceError(
                    f"{want} {row['role']}: locked figures {locked} redrawn as {redrawn}"
                )
        test = {name: float(getattr(pooled, name)[j]) for name in evaluate.FIGURES}
        test["utility"] = preference.utility(test["bad"], test["typical"], test["good"], k)
        result = {
            **row,
            **{f"train_{name}": value for name, value in train.items()},
            "train_status": figures.status[local],
            "train_paths": figures.paths,
            "test_status": pooled.status[j],
            "test_paths": pooled.paths,
            **{f"test_{name}": value for name, value in test.items()},
            "bank_seeds": list(task.test_seeds),
            "bank_index_sha256": bank_hashes,
            "realized_status": realized.status,
            "horizon_start": horizon.days[0] if horizon.days else None,
            "horizon_end": horizon.days[-1] if horizon.days else None,
            "realized_sha256": horizon.returns_sha256,
        }
        for name in evaluate.FIGURES:
            result[f"bank_{name}"] = [float(getattr(one, name)[j]) for one in per_bank]
        result["bank_utility"] = [
            preference.utility(b, t, g, k)
            for b, t, g in zip(
                result["bank_bad"], result["bank_typical"], result["bank_good"], strict=True
            )
        ]
        if metrics is not None:
            y = float(metrics.annual_return[j])
            result.update(
                {
                    "annual_return": y,
                    "loss": bool(metrics.loss[j]),
                    "below_20": bool(metrics.below_20[j]),
                    "worst_day": float(metrics.worst_day[j]),
                    "max_drawdown": float(metrics.max_drawdown[j]),
                    "volatility": float(metrics.volatility[j]),
                }
            )
            for forecast, values in (("train", train), ("test", test)):
                for name, q in QUANTILES:
                    f = values[name]
                    if math.isfinite(f):
                        result[f"{forecast}_pinball_{name}"] = float(evaluate.pinball(q, y, f))
                        result[f"{forecast}_at_or_below_{name}"] = bool(evaluate.at_or_below(y, f))
            if pooled.status[j] == OK:
                outcomes = np.concatenate([simulation.years[:, j] for simulation in simulations])
                result["test_pit"] = evaluate.pit(y, outcomes)
        out.append(result)
    return pa.Table.from_pylist(out, schema=EVALUATED_SCHEMA)


# ---------------------------------------------------------------------------------- outcomes


def finish_outcomes(table: pa.Table, months: Mapping[str, Sequence[str]]) -> pa.Table:
    """The outcomes table: evaluated rows in canonical order plus the cross-row columns.

    ``table`` holds `EVALUATED_SCHEMA` rows already in canonical order (`cell_sort_key`, then
    the locked roles); ``months`` gives each profile's scheduled origins in order, for turnover.
    """
    names = ("profile", "menu", "month", "ceiling_id", "seed", "role", "allowance", "stands_for")
    cols = {name: table[name].to_pylist() for name in names}
    weights = table["weights"].to_pylist()
    annual = table["annual_return"].to_pylist()
    expected = table["expected_return"].to_pylist()
    rows = range(table.num_rows)

    def ident(i: int) -> tuple:
        return tuple(cols[name][i] for name in names[:5])

    reference_return: dict[tuple, float | None] = {}
    by_fraction: dict[tuple, list[float]] = {}
    by_seed: dict[tuple, dict[int, list[float]]] = {}
    for i in rows:
        profile, menu, month, ceiling_id, seed = ident(i)
        role = (cols["role"][i], cols["allowance"][i])
        if role[0] == "R":
            reference_return[ident(i)] = annual[i]
        for ceiling in cols["stands_for"][i]:
            by_fraction[(profile, menu, month, ceiling, seed, *role)] = weights[i]
        by_seed.setdefault((profile, menu, month, ceiling_id, *role), {})[seed] = weights[i]
    added: dict[str, list[Any]] = {name: [] for name in CROSS_ROW}
    for i in rows:
        profile, menu, month, ceiling_id, seed = ident(i)
        role = (cols["role"][i], cols["allowance"][i])
        y = annual[i]
        added["forecast_error"].append(None if y is None else y - expected[i])
        paired = role[0] in MEASURE_ARMS
        base = reference_return.get(ident(i)) if paired else None
        added["paired_role"].append("R" if paired else None)
        added["paired_realized_difference"].append(None if y is None or base is None else y - base)
        sequence = list(months[profile])
        position = sequence.index(month)
        turnover: list[float | None] = []
        for ceiling in cols["stands_for"][i]:
            previous = None
            if position > 0:
                key = (profile, menu, sequence[position - 1], ceiling, seed, *role)
                previous = by_fraction.get(key)
            turnover.append(None if previous is None else 0.5 * _l1(weights[i], previous))
        added["turnover_prev"].append(turnover)
        seeds = by_seed[(profile, menu, month, ceiling_id, *role)]
        others = sorted(other for other in seeds if other != seed)
        added["seed_l1_seeds"].append(others)
        added["seed_l1"].append([_l1(weights[i], seeds[other]) for other in others])
    out = table.cast(EVALUATED_SCHEMA)
    for name in CROSS_ROW:
        out = out.append_column(
            OUTCOMES_SCHEMA.field(name),
            pa.array(added[name], type=OUTCOMES_SCHEMA.field(name).type),
        )
    return out.select(OUTCOMES_SCHEMA.names)


def _l1(a: Sequence[float], b: Sequence[float]) -> float:
    return math.fsum(abs(x - y) for x, y in zip(a, b, strict=True))


def forecast_error_diagnostic(
    frame: pd.DataFrame,
    *,
    profile: str = "stage-1",
    seed: int = PRIMARY_SEED,
    arm: str = "R+D",
    allowance: float = PRIMARY_ALLOWANCE,
) -> pd.DataFrame:
    """Per menu and prescribed risk cell: corr(w_R forecast error, arm minus R realized return).

    Rows: the profile's ``seed`` with complete realized outcomes; a distinct cell counts in every
    prescribed risk cell it stands for. Columns: menu, ceiling_id, n (mature origins with both
    values), correlation (Pearson; None below two origins or without variation) and sign (+1, -1,
    0 or None).
    """
    errors: dict[tuple[str, str, str], float] = {}
    paired: dict[tuple[str, str, str], float] = {}
    for row in frame.to_dict("records"):
        if row["profile"] != profile or row["seed"] != seed or row["realized_status"] != COMPLETE:
            continue
        for ceiling in row["stands_for"]:
            key = (str(row["menu"]), str(ceiling), str(row["month"]))
            if row["role"] == "R":
                errors[key] = float(row["forecast_error"])
            elif row["role"] == arm and row["allowance"] == allowance:
                paired[key] = float(row["paired_realized_difference"])
    groups: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for key in sorted(errors.keys() & paired.keys()):
        groups.setdefault(key[:2], []).append((errors[key], paired[key]))
    out = []
    for (menu, ceiling), pairs in groups.items():
        x = np.array([a for a, _ in pairs])
        y = np.array([b for _, b in pairs])
        correlation = None
        if len(pairs) >= 2 and np.std(x) > 0.0 and np.std(y) > 0.0:
            correlation = float(np.corrcoef(x, y)[0, 1])
        sign = None if correlation is None else int(np.sign(correlation))
        out.append(
            {
                "menu": menu,
                "ceiling_id": ceiling,
                "n": len(pairs),
                "correlation": correlation,
                "sign": sign,
            }
        )
    return pd.DataFrame(out, columns=["menu", "ceiling_id", "n", "correlation", "sign"])
