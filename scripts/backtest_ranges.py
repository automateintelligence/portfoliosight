"""The rolling-origin harness over a frozen research snapshot (protocol 4 and 8; plan task 6.1).

Usage, from the repo root:
    .venv/bin/python scripts/backtest_ranges.py ledger --store-dir SNAPSHOT --out FILE
        [--menus tsp,example] [--lookbacks 5y[,1y...]] [--origins monthly|quarter-end|year-end]
    .venv/bin/python scripts/backtest_ranges.py coverage --store-dir SNAPSHOT [--out FILE.json]
        [--menus ...] [--lookbacks ...] [--origins ...]

`--store-dir` is a snapshot written by scripts/freeze_research_inputs.py. It is verified with that
script's `verify_snapshot` before anything is read, every file is hashed again as it is read, and
nothing else (no store, provider, mirror or lake) is opened. The ledger logic lives in
`portfoliosight/research/harness.py`, whose docstring defines every status and column.

`ledger` writes the origins ledger, one row per month and menu, to `--out` (`.parquet` or
`.csv`). `coverage` prints the protocol 4 evidence gate (mature common training-eligible
origins, complete outcomes and disjoint intervals per menu, unexplained missingness, and the
120-origin panel ceiling) and writes it as JSON to `--out` when given. Both print the boundary:
the first month, the fund whose first price sets it, and the reason earlier months are not in
the ledger (`prehistory_full_fixed_menu_unavailable`). `--menus` names the
snapshot menus that together form the fixed menu (default: all of them, the protocol's ledger);
`--lookbacks` takes production lookback ids (`5y` is the protocol's); `--origins quarter-end` and
`year-end` are the spec 10 subsets of the monthly ledger (2015-12 through 2025-09, and 2024-12),
on which the gates do not apply.

The return-optimization experiment (protocol 4-9; plan task 6b.5):
    .venv/bin/python scripts/backtest_ranges.py experiment estimate --snapshot SNAPSHOT
        [--out ROOT] [--workers 0|1|2] [--estimate-id ID]
    .venv/bin/python scripts/backtest_ranges.py experiment run --snapshot SNAPSHOT [--out ROOT]
        [--stage 1|2] [--sensitivity coefficients|lookback|budget] [--run-id ID]
        [--workers 0|1|2] [--cpu-hours-ceiling HOURS]
    .venv/bin/python scripts/backtest_ranges.py experiment report --run RUN_DIR
        [--allow-incomplete]

`run` without `--sensitivity` runs Stage 1 into `ROOT/<protocol sha256 prefix16>/<run id>/`;
`--sensitivity NAME` and `--stage 2` name that Stage 1 run with `--run-id` and write beneath it.
`estimate` searches a fixed sample of real cells with full budgets and prints the projected CPU
hours of Stage 1 plus the sensitivities against the 24-hour ceiling; it is not a run. `--out`
defaults to this checkout's git-ignored `.omx/research/return-optimization/`. Every protocol value
is fixed; `--cpu-hours-ceiling` alone changes a ceiling and is recorded as an amendment. The
logic and the artifact schemas live in `portfoliosight/research/experiment.py`,
`portfoliosight/research/selection.py` and `portfoliosight/research/outcomes.py`. This script
holds BLAS to one thread (`OPENBLAS/OMP/MKL_NUM_THREADS`, unless already set; a value other than
1 is refused). `report` reads a Stage 1 run directory and its three sensitivity directories,
verifies every artifact digest the manifests list, and writes `summary.json` (whose
`stage_2.run` gates `run --stage 2`) and `report.md` into that run directory
(`portfoliosight/research/report.py`, statistics in `portfoliosight/research/evidence.py`); an
incomplete run is refused unless `--allow-incomplete`, which labels it inconclusive/invalid.

Exit codes: 0 done (a gate that is not met is a result, not an error), 2 a bad argument or an
output path inside the snapshot, the mirror it was copied from or the repository (unless
git-ignored), 6 a snapshot that fails verification or changes while it is read, or a run
artifact whose digest no longer matches its manifest, 7 an experiment refused before it starts
(a dirty repository, BLAS threads, the TSP investigation digest, more than 120 scheduled origins,
a Stage 1 run that is missing, incomplete or does not authorize Stage 2) or a report refused for
an incomplete run, 8 an experiment stopped at a resource ceiling (its partial artifacts are
kept).
"""

from __future__ import annotations

import os

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_name, "1")  # before NumPy is loaded (protocol 5: one BLAS thread)

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from dataclasses import asdict  # noqa: E402
from datetime import date  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout's package
sys.path.insert(0, str(Path(__file__).resolve().parent))  # the freeze script beside this one

from freeze_research_inputs import (  # noqa: E402
    FreezeError,
    dirty_paths,
    repo_blob,
    repo_head,
    verify_snapshot,
)

from portfoliosight.engine.windows import LOOKBACK_ROWS  # noqa: E402
from portfoliosight.research import experiment, harness  # noqa: E402
from portfoliosight.research import report as run_report  # noqa: E402

LEDGER_SUFFIXES = (".parquet", ".csv")
REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / ".omx" / "research" / "return-optimization"


def _names(text: str) -> list[str]:
    names = [name.strip() for name in text.split(",")]
    if not all(names) or len(set(names)) != len(names):
        raise argparse.ArgumentTypeError(f"{text!r} is not a comma-separated list of names")
    return names


def _lookbacks(text: str) -> list[str]:
    names = _names(text)
    unknown = [name for name in names if name not in LOOKBACK_ROWS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown lookback(s) {', '.join(unknown)}; expected {', '.join(LOOKBACK_ROWS)}"
        )
    return names


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Origins ledger and evidence gate of a snapshot.")
    commands = parser.add_subparsers(dest="command", required=True)
    trial = commands.add_parser("experiment", help="the return-optimization experiment")
    actions = trial.add_subparsers(dest="action", required=True)
    for name, text in (
        ("estimate", "project the CPU cost from a sample of real cells (not a run)"),
        ("run", "run Stage 1, a sensitivity or Stage 2"),
    ):
        action = actions.add_parser(name, help=text)
        action.add_argument("--snapshot", type=Path, required=True, help="frozen research snapshot")
        action.add_argument("--out", type=Path, default=DEFAULT_OUT, help="artifact root")
        action.add_argument("--workers", type=int, choices=(0, 1, 2), default=2)
        action.add_argument(
            "--cpu-hours-ceiling", type=float, help="an amended CPU-hour ceiling (recorded)"
        )
        if name == "run":
            action.add_argument("--stage", type=int, choices=(1, 2), default=1)
            action.add_argument("--sensitivity", choices=experiment.SENSITIVITIES)
            action.add_argument("--run-id", help="the Stage 1 run id (needed beneath one)")
        else:
            action.add_argument("--estimate-id")
    action = actions.add_parser("report", help="write summary.json and report.md of a run")
    action.add_argument("--run", type=Path, required=True, help="the Stage 1 run directory")
    action.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="report an incomplete run (labeled inconclusive/invalid)",
    )
    for name, text in (
        ("ledger", "write the origins ledger"),
        ("coverage", "print the protocol 4 evidence gate"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument(
            "--store-dir", type=Path, required=True, help="frozen research snapshot (verified)"
        )
        command.add_argument("--menus", type=_names, help="snapshot menus (default: all)")
        command.add_argument("--lookbacks", type=_lookbacks, default=["5y"], help="e.g. 5y,1y")
        command.add_argument("--origins", choices=harness.ORIGIN_KINDS, default="monthly")
        command.add_argument(
            "--out",
            type=Path,
            required=name == "ledger",
            help=".parquet or .csv" if name == "ledger" else "JSON report",
        )
    return parser


def _boundary_line(month: str, fund: str, first: date) -> str:
    return (
        f"first month {month}: {fund} first priced {first.isoformat()}; "
        f"earlier months are {harness.PREHISTORY}"
    )


def _verdict(met: bool | None) -> str:
    return {True: "met", False: "NOT met", None: "n/a, defined on the monthly ledger"}[met]


def coverage_lines(snapshot: str, report: harness.Coverage) -> list[str]:
    gate = report.gate
    counts = ", ".join(f"{status} {count}" for status, count in report.counts.items())
    lines = [
        f"{snapshot}: lookback {report.lookback}, {report.origins} origins, fixed menu "
        f"{'+'.join(report.fixed_menu)}, D* {report.d_star.isoformat()}",
        _boundary_line(report.boundary_month, report.boundary_fund, report.boundary_date),
        f"months: {report.months} ({counts})",
    ]
    for label, name in (
        ("scheduled common training-eligible origins", "scheduled_origins"),
        ("mature common training-eligible origins", "mature_origins"),
    ):
        lines.append(f"{label}: {gate(name).value} ({gate(name).rule}: {_verdict(gate(name).met)})")
    for menu in report.menus:
        share = gate(f"{menu.menu}_completeness")
        percent = "n/a" if share.value is None else f"{100 * share.value:.1f}%"
        unexplained = gate(f"{menu.menu}_unexplained_missing")
        disjoint = gate(f"{menu.menu}_disjoint_intervals")
        lines += [
            f"{menu.menu} complete outcomes: {menu.complete} of {report.mature} = {percent} "
            f"({share.rule}: {_verdict(share.met)})",
            f"{menu.menu} unexplained missing outcomes: {menu.unexplained} "
            f"({unexplained.rule}: {_verdict(unexplained.met)})",
            f"{menu.menu} disjoint intervals: {menu.disjoint} "
            f"({disjoint.rule}: {_verdict(disjoint.met)})",
        ]
    lines.append(f"evidence gate: {_verdict(report.met)}")
    return lines


def _inside(path: Path, bases: list[str | Path]) -> Path | None:
    target = path.expanduser().resolve()
    for base in bases:
        if not str(base):
            continue
        root = Path(base).resolve()
        if target == root or root in target.parents:
            return root
    return None


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, timeout=30)


def _ignored(path: Path) -> bool:
    """Whether git ignores ``path`` in the worktree that holds it."""
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            done = subprocess.run(
                ["git", "-C", str(parent), "check-ignore", "-q", "--no-index", str(path)],
                capture_output=True,
                timeout=30,
            )
            return done.returncode == 0
    return False


def _provenance() -> experiment.Provenance:
    """HEAD, its cleanliness, the protocol at HEAD and the repository's locations."""
    head = repo_head(REPO)
    protocol = repo_blob(REPO, head, experiment.PROTOCOL_PATH)
    status = next((line for line in protocol.decode("utf-8").splitlines() if "Status:" in line), "")
    common = Path(
        _git("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.decode().strip()
    )
    worktrees = [
        Path(line.removeprefix(b"worktree ").decode())
        for line in _git("worktree", "list", "--porcelain").stdout.splitlines()
        if line.startswith(b"worktree ")
    ]
    return experiment.Provenance(
        head=head,
        dirty=tuple(dirty_paths(REPO)),
        protocol_sha256=hashlib.sha256(protocol).hexdigest(),
        protocol_status=status,
        worktrees=tuple(path.resolve() for path in worktrees),
        git_dirs=(common.resolve(),),
        ignored=_ignored,
    )


def _settings() -> experiment.Settings:
    """The protocol's settings; the CLI exposes none of them."""
    return experiment.Settings()


def _report(args: argparse.Namespace) -> int:
    try:
        written = run_report.write_report(args.run, allow_incomplete=args.allow_incomplete)
    except run_report.ArtifactChanged as exc:
        print(str(exc), file=sys.stderr)
        return 6
    except run_report.ReportRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 7
    summary = written.summary
    labels = summary["labels"]
    print(f"{written.directory}: summary.json and report.md written")
    print(f"experiment: {labels['experiment']}")
    for menu, label in labels["menus"].items():
        print(f"{menu}: {label['conditional']}; {label['realized']}")
    stage_2 = summary["stage_2"]
    print(f"stage 2: {'run' if stage_2['run'] else 'skip'}: {stage_2['reason']}")
    return 0


def _experiment(args: argparse.Namespace) -> int:
    if args.action == "report":
        return _report(args)
    try:
        inputs = experiment.read_inputs(args.snapshot, verify_snapshot)
    except (FreezeError, harness.SnapshotChanged) as exc:
        print(str(exc), file=sys.stderr)
        return 6
    amended = args.cpu_hours_ceiling is not None
    limits = experiment.Limits(
        workers=args.workers,
        cpu_hours=args.cpu_hours_ceiling if amended else experiment.CPU_HOURS,
        cpu_amended=amended,
    )
    try:
        if args.action == "estimate":
            projection = experiment.estimate(
                inputs, _provenance(), args.out, settings=_settings(), limits=limits,
                estimate_id=args.estimate_id,
            )  # fmt: skip
            print("\n".join(_projection_lines(projection)))
            return 0
        result = experiment.run(
            inputs, _provenance(), args.out, settings=_settings(), limits=limits,
            stage=args.stage, sensitivity=args.sensitivity, run_id=args.run_id,
        )  # fmt: skip
    except experiment.UnsafeOutput as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except experiment.Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 7
    outcome = result.outcome
    print(f"{result.directory}: {result.status}")
    print(
        f"cells {result.cells}: completed {outcome.get('completed')}, "
        f"failed {outcome.get('failed')}, incomplete {outcome.get('incomplete')}, "
        f"failure rate {outcome.get('failure_rate', 0):.4f}"
    )
    if result.breach is not None:
        breach = result.breach
        print(f"stopped at a ceiling: {breach.rule} {breach.value} > {breach.limit}")
        return 8
    return 0


def _projection_lines(projection: experiment.Projection) -> list[str]:
    lines = [
        f"estimate in {projection.directory} (not a run)",
        f"scheduled origins {projection.scheduled_origins}; sample cells {projection.sample_cells}",
    ]
    for menu, cells in projection.stage_1_cells.items():
        per = projection.search_cpu_per_cell[menu]
        lines.append(f"{menu}: {cells} Stage 1 cells at {per:.2f} CPU s per cell searched")
    lines.append(f"evaluation: {projection.evaluation_cpu_per_mix:.4f} CPU s per locked mix")
    for part, seconds in projection.parts.items():
        lines.append(f"  {part}: {seconds / 3600:.2f} CPU h")
    verdict = "within" if projection.fits else "OVER"
    lines.append(
        f"projected {projection.total_cpu_hours:.2f} CPU h, {verdict} the "
        f"{projection.cpu_hours_ceiling:g} CPU h ceiling; "
        f"longest arm {projection.max_arm_seconds:.1f} s"
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "experiment":
        return _experiment(args)
    out: Path | None = args.out
    if args.command == "ledger" and out is not None and out.suffix not in LEDGER_SUFFIXES:
        parser.error(f"--out must end in {' or '.join(LEDGER_SUFFIXES)}")
    if args.command == "coverage" and out is not None and out.suffix != ".json":
        parser.error("--out must end in .json")
    try:
        inputs = harness.read_snapshot(args.store_dir, verify_snapshot)
    except (FreezeError, harness.SnapshotChanged) as exc:
        print(str(exc), file=sys.stderr)
        return 6
    menus = args.menus or list(inputs.menus)
    unknown = [name for name in menus if name not in inputs.menus]
    if unknown:
        parser.error(
            f"unknown menu(s) {', '.join(unknown)}; the snapshot has {', '.join(inputs.menus)}"
        )
    if out is not None:
        refused = _inside(out, [inputs.root, inputs.source_root])
        if refused is not None:
            print(f"refusing to write {out}: it is inside {refused}", file=sys.stderr)
            return 2

    fixed = {name: inputs.menus[name] for name in menus}
    ledgers = [
        harness.validation_origins(
            harness.build_ledger(inputs.records, inputs.sessions, inputs.d_star, fixed, lookback),
            args.origins,
        )
        for lookback in args.lookbacks
    ]
    if args.command == "ledger":
        if out is None:  # argparse requires it; this narrows the type
            parser.error("ledger needs --out")
        frame = pd.concat([harness.ledger_frame(ledger) for ledger in ledgers], ignore_index=True)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix == ".parquet":
            frame.to_parquet(out, index=False)
        else:
            frame.to_csv(out, index=False)
        boundary = ledgers[0]  # the boundary depends on the fixed menu, not on the lookback
        print(
            _boundary_line(boundary.boundary_month, boundary.boundary_fund, boundary.boundary_date)
        )
        print(f"{len(frame)} rows written to {out}")
        return 0

    reports = [harness.coverage(ledger) for ledger in ledgers]
    for report in reports:
        print("\n".join(coverage_lines(inputs.root.name, report)))
    if out is not None:
        body = [
            {"snapshot": inputs.root.name, "manifest_sha256": inputs.manifest_sha256}
            | asdict(report)
            for report in reports
        ]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
