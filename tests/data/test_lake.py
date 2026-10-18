"""The lake as a source: its status rule, its overlay, and the provider walk that skips it."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from portfoliosight.data import download, refresh
from portfoliosight.data import lake as lake_mod
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.calendar import session_back
from portfoliosight.data.store import LocalStore, R2Store
from portfoliosight.data.universe import Tiers, parse_universe_lines
from tests.data.test_download import RECORD_START, Clock, FakeProvider, _put_record

D = date(2026, 3, 9)  # a Monday: D-3 sessions is Wednesday 2026-03-04


def _lake_entry(symbol: str = "AAPL", last: date = D, **over) -> lake_mod.LakeEntry:
    fields = {
        "name": symbol,
        "kind": "stock",
        "tier": 3,
        "source": "lake",
        "first_date": RECORD_START,
        "last_date": last,
        "adjusted_through": last,
        "status": "ok",
        "fetched_at": "2026-03-09T15:00:00+00:00",
        "relies_on_yfinance": True,
        "digest": "d" * 64,
    }
    fields.update(over)
    return lake_mod.LakeEntry(**fields)


@pytest.mark.parametrize(
    ("back", "expected"), [(0, "ok"), (3, "ok"), (4, "stale")], ids=["current", "edge", "behind"]
)
def test_a_lake_entry_follows_the_provider_date_rule(back, expected):
    day = session_back(D, back) if back else D
    entry = _lake_entry(last=day)
    assert manifest_mod.status_for(entry, D) == expected


def test_a_lake_entry_without_dates_is_unavailable():
    entry = _lake_entry(last_date=None, adjusted_through=None)
    assert manifest_mod.status_for(entry, D) == "unavailable"


def test_apply_lake_replaces_restatuses_and_releases():
    manifest = manifest_mod.Manifest(
        symbols={
            "AAPL": manifest_mod.ManifestEntry(
                name="AAPL", kind="stock", tier=3, source="seed", status="pending"
            ),
            "MSFT": manifest_mod.ManifestEntry(
                name="MSFT",
                kind="stock",
                tier=3,
                source="lake",
                last_date=D,
                adjusted_through=D,
                status="ok",
                relies_on_yfinance=True,
            ),
        }
    )
    behind = session_back(D, 4)
    overlay = lake_mod.LakeOverlay(
        generated_at="2026-03-09T13:50:00+00:00",
        symbols={"AAPL": _lake_entry(), "XOM": _lake_entry("XOM", behind, status="ok")},
    )
    released = lake_mod.apply_lake(manifest, overlay, D)
    assert released == ["MSFT"]
    assert manifest.symbols["AAPL"].source == "lake" and manifest.symbols["AAPL"].status == "ok"
    assert manifest.symbols["AAPL"].relies_on_yfinance is True
    assert "digest" not in manifest.to_json()["symbols"]["AAPL"]
    # The overlay's own status is recomputed against D_G.
    assert manifest.symbols["XOM"].status == "stale"
    msft = manifest.symbols["MSFT"]
    assert (msft.source, msft.status) == ("seed", "pending")
    assert msft.reason == f"corporate actions not yet verified after {D.isoformat()}"
    assert msft.relies_on_yfinance is True  # its record still holds the lake's history


def test_plan_refresh_leaves_lake_symbols_out():
    d_g = date(2026, 3, 13)
    behind = date(2026, 3, 2)
    entries = {
        "LAKE": {"source": "lake", "last_date": behind, "adjusted_through": behind},
        "SEED": {"source": "seed", "last_date": behind, "adjusted_through": behind},
    }
    assert refresh.plan_refresh(entries, ["LAKE", "SEED"], d_g) == [("SEED", date(2026, 2, 23))]


FEB27 = date(2026, 2, 27)


def test_the_provider_walk_spends_nothing_on_lake_symbols_and_keeps_their_entries(tmp_path):
    store = LocalStore(tmp_path / "store")
    behind = date(2026, 2, 20)
    for symbol in ("LAKE", "TIIN"):
        _put_record(store, symbol, behind, behind)
    base = {
        symbol: {
            "name": f"{symbol} Corp",  # named: no meta request
            "kind": "stock",
            "tier": 3,
            "income": False,
            "source": "seed+tiingo",
            "first_date": RECORD_START.isoformat(),
            "last_date": behind.isoformat(),
            "adjusted_through": behind.isoformat(),
            "status": "stale",
            "reason": None,
            "fetched_at": "2026-02-21T10:00:00+00:00",
        }
        for symbol in ("LAKE", "TIIN")
    }
    store_mod.put_json(store, manifest_mod.MANIFEST_KEY, {"symbols": base})
    overlay = lake_mod.LakeOverlay(symbols={"LAKE": _lake_entry("LAKE", date(2026, 2, 26))})
    store_mod.put_json(store, lake_mod.LAKE_KEY, overlay.to_json())

    provider = FakeProvider(default_available=FEB27)
    clock = Clock(FEB27, 13)
    code = download.run(
        "refresh",
        store=store,
        providers={"tiingo": provider},
        clock=clock,
        sleep=clock.sleep,
        symbols=["LAKE", "TIIN"],
    )
    assert code == 0
    assert [call[1] for call in provider.calls] == ["TIIN"]
    entries = store_mod.get_json(store, manifest_mod.MANIFEST_KEY)["symbols"]
    assert entries["LAKE"]["source"] == "lake" and entries["LAKE"]["status"] == "ok"
    assert entries["TIIN"]["status"] == "ok"
    listed = {
        row["id"]: row["kind"]
        for row in store_mod.get_json(store, manifest_mod.SYMBOLS_KEY)["symbols"]
    }
    assert listed == {"LAKE": "stock", "TIIN": "stock"}


def test_a_catalog_write_carries_an_entry_the_sync_took_during_the_walk(tmp_path):
    """The walk loaded the overlay before the sync wrote; its catalog write still carries it."""
    store = LocalStore(tmp_path / "store")
    store_mod.put_json(store, manifest_mod.MANIFEST_KEY, {"symbols": {}})

    class Provider(FakeProvider):
        def fetch_daily(self, symbol, start, end=None):
            # The sync runs while the walk fetches.
            overlay = lake_mod.LakeOverlay(symbols={"AAPL": _lake_entry("AAPL", FEB27)})
            store_mod.put_json(store, lake_mod.LAKE_KEY, overlay.to_json())
            return super().fetch_daily(symbol, start, end)

    provider = Provider(default_available=FEB27)
    clock = Clock(FEB27, 13)
    download.run(
        "catch-up",
        store=store,
        providers={"tiingo": provider},
        clock=clock,
        sleep=clock.sleep,
        symbols=["NEWF"],
    )
    entries = store_mod.get_json(store, manifest_mod.MANIFEST_KEY)["symbols"]
    assert entries["AAPL"]["source"] == "lake" and "NEWF" in entries


def test_update_json_rereads_when_another_writer_got_in_first(tmp_path):
    store = LocalStore(tmp_path)
    key = "meta/manifest.json"
    store_mod.put_json(store, key, {"symbols": {"A": 1}})
    seen: list[dict] = []

    def change(document):
        seen.append(dict(document["symbols"]))
        if len(seen) == 1:  # a blind write lands between this read and its write
            store_mod.put_json(store, key, {"symbols": {"A": 1, "NIGHTLY": 2}})
        return {"symbols": {**document["symbols"], "LAKE": 3}}

    store_mod.update_json(store, key, change)
    assert seen == [{"A": 1}, {"A": 1, "NIGHTLY": 2}]
    assert store_mod.get_json(store, key) == {"symbols": {"A": 1, "NIGHTLY": 2, "LAKE": 3}}


def test_update_json_gives_up_after_repeated_conflicts(tmp_path):
    store = LocalStore(tmp_path)
    key = "meta/x.json"
    counter = iter(range(100))

    def change(document):
        store_mod.put_json(store, key, {"n": next(counter)})
        return {"mine": True}

    with pytest.raises(store_mod.ConcurrentUpdate):
        store_mod.update_json(store, key, change, attempts=3)


def test_update_json_creates_an_absent_key_only_if_still_absent(tmp_path):
    store = LocalStore(tmp_path)
    assert store_mod.update_json(store, "meta/new.json", lambda doc: {"was": doc}) == {"was": None}
    assert not store.put_if("meta/new.json", b"{}", None)


class _Client:
    def __init__(self, refuse: int | None = None):
        self.refuse = refuse
        self.calls: list[dict] = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.refuse:
            code = "PreconditionFailed" if self.refuse == 412 else "ConditionalRequestConflict"
            raise ClientError(
                {
                    "Error": {"Code": code},
                    "ResponseMetadata": {"HTTPStatusCode": self.refuse},
                },
                "PutObject",
            )

    def get_object(self, **kwargs):
        return {"Body": SimpleNamespace(read=lambda: b"{}"), "ETag": '"abc"'}


@pytest.mark.parametrize("status", [412, 409])
def test_r2_conditional_put_reports_a_refusal(status):
    client = _Client(refuse=status)
    assert R2Store("b", client).put_if("meta/manifest.json", b"{}", '"abc"') is False
    assert client.calls[0]["IfMatch"] == '"abc"'


def test_r2_conditional_put_of_an_absent_key_uses_if_none_match():
    client = _Client()
    store = R2Store("b", client)
    assert store.put_if("meta/lake.json", b"{}", None) is True
    assert client.calls[0]["IfNoneMatch"] == "*" and "IfMatch" not in client.calls[0]
    assert store.get_tagged("meta/lake.json") == (b"{}", '"abc"')


def test_overlay_round_trips_through_the_store(tmp_path):
    store = LocalStore(tmp_path)
    assert lake_mod.load_lake(store) == lake_mod.LakeOverlay()
    overlay = lake_mod.LakeOverlay(
        generated_at="2026-10-14T13:50:00+00:00",
        synced_at=datetime.combine(D, time(15), tzinfo=UTC).isoformat(),
        symbols={"AAPL": _lake_entry()},
    )
    store_mod.put_json(store, lake_mod.LAKE_KEY, overlay.to_json())
    assert lake_mod.load_lake(store) == overlay
    assert json.loads(store.get(lake_mod.LAKE_KEY))["symbols"]["AAPL"]["digest"] == "d" * 64


def _stale_entries(symbols, behind: date) -> dict[str, dict]:
    return {
        symbol: {
            "name": symbol,
            "kind": "stock",
            "tier": 3,
            "income": False,
            "source": "seed+tiingo",
            "first_date": RECORD_START.isoformat(),
            "last_date": behind.isoformat(),
            "adjusted_through": behind.isoformat(),
            "status": "stale",
            "reason": None,
            "fetched_at": "2026-02-21T10:00:00+00:00",
        }
        for symbol in symbols
    }


def test_a_symbol_the_sync_takes_mid_walk_is_neither_fetched_nor_written_over(tmp_path):
    """The sync takes LAKE while the walk fetches FIRST, and SAME while the walk fetches SAME."""
    store = LocalStore(tmp_path / "store")
    behind = date(2026, 2, 20)
    for symbol in ("FIRST", "LAKE", "SAME"):
        _put_record(store, symbol, behind, behind)
    store_mod.put_json(
        store,
        manifest_mod.MANIFEST_KEY,
        {"symbols": _stale_entries(["FIRST", "LAKE", "SAME"], behind)},
    )
    lake_record = b"the lake's record"

    class Provider(FakeProvider):
        def fetch_daily(self, symbol, start, end=None):
            taken = {"FIRST": "LAKE", "SAME": "SAME"}.get(symbol)
            if taken is not None:  # the sync stores the record, then its overlay
                store.put(store_mod.record_key(taken), lake_record)
                overlay = lake_mod.load_lake(store)
                overlay.symbols[taken] = _lake_entry(taken, date(2026, 2, 26))
                store_mod.put_json(store, lake_mod.LAKE_KEY, overlay.to_json())
            return super().fetch_daily(symbol, start, end)

    provider = Provider(default_available=FEB27)
    clock = Clock(FEB27, 13)
    code = download.run(
        "refresh",
        store=store,
        providers={"tiingo": provider},
        clock=clock,
        sleep=clock.sleep,
        symbols=["FIRST", "LAKE", "SAME"],
    )
    assert code == 0
    # LAKE never fetched; FIRST, which has no name, also gets its meta request, SAME does not.
    assert provider.calls == [
        ("daily", "FIRST", date(2026, 2, 13)),
        ("meta", "FIRST", None),
        ("daily", "SAME", date(2026, 2, 13)),
    ]
    assert store.get("prices/LAKE.parquet") == lake_record
    assert store.get("prices/SAME.parquet") == lake_record  # the fetched tail was not written
    entries = store_mod.get_json(store, manifest_mod.MANIFEST_KEY)["symbols"]
    assert entries["LAKE"]["source"] == entries["SAME"]["source"] == "lake"
    assert entries["FIRST"]["status"] == "ok"


def test_a_missing_record_whose_refetch_cannot_be_stored_keeps_its_entry(tmp_path):
    store = LocalStore(tmp_path / "store")
    behind = date(2026, 2, 20)
    store_mod.put_json(
        store, manifest_mod.MANIFEST_KEY, {"symbols": _stale_entries(["GONE"], behind)}
    )

    class Refusing(LocalStore):
        def put(self, key: str, data: bytes) -> None:
            if key.startswith("prices/"):
                raise OSError("disk full")
            super().put(key, data)

    refusing = Refusing(store.root)
    provider = FakeProvider(default_available=FEB27)
    clock = Clock(FEB27, 13)
    report = download.RunReport()
    download.run(
        "refresh",
        store=refusing,
        providers={"tiingo": provider},
        clock=clock,
        sleep=clock.sleep,
        symbols=["GONE"],
        report=report,
    )
    assert report.exit_code == 1 and report.errors[0]["provider"] == "store"
    entry = store_mod.get_json(store, manifest_mod.MANIFEST_KEY)["symbols"]["GONE"]
    assert entry["last_date"] == entry["adjusted_through"] == behind.isoformat()


def _write_fundamentals(lake, files: dict[str, str]) -> None:
    folder = lake / lake_mod.FUNDAMENTALS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    for symbol, text in files.items():
        (folder / f"{symbol}.json").write_text(text)


def test_lake_names_read_general_name_then_the_symbol_list(tmp_path):
    lake = tmp_path / "lake"
    _write_fundamentals(
        lake,
        {
            "AAPL": json.dumps({"General": {"Code": "AAPL", "Name": "  Apple Inc. "}}),
            "EMPTY": "",
            "BROKEN": '{"General": {"Name": "Cut',
            "STATIC": json.dumps({"static": {"sector": "Utilities"}}),
            "NONAME": json.dumps({"General": {"Code": "NONAME", "Name": "   "}}),
            "LISTED": json.dumps({"General": {"Code": "LISTED"}}),
            "TICK": json.dumps({"General": {"Name": "TICK"}}),
            "LIST": json.dumps([1, 2]),
        },
    )
    (lake / "symbols").mkdir()
    (lake / lake_mod.LISTING_FILE).write_text(
        "Code,Name,Country,Exchange,Currency,Type,Isin\n"
        "LISTED,Listed Holdings Corp,USA,NYSE,USD,Common Stock,US0000000001\n"
        "STATIC,IDACORP Inc,USA,NYSE,USD,Common Stock,US4511071064\n"
        "AAPL,Apple Inc,USA,NASDAQ,USD,Common Stock,US0378331005\n"
        "TWICE,Twice Fund A,USA,PINK,USD,FUND,\n"
        "TWICE,Twice Fund B,USA,NYSE,USD,ETF,\n"
        "ONLY,Only Listed ETF,USA,NYSE ARCA,USD,ETF,\n"
    )
    names = lake_mod.LakeNames(lake)
    assert names.name("AAPL") == "Apple Inc."  # the fundamentals file wins, issuer's case kept
    assert names.name("STATIC") == "IDACORP Inc"  # no General: the symbol list
    assert names.name("LISTED") == "Listed Holdings Corp"  # General without Name
    assert names.name("ONLY") == "Only Listed ETF"  # no fundamentals file
    for symbol in ("EMPTY", "BROKEN", "NONAME", "TICK", "LIST", "TWICE", "MISSING"):
        assert names.name(symbol) is None, symbol  # nothing usable, or a code listed twice


def test_lake_names_without_a_symbol_list_use_the_fundamentals_only(tmp_path):
    lake = tmp_path / "lake"
    _write_fundamentals(lake, {"C": json.dumps({"General": {"Name": "Citigroup Inc."}})})
    names = lake_mod.LakeNames(lake)
    assert names.listing == {}
    assert names.name("C") == "Citigroup Inc." and names.name("AAPL") is None


def test_the_default_walk_spends_nothing_on_the_added_stocks_the_lake_keeps(tmp_path, monkeypatch):
    """The QSE PortfolioSight list is in tier 3, so the nightly's own universe walk reaches it;
    a stock the lake keeps costs no request there, and one it does not keep is fetched."""
    behind = date(2026, 2, 20)
    path = Path(__file__).resolve().parents[2] / "data" / "universes" / "qse_portfoliosight.txt"
    added = [s for s, _ in parse_universe_lines(path.read_text(encoding="utf-8"))]
    kept, unvouched = added[:2], added[2]
    store = LocalStore(tmp_path / "store")
    entries = {}
    for symbol in (*kept, unvouched):
        _put_record(store, symbol, behind, behind)
        entries[symbol] = {
            "name": f"{symbol} Corp",
            "kind": "stock",
            "tier": 3,
            "income": False,
            "source": "seed",
            "first_date": RECORD_START.isoformat(),
            "last_date": behind.isoformat(),
            "adjusted_through": behind.isoformat(),
            "status": "pending",
            "reason": None,
            "fetched_at": None,
        }
    store_mod.put_json(store, manifest_mod.MANIFEST_KEY, {"symbols": entries})
    overlay = lake_mod.LakeOverlay(
        symbols={symbol: _lake_entry(symbol, date(2026, 2, 26)) for symbol in kept}
    )
    store_mod.put_json(store, lake_mod.LAKE_KEY, overlay.to_json())
    only_added = Tiers(
        tier1=(), tier2=(), tier3=tuple(added[:3]), income=frozenset(), starter_slice=130
    )
    monkeypatch.setattr(download, "load_tiers", lambda: only_added)

    provider = FakeProvider(default_available=FEB27)
    clock = Clock(FEB27, 13)
    code = download.run(
        "refresh",
        store=store,
        providers={"tiingo": provider},
        clock=clock,
        sleep=clock.sleep,
        tiers=(3,),
    )
    assert code == 0
    assert [call[1] for call in provider.calls] == [unvouched]
    now = store_mod.get_json(store, manifest_mod.MANIFEST_KEY)["symbols"]
    assert {s: now[s]["source"] for s in kept} == dict.fromkeys(kept, "lake")
