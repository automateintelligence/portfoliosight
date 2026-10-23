"""Parent and job manifests of the fixed-risk run (protocol §8).

The parent manifest (`<run_dir>/parent.json`) is written before any job starts: protocol path and
hash, snapshot digest, each menu's schedule, each engine's solver, the seeds, the four expected job
keys, each job's CPU budget and host, and the git HEAD. Its digest is the SHA-256 of the canonical
JSON of the body without `created_utc` and `digest`. Each job manifest carries that digest, the
host name and label, the CPU model and the library versions.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import itertools
import json
import os
import platform
import socket
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import cscv, data
from portfoliosight.research.fixedrisk.menus import MENUS

REPO = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
WORKERS = 6
RSS_CEILING = 4 * 2**30
ARM_SECONDS = 600.0
# Protocol §8 sets 240; raised to cover the measured COBYLA-768 projections of all four jobs
# (stated override, 2026-10-23: both engines' gates chose COBYLA-768; the measured projections
# total about 691 CPU-hours, x 1.1).
CPU_HOURS = 760.0
DEPENDENCIES = (
    "numpy", "scipy", "pandas", "pyarrow", "cvxpy", "clarabel", "scikit-learn",
    "exchange_calendars", "threadpoolctl", "arch",
)  # fmt: skip
# Protocol §8 CPU-hour projections per job (assumptions until the estimate command measures them).
PROTOCOL_PROJECTION = {
    "research2003_replay": 19.2,
    "tsp_replay": 18.9,
    "research2003_garch": 36.6,
    "tsp_garch": 10.2,
}
PROTOCOL_PLACEMENT = {
    "research2003_replay": "local",
    "tsp_replay": "local",
    "research2003_garch": "ks002",
    "tsp_garch": "ks002",
}


def utc() -> str:
    return datetime.now(UTC).isoformat()


def job_key(menu: str, engine: str) -> str:
    return f"{menu}_{engine}"


def expected_job_keys() -> list[str]:
    return [job_key(menu.name, engine) for engine in C.ENGINES for menu in MENUS]


def canonical(body: Mapping[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def body_digest(body: Mapping[str, Any]) -> str:
    kept = {k: v for k, v in body.items() if k not in ("digest", "created_utc")}
    return hashlib.sha256(canonical(kept)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(repo: Path = REPO) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30
    )
    return done.stdout.strip() if done.returncode == 0 else "unknown"


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.partition(":")[2].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def library_versions() -> dict[str, str | None]:
    found: dict[str, str | None] = {}
    for name in DEPENDENCIES:
        try:
            found[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            found[name] = None
    return found


def host_info(label: str | None = None) -> dict[str, Any]:
    name = socket.gethostname()
    return {
        "hostname": name,
        "label": label or name,
        "cpu_model": cpu_model(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "libraries": library_versions(),
        "blas_env": {
            n: os.environ.get(n)
            for n in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
        },
    }


# ------------------------------------------------------------------ budgets and placement


def budgets(projections: Mapping[str, float], total: float = CPU_HOURS) -> dict[str, float]:
    """`total x (job projection / all projections)`; the budgets sum to `total`."""
    whole = sum(projections.values())
    if whole <= 0:
        raise ValueError("projections must sum to a positive number")
    return {key: total * value / whole for key, value in projections.items()}


def place(
    costs: Mapping[str, Mapping[str, float]], hosts: Sequence[str], workers: int = WORKERS
) -> tuple[dict[str, str], dict[str, float]]:
    """Assign each job to a host so the larger host wall time is smallest.

    ``costs[job][host]`` is the job's projected CPU-hours at that host's measured rate. A host runs
    its jobs one at a time on ``workers`` workers: wall = sum of its jobs' CPU-hours / workers.
    Returns the assignment and each host's projected wall hours.
    """
    jobs = sorted(costs)
    best: tuple[float, dict[str, str], dict[str, float]] | None = None
    for choice in itertools.product(hosts, repeat=len(jobs)):
        wall = dict.fromkeys(hosts, 0.0)
        for job, host in zip(jobs, choice, strict=True):
            wall[host] += costs[job][host] / workers
        score = (max(wall.values()), sum(wall.values()))
        if best is None or score < (max(best[2].values()), sum(best[2].values())):
            best = (score[0], dict(zip(jobs, choice, strict=True)), wall)
    assert best is not None
    return best[1], best[2]


# ------------------------------------------------------------------------- parent manifest


def run_settings() -> dict[str, Any]:
    """The experiment settings of the running code (recorded in, and checked against, a parent)."""
    return {
        "paths": C.PATHS,
        "horizon": C.HORIZON,
        "lookback": C.LOOKBACK,
        "sensitivity_lookback": C.SENSITIVITY_LOOKBACK,
        "risk_fractions": list(C.RISK_FRACTIONS),
        "cells": list(C.CELLS),
        "arms": {name: list(triple) for name, triple in C.ARMS.items()},
        "arm_order": list(C.ARM_ORDER),
        "tau_r": C.TAU_R,
        "tau_r_sensitivity": C.TAU_R_SENSITIVITY,
        "tau_d": C.TAU_D,
        "starts": C.STARTS,
        "sobol_points": C.SOBOL_POINTS,
        "showcase_columns": 48,
        "showcase_d_grid": [round(0.05 * k, 2) for k in range(1, 20)],
    }


def run_seeds() -> dict[str, Any]:
    return {
        "primary": C.PRIMARY_SEED,
        "stability": list(C.STABILITY_SEEDS),
        "test": list(C.TEST_SEEDS),
        "stability_stride": C.STABILITY_STRIDE,
    }


def run_ceilings() -> dict[str, Any]:
    return {
        "workers_per_host": WORKERS,
        "rss_bytes_per_host": RSS_CEILING,
        "arm_seconds": ARM_SECONDS,
        "cpu_hours_total": CPU_HOURS,
        "one_job_at_a_time_per_host": True,
        "stop_on_breach": True,
    }


def code_head(repo: Path = REPO) -> str:
    """The running code's commit: `git rev-parse HEAD`, else the `GIT_HEAD` file that
    `scripts/ks002_sync.sh push` writes beside a copied worktree (no git objects there)."""
    head = git_head(repo)
    if head != "unknown":
        return head
    path = repo / "GIT_HEAD"
    return path.read_text().strip() if path.is_file() else "unknown"


def code_mismatches(
    parent: Mapping[str, Any], *, hooks: str | None = None, repo: Path = REPO
) -> list[str]:
    """Why the running code is not the code the parent manifest records (empty when it is):
    git HEAD, protocol revision, settings, seeds, ceilings, hooks and the engines' solvers."""
    problems = []
    head, recorded = code_head(repo), parent.get("git_head")
    if head == "unknown" or head != recorded:
        problems.append(f"code is at commit {head}, the parent manifest records {recorded}")
    if parent["protocol"]["revision"] != C.PROTOCOL_REVISION:
        problems.append(
            f"protocol revision {C.PROTOCOL_REVISION} in the code, "
            f"{parent['protocol']['revision']} in the parent"
        )
    for name, current in (
        ("settings", run_settings()),
        ("seeds", run_seeds()),
        ("ceilings", run_ceilings()),
    ):
        if parent.get(name) != current:
            changed = sorted(
                k
                for k in set(current) | set(parent.get(name) or {})
                if current.get(k) != (parent.get(name) or {}).get(k)
            )
            problems.append(f"{name} differ from the parent's: {changed}")
    if hooks and hooks != parent.get("hooks"):
        problems.append(f"hooks {hooks!r} differ from the parent's {parent.get('hooks')!r}")
    if not (hooks or parent.get("hooks")):
        from portfoliosight.research.fixedrisk.optimizer import SOLVERS

        for engine, entry in parent["engines"].items():
            if entry["solver"] not in SOLVERS:
                problems.append(f"{engine} solver {entry['solver']!r} is not one of {SOLVERS}")
    return problems


def menu_facts(inputs: data.ResearchInputs, menu: C.MenuSpec) -> dict[str, Any]:
    months = data.schedule(inputs, menu)
    intervals = data.disjoint_intervals(inputs, menu)
    ledger = inputs.ledger(menu)
    scheduled = set(months)
    realized = [i for i in data.realized_intervals(inputs, menu) if i.month in scheduled]
    return {
        "holdings": list(menu.holdings),
        "lower": list(menu.lower),
        "upper": list(menu.upper),
        "boundary_month": ledger.boundary_month,
        "boundary_fund": ledger.boundary_fund,
        "schedule": months,
        "first_origin": months[0] if months else None,
        "last_origin": months[-1] if months else None,
        "origins": len(months),
        "showcase_months": data.showcase_months(inputs, menu),
        "stability_months": data.stability_months(inputs, menu),
        "lookback5_months": data.lookback5_months(inputs, menu),
        "disjoint_intervals": [
            {
                "month": i.month,
                "origin": i.origin.isoformat(),
                "horizon_start": i.horizon_start.isoformat(),
                "horizon_end": i.horizon_end.isoformat(),
            }
            for i in intervals
        ],
        "disjoint_interval_count": len(intervals),
        # frozen before any job runs; the report reads these masks unchanged (protocol §7)
        "cscv": cscv.frozen_record(
            [i.month for i in realized],
            [i.origin.isoformat() for i in realized],
            [i.horizon_end.isoformat() for i in realized],
        ),
    }


def build_parent(
    inputs: data.ResearchInputs,
    *,
    snapshot_dir: Path,
    solvers: Mapping[str, str],
    placement: Mapping[str, str],
    projections: Mapping[str, float],
    projection_source: str = "protocol §8 assumptions",
    repo: Path = REPO,
    hooks: str | None = None,
) -> dict[str, Any]:
    keys = expected_job_keys()
    if sorted(placement) != sorted(keys) or sorted(projections) != sorted(keys):
        raise ValueError(f"placement and projections must name exactly the jobs {keys}")
    if sorted(solvers) != sorted(C.ENGINES):
        raise ValueError(f"solvers must name exactly the engines {list(C.ENGINES)}")
    cpu_budget = budgets(projections)
    protocol = repo / C.PROTOCOL_PATH
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "fixed_risk_parent",
        "protocol": {
            "path": C.PROTOCOL_PATH,
            "revision": C.PROTOCOL_REVISION,
            "sha256": file_sha256(protocol) if protocol.is_file() else None,
        },
        "snapshot": {
            "path": str(inputs.root) if inputs.root else None,
            "manifest_sha256": inputs.manifest_sha256,
            "d_star": inputs.d_star.isoformat(),
        },
        "menus": {menu.name: menu_facts(inputs, menu) for menu in inputs.menus},
        "engines": {engine: {"solver": solvers[engine]} for engine in C.ENGINES},
        "settings": run_settings(),
        "seeds": run_seeds(),
        "jobs": {
            key: {
                "menu": key.rsplit("_", 1)[0],
                "engine": key.rsplit("_", 1)[1],
                "host": placement[key],
                "projected_cpu_hours": projections[key],
                "cpu_hours_budget": cpu_budget[key],
            }
            for key in keys
        },
        "projection_source": projection_source,
        "ceilings": run_ceilings(),
        "placement": dict(placement),
        "hooks": hooks,
        "git_head": git_head(repo),
    }
    body["digest"] = body_digest(body)
    return {**body, "created_utc": utc()}


def write_parent(run_dir: Path, parent: Mapping[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "parent.json"
    if path.exists():
        existing = json.loads(path.read_text())
        if existing.get("digest") != parent["digest"]:
            raise FileExistsError(f"{path} exists with another digest; use a new run directory")
        return path
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(parent, indent=2, sort_keys=True) + "\n")
    tmp.rename(path)
    return path


def read_parent(run_dir: Path) -> dict[str, Any]:
    parent = json.loads((run_dir / "parent.json").read_text())
    if body_digest(parent) != parent.get("digest"):
        raise ValueError(f"{run_dir / 'parent.json'}: digest does not match its contents")
    return parent


def job_manifest(
    parent: Mapping[str, Any],
    menu: str,
    engine: str,
    host_label: str | None,
    *,
    status: str,
    tasks_total: int,
    tasks_done: int,
    failed: int,
    cpu_seconds: float,
    breach: Mapping[str, Any] | None = None,
    started_utc: str | None = None,
) -> dict[str, Any]:
    key = job_key(menu, engine)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "fixed_risk_job",
        "job": key,
        "menu": menu,
        "engine": engine,
        "parent_digest": parent["digest"],
        "host": host_info(host_label),
        "status": status,  # running | complete | incomplete
        "incomplete": status != "complete",
        "tasks_total": tasks_total,
        "tasks_done": tasks_done,
        "tasks_failed": failed,
        "cpu_seconds": cpu_seconds,
        "cpu_hours_budget": parent["jobs"][key]["cpu_hours_budget"],
        "solver": parent["engines"][engine]["solver"],
        "breach": dict(breach) if breach else None,
        "started_utc": started_utc or utc(),
        "updated_utc": utc(),
    }
