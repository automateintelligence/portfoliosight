"""The build queue (spec 6): one worker thread and a job table keyed by (G, hash, lookback).

A POST for a key that is queued or building returns that job's state; a tensor already in the
store is ready without a job; a job that raises is failed and a later POST re-enqueues it, up to
three attempts. A ready key never gets a second job, and the default builder never writes over
an existing key, so the first tensor of a key is the one served (spec 4.12).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from portfoliosight.api.hashing import universe_hash
from portfoliosight.api.presets import preset_definitions, tensor_key, tensor_url
from portfoliosight.api.settings import GridSettings
from portfoliosight.data import cache as cache_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.secrets import install_redaction
from portfoliosight.jobs.build import (
    CUSTOM_MENU_NAME,
    BuildRefused,
    KeyExists,
    build_from_store,
    put_tensor,
)

logger = logging.getLogger(__name__)
install_redaction([logger.name])

MAX_DEPTH = 20
MAX_ATTEMPTS = 3
MAX_FAILED = 2000  # failed job states kept; older ones are forgotten
INITIAL_BUILD_SECONDS = 30.0  # a first guess (spec 4.12), until this process has measured builds
BUILD_FAILED = "build_failed"

Key = tuple[str, str, str]
BuildFn = Callable[..., object]
Clock = Callable[[], float]


def build_job(
    store: store_mod.Store,
    generation: str,
    uhash: str,
    lookback: str,
    funds: Sequence[Mapping[str, Any]],
    *,
    universe_name: str = CUSTOM_MENU_NAME,
    preset_id: str | None = None,
) -> None:
    """Build one tensor and write ``tensors/{generation}/{uhash}/{lookback}.json``.

    The default ``build_fn`` of the queue worker and of the nightly. A key that exists is left
    alone: nothing is built and nothing is written. A preset that comes with an allocation has
    it built in as the tensor's entered mix. The scratch cache is evicted to its cap afterwards
    (spec 5.3).
    """
    key = tensor_key(generation, uhash, lookback)
    if store.exists(key):
        return
    if universe_hash(funds) != uhash:
        raise ValueError(f"universe hash {uhash} does not belong to the requested funds")
    cache_dir = cache_mod.cache_dir_from_env()
    grid = GridSettings.from_env()
    try:
        tensor = build_from_store(
            store,
            generation=generation,
            funds=funds,
            lookback=lookback,
            cache_dir=cache_dir,
            universe_name=universe_name,
            preset_id=preset_id,
            allocation=_preset_allocation(preset_id),
            nx=grid.nx,
            ny=grid.ny,
            levels=grid.levels,
        )
        try:
            put_tensor(store, key, tensor)
        except KeyExists:
            logger.info("%s was written by another builder first; keeping that tensor", key)
    finally:
        cache_mod.evict(cache_dir=cache_dir)


def _preset_allocation(preset_id: str | None) -> Mapping[str, float] | None:
    """The allocation of the preset ``preset_id``; ``None`` for a custom menu or a bare preset."""
    for preset in preset_definitions() if preset_id is not None else ():
        if preset.id == preset_id:
            return preset.allocation
    return None


class QueueBusy(Exception):
    """The waiting line is full (spec 6: 503 ``busy``)."""


@dataclass(frozen=True)
class JobState:
    """What a client is told about one key."""

    status: str  # queued | building | ready | failed
    generation: str
    hash: str
    lookback: str
    position: int | None = None  # 0 while building, else the 1-based rank in the waiting line
    eta_s: int | None = None  # estimated seconds until the tensor is ready
    attempts: int = 0
    error: str | None = None
    retry: bool | None = None
    details: dict[str, Any] | None = None

    @property
    def url(self) -> str:
        return tensor_url(self.generation, self.hash, self.lookback)


@dataclass
class _Job:
    key: Key
    funds: Sequence[Mapping[str, Any]]
    status: str = "queued"
    attempts: int = 0
    error: str | None = None
    retry: bool = True
    details: dict[str, Any] | None = None


class BuildQueue:
    """A single worker thread building one tensor at a time."""

    def __init__(
        self,
        build_fn: BuildFn,
        store: store_mod.Store,
        clock: Clock = time.time,
        *,
        max_depth: int = MAX_DEPTH,
        max_failed: int = MAX_FAILED,
        start_worker: bool = True,
    ):
        self._build_fn = build_fn
        self._store = store
        self._clock = clock
        self.max_depth = max_depth
        self.max_failed = max_failed
        self._jobs: dict[Key, _Job] = {}  # queued, building and failed jobs; never ready ones
        self._waiting: deque[Key] = deque()
        self._building: Key | None = None
        self._build_started = 0.0
        self._mean_seconds = INITIAL_BUILD_SECONDS
        self._paused = True
        self._stopped = False
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        if start_worker:
            self.resume()

    # -- observed from outside ------------------------------------------------------------

    @property
    def depth(self) -> int:
        """Jobs waiting; the one being built is not counted."""
        with self._cond:
            return len(self._waiting)

    @property
    def building(self) -> bool:
        with self._cond:
            return self._building is not None

    def state(self, generation: str, uhash: str, lookback: str) -> JobState | None:
        """The job's state, ``None`` when the table has no job for the key."""
        with self._cond:
            job = self._jobs.get((generation, uhash, lookback))
            return None if job is None else self._view(job)

    # -- control ---------------------------------------------------------------------------

    def pause(self) -> None:
        """Stop taking jobs from the line; a build in progress finishes."""
        with self._cond:
            self._paused = True

    def resume(self) -> None:
        with self._cond:
            if self._stopped:
                return
            self._paused = False
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._work, name="tensor-build-worker", daemon=True
                )
                self._thread.start()
            self._cond.notify_all()

    def close(self, timeout: float = 5.0) -> None:
        """Stop the worker after the build in progress, waiting at most ``timeout`` seconds."""
        with self._cond:
            self._stopped = True
            self._cond.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # -- submitting ------------------------------------------------------------------------

    def submit(
        self, generation: str, uhash: str, lookback: str, funds: Sequence[Mapping[str, Any]]
    ) -> JobState:
        """The state of the key's job, enqueuing one when the key has neither job nor tensor.

        Raises ``QueueBusy`` when a job would have to join a full waiting line.
        """
        key = (generation, uhash, lookback)
        with self._cond:
            known = self._known(key)
        if known is not None:
            return known
        if self._store.exists(tensor_key(*key)):
            return JobState("ready", *key)
        with self._cond:
            known = self._known(key)
            if known is not None:
                return known
            if len(self._waiting) >= self.max_depth:
                raise QueueBusy()
            job = _Job(key=key, funds=[dict(fund) for fund in funds])
            self._jobs[key] = job
            self._waiting.append(key)
            self._cond.notify_all()
            return self._view(job)

    def _known(self, key: Key) -> JobState | None:
        """The state of a job in the table; a failed job that may be retried is re-enqueued."""
        job = self._jobs.get(key)
        if job is None:
            return None
        if job.status == "failed" and job.retry:
            if len(self._waiting) >= self.max_depth:
                raise QueueBusy()
            job.status = "queued"
            self._waiting.append(key)
            self._cond.notify_all()
        return self._view(job)

    def _view(self, job: _Job) -> JobState:
        if job.status == "failed":
            return JobState(
                "failed",
                *job.key,
                attempts=job.attempts,
                error=job.error,
                retry=job.retry,
                details=job.details,
            )
        running_left = 0.0
        if self._building is not None:
            elapsed = self._clock() - self._build_started
            running_left = max(self._mean_seconds - elapsed, 1.0)
        if job.status == "building":
            position = 0
        else:
            position = self._waiting.index(job.key) + 1
        eta = running_left + position * self._mean_seconds
        return JobState(
            job.status, *job.key, position=position, eta_s=math.ceil(eta), attempts=job.attempts
        )

    # -- the worker ------------------------------------------------------------------------

    def _work(self) -> None:
        while True:
            with self._cond:
                while not self._stopped and (self._paused or not self._waiting):
                    self._cond.wait()
                if self._stopped:
                    return
                job = self._jobs[self._waiting.popleft()]
                job.status = "building"
                self._building = job.key
                self._build_started = self._clock()
            failure = self._attempt(job)
            with self._cond:
                seconds = max(self._clock() - self._build_started, 0.0)
                self._building = None
                job.attempts += 1
                if failure is None:
                    self._mean_seconds = 0.7 * self._mean_seconds + 0.3 * max(seconds, 1.0)
                    del self._jobs[job.key]
                    continue
                job.status = "failed"
                job.error, refused, job.details = failure
                job.retry = not refused and job.attempts < MAX_ATTEMPTS
                self._forget_old_failures()

    def _attempt(self, job: _Job) -> tuple[str, bool, dict[str, Any] | None] | None:
        """Run one build; ``None`` on success, else ``(error, refused, details)``."""
        generation, uhash, lookback = job.key
        try:
            self._build_fn(self._store, generation, uhash, lookback, job.funds)
            if not self._store.exists(tensor_key(*job.key)):
                raise RuntimeError("the build returned without writing its tensor")
        except BuildRefused as exc:
            logger.warning("build %s refused: %s", "/".join(job.key), exc.code)
            return exc.code, True, exc.details
        except BaseException as exc:
            # Also what is not an Exception: a worker that died here would leave this job
            # "building" and every later one waiting for good.
            logger.error("build %s failed: %s: %s", "/".join(job.key), type(exc).__name__, exc)
            return BUILD_FAILED, False, None
        return None

    def _forget_old_failures(self) -> None:
        failed = [key for key, job in self._jobs.items() if job.status == "failed"]
        for key in failed[: max(len(failed) - self.max_failed, 0)]:
            del self._jobs[key]
