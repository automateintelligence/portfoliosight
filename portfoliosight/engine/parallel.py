"""Work on many risk columns at once, on worker processes (spec 4.12).

`by_column` runs one task per column and returns the answers by column index. It is for work in
which a column reads the build's shared inputs and its own payload and nothing another column
computes in the same call: a column's ladder (`ladder.ladders`), the starts of its peak search
that need no neighbour (`ladder.peak_pools`) and its frontier program (`optimize.frontier`).
Such columns can be solved in any order and on any process. With one worker they are solved in
this process, in column order. With more, they are handed out in chunks to a pool of processes
and the answers are taken back by index, so the caller uses them in column order whatever order
they finished in. A worker runs the same code on the same numbers (pickling keeps every float to
the bit) with BLAS on one thread, as `build_tensor` holds it in the build's own process, so an
answer is the same bit for bit on any number of workers.

The shared inputs (the menu's program, its frontier) are pickled once per call and the same
bytes go with every chunk. Worker processes come from a fork server: a fresh, single-threaded
interpreter that imports the engine once and then forks each worker in milliseconds. The build
service builds on a thread of a threaded process, which must not fork itself, and starting each
worker as a fresh interpreter would cost every one of them the engine's import. A worker still
imports the process's main module (Python 3.12's fork server does not preload it). The pool is
kept for the life of the process and reused by every later call with the same number of workers.
"""

from __future__ import annotations

import math
import multiprocessing
import pickle
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from typing import Any

from threadpoolctl import threadpool_limits

CHUNKS_PER_WORKER = 4  # chunks per worker, so a worker that drew cheap columns takes more
# What the fork server imports before it forks a worker: first the module that holds BLAS to
# one thread (so the server has no threads to fork with), then every engine module.
PRELOAD = ("portfoliosight.worker_env", "__main__", f"{__package__}.builder")

Task = Callable[[Any, int, Any], Any]  # task(shared, column index, payload) -> answer

_lock = threading.Lock()
_executor: ProcessPoolExecutor | None = None
_executor_workers = 0
_blas_limit: threadpool_limits | None = None


class ColumnError(RuntimeError):
    """The work of one risk column failed; `column` is its index, `reason` what went wrong."""

    def __init__(self, column: int, reason: str):
        super().__init__(f"risk column {column}: {reason}")
        self.column = column
        self.reason = reason

    def __reduce__(self):
        return type(self), (self.column, self.reason)


def by_column(
    task: Task,
    shared: Any,
    payloads: Mapping[int, Any],
    workers: int,
    chunks_per_worker: int = CHUNKS_PER_WORKER,
) -> dict[int, Any]:
    """`task(shared, j, payloads[j])` for every column `j` of `payloads`, by column index.

    `task` must be a module-level function, so a worker can import it. Each chunk unpickles
    `shared` once, so state a task leaves on it serves the rest of the chunk; one chunk per
    worker suits work of even cost that pays a set-up per chunk. Raises `ColumnError`
    naming the column whose task raised, or the columns a worker process was given when it
    stopped; the tasks not yet started are cancelled.
    """
    items = list(payloads.items())
    if workers < 2 or len(items) < 2:
        return {j: _run(task, shared, j, payload) for j, payload in items}
    blob = pickle.dumps(shared, protocol=pickle.HIGHEST_PROTOCOL)
    answers: dict[int, Any] = {}
    pending: dict[Future, list[int]] = {}
    chunk: list[int] = []
    executor = _pool(workers)
    try:
        for part in _chunks(items, workers * chunks_per_worker):
            chunk = [j for j, _payload in part]
            pending[executor.submit(_run_chunk, task, blob, part)] = chunk
        for future in as_completed(pending):
            chunk = pending[future]
            answers.update(future.result())
    except BrokenProcessPool as exc:
        _discard(executor)
        reason = f"a worker process stopped before columns {chunk} were done"
        raise ColumnError(chunk[0], reason) from exc
    finally:
        for future in pending:
            future.cancel()
    return answers


def warm_up(workers: int) -> None:
    """Start the process pool for `workers` now rather than at the first call that needs it."""
    if workers > 1:
        _pool(workers).submit(_ready).result()


def shutdown() -> None:
    """Stop the process pool, if there is one; the next call that needs one starts another."""
    global _executor
    with _lock:
        if _executor is not None:
            _executor.shutdown(wait=True, cancel_futures=True)
            _executor = None


def _run(task: Task, shared: Any, j: int, payload: Any) -> Any:
    try:
        return task(shared, j, payload)
    except Exception as exc:
        raise ColumnError(j, f"{type(exc).__name__}: {exc}") from exc


def _run_chunk(task: Task, blob: bytes, part: Sequence[tuple[int, Any]]) -> list[tuple[int, Any]]:
    """What a worker does with one chunk: each column's answer, with its index."""
    shared = pickle.loads(blob)
    return [(j, _run(task, shared, j, payload)) for j, payload in part]


def _chunks(items: Sequence[tuple[int, Any]], count: int) -> list[list[tuple[int, Any]]]:
    """`items` in order, cut into at most `count` runs of equal length (the last may be short)."""
    size = max(1, math.ceil(len(items) / count))
    return [list(items[start : start + size]) for start in range(0, len(items), size)]


def _pool(workers: int) -> ProcessPoolExecutor:
    """The process pool for `workers`, started on first use and kept."""
    global _executor, _executor_workers
    with _lock:
        if _executor is not None and _executor_workers != workers:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None
        if _executor is None:
            context = multiprocessing.get_context("forkserver")
            context.set_forkserver_preload(list(PRELOAD))
            _executor = ProcessPoolExecutor(workers, mp_context=context, initializer=_init_worker)
            _executor_workers = workers
        return _executor


def _discard(executor: ProcessPoolExecutor) -> None:
    """Forget a broken pool, so the next call starts a new one."""
    global _executor
    with _lock:
        if _executor is executor:
            _executor = None
    executor.shutdown(wait=False, cancel_futures=True)


def _init_worker() -> None:
    """A worker holds BLAS to one thread for good, as a build does for its duration."""
    global _blas_limit
    _blas_limit = threadpool_limits(limits=1, user_api="blas")


def _ready() -> bool:
    return True
