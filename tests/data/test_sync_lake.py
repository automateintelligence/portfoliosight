"""The lake sync (spec 5.4): what it takes, skips and releases, and when it refuses to run."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from portfoliosight.data import download
from portfoliosight.data import lake as lake_mod
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.store import LocalStore
from portfoliosight.data.universe import Tiers
from tests.data.test_download import Clock, FakeProvider

ROOT = Path(__file__).resolve().parents[2]
LATEST = date(2026, 10, 13)
STOPPED = date(2026, 3, 26)
# Wednesday 2026-10-14: QSE's stitch wrote the run at 06:50 PDT; the poll is at 07:30 PDT.
GENERATED = "2026-10-14T13:50:00+00:00"
NOW = datetime(2026, 10, 14, 14, 30, tzinfo=UTC)
TIERS = Tiers(
    tier1=("VTI",),
    tier2=("VTI", "BND", "SGOV"),
    tier3=("AAPL", "MSFT", "OLD", "GONE", "PART", "AHEAD", "BND"),
    income=frozenset({"BND"}),
    starter_slice=2,
)
SESSIONS = [
    date.fromisoformat(str(s)[:10])
    for s in xcals.get_calendar("XNYS").sessions_in_range("2026-01-02", LATEST.isoformat())
]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


sync_lake = _load_script("sync_lake")


def _eod(symbol: str, through: date) -> pd.DataFrame:
    days = [d for d in SESSIONS if d <= through]
    rng = np.random.default_rng(sum(map(ord, symbol)))
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.0004, 0.01, len(days)))
    adj = close * np.linspace(0.97, 1.0, len(days))  # back-adjusted: equal on the last row
    return pd.DataFrame(
        {
            "date": pd.to_datetime([d.isoformat() for d in days]),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "adj_close": adj,
            "volume": np.full(len(days), 1000, dtype="int64"),
        }
    )


def _actions(rows: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime([day for day, _ in rows]),
            "value": [0.25] * len(rows),
            "source": pd.Series([source for _, source in rows], dtype="string"),
        }
    )


def _write_lake(root: Path, vouched: dict[str, str], generated: str = GENERATED) -> Path:
    for folder in ("eod_history", "dividends", "splits"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "_adjusted_through.json").write_text(
        json.dumps({"generated_at": generated, "method": "schwab+yfinance", "symbols": vouched})
    )
    return root


@pytest.fixture
def lake(tmp_path) -> Path:
    """AAPL and MSFT vouched through the latest session (AAPL with a yfinance dividend), OLD
    vouched and stopped in March, GONE not vouched, PART vouched a session short of its last
    row (taken, newest row price-only), AHEAD vouched past its last row, VTI (tier 1, the
    provider's) and BND (tier 2, a pending seed) current; SGOV not in the lake."""
    root = tmp_path / "lake"
    _write_lake(
        root,
        {
            "AAPL": LATEST.isoformat(),
            "MSFT": LATEST.isoformat(),
            "OLD": STOPPED.isoformat(),
            "PART": "2026-10-12",
            "AHEAD": LATEST.isoformat(),
            "VTI": LATEST.isoformat(),
            "BND": LATEST.isoformat(),
        },
    )
    for symbol in ("AAPL", "MSFT", "PART", "GONE", "VTI", "BND"):
        _eod(symbol, LATEST).to_parquet(root / "eod_history" / f"{symbol}.parquet", index=False)
    _eod("OLD", STOPPED).to_parquet(root / "eod_history" / "OLD.parquet", index=False)
    ahead = _eod("AHEAD", date(2026, 10, 12))
    ahead.to_parquet(root / "eod_history" / "AHEAD.parquet", index=False)
    _actions([("2026-02-09", "eodhd"), ("2026-05-11", "yfinance")]).to_parquet(
        root / "dividends" / "AAPL.parquet", index=False
    )
    _actions([("2026-05-21", "eodhd"), ("2026-08-20", "schwab")]).to_parquet(
        root / "dividends" / "MSFT.parquet", index=False
    )
    pd.DataFrame().to_parquet(root / "splits" / "MSFT.parquet")  # QSE's empty file: no columns
    _actions([("2026-03-02", "yfinance")]).to_parquet(
        root / "dividends" / "BND.parquet", index=False
    )
    return root


def _seed_entry(symbol: str, tier: int, kind: str) -> dict:
    return {
        "name": symbol,
        "kind": kind,
        "tier": tier,
        "income": False,
        "source": "seed",
        "first_date": "2026-01-02",
        "last_date": "2026-03-27",
        "adjusted_through": "2026-03-27",
        "status": "pending",
        "reason": "corporate actions not yet verified after 2026-03-27",
        "fetched_at": None,
    }


@pytest.fixture
def store(tmp_path) -> LocalStore:
    store = LocalStore(tmp_path / "store")
    vti = {
        **_seed_entry("VTI", 1, "etf"),
        "name": "Vanguard Total Stock Market ETF",
        "source": "seed+tiingo",
        "last_date": "2026-10-13",
        "adjusted_through": "2026-10-13",
        "status": "ok",
        "reason": None,
        "fetched_at": "2026-10-14T09:00:00+00:00",
    }
    entries = {
        "VTI": vti,
        "BND": {**_seed_entry("BND", 2, "etf"), "name": "Vanguard Total Bond Market ETF"},
        "AAPL": {**_seed_entry("AAPL", 3, "stock"), "source": "seed+tiingo", "status": "stale"},
        "MSFT": _seed_entry("MSFT", 3, "stock"),
        "OLD": _seed_entry("OLD", 3, "stock"),
    }
    store_mod.put_json(store, manifest_mod.MANIFEST_KEY, {"symbols": entries})
    return store


class Recording:
    """A store proxy that records every put (the five pinned methods only)."""

    def __init__(self, inner: LocalStore):
        self.inner = inner
        self.puts: list[str] = []

    def get(self, key):
        return self.inner.get(key)

    def put(self, key, data):
        self.puts.append(key)
        self.inner.put(key, data)

    def exists(self, key):
        return self.inner.exists(key)

    def list(self, prefix=""):
        return self.inner.list(prefix)

    def delete(self, key):
        self.inner.delete(key)


def _sync(
    lake: Path, store, now: datetime = NOW, withheld: dict | None = None, **kwargs
) -> tuple[int, list[str]]:
    """One sync; ``withheld``, when given, is written as the owner's list first (else it stays
    as the last call left it, empty at the start)."""
    path = lake.parent / "withheld.json"
    if withheld is not None or not path.exists():
        path.write_text(json.dumps(withheld or {}))
    lines: list[str] = []
    code = sync_lake.sync(
        lake=lake,
        store=store,
        now=now,
        tiers=TIERS,
        withheld_file=path,
        emit=lines.append,
        **kwargs,
    )
    return code, lines


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _manifest(store) -> dict[str, dict]:
    return store_mod.get_json(store, manifest_mod.MANIFEST_KEY)["symbols"]


def test_sync_takes_current_vouched_symbols_and_serves_them(lake, store):
    before = _snapshot(lake)
    code, lines = _sync(lake, store)
    assert code == 0, lines
    assert _snapshot(lake) == before  # the lake is only read

    entries = _manifest(store)
    for symbol in ("AAPL", "MSFT", "BND"):
        assert entries[symbol]["source"] == "lake", symbol
        assert entries[symbol]["status"] == "ok", symbol
        assert entries[symbol]["last_date"] == entries[symbol]["adjusted_through"] == "2026-10-13"
    assert entries["AAPL"]["relies_on_yfinance"] is True
    assert entries["MSFT"]["relies_on_yfinance"] is False
    # BND's only yfinance row is dated before 2026-03-21: not relied on.
    assert entries["BND"]["relies_on_yfinance"] is False
    assert entries["BND"]["kind"] == "etf" and entries["BND"]["tier"] == 2
    assert entries["BND"]["income"] is True
    assert entries["BND"]["name"] == "Vanguard Total Bond Market ETF"
    assert entries["AAPL"]["kind"] == "stock" and entries["AAPL"]["tier"] == 3
    # The provider keeps its tier 1 fund; March-stale and unvouched symbols are not taken.
    assert entries["VTI"]["source"] == "seed+tiingo"
    assert entries["OLD"]["source"] == "seed" and entries["OLD"]["status"] == "pending"
    assert {"GONE", "AHEAD", "SGOV"}.isdisjoint(entries)
    # vouched a session behind its last row: taken, the newest row price-only
    assert entries["PART"]["source"] == "lake" and entries["PART"]["status"] == "ok"
    assert entries["PART"]["adjusted_through"] == "2026-10-12"
    assert entries["PART"]["last_date"] == "2026-10-13"

    record = store_mod.get_record(store, "AAPL")
    eod = pd.read_parquet(lake / "eod_history" / "AAPL.parquet")
    expected = eod["adj_close"].to_numpy() / eod["adj_close"].iloc[0]
    np.testing.assert_allclose(record["tr_index"].to_numpy(), expected, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(record["close"].to_numpy(), eod["close"].to_numpy())

    overlay = lake_mod.load_lake(store)
    assert overlay.generated_at == GENERATED
    assert sorted(overlay.symbols) == ["AAPL", "BND", "MSFT", "PART"]

    listed = store_mod.get_json(store, manifest_mod.SYMBOLS_KEY)["symbols"]
    by_id = {row["id"]: row for row in listed}
    assert by_id["AAPL"]["kind"] == "stock" and by_id["MSFT"]["kind"] == "stock"
    assert {"AAPL", "MSFT", "BND", "PART", "VTI"} == set(by_id)


def test_dry_run_counts_by_status_and_reason_and_writes_nothing(lake, store):
    recording = Recording(store)
    code, lines = _sync(lake, recording, dry_run=True)
    assert code == 0 and recording.puts == []
    text = "\n".join(lines)
    assert "taken 4 (4 written, 0 unchanged); status {'ok': 4}" in text
    assert "served 4 (3 stocks); relies_on_yfinance 1" in text
    for line in (
        "skipped 1: kept current by the provider",
        "skipped 1: more than 3 sessions behind the lake's latest session",
        "skipped 1: not vouched by the lake",
        "skipped 1: vouched date is after the last price row",
        "skipped 1: not in the lake",
    ):
        assert line in lines, (line, lines)
    assert "dry run: nothing written" in lines


def test_a_new_run_rewrites_only_changed_symbols_and_a_repeat_is_a_no_op(lake, store):
    assert _sync(lake, store)[0] == 0
    recording = Recording(store)
    code, lines = _sync(lake, recording)
    assert code == 0 and recording.puts == []
    assert any("already synced" in line for line in lines)

    # The next lake run: only AAPL's files changed.
    vouched = json.loads((lake / "_adjusted_through.json").read_text())["symbols"]
    _write_lake(lake, vouched, generated="2026-10-15T13:52:00+00:00")
    frame = pd.read_parquet(lake / "eod_history" / "AAPL.parquet")
    frame.loc[frame.index[-1], "volume"] = 2000
    frame.to_parquet(lake / "eod_history" / "AAPL.parquet", index=False)
    code, lines = _sync(lake, recording, now=datetime(2026, 10, 15, 14, 30, tzinfo=UTC))
    assert code == 0, lines
    assert [key for key in recording.puts if key.startswith("prices/")] == ["prices/AAPL.parquet"]
    assert "taken 4 (1 written, 3 unchanged); status {'ok': 4}" in "\n".join(lines)
    assert lake_mod.load_lake(store).generated_at == "2026-10-15T13:52:00+00:00"


@pytest.mark.parametrize(
    ("now", "generated", "code", "says"),
    [
        # Thursday 07:20 PDT, the run still yesterday's: wait quietly.
        (datetime(2026, 10, 15, 14, 20, tzinfo=UTC), GENERATED, 0, "waiting"),
        # Thursday 09:50 PDT, the last poll: alert, upload nothing.
        (datetime(2026, 10, 15, 16, 50, tzinfo=UTC), GENERATED, 1, "ALERT sync_lake"),
        # A run written before 06:45 PDT today (a late-night repair run) is not today's stitch.
        (datetime(2026, 10, 15, 17, 0, tzinfo=UTC), "2026-10-15T04:05:43+00:00", 1, "ALERT"),
        # Saturday: no stitch, nothing to do.
        (datetime(2026, 10, 17, 16, 0, tzinfo=UTC), GENERATED, 0, "weekend"),
    ],
)
def test_an_incomplete_lake_run_is_refused(lake, store, now, generated, code, says):
    vouched = json.loads((lake / "_adjusted_through.json").read_text())["symbols"]
    _write_lake(lake, vouched, generated=generated)
    recording = Recording(store)
    got, lines = _sync(lake, recording, now=now)
    assert got == code and recording.puts == []
    assert says in lines[0]


def test_force_syncs_the_lake_run_there_is(lake, store):
    sunday_night = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)
    code, lines = _sync(lake, store, now=sunday_night, force=True)
    assert code == 0 and lines[0].startswith("--force")
    assert _manifest(store)["AAPL"]["source"] == "lake"


def test_completion_is_compared_as_a_timestamp_not_a_string():
    # 06:45 PDT is 13:45 UTC; written with a -07:00 offset, a string compare would fail it.
    go, _, _ = sync_lake.gate(
        datetime(2026, 10, 14, 15, 0, tzinfo=UTC),
        datetime.fromisoformat("2026-10-14T06:46:00-07:00"),
        force=False,
    )
    assert go
    go, _, _ = sync_lake.gate(
        datetime(2026, 10, 14, 15, 0, tzinfo=UTC),
        datetime.fromisoformat("2026-10-14T13:44:59+00:00"),
        force=False,
    )
    assert not go


def test_a_symbol_the_lake_stops_vouching_is_released(lake, store):
    assert _sync(lake, store)[0] == 0
    vouched = json.loads((lake / "_adjusted_through.json").read_text())["symbols"]
    del vouched["MSFT"]
    _write_lake(lake, vouched, generated="2026-10-15T13:52:00+00:00")
    code, lines = _sync(lake, store, now=datetime(2026, 10, 15, 14, 30, tzinfo=UTC))
    assert code == 0 and "released 1 to seed: MSFT" in lines
    msft = _manifest(store)["MSFT"]
    assert msft["source"] == "seed" and msft["status"] == "pending"
    assert msft["adjusted_through"] == "2026-10-13"
    assert "MSFT" not in lake_mod.load_lake(store).symbols
    listed = {row["id"] for row in store_mod.get_json(store, manifest_mod.SYMBOLS_KEY)["symbols"]}
    assert "MSFT" not in listed and "AAPL" in listed


def test_an_entry_another_writer_replaced_is_rewritten_with_its_record(lake, store):
    assert _sync(lake, store)[0] == 0
    # An older nightly wrote the manifest without the overlay and spliced AAPL's record.
    entries = _manifest(store)
    entries["AAPL"] = _seed_entry("AAPL", 3, "stock")
    store_mod.put_json(store, manifest_mod.MANIFEST_KEY, {"symbols": entries})
    store.put("prices/AAPL.parquet", b"clobbered")
    recording = Recording(store)
    code, lines = _sync(lake, recording)
    assert code == 0, lines
    assert [key for key in recording.puts if key.startswith("prices/")] == ["prices/AAPL.parquet"]
    assert _manifest(store)["AAPL"]["source"] == "lake"
    assert len(store_mod.get_record(store, "AAPL")) > 100


class RacingStore(LocalStore):
    """A nightly catalog write lands right after the sync reads the manifest."""

    raced = False

    def get_tagged(self, key: str) -> tuple[bytes, str]:
        data, tag = super().get_tagged(key)
        if key == manifest_mod.MANIFEST_KEY and not self.raced:
            self.raced = True
            nightly = json.loads(data)
            nightly["symbols"]["NEW"] = {**_seed_entry("NEW", 2, "etf"), "source": "tiingo"}
            store_mod.put_json(self, key, nightly)
        return data, tag


def test_the_manifest_write_never_overwrites_a_write_it_did_not_read(lake, store):
    racing = RacingStore(store.root)
    code, lines = _sync(lake, racing)
    assert code == 0 and racing.raced, lines
    entries = _manifest(store)
    assert entries["NEW"]["source"] == "tiingo"  # the other writer's entry survived
    assert entries["AAPL"]["source"] == "lake"  # and the sync's entries are in


def test_main_takes_its_own_lock_and_reports_an_unreadable_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("PS_STORE", "local")
    monkeypatch.setenv("PS_LOCAL_STORE_DIR", str(tmp_path / "store"))
    lock = tmp_path / "state" / "sync_lake.lock"
    args = ["--lake", str(tmp_path / "missing"), "--lock", str(lock)]
    assert sync_lake.main(args, now=NOW) == 1
    assert lock.exists()
    with sync_lake._single_run(lock) as alone:
        assert alone
        assert sync_lake.main(args, now=NOW) == 0  # another sync holds it: nothing to do


def test_action_sources_reads_rows_after_the_cutoff_only(tmp_path):
    dividends = tmp_path / "dividends.parquet"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-03-20", "2026-03-23", "2026-06-01"]),
            "source": pd.Series(["yfinance", "eodhd", "schwab"], dtype="string"),
        }
    ).to_parquet(dividends, index=False)
    empty = tmp_path / "splits.parquet"
    pd.DataFrame().to_parquet(empty)
    assert sync_lake.action_sources([dividends, empty, tmp_path / "absent.parquet"]) == [
        "eodhd",
        "schwab",
    ]


def test_a_symbol_the_lake_brings_back_to_current_is_taken(lake, store):
    """QSE backfills a symbol that stopped in March: its date jumps to the latest session."""
    assert _sync(lake, store)[0] == 0
    assert "OLD" not in lake_mod.load_lake(store).symbols
    vouched = json.loads((lake / "_adjusted_through.json").read_text())["symbols"]
    vouched["OLD"] = LATEST.isoformat()
    _write_lake(lake, vouched, generated="2026-10-15T13:52:00+00:00")
    _eod("OLD", LATEST).to_parquet(lake / "eod_history" / "OLD.parquet", index=False)
    recording = Recording(store)
    code, lines = _sync(lake, recording, now=datetime(2026, 10, 15, 14, 30, tzinfo=UTC))
    assert code == 0, lines
    assert [key for key in recording.puts if key.startswith("prices/")] == ["prices/OLD.parquet"]
    old = _manifest(store)["OLD"]
    assert (old["source"], old["status"], old["last_date"]) == ("lake", "ok", "2026-10-13")


def test_the_claim_comes_first_and_a_record_that_cannot_be_stored_is_retried(lake, store):
    class Failing(Recording):
        def put(self, key, data):
            if key == "prices/AAPL.parquet":
                raise OSError("R2 kept answering 500")
            super().put(key, data)

    failing = Failing(store)
    code, lines = _sync(lake, failing)
    assert code == 1 and any(
        line.startswith("ALERT sync_lake: 1 record(s)") and "AAPL" in line for line in lines
    )
    # The overlay claimed the symbols before any record changed.
    first_record = min(i for i, key in enumerate(failing.puts) if key.startswith("prices/"))
    assert failing.puts.index(lake_mod.LAKE_KEY) < first_record
    entries = _manifest(store)
    assert entries["MSFT"]["source"] == "lake" and entries["MSFT"]["status"] == "ok"
    # AAPL keeps its old record under a claim: the lake's, not fetched, not served yet.
    assert entries["AAPL"]["source"] == "lake" and entries["AAPL"]["status"] == "stale"
    assert entries["AAPL"]["last_date"] == "2026-03-27"
    overlay = lake_mod.load_lake(store)
    assert overlay.generated_at is None and overlay.symbols["AAPL"].digest == ""

    # The next poll stores only what is missing.
    recording = Recording(store)
    code, lines = _sync(lake, recording)
    assert code == 0, lines
    assert [key for key in recording.puts if key.startswith("prices/")] == ["prices/AAPL.parquet"]
    assert _manifest(store)["AAPL"]["status"] == "ok"
    assert lake_mod.load_lake(store).generated_at == GENERATED


def _fundamentals(lake: Path, files: dict[str, str]) -> None:
    folder = lake / lake_mod.FUNDAMENTALS_DIR
    folder.mkdir(exist_ok=True)
    for symbol, text in files.items():
        (folder / f"{symbol}.json").write_text(text)


def _general(name: str) -> str:
    return json.dumps({"General": {"Name": name}, "Highlights": {"MarketCapitalization": 1}})


def test_taken_symbols_carry_the_lake_name_and_unnamed_entries_get_it(lake, store):
    """AAPL is named by its fundamentals file; MSFT's file is empty and PART has none, so they
    keep their ticker; BND's file has no ``General.Name``, so it keeps the catalog's name. OLD
    (not taken, no name) gets the lake's name; VTI (the provider's) keeps its own."""
    _fundamentals(
        lake,
        {
            "AAPL": _general(" Apple Inc. "),
            "MSFT": "",
            "BND": json.dumps({"static": {"sector": "Bonds"}}),
            "OLD": _general("Old Industries Inc"),
            "VTI": _general("Vanguard Total Stock Market Index Fund ETF Shares"),
        },
    )
    before = _snapshot(lake)
    code, lines = _sync(lake, store)
    assert code == 0, lines
    assert _snapshot(lake) == before
    entries = _manifest(store)
    assert entries["AAPL"]["name"] == "Apple Inc."
    assert entries["MSFT"]["name"] == "MSFT" and entries["PART"]["name"] == "PART"
    assert entries["BND"]["name"] == "Vanguard Total Bond Market ETF"
    assert entries["OLD"]["name"] == "Old Industries Inc" and entries["OLD"]["source"] == "seed"
    assert entries["VTI"]["name"] == "Vanguard Total Stock Market ETF"
    assert lake_mod.load_lake(store).symbols["AAPL"].name == "Apple Inc."
    listed = {
        r["id"]: r["name"] for r in store_mod.get_json(store, manifest_mod.SYMBOLS_KEY)["symbols"]
    }
    assert listed["AAPL"] == "Apple Inc." and listed["VTI"] == "Vanguard Total Stock Market ETF"
    assert (
        "names: 2 taken entries have only their ticker; "
        "1 entries other writers keep get the lake's name"
    ) in lines


def test_a_name_only_change_rewrites_the_entry_not_the_record(lake, store):
    assert _sync(lake, store)[0] == 0
    assert _manifest(store)["MSFT"]["name"] == "MSFT"
    # The next lake run changes no price file, only MSFT's fundamentals.
    vouched = json.loads((lake / "_adjusted_through.json").read_text())["symbols"]
    _write_lake(lake, vouched, generated="2026-10-15T13:52:00+00:00")
    _fundamentals(lake, {"MSFT": _general("Microsoft Corporation")})
    recording = Recording(store)
    code, lines = _sync(lake, recording, now=datetime(2026, 10, 15, 14, 30, tzinfo=UTC))
    assert code == 0, lines
    assert [key for key in recording.puts if key.startswith("prices/")] == []
    assert "taken 4 (0 written, 4 unchanged); status {'ok': 4}" in "\n".join(lines)
    assert _manifest(store)["MSFT"]["name"] == "Microsoft Corporation"
    assert lake_mod.load_lake(store).symbols["MSFT"].name == "Microsoft Corporation"
    listed = {
        r["id"]: r["name"] for r in store_mod.get_json(store, manifest_mod.SYMBOLS_KEY)["symbols"]
    }
    assert listed["MSFT"] == "Microsoft Corporation"


HELD = {"note": "price error under repair", "good_through": "2026-03-20", "since": "2026-10-14"}
HELD_REASON = "price error under repair; no data since 2026-03-20"


def _listed(store) -> set[str]:
    return {row["id"] for row in store_mod.get_json(store, manifest_mod.SYMBOLS_KEY)["symbols"]}


def test_a_withheld_symbol_is_not_taken_served_or_rewritten(lake, store):
    assert _sync(lake, store)[0] == 0
    stored = store.get("prices/AAPL.parquet")
    assert _manifest(store)["AAPL"]["status"] == "ok"

    # The owner lists AAPL; the lake run is the one already synced.
    recording = Recording(store)
    code, lines = _sync(lake, recording, withheld={"AAPL": HELD})
    assert code == 0, lines
    assert [key for key in recording.puts if key.startswith("prices/")] == []
    assert store.get("prices/AAPL.parquet") == stored  # the record is kept as it is
    aapl = _manifest(store)["AAPL"]
    assert (aapl["source"], aapl["status"], aapl["reason"]) == ("lake", "unavailable", HELD_REASON)
    assert "AAPL" not in _listed(store) and "MSFT" in _listed(store)
    text = "\n".join(lines)
    assert "taken 3 (0 written, 3 unchanged); status {'ok': 3}" in text
    assert f"skipped 1: {sync_lake.SKIP_WITHHELD}" in lines
    # A nightly deployed before the withheld list drops the mark it does not know and
    # recomputes the status from the entry's dates: still not served.
    overlay = store_mod.get_json(store, lake_mod.LAKE_KEY)
    overlay["symbols"]["AAPL"].pop("withheld")
    older = manifest_mod.load_manifest(store)
    lake_mod.apply_lake(older, lake_mod.LakeOverlay.model_validate(overlay), LATEST)
    assert older.symbols["AAPL"].status != "ok"

    # A later run of the lake that changed AAPL's files still does not take it.
    vouched = json.loads((lake / "_adjusted_through.json").read_text())["symbols"]
    _write_lake(lake, vouched, generated="2026-10-15T13:52:00+00:00")
    frame = pd.read_parquet(lake / "eod_history" / "AAPL.parquet")
    frame.loc[frame.index[-1], "volume"] = 2000
    frame.to_parquet(lake / "eod_history" / "AAPL.parquet", index=False)
    code, lines = _sync(lake, recording, now=datetime(2026, 10, 15, 14, 30, tzinfo=UTC))
    assert code == 0, lines
    assert [key for key in recording.puts if key.startswith("prices/")] == []
    assert store.get("prices/AAPL.parquet") == stored
    assert _manifest(store)["AAPL"]["status"] == "unavailable"
    assert "AAPL" not in _listed(store)


def test_a_symbol_withheld_before_it_was_ever_taken_is_catalogued_unavailable(lake, store):
    recording = Recording(store)
    code, lines = _sync(lake, recording, withheld={"AAPL": HELD})
    assert code == 0, lines
    assert "prices/AAPL.parquet" not in recording.puts
    aapl = _manifest(store)["AAPL"]
    assert (aapl["source"], aapl["status"], aapl["reason"]) == ("lake", "unavailable", HELD_REASON)
    assert "AAPL" not in _listed(store)
    assert f"skipped 1: {sync_lake.SKIP_WITHHELD}" in lines


def test_the_dry_run_counts_a_withheld_symbol_as_skipped(lake, store):
    recording = Recording(store)
    code, lines = _sync(lake, recording, withheld={"AAPL": HELD}, dry_run=True)
    assert code == 0 and recording.puts == []
    assert "taken 3 (3 written, 0 unchanged); status {'ok': 3}" in "\n".join(lines)
    assert f"skipped 1: {sync_lake.SKIP_WITHHELD}" in lines


def test_a_symbol_taken_off_the_list_is_taken_again_by_the_next_sync(lake, store):
    assert _sync(lake, store, withheld={"AAPL": HELD})[0] == 0
    assert _manifest(store)["AAPL"]["status"] == "unavailable"
    recording = Recording(store)
    code, lines = _sync(lake, recording, withheld={})
    assert code == 0, lines
    assert [key for key in recording.puts if key.startswith("prices/")] == ["prices/AAPL.parquet"]
    aapl = _manifest(store)["AAPL"]
    assert (aapl["source"], aapl["status"], aapl["reason"]) == ("lake", "ok", None)
    assert aapl["last_date"] == aapl["adjusted_through"] == LATEST.isoformat()
    assert "AAPL" in _listed(store)


def test_a_malformed_list_stops_the_sync_before_anything_is_written(lake, store):
    recording = Recording(store)
    bad = {"AAPL": HELD, "MSFT": {**HELD, "note": ""}}
    code, lines = _sync(lake, recording, withheld=bad)
    assert code == 1 and recording.puts == []
    alert = [line for line in lines if line.startswith("ALERT sync_lake")]
    assert len(alert) == 1 and "withheld.json" in alert[0] and "MSFT" in alert[0]


def test_the_nightly_and_a_restatus_after_the_sync_keep_a_withheld_symbol_unserved(lake, store):
    assert _sync(lake, store)[0] == 0
    assert _sync(lake, store, withheld={"AAPL": HELD})[0] == 0
    stored = store.get("prices/AAPL.parquet")

    # The first run of a month retries every unavailable symbol; AAPL is the lake's, not asked.
    provider = FakeProvider(default_available=date(2026, 10, 30))
    clock = Clock(date(2026, 11, 1), 10)
    download.run(
        "refresh",
        store=store,
        providers={"tiingo": provider},
        clock=clock,
        sleep=clock.sleep,
        symbols=["AAPL", "MSFT"],
    )
    assert "AAPL" not in {call[1] for call in provider.calls}
    assert store.get("prices/AAPL.parquet") == stored
    aapl = _manifest(store)["AAPL"]
    assert (aapl["source"], aapl["status"], aapl["reason"]) == ("lake", "unavailable", HELD_REASON)
    assert "AAPL" not in _listed(store)

    manifest = manifest_mod.load_manifest(store)
    manifest_mod.restatus(manifest, date(2026, 11, 2))
    assert manifest.symbols["AAPL"].status == "unavailable"
    assert manifest.symbols["AAPL"].reason == HELD_REASON


def test_a_withheld_symbol_stays_held_while_the_sync_stores_other_records(lake, store):
    """A provider walk that reads the overlay while the sync stores records must not find the
    withheld symbol missing from it (it would release it to the provider)."""
    assert _sync(lake, store)[0] == 0
    seen: list[lake_mod.LakeEntry | None] = []

    class Watching(Recording):
        def put(self, key, data):
            if key.startswith("prices/"):
                seen.append(lake_mod.load_lake(self.inner).symbols.get("AAPL"))
            super().put(key, data)

    vouched = json.loads((lake / "_adjusted_through.json").read_text())["symbols"]
    _write_lake(lake, vouched, generated="2026-10-15T13:52:00+00:00")
    frame = pd.read_parquet(lake / "eod_history" / "MSFT.parquet")
    frame.loc[frame.index[-1], "volume"] = 2000
    frame.to_parquet(lake / "eod_history" / "MSFT.parquet", index=False)
    watching = Watching(store)
    now = datetime(2026, 10, 15, 14, 30, tzinfo=UTC)
    code, lines = _sync(lake, watching, now=now, withheld={"AAPL": HELD})
    assert code == 0, lines
    assert len(seen) == 1 and seen[0] is not None and seen[0].withheld is not None
