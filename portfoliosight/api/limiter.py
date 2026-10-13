"""Per-IP sliding-window limits (spec 6): 5 tensor POSTs and 60 requests a minute."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable

WINDOW_SECONDS = 60.0
POSTS_PER_MINUTE = 5
REQUESTS_PER_MINUTE = 60
_SWEEP_EVERY = 1024  # admissions between sweeps of keys whose window has emptied


class RateLimiter:
    """At most ``limit`` admissions per key in any ``window`` seconds of ``clock``."""

    def __init__(self, limit: int, clock: Callable[[], float], window: float = WINDOW_SECONDS):
        self.limit = limit
        self.window = window
        self._clock = clock
        self._admitted: dict[str, deque[float]] = {}
        self._since_sweep = 0
        self._lock = threading.Lock()

    def admit(self, key: str) -> bool:
        """Count one request for ``key``; False (and nothing counted) when it is over the limit."""
        now = self._clock()
        floor = now - self.window
        with self._lock:
            times = self._admitted.setdefault(key, deque())
            while times and times[0] <= floor:
                times.popleft()
            if len(times) >= self.limit:
                return False
            times.append(now)
            self._since_sweep += 1
            if self._since_sweep >= _SWEEP_EVERY:
                self._sweep(floor)
            return True

    def _sweep(self, floor: float) -> None:
        self._since_sweep = 0
        idle = [key for key, times in self._admitted.items() if not times or times[-1] <= floor]
        for key in idle:
            del self._admitted[key]
