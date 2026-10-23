"""Command line of the fixed-risk run: `python -m portfoliosight.research.fixedrisk.cli ...`.

    freeze   print how to freeze the inputs (scripts/freeze_fixed_risk_inputs.py), or run it
    estimate --snapshot S --engine E --host-label L [--out-dir D] [--hooks MODULE]
    parent   --snapshot S --run-dir R --solver-replay X --solver-garch Y
             [--placement JOB=HOST ...] [--estimate FILE ...]
    run      --run-dir R --menu M --engine E [--workers 6] [--snapshot S] [--host-label L]
    status   --run-dir R

Run with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1` (workers refuse otherwise).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import data, driver, estimate, manifest
from portfoliosight.research.fixedrisk.menus import MENUS

REPO = Path(__file__).resolve().parents[3]
BLAS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")


def _require_blas() -> None:
    wrong = {name: os.environ.get(name) for name in BLAS if os.environ.get(name) != "1"}
    if wrong:
        raise SystemExit(f"set {', '.join(BLAS)} to 1 before running (found {wrong})")


def _parse_pairs(items: list[str] | None) -> dict[str, str]:
    pairs = {}
    for item in items or []:
        key, _, value = item.partition("=")
        if not value:
            raise SystemExit(f"expected JOB=VALUE, got {item!r}")
        pairs[key] = value
    return pairs


def cmd_freeze(args: argparse.Namespace) -> int:
    script = REPO / "scripts" / "freeze_fixed_risk_inputs.py"
    if not args.run:
        print(f"{sys.executable} {script} [--mirror DIR] [--root DIR] [--d-star DATE]")
        print(f"{sys.executable} {script} --verify SNAPSHOT_DIR")
        return 0
    return subprocess.call([sys.executable, str(script), *args.rest])


def cmd_estimate(args: argparse.Namespace) -> int:
    _require_blas()
    base = Path(args.out_dir) if args.out_dir else Path(args.snapshot).parent.parent / "estimates"
    inputs = data.load_inputs(args.snapshot, ledger_cache=base / "ledger_cache")
    solvers = dict.fromkeys(C.ENGINES, args.solver)
    hooks = driver.load_hooks(args.hooks, solvers)
    out = base / f"{args.host_label}_{args.engine}"
    result = estimate.run_estimate(inputs, args.engine, args.host_label, hooks, out)
    print(json.dumps({"out": str(out / "estimate.json"), "jobs": result["jobs"]}, indent=2))
    return 0


def cmd_parent(args: argparse.Namespace) -> int:
    inputs = data.load_inputs(args.snapshot, ledger_cache=Path(args.run_dir) / "ledger_cache")
    solvers = {"replay": args.solver_replay, "garch": args.solver_garch}
    placement = dict(manifest.PROTOCOL_PLACEMENT)
    projections = dict(manifest.PROTOCOL_PROJECTION)
    source = "protocol §8 assumptions"
    estimates = [json.loads(Path(p).read_text()) for p in args.estimate or []]
    explicit = _parse_pairs(args.placement)
    if estimates:
        by_host: dict[str, dict[str, float]] = {}
        for est in estimates:
            by_host.setdefault(est["host"]["label"], {}).update(est["jobs"])
        hosts = sorted(by_host)
        costs = {
            key: {h: by_host[h].get(key, projections[key]) for h in hosts}
            for key in manifest.expected_job_keys()
        }
        source = f"measured estimates {args.estimate}"
        if len(hosts) >= 2 and not explicit:
            placement, wall = manifest.place(costs, hosts)
            source += f"; placement minimizes the larger host wall time {wall}"
        placement.update(explicit)
        projections = {
            key: costs[key].get(placement[key], min(costs[key].values())) for key in costs
        }
    else:
        placement.update(explicit)
    parent = manifest.build_parent(
        inputs,
        snapshot_dir=Path(args.snapshot),
        solvers=solvers,
        placement=placement,
        projections=projections,
        projection_source=source,
        hooks=args.hooks,
    )
    path = manifest.write_parent(Path(args.run_dir), parent)
    print(
        json.dumps(
            {"parent": str(path), "digest": parent["digest"], "jobs": parent["jobs"]}, indent=2
        )
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    _require_blas()
    result = driver.run_job(
        Path(args.run_dir),
        args.menu,
        args.engine,
        snapshot_dir=args.snapshot,
        workers=args.workers,
        hooks=args.hooks,
        host_label=args.host_label,
    )
    summary = {
        "job": result.job,
        "status": result.status,
        "tasks": result.tasks_total,
        "done": result.tasks_done,
        "failed": result.tasks_failed,
        "cpu_hours": result.cpu_seconds / 3600.0,
        "breach": result.breach,
    }
    print(json.dumps(summary))
    return 0 if result.status == "complete" else 1


def cmd_status(args: argparse.Namespace) -> int:
    for row in driver.job_status(Path(args.run_dir)):
        print(json.dumps(row))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fixedrisk", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("freeze", help="document or run scripts/freeze_fixed_risk_inputs.py")
    p.add_argument("--run", action="store_true", help="run the script with the remaining arguments")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_freeze)

    p = sub.add_parser("estimate", help="measure unit costs on the six showcase origins")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--engine", required=True, choices=C.ENGINES)
    p.add_argument("--host-label", required=True)
    p.add_argument("--out-dir")
    p.add_argument("--solver", default="exact_grad")
    p.add_argument("--hooks")
    p.set_defaults(func=cmd_estimate)

    p = sub.add_parser("parent", help="write the parent manifest of a run")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--solver-replay", required=True)
    p.add_argument("--solver-garch", required=True)
    p.add_argument("--placement", nargs="*", help="JOB=HOST (override), e.g. tsp_garch=ks002")
    p.add_argument("--estimate", nargs="*", help="estimate.json files (one per host and engine)")
    p.add_argument("--hooks")
    p.set_defaults(func=cmd_parent)

    p = sub.add_parser("run", help="run one job (menu, engine)")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--menu", required=True, choices=[m.name for m in MENUS])
    p.add_argument("--engine", required=True, choices=C.ENGINES)
    p.add_argument("--workers", type=int, default=manifest.WORKERS)
    p.add_argument("--snapshot", help="snapshot path on this host (digest must match the parent)")
    p.add_argument("--host-label")
    p.add_argument("--hooks")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status", help="progress of every job of a run")
    p.add_argument("--run-dir", required=True)
    p.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
