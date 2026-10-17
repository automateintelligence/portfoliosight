"""The build queue: one worker, one job per key, three attempts, no rebuild of a ready key."""

from __future__ import annotations

import json
import threading
import time

import pytest

from portfoliosight.api.hashing import universe_hash
from portfoliosight.api.presets import tensor_key, tensor_url
from portfoliosight.api.queue import MAX_ATTEMPTS, BuildQueue, QueueBusy, build_job
from portfoliosight.jobs.build import BuildRefused, GenerationGone

G = "2026-10-12-0.1.0"
FUNDS = [{"id": "VTI", "min": None, "max": None}, {"id": "BND", "min": None, "max": None}]
H = universe_hash(FUNDS)


def _hash(n: int) -> str:
    return f"{n:016x}"


def _wait(predicate, what: str, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail(f"timed out waiting for {what}")


class _Builder:
    """A build_fn that writes the key; it can hold, raise or write nothing per hash."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.raises: dict[str, BaseException] = {}
        self.silent: set[str] = set()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def __call__(self, store, generation, uhash, lookback, funds):
        self.calls.append((generation, uhash, lookback))
        self.entered.set()
        self.release.wait(timeout=10)
        if uhash in self.raises:
            raise self.raises[uhash]
        if uhash not in self.silent:
            store.put(tensor_key(generation, uhash, lookback), b"{}")


@pytest.fixture
def builder() -> _Builder:
    return _Builder()


@pytest.fixture
def make_queue(store, builder):
    queues: list[BuildQueue] = []

    def _make(**kwargs) -> BuildQueue:
        queue = BuildQueue(builder, store, **kwargs)
        queues.append(queue)
        return queue

    yield _make
    builder.release.set()
    for queue in queues:
        queue.close()


def test_job_runs_from_queued_to_ready(store, builder, make_queue):
    builder.release.clear()
    queue = make_queue()
    first = queue.submit(G, H, "1y", FUNDS)
    assert first.status in ("queued", "building") and first.generation == G and first.hash == H
    assert isinstance(first.position, int) and isinstance(first.eta_s, int) and first.eta_s > 0
    _wait(builder.entered.is_set, "the worker to start the build")
    building = queue.state(G, H, "1y")
    assert building is not None and building.status == "building" and building.position == 0
    assert queue.building is True and queue.depth == 0
    again = queue.submit(G, H, "1y", FUNDS)
    assert again.status == "building" and len(builder.calls) == 1
    builder.release.set()
    _wait(lambda: queue.state(G, H, "1y") is None, "the job to finish")
    assert store.exists(tensor_key(G, H, "1y")) and queue.building is False
    ready = queue.submit(G, H, "1y", FUNDS)
    assert ready.status == "ready" and ready.url == tensor_url(G, H, "1y")
    assert ready.url == f"/api/tensors/{G}/{H}/1y"
    assert builder.calls == [(G, H, "1y")]


def test_a_key_already_in_the_store_is_ready_without_a_job(store, builder, make_queue):
    store.put(tensor_key(G, H, "5y"), b"{}")
    queue = make_queue()
    assert queue.submit(G, H, "5y", FUNDS).status == "ready"
    assert queue.depth == 0 and builder.calls == []


def test_paused_queue_keeps_jobs_in_order_and_refuses_the_twenty_first(builder, make_queue):
    queue = make_queue(start_worker=False)
    positions = [queue.submit(G, _hash(n), "1y", FUNDS).position for n in range(20)]
    assert positions == list(range(1, 21)) and queue.depth == 20 and queue.building is False
    duplicate = queue.submit(G, _hash(3), "1y", FUNDS)
    assert duplicate.status == "queued" and duplicate.position == 4 and queue.depth == 20
    with pytest.raises(QueueBusy):
        queue.submit(G, _hash(99), "1y", FUNDS)
    assert queue.state(G, _hash(99), "1y") is None and queue.depth == 20
    later = queue.state(G, _hash(19), "1y")
    earlier = queue.state(G, _hash(0), "1y")
    assert later is not None and earlier is not None and later.eta_s > earlier.eta_s
    assert builder.calls == []
    queue.resume()
    _wait(lambda: queue.depth == 0 and not queue.building, "the queue to drain")
    assert [call[1] for call in builder.calls] == [_hash(n) for n in range(20)]


def test_pause_lets_the_running_build_finish_and_holds_the_rest(builder, make_queue):
    builder.release.clear()
    queue = make_queue()
    queue.submit(G, _hash(1), "1y", FUNDS)
    _wait(builder.entered.is_set, "the first build")
    queue.pause()
    queue.submit(G, _hash(2), "1y", FUNDS)
    builder.release.set()
    _wait(lambda: not queue.building, "the first build to finish")
    time.sleep(0.05)
    assert queue.depth == 1 and len(builder.calls) == 1
    queue.resume()
    _wait(lambda: queue.depth == 0 and not queue.building, "the second build")
    assert len(builder.calls) == 2


def test_a_failing_job_is_retried_on_request_up_to_three_attempts(builder, make_queue):
    builder.raises[H] = RuntimeError("solver exploded with secret-looking text")
    queue = make_queue()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        queue.submit(G, H, "1y", FUNDS)
        _wait(
            lambda attempt=attempt: (
                (state := queue.state(G, H, "1y")) is not None
                and state.status == "failed"
                and state.attempts == attempt
            ),
            f"failure {attempt}",
        )
        state = queue.state(G, H, "1y")
        assert state is not None and state.error == "build_failed" and state.details is None
        assert state.retry is (attempt < MAX_ATTEMPTS)
        assert len(builder.calls) == attempt
    final = queue.submit(G, H, "1y", FUNDS)
    assert final.status == "failed" and final.attempts == 3 and final.retry is False
    time.sleep(0.05)
    assert len(builder.calls) == 3 and queue.depth == 0


def test_a_retry_succeeds_when_the_fault_clears(store, builder, make_queue):
    builder.raises[H] = RuntimeError("transient")
    queue = make_queue()
    queue.submit(G, H, "1y", FUNDS)
    _wait(lambda: getattr(queue.state(G, H, "1y"), "status", "") == "failed", "the failure")
    del builder.raises[H]
    assert queue.submit(G, H, "1y", FUNDS).status in ("queued", "building")
    _wait(lambda: store.exists(tensor_key(G, H, "1y")), "the retry to write the tensor")
    _wait(lambda: queue.state(G, H, "1y") is None, "the job to leave the table")
    assert queue.submit(G, H, "1y", FUNDS).status == "ready"


@pytest.mark.parametrize(
    ("raised", "code", "details"),
    [
        (GenerationGone(G), "generation_gone", None),
        (
            BuildRefused("window_unavailable", "too short", {"lookback": "1y", "rows": 3}),
            "window_unavailable",
            {"lookback": "1y", "rows": 3},
        ),
    ],
)
def test_a_refused_build_fails_once_and_is_never_retried(
    builder, make_queue, raised, code, details
):
    builder.raises[H] = raised
    queue = make_queue()
    queue.submit(G, H, "1y", FUNDS)
    _wait(lambda: getattr(queue.state(G, H, "1y"), "status", "") == "failed", "the failure")
    state = queue.submit(G, H, "1y", FUNDS)
    assert (state.status, state.error, state.attempts, state.retry) == ("failed", code, 1, False)
    assert state.details == details
    time.sleep(0.05)
    assert len(builder.calls) == 1


def test_the_worker_survives_a_build_that_exits(builder, make_queue):
    builder.raises[H] = SystemExit(3)
    queue = make_queue()
    queue.submit(G, H, "1y", FUNDS)
    _wait(lambda: getattr(queue.state(G, H, "1y"), "status", "") == "failed", "the failure")
    assert queue.building is False
    queue.submit(G, _hash(7), "1y", FUNDS)
    _wait(lambda: len(builder.calls) == 2 and not queue.building, "the next job to be built")


def test_a_build_that_writes_nothing_is_a_failure(builder, make_queue):
    builder.silent.add(H)
    queue = make_queue()
    queue.submit(G, H, "1y", FUNDS)
    _wait(lambda: getattr(queue.state(G, H, "1y"), "status", "") == "failed", "the failure")
    state = queue.state(G, H, "1y")
    assert state is not None and state.error == "build_failed" and state.retry is True


def test_a_failed_job_is_not_requeued_into_a_full_queue(builder, make_queue):
    builder.raises[H] = RuntimeError("fault")
    queue = make_queue()
    queue.submit(G, H, "1y", FUNDS)
    _wait(lambda: getattr(queue.state(G, H, "1y"), "status", "") == "failed", "the failure")
    queue.pause()
    for n in range(20):
        queue.submit(G, _hash(n), "1y", FUNDS)
    with pytest.raises(QueueBusy):
        queue.submit(G, H, "1y", FUNDS)
    state = queue.state(G, H, "1y")
    assert state is not None and state.status == "failed" and state.attempts == 1


def test_old_failures_are_forgotten_beyond_the_cap(builder, make_queue):
    queue = make_queue(max_failed=3)
    for n in range(5):
        builder.raises[_hash(n)] = RuntimeError("fault")
        queue.submit(G, _hash(n), "1y", FUNDS)
    _wait(lambda: queue.depth == 0 and not queue.building, "the queue to drain")
    kept = [n for n in range(5) if queue.state(G, _hash(n), "1y") is not None]
    assert kept == [2, 3, 4]


def test_default_build_job_writes_once_and_never_again(store, generation, api_env):
    funds = [{"id": fund, "min": None, "max": None} for fund in ("VTI", "BND", "VNQ")]
    uhash = universe_hash(funds)
    key = tensor_key(generation, uhash, "1y")
    build_job(store, generation, uhash, "1y", funds)
    stored = store.get(key)
    assert b'"hash":"' + uhash.encode() in stored
    puts: list[str] = []
    real_put = store.put
    store.put = lambda k, data: (puts.append(k), real_put(k, data))[1]
    build_job(store, generation, uhash, "1y", funds)
    assert puts == [] and store.get(key) == stored


def test_default_build_job_refuses_a_hash_that_is_not_the_menu_s(store, generation, api_env):
    funds = [{"id": fund, "min": None, "max": None} for fund in ("VTI", "BND")]
    with pytest.raises(ValueError, match="hash"):
        build_job(store, generation, "0" * 16, "1y", funds)
    assert store.list("tensors/") == []


def test_default_build_job_keeps_the_cache_under_its_cap(
    store, generation, api_env, monkeypatch, tmp_path
):
    monkeypatch.setenv("PS_CACHE_MAX_MB", "0.05")
    funds = [{"id": fund, "min": None, "max": None} for fund in ("VTI", "BND", "VNQ")]
    build_job(store, generation, universe_hash(funds), "1y", funds)
    cached = [path for path in (tmp_path / "cache").rglob("*") if path.is_file()]
    assert sum(path.stat().st_size for path in cached) <= 50_000


def test_default_build_job_keeps_a_tensor_another_builder_wrote_first(
    store, generation, api_env, monkeypatch
):
    funds = [{"id": fund, "min": None, "max": None} for fund in ("VTI", "BND", "VNQ")]
    uhash = universe_hash(funds)
    key = tensor_key(generation, uhash, "1y")
    from portfoliosight.api import queue as queue_mod

    real_build = queue_mod.build_from_store

    def build_while_another_writes(store_, **kwargs):
        tensor = real_build(store_, **kwargs)
        store_.put(key, b'{"first":true}')
        return tensor

    monkeypatch.setattr(queue_mod, "build_from_store", build_while_another_writes)
    build_job(store, generation, uhash, "1y", funds)
    assert store.get(key) == b'{"first":true}'


def test_custom_menus_get_ps_engines_custom_and_presets_ps_engines(
    store, generation, api_env, monkeypatch
):
    """Engines spec 7: an engine a custom build does not compute is unavailable, with why."""
    monkeypatch.delenv("PS_ENGINES", raising=False)
    monkeypatch.setenv("PS_ENGINES_CUSTOM", "replay")
    funds = [{"id": fund, "min": None, "max": None} for fund in ("VTI", "BND", "VNQ")]
    uhash = universe_hash(funds)
    build_job(store, generation, uhash, "1y", funds)
    custom = json.loads(store.get(tensor_key(generation, uhash, "1y")))
    assert custom["engines"]["garch"] == {
        "status": "unavailable",
        "reason": "not computed for custom menus",
        "method": None,
    }
    assert custom["shape"] is None and list(custom["ladder"]["ranges"]) == ["replay"]
    assert store.list("models/") == []
    tsp = [{"id": fund, "min": None, "max": None} for fund in ("TSP-G", "TSP-C", "TSP-F")]
    build_job(
        store, generation, universe_hash(tsp), "1y", tsp, universe_name="TSP", preset_id="tsp"
    )
    preset = json.loads(store.get(tensor_key(generation, universe_hash(tsp), "1y")))
    assert preset["engines"]["garch"]["status"] == "ready" and preset["shape"] is not None
    assert len(store.list(f"models/{generation}/")) == 2
