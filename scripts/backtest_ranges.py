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

Exit codes: 0 done (a gate that is not met is a result, not an error), 2 a bad argument or an
output path inside the snapshot or the mirror it was copied from, 6 a snapshot that fails
verification or changes while it is read.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout's package
sys.path.insert(0, str(Path(__file__).resolve().parent))  # the freeze script beside this one

from freeze_research_inputs import FreezeError, verify_snapshot  # noqa: E402

from portfoliosight.engine.windows import LOOKBACK_ROWS  # noqa: E402
from portfoliosight.research import harness  # noqa: E402

LEDGER_SUFFIXES = (".parquet", ".csv")


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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
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
