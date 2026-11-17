#!/usr/bin/env python3
"""Write QSE's second fetch list from what PortfolioSight wants (spec 2026-11-16 section 4).

    python scripts/export_qse_fetch_list.py [--qse-file PATH] [--core-file PATH]
        [--tiers-file PATH] [--out PATH] [--new-only]

PortfolioSight wants every tier 1 fund, tier 2 fund and requested ticker (`tiers.json`,
`data/universes/requested.txt`) that is not a TSP fund and has no "data ended" note. The output
is QSE's current second list plus every wanted symbol that is not on QSE's core list, sorted,
one per line, no repeats. `--new-only` prints only the symbols `--qse-file` does not hold yet.
QSE's core list, its experiment universe, is read and never written.

Adding a ticker later has four steps, in this order, and no new code:
  1. Add it to `data/universes/requested.txt` (or tier 2) on a PortfolioSight branch, then run
     this script and keep its output.
  2. Open a QSE pull request with that output as QSE's second list, and merge it.
  3. On the laptop, load the new symbols into the lake (spec section 5).
  4. Refresh PortfolioSight's copy `data/universes/qse_portfoliosight.txt` at the merged QSE
     commit, and merge the PortfolioSight branch.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from portfoliosight.data.universe import (  # noqa: E402
    TIERS_FILE,
    Tiers,
    is_tsp,
    load_tiers,
    parse_universe_lines,
)

DEFAULT_QSE_FILE = REPO_ROOT / "data" / "universes" / "qse_portfoliosight.txt"
DEFAULT_CORE_FILE = REPO_ROOT / "data" / "universes" / "qse_core.txt"


def wanted_symbols(tiers: Tiers) -> set[str]:
    """Tier 1, tier 2 and requested symbols that are not TSP and have no note in ``tiers.json``."""
    listed = (*tiers.tier1, *tiers.tier2, *tiers.requested)
    return {s for s in listed if not is_tsp(s) and s not in tiers.notes}


def fetch_list(current: Iterable[str], tiers: Tiers, core: Iterable[str]) -> list[str]:
    """QSE's current list plus every wanted symbol outside its core list, sorted."""
    return sorted(set(current) | (wanted_symbols(tiers) - set(core)))


def _read_list(path: Path) -> list[str]:
    return [symbol for symbol, _ in parse_universe_lines(path.read_text(encoding="utf-8"))]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--qse-file",
        type=Path,
        default=DEFAULT_QSE_FILE,
        help="QSE's current second list (default: the committed copy)",
    )
    parser.add_argument(
        "--core-file",
        type=Path,
        default=DEFAULT_CORE_FILE,
        help="QSE's core list (default: the committed copy)",
    )
    parser.add_argument(
        "--tiers-file",
        type=Path,
        default=TIERS_FILE,
        help="PortfolioSight's tiers.json (default: the committed one)",
    )
    parser.add_argument("--out", type=Path, help="write the list here instead of printing it")
    parser.add_argument(
        "--new-only", action="store_true", help="only the symbols not in --qse-file"
    )
    args = parser.parse_args(argv)

    current = _read_list(args.qse_file)
    listed = fetch_list(current, load_tiers(args.tiers_file), _read_list(args.core_file))
    if args.new_only:
        held = set(current)
        listed = [symbol for symbol in listed if symbol not in held]
    text = "".join(f"{symbol}\n" for symbol in listed)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
