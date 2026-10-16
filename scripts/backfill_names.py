#!/usr/bin/env python3
"""Name every catalog entry that has no name, once (spec 5.4).

    python scripts/backfill_names.py [--lake PATH] [--dry-run] [--lake-only]

Entries the lake sync keeps (``source: lake``) are named by the sync and left alone here. Every
other entry whose name is missing or only its ticker gets, in this order: the lake's name for it
(``General.Name`` of its EODHD fundamentals file, else EODHD's US symbol list; the lake is only
read); else, for a served entry the provider keeps (TSP aside) that the provider already fetched
this month, Tiingo's meta ``name``: one request each, accounted in the budget ledger
``meta/budget.json`` before it is made, so the run waits for the next UTC hour when the hour's
budget is spent and stops when the day's is (a rerun resumes, since named entries are not asked
again). A symbol not yet fetched this month is left to the nightly, which asks for a missing name
when it refreshes the symbol. Else the ticker stays.

Names are written to ``meta/manifest.json`` by a conditional read-modify-write that names only
entries still without one, then ``meta/symbols.json``: once after the lake's names and after
every ``BATCH`` names from Tiingo, so an interrupted run keeps what it found. The keys come from
``~/.secrets/portfoliosight.env`` and are never printed.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from portfoliosight.data import lake as lake_mod  # noqa: E402
from portfoliosight.data import manifest as manifest_mod  # noqa: E402
from portfoliosight.data import store as store_mod  # noqa: E402
from portfoliosight.data.budget import BudgetLedger, BudgetSpent  # noqa: E402
from portfoliosight.data.limits import load_limits  # noqa: E402
from portfoliosight.data.manifest import Manifest  # noqa: E402
from portfoliosight.data.providers.base import ProviderError, RateLimited  # noqa: E402
from portfoliosight.data.secrets import RedactingFilter, install_redaction  # noqa: E402
from portfoliosight.data.universe import is_tsp  # noqa: E402

BATCH = 10

logger = logging.getLogger("backfill_names")
install_redaction([logger.name])
Emit = Callable[[str], None]
Clock = Callable[[], datetime]


def write_names(store: store_mod.Store, names: Mapping[str, str], now: datetime) -> list[str]:
    """Name the stored entries (not the lake's) that still have none; returns those named."""
    named: list[str] = []

    def change(document: Any) -> dict[str, Any]:
        manifest = Manifest.model_validate(document or {})
        mine = {
            symbol: name
            for symbol, name in names.items()
            if (entry := manifest.symbols.get(symbol)) is not None
            and entry.source != lake_mod.LAKE_SOURCE
        }
        named[:] = manifest_mod.fill_names(manifest, mine)
        return manifest.to_json()

    written = Manifest.model_validate(
        store_mod.update_json(store, manifest_mod.MANIFEST_KEY, change)
    )
    store_mod.put_json(
        store, manifest_mod.SYMBOLS_KEY, manifest_mod.symbols_view(written, now.astimezone(UTC))
    )
    return named


def backfill(
    *,
    store: store_mod.Store,
    lake: Path | None,
    provider: Any | None,
    clock: Clock,
    sleep: Callable[[float], None],
    dry_run: bool = False,
    emit: Emit = logger.info,
) -> int:
    """One backfill; returns the exit code (0 also when a budget stopped it cleanly)."""
    manifest = manifest_mod.load_manifest(store)
    todo = sorted(
        symbol
        for symbol, entry in manifest.symbols.items()
        if entry.source != lake_mod.LAKE_SOURCE and manifest_mod.unnamed(symbol, entry.name)
    )
    emit(f"{len(todo)} entries the lake sync does not keep have no name")
    names = lake_mod.LakeNames(lake) if lake is not None and lake.is_dir() else None
    from_lake: dict[str, str] = {}
    if names is not None:
        from_lake = {symbol: name for symbol in todo if (name := names.name(symbol)) is not None}
    emit(f"the lake names {len(from_lake)}")
    if from_lake and not dry_run:
        written = write_names(store, from_lake, clock())
        emit(f"wrote {len(written)} names from the lake")

    asked = [
        symbol
        for symbol in todo
        if symbol not in from_lake
        and manifest.symbols[symbol].status == "ok"
        and not is_tsp(symbol)
    ]
    if provider is None or not asked:
        emit(f"{len(asked)} served entries left for Tiingo; none asked")
        return 0
    ledger = BudgetLedger(store, clock, sleep, load_limits(store))
    fetched = set(ledger.months.get(clock().astimezone(UTC).strftime("%Y-%m"), []))
    now_asked = [symbol for symbol in asked if symbol in fetched]
    emit(
        f"{len(asked)} served entries left for Tiingo: {len(now_asked)} asked now, "
        f"{len(asked) - len(now_asked)} not fetched this month are left to the nightly"
    )
    if dry_run or not now_asked:
        emit("dry run: nothing written" if dry_run else "nothing to ask")
        return 0
    saved_hook = getattr(provider, "before_request", None)
    provider.before_request = ledger.before_request
    pending: dict[str, str] = {}
    code = 0
    try:
        for number, symbol in enumerate(now_asked, start=1):
            try:
                meta = provider.fetch_meta(symbol)
            except BudgetSpent as spent:
                emit(f"{spent.scope} budget spent at {symbol}: stopping; a rerun resumes")
                break
            except RateLimited:
                emit(f"Tiingo rate limit at {symbol}: stopping; a rerun resumes")
                break
            except store_mod.ConcurrentUpdate:
                emit(f"the budget ledger kept changing at {symbol}: stopping; a rerun resumes")
                break
            except ProviderError as exc:
                code = 1
                emit(f"{symbol}: {RedactingFilter().redact(str(exc))[:300]}")
                continue
            name = lake_mod.clean_name(meta.name) if meta is not None else None
            if name is not None and not manifest_mod.unnamed(symbol, name):
                pending[symbol] = name
            emit(f"asked {number}/{len(now_asked)}: {symbol} -> {name or 'no name'}")
            if len(pending) >= BATCH:
                write_names(store, pending, clock())
                pending = {}
    finally:
        provider.before_request = saved_hook
        if pending:
            write_names(store, pending, clock())
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Name the catalog entries that have no name.")
    parser.add_argument("--lake", default=lake_mod.DEFAULT_LAKE, help="the datalake_us_core dir")
    parser.add_argument("--dry-run", action="store_true", help="count, write nothing, ask nothing")
    parser.add_argument("--lake-only", action="store_true", help="make no Tiingo request")
    args = parser.parse_args(argv)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    try:
        store = store_mod.store_from_env()
        provider = None
        if not args.lake_only:
            from portfoliosight.data.providers.tiingo import TiingoProvider

            provider = TiingoProvider()
    except (store_mod.StoreConfigError, ProviderError) as exc:
        logger.error("backfill not run: %s", exc)
        return 2
    return backfill(
        store=store,
        lake=Path(args.lake).expanduser(),
        provider=provider,
        clock=lambda: datetime.now(UTC),
        sleep=time.sleep,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    from portfoliosight.data.secrets import load_env

    load_env()
    raise SystemExit(main())
