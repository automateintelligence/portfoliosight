"""The nightly run: a generation is published whole or not at all, and reruns resume."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from portfoliosight.api.hashing import universe_hash
from portfoliosight.api.presets import LOOKBACKS, preset_definitions, preset_funds, tensor_key
from portfoliosight.data import download
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.providers.base import empty_frame
from portfoliosight.engine import ENGINE_VERSION
from portfoliosight.engine.tensor import validate_tensor
from portfoliosight.jobs import nightly
from portfoliosight.jobs.build import BuildRefused

NOW = datetime(2026, 10, 13, 2, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TSP_CORE = ["TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I"]


class _Interrupt(BaseException):
    """The process dying mid-run."""


class _NoData:
    """A provider with nothing: every symbol the store does not already hold stays empty."""

    def __init__(self, name: str, error: Exception | None = None):
        self.name, self.error = name, error
        self.calls: list[str] = []

    def fetch_daily(self, symbol, start, end=None):
        self.calls.append(symbol)
        if self.error is not None:
            raise self.error
        return empty_frame()

    def fetch_meta(self, symbol):
        self.calls.append(symbol)
        if self.error is not None:
            raise self.error
        return None


class _Recording:
    def __init__(self, inner):
        self._inner = inner
        self.puts: list[str] = []
        self.deletes: list[str] = []

    def put(self, key, data):
        self.puts.append(key)
        return self._inner.put(key, data)

    def delete(self, key):
        self.deletes.append(key)
        return self._inner.delete(key)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _FastBuild:
    """Writes a placeholder at the key; can die after n calls or fail chosen lookbacks."""

    def __init__(self, die_after: int | None = None, fail: dict[str, Exception] | None = None):
        self.die_after, self.fail = die_after, fail or {}
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, store, generation, uhash, lookback, funds, **names):
        if self.die_after is not None and len(self.calls) >= self.die_after:
            raise _Interrupt()
        self.calls.append((uhash, lookback, names))
        if lookback in self.fail:
            raise self.fail[lookback]
        store.put(tensor_key(generation, uhash, lookback), b'{"placeholder":true}')


def _providers(tsp_error: Exception | None = None) -> dict:
    return {"tiingo": _NoData("tiingo"), "tsp": _NoData("tsp", tsp_error)}


def _expected_keys(generation: str) -> set[str]:
    return {
        tensor_key(generation, universe_hash(preset_funds(preset)), lookback)
        for preset in preset_definitions()
        for lookback in LOOKBACKS
    }


def _old_generation(store, generation: str, *, complete: bool = True) -> None:
    store_mod.put_json(store, f"meta/{generation}/generation.json", {"generation": generation})
    if complete:
        store_mod.put_json(store, f"meta/{generation}/presets.json", {"generation": generation})
    store.put(f"tensors/{generation}/{'ab' * 8}/5y.json", b"{}")


@pytest.fixture
def unpublished(store, generation, monkeypatch, tmp_path):
    """The fixture store before any generation exists, with a budget that never sleeps."""
    for key in store.list(f"meta/{generation}/") + ["meta/current.json"]:
        store.delete(key)
    monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PS_CACHE_MAX_MB", "300")
    monkeypatch.setenv("PS_PROVIDER_REQ_PER_HOUR", "9000")
    monkeypatch.setenv("PS_PROVIDER_REQ_PER_DAY", "90000")
    monkeypatch.setenv("PS_PROVIDER_SYMBOLS_PER_MONTH", "100000")
    monkeypatch.setenv("PS_GRID_NX", "12")
    monkeypatch.setenv("PS_GRID_NY", "8")
    monkeypatch.setenv("PS_GRID_LEVELS", "3")
    return _Recording(store)


def test_interrupted_run_publishes_nothing_and_the_rerun_resumes(unpublished, generation, d_g):
    store = unpublished
    old, previous = "2026-10-08-0.1.0", "2026-10-09-0.1.0"
    _old_generation(store, old)
    _old_generation(store, previous)
    store_mod.put_json(store, "meta/current.json", {"generation": previous})
    pointer = store.get("meta/current.json")
    store.puts.clear()

    first = _FastBuild(die_after=5)
    with pytest.raises(_Interrupt):
        nightly.run(store=store, now=NOW, providers=_providers(), build_fn=first)
    assert len(first.calls) == 5 and len(store.list(f"tensors/{generation}/")) == 5
    meta = store_mod.get_json(store, f"meta/{generation}/generation.json")
    assert meta["generation"] == generation and meta["asof"] == d_g.isoformat()
    assert meta["engine_version"] == ENGINE_VERSION and meta["bounds_rule"] == "max(0.25, 3/N)"
    assert meta["lookbacks"]["ew"] == {"rows": 1260, "ew_halflife_days": 252}
    assert meta["lookbacks"]["1y"] == {"rows": 252, "ew_halflife_days": None}
    assert meta["created_at"].startswith("2026-10-13T09:00")
    assert not store.exists(f"meta/{generation}/presets.json")
    assert store.get("meta/current.json") == pointer and store.list(f"meta/{old}/")

    second = _FastBuild()
    status = nightly.run(store=store, now=NOW, providers=_providers(), build_fn=second)
    assert len(second.calls) == 7
    assert not {call[:2] for call in second.calls} & {call[:2] for call in first.calls}
    assert set(store.list(f"tensors/{generation}/")) == _expected_keys(generation)
    assert store.puts.count(f"meta/{generation}/generation.json") == 1
    assert store.puts.count(f"meta/{generation}/presets.json") == 1
    for key in _expected_keys(generation):
        assert store.puts.count(key) == 1
    switch = max(i for i, key in enumerate(store.puts) if key == "meta/current.json")
    needed = _expected_keys(generation) | {f"meta/{generation}/presets.json"}
    assert switch > max(i for i, key in enumerate(store.puts) if key in needed)
    assert store_mod.get_json(store, "meta/current.json")["generation"] == generation
    presets = store_mod.get_json(store, f"meta/{generation}/presets.json")
    assert [preset["id"] for preset in presets["presets"]] == ["guide2017", "tsp"]
    assert all(
        entry["status"] == "ready"
        for preset in presets["presets"]
        for entry in preset["lookbacks"].values()
    )
    # The generation before the previous one is gone; the previous one is whole.
    assert store.list(f"meta/{old}/") == [] and store.list(f"tensors/{old}/") == []
    assert len(store.list(f"meta/{previous}/") + store.list(f"tensors/{previous}/")) == 3
    assert store_mod.get_json(store, "meta/previous.json") == {
        "current": generation,
        "previous": previous,
    }
    assert store.puts.index("meta/previous.json") < switch
    assert status["published"] is True and status["pruned"] == [old]
    assert status == store_mod.get_json(store, "meta/status.json")
    assert status["D_G"] == d_g.isoformat() and status["generation"] == generation
    assert status["started"] == "2026-10-13T09:00:00+00:00" and status["finished"] is not None
    assert status["preset_tensors_built"] == {"guide2017": 1, "tsp": 6}
    assert set(status["preset_build_seconds"]) == {"guide2017", "tsp"}
    assert second.calls[-1][2] == {"universe_name": "TSP (G, F, C, S, I)", "preset_id": "tsp"}

    # A third run finds the generation published: no build, nothing under it touched.
    store.puts.clear()
    store.deletes.clear()
    third = _FastBuild()
    again = nightly.run(store=store, now=NOW, providers=_providers(), build_fn=third)
    assert third.calls == [] and again["published"] is True and again["pruned"] == []
    touched = store.puts + store.deletes
    assert not [key for key in touched if generation in key]
    assert "meta/status.json" in store.puts and "meta/manifest.json" in store.puts
    assert store.list(f"meta/{previous}/")


def test_published_run_still_refreshes_the_lower_tiers(unpublished):
    providers = _providers()
    nightly.run(store=unpublished, now=NOW, providers=providers, build_fn=_FastBuild())
    asked = set(providers["tiingo"].calls)
    assert "SGOV" in asked and len(asked) > 100  # tier 2 and the tier 3 slice were walked
    # Tier 1 was current at D_G: no request went out for it.
    assert not asked & {"VTI", "BND"} and not set(providers["tsp"].calls) & set(TSP_CORE)


def test_a_build_that_fails_keeps_the_generation_unpublished_until_it_builds(
    unpublished, generation
):
    store = unpublished
    refusal = BuildRefused("window_unavailable", "the 10y window is unavailable")
    broken = _FastBuild(fail={"10y": refusal, "ew": RuntimeError("solver fault")})
    status = nightly.run(store=store, now=NOW, providers=_providers(), build_fn=broken)
    assert len(broken.calls) == 12  # one failure does not stop the other keys
    assert status["published"] is False and not store.exists("meta/current.json")
    assert not store.exists(f"meta/{generation}/presets.json")
    build_errors = [error for error in status["errors"] if error["step"] == "build"]
    assert [(e["preset"], e["lookback"]) for e in build_errors] == [
        ("guide2017", "10y"),
        ("guide2017", "ew"),
        ("tsp", "10y"),
        ("tsp", "ew"),
    ]
    assert build_errors[0]["error"].startswith("window_unavailable: ")
    assert build_errors[1]["error"] == "build_failed: RuntimeError: solver fault"
    assert {"step": "publish", "error": "not every preset tensor exists; not published"} in (
        status["errors"]
    )
    assert status["preset_tensors_built"] == {"guide2017": 4, "tsp": 4}
    assert status["error_count"] == len(status["errors"])
    fixed = _FastBuild()
    status = nightly.run(store=store, now=NOW, providers=_providers(), build_fn=fixed)
    assert len(fixed.calls) == 4 and status["published"] is True


def test_tsp_fetch_failure_marks_tsp_stale_and_is_not_a_failed_run(unpublished, generation, d_g):
    store = unpublished
    catalog = manifest_mod.load_manifest(store)
    before = pd.Timestamp(d_g)
    for symbol in TSP_CORE:  # one session behind, so the refresh has to ask tsp.gov
        record = store_mod.get_record(store, symbol)
        record = record.loc[record["date"] < before]
        store_mod.put_record(store, symbol, record)
        entry = catalog.symbols[symbol]
        entry.last_date = entry.adjusted_through = record["date"].iloc[-1].date()
    manifest_mod.write_catalog(store, catalog, NOW)
    providers = _providers(tsp_error=RuntimeError("tsp.gov answered 503"))
    status = nightly.run(store=store, now=NOW, providers=providers, build_fn=_FastBuild())
    now = manifest_mod.load_manifest(store).symbols
    assert [now[symbol].status for symbol in TSP_CORE] == ["stale"] * 5
    assert now["VTI"].status == "ok" and now["FIENX"].status == "unavailable"
    tsp_errors = [error for error in status["errors"] if error.get("provider") == "tsp"]
    assert {error["symbol"] for error in tsp_errors} >= set(TSP_CORE)
    assert "tsp.gov answered 503" in tsp_errors[0]["error"]
    listed = {row["id"] for row in store_mod.get_json(store, "meta/symbols.json")["symbols"]}
    assert not listed & set(TSP_CORE) and "VTI" in listed
    assert status["published"] is True
    assert store_mod.get_json(store, "meta/current.json")["generation"] == generation


def test_an_unexpected_failure_is_recorded_and_raised(unpublished, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("store unreachable")

    monkeypatch.setattr(download, "run", broken)
    with pytest.raises(OSError, match="store unreachable"):
        nightly.run(store=unpublished, now=NOW, providers=_providers(), build_fn=_FastBuild())
    status = store_mod.get_json(unpublished, "meta/status.json")
    assert status["finished"] is None and status["published"] is False
    assert status["errors"] == [{"step": "run", "error": "OSError: store unreachable"}]


def test_a_stopped_refresh_is_recorded(unpublished, monkeypatch):
    def stopped(mode, *, report, **kwargs):
        report.stopped = "daily budget spent"
        return 0

    monkeypatch.setattr(download, "run", stopped)
    status = nightly.run(store=unpublished, now=NOW, providers=_providers(), build_fn=_FastBuild())
    assert {"step": "refresh", "error": "daily budget spent"} in status["errors"]


class _FakeClock:
    def __init__(self, start: datetime):
        self.now = start.astimezone(UTC)

    def __call__(self) -> datetime:
        return self.now


class _Ticking(_NoData):
    """Each request takes ten minutes on ``clock``."""

    def __init__(self, name: str, clock: _FakeClock, calls: list[str]):
        super().__init__(name)
        self.clock, self.calls = clock, calls

    def fetch_daily(self, symbol, start, end=None):
        self.clock.now += timedelta(minutes=10)
        return super().fetch_daily(symbol, start, end)


class _BuildUntil(_FastBuild):
    """Builds every tensor; the builds end with ``clock`` at ``until``.

    ``before`` is the requests made before the first build (tier 1's).
    """

    def __init__(self, clock: _FakeClock, until: datetime, calls: list[str]):
        super().__init__()
        self.clock, self.until, self.requests = clock, until.astimezone(UTC), calls
        self.before: list[str] | None = None

    def __call__(self, *args, **kwargs):
        if self.before is None:
            self.before = list(self.requests)
        super().__call__(*args, **kwargs)
        self.clock.now = self.until


LA = ZoneInfo("America/Los_Angeles")


@pytest.mark.parametrize(
    ("walk_starts", "requests"),
    [
        # 01:00, 01:10 and 01:20 start before the 01:30 deadline; 01:30 does not.
        (datetime(2026, 10, 13, 1, 0, tzinfo=LA), 3),
        # The builds ran past the deadline: tiers 2 and 3 wait, publication does not.
        (datetime(2026, 10, 13, 1, 45, tzinfo=LA), 0),
    ],
)
def test_the_lower_tier_walk_stops_at_the_deadline_and_publication_is_untouched(
    unpublished, generation, walk_starts, requests
):
    """A manual run at 00:30 PT: the deadline is 01:30 PT, 30 minutes before the 02:00 start."""
    store = unpublished
    clock = _FakeClock(datetime(2026, 10, 13, 0, 30, tzinfo=LA))
    calls: list[str] = []
    providers = {"tiingo": _Ticking("tiingo", clock, calls), "tsp": _Ticking("tsp", clock, calls)}
    build = _BuildUntil(clock, walk_starts, calls)
    status = nightly.run(
        store=store, now=clock.now, providers=providers, build_fn=build, clock=clock
    )
    assert len(build.calls) == 12 and status["published"] is True
    assert store_mod.get_json(store, "meta/current.json")["generation"] == generation
    # Tier 1 (the TSP L funds the fixture leaves behind) runs to the end, past the deadline.
    assert build.before is not None and len(build.before) == 11
    assert all(symbol.startswith("TSP-L") for symbol in build.before)
    assert len(calls) - len(build.before) == requests
    assert status["deadline"] == "2026-10-13T08:30:00+00:00"
    assert status["stopped"] == download.DEADLINE_REACHED
    assert not [error for error in status["errors"] if "deadline" in json.dumps(error)]
    assert store_mod.get_json(store, "meta/status.json") == status
    assert status["finished"] is not None


def test_only_the_lower_tiers_get_the_deadline(unpublished, monkeypatch):
    seen: list[tuple[tuple[int, ...], datetime | None]] = []
    real = download.run

    def spy(mode, **kwargs):
        seen.append((tuple(kwargs["tiers"]), kwargs.get("deadline")))
        return real(mode, **kwargs)

    monkeypatch.setattr(download, "run", spy)
    status = nightly.run(
        store=unpublished,
        now=NOW,
        providers=_providers(),
        build_fn=_FastBuild(),
        deadline_minutes_before_next=45,
    )
    deadline = datetime(2026, 10, 14, 8, 15, tzinfo=UTC)  # 01:15 PDT the next morning
    assert seen == [((1,), None), ((2, 3), deadline)]
    assert status["deadline"] == deadline.isoformat() and status["stopped"] is None


def test_deadline_minutes_come_from_the_environment(monkeypatch):
    monkeypatch.delenv("PS_NIGHTLY_DEADLINE_MINUTES_BEFORE_NEXT", raising=False)
    assert nightly._deadline_minutes_from_env() == 30
    monkeypatch.setenv("PS_NIGHTLY_DEADLINE_MINUTES_BEFORE_NEXT", " 75 ")
    assert nightly._deadline_minutes_from_env() == 75


def test_now_must_be_timezone_aware(unpublished):
    with pytest.raises(ValueError, match="timezone-aware"):
        nightly.run(store=unpublished, now=datetime(2026, 10, 13, 2, 0), providers=_providers())


def test_generations_are_ordered_by_date_then_version(tmp_path):
    store = store_mod.LocalStore(tmp_path)
    names = ["2026-10-09-0.1.0", "2026-10-12-0.2.0", "2026-10-12-0.10.0", "2026-10-08-0.1.0"]
    for name in names:
        _old_generation(store, name)
    store.put("meta/manifest.json", b"{}")
    store.put("tensors/not-a-generation/x/1y.json", b"{}")
    assert nightly.stored_generations(store) == [
        "2026-10-08-0.1.0",
        "2026-10-09-0.1.0",
        "2026-10-12-0.2.0",
        "2026-10-12-0.10.0",
    ]
    store_mod.put_json(
        store, "meta/previous.json", {"current": "2026-10-12-0.10.0", "previous": names[1]}
    )
    assert nightly.prune_generations(store, "2026-10-12-0.10.0") == [
        "2026-10-08-0.1.0",
        "2026-10-09-0.1.0",
    ]
    assert nightly.stored_generations(store) == ["2026-10-12-0.2.0", "2026-10-12-0.10.0"]
    assert store.exists("meta/manifest.json")
    assert store.exists("tensors/not-a-generation/x/1y.json")


def test_nothing_is_pruned_without_a_record_of_the_previous_generation(tmp_path):
    store = store_mod.LocalStore(tmp_path)
    for name in ("2026-10-08-0.1.0", "2026-10-09-0.1.0", "2026-10-12-0.1.0"):
        _old_generation(store, name)
    current = "2026-10-12-0.1.0"
    assert nightly.previous_generation(store, current) == (False, None)
    assert nightly.prune_generations(store, current) == []
    # A record written for a switch that never happened says nothing about this pointer.
    store_mod.put_json(
        store, "meta/previous.json", {"current": "2026-10-13-0.1.0", "previous": current}
    )
    assert nightly.prune_generations(store, current) == []
    store.put("meta/previous.json", b"[]")
    assert nightly.prune_generations(store, current) == []
    assert len(nightly.stored_generations(store)) == 3
    # The first generation ever has no previous one: everything older is left-over.
    store_mod.put_json(store, "meta/previous.json", {"current": current, "previous": None})
    assert nightly.previous_generation(store, current) == (True, None)
    assert nightly.prune_generations(store, current) == ["2026-10-08-0.1.0", "2026-10-09-0.1.0"]


def test_an_abandoned_generation_is_not_mistaken_for_the_previous_one(unpublished, generation):
    """Published G1, a G2 that died half-built, then G3: visitors hold G1, so G1 is kept."""
    store = unpublished
    g1, g2 = "2026-10-08-0.1.0", "2026-10-09-0.1.0"
    _old_generation(store, g1)
    _old_generation(store, g2, complete=False)
    store_mod.put_json(store, "meta/current.json", {"generation": g1})
    status = nightly.run(store=store, now=NOW, providers=_providers(), build_fn=_FastBuild())
    assert status["published"] is True and status["pruned"] == [g2]
    assert nightly.stored_generations(store) == [g1, generation]
    assert store.exists(f"tensors/{g1}/{'ab' * 8}/5y.json")
    # Later runs of the same day leave the previous generation where it is.
    again = nightly.run(store=store, now=NOW, providers=_providers(), build_fn=_FastBuild())
    assert again["pruned"] == [] and nightly.stored_generations(store) == [g1, generation]


def test_first_publication_has_no_previous_generation(unpublished, generation):
    nightly.run(store=unpublished, now=NOW, providers=_providers(), build_fn=_FastBuild())
    assert store_mod.get_json(unpublished, "meta/previous.json") == {
        "current": generation,
        "previous": None,
    }


def test_entry_point_logs_a_failed_run_redacted_and_exits_1(
    unpublished, monkeypatch, caplog, capsys
):
    monkeypatch.setenv("PS_STORE", "local")
    monkeypatch.setenv("PS_LOCAL_STORE_DIR", str(unpublished.root))
    monkeypatch.setenv("PS_NIGHTLY_PROVIDERS", "fixture")
    monkeypatch.setenv("PS_FIXTURE_DIR", str(FIXTURES))
    monkeypatch.setenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "r2-secret-value-0123456789")

    def broken(*args, **kwargs):
        raise OSError("request signed with r2-secret-value-0123456789 was refused")

    monkeypatch.setattr(download, "run", broken)
    with caplog.at_level("ERROR"):
        assert nightly.main() == 1
    printed = capsys.readouterr()
    logged = caplog.text + printed.err + printed.out
    assert "nightly failed" in logged and "Traceback" in logged and "[redacted]" in logged
    assert "r2-secret-value-0123456789" not in logged
    stored = unpublished.get("meta/status.json").decode()
    assert "r2-secret-value-0123456789" not in stored and "[redacted]" in stored


def test_entry_point_publishes_real_tensors_offline(unpublished, generation, monkeypatch):
    """The local container run in process: fixture providers, a fixed clock, the real builder."""
    monkeypatch.setenv("PS_STORE", "local")
    monkeypatch.setenv("PS_LOCAL_STORE_DIR", str(unpublished.root))
    monkeypatch.setenv("PS_NIGHTLY_PROVIDERS", "fixture")
    monkeypatch.setenv("PS_FIXTURE_DIR", str(FIXTURES))
    monkeypatch.setenv("PS_FIXED_NOW", "2026-10-13T02:00:00-07:00")
    monkeypatch.setenv("PS_CACHE_MAX_MB", "0.2")
    assert nightly.main() == 0
    store = unpublished
    assert store_mod.get_json(store, "meta/current.json")["generation"] == generation
    assert generation == f"2026-10-12-{ENGINE_VERSION}"
    for key in _expected_keys(generation):
        tensor = json.loads(store.get(key))
        validate_tensor(tensor)
        assert tensor["generation"] == generation and tensor["asof"] == "2026-10-12"
    guide = json.loads(store.get(sorted(k for k in _expected_keys(generation) if "/5y" in k)[0]))
    names = {guide["universe"]["name"], guide["universe"]["preset_id"]}
    assert names <= {"Example Portfolio", "guide2017", "TSP (G, F, C, S, I)", "tsp"}
    # a preset that comes with an allocation has it built in as the entered mix, in every view
    presets = {preset.id: preset for preset in preset_definitions()}
    for key in _expected_keys(generation):
        tensor = json.loads(store.get(key))
        held = presets[tensor["universe"]["preset_id"]].allocation
        if held is None:
            assert tensor["entered"] is None and tensor["universe"]["preset_id"] == "tsp"
            continue
        ids = [fund["id"] for fund in tensor["universe"]["funds"]]
        total = sum(held[fund] for fund in ids)
        expected = [held[fund] / total for fund in ids]
        assert tensor["entered"]["w"] == pytest.approx(expected, abs=1e-15)
        assert tensor["entered"]["set_aside"] == pytest.approx(1.0 - total / sum(held.values()))
        spread = tensor["entered"]["range"]
        assert spread["bad"] < spread["typical"] < spread["good"]
    status = store_mod.get_json(store, "meta/status.json")
    assert status["published"] is True and status["finished"]
    assert status["preset_tensors_built"] == {"guide2017": 6, "tsp": 6}
    # The recorded tsp.gov slice ends in March: the L funds it adds are behind, not a failure.
    catalog = manifest_mod.load_manifest(store).symbols
    assert catalog["TSP-L2030"].status == "stale" and catalog["TSP-G"].status == "ok"
    cached = [p for p in Path(unpublished.root.parent / "cache").rglob("*") if p.is_file()]
    assert sum(p.stat().st_size for p in cached) <= 200_000
    assert nightly.main() == 0  # already published


@pytest.mark.parametrize(
    "env",
    [
        {"PS_STORE": "local", "PS_LOCAL_STORE_DIR": ""},
        {"PS_NIGHTLY_PROVIDERS": "replay"},
        {"PS_NIGHTLY_PROVIDERS": "fixture", "PS_FIXTURE_DIR": "/nonexistent/fixtures"},
        {"PS_FIXED_NOW": "2026-10-13T02:00:00"},
        {"PS_FIXED_NOW": "tomorrow"},
        {"PS_NIGHTLY_DEADLINE_MINUTES_BEFORE_NEXT": "soon"},
        {"PS_NIGHTLY_DEADLINE_MINUTES_BEFORE_NEXT": "1440"},
        {"PS_NIGHTLY_DEADLINE_MINUTES_BEFORE_NEXT": "-5"},
    ],
)
def test_entry_point_refuses_a_bad_environment(unpublished, monkeypatch, capsys, env):
    monkeypatch.setenv("PS_STORE", "local")
    monkeypatch.setenv("PS_LOCAL_STORE_DIR", str(unpublished.root))
    monkeypatch.setenv("PS_NIGHTLY_PROVIDERS", "fixture")
    monkeypatch.setenv("PS_FIXTURE_DIR", str(FIXTURES))
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert nightly.main() == 2
    assert "nightly not run" in capsys.readouterr().err
    assert not unpublished.exists("meta/status.json")


def test_entry_point_uses_the_real_providers_by_default(unpublished, monkeypatch):
    monkeypatch.delenv("PS_NIGHTLY_PROVIDERS", raising=False)
    monkeypatch.delenv("PS_FIXED_NOW", raising=False)
    monkeypatch.setenv("TIINGO_API_KEY", "unit-test-not-a-key")
    providers = nightly._providers_from_env()
    assert providers["tiingo"].name == "tiingo" and providers["tsp"].name == "tsp"
    assert nightly._now_from_env().tzinfo is not None
    monkeypatch.delenv("TIINGO_API_KEY")
    monkeypatch.setenv("PS_STORE", "local")
    monkeypatch.setenv("PS_LOCAL_STORE_DIR", str(unpublished.root))
    assert nightly.main() == 2
