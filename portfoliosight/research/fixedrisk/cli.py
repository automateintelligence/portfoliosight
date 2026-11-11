"""Command line of the fixed-risk run: `python -m portfoliosight.research.fixedrisk.cli ...`.

    freeze   print how to freeze the inputs (scripts/freeze_fixed_risk_inputs.py), or run it
    estimate --snapshot S --engine E --host-label L [--out-dir D] [--hooks MODULE]
    parent   --snapshot S --run-dir R --solver-replay X --solver-garch Y
             [--placement JOB=HOST ...] [--estimate FILE ...]
    run      --run-dir R --menu M --engine E [--workers 6] [--snapshot S] [--host-label L]
    status   --run-dir R
    v3-parent  --snapshot S --run-dir R --cpu-hours H [--calls 768] [--starts 3] [--months M ...]
               [--sizing FILE] [--jobs research2003_replay ...]
    v3-sizing  --snapshot S --out-dir D --v2-job-dir J [--ledger-cache C] [--workers 6]
    v3-analyze --run-dir R --snapshot S --out FILE [--job research2003_replay]
               [--ensemble-out FILE] [--skip-ensemble]
    v3-ensemble --run-dir R --snapshot S [--job research2003_replay] [--analysis FILE]
               [--ensemble-out FILE]
    v3-region  --run-dir R --snapshot S [--job research2003_replay] [--analysis FILE]
               [--out FILE] [--months M ...]
    v3-report  --run-dir R --snapshot S --out FILE [--job research2003_replay]
               [--analysis FILE] [--ensemble FILE] [--allow-partial]

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
from portfoliosight.research.fixedrisk import realized as R
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
    override = None
    if args.cpu_hours_budget is not None or args.allow_changes_in:
        if not args.override_reason:
            raise SystemExit("--cpu-hours-budget/--allow-changes-in need --override-reason")
        override = driver.ResumeOverride(
            args.override_reason, args.cpu_hours_budget, tuple(args.allow_changes_in or ())
        )
    result = driver.run_job(
        Path(args.run_dir),
        args.menu,
        args.engine,
        override=override,
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


def cmd_v3_parent(args: argparse.Namespace) -> int:
    inputs = data.load_inputs(args.snapshot, ledger_cache=Path(args.run_dir) / "ledger_cache")
    sizing = None
    if args.sizing:
        body = json.loads(Path(args.sizing).read_text())
        sizing = {"file": str(args.sizing), "projection": body.get("projection"),
                  "solver_check": body.get("solver_check")}  # fmt: skip
        for item in (sizing["projection"] or {}), (sizing["solver_check"] or {}):
            item.pop("projected_task_seconds", None)
            item.pop("columns", None)
    parent = manifest.build_parent_v3(
        inputs, snapshot_dir=Path(args.snapshot), cpu_hours=args.cpu_hours,
        jobs=tuple(args.jobs or manifest.V3_JOBS), calls=args.calls, starts=args.starts,
        only_months=args.months, sizing=sizing, hooks=args.hooks,
    )  # fmt: skip
    path = manifest.write_parent(Path(args.run_dir), parent)
    print(json.dumps({"parent": str(path), "digest": parent["digest"], "jobs": parent["jobs"]}))
    return 0


def cmd_v3_sizing(args: argparse.Namespace) -> int:
    _require_blas()
    from portfoliosight.research.fixedrisk import sizing3

    body = sizing3.run_sizing(
        snapshot=args.snapshot, out_dir=Path(args.out_dir), v2_job_dir=Path(args.v2_job_dir),
        months=args.months, ledger_cache=args.ledger_cache, workers=args.workers,
        calls=args.calls, starts=args.starts,
    )  # fmt: skip
    print(json.dumps({"out": str(Path(args.out_dir) / "sizing.json"),
                      "projection": {k: v for k, v in body["projection"].items()
                                     if k != "projected_task_seconds"},
                      "solver_check": {k: v for k, v in (body["solver_check"] or {}).items()
                                       if k != "columns"}}, indent=2, default=str))  # fmt: skip
    return 0


def _v3_inputs(args: argparse.Namespace) -> tuple[dict, object, tuple]:
    """The parent manifest, the snapshot's inputs (digest checked) and the realized callables."""
    from portfoliosight.research.fixedrisk import report

    parent = manifest.read_parent(Path(args.run_dir))
    inputs = data.load_inputs(args.snapshot, ledger_cache=Path(args.run_dir) / "ledger_cache")
    if inputs.manifest_sha256 != parent["snapshot"]["manifest_sha256"]:
        raise SystemExit("the snapshot's digest is not the parent manifest's")
    return parent, inputs, report.make_callables(inputs, data)


def _v3_ensemble(
    args: argparse.Namespace, parent: dict, horizon: R.HorizonFn, analysis: Path | None
) -> dict:
    """Run the §7.3 screen after the recorded analysis; write and record its outputs."""
    from portfoliosight.research.fixedrisk import ensemble3

    job_dir = Path(args.run_dir) / args.job
    job = parent["jobs"][args.job]
    if args.ensemble_out:
        out = Path(args.ensemble_out)
    else:
        out = ensemble3.verified_entry(job_dir, "analysis", analysis).parent / "ensemble.json"
    picks = out.with_name(out.stem + "_picks.parquet")
    body = ensemble3.screen_job(
        job_dir, parent, job["menu"], job["engine"], horizon,
        analysis_path=analysis, picks_out=picks,
        progress=lambda line: print(line, file=sys.stderr, flush=True),
    )  # fmt: skip
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=2, default=str) + "\n")
    ensemble3.record_ensemble(job_dir, out)
    return {"out": str(out), "picks": str(picks), "would_pass": len(body["would_pass"]),
            "label": body["label"]}  # fmt: skip


def cmd_v3_analyze(args: argparse.Namespace) -> int:
    from portfoliosight.research.fixedrisk import analysis3, ensemble3

    parent, inputs, callables = _v3_inputs(args)
    job = parent["jobs"][args.job]
    job_dir = Path(args.run_dir) / args.job
    out = analysis3.analyze_job(job_dir, parent, job["menu"], job["engine"], inputs, callables)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str) + "\n")
    ensemble3.record_analysis(job_dir, path)  # before any ensemble code reads an outcome (§7.3)
    summary = {"out": args.out, "label": out["confirmatory"]["label"],
               "verdict": out["confirmatory"]["verdict_text"]}  # fmt: skip
    if not args.skip_ensemble:
        summary["ensemble"] = _v3_ensemble(args, parent, callables[0], path)
    print(json.dumps(summary))
    return 0


def cmd_v3_ensemble(args: argparse.Namespace) -> int:
    parent, _, callables = _v3_inputs(args)
    analysis = Path(args.analysis) if args.analysis else None
    print(json.dumps(_v3_ensemble(args, parent, callables[0], analysis)))
    return 0


def cmd_v3_region(args: argparse.Namespace) -> int:
    """The region check (docs/plans/2026-11-09-fixed-risk-v3-region-check.md); recorded in the
    job's analysis record unless `--months` restricts it."""
    from portfoliosight.research.fixedrisk import region3

    parent, inputs, callables = _v3_inputs(args)
    job = parent["jobs"][args.job]
    job_dir = Path(args.run_dir) / args.job
    out = Path(args.out) if args.out else Path(args.run_dir) / "analysis" / "region_check.json"
    spec = inputs.menu(job["menu"])  # pyright: ignore[reportAttributeAccessIssue]
    body = region3.region_job(
        job_dir, parent, job["menu"], job["engine"], callables[0],
        bounds=(spec.lower, spec.upper),
        analysis_path=Path(args.analysis) if args.analysis else None, months=args.months,
        progress=lambda line: print(line, file=sys.stderr, flush=True),
    )  # fmt: skip
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=2, default=str) + "\n")
    if args.months is None:
        region3.record_region(job_dir, out)
    print(json.dumps({"out": str(out), "label": body["label"], "cells": body["cells"],
                      "recorded": args.months is None}))  # fmt: skip
    return 0


def cmd_v3_report(args: argparse.Namespace) -> int:
    from portfoliosight.research.fixedrisk import report3

    parent = manifest.read_parent(Path(args.run_dir))
    inputs = data.load_inputs(args.snapshot, ledger_cache=Path(args.run_dir) / "ledger_cache")
    if inputs.manifest_sha256 != parent["snapshot"]["manifest_sha256"]:
        raise SystemExit("the snapshot's digest is not the parent manifest's")
    try:
        text = report3.run_report(
            Path(args.run_dir), parent=parent, job=args.job,
            analysis_path=Path(args.analysis) if args.analysis else None,
            ensemble_path=Path(args.ensemble) if args.ensemble else None,
            allow_partial=args.allow_partial,
        )  # fmt: skip
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text)
    print(json.dumps({"out": args.out, "interim": text.startswith("# INTERIM")}))
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
    p.add_argument("--cpu-hours-budget", type=float, help="owner-approved override of the budget")
    p.add_argument(
        "--allow-changes-in", nargs="*", help="owner-approved: paths that may differ from the "
        "parent's commit (a path, or a directory ending in /)",
    )  # fmt: skip
    p.add_argument("--override-reason", help="required with either override; recorded")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status", help="progress of every job of a run")
    p.add_argument("--run-dir", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("v3-parent", help="write the v3 parent manifest")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--cpu-hours", required=True, type=float, help="twice the sizing projection")
    p.add_argument("--calls", type=int, default=768)
    p.add_argument("--starts", type=int, default=C.V3_STARTS)
    p.add_argument("--months", nargs="*", help="restrict the schedule (a smoke run)")
    p.add_argument("--sizing", help="sizing.json whose projection and decision are recorded")
    p.add_argument("--jobs", nargs="*")
    p.add_argument("--hooks")
    p.set_defaults(func=cmd_v3_parent)

    p = sub.add_parser("v3-sizing", help="the v3 sizing run (protocol v3 §8.1)")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--v2-job-dir", required=True, help="fr-run-v2b/research2003_replay")
    p.add_argument("--ledger-cache")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--months", nargs="*")
    p.add_argument("--calls", type=int, default=768)
    p.add_argument("--starts", type=int, default=C.V3_STARTS)
    p.set_defaults(func=cmd_v3_sizing)

    p = sub.add_parser("v3-analyze", help="realized outcomes and the confirmatory test of a job")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--job", default="research2003_replay")
    p.add_argument("--ensemble-out", help="the screen's JSON (default: ensemble.json beside --out)")
    p.add_argument("--skip-ensemble", action="store_true", help="stop after the confirmatory file")
    p.set_defaults(func=cmd_v3_analyze)

    p = sub.add_parser("v3-ensemble", help="the exploratory ensemble screen (protocol v3 §7.3)")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--job", default="research2003_replay")
    p.add_argument("--analysis", help="the recorded analysis file (default: the record's)")
    p.add_argument("--ensemble-out", help="default: ensemble.json beside the analysis file")
    p.set_defaults(func=cmd_v3_ensemble)

    p = sub.add_parser("v3-region", help="the exploratory region check (addendum 2026-11-09)")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--job", default="research2003_replay")
    p.add_argument("--analysis", help="the recorded analysis file (default: the record's)")
    p.add_argument("--out", help="default: <run-dir>/analysis/region_check.json")
    p.add_argument("--months", nargs="*", help="restrict the start months (a smoke run; the "
                   "output is then not recorded)")  # fmt: skip
    p.set_defaults(func=cmd_v3_region)

    p = sub.add_parser("v3-report", help="the v3 Markdown report (protocol v3 §8.4)")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--snapshot", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--job", default="research2003_replay")
    p.add_argument("--analysis", help="the recorded analysis file (default: the record's)")
    p.add_argument("--ensemble", help="the recorded ensemble file (default: the record's)")
    p.add_argument("--allow-partial", action="store_true",
                   help="write a labelled interim report of an incomplete job")  # fmt: skip
    p.set_defaults(func=cmd_v3_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
