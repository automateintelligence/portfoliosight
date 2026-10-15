"""How many processes a tensor build may use (spec 4.12).

The engine itself reads nothing (`portfoliosight/engine/__init__.py`); this module is the one
place that looks at the host for it. What it answers decides how a build's work is scheduled,
never what the build computes: a tensor is the same whatever the count.

Two limits apply to a process. Its affinity mask names the CPUs it may run on (`taskset`,
`docker --cpuset-cpus`). A container's CPU limit (compose `cpus: "4"`) is not a mask but a
cgroup v2 quota: `/sys/fs/cgroup/cpu.max` holds `<quota> <period>` in microseconds, or `max`
when there is none, and the process may use `quota / period` CPUs' worth of time spread over
every CPU of its mask. The CPUs available are the smaller of the two, the quota rounded down
and never below one.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

WORKERS_ENV = "PS_BUILD_WORKERS"
MAX_DEFAULT_WORKERS = 8
CPU_MAX = Path("/sys/fs/cgroup/cpu.max")


def cgroup_cpus(cpu_max: Path = CPU_MAX) -> int | None:
    """CPUs granted by the cgroup v2 quota, rounded down, at least 1; `None` without a quota.

    A missing or unreadable file (no cgroup v2, another OS) and `max` both mean no quota.
    """
    try:
        fields = cpu_max.read_text(encoding="ascii").split()
    except OSError:
        return None
    if not fields or fields[0] == "max":
        return None
    if len(fields) != 2 or not all(field.isdigit() for field in fields) or fields[1] == "0":
        raise ValueError(f"{cpu_max} holds {' '.join(fields)!r}, not '<quota> <period>' or 'max'")
    return max(1, int(fields[0]) // int(fields[1]))


def available_cpus(cpu_max: Path = CPU_MAX) -> int:
    """CPUs this process may use: its affinity mask, lowered to the cgroup quota if there is one."""
    mask = len(os.sched_getaffinity(0))
    quota = cgroup_cpus(cpu_max)
    return mask if quota is None else min(mask, quota)


def build_workers(environ: Mapping[str, str] | None = None, cpu_max: Path = CPU_MAX) -> int:
    """Worker processes for one build: `PS_BUILD_WORKERS` when set, else the CPUs available, at
    most `MAX_DEFAULT_WORKERS`. One means the build runs in its own process, as before.
    """
    raw = (os.environ if environ is None else environ).get(WORKERS_ENV, "").strip()
    if not raw:
        return min(available_cpus(cpu_max), MAX_DEFAULT_WORKERS)
    if not raw.isdigit() or int(raw) < 1:
        raise ValueError(f"{WORKERS_ENV} must be a whole number of at least 1, not {raw!r}")
    return int(raw)
