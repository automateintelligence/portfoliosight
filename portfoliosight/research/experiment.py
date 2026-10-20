"""The return-optimization experiment runner (protocol 4-7 and 9; plan task 6b.5).

`run` executes Stage 1 (R and R+D on both menus), a prespecified sensitivity or Stage 2 from a
verified research snapshot and writes the protocol 9 artifacts; `estimate` measures a small fixed
sample of real cells and projects the CPU cost of Stage 1 plus the sensitivities. The search of
one cell is `research.search`, the selection, lock and search tables `research.selection`, the
evaluation after the lock `research.outcomes`.

Preflight, before any directory is made: the repository is clean (the run names the code by its
HEAD), BLAS is held to one thread (`OPENBLAS/OMP/MKL_NUM_THREADS=1`), the output lies outside the
snapshot, the mirror it was copied from and every git directory, and inside a worktree only where
`git check-ignore` says so (the default `.omx/research/return-optimization/` is excluded), the
TSP investigation sample digest (TSP, 5y, as of 2026-10-16) reproduces `TSP_INVESTIGATION_DIGEST`,
and the investigation's saved tensor (frozen into the snapshot) has its recorded ranges
reproduced: `search.tensor_ranges` recomputes Bad/Typical/Good of its frontier and ladder mixes in
risk columns 36 and 37 one mix at a time with production replay on the reconstructed sample, and
the largest absolute discrepancy must be at most `TENSOR_RANGE_TOLERANCE` (1e-12: per-mix against
the build's batched compounding; the investigation found 0); it is recorded in the manifest
(protocol 5, last paragraph); otherwise a named `Refused` error (`InvestigationMismatch`,
`InvestigationRangesMismatch`). Above 120 scheduled origins the
run stops for a resource amendment (`ScheduleTooLarge`).

Schedule and frozen denominator (protocol 3, 5). The scheduled origins are every common
training-eligible month of the origins ledger (immature months included), in month order. For
each profile, menu and scheduled origin the origin model is built and its risk span computed
(`search.risk_ceilings`); every distinct ceiling (all three, or `x100` alone when the span
collapses, which then stands for `x25`, `x50` and `x100` with their 1/3 weights) and every
optimizer seed of the profile is one cell. That list is the denominator, frozen before any search
and written to the manifest; an origin whose minimum variance cannot be solved, or a sensitivity
lookback without a training window there, yields its cells as failed (`min_variance_unsolved`,
`training_ineligible`) rather than dropping them. A paired cell fails when the search names a
computational error or any required arm fails. `training_ineligible` is not a failure: it leaves
both sides of the failure rate, which is failed cells over the denominator's other cells (the
report counts it the same way). Any unresolved failure prevents a valid completed verdict
(ruling R25); the rate and its 1% line are recorded. Cells a stopped run never finished are
`unattempted` or `interrupted`, never successes.

Order and timing (protocol 7, timing contract). Within each (profile, menu) cells are sorted by
the SHA-256 of their canonical key `[menu, ISO origin, ceiling id, seed]` (the key breaks ties)
and the arm order rotates with the sorted index: R first at even indices, R+D first at odd ones
(with three arms, a cyclic rotation). Each cell is searched by `search.prepare`, then each arm by
`search.run_arm` on a fresh arm-local cache preloaded with the shared broad archive only, timed
from that call to its native selection, then `search.combine` and the selections. `Probe` splits
the time into replay evaluation, measure scoring, the arm's native selection and bank draws; the
rest of an arm is the solver's. Every cell's record goes to `resources.jsonl`. An arm stopped at
the per-arm ceiling keeps its attempts so far in search.parquet (`runner.run_search_task`).

Lock, then evaluate (protocol 5 step 8). When every cell has been searched, the locked selections
of all cells are written to `locked.parquet` and hashed; only then are realized horizons built and
independent banks drawn: the locked file is read back once and verified against its digest, and
the evaluation of each (profile, menu, origin) gets its rows of that file and its origin model,
never a search result (`research.outcomes`, which the search and selection modules never import).

Resources (protocol 7). At most six worker processes (spawned, one BLAS thread each; `workers=0`
runs the cells in this process), aggregate peak RSS of this process and its workers at most
4 GiB (the sum of each process's peak, read from /proc), 300 s per arm (measured, and enforced by
an alarm inside the arm), and 120 CPU-hours for Stage 1 and its sensitivities together (a
sensitivity run counts the CPU its Stage 1 run and earlier sensitivities recorded). The CPU
ceiling changes only through `Limits(cpu_hours=..., cpu_amended=True)` (the CLI's
`--cpu-hours-ceiling`), which the manifest records as an amendment; Stage 2, for which the
protocol states no CPU ceiling, needs one. The first breach stops the run: workers are stopped,
every artifact written so far is kept, and the manifest says `incomplete` with the breach.

Profiles. Stage 1: R and R+D, the five optimizer seeds, every scheduled origin. Sensitivities
(protocol 7), on the six scheduled origins at indices `floor(j (K - 1) / 5)`, every risk cell,
both menus and the primary seed only: `coefficients` re-searches with U coefficients
(.70, .20, .10) and (.50, .35, .15) (R maximizes U, so the arms' objectives change), `lookback`
with 252-row windows (a new ledger and new origin models), `budget` with 2,048 broad points and
768 calls per start. The U-allowance sweep 0, 5 and 10 bp is selection-only from the same pools,
so every Stage 1 cell locks it beside the primary 2.5 bp. Stage 2 adds R+E (ENB) with the same
budgets and a three-arm union, and runs only when the Stage 1 report's `summary.json` says
`{"stage_2": {"run": true}}` (the seam the report writer fills).

Artifacts, under `<out>/<protocol SHA-256 prefix16>/<run id>/` (a sensitivity in
`sensitivity-<name>/` and Stage 2 in `stage-2/` beneath its Stage 1 run): `manifest.json`,
`origins.parquet` (the ledger of every enumerated month with each scheduled origin's model and
ceilings), `search.parquet`, `locked.parquet`, `outcomes.parquet` and `resources.jsonl`; the
schemas are `selection.SEARCH_SCHEMA`, `selection.LOCKED_SCHEMA` and
`outcomes.OUTCOMES_SCHEMA`. `summary.json` and `report.md` are the report writer's. The same
inputs and settings give byte-identical parquet files whatever the number of workers.
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import time
import traceback
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from portfoliosight.engine import preference
from portfoliosight.engine.optimize import SolveError
from portfoliosight.research import harness, outcomes, search, selection
from portfoliosight.research.evaluate import OriginModel, origin_model, realized_horizon
from portfoliosight.research.outcomes import DEFINITIONS, TEST_SEEDS, EvaluationTask
from portfoliosight.research.runner import (
    BLAS_ENV,
    Breach,
    CellResult,
    GroupResult,
    Inline,
    Meter,
    Monitor,
    Processes,
    ProcMeter,
    Resources,
    SearchTask,
    Stop,
    drive,
    utc,
)
from portfoliosight.research.search import (
    ARMS,
    CEILING_IDS,
    CELL_WEIGHT,
    COMPUTATIONAL_ERROR,
    DEFAULT_BUDGET,
    FAILED_ARM,
    FRACTIONS,
    MIN_VARIANCE_UNSOLVED,
    PATH_SEEDS,
    PRIMARY_ALLOWANCE,
    STAGE_1_ARMS,
    TENSOR_RANGE_TOLERANCE,
    TSP_INVESTIGATION_ASOF,
    TSP_INVESTIGATION_COLUMNS,
    TSP_INVESTIGATION_DIGEST,
    TSP_INVESTIGATION_LOOKBACK,
    TSP_INVESTIGATION_TENSOR,
    Budget,
    Ceilings,
)
from portfoliosight.research.selection import (
    ALLOWANCES,
    INTERRUPTED,
    OK_CELL,
    RESOURCE_BREACH,
    TRAINING_INELIGIBLE,
    UNATTEMPTED,
    CellSpec,
    Profile,
    cell_key,
)

PROTOCOL_PATH = "docs/plans/2026-10-18-return-optimization-experiment-protocol.md"
MENU_CAPS = (("tsp", 0.60), ("example", 0.25))  # protocol 3
MAX_WORKERS = 6
# ruling R22 (wording as qualified by the Codex review): the parent prepares serially
PROCESS_MODEL = "1 coordinator (serial preparation, no concurrent compute) + <=6 compute workers"
RSS_CEILING = 4 * 2**30
ARM_SECONDS = 300.0
CPU_HOURS = 120.0
MAX_ORIGINS = harness.MAX_SCHEDULED_ORIGINS
FAILURE_RATE_LIMIT = 0.01
SENSITIVITY_ORIGINS = 6
SENSITIVITY_LOOKBACK = "1y"  # 252 union-calendar rows
SENSITIVITY_COEFFICIENTS = ((0.70, 0.20, 0.10), (0.50, 0.35, 0.15))
SENSITIVITIES = ("coefficients", "lookback", "budget")
FAILED = frozenset({FAILED_ARM, COMPUTATIONAL_ERROR})  # training_ineligible is excluded
INCOMPLETE = frozenset({UNATTEMPTED, INTERRUPTED, RESOURCE_BREACH})
DEPENDENCIES = (
    "numpy", "scipy", "pandas", "pyarrow", "cvxpy", "clarabel", "scikit-learn",
    "exchange_calendars", "threadpoolctl",
)  # fmt: skip
SCHEMA_VERSION = 1


# ------------------------------------------------------------------------------------ errors


class Refused(Exception):
    """The run cannot start: a named precondition fails (CLI exit 7)."""


class DirtyRepository(Refused):
    pass


class BlasThreads(Refused):
    pass


class InvestigationMismatch(Refused):
    pass


class InvestigationRangesMismatch(InvestigationMismatch):
    """The investigation tensor's recorded ranges are not reproduced within the tolerance."""


class ScheduleTooLarge(Refused):
    pass


class StageNotReady(Refused):
    pass


class UnsafeOutput(Refused):
    """The output path is inside the snapshot, the mirror or the repository (CLI exit 2)."""


# ---------------------------------------------------------------------------------- settings


@dataclass(frozen=True)
class Investigation:
    """The TSP investigation sample and saved tensor the harness must reproduce first."""

    menu: str = "tsp"
    lookback: str = TSP_INVESTIGATION_LOOKBACK
    asof: date = TSP_INVESTIGATION_ASOF
    digest: str = TSP_INVESTIGATION_DIGEST
    tensor: str = TSP_INVESTIGATION_TENSOR  # its path in the snapshot
    columns: tuple[int, ...] = TSP_INVESTIGATION_COLUMNS  # the investigation's risk columns


@dataclass(frozen=True)
class Settings:
    """The protocol values a run uses; the defaults are the protocol's (tests reduce them)."""

    lookback: str = "5y"
    seeds: tuple[int, ...] = PATH_SEEDS
    test_seeds: tuple[int, ...] = TEST_SEEDS
    budget: Budget = DEFAULT_BUDGET
    caps: tuple[tuple[str, float], ...] = MENU_CAPS
    months: tuple[str, str] | None = None  # restrict the scheduled origins (never the protocol)
    investigation: Investigation = Investigation()

    def deviations(self) -> list[str]:
        """The names of the settings that are not the protocol's."""
        default = Settings()
        return [
            f.name
            for f in dataclasses.fields(self)
            if getattr(self, f.name) != getattr(default, f.name)
        ]

    def record(self) -> dict[str, Any]:
        return json.loads(json.dumps(dataclasses.asdict(self), default=str))

    def cap(self, menu: str) -> float:
        caps = dict(self.caps)
        if menu not in caps:
            raise ValueError(f"no protocol cap for menu {menu!r}; known: {sorted(caps)}")
        return caps[menu]


@dataclass(frozen=True)
class Limits:
    """The protocol 7 resource ceilings and the worker count."""

    workers: int = MAX_WORKERS
    rss_bytes: int = RSS_CEILING
    arm_seconds: float = ARM_SECONDS
    cpu_hours: float = CPU_HOURS
    cpu_amended: bool = False  # the CPU ceiling was set explicitly: an amendment
    poll_seconds: float = 2.0

    def __post_init__(self) -> None:
        if isinstance(self.workers, bool) or self.workers not in range(MAX_WORKERS + 1):
            raise ValueError(
                f"at most {MAX_WORKERS} worker processes (0: this process); got {self.workers}"
            )
        if not (self.cpu_hours > 0 and self.arm_seconds > 0 and self.rss_bytes > 0):
            raise ValueError("resource ceilings must be positive")
        if not self.cpu_amended and self.cpu_hours != CPU_HOURS:
            raise ValueError("the CPU ceiling changes only as a recorded amendment (cpu_amended)")


PROTOCOL_SETTINGS = Settings()
PROTOCOL_LIMITS = Limits()


@dataclass(frozen=True)
class Provenance:
    """The code a run names: HEAD, its cleanliness, the protocol at HEAD, the repositories."""

    head: str
    dirty: tuple[str, ...]
    protocol_sha256: str
    protocol_status: str
    worktrees: tuple[Path, ...]
    git_dirs: tuple[Path, ...]
    ignored: Callable[[Path], bool] = field(compare=False, repr=False)


@dataclass(frozen=True)
class Inputs:
    """A verified snapshot's ledger inputs and its manifest."""

    data: harness.SnapshotInputs
    manifest: Mapping[str, Any]
    verified_utc: str


def read_inputs(path: str | Path, verify: Callable[[Path], Mapping[str, Any]]) -> Inputs:
    """`harness.read_snapshot` with ``verify``, keeping the verified manifest."""
    kept: dict[str, Mapping[str, Any]] = {}

    def keep(root: Path) -> Mapping[str, Any]:
        kept["manifest"] = verify(root)
        return kept["manifest"]

    data = harness.read_snapshot(path, keep)
    return Inputs(data, kept["manifest"], datetime.now(UTC).isoformat())


# --------------------------------------------------------------------------------- preflight


def blas_environment() -> dict[str, str | None]:
    """The BLAS thread settings; refused unless each is exactly "1"."""
    found = {name: os.environ.get(name) for name in BLAS_ENV}
    wrong = {name: value for name, value in found.items() if value != "1"}
    if wrong:
        raise BlasThreads(
            f"BLAS must run on one thread: set {', '.join(f'{k}=1' for k in wrong)} (found {wrong})"
        )
    return found


def _inside(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def guard_output(path: Path, inputs: Inputs, provenance: Provenance) -> Path:
    """The resolved output root once it is known to be a safe place to write."""
    target = Path(path).expanduser().resolve()
    for label, base in (
        ("the snapshot", inputs.data.root),
        ("the mirror", inputs.data.source_root),
    ):
        if str(base) and _inside(target, Path(base).resolve()):
            raise UnsafeOutput(f"refusing to write {target}: it is inside {label} {base}")
    for base in provenance.git_dirs:
        if _inside(target, base.resolve()):
            raise UnsafeOutput(f"refusing to write {target}: it is inside the git directory {base}")
    for base in provenance.worktrees:
        if _inside(target, base.resolve()) and not provenance.ignored(target):
            raise UnsafeOutput(
                f"refusing to write {target}: it is inside the worktree {base} and not git-ignored"
            )
    return target


def check_investigation(inputs: Inputs, investigation: Investigation) -> dict[str, Any]:
    """Reproduce the TSP investigation's sample digest and recorded ranges, or refuse the run.

    Returns what the manifest records: the reproduced digest and the range check (module
    docstring, preflight).
    """
    funds = inputs.data.menus.get(investigation.menu)
    if funds is None:
        raise InvestigationMismatch(f"the snapshot has no {investigation.menu!r} menu")
    try:
        digest = search.production_sample_digest(
            inputs.data.records, funds, investigation.lookback, investigation.asof
        )
    except ValueError as exc:
        raise InvestigationMismatch(f"the investigation sample cannot be rebuilt: {exc}") from exc
    if digest != investigation.digest:
        raise InvestigationMismatch(
            f"the {investigation.menu} {investigation.lookback} sample as of "
            f"{investigation.asof} has digest {digest}, the investigation {investigation.digest}"
        )
    raw = inputs.data.tensors.get(investigation.tensor)
    if raw is None:
        raise InvestigationMismatch(
            f"the snapshot holds no investigation tensor {investigation.tensor}"
        )
    try:
        tensor = json.loads(raw)
        check = search.tensor_ranges(
            inputs.data.records,
            funds,
            investigation.lookback,
            investigation.asof,
            tensor,
            investigation.columns,
        )
    except ValueError as exc:
        raise InvestigationMismatch(
            f"the investigation tensor's ranges cannot be recomputed: {exc}"
        ) from exc
    ranges = {
        "tensor": investigation.tensor,
        "tensor_sha256": hashlib.sha256(raw).hexdigest(),
        **check.record(),
        "tolerance": TENSOR_RANGE_TOLERANCE,
        "note": "per-mix replay (BLAS gemv) against the build's batched one_year_ranges (gemm): "
        "summation order differs by about 1e-14",
    }
    if not check.max_abs_discrepancy <= TENSOR_RANGE_TOLERANCE:
        raise InvestigationRangesMismatch(
            f"the investigation tensor's recorded ranges differ by {check.max_abs_discrepancy!r} "
            f"(at {check.worst}), more than {TENSOR_RANGE_TOLERANCE}"
        )
    return {"reproduced": digest, "ranges": ranges}


# ----------------------------------------------------------------------------------- profiles


def profiles(stage: int, sensitivity: str | None, settings: Settings) -> tuple[Profile, ...]:
    """The profiles one run executes (see the module docstring)."""
    base = Profile(
        name="stage-1",
        lookback=settings.lookback,
        budget=settings.budget,
        coefficients=preference.COEFFICIENTS,
        arms=STAGE_1_ARMS,
        seeds=settings.seeds,
        origins="scheduled",
    )
    if stage == 2:
        if sensitivity is not None:
            raise ValueError("the sensitivities belong to Stage 1")
        return (replace(base, name="stage-2", arms=ARMS),)
    if stage != 1:
        raise ValueError(f"stage must be 1 or 2, got {stage}")
    if sensitivity is None:
        return (base,)
    primary = replace(base, seeds=(settings.seeds[0],), origins="sensitivity")
    if sensitivity == "coefficients":
        return tuple(
            replace(
                primary,
                name="coefficients-" + "-".join(f"{round(100 * x)}" for x in k),
                coefficients=k,
            )
            for k in SENSITIVITY_COEFFICIENTS
        )
    if sensitivity == "lookback":
        rows = harness.LOOKBACK_ROWS[SENSITIVITY_LOOKBACK]
        return (replace(primary, name=f"lookback-{rows}", lookback=SENSITIVITY_LOOKBACK),)
    if sensitivity == "budget":
        b = settings.budget
        doubled = Budget(
            points=2 * b.points, starts=b.starts, calls=2 * b.calls, maxiter=2 * b.maxiter
        )
        return (replace(primary, name="budget-x2", budget=doubled),)
    raise ValueError(f"unknown sensitivity {sensitivity!r}; expected one of {SENSITIVITIES}")


def sensitivity_months(months: Sequence[str], count: int = SENSITIVITY_ORIGINS) -> tuple[str, ...]:
    """The origins at indices `floor(j (K - 1) / (count - 1))`, j = 0..count-1, each once."""
    k = len(months)
    if k == 0:
        return ()
    indices = sorted({j * (k - 1) // (count - 1) for j in range(count)})
    return tuple(months[i] for i in indices)


def arm_order(arms: Sequence[str], index: int) -> tuple[str, ...]:
    """The arms rotated by the cell's sorted index: R first at even indices with two arms."""
    shift = index % len(arms)
    return tuple(arms[shift:]) + tuple(arms[:shift])


# ----------------------------------------------------------------------------------- schedule


@dataclass(frozen=True)
class OriginFacts:
    """One menu at one origin under one lookback: its model and risk span, or why there is none."""

    lookback: str
    month: str
    menu: str
    model: OriginModel | None
    ceilings: Ceilings | None
    error: str | None
    detail: str | None


@dataclass(frozen=True)
class Schedule:
    menus: tuple[str, ...]
    ledgers: Mapping[str, harness.Ledger]  # by lookback
    scheduled: tuple[str, ...]  # common training-eligible months of the base ledger
    sensitivity: tuple[str, ...]  # the six indexed months
    profiles: tuple[Profile, ...]
    origins: Mapping[tuple[str, str, str], OriginFacts]  # (lookback, month, menu)
    cells: tuple[CellSpec, ...]  # in execution order

    def months(self, profile: Profile) -> tuple[str, ...]:
        return self.scheduled if profile.origins == "scheduled" else self.sensitivity

    def profile(self, name: str) -> Profile:
        return next(p for p in self.profiles if p.name == name)

    def caps(self, settings: Settings, menu: str) -> tuple[float, ...]:
        funds = dict(self.ledgers[settings.lookback].menus)[menu]
        return (settings.cap(menu),) * len(funds)


def build_schedule(
    inputs: Inputs,
    settings: Settings,
    run_profiles: Sequence[Profile],
    *,
    max_origins: int | None = MAX_ORIGINS,
) -> Schedule:
    """Ledgers, origin models, ceilings and every cell, in execution order (module docstring)."""
    data = inputs.data
    menus = {name: tuple(funds) for name, funds in data.menus.items()}
    for name in menus:
        settings.cap(name)
    ledgers = {
        settings.lookback: harness.build_ledger(
            data.records, data.sessions, data.d_star, menus, settings.lookback
        )
    }
    base = ledgers[settings.lookback]
    first, last = settings.months or (None, None)
    scheduled = tuple(
        row.month
        for row in base.rows
        if row.training_eligible
        and (first is None or row.month >= first)
        and (last is None or row.month <= last)
    )
    if not scheduled:
        raise Refused("the ledger has no common training-eligible origin to schedule")
    if max_origins is not None and len(scheduled) > max_origins:
        raise ScheduleTooLarge(
            f"{len(scheduled)} common training-eligible origins are scheduled, more than "
            f"{max_origins}: stop for a resource-plan amendment (protocol 4)"
        )
    six = sensitivity_months(scheduled)
    for profile in run_profiles:
        if profile.lookback not in ledgers:
            ledgers[profile.lookback] = harness.build_ledger(
                data.records, data.sessions, data.d_star, menus, profile.lookback
            )
    origins: dict[tuple[str, str, str], OriginFacts] = {}
    cells: list[CellSpec] = []
    for profile in run_profiles:
        months = scheduled if profile.origins == "scheduled" else six
        ledger = ledgers[profile.lookback]
        for menu, funds in menus.items():
            caps = (settings.cap(menu),) * len(funds)
            block = []
            for month in months:
                key = (profile.lookback, month, menu)
                if key not in origins:
                    origins[key] = _origin_facts(data.records, ledger, month, menu, caps)
                block += _cells(profile, origins[key], ledger.row(month).origin)
            block.sort(key=lambda cell: (cell.sha256, cell.key))
            cells += [
                replace(cell, menu_index=i, arm_order=arm_order(profile.arms, i))
                for i, cell in enumerate(block)
            ]
    cells = [replace(cell, order=i) for i, cell in enumerate(cells)]
    return Schedule(
        menus=tuple(menus),
        ledgers=ledgers,
        scheduled=scheduled,
        sensitivity=six,
        profiles=tuple(run_profiles),
        origins=origins,
        cells=tuple(cells),
    )


def _origin_facts(records, ledger: harness.Ledger, month: str, menu: str, caps) -> OriginFacts:
    entry = ledger.row(month).menu(menu)
    if not entry.training_eligible:
        reasons = ", ".join(map(harness.issue_text, entry.issues)) or ledger.row(month).status
        return OriginFacts(ledger.lookback, month, menu, None, None, TRAINING_INELIGIBLE, reasons)
    model = origin_model(records, ledger, month, menu)
    try:
        ceilings = search.risk_ceilings(model, caps)
    except SolveError as exc:
        return OriginFacts(
            ledger.lookback, month, menu, model, None, MIN_VARIANCE_UNSOLVED, str(exc)
        )
    return OriginFacts(ledger.lookback, month, menu, model, ceilings, None, None)


def _cells(profile: Profile, facts: OriginFacts, origin: date) -> list[CellSpec]:
    out = []
    ceilings = facts.ceilings
    distinct = FRACTIONS if ceilings is None else ceilings.distinct
    for fraction in distinct:
        if ceilings is None:
            stands_for = (CEILING_IDS[fraction],)
        else:
            stands_for = tuple(
                CEILING_IDS[f] for f in FRACTIONS if ceilings.alias_of(f) == fraction
            )
        ceiling_id = CEILING_IDS[fraction]
        for seed in profile.seeds:
            key = cell_key(facts.menu, origin, ceiling_id, seed)
            out.append(
                CellSpec(
                    profile=profile.name,
                    menu=facts.menu,
                    month=facts.month,
                    origin=origin,
                    lookback=profile.lookback,
                    ceiling_id=ceiling_id,
                    fraction=fraction,
                    seed=seed,
                    stands_for=stands_for,
                    weight=CELL_WEIGHT * len(stands_for),
                    key=key,
                    sha256=hashlib.sha256(key.encode("utf-8")).hexdigest(),
                    preset=facts.error,
                    preset_detail=facts.detail,
                )
            )
    return out


def denominator(schedule: Schedule) -> dict[str, Any]:
    """The frozen cell denominator: every scheduled cell, written before any search."""
    listing = [
        {
            "profile": cell.profile,
            "key": cell.key,
            "sha256": cell.sha256,
            "menu": cell.menu,
            "month": cell.month,
            "ceiling_id": cell.ceiling_id,
            "seed": cell.seed,
            "stands_for": list(cell.stands_for),
            "weight": cell.weight,
            "order": cell.order,
            "menu_index": cell.menu_index,
            "arm_order": list(cell.arm_order),
            "preset_failure": cell.preset,
        }
        for cell in schedule.cells
    ]
    counts = Counter((cell.profile, cell.menu) for cell in schedule.cells)
    canonical = json.dumps(
        [entry["key"] + "|" + entry["profile"] for entry in listing], separators=(",", ":")
    )
    return {
        "cells": len(listing),
        "by_profile_menu": {f"{p}/{m}": n for (p, m), n in sorted(counts.items())},
        "collapsed_aliases": sum(len(cell.stands_for) - 1 for cell in schedule.cells),
        "preset_failures": sum(cell.preset is not None for cell in schedule.cells),
        "cells_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "listing": listing,
    }


# ------------------------------------------------------------------------------------- the run


@dataclass(frozen=True)
class RunResult:
    directory: Path
    status: str  # complete | incomplete
    breach: Breach | None
    cells: int
    outcome: Mapping[str, Any]


def _write_json(path: Path, body: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _directory(
    out_root: Path,
    provenance: Provenance,
    inputs: Inputs,
    settings: Settings,
    stage: int,
    sensitivity: str | None,
    run_id: str | None,
) -> tuple[Path, str, float]:
    """The run directory (not yet made), its run id and the CPU seconds already spent."""
    base = out_root / provenance.protocol_sha256[:16]
    if stage == 1 and sensitivity is None:
        name = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        target = base / name
        if target.exists():
            raise Refused(f"the run directory {target} already exists")
        return target, name, 0.0
    if run_id is None:
        raise StageNotReady("a sensitivity or Stage 2 run names its Stage 1 run (run id)")
    first = base / run_id
    manifest_path = first / "manifest.json"
    if not manifest_path.exists():
        raise StageNotReady(f"no Stage 1 run at {first}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status", {}).get("state") != "complete":
        raise StageNotReady(f"the Stage 1 run {first} is not complete")
    same = (
        manifest["code"]["head"] == provenance.head
        and manifest["data"]["snapshot_manifest_sha256"] == inputs.data.manifest_sha256
        and manifest["settings"] == settings.record()
    )
    if not same:
        raise StageNotReady(f"{first} was run on other code, data or settings")
    if stage == 2:
        summary = first / "summary.json"
        verdict = json.loads(summary.read_text(encoding="utf-8")) if summary.exists() else {}
        if verdict.get("stage_2", {}).get("run") is not True:
            raise StageNotReady(f"{summary} does not authorize Stage 2 (stage_2.run is not true)")
        target = first / "stage-2"
        spent = 0.0
    else:
        target = first / f"sensitivity-{sensitivity}"
        spent = float(manifest["execution"]["cpu_seconds"])
        for other in sorted(first.glob("sensitivity-*/manifest.json")):
            spent += float(
                json.loads(other.read_text(encoding="utf-8"))["execution"]["cpu_seconds"]
            )
    if target.exists():
        raise Refused(f"{target} already exists")
    return target, run_id, spent


def run(
    inputs: Inputs,
    provenance: Provenance,
    out_root: Path,
    *,
    settings: Settings = PROTOCOL_SETTINGS,
    limits: Limits = PROTOCOL_LIMITS,
    stage: int = 1,
    sensitivity: str | None = None,
    run_id: str | None = None,
    meter: Meter | None = None,
    clock: Callable[[], float] = time.perf_counter,
    alarm: bool = True,
    reviews: Sequence[str] = (),
) -> RunResult:
    """Run Stage 1, a sensitivity or Stage 2 and write its artifacts (module docstring).

    ``reviews`` are recorded verbatim in the manifest's `reviews` (ruling R28), never read.
    """
    run_profiles = profiles(stage, sensitivity, settings)
    if stage == 2 and not limits.cpu_amended:
        raise Refused("the protocol states no Stage 2 CPU ceiling: set one as an amendment")
    if provenance.dirty:
        raise DirtyRepository(
            f"uncommitted changes to tracked files: {', '.join(provenance.dirty)}"
        )
    blas = blas_environment()
    meter = meter or ProcMeter()  # from here on, this process's CPU is the run's
    root = guard_output(out_root, inputs, provenance)
    reproduced = check_investigation(inputs, settings.investigation)
    directory, name, cpu_before = _directory(
        root, provenance, inputs, settings, stage, sensitivity, run_id
    )
    schedule = build_schedule(inputs, settings, run_profiles)
    directory.mkdir(parents=True)
    pq.write_table(_origins_table(schedule), directory / "origins.parquet")
    manifest = _manifest(
        inputs, provenance, settings, limits, schedule, stage, sensitivity, name, reproduced, blas
    )
    manifest["reviews"] = [str(entry) for entry in reviews]
    manifest_path = directory / "manifest.json"
    _write_json(manifest_path, manifest)
    resources = Resources(directory / "resources.jsonl")
    monitor = Monitor(limits.rss_bytes, limits.cpu_hours, meter, cpu_before)
    resources.write({"kind": "run", "event": "start", "utc": utc(), "cpu_before": cpu_before})
    started = time.monotonic()
    pool: Any = None
    state = "complete"
    stop = Stop()
    outcome: dict[str, Any] = {}
    try:
        pool = Inline(clock, alarm) if limits.workers == 0 else Processes(limits.workers)
        for worker in pool.workers:
            resources.write(worker)
        stop, results = _search_phase(
            schedule, settings, limits, pool, monitor, resources, directory
        )
        outcome = _denominator_outcome(schedule, results, stop)
        if stop.breach is None:
            locked_sha256 = _lock(schedule, results, directory, resources)
            manifest["lock"] = {"file": "locked.parquet", "sha256": locked_sha256, "utc": utc()}
            _write_json(manifest_path, manifest)
            stop = _evaluation_phase(
                schedule,
                settings,
                limits,
                pool,
                monitor,
                resources,
                directory,
                inputs,
                locked_sha256,
            )
        if stop.breach is not None:
            state = "incomplete"
    except BaseException as exc:
        state = "error"
        manifest["status"] = {
            "state": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        raise
    finally:
        if pool is not None:
            (pool.close if state == "complete" else pool.terminate)()
        for sample in monitor.samples:
            resources.write(sample)
        monitor.check([])
        wall = time.monotonic() - started
        resources.write(
            {
                "kind": "run",
                "event": "end",
                "utc": utc(),
                "state": state,
                "wall": wall,
                "cpu_seconds": monitor.cpu_seconds,
                "rss_peak": monitor.rss_peak,
                "peak_bytes": monitor.peak_bytes,
            }
        )
        resources.close()
        if state != "error":
            manifest["status"] = {
                "state": state,
                "breach": None
                if stop.breach is None
                else {"rule": stop.breach.rule, "limit": stop.breach.limit},
                "denominator": outcome,
            }
        manifest["run"]["finished_utc"] = utc()
        manifest["execution"].update(
            {
                "wall_seconds": wall,
                "cpu_seconds": monitor.cpu_seconds,
                "cpu_before": cpu_before,
                "rss_peak_bytes": monitor.rss_peak,
                "peak_bytes_sum": monitor.peak_bytes,
                "breach": None if stop.breach is None else stop.breach.record(),
                "workers": [] if pool is None else pool.workers,
                "resources_sha256": _sha256(directory / "resources.jsonl"),
            }
        )
        manifest["artifacts"] = {
            path.name: _sha256(path) for path in sorted(directory.glob("*.parquet"))
        }
        _write_json(manifest_path, manifest)
    return RunResult(directory, state, stop.breach, len(schedule.cells), outcome)


def _search_tasks(
    schedule: Schedule, settings: Settings, limits: Limits
) -> list[tuple[int, SearchTask]]:
    tasks = []
    for cell in schedule.cells:
        facts = schedule.origins[(cell.lookback, cell.month, cell.menu)]
        tasks.append(
            (
                cell.order,
                SearchTask(
                    cell=cell,
                    profile=schedule.profile(cell.profile),
                    model=facts.model,
                    ceilings=facts.ceilings,
                    caps=schedule.caps(settings, cell.menu),
                    arm_seconds=limits.arm_seconds,
                ),
            )
        )
    return tasks


def _search_phase(
    schedule: Schedule,
    settings: Settings,
    limits: Limits,
    pool: Any,
    monitor: Monitor,
    resources: Resources,
    directory: Path,
) -> tuple[Stop, dict[int, CellResult]]:
    """Every cell, written to search.parquet in schedule order; the results by order."""
    results: dict[int, CellResult] = {}
    written = 0
    writer = pq.ParquetWriter(directory / "search.parquet", selection.SEARCH_SCHEMA)

    def handle(index: int, result: CellResult) -> Breach | None:
        nonlocal written
        results[index] = result
        resources.write(result.resources)
        while written in results:  # in schedule order, then the rows are let go
            done = results[written]
            if done.table is not None:
                writer.write_table(done.table)
            results[written] = replace(done, table=None)
            written += 1
        return result.breach

    try:
        stop = drive(
            pool, _search_tasks(schedule, settings, limits), monitor, limits.poll_seconds, handle
        )
        if stop.breach is not None:
            resources.write({"kind": "breach", "utc": utc(), **stop.breach.record()})
        for cell in schedule.cells[written:]:
            if cell.order in results:
                done = results[cell.order]
                if done.table is not None:
                    writer.write_table(done.table)
                results[cell.order] = replace(done, table=None)
            else:
                status = INTERRUPTED if cell.order in stop.interrupted else UNATTEMPTED
                row = selection.cell_row(cell, status, profile=schedule.profile(cell.profile))
                writer.write_table(selection.status_table([row]))
    finally:
        writer.close()
    return stop, results


def _denominator_outcome(
    schedule: Schedule, results: Mapping[int, CellResult], stop: Stop
) -> dict[str, Any]:
    statuses = Counter()
    for cell in schedule.cells:
        if cell.order in results:
            statuses[results[cell.order].status] += 1
        elif cell.order in stop.interrupted:
            statuses[INTERRUPTED] += 1
        else:
            statuses[UNATTEMPTED] += 1
    total = len(schedule.cells)
    ineligible = statuses[TRAINING_INELIGIBLE]
    base = total - ineligible
    failed = sum(n for status, n in statuses.items() if status in FAILED)
    incomplete = sum(n for status, n in statuses.items() if status in INCOMPLETE)
    rate = failed / base if base else 0.0
    return {
        "cells": total,
        "completed": statuses[OK_CELL],
        "training_ineligible_excluded": ineligible,
        "failure_denominator": base,
        "failed": failed,
        "incomplete": incomplete,
        "by_status": dict(sorted(statuses.items())),
        "failure_rate": rate,
        "failure_rate_above_limit": rate > FAILURE_RATE_LIMIT,
        "failure_rate_limit": FAILURE_RATE_LIMIT,
    }


def _lock(
    schedule: Schedule, results: Mapping[int, CellResult], directory: Path, resources: Resources
) -> str:
    """Write every locked selection, before any independent draw or realized return is read."""
    table = _locked(schedule, results)
    digest = selection.write_locked(table, directory / "locked.parquet")
    resources.write({"kind": "lock", "utc": utc(), "rows": table.num_rows, "sha256": digest})
    return digest


def _locked(schedule: Schedule, results: Mapping[int, CellResult]) -> pa.Table:
    """Every cell's locked rows, cells in canonical order (`selection.cell_sort_key`)."""
    names = [profile.name for profile in schedule.profiles]
    ordered = sorted(
        results.values(), key=lambda r: selection.cell_sort_key(r.cell, names, schedule.menus)
    )
    return pa.concat_tables([selection.lock_table([]), *(result.locked for result in ordered)])


def _evaluation_tasks(
    schedule: Schedule, settings: Settings, inputs: Inputs, path: Path, digest: str
) -> list[tuple[int, EvaluationTask]]:
    """One task per (profile, menu, origin) of the locked file, in its order.

    The file is read and verified against its digest once, here; each task carries its rows.
    """
    table = selection.read_locked(path, digest)
    tasks = []
    for index, ((name, menu, month), rows) in enumerate(outcomes.evaluation_groups(table)):
        profile = schedule.profile(name)
        facts = schedule.origins[(profile.lookback, month, menu)]
        if facts.model is None:
            raise RuntimeError(f"{name} {menu} {month}: locked rows without an origin model")
        # the realized horizon is read here, after the lock, and only here
        horizon = realized_horizon(
            inputs.data.records, schedule.ledgers[profile.lookback], month, menu
        )
        task = EvaluationTask(
            name, menu, month, facts.model, horizon, tuple(rows), digest, settings.test_seeds
        )
        tasks.append((index, task))
    return tasks


def _evaluation_phase(
    schedule: Schedule,
    settings: Settings,
    limits: Limits,
    pool: Any,
    monitor: Monitor,
    resources: Resources,
    directory: Path,
    inputs: Inputs,
    locked_sha256: str,
) -> Stop:
    """Evaluate the locked selections group by group, then write outcomes.parquet."""
    tasks = _evaluation_tasks(
        schedule, settings, inputs, directory / "locked.parquet", locked_sha256
    )
    tables: dict[int, pa.Table] = {}

    def handle(index: int, result: GroupResult) -> Breach | None:
        tables[index] = result.rows
        resources.write(result.resources)
        return None

    stop = drive(pool, tasks, monitor, limits.poll_seconds, handle)
    if stop.breach is not None:
        resources.write({"kind": "breach", "utc": utc(), **stop.breach.record()})
    evaluated = pa.concat_tables(
        [pa.Table.from_pylist([], schema=outcomes.EVALUATED_SCHEMA)]
        + [tables[index] for index in sorted(tables)]
    )
    months = {profile.name: schedule.months(profile) for profile in schedule.profiles}
    pq.write_table(outcomes.finish_outcomes(evaluated, months), directory / "outcomes.parquet")
    return stop


# ------------------------------------------------------------------------------------ manifest


def _versions() -> dict[str, str | None]:
    found = {}
    for name in DEPENDENCIES:
        try:
            found[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            found[name] = None
    return found


def _manifest(
    inputs: Inputs,
    provenance: Provenance,
    settings: Settings,
    limits: Limits,
    schedule: Schedule,
    stage: int,
    sensitivity: str | None,
    run_id: str,
    reproduced: Mapping[str, Any],
    blas: Mapping[str, str | None],
) -> dict[str, Any]:
    snapshot = inputs.manifest
    base = schedule.ledgers[settings.lookback]
    coverage = harness.coverage(base)
    return {
        "schema_version": SCHEMA_VERSION,
        "run": {"id": run_id, "created_utc": utc(), "finished_utc": None},
        "stage": stage,
        "sensitivity": sensitivity,
        "status": {"state": "running"},
        "protocol": {
            "path": PROTOCOL_PATH,
            "sha256": provenance.protocol_sha256,
            "prefix": provenance.protocol_sha256[:16],
            "status": provenance.protocol_status,
        },
        "code": {"head": provenance.head, "dirty": False},
        "reviews": [],
        "settings": settings.record(),
        "deviations_from_protocol": settings.deviations(),
        "profiles": [
            {**dataclasses.asdict(profile), "budget": dataclasses.asdict(profile.budget)}
            for profile in schedule.profiles
        ],
        "preference": {
            "coefficients": list(preference.COEFFICIENTS),
            "guards": {
                "bad": preference.BAD_GUARD,
                "typical": preference.TYPICAL_GUARD,
                "good": preference.GOOD_GUARD,
            },
            "u_allowance_primary": PRIMARY_ALLOWANCE,
            "u_allowances_evaluated": list(ALLOWANCES),
            "veto_tolerance": preference.VETO_TOLERANCE,
            "dominance_tolerance": preference.DOMINANCE_TOLERANCE,
            "tie_tolerance": preference.TIE_TOLERANCE,
            "binding_tolerance": preference.BINDING_TOLERANCE,
        },
        "search": {
            "path_seeds": list(settings.seeds),
            "generator_offset": search.GENERATOR_OFFSET,
            "independent_bank_seeds": list(settings.test_seeds),
            "primary_seed": settings.seeds[0],
            "paths": 2000,
            "mean_block_days": 21,
            "horizon_days": 252,
            "rhobeg": search.RHOBEG,
            "tol": search.COBYLA_TOL,
            "catol": search.CATOL,
            "feasibility_tolerance": search.FEASIBILITY_TOL,
            "penalty": search.PENALTY,
            "start_spacing": search.START_SPACING,
            "ceiling_fractions": list(FRACTIONS),
            "collapse_tolerance": search.COLLAPSE_TOL,
        },
        "estimator": {
            "covariance": "production portfoliosight.engine.stats.estimate_moments, fixed window: "
            "Ledoit-Wolf shrinkage of the standardized returns' correlation, ddof=1 volatilities, "
            "sigma floor 1e-4; shrinkage recorded per origin and menu",
            "mu_s": "production menu_beta_blend at the origin's risk-free rate",
            "risk_free": "SGOV's last 252 own-date returns at the origin, else TSP-G's, else 4%",
        },
        "definitions": DEFINITIONS,
        "menus": {
            name: {"funds": list(dict(base.menus)[name]), "cap": settings.cap(name)}
            for name in schedule.menus
        },
        "data": {
            "snapshot": str(inputs.data.root),
            "snapshot_manifest_sha256": inputs.data.manifest_sha256,
            "verified_utc": inputs.verified_utc,
            "verification": "verify_snapshot: every file re-hashed, read-only, name matches",
            "source_root": inputs.data.source_root,
            "d_star": inputs.data.d_star.isoformat(),
            "files": [
                {"path": f["path"], "sha256": f["sha256"]} for f in snapshot.get("files", [])
            ],
            "calendar": snapshot.get("calendar"),
            "risk_free": snapshot.get("risk_free"),
            "dependency_lock": snapshot.get("dependency_lock"),
            "investigation": {**dataclasses.asdict(settings.investigation), **reproduced},
        },
        "ledger": {
            "lookback": base.lookback,
            "boundary_month": base.boundary_month,
            "boundary_fund": base.boundary_fund,
            "boundary_date": base.boundary_date.isoformat(),
            "boundary_reason": harness.PREHISTORY,
            "months": len(base.rows),
            "counts": coverage.counts,
            "scheduled_origins": len(schedule.scheduled),
            "mature_origins": coverage.mature,
            "sensitivity_origins": list(schedule.sensitivity),
            "max_origins": MAX_ORIGINS,
        },
        "denominator": denominator(schedule),
        "limits": {
            "workers": limits.workers,
            "max_workers": MAX_WORKERS,
            "process_model": PROCESS_MODEL
            if limits.workers
            else "in-process: the coordinator computes every cell (workers=0)",
            "rss_bytes": limits.rss_bytes,
            "arm_seconds": limits.arm_seconds,
            "cpu_hours": limits.cpu_hours,
            "cpu_hours_amendment": limits.cpu_amended,
            "cpu_scope": "Stage 2 alone"
            if stage == 2
            else "Stage 1 and its sensitivities together",
        },
        "execution": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "blas_env": dict(blas),
            "process_start": "spawn",
            "dependencies": _versions(),
        },
    }


def _origins_table(schedule: Schedule) -> pa.Table:
    """Every enumerated month of each ledger used, with each scheduled origin's model facts."""
    position = {month: i for i, month in enumerate(schedule.scheduled)}
    frames = []
    for lookback, ledger in schedule.ledgers.items():
        frame = harness.ledger_frame(ledger)
        facts = [
            schedule.origins.get((lookback, month, menu))
            for month, menu in zip(frame["month"], frame["menu"], strict=True)
        ]
        models = [None if f is None else f.model for f in facts]
        spans = [None if f is None else f.ceilings for f in facts]
        frame["scheduled"] = frame["month"].isin(list(position))
        frame["schedule_index"] = pd.array([position.get(m) for m in frame["month"]], dtype="Int64")
        frame["sensitivity_origin"] = frame["month"].isin(list(schedule.sensitivity))
        frame["model_error"] = pd.array(
            [None if f is None else f.error for f in facts], dtype="string"
        )
        frame["shrinkage"] = _floats([None if m is None else m.moments.shrinkage for m in models])
        frame["sample_sha256"] = pd.array(
            [None if m is None else m.sample_sha256 for m in models], dtype="string"
        )
        frame["model_inputs_sha256"] = pd.array(
            [None if m is None else m.inputs_sha256 for m in models], dtype="string"
        )
        for name in ("sigma_min", "sigma_top"):
            frame[name] = _floats([None if c is None else getattr(c, name) for c in spans])
        frame["collapsed"] = pd.array(
            [None if c is None else c.collapsed for c in spans], dtype="boolean"
        )
        for fraction, ceiling_id in CEILING_IDS.items():
            frame[f"ceiling_{ceiling_id}"] = _floats(
                [None if c is None else c.value(fraction) for c in spans]
            )
        frames.append(pa.Table.from_pandas(frame, preserve_index=False))
    return pa.concat_tables(frames)


def _floats(values: Sequence[float | None]) -> pd.Series:
    return pd.Series([math.nan if v is None else float(v) for v in values], dtype="float64")


# ------------------------------------------------------------------------------------ estimate


@dataclass(frozen=True)
class Projection:
    directory: Path
    sample_cells: int
    scheduled_origins: int
    stage_1_cells: Mapping[str, int]
    search_cpu_per_cell: Mapping[str, float]
    evaluation_cpu_per_mix: float
    parts: Mapping[str, float]  # CPU seconds by part
    total_cpu_hours: float
    cpu_hours_ceiling: float
    max_arm_seconds: float

    @property
    def fits(self) -> bool:
        return self.total_cpu_hours <= self.cpu_hours_ceiling


def estimate(
    inputs: Inputs,
    provenance: Provenance,
    out_root: Path,
    *,
    settings: Settings = PROTOCOL_SETTINGS,
    limits: Limits = PROTOCOL_LIMITS,
    estimate_id: str | None = None,
    meter: Meter | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> Projection:
    """Search, lock and evaluate a fixed sample of real cells; project Stage 1 + sensitivities.

    The sample: the six sensitivity origins, both menus, the X(.50) cell (the a = 1 cell when the
    span collapses) and the primary seed, with full budgets. The projection multiplies the mean
    search CPU per cell of each menu by its Stage 1 cells, and by the sensitivity cells (two
    coefficient profiles, the lookback profile at the 5y cost, the doubled budget at twice it),
    adds evaluation at the measured CPU per locked mix and the measured scheduling cost per run.
    It is written under `<out>/<prefix16>/estimates/<id>/` and is not a run.
    """
    blas_environment()
    meter = meter or ProcMeter()
    root = guard_output(out_root, inputs, provenance)
    check_investigation(inputs, settings.investigation)
    name = estimate_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory = root / provenance.protocol_sha256[:16] / "estimates" / name
    started_cpu = time.process_time()
    stage_1 = profiles(1, None, settings)
    schedule = build_schedule(inputs, settings, stage_1, max_origins=None)
    scheduling_cpu = time.process_time() - started_cpu
    sample = [
        cell
        for cell in schedule.cells
        if cell.month in schedule.sensitivity
        and cell.seed == settings.seeds[0]
        and cell.ceiling_id == ("x50" if len(cell.stands_for) == 1 else "x100")
    ]
    directory.mkdir(parents=True)
    resources = Resources(directory / "resources.jsonl")
    monitor = Monitor(limits.rss_bytes, limits.cpu_hours, meter)
    pool: Any = Inline(clock, True) if limits.workers == 0 else Processes(limits.workers)
    results: dict[int, CellResult] = {}
    groups: list[GroupResult] = []
    chosen = set(sample)
    try:
        for worker in pool.workers:
            resources.write(worker)
        tasks = [
            (i, task)
            for i, (_, task) in enumerate(
                t for t in _search_tasks(schedule, settings, limits) if t[1].cell in chosen
            )
        ]

        def keep(index: int, result: CellResult) -> Breach | None:
            results[index] = result
            resources.write(result.resources)
            return result.breach

        stop = drive(pool, tasks, monitor, limits.poll_seconds, keep)
        if stop.breach is None:
            path = directory / "locked.parquet"
            digest = selection.write_locked(_locked(schedule, results), path)
            eval_tasks = _evaluation_tasks(schedule, settings, inputs, path, digest)

            def gather(index: int, result: GroupResult) -> Breach | None:
                groups.append(result)
                resources.write(result.resources)
                return None

            stop = drive(pool, eval_tasks, monitor, limits.poll_seconds, gather)
    finally:
        pool.terminate()
    if stop.breach is not None:  # an estimate that crossed a ceiling projects nothing
        resources.write({"kind": "breach", "utc": utc(), **stop.breach.record()})
        resources.close()
        _write_json(
            directory / "estimate.json",
            {
                "not_a_run": True,
                "complete": False,
                "breach": stop.breach.record(),
                "cells_done": len(results),
                "sample": [cell.key for cell in sample],
                "workers": limits.workers,
                "protocol_sha256": provenance.protocol_sha256,
                "head": provenance.head,
                "snapshot_manifest_sha256": inputs.data.manifest_sha256,
                "settings": settings.record(),
            },
        )
        raise Refused(f"the estimate crossed a ceiling: {stop.breach.record()}")
    per_cell = {}
    cells_by_menu = Counter(cell.menu for cell in schedule.cells)
    six_cells = Counter(
        cell.menu
        for cell in schedule.cells
        if cell.month in schedule.sensitivity and cell.seed == settings.seeds[0]
    )
    for menu in schedule.menus:
        spent = [r.resources["cpu"] for r in results.values() if r.cell.menu == menu]
        per_cell[menu] = sum(spent) / len(spent) if spent else 0.0
    mixes = sum(result.rows.num_rows for result in groups)
    per_mix = sum(result.resources["cpu"] for result in groups) / mixes if mixes else 0.0
    roles_per_cell = mixes / len(results) if results else 0.0
    parts = {
        "stage_1_search": sum(per_cell[m] * cells_by_menu[m] for m in schedule.menus),
        "stage_1_evaluation": per_mix * roles_per_cell * len(schedule.cells),
        "sensitivity_search": sum(per_cell[m] * six_cells[m] * (2 + 1 + 2) for m in schedule.menus),
        "sensitivity_evaluation": per_mix * roles_per_cell * sum(six_cells.values()) * 4,
        "scheduling": scheduling_cpu * 4,
    }
    arm_walls = [arm["wall"] for r in results.values() for arm in r.resources.get("arms", [])]
    projection = Projection(
        directory=directory,
        sample_cells=len(sample),
        scheduled_origins=len(schedule.scheduled),
        stage_1_cells=dict(cells_by_menu),
        search_cpu_per_cell=per_cell,
        evaluation_cpu_per_mix=per_mix,
        parts=parts,
        total_cpu_hours=sum(parts.values()) / 3600.0,
        cpu_hours_ceiling=limits.cpu_hours,
        max_arm_seconds=max(arm_walls, default=0.0),
    )
    body = {
        **{k: v for k, v in dataclasses.asdict(projection).items() if k != "directory"},
        "fits": projection.fits,
        "workers": limits.workers,
        "protocol_sha256": provenance.protocol_sha256,
        "head": provenance.head,
        "repo_dirty": bool(provenance.dirty),
        "snapshot_manifest_sha256": inputs.data.manifest_sha256,
        "sample": [cell.key for cell in sample],
        "scheduled_over_limit": len(schedule.scheduled) > MAX_ORIGINS,
        "settings": settings.record(),
        "not_a_run": True,
        "complete": True,
        "breach": None,
    }
    resources.write({"kind": "projection", **body})
    resources.close()
    _write_json(directory / "estimate.json", body)
    return projection
