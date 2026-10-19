"""Selection and the lock: everything decided before an independent draw is read (protocol 5, 9).

The experiment runner (`research.experiment`) schedules cells and runs them; this module turns a
searched cell into rows and locks its selections. It never reads a realized return or draws an
independent bank: the evaluation of what is locked is `research.outcomes`, which imports this
module and never the reverse (tests/research/test_experiment.py checks the import graph).

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
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from portfoliosight.engine import measures, preference
from portfoliosight.engine.preference import Candidate, Selection
from portfoliosight.engine.torsion import enb, torsion_basis
from portfoliosight.research.evaluate import OK, OriginModel
from portfoliosight.research.search import (
    FEASIBILITY_TOL,
    PATH_SEEDS,
    PRIMARY_ALLOWANCE,
    Budget,
    CellSearch,
    Scored,
)

PRIMARY_SEED = PATH_SEEDS[0]
ALLOWANCES = (PRIMARY_ALLOWANCE, 0.0, 0.0005, 0.001)  # 2.5 bp primary, then 0, 5, 10 bp
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
