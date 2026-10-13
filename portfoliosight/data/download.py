"""The downloader (spec 5.4): measure the provider limits, catch up, refresh.

    python -m portfoliosight.data.download --mode measure-limits|catch-up|refresh
        [--symbols VTI,VBIAX] [--tiers 1,2,3]

Catch-up fetches every symbol of the configured set that has no record (history, then meta) and
the tail of every seeded symbol not yet refreshed. Refresh fetches the tail of every symbol that
is not current at ``D_G``, whatever its status. Both walk the priority order, write each record
as they go, and rewrite the catalog after each tier and at the end.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.budget import BudgetLedger, BudgetSpent
from portfoliosight.data.calendar import generation_date
from portfoliosight.data.limits import load_limits, measure_limits, plan_tier
from portfoliosight.data.manifest import Manifest, ManifestEntry
from portfoliosight.data.providers.base import ProviderError, RateLimited, SymbolMeta
from portfoliosight.data.refresh import is_current, plan_refresh, tail_start
from portfoliosight.data.returns import provider_rows_to_record, splice_tail
from portfoliosight.data.secrets import install_redaction
from portfoliosight.data.universe import SymbolInfo, is_tsp, load_tiers, priority_order

__all__ = ["MODES", "main", "plan_refresh", "run"]

logger = logging.getLogger(__name__)
install_redaction([logger.name])

MODES = ("measure-limits", "catch-up", "refresh")
FULL_HISTORY_START = date(1970, 1, 1)
DEFAULT_PROBE_SYMBOL = "VTI"
BUDGETED_PROVIDER = "tiingo"
TSP_PROVIDER = "tsp"
DEFAULT_TIER = 3

Clock = Callable[[], datetime]
Sleep = Callable[[float], None]


def run(
    mode: str,
    *,
    store: store_mod.Store,
    providers: Mapping[str, Any],
    clock: Clock,
    sleep: Sleep,
    symbols: Iterable[str] | None = None,
    tiers: Iterable[int] | None = None,
) -> int:
    """One downloader run; returns the exit code (0 also when a budget stopped it cleanly).

    ``providers`` maps ``"tiingo"`` (every id not starting with ``TSP-``) and ``"tsp"`` to
    provider objects. ``clock()`` is the only source of time and ``sleep(seconds)`` the only
    wait. ``symbols``, when given, is the configured set in priority order; each symbol's name,
    kind and tier then come from its manifest entry and no universe file is read. Without it the
    set is the universe's priority order, optionally limited to ``tiers``.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
    info: dict[str, SymbolInfo] = {}
    if symbols is None and mode != "measure-limits":
        universe = load_tiers()
        only = tuple(tiers) if tiers is not None else (1, 2, 3)
        order = priority_order(plan_tier(store), universe, only_tiers=only)
        info = universe.info()
    else:
        order = list(symbols or [])
    return _execute(
        mode, store=store, providers=providers, clock=clock, sleep=sleep, order=order, info=info
    )


def _execute(
    mode: str,
    *,
    store: store_mod.Store,
    providers: Mapping[str, Any],
    clock: Clock,
    sleep: Sleep,
    order: list[str],
    info: Mapping[str, SymbolInfo],
) -> int:
    ledger = BudgetLedger(store, clock, sleep, load_limits(store))
    budgeted: Any = providers.get(BUDGETED_PROVIDER)
    # A provider with a ``before_request`` hook accounts every HTTP attempt itself (retries
    # included); for any other provider the run accounts one request per call.
    hooked = budgeted is not None and hasattr(budgeted, "before_request")
    saved_hook = getattr(budgeted, "before_request", None)
    saved_retry = getattr(budgeted, "retry_on_429", None)
    if budgeted is not None and hooked:
        budgeted.before_request = ledger.before_request
    try:
        if mode == "measure-limits":
            if budgeted is None:
                logger.error("measure-limits needs the %s provider", BUDGETED_PROVIDER)
                return 2
            if saved_retry is not None:
                budgeted.retry_on_429 = False  # the probe must see the first 429
            measured = measure_limits(
                store=store,
                ledger=ledger,
                provider=budgeted,
                clock=clock,
                sleep=sleep,
                symbol=order[0] if order else DEFAULT_PROBE_SYMBOL,
                account=not hooked,
            )
            return 0 if measured is not None else 1
        ingest = _Ingest(
            mode=mode,
            store=store,
            providers=providers,
            clock=clock,
            ledger=ledger,
            info=info,
            account=not hooked,
        )
        return ingest.walk(order)
    finally:
        if budgeted is not None and hooked:
            budgeted.before_request = saved_hook
        if budgeted is not None and saved_retry is not None:
            budgeted.retry_on_429 = saved_retry


@dataclass
class _Ingest:
    mode: str
    store: store_mod.Store
    providers: Mapping[str, Any]
    clock: Clock
    ledger: BudgetLedger
    info: Mapping[str, SymbolInfo]
    account: bool
    manifest: Manifest = field(init=False)
    d_g: date = field(init=False)
    retry_unavailable: bool = field(init=False)
    errors: int = 0

    def __post_init__(self) -> None:
        now = self.clock().astimezone(UTC)
        self.manifest = manifest_mod.load_manifest(self.store)
        self.d_g = generation_date(now)
        # Unavailable symbols are asked for again on the first run date of each month.
        self.retry_unavailable = now.day == 1

    # -- the walk -------------------------------------------------------------------------

    def walk(self, order: list[str]) -> int:
        month_spent_logged = False
        group: tuple[int, bool] | None = None
        try:
            for symbol in order:
                this_group = self._group(symbol)
                if group is not None and this_group != group:
                    self._write_catalog()
                group = this_group
                try:
                    self._visit(symbol)
                except BudgetSpent as spent:
                    if spent.scope == "month":
                        if not month_spent_logged:
                            logger.info(
                                "monthly budget spent: symbols not yet fetched this month wait"
                            )
                            month_spent_logged = True
                        continue
                    logger.info("daily budget spent: stopping at %s, resuming next run", symbol)
                    break
                except RateLimited:
                    logger.warning("provider rate limit persists: stopping at %s", symbol)
                    break
                except (ProviderError, ValueError) as exc:
                    self.errors += 1
                    logger.error("%s: %s: %s", symbol, type(exc).__name__, exc)
        finally:
            self._write_catalog()
        return 1 if self.errors else 0

    def _group(self, symbol: str) -> tuple[int, bool]:
        """Tier, and within tier 2 the income flag: the catalog is rewritten after each group."""
        tier, income = self._tier_income(symbol)
        return (tier, income if tier == 2 else False)

    def _tier_income(self, symbol: str) -> tuple[int, bool]:
        entry = self.manifest.symbols.get(symbol)
        known = self.info.get(symbol)
        if known is not None:
            return known.tier, known.income
        if entry is not None:
            return entry.tier, entry.income
        return (1 if is_tsp(symbol) else DEFAULT_TIER), False

    def _write_catalog(self) -> None:
        manifest_mod.restatus(self.manifest, self.d_g)
        manifest_mod.write_catalog(self.store, self.manifest, self.clock().astimezone(UTC))

    # -- one symbol -----------------------------------------------------------------------

    def _provider(self, symbol: str) -> tuple[str, Any]:
        name = TSP_PROVIDER if is_tsp(symbol) else BUDGETED_PROVIDER
        provider = self.providers.get(name)
        if provider is None:
            raise ProviderError(f"no {name!r} provider was given for {symbol}")
        return name, provider

    def _fetch_daily(self, symbol: str, start: date) -> pd.DataFrame:
        name, provider = self._provider(symbol)
        if name == BUDGETED_PROVIDER and self.account:
            self.ledger.before_request(symbol)
        return provider.fetch_daily(symbol, start, None)

    def _fetch_meta(self, symbol: str) -> SymbolMeta | None:
        name, provider = self._provider(symbol)
        if name == BUDGETED_PROVIDER and self.account:
            self.ledger.before_request(symbol)
        return provider.fetch_meta(symbol)

    def _visit(self, symbol: str) -> None:
        entry = self.manifest.symbols.get(symbol)
        if entry is not None and entry.status == "unavailable" and not self.retry_unavailable:
            return
        has_record = (
            entry is not None and entry.adjusted_through is not None and entry.last_date is not None
        )
        if entry is None or not has_record:
            self._full(symbol, entry)
            return
        if self.mode == "catch-up" and entry.source != "seed":
            return
        if self.mode == "refresh" and is_current(entry, self.d_g):
            return
        self._tail(symbol, entry)

    def _full(self, symbol: str, entry: ManifestEntry | None) -> None:
        """A symbol without a record: the full history, then its meta (two requests)."""
        provider_name, _ = self._provider(symbol)
        frame = self._fetch_daily(symbol, FULL_HISTORY_START)
        tier, income = self._tier_income(symbol)
        if entry is None:
            entry = ManifestEntry(
                name=symbol,
                kind=self._kind(symbol, None, None),
                tier=tier,
                income=income,
                source=provider_name,
                status="unavailable",
            )
            self.manifest.symbols[symbol] = entry
        entry.fetched_at = self.clock().astimezone(UTC).isoformat()
        if frame.empty:
            entry.status = "unavailable"
            entry.reason = manifest_mod.REASON_NO_DATA
            logger.info("%s: no data from %s", symbol, provider_name)
            return
        record = provider_rows_to_record(frame)
        store_mod.put_record(self.store, symbol, record)
        entry.source = provider_name
        entry.first_date = _day(record["date"].iloc[0])
        entry.last_date = entry.adjusted_through = _day(record["date"].iloc[-1])
        self._settle(symbol, entry)

    def _tail(self, symbol: str, entry: ManifestEntry) -> None:
        """A symbol with a record: its tail from ``adjusted_through - 7 days`` (one request)."""
        anchor = entry.adjusted_through
        try:
            if anchor is None:
                raise KeyError(symbol)
            record = store_mod.get_record(self.store, symbol)
        except KeyError:
            logger.warning("%s: the manifest lists a record the store lacks; refetching", symbol)
            entry.last_date = entry.adjusted_through = None
            self._full(symbol, entry)
            return
        provider_name, _ = self._provider(symbol)
        frame = self._fetch_daily(symbol, tail_start(anchor))
        entry.fetched_at = self.clock().astimezone(UTC).isoformat()
        if frame.empty:
            entry.status = "unavailable"
            entry.reason = manifest_mod.reason_for(
                entry, "unavailable", self.d_g, self._note(symbol)
            )
            logger.info("%s: no data from %s", symbol, provider_name)
            return
        spliced, adjusted_through = splice_tail(record, frame, anchor)
        if adjusted_through != anchor:
            store_mod.put_record(self.store, symbol, spliced)
            entry.last_date = entry.adjusted_through = adjusted_through
        if entry.source == "seed":
            entry.source = f"seed+{provider_name}"
        self._settle(symbol, entry)

    def _settle(self, symbol: str, entry: ManifestEntry) -> None:
        """Status against ``D_G``; and the name and kind, once, for an entry that has none."""
        entry.status = manifest_mod.status_for(entry, self.d_g)
        entry.reason = manifest_mod.reason_for(entry, entry.status, self.d_g, self._note(symbol))
        if entry.name and entry.name != symbol:
            return
        meta = self._fetch_meta(symbol)
        if meta is not None:
            entry.name = meta.name or symbol
            entry.kind = self._kind(symbol, meta, entry)
            if meta.first_date is not None and entry.first_date is None:
                entry.first_date = meta.first_date

    def _note(self, symbol: str) -> str | None:
        known = self.info.get(symbol)
        return known.note if known is not None else None

    def _kind(self, symbol: str, meta: SymbolMeta | None, entry: ManifestEntry | None) -> str:
        known = self.info.get(symbol)
        if known is not None and known.kind is not None:
            return known.kind
        if is_tsp(symbol):
            return "tsp"
        if entry is not None and entry.source.startswith("seed") and entry.kind:
            return entry.kind
        if meta is not None:
            return meta.kind
        return entry.kind if entry is not None else "etf"


def _day(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    """The CLI: the store and the real providers come from the environment."""
    from portfoliosight.data.providers.tiingo import TiingoProvider
    from portfoliosight.data.providers.tsp import TspProvider

    parser = argparse.ArgumentParser(prog="python -m portfoliosight.data.download")
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--symbols", help="comma-separated ids, in priority order")
    parser.add_argument("--tiers", help="comma-separated tiers of the universe, e.g. 1,2")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        store = store_mod.store_from_env()
        providers = {BUDGETED_PROVIDER: TiingoProvider(), TSP_PROVIDER: TspProvider()}
    except (store_mod.StoreConfigError, ProviderError) as exc:
        print(f"download not run: {exc}", file=sys.stderr)
        return 2

    symbols = [symbol.upper() for symbol in _split(args.symbols)]
    tiers = tuple(int(tier) for tier in _split(args.tiers)) or (1, 2, 3)
    if args.mode == "measure-limits":
        order, info = symbols[:1], {}
    else:
        universe = load_tiers()
        info = universe.info()
        order = symbols or priority_order(plan_tier(store), universe, only_tiers=tiers)
    return _execute(
        args.mode,
        store=store,
        providers=providers,
        clock=lambda: datetime.now(UTC),
        sleep=time.sleep,
        order=order,
        info=info,
    )


if __name__ == "__main__":
    from portfoliosight.data.secrets import load_env

    load_env()
    raise SystemExit(main())
