"""The return-optimization report: `summary.json` and `report.md` of a run (protocol 6, 7, 9).

`write_report(directory)` reads one Stage 1 run directory (and its three sensitivity
subdirectories `sensitivity-coefficients`, `sensitivity-lookback`, `sensitivity-budget`) and
nothing else, and writes `summary.json` and `report.md` into that directory. It changes no other
file.

Verification. Every artifact the manifest lists (`artifacts`: the parquet files;
`execution.resources_sha256`: resources.jsonl; `lock.sha256`: the locked file) is re-hashed
before it is parsed, and a missing or changed file refuses the report (`ArtifactChanged`). A run is
incomplete when its Stage 1 manifest or any sensitivity manifest is missing or not `complete`;
an incomplete run is refused (`IncompleteRun`) unless ``allow_incomplete``, and then the
experiment is labeled inconclusive/invalid.

Validity (protocol 5 and 7, ruling R25): the run and its sensitivities are complete; every cell
of the frozen denominator (the manifest's `denominator.listing`) has its search.parquet row; no
Stage 1 cell is unattempted, interrupted or stopped at a resource ceiling; no Stage 1 cell failed
(a failed arm or a named computational error; `training_ineligible` is not a failure and leaves
both sides of the failure rate, which is recorded with its 1% line as information); the report's
count agrees with the denominator outcome the runner wrote to the manifest; the protocol 4
evidence gate holds on the scheduled panel (at least 60 mature origins, at least 95% complete
outcomes in each menu, no unexplained missing outcome, at least five disjoint intervals in each
menu, at most 120 scheduled origins); the TSP investigation digest and the recorded ranges of
its saved tensor were reproduced; equal weights
in a cell have bit-identical outcomes (invariance); every completed cell has R and R+D at every
allowance; and the run's settings are the protocol's. Each sensitivity profile is validated the
same way against its own frozen schedule (failed, incomplete and missing cells, paired
completeness, invariance); a profile that fails is unavailable, so its setting blocks Stage 2,
and the experiment is invalid. Any unresolved failure prevents a valid completed verdict: the
failed cells stay in the denominator, are listed with their reasons, and every statistic computed
over the remaining cells is labeled descriptive next to its table (`validity.descriptive_only`);
no protocol 7 label or Stage 2 run derives from it. A failed cell is resolved only by a rerun
under a recorded amendment.

The statistics and decisions are `research.evidence`; this module gathers the artifacts into its
inputs, writes the summary and renders the markdown (see `SUMMARY_SECTIONS` for the schema).
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from portfoliosight.research import evidence
from portfoliosight.research.evidence import (
    BASE_ARM,
    BLOCKS,
    BP,
    DESCRIPTIVE_LEVEL,
    PRIMARY_ARM,
    RISK_CELLS,
    Arm,
    Bootstrap,
    Grid,
    MenuEvidence,
    Replay,
    Validity,
    Verdict,
)
from portfoliosight.research.report_markdown import render
from portfoliosight.research.search import (
    COMPUTATIONAL_ERROR,
    FAILED_ARM,
    PRIMARY_ALLOWANCE,
)
from portfoliosight.research.selection import (
    ALLOWANCES,
    INTERRUPTED,
    OK_CELL,
    RESOURCE_BREACH,
    TRAINING_INELIGIBLE,
    UNATTEMPTED,
)

SCHEMA_VERSION = 1
STAGE_1 = "stage-1"
SENSITIVITY_RUNS = {
    "coefficients": ("coefficients-70-20-10", "coefficients-50-35-15"),
    "lookback": ("lookback-252",),
    "budget": ("budget-x2",),
}
SWEEP = {"cap-0bp": 0.0, "cap-5bp": 0.0005, "cap-10bp": 0.001}
REFERENCES = ("mdp", "min_variance", "equal_weight")
FAILED_STATUSES = frozenset({FAILED_ARM, COMPUTATIONAL_ERROR})
INCOMPLETE_STATUSES = frozenset({UNATTEMPTED, INTERRUPTED, RESOURCE_BREACH})
FAILURE_RATE_LIMIT = 0.01
MIN_MATURE, MIN_COMPLETE, MIN_DISJOINT, MAX_SCHEDULED = 60, 0.95, 5, 120
REPLAY_FIGURES = ("utility", "bad", "typical", "good", "es_25")
REALIZED_FIGURES = (  # column, reversed (second - first), label
    ("annual_return", False, "annual return"),
    ("max_drawdown", True, "max-drawdown improvement"),
    ("loss", False, "loss rate"),
    ("below_20", False, "below -20% rate"),
    ("worst_day", False, "worst day"),
    ("volatility", False, "realized volatility"),
)
SUMMARY_SECTIONS = (
    "schema_version",
    "run",
    "verification",
    "scope",
    "protocol_readings",
    "panel",
    "denominator",
    "validity",
    "references",
    "white_line",
    "primary",
    "realized",
    "forecast_error",
    "calibration",
    "stability",
    "native",
    "sensitivities",
    "cost",
    "criteria",
    "labels",
    "material_harm",
    "confirmed_worthwhile_benefit",
    "stage_2",
)

PROTOCOL_READINGS = (
    "Stage 2 runs iff the experiment is valid, both menus reach positive conditional-model "
    "evidence and no sensitivity disclosure blocks progression (controller ruling 1). A menu that "
    "qualifies only through the stability branch therefore cannot authorize Stage 2 under the "
    "protocol as written: its cross-seed stability sensitivity is unavailable.",
    "The 0 bp allowance is a diagnostic control, inert by construction (R+D = w_R or a 1e-12 U "
    "tie): it never blocks Stage 2, including when it is unavailable or tied (protocol amendment "
    "R26, superseding R24-2). 5 and 10 bp and the coefficient, lookback and budget settings block "
    "on a sign reversal of the pooled six-origin ΔU, a failed return floor, fewer than 4/5 banks "
    "with positive ΔU or an unavailable setting; a positive gain under 5 bp is reported but does "
    "not block alone.",
    "A setting's sign reversal is judged against Stage 1 on the same six indexed origins (R+D at "
    "2.5 bp minus R, primary seed, pooled test ΔU), not the full-panel ΔU (protocol amendment "
    "R27); without that baseline a reversal cannot be ruled out and the setting blocks.",
    "The stability branch is evaluated only when the primary pooled mean paired ΔU is under 5 bp "
    "(ruling 3); its bank rule counts banks meeting every floor, not banks with a gain.",
    "training_ineligible is not a failure (recorded, excluded from numerator and denominator); "
    "failed arms and named computational errors are failures, and a valid completed verdict "
    "requires zero unresolved failures in Stage 1 and in each sensitivity profile (ruling R25, "
    "superseding R24-4): the failed cells stay in the denominator and are listed with their "
    "reasons, statistics over the remaining cells are descriptive and labeled as such, and no "
    "protocol 7 label or Stage 2 run derives from them; the failure rate and its 1% line are "
    "recorded as information. An unattempted, interrupted, resource-breach or missing cell makes "
    "the run incomplete. A sensitivity profile with any such cell is unavailable and blocks.",
    "General stability is assessed on R+D at the 2.5 bp cap per risk cell: the across-seed SD "
    "uses ddof 1; 'primary portfolio chart volatility' is the model risk sqrt(w'Σw) of the "
    "primary-seed R+D selection at that origin and ceiling; median and 90th-percentile pairwise "
    "L1 pool all seed pairs over every origin; turnover pools every optimizer seed. The "
    "stable-gain L1 comparison is made at menu level, as the mean over the three risk cells of "
    "each arm's per-cell median and 90th percentile (ruling 5).",
    "The realized mask is the intersection across both menus and arms: an origin enters the "
    "realized statistics only when its horizon is complete in both menus (ruling 6).",
    "The realized 'annual-return median loss' is median(R) - median(R+D) across origins within "
    "a risk cell (ruling 7).",
    "The 12- and 36-origin bootstrap sensitivities reuse seed 20261201; the origin index is every "
    "ledger month from the first to the last scheduled origin, unscheduled months masked.",
    "Independent-replay return floors for material harm: pooled ΔU >= -2.5 bp, ΔB >= -5 bp, "
    "ΔT >= -10 bp, ΔG >= -20 bp and every risk-cell ΔU >= -2.5 bp (primary seed, pooled test).",
    "Realized-support disjoint intervals are counted greedily on the realized panel (the "
    "intersection mask) per menu; the protocol 4 coverage gate counts them on each menu's own "
    "complete outcomes.",
)


class ReportRefused(Exception):
    """The report cannot be written: a named precondition fails."""


class ArtifactChanged(ReportRefused):
    """An artifact listed in the manifest is missing or no longer has its recorded digest."""


class IncompleteRun(ReportRefused):
    """Stage 1 or a sensitivity is missing or not complete (allow with ``allow_incomplete``)."""


# ------------------------------------------------------------------------------------ reading


@dataclass(frozen=True)
class RunFiles:
    directory: Path
    manifest: Mapping[str, Any]
    verified: Mapping[str, str]  # artifact name -> SHA-256 checked
    outcomes: pa.Table | None
    origins: pa.Table | None
    cells: tuple[Mapping[str, Any], ...]  # search.parquet rows of kind "cell"
    resources: tuple[Mapping[str, Any], ...]

    @property
    def state(self) -> str:
        return str(self.manifest.get("status", {}).get("state"))


_CELL_COLUMNS = (
    "profile",
    "cell_key",
    "menu",
    "month",
    "ceiling_id",
    "seed",
    "stands_for",
    "cell_status",
    "error",
    "error_detail",
    "aggregation_weight",
)


def _hash_handle(handle: BinaryIO) -> str:
    """SHA-256 of an open file from its start, read in chunks."""
    digest = hashlib.sha256()
    handle.seek(0)
    for chunk in iter(lambda: handle.read(1 << 24), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _stamp(handle: BinaryIO) -> tuple[int, int, int]:
    found = os.fstat(handle.fileno())
    return (found.st_size, found.st_mtime_ns, found.st_ino)


def _search_cells(path: Path, digest: str) -> tuple[Mapping[str, Any], ...]:
    """The `cell` rows of search.parquet, parsed through the very handle that was hashed.

    The file can be 1-2 GB, so it is hashed in chunks rather than held in memory; its size,
    modification time and inode must not change between opening, hashing and parsing.
    """
    with path.open("rb") as handle:
        before = _stamp(handle)
        found = _hash_handle(handle)
        if found != digest:
            raise ArtifactChanged(f"{path}: SHA-256 {found}, the manifest records {digest}")
        if _stamp(handle) != before:
            raise ArtifactChanged(f"{path} changed while it was hashed")
        handle.seek(0)
        source = pq.ParquetFile(handle)
        kept = []
        for group in range(source.num_row_groups):  # one row group at a time: bounded memory
            rows = source.read_row_group(group, columns=["kind", *_CELL_COLUMNS])
            cell = pa.array([kind == "cell" for kind in rows["kind"].to_pylist()], pa.bool_())
            kept.append(rows.filter(cell).select(list(_CELL_COLUMNS)))
        if _stamp(handle) != before:
            raise ArtifactChanged(f"{path} changed while it was read")
    return tuple(pa.concat_tables(kept).to_pylist()) if kept else ()


def read_run(directory: str | Path) -> RunFiles:
    """One run directory's manifest and verified artifacts (``ArtifactChanged`` otherwise).

    Every artifact is parsed from the bytes that were hashed: the small ones are read once into
    memory, search.parquet through the one open handle that was hashed (`_search_cells`).
    """
    root = Path(directory)
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        raise IncompleteRun(f"no manifest.json in {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = dict(manifest.get("artifacts") or {})
    resources_digest = (manifest.get("execution") or {}).get("resources_sha256")
    if resources_digest:
        expected["resources.jsonl"] = resources_digest
    lock = manifest.get("lock")
    if lock and expected.get("locked.parquet") != lock.get("sha256"):
        raise ArtifactChanged(f"{root}: locked.parquet is listed with a digest other than the lock")
    blobs: dict[str, bytes] = {}
    cells: tuple[Mapping[str, Any], ...] = ()
    for name, digest in sorted(expected.items()):
        path = root / name
        if not path.exists():
            raise ArtifactChanged(f"{path} is listed in the manifest but missing")
        if name == "search.parquet":
            cells = _search_cells(path, digest)
            continue
        blobs[name] = path.read_bytes()
        found = hashlib.sha256(blobs[name]).hexdigest()
        if found != digest:
            raise ArtifactChanged(f"{path}: SHA-256 {found}, the manifest records {digest}")

    def table(name: str) -> pa.Table | None:
        return pq.read_table(io.BytesIO(blobs[name])) if name in blobs else None

    resources: tuple[Mapping[str, Any], ...] = ()
    if "resources.jsonl" in blobs:
        text = blobs["resources.jsonl"].decode("utf-8")
        resources = tuple(json.loads(line) for line in text.splitlines() if line.strip())
    return RunFiles(
        directory=root,
        manifest=manifest,
        verified=expected,
        outcomes=table("outcomes.parquet"),
        origins=table("origins.parquet"),
        cells=cells,
        resources=resources,
    )


# -------------------------------------------------------------------------------------- panel


@dataclass(frozen=True)
class Panel:
    months: tuple[str, ...]  # the origin index
    scheduled: np.ndarray
    mask: np.ndarray  # realized intersection mask
    facts: Mapping[str, Mapping[str, Any]]  # per menu
    ledger_counts: Mapping[str, int]
    gates: tuple[Mapping[str, Any], ...]


def _iso(value: Any) -> str | None:
    return (
        None
        if value is None
        else value.date().isoformat()
        if hasattr(value, "date")
        else str(value)
    )


def build_panel(run: RunFiles, menus: Sequence[str]) -> Panel:
    """The origin index, the realized mask and the protocol 4 gate on the scheduled panel."""
    if run.origins is None:
        raise ReportRefused("origins.parquet is not in the run")
    lookback = run.manifest["ledger"]["lookback"]
    rows = [row for row in run.origins.to_pylist() if row["lookback"] == lookback]
    by = {(row["month"], row["menu"]): row for row in rows}
    scheduled_months = sorted({row["month"] for row in rows if row["scheduled"]})
    if not scheduled_months:
        raise ReportRefused("the run scheduled no origin")
    all_months = sorted({row["month"] for row in rows})
    months = tuple(m for m in all_months if scheduled_months[0] <= m <= scheduled_months[-1])
    scheduled = np.array([m in set(scheduled_months) for m in months])
    complete: dict[str, list[bool]] = {}
    for menu in menus:
        complete[menu] = [
            bool(s)
            and by[(m, menu)]["status"] == "mature"
            and by[(m, menu)]["outcome"] == "complete"
            for m, s in zip(months, scheduled, strict=True)
        ]
    mask = evidence.intersection_mask(complete, menus)
    month_status = {row["month"]: row["status"] for row in rows}
    mature = [
        m for m, s in zip(months, scheduled, strict=True) if s and month_status[m] == "mature"
    ]
    facts: dict[str, dict[str, Any]] = {}
    gates: list[dict[str, Any]] = [
        {
            "gate": "scheduled_origins",
            "value": len(scheduled_months),
            "rule": f"<= {MAX_SCHEDULED}",
            "met": len(scheduled_months) <= MAX_SCHEDULED,
        },
        {
            "gate": "mature_origins",
            "value": len(mature),
            "rule": f">= {MIN_MATURE}",
            "met": len(mature) >= MIN_MATURE,
        },
    ]
    for menu in menus:
        own = [by[(m, menu)] for m, ok in zip(months, complete[menu], strict=True) if ok]
        panel = [by[(m, menu)] for m, ok in zip(months, mask, strict=True) if ok]
        missing = [by[(m, menu)] for m in mature if by[(m, menu)]["outcome"] != "complete"]
        unexplained = sum(1 for row in missing if json.loads(row["menu_issues"] or "[]") == [])
        share = len(own) / len(mature) if mature else None
        disjoint_menu = evidence.disjoint_count(
            [r["origin"] for r in own], [r["horizon_end"] for r in own]
        )
        facts[menu] = {
            "scheduled": len(scheduled_months),
            "mature": len(mature),
            "complete": len(own),
            "mature_missing": len(missing),
            "unexplained_missing": unexplained,
            "immature": sum(
                1
                for m, s in zip(months, scheduled, strict=True)
                if s and month_status[m] != "mature"
            ),
            "realized_panel": int(mask.sum()),
            "disjoint_menu": disjoint_menu,
            "disjoint_panel": evidence.disjoint_count(
                [r["origin"] for r in panel], [r["horizon_end"] for r in panel]
            ),
            "first_origin": _iso(by[(scheduled_months[0], menu)]["origin"]),
            "last_origin": _iso(by[(scheduled_months[-1], menu)]["origin"]),
            "last_horizon_end": _iso(max((r["horizon_end"] for r in panel), default=None)),
            "missing_reasons": [
                {"month": row["month"], "outcome": row["outcome"], "issues": row["menu_issues"]}
                for row in missing
            ],
        }
        gates += [
            {
                "gate": f"{menu}_completeness",
                "value": share,
                "rule": ">= 95%",
                "met": share is not None and share >= MIN_COMPLETE,
            },
            {
                "gate": f"{menu}_unexplained_missing",
                "value": unexplained,
                "rule": "= 0",
                "met": unexplained == 0,
            },
            {
                "gate": f"{menu}_disjoint_intervals",
                "value": disjoint_menu,
                "rule": f">= {MIN_DISJOINT}",
                "met": disjoint_menu >= MIN_DISJOINT,
            },
        ]
    counts = Counter(row["status"] for row in rows if row["menu"] == menus[0])
    return Panel(months, scheduled, mask, facts, dict(sorted(counts.items())), tuple(gates))


# ------------------------------------------------------------------------------- denominator


def denominator(run: RunFiles, profile: str | None = STAGE_1) -> dict[str, Any]:
    """A profile's cells (every profile with None) against the run's frozen denominator.

    Statuses come from the search.parquet cell rows; the failure rate is failed arms and named
    computational errors over the scheduled cells other than `training_ineligible` (ruling R25:
    information, since any failure prevents a valid verdict). A frozen cell without a row is
    `missing`, a row outside the frozen listing `unscheduled`; without a listing in the manifest
    the rows are the cells.
    """
    cells = [cell for cell in run.cells if profile is None or cell["profile"] == profile]
    listing = (run.manifest.get("denominator") or {}).get("listing")
    found = {(cell["profile"], cell["cell_key"]) for cell in cells}
    missing: list[str] = []
    unscheduled: list[str] = []
    total = len(cells)
    if listing is not None:
        frozen = [
            (entry["profile"], entry["key"])
            for entry in listing
            if profile is None or entry["profile"] == profile
        ]
        missing = [key for name, key in frozen if (name, key) not in found]
        unscheduled = sorted(key for _, key in found - set(frozen))
        total = len(frozen)
    statuses = Counter(cell["cell_status"] for cell in cells)
    ineligible = statuses.get(TRAINING_INELIGIBLE, 0)
    failed = [cell for cell in cells if cell["cell_status"] in FAILED_STATUSES]
    incomplete = [cell for cell in cells if cell["cell_status"] in INCOMPLETE_STATUSES]
    base = total - ineligible
    rate = len(failed) / base if base else 0.0
    listed = [
        {key: cell[key] for key in ("cell_key", "cell_status", "error", "error_detail")}
        for cell in failed + incomplete
    ]
    listed += [
        {
            "cell_key": key,
            "cell_status": "missing",
            "error": None,
            "error_detail": "a frozen cell without a search.parquet row",
        }
        for key in missing
    ]
    return {
        "cells": total,
        "by_status": dict(sorted(statuses.items())),
        "training_ineligible_excluded": ineligible,
        "failure_denominator": base,
        "failed": len(failed),
        "failure_rate": rate,
        "failure_rate_limit": FAILURE_RATE_LIMIT,
        "failure_rate_above_limit": rate > FAILURE_RATE_LIMIT,
        "incomplete": len(incomplete),
        "missing": len(missing),
        "missing_cells": missing,
        "unscheduled_cells": unscheduled,
        "failed_cells": listed,
        "manifest_outcome": (run.manifest.get("status") or {}).get("denominator"),
    }


_AGREEING = (
    "cells",
    "training_ineligible_excluded",
    "failure_denominator",
    "failed",
    "incomplete",
    "failure_rate",
    "by_status",
)


def invariance_breaks(outcomes: pa.Table, profile: str | None = None) -> list[str]:
    """Equal weights in one cell must have bit-identical outcomes, whatever their role."""
    figures = [
        name
        for name in outcomes.column_names
        if name.startswith(("test_", "bank_", "train_"))
        or name in ("annual_return", "max_drawdown", "volatility", "worst_day")
    ]
    keys = ("profile", "menu", "month", "ceiling_id", "seed")
    table = outcomes.select([*keys, "role", "allowance", "weights", *figures]).to_pylist()
    seen: dict[tuple, tuple[str, str]] = {}
    broken = []
    for row in table:
        if profile is not None and row["profile"] != profile:
            continue
        cell = tuple(row[k] for k in keys)
        weights = tuple(float(w).hex() for w in row["weights"])
        found = json.dumps([row[name] for name in figures], default=repr, allow_nan=True)
        key = (cell, weights)
        if key in seen and seen[key][1] != found:
            broken.append(f"{cell} {seen[key][0]} vs {row['role']}@{row['allowance']}")
        seen.setdefault(key, (f"{row['role']}@{row['allowance']}", found))
    return broken


def _paired_complete(run: RunFiles, profile: str = STAGE_1) -> list[str]:
    """Completed cells without an R row and an R+D row at every nonzero allowance.

    The 0 bp control is a diagnostic that never blocks (R26): its row is not required.
    """
    if run.outcomes is None:
        return []
    have = Counter()
    for row in run.outcomes.select(["profile", "cell_key", "role", "allowance"]).to_pylist():
        if row["profile"] == profile and row["role"] in ("R", "R+D"):
            have[(row["cell_key"], row["role"], row["allowance"])] += 1
    missing = []
    for cell in run.cells:
        if cell["profile"] != profile or cell["cell_status"] != OK_CELL:
            continue
        needed = [("R", None)] + [("R+D", a) for a in ALLOWANCES if a != 0.0]
        if any(have[(cell["cell_key"], role, a)] != 1 for role, a in needed):
            missing.append(cell["cell_key"])
    return missing


def profile_problems(run: RunFiles, profile: str) -> list[str]:
    """Why a profile's cells are not a complete paired record (empty when they are)."""
    counted = denominator(run, profile)
    problems = []
    for name, text in (
        ("failed", "failed"),
        ("incomplete", "unattempted, interrupted or resource-breach"),
        ("missing", "missing from search.parquet"),
    ):
        if counted[name]:
            problems.append(f"{profile}: {counted[name]} {text}")
    if counted["unscheduled_cells"]:
        outside = len(counted["unscheduled_cells"])
        problems.append(f"{profile}: {outside} cells outside the schedule")
    if run.outcomes is None:
        problems.append(f"{profile}: no outcomes.parquet")
        return problems
    unpaired = _paired_complete(run, profile)
    if unpaired:
        problems.append(f"{profile}: {len(unpaired)} completed cells lack a paired arm")
    broken = invariance_breaks(run.outcomes, profile)
    if broken:
        problems.append(f"{profile}: {len(broken)} cells break exact-weight invariance")
    return problems


def sensitivity_problems(sensitivities: Mapping[str, RunFiles | None]) -> dict[str, list[str]]:
    """Per sensitivity profile, why its cells cannot stand for the setting (empty: they can)."""
    out: dict[str, list[str]] = {}
    for name, profiles in SENSITIVITY_RUNS.items():
        run = sensitivities.get(name)
        for profile in profiles:
            out[profile] = (
                [f"{profile}: not run"] if run is None else profile_problems(run, profile)
            )
    return out


def _provenance(run: RunFiles, part: str) -> Any:
    manifest = run.manifest
    if part == "run id":
        return (manifest.get("run") or {}).get("id")
    if part == "snapshot":
        return (manifest.get("data") or {}).get("snapshot_manifest_sha256")
    return manifest.get(part)


def validity(
    stage1: RunFiles,
    sensitivities: Mapping[str, RunFiles | None],
    panel: Panel | None,
    counted: Mapping[str, Any],
    problems: Mapping[str, Sequence[str]],
) -> tuple[Validity, list[dict[str, Any]]]:
    """Every validity check (module docstring) and the reasons the experiment is invalid.

    ``counted`` is `denominator(stage1)`, ``problems`` `sensitivity_problems(sensitivities)`.
    """
    checks: list[dict[str, Any]] = []

    def check(name: str, met: bool, detail: str) -> None:
        checks.append({"check": name, "met": bool(met), "detail": detail})

    check("stage_1_complete", stage1.state == "complete", f"Stage 1 state {stage1.state}")
    for name, profiles in SENSITIVITY_RUNS.items():
        run = sensitivities.get(name)
        state = "missing" if run is None else run.state
        check(f"sensitivity_{name}_complete", state == "complete", f"state {state}")
        found = [
            text for profile in profiles for text in problems.get(profile, [f"{profile}: not run"])
        ]
        check(
            f"sensitivity_{name}_cells",
            not found,
            "; ".join(found)
            if found
            else "every frozen cell completed with its paired arms and exact-weight invariance",
        )
    missing = counted["missing_cells"] + counted["unscheduled_cells"]
    check(
        "frozen_schedule",
        not missing,
        f"{counted['missing']} frozen cells without a row, {len(counted['unscheduled_cells'])} "
        "rows outside the frozen schedule" + (f": {missing[:5]}" if missing else ""),
    )
    check(
        "no_incomplete_cells",
        counted["incomplete"] == 0,
        f"{counted['incomplete']} unattempted, interrupted or resource-breach cells",
    )
    check(
        "no_failed_cells",
        counted["failed"] == 0,
        f"{counted['failed']} failed of {counted['failure_denominator']} "
        f"(training-ineligible excluded: {counted['training_ineligible_excluded']}); rate "
        f"{counted['failure_rate']:.4f}, 1% line recorded as information; any unresolved "
        "failure prevents a valid completed verdict (R25)",
    )
    whole = denominator(stage1, None)
    recorded = counted["manifest_outcome"]
    differs = (
        list(_AGREEING)
        if not isinstance(recorded, Mapping)
        else [key for key in _AGREEING if recorded.get(key) != whole[key]]
    )
    check(
        "denominator_agrees_with_manifest",
        not differs,
        "the report's count differs from the manifest's denominator outcome in "
        + ", ".join(differs)
        if differs
        else "the report counts the cells as the runner recorded them",
    )
    if panel is None:
        check("coverage_gate", False, "origins.parquet unavailable")
    else:
        failed_gates = [g["gate"] for g in panel.gates if not g["met"]]
        check(
            "coverage_gate",
            not failed_gates,
            "failed: " + ", ".join(failed_gates) if failed_gates else "every protocol 4 gate met",
        )
    investigation = (stage1.manifest.get("data") or {}).get("investigation") or {}
    expected, reproduced = investigation.get("digest"), investigation.get("reproduced")
    check(
        "investigation_digest",
        expected is not None and reproduced == expected,
        f"reproduced {reproduced}, expected {expected}",
    )
    ranges = investigation.get("ranges") or {}
    gap, line = ranges.get("max_abs_discrepancy"), ranges.get("tolerance")
    check(
        "investigation_ranges",
        gap is not None and line is not None and gap <= line,
        f"the investigation tensor's recorded ranges reproduced within {gap} (tolerance {line}) "
        f"over {ranges.get('mixes')} mixes in columns {ranges.get('columns')}",
    )
    for name, run in sensitivities.items():
        if run is not None:
            differs = [
                part
                for part in ("run id", "code", "settings", "snapshot")
                if _provenance(run, part) != _provenance(stage1, part)
            ]
            check(
                f"sensitivity_{name}_provenance",
                not differs,
                "differs from Stage 1 in " + ", ".join(differs)
                if differs
                else "same run id, code, settings and snapshot as Stage 1",
            )
    if stage1.outcomes is None:
        check("outcomes_present", False, "outcomes.parquet unavailable")
    else:
        broken = invariance_breaks(stage1.outcomes, STAGE_1)
        check(
            "invariance",
            not broken,
            f"{len(broken)} cells break exact-weight invariance"
            + (f": {broken[:5]}" if broken else ""),
        )
        unpaired = _paired_complete(stage1)
        check("paired_arms", not unpaired, f"{len(unpaired)} completed cells lack a paired arm")
    deviations = list(stage1.manifest.get("deviations_from_protocol") or [])
    check(
        "protocol_settings",
        not deviations,
        "settings deviate from the protocol: " + ", ".join(deviations)
        if deviations
        else "every setting is the protocol's",
    )
    reasons = tuple(f"{c['check']}: {c['detail']}" for c in checks if not c["met"])
    return Validity(valid=not reasons, reasons=reasons), checks


def descriptive_note(
    stage1: RunFiles, counted: Mapping[str, Any], unpaired: Sequence[str] = ()
) -> str | None:
    """The label of every statistic computed over a partial Stage 1 (None when it is whole).

    ``unpaired`` are the completed cells missing a required paired outcome (`_paired_complete`).
    """
    parts = [
        f"{counted[name]} {text}"
        for name, text in (
            ("failed", "failed"),
            ("incomplete", "unattempted, interrupted or resource-breach"),
            ("missing", "missing"),
        )
        if counted[name]
    ]
    if unpaired:
        shown = ", ".join(unpaired[:3]) + (", ..." if len(unpaired) > 3 else "")
        parts.append(f"{len(unpaired)} completed cells lack a required paired outcome ({shown})")
    if not parts and stage1.state == "complete":
        return None
    said = []
    if parts:
        said.append(
            " and ".join(parts) + " (Stage 1 cells stay in the denominator and are listed under "
            "Protocol compliance)"
        )
    if stage1.state != "complete":
        said.append(f"the Stage 1 run is {stage1.state}")
    return (
        "Descriptive only: computed over the available cells; "
        + "; ".join(said)
        + ". No protocol 7 label or Stage 2 decision derives from this table (R25)."
    )


# ---------------------------------------------------------------------------------- the report


@dataclass(frozen=True)
class Report:
    directory: Path
    summary: Mapping[str, Any]
    markdown: str
    verdict: Verdict | None


def _sensitivity_runs(directory: Path, allow: bool) -> dict[str, RunFiles | None]:
    found: dict[str, RunFiles | None] = {}
    for name in SENSITIVITY_RUNS:
        path = directory / f"sensitivity-{name}"
        if not (path / "manifest.json").exists():
            if not allow:
                raise IncompleteRun(f"the {name} sensitivity has not run ({path})")
            found[name] = None
            continue
        run = read_run(path)
        if run.state != "complete" and not allow:
            raise IncompleteRun(f"the {name} sensitivity is {run.state} ({path})")
        found[name] = run
    return found


def write_report(
    directory: str | Path, *, allow_incomplete: bool = False, reviews: Sequence[str] = ()
) -> Report:
    """Read the run directory, compute every statistic and decision, write both files.

    ``reviews`` (ruling R28) are appended verbatim to the Stage 1 manifest's `reviews`, each
    entry once, before the summary is built; they are recorded, never interpreted. Without
    them no file but `summary.json` and `report.md` is written.
    """
    root = Path(directory)
    stage1 = read_run(root)
    if stage1.manifest.get("stage") != 1 or stage1.manifest.get("sensitivity") is not None:
        raise ReportRefused(f"{root} is not a Stage 1 run directory")
    if stage1.state != "complete" and not allow_incomplete:
        raise IncompleteRun(f"the Stage 1 run is {stage1.state}; pass allow_incomplete to label it")
    sensitivities = _sensitivity_runs(root, allow_incomplete)
    recorded = list(stage1.manifest.get("reviews") or [])
    added = [str(entry) for entry in dict.fromkeys(reviews) if str(entry) not in recorded]
    if added:
        manifest = {**stage1.manifest, "reviews": recorded + added}
        path = root / "manifest.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
        temporary.replace(path)
        stage1 = replace(stage1, manifest=manifest)
    summary, verdict = build_summary(stage1, sensitivities)
    markdown = render(summary)
    (root / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (root / "report.md").write_text(markdown, encoding="utf-8")
    return Report(root, summary, markdown, verdict)


def _clean(value: Any) -> Any:
    """JSON-ready: non-finite floats become None, tuples lists, NumPy scalars Python ones."""
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def build_summary(
    stage1: RunFiles, sensitivities: Mapping[str, RunFiles | None]
) -> tuple[dict[str, Any], Verdict | None]:
    """The summary (keys `SUMMARY_SECTIONS`) and the verdict (None without outcomes)."""
    manifest = stage1.manifest
    menus = tuple(manifest["menus"])
    primary = int(manifest["search"]["primary_seed"])
    coefficients = tuple(manifest["preference"]["coefficients"])
    counted = denominator(stage1)
    panel = build_panel(stage1, menus) if stage1.origins is not None else None
    problems = sensitivity_problems(sensitivities)
    valid, checks = validity(stage1, sensitivities, panel, counted, problems)
    unpaired_cells = _paired_complete(stage1)
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "id": manifest["run"]["id"],
            "stage": manifest.get("stage"),
            "state": stage1.state,
            "protocol": manifest.get("protocol"),
            "code": manifest.get("code"),
            "created_utc": manifest["run"].get("created_utc"),
            "finished_utc": manifest["run"].get("finished_utc"),
            "menus": menus,
            "primary_seed": primary,
            "seeds": manifest["search"]["path_seeds"],
            "deviations_from_protocol": manifest.get("deviations_from_protocol"),
            "cpu_hours_amendment": (manifest.get("limits") or {}).get("cpu_hours_amendment"),
        },
        "verification": {
            "stage_1": dict(stage1.verified),
            "sensitivities": {
                name: None if run is None else {"state": run.state, "artifacts": dict(run.verified)}
                for name, run in sensitivities.items()
            },
        },
        "scope": _scope(manifest),
        "protocol_readings": list(PROTOCOL_READINGS),
        "panel": None if panel is None else _panel_record(panel),
        "denominator": counted,
        "validity": {
            "valid": valid.valid,
            "reasons": list(valid.reasons),
            "checks": checks,
            "descriptive_only": descriptive_note(stage1, counted, unpaired_cells),
            "unpaired_cells": unpaired_cells,
        },
    }
    if stage1.outcomes is None or panel is None:
        stage_2 = {
            "run": False,
            "reason": "Stage 2 (R+E, ENB) is skipped under the owner's stopping policy (D7): the "
            "experiment is inconclusive/invalid and has no outcomes to assess. ENB unevaluated, "
            "not ineffective.",
            "failing_criteria": [f"validity: {reason}" for reason in valid.reasons],
        }
        for section in SUMMARY_SECTIONS:
            summary.setdefault(section, None)
        summary["labels"] = {
            "experiment": evidence.INVALID,
            "experiment_reasons": list(valid.reasons),
            "menus": {},
        }
        summary["material_harm"] = []
        summary["confirmed_worthwhile_benefit"] = False
        summary["stage_2"] = stage_2
        summary["cost"] = _cost_section(stage1, sensitivities, menus)
        return _clean({k: summary[k] for k in SUMMARY_SECTIONS}), None

    grid = Grid(stage1.outcomes, panel.months, profile=STAGE_1, realized_mask=panel.mask)
    boot = Bootstrap(len(panel.months))
    summary["scope"]["origin_index"] = _index_note(len(panel.months))
    summary["references"] = {
        ref: _contrasts(grid, menus, BASE_ARM, (ref, None), primary, boot) for ref in REFERENCES
    }
    summary["references"]["equal_weight_within_ceiling_share"] = _within_share(
        stage1.outcomes, primary
    )
    summary["white_line"] = {
        "w_r_minus_frontier": _contrasts(grid, menus, BASE_ARM, ("frontier", None), primary, boot),
        "per_origin": _per_origin(stage1.outcomes, primary),
    }
    summary["primary"] = _primary(grid, menus, primary, boot)
    summary["realized"] = _realized_section(grid, menus, primary, boot, coefficients)
    summary["forecast_error"] = _forecast_error(grid, menus, primary, boot)
    summary["calibration"] = {
        menu: {
            _arm_name((role, allowance)): {
                forecast: evidence.calibration(grid, menu, (role, allowance), primary, forecast)
                for forecast in ("train", "test")
            }
            for role, allowance in (
                BASE_ARM,
                PRIMARY_ARM,
                ("frontier", None),
                *[(r, None) for r in REFERENCES],
            )
        }
        for menu in menus
    }
    stabilities = {
        menu: {
            "R": evidence.stability(grid, menu, BASE_ARM, primary),
            "R+D": evidence.stability(grid, menu, PRIMARY_ARM, primary),
        }
        for menu in menus
    }
    summary["stability"] = {
        menu: {arm: _stability_record(s) for arm, s in arms.items()}
        | {"selection": selection_frequencies(grid, menu)}
        for menu, arms in stabilities.items()
    }
    summary["native"] = {
        figure: evidence.table_record(
            evidence.paired_estimates(
                grid,
                menus,
                ("R+D:native", PRIMARY_ALLOWANCE),
                ("R:native", None),
                f"test_{figure}",
                primary,
                boot,
            )
        )
        for figure in REPLAY_FIGURES
    }
    six = tuple(manifest["ledger"]["sensitivity_origins"])
    replays = _sensitivity_replays(stage1, sensitivities, menus, six, primary, problems)
    menu_evidence = {}
    for menu in menus:
        dr2, changed = evidence.score_change(grid, menu, PRIMARY_ARM, BASE_ARM, primary)
        menu_evidence[menu] = MenuEvidence(
            menu=menu,
            replay=evidence.replay_contrast(grid, menu, PRIMARY_ARM, BASE_ARM, primary),
            stability=stabilities[menu],
            dr2_gain=dr2,
            changed_share=changed,
            cost=evidence.cost(stage1.resources, menu),
            realized=evidence.realized(
                grid,
                menu,
                PRIMARY_ARM,
                BASE_ARM,
                primary,
                boot,
                disjoint=panel.facts[menu]["disjoint_panel"],
            ),
        )
    verdict = evidence.decide(valid, menu_evidence, replays.settings, replays.primary_six)
    summary["sensitivities"] = _sensitivity_section(replays, six, verdict)
    summary["cost"] = _cost_section(stage1, sensitivities, menus)
    summary["cost"]["evidence"] = {
        menu: vars(e.cost) | {"line_seconds": evidence.COST_R_P95[menu]}
        for menu, e in menu_evidence.items()
    }
    summary["criteria"] = [c.record() for c in verdict.criteria]
    summary["labels"] = _labels(verdict, menu_evidence)
    summary["material_harm"] = [_harm_record(c, summary) for c in verdict.material_harm]
    summary["confirmed_worthwhile_benefit"] = verdict.confirmed_worthwhile_benefit
    summary["stage_2"] = dict(verdict.stage_2)
    return _clean({k: summary[k] for k in SUMMARY_SECTIONS}), verdict


# -------------------------------------------------------------------------------- sections


def _scope(manifest: Mapping[str, Any]) -> dict[str, Any]:
    limits = manifest.get("limits") or {}
    return {
        "design": "retrospective fixed-menu, as-of-truncated backtest (protocol 4): today's menus "
        "and adjusted histories are hindsight choices; not point-in-time investability or a "
        "prospective blind trial",
        "cohorts": "one realized annual return per origin; monthly cohorts overlap heavily, and "
        "risk cells and menus share outcomes; neither cells nor simulated paths are independent "
        "historical replications",
        "tail_power": "below 200 disjoint annual intervals, realized q(.025) superiority and "
        "calibration are underpowered; no confirmed real-world tail-benefit claim",
        "intervals": "paired circular moving-block bootstrap over the monthly origin index, block "
        "24 (12 and 36 as sensitivity), 2,000 resamples, seed 20261201; percentile intervals, 99% "
        "for the four realized-support endpoints and 95% elsewhere; exploratory below 20 disjoint "
        "annual intervals; block resampling cannot create missing regimes or independence",
        "allowance_sweep": "the {0, 5, 10} bp allowance sweep is selection-only from pools "
        "searched under the 2.5 bp R+D guard (ruling R23), so it understates a search targeted "
        "at those caps",
        "process_model": limits.get("process_model"),
        "definitions": manifest.get("definitions"),
        "forecast_error": "forecast error = realized annual return of w_R minus its forecast "
        "mu_s'w_R; correlated with the paired realized difference R+D - R; a negative sign "
        "(R+D helps most where mu_s overshot) is mechanism (a) of protocol 1; a diagnostic, not a "
        "gate",
        "stage_2_stability_branch": PROTOCOL_READINGS[0],
        "stage_2_artifacts": "this report assesses Stage 1 and its sensitivities only; Stage 2 "
        "artifacts, if any, are not summarized here and cannot change this Stage 1 verdict",
        "manifest": "artifact digests come from each manifest.json, which is itself not hashed",
        "review": "this report claims no review; the manifest records reviews "
        f"{manifest.get('reviews')}. It authorizes no default change, UI design, deployment or "
        "publication.",
    }


def _index_note(k: int) -> str:
    """How the block lengths compare with the origin index (a degenerate case is said so)."""
    rotated = [block for block in BLOCKS if block >= k]
    note = f"{k} origins on the index"
    if rotated:
        note += (
            f"; with block length {', '.join(map(str, rotated))} >= {k} every resample is a "
            "rotation of the whole index, so intervals of origin means have zero width there"
        )
    return note


def _panel_record(panel: Panel) -> dict[str, Any]:
    return {
        "origins": len(panel.months),
        "months": list(panel.months),
        "scheduled": int(panel.scheduled.sum()),
        "realized_mask": [bool(x) for x in panel.mask],
        "realized_panel": int(panel.mask.sum()),
        "ledger_status_counts": dict(panel.ledger_counts),
        "menus": dict(panel.facts),
        "coverage_gates": list(panel.gates),
    }


def _contrasts(
    grid: Grid, menus: Sequence[str], first: Arm, second: Arm, seed: int, boot: Bootstrap
) -> dict[str, Any]:
    """Paired replay (pooled test) and realized mean differences, first minus second."""
    replay = {
        figure: evidence.table_record(
            evidence.paired_estimates(grid, menus, first, second, f"test_{figure}", seed, boot)
        )
        for figure in REPLAY_FIGURES
    }
    realized = {
        column: evidence.table_record(
            evidence.paired_estimates(
                grid, menus, first, second, column, seed, boot, realized=True, reverse=reverse
            )
        )
        for column, reverse, _ in REALIZED_FIGURES
    }
    return {
        "first": _arm_name(first),
        "second": _arm_name(second),
        "replay": replay,
        "realized": realized,
    }


def _arm_name(arm: Arm) -> str:
    role, allowance = arm
    return role if allowance is None else f"{role}@{allowance / BP:g}bp"


def _within_share(outcomes: pa.Table, seed: int) -> dict[str, float | None]:
    rows = outcomes.select(["profile", "menu", "seed", "role", "within_ceiling"]).to_pylist()
    out: dict[str, list[bool]] = {}
    for row in rows:
        if row["profile"] == STAGE_1 and row["seed"] == seed and row["role"] == "equal_weight":
            out.setdefault(row["menu"], []).append(bool(row["within_ceiling"]))
    return {menu: sum(v) / len(v) if v else None for menu, v in out.items()}


_ORIGIN_FIGURES = (
    "risk",
    "dr2",
    "train_bad",
    "train_typical",
    "train_good",
    "train_utility",
    "train_es_25",
    "test_bad",
    "test_typical",
    "test_good",
    "test_utility",
    "test_es_25",
)


def _per_origin(outcomes: pa.Table, seed: int) -> list[dict[str, Any]]:
    """Per (menu, origin, distinct ceiling), primary seed: both white-line candidates and the
    R+D selection beside the pool's most diversified member and the MDP anchor."""
    columns = [
        "profile",
        "menu",
        "month",
        "ceiling_id",
        "stands_for",
        "seed",
        "role",
        "allowance",
        "weights",
        "sacrifice",
        "guards",
        *_ORIGIN_FIGURES,
    ]
    cells: dict[tuple, dict[str, Any]] = {}
    for row in outcomes.select(columns).to_pylist():
        if row["profile"] != STAGE_1 or row["seed"] != seed:
            continue
        role = row["role"]
        if role == "R+D" and row["allowance"] != PRIMARY_ALLOWANCE:
            continue
        if role not in ("R", "frontier", "R+D", "pool_max_dr2", "mdp"):
            continue
        key = (row["menu"], row["month"], row["ceiling_id"])
        entry = cells.setdefault(
            key,
            {
                "menu": key[0],
                "month": key[1],
                "ceiling_id": key[2],
                "stands_for": row["stands_for"],
            },
        )
        figures = {name: row[name] for name in _ORIGIN_FIGURES}
        figures["weights"] = row["weights"]
        if role == "R+D":
            figures |= {"sacrifice": row["sacrifice"], "guards": json.loads(row["guards"] or "[]")}
        entry["w_R" if role == "R" else role] = figures
    return [cells[key] for key in sorted(cells, key=lambda k: (k[0], k[1], RISK_CELLS.index(k[2])))]


def _primary(grid: Grid, menus: Sequence[str], seed: int, boot: Bootstrap) -> dict[str, Any]:
    out = _contrasts(grid, menus, PRIMARY_ARM, BASE_ARM, seed, boot)
    out["train"] = {
        figure: evidence.table_record(
            evidence.paired_estimates(
                grid, menus, PRIMARY_ARM, BASE_ARM, f"train_{figure}", seed, boot
            )
        )
        for figure in REPLAY_FIGURES
    }
    out["dr2_gain"] = evidence.table_record(
        evidence.paired_estimates(grid, menus, PRIMARY_ARM, BASE_ARM, "dr2", seed, boot)
    )
    per_menu: dict[str, Any] = {}
    for menu in menus:
        replay = evidence.replay_contrast(grid, menu, PRIMARY_ARM, BASE_ARM, seed)
        dr2, changed = evidence.score_change(grid, menu, PRIMARY_ARM, BASE_ARM, seed)
        deltas = {
            name: grid.values(menu, PRIMARY_ARM, f"test_{name}", seed)
            - grid.values(menu, BASE_ARM, f"test_{name}", seed)
            for name in ("bad", "typical", "good", "utility")
        }
        three = _indicator(deltas["bad"], deltas["typical"], deltas["good"])
        four = _indicator(deltas["bad"], deltas["typical"], deltas["good"], deltas["utility"])
        guards = grid.objects(menu, PRIMARY_ARM, "guards", seed)
        sacrifice = grid.values(menu, PRIMARY_ARM, "sacrifice", seed)
        counts: Counter[str] = Counter()
        cells = 0
        for j in range(len(RISK_CELLS)):
            for value in guards[j]:
                if value is not None:
                    cells += 1
                    counts.update(json.loads(value))
        per_menu[menu] = {
            "replay": _replay_record(replay),
            "dr2_gain": dr2,
            "changed_share": changed,
            "share_all_three_improve": _origin_point(three, grid.k),
            "share_all_four_improve": _origin_point(four, grid.k),
            "sacrifice": {
                "mean": _origin_point(sacrifice, grid.k),
                "max": _max(sacrifice),
                "share_at_cap": _origin_point(
                    np.where(
                        np.isfinite(sacrifice),
                        (sacrifice >= PRIMARY_ALLOWANCE - 1e-10) * 1.0,
                        np.nan,
                    ),
                    grid.k,
                ),
            },
            "binding_guards": {
                g: counts[g] / cells if cells else None
                for g in ("bad", "typical", "good", "u", "veto")
            },
            "risk_cell_entries": cells,
        }
    out["menus"] = per_menu
    return out


def _indicator(*deltas: np.ndarray) -> np.ndarray:
    stacked = np.stack(deltas)
    defined = np.isfinite(stacked).all(axis=0)
    return np.where(defined, (stacked > 0).all(axis=0) * 1.0, np.nan)


def _origin_point(x: np.ndarray, k: int) -> float | None:
    if k == 0:
        return None
    value = float(evidence.origin_mean(x, np.arange(k)[None, :])[0])
    return value if math.isfinite(value) else None


def _max(x: np.ndarray) -> float | None:
    finite = x[np.isfinite(x)]
    return float(finite.max()) if finite.size else None


def _replay_record(r: Replay | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {
        "u": r.u,
        "bad": r.bad,
        "typical": r.typical,
        "good": r.good,
        "es": r.es,
        "cells_u": dict(r.cells_u),
        "banks": [
            {
                "u": b.u,
                "bad": b.bad,
                "typical": b.typical,
                "good": b.good,
                "es": b.es,
                "cells_u": dict(b.cells_u),
            }
            for b in r.banks
        ],
    }


def _realized_section(
    grid: Grid, menus: Sequence[str], seed: int, boot: Bootstrap, coefficients: Sequence[float]
) -> dict[str, Any]:
    """Per-arm quantiles across origins and their U, contrasts within each cell (ruling 7)."""
    arms = (PRIMARY_ARM, BASE_ARM)
    paired = {}
    for menu in menus:
        a = grid.values(menu, PRIMARY_ARM, "annual_return", seed, realized=True)
        b = grid.values(menu, BASE_ARM, "annual_return", seed, realized=True)
        ok = np.isfinite(a) & np.isfinite(b)
        paired[menu] = {PRIMARY_ARM: np.where(ok, a, np.nan), BASE_ARM: np.where(ok, b, np.nan)}
    levels = {}
    for menu in menus:
        levels[menu] = {
            _arm_name(arm): {
                cell: {
                    name: evidence.percentile(paired[menu][arm][j].tolist(), 100 * q)
                    for name, q in evidence.QUANTILES
                }
                for j, cell in enumerate(RISK_CELLS)
            }
            for arm in arms
        }
        for arm_levels in levels[menu].values():
            for cell_levels in arm_levels.values():
                q = [cell_levels[name] for name, _ in evidence.QUANTILES]
                cell_levels["utility"] = (
                    None if None in q else sum(k * v for k, v in zip(coefficients, q, strict=True))
                )
        for arm in arms:
            for j, cell in enumerate(RISK_CELLS):
                tail = evidence.expected_shortfall(paired[menu][arm][j], np.arange(grid.k)[None, :])
                value = float(tail[0])
                levels[menu][_arm_name(arm)][cell]["es_25"] = (
                    value if math.isfinite(value) else None
                )
    contrasts: dict[str, Any] = {}
    for name, q in (*evidence.QUANTILES, ("utility", None), ("es_25", None)):
        stats: dict[str, list] = {}
        counts: dict[str, list[int]] = {}
        for menu in menus:
            stats[menu], counts[menu] = [], []
            for j in range(len(RISK_CELLS)):
                x1, x2 = paired[menu][PRIMARY_ARM][j], paired[menu][BASE_ARM][j]
                stats[menu].append(_quantile_contrast(x1, x2, name, q, coefficients))
                counts[menu].append(int(np.isfinite(x1).sum()))
        contrasts[name] = evidence.table_record(evidence.nonlinear_table(stats, counts, boot))
    menus_out = {}
    for menu in menus:
        menus_out[menu] = {"quantiles": levels[menu]}
    return {
        "arms": [_arm_name(arm) for arm in arms],
        "per_arm": menus_out,
        "quantile_contrasts_rd_minus_r": contrasts,
        "underpowered": "q(.025) and ES_2.5 superiority across origins are underpowered below "
        "200 disjoint annual intervals",
    }


def _quantile_contrast(
    x1: np.ndarray, x2: np.ndarray, name: str, q: float | None, coefficients: Sequence[float]
) -> evidence.Statistic:
    """R+D minus R of a statistic across origins within one risk cell (a quantile, U, ES)."""
    if q is not None:
        return lambda i: evidence.quantile(x1, q, i) - evidence.quantile(x2, q, i)
    if name == "es_25":
        return lambda i: evidence.expected_shortfall(x1, i) - evidence.expected_shortfall(x2, i)

    def utility(i: np.ndarray) -> np.ndarray:
        total = np.zeros(i.shape[0])
        for k, (_, level) in zip(coefficients, evidence.QUANTILES, strict=True):
            total = total + k * (evidence.quantile(x1, level, i) - evidence.quantile(x2, level, i))
        return total

    return utility


def _forecast_error(grid: Grid, menus: Sequence[str], seed: int, boot: Bootstrap) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for menu in menus:
        errors = grid.values(menu, BASE_ARM, "forecast_error", seed, realized=True)
        difference = grid.values(menu, PRIMARY_ARM, "annual_return", seed, realized=True) - (
            grid.values(menu, BASE_ARM, "annual_return", seed, realized=True)
        )
        cells = {}
        for j, cell in enumerate(RISK_CELLS):
            e, d = errors[j], difference[j]
            n = int((np.isfinite(e) & np.isfinite(d)).sum())
            est = boot.estimate(
                lambda i, a=e, b=d: evidence.correlation(a, b, i), DESCRIPTIVE_LEVEL, n
            )
            record = est.record()
            record["sign"] = None if est.value is None else int(np.sign(est.value))
            cells[cell] = record
        out[menu] = cells
    return out


def selection_frequencies(grid: Grid, menu: str) -> dict[str, Any]:
    """Across every optimizer seed and origin, per risk cell: how often R+D is exactly w_R and
    how often each guard binds the R+D selection (protocol 6 selection/guard frequencies)."""
    out: dict[str, Any] = {}
    for j, cell in enumerate(RISK_CELLS):
        same, entries = 0, 0
        guards: Counter[str] = Counter()
        for seed in grid.seeds:
            first = grid.lists(menu, PRIMARY_ARM, "weights", seed)
            second = grid.lists(menu, BASE_ARM, "weights", seed)
            found = grid.objects(menu, PRIMARY_ARM, "guards", seed)[j]
            for t in range(grid.k):
                if first.shape[0] == 0 or not np.isfinite(first[:, j, t]).all():
                    continue
                entries += 1
                same += bool(np.array_equal(first[:, j, t], second[:, j, t]))
                guards.update(json.loads(found[t] or "[]"))
        out[cell] = {
            "entries": entries,
            "r_plus_d_is_w_r": same / entries if entries else None,
            "binding_guards": {
                g: guards[g] / entries if entries else None
                for g in ("bad", "typical", "good", "u", "veto")
            },
        }
    return out


def _stability_record(s: evidence.Stability) -> dict[str, Any]:
    return {
        "median_l1": dict(s.median_l1),
        "p90_l1": dict(s.p90_l1),
        "bad_sd_share": dict(s.bad_sd_share),
        "turnover_median": dict(s.turnover_median),
        "diagnostics": dict(s.diagnostics),
    }


@dataclass(frozen=True)
class SensitivityReplays:
    """The decision inputs (None: unavailable), Stage 1 on the six origins, and per menu and
    setting the descriptive contrast and the reasons of an unavailable setting."""

    settings: dict[str, dict[str, Replay | None]]
    primary_six: dict[str, Replay | None]
    partial: dict[str, dict[str, Replay | None]]
    reasons: dict[str, dict[str, list[str]]]


def _sensitivity_replays(
    stage1: RunFiles,
    sensitivities: Mapping[str, RunFiles | None],
    menus: Sequence[str],
    six: Sequence[str],
    seed: int,
    problems: Mapping[str, Sequence[str]],
) -> SensitivityReplays:
    """Each setting's six-origin paired replay contrast per menu and Stage 1's on those origins.

    A sensitivity profile whose run is missing or not complete, or that has a problem
    (`profile_problems`), is unavailable: the decision gets None, and its contrast over the
    available cells, if any, is kept apart as descriptive.
    """
    assert stage1.outcomes is not None
    settings: dict[str, dict[str, Replay | None]] = {menu: {} for menu in menus}
    partial: dict[str, dict[str, Replay | None]] = {menu: {} for menu in menus}
    reasons: dict[str, dict[str, list[str]]] = {menu: {} for menu in menus}
    stage_grid = Grid(stage1.outcomes, six, profile=STAGE_1)
    absent = "no paired outcome on the six origins"

    def contrast(grid: Grid, menu: str, arm: Arm) -> Replay | None:
        if not (grid.has(menu, arm, seed) and grid.has(menu, BASE_ARM, seed)):
            return None
        return evidence.replay_contrast(grid, menu, arm, BASE_ARM, seed)

    primary_six = {menu: contrast(stage_grid, menu, PRIMARY_ARM) for menu in menus}
    for menu in menus:
        for name, allowance in SWEEP.items():
            settings[menu][name] = contrast(stage_grid, menu, ("R+D", allowance))
            reasons[menu][name] = [] if settings[menu][name] is not None else [absent]
    for run_name, profiles in SENSITIVITY_RUNS.items():
        run = sensitivities.get(run_name)
        for profile in profiles:
            why = list(problems.get(profile, []))
            if run is None:
                why = why or [f"{profile}: not run"]
            elif run.state != "complete":
                why.insert(0, f"{profile}: the run is {run.state}")
            for menu in menus:
                found = None
                if run is not None and run.outcomes is not None:
                    found = contrast(Grid(run.outcomes, six, profile=profile), menu, PRIMARY_ARM)
                settings[menu][profile] = None if why else found
                if why and found is not None:
                    partial[menu][profile] = found
                reasons[menu][profile] = why or ([] if found is not None else [absent])
    return SensitivityReplays(settings, primary_six, partial, reasons)


def _sensitivity_section(
    replays: SensitivityReplays, six: Sequence[str], verdict: Verdict
) -> dict[str, Any]:
    disclosed = {(d.menu, d.setting): d.record() for d in verdict.disclosures}

    def entry(menu: str, name: str, replay: Replay | None) -> dict[str, Any]:
        descriptive = name in replays.partial[menu]
        shown = replay if replay is not None else replays.partial[menu].get(name)
        return {
            "available": replay is not None,
            "unavailable": replays.reasons[menu][name],
            "descriptive_only": descriptive,
            "replay": _replay_record(shown),
            "pooled_gain_at_least_5bp": None
            if replay is None or replay.u is None
            else replay.u >= evidence.REPLAY_GAIN,
            "disclosure": disclosed.get((menu, name)),
        }

    return {
        "origins": list(six),
        "seed": "primary only; cross-seed stability is unavailable for every setting",
        "reversal_baseline": "stage_1_six_origins: Stage 1 on these six origins (R27)",
        "menus": {
            menu: {
                "stage_1_six_origins": _replay_record(replays.primary_six.get(menu)),
                "settings": {name: entry(menu, name, replay) for name, replay in found.items()},
                "cross_seed_stability": disclosed.get((menu, "cross-seed stability")),
            }
            for menu, found in replays.settings.items()
        },
    }


def _labels(verdict: Verdict, menus: Mapping[str, MenuEvidence]) -> dict[str, Any]:
    return {
        "experiment": evidence.VALID if verdict.valid else evidence.INVALID,
        "experiment_reasons": list(verdict.validity_reasons),
        "menus": {
            menu: {
                "conditional": v.conditional,
                "branch": v.branch,
                "positive_conditional_model_evidence": v.pcme,
                "score_change": v.score_change,
                "realized": v.realized,
                "realized_policy_support": v.support,
                "tail_power": v.tail_power,
                "intervals": v.intervals,
                "sensitivity": v.sensitivity,
                "disjoint_panel": menus[menu].realized.disjoint,
            }
            for menu, v in verdict.menus.items()
        },
    }


def _harm_record(criterion: evidence.Criterion, summary: Mapping[str, Any]) -> dict[str, Any]:
    """A material-harm breach with its paired uncertainty (95% descriptive interval)."""
    record = criterion.record()
    if criterion.key == "guard.median_loss":
        table = summary["realized"]["quantile_contrasts_rd_minus_r"]["typical"]
        record["uncertainty_of"] = "R+D minus R median annual return across origins"
        record["uncertainty"] = table["by_cell"][criterion.menu][criterion.location]
        return record
    figure = {
        "replay.bad": ("replay", "bad"),
        "replay.typical": ("replay", "typical"),
        "replay.good": ("replay", "good"),
        "replay.cell_u": ("replay", "utility"),
        "harm.u": ("replay", "utility"),
        "guard.mean_loss": ("realized", "annual_return"),
        "guard.loss_frequency": ("realized", "loss"),
        "guard.drawdown": ("realized", "max_drawdown"),
    }.get(criterion.key)
    if figure is not None:
        table = summary["primary"][figure[0]][figure[1]]
        record["uncertainty_of"] = f"R+D minus R paired {figure[0]} {figure[1]}" + (
            " (improvement: R minus R+D)" if figure[1] == "max_drawdown" else ""
        )
        record["uncertainty"] = (
            table["by_menu"][criterion.menu]
            if criterion.location == "menu"
            else table["by_cell"][criterion.menu][criterion.location]
        )
    return record


def _quantiles(values: Sequence[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "median": evidence.percentile(values, 50),
        "p95": evidence.percentile(values, 95),
        "max": max(values) if values else None,
        "sum": math.fsum(values),
    }


def _profile_cost(run: RunFiles, profile: str | None, menus: Sequence[str]) -> dict[str, Any]:
    cells = [
        r
        for r in run.resources
        if r.get("kind") == "cell" and (profile is None or r.get("profile") == profile)
    ]
    out: dict[str, Any] = {}
    for menu in menus:
        mine = [c for c in cells if json.loads(c["cell_key"])[0] == menu]
        arms: dict[str, dict[str, list[float]]] = {}
        ratios = []
        for cell in mine:
            walls = {}
            for arm in cell.get("arms", []):
                parts = arms.setdefault(arm["arm"], {})
                for part in (
                    "wall",
                    "return_evaluation",
                    "score",
                    "native_selection",
                    "solver",
                    "calls",
                    "evaluations",
                    "invalid",
                    "failed_starts",
                ):
                    parts.setdefault(part, []).append(float(arm.get(part, 0.0)))
                walls[arm["arm"]] = float(arm["wall"])
            if {"R", "R+D"} <= set(walls) and walls["R"] > 0:
                ratios.append(
                    {
                        "cell_key": cell["cell_key"],
                        "ratio": walls["R+D"] / walls["R"],
                        "r_wall": walls["R"],
                        "rd_wall": walls["R+D"],
                    }
                )
        shared = [c.get("shared", {}) for c in mine]
        out[menu] = {
            "cells": len(mine),
            "statuses": dict(Counter(c.get("status") for c in mine)),
            "search_cost_by_arm": {
                arm: {part: _quantiles(values) for part, values in parts.items()}
                for arm, parts in sorted(arms.items())
            },
            "shared_preprocessing_and_broad_search": {
                part: _quantiles([float(s.get(part, 0.0)) for s in shared])
                for part in ("wall", "return_evaluation", "score", "bank")
            },
            "union_rescoring": _quantiles([float(c.get("union", 0.0)) for c in mine]),
            "selection": _quantiles([float(c.get("selection", 0.0)) for c in mine]),
            "tables": _quantiles([float(c.get("tables", 0.0)) for c in mine]),
            "cell_wall": _quantiles([float(c.get("wall", 0.0)) for c in mine]),
            "cell_cpu": _quantiles([float(c.get("cpu", 0.0)) for c in mine]),
            "failed_cell_wall": _quantiles(
                [float(c.get("wall", 0.0)) for c in mine if c.get("status") != OK_CELL]
            ),
            "paired_wall_ratio": _quantiles([r["ratio"] for r in ratios]),
            "paired_wall_ratios": ratios,
        }
    evaluations = [r for r in run.resources if r.get("kind") == "evaluation"]
    ends = [r for r in run.resources if r.get("kind") == "run" and r.get("event") == "end"]
    out["independent_evaluation"] = {
        "groups": len(evaluations),
        "mixes": sum(int(r.get("mixes", 0)) for r in evaluations),
        "wall": math.fsum(float(r.get("wall", 0.0)) for r in evaluations),
        "cpu": math.fsum(float(r.get("cpu", 0.0)) for r in evaluations),
    }
    out["whole_run"] = ends[-1] if ends else None
    out["breaches"] = [r for r in run.resources if r.get("kind") == "breach"]
    return out


def _cost_section(
    stage1: RunFiles, sensitivities: Mapping[str, RunFiles | None], menus: Sequence[str]
) -> dict[str, Any]:
    cpu = float((stage1.manifest.get("execution") or {}).get("cpu_seconds") or 0.0)
    sensitivity_cpu = {
        name: None
        if run is None
        else float((run.manifest.get("execution") or {}).get("cpu_seconds") or 0.0)
        for name, run in sensitivities.items()
    }
    total = cpu + sum(v for v in sensitivity_cpu.values() if v is not None)
    limits = stage1.manifest.get("limits") or {}
    return {
        "separation": "search cost = an arm's warm wall time from its fresh cache to its native "
        "selection (replay scoring 'return_evaluation', measure scoring 'score', the native "
        "selection on its own archive 'native_selection' net of its scoring, solver and "
        "overhead 'solver'); shared preprocessing and broad search, union rescoring and "
        "independent evaluation are charged separately; failed calls are inside the arm wall "
        "and counted under 'invalid'; an arm stopped at the time ceiling counts what it did",
        "stage_1": _profile_cost(stage1, STAGE_1, menus),
        "sensitivities": {
            name: None if run is None else _profile_cost(run, None, menus)
            for name, run in sensitivities.items()
        },
        "cpu_hours": {
            "stage_1": cpu / 3600.0,
            "sensitivities": {
                k: None if v is None else v / 3600.0 for k, v in sensitivity_cpu.items()
            },
            "total": total / 3600.0,
            "ceiling": limits.get("cpu_hours"),
            "amended": limits.get("cpu_hours_amendment"),
        },
    }
