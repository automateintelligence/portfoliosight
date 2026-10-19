"""Running the experiment's cells: resource stop rules, timing, tasks and worker processes.

`research.experiment` schedules a run and writes its artifacts; this module executes it under the
protocol 7 ceilings.

- `Monitor` checks the aggregate ceilings each time it is asked: the sum of each process's peak
  resident set (this process and its workers, read from /proc by `ProcMeter`) against 4 GiB, and
  the CPU seconds of all of them plus the CPU spent before this run against the CPU-hour ceiling.
  A `Meter` can be injected, as can the clock that times each arm.
- `run_search_task` searches, selects and locks one cell. Each arm is timed from `search.run_arm`
  (a fresh arm-local cache preloaded with the shared broad archive only) to its native selection;
  an arm past the per-arm ceiling stops the run, whether measured after the arm or raised inside it
  by `arm_alarm` (SIGALRM, in the main thread of the process running the arm). `Probe` splits the
  time into replay evaluation, measure scoring and bank draws while the cell runs.
- `run_evaluation_task` evaluates the locked rows of one origin (`outcomes.evaluate_group`).
- `Inline` runs tasks in this process; `Processes` spawns at most two workers, each holding BLAS to
  one thread (`threadpoolctl`, after checking the inherited environment) and warmed with a small
  COBYLA solve before any timed arm. `drive` feeds tasks in order, one per idle worker, and stops
  at the first breach, reporting which tasks were running (interrupted) and which never started.

A task's result depends only on the task: the same task gives the same bits in any process.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import math
import multiprocessing
import os
import queue
import signal
import threading
import time
import traceback
from collections import Counter, deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pyarrow as pa

from portfoliosight.research import outcomes, search, selection
from portfoliosight.research.evaluate import OriginModel
from portfoliosight.research.outcomes import EvaluationTask
from portfoliosight.research.search import COMPUTATIONAL_ERROR, PRIMARY_ALLOWANCE, Ceilings
from portfoliosight.research.selection import (
    OK_CELL,
    RESOURCE_BREACH,
    TRAINING_INELIGIBLE,
    CellSpec,
    Profile,
)

BLAS_ENV = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
SAMPLE_SECONDS = 60.0  # how often a monitor sample is kept for resources.jsonl


class ArmTimeLimit(Exception):
    """Raised inside an arm by the alarm when it runs past the per-arm ceiling."""


class WorkerError(RuntimeError):
    """A task raised an unexpected exception, or a worker stopped; the message says which."""


def utc() -> str:
    return datetime.now(UTC).isoformat()


# ----------------------------------------------------------------------------------- resources


@dataclass(frozen=True)
class Usage:
    cpu_seconds: float  # this process and its workers, exited ones included
    rss_bytes: int  # current resident set, summed
    peak_bytes: int  # each process's peak resident set, summed


class Meter(Protocol):
    def usage(self, pids: Sequence[int]) -> Usage: ...


class ProcMeter:
    """CPU and resident memory of this process and the given workers, read from /proc.

    This process's CPU counts from the meter's creation (what it spent before is not the run's);
    a worker's counts from its start, imports and warm-up included. A process that has exited
    keeps its last reading.
    """

    def __init__(self) -> None:
        self._tick = os.sysconf("SC_CLK_TCK")
        self._cpu: dict[int, float] = {}
        self._peak: dict[int, int] = {}
        self._base = self._read_cpu(os.getpid()) or 0.0

    def _read_cpu(self, pid: int) -> float | None:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            return None
        fields = stat[stat.rindex(")") + 2 :].split()
        return (int(fields[11]) + int(fields[12])) / self._tick

    def usage(self, pids: Sequence[int]) -> Usage:
        current = 0
        for pid in (os.getpid(), *pids):
            try:
                stat = Path(f"/proc/{pid}/stat").read_text()
                status = Path(f"/proc/{pid}/status").read_text()
            except OSError:
                continue  # exited: its last reading stands
            fields = stat[stat.rindex(")") + 2 :].split()
            spent = (int(fields[11]) + int(fields[12])) / self._tick
            self._cpu[pid] = spent - self._base if pid == os.getpid() else spent
            values = {
                line.split(":")[0]: int(line.split()[1]) * 1024
                for line in status.splitlines()
                if line.startswith(("VmRSS:", "VmHWM:"))
            }
            current += values.get("VmRSS", 0)
            self._peak[pid] = max(self._peak.get(pid, 0), values.get("VmHWM", 0))
        return Usage(sum(self._cpu.values()), current, sum(self._peak.values()))


@dataclass(frozen=True)
class Breach:
    rule: str  # aggregate_peak_rss | cpu_hours | arm_seconds
    limit: float
    value: float
    detail: str = ""

    def record(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class Monitor:
    """Checks the aggregate ceilings and keeps the run's resource figures."""

    def __init__(
        self, rss_bytes: int, cpu_hours: float, meter: Meter, cpu_before: float = 0.0
    ) -> None:
        self.rss_bytes = rss_bytes
        self.cpu_hours = cpu_hours
        self.meter = meter
        self.cpu_before = cpu_before
        self.cpu_seconds = 0.0
        self.rss_peak = 0  # the largest sampled aggregate resident set
        self.peak_bytes = 0  # the largest sum of per-process peaks
        self.samples: list[dict[str, Any]] = []
        self._last_sample = -math.inf

    def check(self, pids: Sequence[int]) -> Breach | None:
        usage = self.meter.usage(pids)
        self.cpu_seconds = max(self.cpu_seconds, usage.cpu_seconds)
        self.rss_peak = max(self.rss_peak, usage.rss_bytes)
        self.peak_bytes = max(self.peak_bytes, usage.peak_bytes)
        now = time.monotonic()
        if now - self._last_sample >= SAMPLE_SECONDS:
            self._last_sample = now
            self.samples.append(
                {
                    "kind": "sample",
                    "utc": utc(),
                    "cpu_seconds": usage.cpu_seconds,
                    "rss_bytes": usage.rss_bytes,
                    "peak_bytes": usage.peak_bytes,
                }
            )
        peak = max(usage.peak_bytes, usage.rss_bytes)
        if peak > self.rss_bytes:
            return Breach("aggregate_peak_rss", self.rss_bytes, peak)
        spent = self.cpu_before + usage.cpu_seconds
        if spent > 3600.0 * self.cpu_hours:
            detail = f"{self.cpu_before:.1f} s before this run"
            return Breach("cpu_hours", 3600.0 * self.cpu_hours, spent, detail)
        return None


@contextlib.contextmanager
def arm_alarm(seconds: float, enabled: bool = True) -> Iterator[None]:
    """Raise `ArmTimeLimit` inside the block once ``seconds`` of real time have passed."""
    usable = (
        enabled
        and math.isfinite(seconds)
        and hasattr(signal, "setitimer")
        and threading.current_thread() is threading.main_thread()
    )
    if not usable:
        yield
        return

    def ring(signum, frame) -> None:
        raise ArmTimeLimit(f"the arm ran past {seconds} s (alarm)")

    previous = signal.signal(signal.SIGALRM, ring)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class Probe:
    """Times replay evaluation, measure scoring and bank draws inside the search while active."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self.clock = clock
        self.seconds: dict[str, float] = {}
        self.calls: Counter[str] = Counter()
        self._saved: list[tuple[Any, str, Any]] = []

    def __enter__(self) -> Probe:
        for owner, name, label in (
            (search, "assess", "return_evaluation"),
            (search, "bank", "bank"),
            (search._Measures, "value", "score"),
        ):
            original = getattr(owner, name)
            self._saved.append((owner, name, original))
            setattr(owner, name, self._timed(original, label))
        return self

    def __exit__(self, *exc: object) -> None:
        while self._saved:
            owner, name, original = self._saved.pop()
            setattr(owner, name, original)

    def _timed(self, original: Callable, label: str) -> Callable:
        def timed(*args, **kwargs):
            start = self.clock()
            try:
                return original(*args, **kwargs)
            finally:
                self.seconds[label] = self.seconds.get(label, 0.0) + self.clock() - start
                self.calls[label] += 1

        return timed

    def mark(self) -> dict[str, float]:
        return dict(self.seconds)


# ------------------------------------------------------------------------------------- tasks


@dataclass(frozen=True)
class SearchTask:
    cell: CellSpec
    profile: Profile
    model: OriginModel | None
    ceilings: Ceilings | None
    caps: tuple[float, ...]
    arm_seconds: float


@dataclass(frozen=True)
class CellResult:
    cell: CellSpec
    status: str
    table: pa.Table | None  # search rows; None once the runner has written them
    locked: pa.Table  # LOCKED_SCHEMA rows, none when the cell failed or stopped
    resources: dict[str, Any]
    breach: Breach | None = None


@dataclass(frozen=True)
class GroupResult:
    task: tuple[str, str, str]
    rows: pa.Table  # EVALUATED_SCHEMA rows in the locked file's order
    resources: dict[str, Any]


def run_search_task(
    task: SearchTask, clock: Callable[[], float] = time.perf_counter, alarm: bool = True
) -> CellResult:
    """Search, select and lock one cell (module docstring: order and timing)."""
    spec, profile = task.cell, task.profile
    started, cpu = clock(), time.process_time()
    record: dict[str, Any] = {
        "kind": "cell", "profile": spec.profile, "cell_key": spec.key, "cell_sha256": spec.sha256,
        "order": spec.order, "menu_index": spec.menu_index, "arm_order": list(spec.arm_order),
        "pid": os.getpid(),
    }  # fmt: skip

    def finish(status: str, table: pa.Table, locked=(), breach: Breach | None = None) -> CellResult:
        record.update(
            {
                "status": status,
                "wall": clock() - started,
                "cpu": time.process_time() - cpu,
                "peak_rss": _own_peak(),
                "breach": None if breach is None else breach.record(),
            }
        )
        return CellResult(spec, status, table, selection.lock_table(locked), record, breach)

    if spec.preset is not None or task.model is None:
        row = selection.cell_row(
            spec, _preset_class(spec), spec.preset, spec.preset_detail, profile=profile
        )
        return finish(row["cell_status"], selection.status_table([row]))
    model = task.model
    with Probe() as probe:
        shared = search.prepare(
            model, task.caps, spec.fraction, spec.seed, arms=profile.arms, budget=profile.budget,
            allowance=PRIMARY_ALLOWANCE, coefficients=profile.coefficients,
        )  # fmt: skip
        if shared.ceilings is not None and shared.ceilings != task.ceilings:
            raise RuntimeError(f"{spec.key}: the cell's risk span differs from the scheduled one")
        shared_marks = probe.mark()
        record["shared"] = {"wall": clock() - started, **shared_marks}
        arms, timings = [], []
        if shared.error is None:
            for position, label in enumerate(spec.arm_order):
                before, start = probe.mark(), clock()
                try:
                    with arm_alarm(task.arm_seconds, alarm):
                        arm = search.run_arm(shared, label)
                except ArmTimeLimit as exc:
                    wall = clock() - start
                    breach = Breach("arm_seconds", task.arm_seconds, wall, f"{label}: {exc}")
                    detail = (
                        f"{exc}; the alarm stopped the arm inside its search, so its attempt "
                        "rows are discarded (the run stops at this breach)"
                    )
                    return finish(
                        RESOURCE_BREACH, _breach_table(spec, profile, label, detail), breach=breach
                    )
                wall = clock() - start
                after = probe.mark()
                spent = {name: after.get(name, 0.0) - before.get(name, 0.0) for name in after}
                timings.append(
                    {
                        "arm": label,
                        "position": position,
                        "wall": wall,
                        **spent,
                        "solver": wall
                        - spent.get("return_evaluation", 0.0)
                        - spent.get("score", 0.0),
                        "calls": arm.calls,
                        "evaluations": arm.evaluations,
                        "cache_hits": arm.calls - arm.evaluations,
                        "invalid": arm.invalid,
                        "failed_starts": arm.failed_starts,
                        "preloaded_rows": len(shared.cache),
                        "cache": "fresh, preloaded with the shared broad archive only",
                    }
                )
                record["arms"] = timings
                if wall > task.arm_seconds:
                    breach = Breach("arm_seconds", task.arm_seconds, wall, label)
                    detail = (
                        f"measured {wall!r} s > {task.arm_seconds!r} s; the arm's attempt rows are "
                        "discarded (the run stops at this breach)"
                    )
                    return finish(
                        RESOURCE_BREACH, _breach_table(spec, profile, label, detail), breach=breach
                    )
                arms.append(arm)
        start = clock()
        cell = search.combine(shared, arms)
        record["union"] = clock() - start
    start = clock()
    chosen = None if cell.failure is not None else selection.choose(cell, profile.coefficients)
    locked = [] if chosen is None else selection.lock_rows(spec, profile, cell, chosen, model)
    record["selection"] = clock() - start
    start = clock()
    table = selection.search_table(spec, profile, cell, chosen, model)
    record["tables"] = clock() - start
    return finish(OK_CELL if cell.failure is None else cell.failure, table, locked)


def _breach_table(spec: CellSpec, profile: Profile, label: str, detail: str) -> pa.Table:
    """The rows of a cell stopped by an arm past its time ceiling: the cell and that arm."""
    cell = selection.cell_row(spec, RESOURCE_BREACH, "arm_seconds", detail, profile=profile)
    arm = {
        key: cell[key]
        for key in (
            "profile", "cell_key", "cell_sha256", "menu", "month", "origin", "lookback",
            "ceiling_id", "fraction", "seed",
        )
    }  # fmt: skip
    arm.update(
        {
            "kind": "arm",
            "arm": label,
            "error": "arm_seconds",
            "error_detail": detail,
            "failure": RESOURCE_BREACH,
        }
    )
    return selection.status_table([cell, arm])


def _preset_class(spec: CellSpec) -> str:
    return TRAINING_INELIGIBLE if spec.preset == TRAINING_INELIGIBLE else COMPUTATIONAL_ERROR


def run_evaluation_task(
    task: EvaluationTask, clock: Callable[[], float] = time.perf_counter
) -> GroupResult:
    start, cpu = clock(), time.process_time()
    rows = outcomes.evaluate_group(task)
    record = {
        "kind": "evaluation", "profile": task.profile, "menu": task.menu, "month": task.month,
        "mixes": rows.num_rows, "wall": clock() - start, "cpu": time.process_time() - cpu,
        "pid": os.getpid(), "peak_rss": _own_peak(),
    }  # fmt: skip
    return GroupResult((task.profile, task.menu, task.month), rows, record)


def execute(task: Any, clock: Callable[[], float] = time.perf_counter, alarm: bool = True) -> Any:
    if isinstance(task, SearchTask):
        return run_search_task(task, clock, alarm)
    if isinstance(task, EvaluationTask):
        return run_evaluation_task(task, clock)
    raise TypeError(f"unknown task {type(task).__name__}")


def _own_peak() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


# --------------------------------------------------------------------------------------- pools


class Inline:
    """Tasks run in this process, one at a time, with the injected clock."""

    def __init__(self, clock: Callable[[], float], alarm: bool) -> None:
        self.clock, self.alarm = clock, alarm
        self._queue: deque[tuple[int, Any]] = deque()
        self.workers: list[dict[str, Any]] = []

    def pids(self) -> list[int]:
        return []

    def idle(self) -> int:
        return 0 if self._queue else 1

    def submit(self, index: int, task: Any) -> None:
        self._queue.append((index, task))

    def next(self, timeout: float) -> tuple[str, int, Any] | None:
        if not self._queue:
            return None
        index, task = self._queue.popleft()
        return ("done", index, execute(task, self.clock, self.alarm))

    def close(self) -> None:
        self._queue.clear()

    terminate = close


def _worker_main(inbox: Any, outbox: Any) -> None:
    """A spawned worker: one BLAS thread, warmed, then tasks until the None sentinel."""
    pid = os.getpid()
    try:
        env = {name: os.environ.get(name) for name in BLAS_ENV}
        if any(value != "1" for value in env.values()):
            raise RuntimeError(f"a worker must run BLAS on one thread; its environment has {env}")
        from threadpoolctl import threadpool_info, threadpool_limits

        limiter = threadpool_limits(limits=1, user_api="blas")
        start = time.perf_counter()
        _warm()
        info = [
            {
                "api": entry.get("user_api"),
                "library": entry.get("internal_api"),
                "threads": entry.get("num_threads"),
            }
            for entry in threadpool_info()
        ]
        outbox.put(
            (
                "ready",
                pid,
                None,
                {"env": env, "blas": info, "warm_seconds": time.perf_counter() - start},
            )
        )
    except BaseException:
        outbox.put(("error", pid, None, traceback.format_exc()))
        return
    while True:
        item = inbox.get()
        if item is None:
            break
        index, task = item
        try:
            result = execute(task)
        except BaseException:
            outbox.put(("error", pid, index, traceback.format_exc()))
        else:
            outbox.put(("done", pid, index, result))
    del limiter


def _warm() -> None:
    """Load the solver code paths before any timed arm (protocol 7: warm state before timing)."""
    from scipy.optimize import minimize

    minimize(
        lambda x: float((x - 0.5) @ (x - 0.5)),
        np.zeros(2),
        method="COBYLA",
        options={"maxiter": 20},
    )


class Processes:
    """At most two spawned worker processes, each fed one task at a time."""

    def __init__(self, count: int, ready_timeout: float = 600.0) -> None:
        context = multiprocessing.get_context("spawn")
        self._outbox = context.Queue()
        self._procs: dict[int, Any] = {}
        self._inbox: dict[int, Any] = {}
        self._busy: dict[int, int | None] = {}
        self.workers: list[dict[str, Any]] = []
        starting = []
        for _ in range(count):
            inbox = context.Queue()
            process = context.Process(target=_worker_main, args=(inbox, self._outbox), daemon=True)
            started = time.perf_counter()
            process.start()
            starting.append((process, inbox, started))
        by_pid = {process.pid: (process, inbox, started) for process, inbox, started in starting}
        while len(self.workers) < count:
            try:
                kind, pid, _index, payload = self._outbox.get(timeout=ready_timeout)
            except queue.Empty as exc:
                _kill(process for process, _, _ in starting)
                raise WorkerError("a worker did not start in time") from exc
            if kind == "error":
                _kill(process for process, _, _ in starting)
                raise WorkerError(payload)
            process, inbox, started = by_pid[pid]
            self._procs[pid], self._inbox[pid], self._busy[pid] = process, inbox, None
            self.workers.append(
                {
                    "kind": "worker",
                    "pid": pid,
                    "cold_seconds": time.perf_counter() - started,
                    **payload,
                }
            )

    def pids(self) -> list[int]:
        return list(self._procs)

    def idle(self) -> int:
        return sum(index is None for index in self._busy.values())

    def submit(self, index: int, task: Any) -> None:
        pid = next(pid for pid, busy in self._busy.items() if busy is None)
        self._busy[pid] = index
        self._inbox[pid].put((index, task))

    def next(self, timeout: float) -> tuple[str, int, Any] | None:
        try:
            kind, pid, index, payload = self._outbox.get(timeout=timeout)
        except queue.Empty:
            for pid, process in self._procs.items():
                if not process.is_alive() and self._busy[pid] is not None:
                    raise WorkerError(
                        f"worker {pid} stopped (exit code {process.exitcode})"
                    ) from None
            return None
        self._busy[pid] = None
        return (kind, index, payload)

    def close(self) -> None:
        for inbox in self._inbox.values():
            inbox.put(None)
        for process in self._procs.values():
            process.join(timeout=30)
        self.terminate()

    def terminate(self) -> None:
        _kill(self._procs.values())


def _kill(processes: Iterable[Any]) -> None:
    alive = list(processes)
    for process in alive:
        if process.is_alive():
            process.terminate()
    for process in alive:
        process.join(timeout=30)


@dataclass
class Stop:
    breach: Breach | None = None
    interrupted: set[int] = field(default_factory=set)
    unattempted: list[int] = field(default_factory=list)


def drive(
    pool: Any,
    tasks: Sequence[tuple[int, Any]],
    monitor: Monitor,
    poll: float,
    handle: Callable[[int, Any], Breach | None],
) -> Stop:
    """Feed ``tasks`` to the pool in order and check the ceilings until done or the first breach."""
    waiting = deque(tasks)
    running: set[int] = set()

    def stop(breach: Breach) -> Stop:
        return Stop(breach, set(running), [index for index, _ in waiting])

    breach = monitor.check(pool.pids())
    if breach is not None:
        return stop(breach)
    while waiting or running:
        while waiting and pool.idle():
            index, task = waiting.popleft()
            pool.submit(index, task)
            running.add(index)
        message = pool.next(poll)
        if message is not None:
            kind, index, payload = message
            running.discard(index)
            if kind == "error":
                raise WorkerError(payload)
            breach = handle(index, payload)
            if breach is not None:
                return stop(breach)
        breach = monitor.check(pool.pids())
        if breach is not None:
            return stop(breach)
    return Stop()


class Resources:
    """`resources.jsonl`, appended line by line."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = path.open("a", encoding="utf-8")

    def write(self, record: Mapping[str, Any]) -> None:
        self._handle.write(json.dumps(record, default=str, separators=(",", ":")) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()
