"""Risk columns on worker processes: the same answers as in one process, and failures named."""

from __future__ import annotations

import importlib
import os
import pickle
import threading
from concurrent.futures import process as futures_process

import numpy as np
import pytest
from threadpoolctl import threadpool_info, threadpool_limits

from portfoliosight.engine import optimize, parallel
from portfoliosight.engine.ladder import Candidate, Pool, ladders, peak_pools, spread_peaks
from portfoliosight.engine.optimize import frontier
from portfoliosight.engine.parallel import ColumnError, by_column
from portfoliosight.engine.tensor import build_tensor, canonical_json
from tests.engine.helpers import Menu, fixture_inputs

TELEMETRY = ("built_at", "build_seconds")


@pytest.fixture(scope="module")
def menu() -> Menu:
    return Menu(12, 3812, nx=12)


@pytest.fixture(scope="module", autouse=True)
def stop_pools():
    yield
    parallel.shutdown()


@pytest.fixture(autouse=True)
def one_blas_thread():
    """BLAS on one thread here too, as in a build: the workers' sums are then the same as ours."""
    with threadpool_limits(limits=1, user_api="blas"):
        yield


def _core(tensor: dict) -> str:
    return canonical_json({k: v for k, v in tensor.items() if k not in TELEMETRY})


def _members(pools: list[Pool]) -> list[list[tuple[bytes, float, float]]]:
    return [[(m.w.tobytes(), m.y, m.z) for m in pool.members] for pool in pools]


def _same_columns(a: dict, b: dict) -> bool:
    return a.keys() == b.keys() and all(
        all(np.array_equal(getattr(a[j], f), getattr(b[j], f)) for f in ("w", "y", "z", "hop"))
        and a[j].collapsed == b[j].collapsed
        for j in a
    )


# Tasks a worker can import: module-level functions of this module.


def _square(shared: int, j: int, payload: int) -> int:
    return shared * j + payload


def _fails_at_five(_shared, j: int, _payload) -> int:
    if j == 5:
        raise ArithmeticError("no answer here")
    return j


def _where(_shared, _j: int, _payload) -> tuple[int, int, list[int]]:
    """This worker's pid, its fork server's thread count and its BLAS libraries' thread counts."""
    server = len(os.listdir(f"/proc/{os.getppid()}/task"))
    blas = [lib["num_threads"] for lib in threadpool_info() if lib["user_api"] == "blas"]
    return os.getpid(), server, blas


class _Crash:
    """A payload that ends the process that unpickles it, as a worker killed mid-build would."""

    def __reduce__(self):
        return os._exit, (3,)


def test_answers_come_back_by_column_whatever_the_workers():
    payloads = {j: 10 * j for j in range(23)}
    expected = {j: 7 * j + 10 * j for j in range(23)}
    for workers in (1, 2, 3, 8):
        assert by_column(_square, 7, payloads, workers) == expected
    assert by_column(_square, 7, {}, 4) == {} and by_column(_square, 7, {4: 1}, 4) == {4: 29}


def test_chunks_keep_column_order_and_cover_every_column():
    items = [(j, None) for j in range(47)]
    for count in (1, 2, 8, 16, 32, 64):
        chunks = parallel._chunks(items, count)
        assert [j for chunk in chunks for j, _ in chunk] == list(range(47))
        assert len(chunks) <= count and len({len(chunk) for chunk in chunks[:-1]}) <= 1


def test_ladders_and_pools_are_the_same_on_any_number_of_workers(menu):
    risks = [float(x) for x in menu.front.x]
    columns = range(menu.nx)
    serial = peak_pools(menu.program, menu.programs, menu.front)
    serial_ladders = ladders(menu.program, risks, serial, columns, 6)
    gained = spread_peaks(menu.program, menu.programs, menu.front, serial)
    serial_ladders.update(ladders(menu.program, risks, serial, gained, 6))
    for workers in (2, 3):
        pools = peak_pools(menu.program, menu.programs, menu.front, workers=workers)
        found = ladders(menu.program, risks, pools, columns, 6, workers)
        assert spread_peaks(menu.program, menu.programs, menu.front, pools) == gained
        found.update(ladders(menu.program, risks, pools, gained, 6, workers))
        assert _same_columns(found, serial_ladders)
        assert _members(pools) == _members(serial)  # every candidate, in the order found


def test_frontiers_are_the_same_on_any_number_of_workers(menu):
    alone = frontier(menu.programs, 12)
    for workers in (2, 3):
        shared = frontier(menu.programs, 12, workers)
        for field in ("x", "y", "w", "pinned"):
            assert np.array_equal(getattr(shared, field), getattr(alone, field))


def test_a_worker_builds_its_own_programs_from_the_menu(menu):
    shipped = pickle.loads(pickle.dumps(optimize._Menu(menu.programs)))
    assert shipped._programs is None
    x = float(menu.front.x[4])
    assert np.array_equal(shipped.programs().frontier_point(x), menu.programs.frontier_point(x))
    assert shipped.programs() is shipped.programs()  # built once, then kept


@pytest.mark.parametrize("workers", [1, 3])
def test_a_failing_column_is_named(workers):
    with pytest.raises(ColumnError, match=r"^risk column 5: ArithmeticError: no answer here$") as e:
        by_column(_fails_at_five, None, dict.fromkeys(range(12)), workers)
    assert e.value.column == 5 and e.value.reason == "ArithmeticError: no answer here"


def test_a_ladder_that_fails_names_its_column(menu):
    pools = peak_pools(menu.program, menu.programs, menu.front)
    broken = Candidate(w=pools[7].top.w, y="not a return", z=pools[7].top.z)  # type: ignore[arg-type]
    pools[7].members = [broken]
    risks = [float(x) for x in menu.front.x]
    for workers in (1, 2):
        with pytest.raises(ColumnError, match=r"^risk column 7: TypeError: ") as e:
            ladders(menu.program, risks, pools, range(menu.nx), 6, workers)
        assert e.value.column == 7


def test_a_column_error_survives_pickling():
    again = pickle.loads(pickle.dumps(ColumnError(3, "ValueError: x")))
    assert isinstance(again, ColumnError) and (again.column, again.reason) == (3, "ValueError: x")
    assert str(again) == "risk column 3: ValueError: x"


def test_a_worker_that_dies_fails_the_call_and_the_next_call_gets_a_new_pool():
    payloads: dict = dict.fromkeys(range(8), 1)
    payloads[6] = _Crash()
    stopped = r"a worker process stopped before columns \[.*\] were done"
    with pytest.raises(ColumnError, match=stopped):
        by_column(_square, 2, payloads, 2)
    assert parallel._executor is None  # the broken pool is forgotten
    assert by_column(_square, 2, dict.fromkeys(range(8), 1), 2) == {j: 2 * j + 1 for j in range(8)}


def test_the_pool_is_kept_for_the_same_count_and_replaced_for_another():
    parallel.warm_up(2)
    first = parallel._executor
    parallel.warm_up(2)
    assert parallel._executor is first
    parallel.warm_up(3)
    assert parallel._executor is not first and parallel._executor_workers == 3
    parallel.warm_up(1)  # one worker needs no pool
    assert parallel._executor_workers == 3
    parallel.shutdown()
    assert parallel._executor is None
    parallel.shutdown()  # nothing to stop


def test_exit_drops_unstarted_chunks_before_the_pool_waits_for_its_work():
    hooks = threading._threading_atexits  # type: ignore[attr-defined]
    ours = [i for i, hook in enumerate(hooks) if getattr(hook, "func", None) is parallel.shutdown]
    exit_hook = futures_process._python_exit
    pools = [i for i, hook in enumerate(hooks) if getattr(hook, "func", None) is exit_hook]
    assert len(ours) == 1 and hooks[ours[0]].keywords == {"wait": False}
    assert pools and ours[0] > pools[0]  # run in reverse order: ours first


def test_workers_fork_from_a_single_threaded_server_and_run_blas_on_one_thread():
    answers = by_column(_where, None, dict.fromkeys(range(8)), 2)
    pids = {pid for pid, _server, _blas in answers.values()}
    assert 1 <= len(pids) <= 2 and os.getpid() not in pids
    assert all(server == 1 for _pid, server, _blas in answers.values())
    assert all(blas and set(blas) == {1} for _pid, _server, blas in answers.values())


def test_what_a_worker_runs_also_runs_here(menu):
    assert parallel._run_chunk(_square, pickle.dumps(3), [(2, 1), (4, 0)]) == [(2, 7), (4, 12)]
    assert parallel._ready() is True
    parallel._init_worker()
    assert parallel._blas_limit is not None
    parallel._blas_limit.restore_original_limits()


def test_the_worker_environment_holds_blas_and_jemalloc_to_one_thread(monkeypatch):
    environment: dict[str, str] = {"OMP_NUM_THREADS": "8"}
    monkeypatch.setattr(os, "environ", environment)  # this process's own stays as it is
    module = importlib.reload(importlib.import_module("portfoliosight.worker_env"))
    assert environment == module.SETTINGS
    assert environment["OPENBLAS_NUM_THREADS"] == "1"
    assert "background_thread:false" in environment["JE_ARROW_MALLOC_CONF"]


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_the_fixture_tensor_is_the_same_on_any_number_of_workers(workers, fixture_tensor):
    built = build_tensor(fixture_inputs("5y"), workers=workers)
    assert _core(built) == _core(fixture_tensor)
