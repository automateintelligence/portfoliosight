#!/usr/bin/env python3
"""Keep the lake's current symbols served from the owner's QSE lake, once per lake run (spec 5.4).

    python scripts/sync_lake.py [--lake PATH] [--dry-run] [--force] [--lock PATH]

A laptop job (cron, weekdays every 10 minutes from 07:00 to 09:50 PT). It reads the lake only.
QSE's price stitch (weekdays 06:45 PT) rewrites every price file and then, last, rewrites
``_adjusted_through.json`` with a fresh ``generated_at``; a lake run is complete for today once
that timestamp is at or after today 06:45 America/Los_Angeles. Until then the job waits (exit 0);
from 09:50 PT it logs an ``ALERT`` line and exits 1, and uploads nothing. On Saturday and Sunday
there is no stitch and it exits 0 at once. ``--force`` syncs the lake run there is, whatever the
time, day or what was synced before.

For every symbol of tiers 1 to 3 (TSP aside) that the lake holds, the sync takes it when the
lake vouches it (a date in ``_adjusted_through.json``), that date is not after its last
price row (newer rows are kept price-only), and it is within 3 sessions of the lake's latest
vouched session; except that a tier 1 or 2 fund a
provider already keeps (source ``tiingo``, ``seed+tiingo`` or ``tsp``, not ``unavailable``)
stays the provider's. A taken symbol gets ``prices/{SYMBOL}.parquet`` (``tr_index`` from
``adj_close``) unless its lake files are unchanged since the last sync (digest), and an entry
``source: lake`` with ``relies_on_yfinance``. The entries go to ``meta/lake.json`` (written by
this job only), then into ``meta/manifest.json`` by a conditional read-modify-write (never over
a write it did not read), then ``meta/symbols.json``. A symbol that was taken and no longer
qualifies is released to ``seed``/``pending``. The R2 keys come from
``~/.secrets/portfoliosight.env`` and are never printed.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import logging
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from portfoliosight.data import lake as lake_mod  # noqa: E402
from portfoliosight.data import manifest as manifest_mod  # noqa: E402
from portfoliosight.data import store as store_mod  # noqa: E402
from portfoliosight.data.calendar import (  # noqa: E402
    SCHEDULE_ZONE,
    generation_date,
    session_back,
)
from portfoliosight.data.lake import LakeEntry, LakeOverlay  # noqa: E402
from portfoliosight.data.manifest import Manifest, ManifestEntry  # noqa: E402
from portfoliosight.data.secrets import (  # noqa: E402
    RedactingFilter,
    install_redaction,
    redacted_traceback,
)
from portfoliosight.data.universe import SymbolInfo, Tiers, is_tsp, load_tiers  # noqa: E402

DEFAULT_LAKE = "~/tft-quantile-forecaster/data/tft/raw/eodhd/datalake_us_core"
DEFAULT_LOCK = "~/.local/state/portfoliosight/sync_lake.lock"
ADJUSTED_FILE = "_adjusted_through.json"
READY_AT = time(6, 45)  # QSE's stitch starts then (America/Los_Angeles, weekdays)
ALERT_AFTER = time(9, 50)  # the last poll of the day: a run still missing then is an alert
DIGEST_VERSION = b"lake-record-1"
THREADS = 8
# QSE's repair filled the lake's dividend and split rows after this day partly from the Yahoo
# Finance library. Only these two sources are primary; an entry with any other source among its
# rows after the day is flagged ``relies_on_yfinance`` (an allow-list: a new source is flagged too).
SECONDARY_SINCE = date(2026, 3, 20)
PRIMARY_SOURCES = frozenset({"eodhd", "schwab"})
PROVIDER_TIERS = (1, 2)
NOT_PROVIDER = ("seed", lake_mod.LAKE_SOURCE)

SKIP_NOT_IN_LAKE = "not in the lake"
SKIP_PROVIDER = "kept current by the provider"
SKIP_NOT_VOUCHED = "not vouched by the lake"
SKIP_BEHIND = "more than 3 sessions behind the lake's latest session"
SKIP_TAIL = "vouched date is after the last price row"
SKIP_UNUSABLE = "unusable prices"

logger = logging.getLogger("sync_lake")
install_redaction([logger.name])
Emit = Callable[[str], None]


class LakeUnreadable(Exception):
    """The lake's ``_adjusted_through.json`` is missing or not what QSE writes."""


@dataclass(frozen=True)
class LakeRun:
    generated_at: datetime
    vouched: dict[str, date]


@dataclass(frozen=True)
class Outcome:
    symbol: str
    action: str  # written | unchanged | skipped
    reason: str | None = None
    entry: LakeEntry | None = None
    record: bytes | None = None  # the canonical record to store (written outcomes only)


def read_lake_run(lake: Path) -> LakeRun:
    """``generated_at`` (timezone-aware) and the vouched date per symbol of the lake's run."""
    path = lake / ADJUSTED_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        generated_at = datetime.fromisoformat(str(doc["generated_at"]))
        vouched = {
            str(symbol).upper(): date.fromisoformat(str(day))
            for symbol, day in dict(doc["symbols"]).items()
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LakeUnreadable(f"cannot read {path}: {type(exc).__name__}: {exc}") from exc
    if generated_at.tzinfo is None:
        raise LakeUnreadable(f"{path}: generated_at {generated_at} carries no UTC offset")
    return LakeRun(generated_at, vouched)


def gate(now: datetime, generated_at: datetime, force: bool) -> tuple[bool, int, str]:
    """``(go, exit_code, message)``: whether today's lake run is complete and may be synced."""
    if force:
        return True, 0, f"--force: syncing the lake run generated at {generated_at.isoformat()}"
    local = now.astimezone(SCHEDULE_ZONE)
    if local.weekday() >= 5:
        return False, 0, "weekend: QSE's price stitch does not run; nothing to do"
    ready = datetime.combine(local.date(), READY_AT, tzinfo=SCHEDULE_ZONE)
    if generated_at >= ready:
        return True, 0, f"the lake run of {local.date()} is complete ({generated_at.isoformat()})"
    if local.time() >= ALERT_AFTER:
        return (
            False,
            1,
            f"ALERT sync_lake: the lake run of {local.date()} is not complete by "
            f"{ALERT_AFTER.strftime('%H:%M')} PT (generated_at {generated_at.isoformat()}); "
            "nothing uploaded",
        )
    return (
        False,
        0,
        f"waiting: the lake run of {local.date()} is not complete yet "
        f"(generated_at {generated_at.isoformat()})",
    )


def file_digest(vouched: date, paths: list[Path]) -> str:
    """sha256 of the vouched date and the bytes of each file (a missing file counts as absent)."""
    digest = hashlib.sha256(DIGEST_VERSION)
    digest.update(vouched.isoformat().encode())
    for path in paths:
        digest.update(path.name.encode())
        if path.is_file():
            digest.update(b"\x01")
            digest.update(path.read_bytes())
        else:
            digest.update(b"\x00")
    return digest.hexdigest()


def action_sources(paths: list[Path], since: date = SECONDARY_SINCE) -> list[str]:
    """The sorted sources of the dividend and split rows dated after ``since`` in ``paths``.

    A missing file, or one without rows or without a ``source`` column, contributes nothing.
    """
    found: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        frame = pd.read_parquet(path)
        if frame.empty or "date" not in frame.columns or "source" not in frame.columns:
            continue
        days = pd.to_datetime(frame["date"]).dt.tz_localize(None)
        after = frame.loc[(days > pd.Timestamp(since)).to_numpy(), "source"]
        found.update(str(value) for value in after.dropna())
    return sorted(found)


def provider_keeps(entry: ManifestEntry | None) -> bool:
    """A provider has refreshed this entry and still serves or retries it."""
    return entry is not None and entry.source not in NOT_PROVIDER and entry.status != "unavailable"


def mismatched(entry: ManifestEntry | None, taken: LakeEntry) -> bool:
    """The manifest does not carry the overlay's entry (another writer replaced it)."""
    return (
        entry is None
        or entry.source != lake_mod.LAKE_SOURCE
        or entry.last_date != taken.last_date
        or entry.fetched_at != taken.fetched_at
    )


@dataclass
class _Sync:
    lake: Path
    store: store_mod.Store
    now: datetime
    dry_run: bool
    run: LakeRun
    info: dict[str, SymbolInfo]
    base: Manifest
    previous: LakeOverlay
    recheck: set[str]

    def __post_init__(self) -> None:
        self.d_g = generation_date(self.now)
        latest = max(self.run.vouched.values())
        self.floor = session_back(latest, manifest_mod.SERVED_WITHIN_SESSIONS)

    def take(self, symbol: str) -> Outcome:
        eod = self.lake / "eod_history" / f"{symbol}.parquet"
        if not eod.is_file():
            return Outcome(symbol, "skipped", SKIP_NOT_IN_LAKE)
        known = self.info[symbol]
        base = self.base.symbols.get(symbol)
        if known.tier in PROVIDER_TIERS and provider_keeps(base):
            return Outcome(symbol, "skipped", SKIP_PROVIDER)
        day = self.run.vouched.get(symbol)
        if day is None:
            return Outcome(symbol, "skipped", SKIP_NOT_VOUCHED)
        if day < self.floor:
            return Outcome(symbol, "skipped", SKIP_BEHIND)
        actions = [self.lake / folder / f"{symbol}.parquet" for folder in ("dividends", "splits")]
        digest = file_digest(day, [eod, *actions])
        before = self.previous.symbols.get(symbol)
        if before is not None and before.digest == digest and symbol not in self.recheck:
            kept = before.model_copy(update={"tier": known.tier, "income": known.income})
            self._settle(kept)
            return Outcome(symbol, "unchanged", entry=kept)
        frame = lake_mod.read_eod(eod)
        if frame.empty or frame["date"].iloc[-1].date() < day:
            return Outcome(symbol, "skipped", SKIP_TAIL)
        if lake_mod.unusable_reason(frame) is not None:
            return Outcome(symbol, "skipped", SKIP_UNUSABLE)
        record = lake_mod.eod_to_record(frame, day)
        entry = LakeEntry(
            name=base.name if base is not None else symbol,
            kind=known.kind or (base.kind if base is not None else "etf"),
            tier=known.tier,
            income=known.income,
            source=lake_mod.LAKE_SOURCE,
            first_date=frame["date"].iloc[0].date(),
            last_date=frame["date"].iloc[-1].date(),
            adjusted_through=day,
            status="pending",
            fetched_at=self.now.astimezone(UTC).isoformat(),
            relies_on_yfinance=not PRIMARY_SOURCES.issuperset(action_sources(actions)),
            digest=digest,
        )
        self._settle(entry)
        data = None if self.dry_run else store_mod.record_to_bytes(record)
        return Outcome(symbol, "written", entry=entry, record=data)

    def claim(self, symbol: str) -> LakeEntry | None:
        """The entry that marks ``symbol`` as the lake's while its new record is stored.

        Its dates are those of the record now stored (the previous lake entry's, or the
        catalog's), and its digest is empty, so a run that fails to store the record rewrites it.
        """
        before = self.previous.symbols.get(symbol)
        if before is not None:
            return before.model_copy(update={"digest": ""})
        base = self.base.symbols.get(symbol)
        if base is None or base.last_date is None or base.adjusted_through is None:
            return None
        fields = base.model_dump(exclude={"source"})
        return LakeEntry(**fields, source=lake_mod.LAKE_SOURCE, digest="")

    def store_record(self, outcome: Outcome) -> str | None:
        """Store one record; the store's error text when it cannot, else ``None``."""
        assert outcome.record is not None
        try:
            self.store.put(store_mod.record_key(outcome.symbol), outcome.record)
        except store_mod.STORE_ERRORS as exc:
            return f"{type(exc).__name__}: {exc}"
        return None

    def _settle(self, entry: LakeEntry) -> None:
        entry.status = manifest_mod.status_for(entry, self.d_g)
        entry.reason = manifest_mod.reason_for(entry, entry.status, self.d_g)


@contextlib.contextmanager
def _single_run(lock: Path) -> Iterator[bool]:
    """This job's own lock (never QSE's pipeline lock): True when no other sync holds it."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _report(outcomes: list[Outcome], released: list[str], emit: Emit) -> dict[str, Any]:
    taken = [o.entry for o in outcomes if o.entry is not None]
    counts = {
        "written": sum(1 for o in outcomes if o.action == "written"),
        "unchanged": sum(1 for o in outcomes if o.action == "unchanged"),
        "status": dict(sorted(Counter(e.status for e in taken).items())),
        "served_stocks": sum(1 for e in taken if e.status == "ok" and e.kind == "stock"),
        "served": sum(1 for e in taken if e.status == "ok"),
        "relies_on_yfinance": sum(1 for e in taken if e.relies_on_yfinance),
        "skipped": dict(
            sorted(Counter(o.reason for o in outcomes if o.action == "skipped").items())
        ),
        "released": len(released),
    }
    emit(
        f"taken {len(taken)} ({counts['written']} written, {counts['unchanged']} unchanged); "
        f"status {counts['status']}; served {counts['served']} "
        f"({counts['served_stocks']} stocks); relies_on_yfinance {counts['relies_on_yfinance']}"
    )
    for reason, count in counts["skipped"].items():
        emit(f"skipped {count}: {reason}")
    if released:
        emit(f"released {len(released)} to seed: {', '.join(released[:20])}")
    return counts


def sync(
    *,
    lake: Path,
    store: store_mod.Store,
    now: datetime,
    force: bool = False,
    dry_run: bool = False,
    tiers: Tiers | None = None,
    emit: Emit = logger.info,
) -> int:
    """One sync; returns the exit code (0 also for waiting, weekend and already synced)."""
    run = read_lake_run(lake)
    go, code, message = gate(now, run.generated_at, force)
    emit(message)
    if not go:
        return code
    previous = lake_mod.load_lake(store)
    base = manifest_mod.load_manifest(store)
    recheck = {s for s, e in previous.symbols.items() if mismatched(base.symbols.get(s), e)}
    strays = {
        s for s, e in base.symbols.items() if e.source == "lake" and s not in previous.symbols
    }
    synced = previous.generated_at is not None and (
        datetime.fromisoformat(previous.generated_at) == run.generated_at
    )
    if synced and not force and not recheck and not strays:
        emit(f"the lake run generated at {run.generated_at.isoformat()} is already synced")
        return 0
    if recheck:
        emit(f"{len(recheck)} lake entries were replaced in the manifest; rewriting them")

    universe = tiers or load_tiers()
    info = {s: known for s, known in universe.info().items() if not is_tsp(s)}
    job = _Sync(lake, store, now, dry_run, run, info, base, previous, recheck)
    emit(
        f"lake {lake}: {len(run.vouched)} symbols vouched, latest session "
        f"{max(run.vouched.values())}, taken from {job.floor}; D_G {job.d_g}"
    )
    with ThreadPoolExecutor(THREADS) as pool:
        outcomes = list(pool.map(job.take, sorted(info)))
    taken = {o.symbol: o.entry for o in outcomes if o.entry is not None}
    released = sorted((set(previous.symbols) | strays) - set(taken))
    _report(outcomes, released, emit)
    if dry_run:
        emit("dry run: nothing written")
        return 0
    if read_lake_run(lake).generated_at != run.generated_at:
        emit("ALERT sync_lake: the lake changed during the sync; catalog not updated, rerun")
        return 1

    def publish_overlay(symbols: dict[str, LakeEntry], generated_at: str | None) -> LakeOverlay:
        overlay = LakeOverlay(
            generated_at=generated_at, synced_at=now.astimezone(UTC).isoformat(), symbols=symbols
        )
        store_mod.put_json(store, lake_mod.LAKE_KEY, overlay.to_json())
        return overlay

    # 1. Claim the symbols whose records are about to change, so that a provider walk running
    #    now neither fetches them nor writes a tail over the record being stored.
    writes = [o for o in outcomes if o.action == "written"]
    claims = {o.symbol: job.claim(o.symbol) for o in writes}
    if writes:
        claimed = {s: e for s, e in claims.items() if e is not None}
        kept = {o.symbol: o.entry for o in outcomes if o.action == "unchanged" and o.entry}
        publish_overlay({**kept, **claimed}, previous.generated_at)
    # 2. Store the records; one that cannot be stored keeps its claim (its old record).
    with ThreadPoolExecutor(THREADS) as pool:
        errors = list(pool.map(job.store_record, writes))
    failures = dict(zip([o.symbol for o in writes], errors, strict=True))
    failed = {symbol: error for symbol, error in failures.items() if error is not None}
    for symbol in failed:
        claim = claims[symbol]
        if claim is None:
            taken.pop(symbol, None)
        else:
            taken[symbol] = claim
    # 3. The overlay of this run, then the catalog. A run with failures is not recorded as
    #    synced, so the next poll stores what is missing (the rest is unchanged by digest).
    overlay = publish_overlay(
        taken, previous.generated_at if failed else run.generated_at.isoformat()
    )

    def change(document: Any) -> dict[str, Any]:
        manifest = Manifest.model_validate(document or {})
        lake_mod.apply_lake(manifest, overlay, job.d_g)
        return manifest.to_json()

    written = Manifest.model_validate(
        store_mod.update_json(store, manifest_mod.MANIFEST_KEY, change)
    )
    store_mod.put_json(
        store,
        manifest_mod.SYMBOLS_KEY,
        manifest_mod.symbols_view(written, now.astimezone(UTC)),
    )
    if failed:
        sample = "; ".join(f"{symbol}: {error}" for symbol, error in sorted(failed.items())[:5])
        emit(
            f"ALERT sync_lake: {len(failed)} record(s) could not be stored, the next poll "
            f"retries them: {RedactingFilter().redact(sample)[:600]}"
        )
        return 1
    emit(f"synced the lake run generated at {run.generated_at.isoformat()}")
    return 0


def main(argv: list[str] | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the lake's current symbols.")
    parser.add_argument("--lake", default=DEFAULT_LAKE, help="the datalake_us_core directory")
    parser.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    parser.add_argument(
        "--force", action="store_true", help="sync the lake run there is, whatever the time"
    )
    parser.add_argument("--lock", default=DEFAULT_LOCK, help="this job's own lock file")
    args = parser.parse_args(argv)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    moment = now or datetime.now(UTC)
    with _single_run(Path(args.lock).expanduser()) as alone:
        if not alone:
            logger.info("another sync holds %s; nothing to do", args.lock)
            return 0
        try:
            store = store_mod.store_from_env()
            return sync(
                lake=Path(args.lake).expanduser(),
                store=store,
                now=moment,
                force=args.force,
                dry_run=args.dry_run,
            )
        except LakeUnreadable as exc:
            logger.error("ALERT sync_lake: %s", exc)
            return 1
        except store_mod.StoreConfigError as exc:
            logger.error("ALERT sync_lake: store not configured: %s", exc)
            return 2
        except Exception as exc:
            logger.error("ALERT sync_lake: failed\n%s", redacted_traceback(exc))
            return 1


if __name__ == "__main__":
    from portfoliosight.data.secrets import load_env

    load_env()
    raise SystemExit(main())
