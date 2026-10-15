"""How many processes a tensor build may use (spec 4.12).

The engine itself reads nothing (`portfoliosight/engine/__init__.py`); this module is the one
place that looks at the host for it. What it answers decides how a build's work is scheduled,
never what the build computes: a tensor is the same whatever the count.

Two limits apply to a process. Its affinity mask names the CPUs it may run on (`taskset`,
`docker --cpuset-cpus`). A container's CPU limit (compose `cpus: "4"`) is not a mask but a
cgroup v2 quota: the `cpu.max` file of the process's cgroup, and of each cgroup above it, holds
`<quota> <period>` in microseconds, or `max` when there is none, and a cgroup may use
`quota / period` CPUs' worth of time spread over every CPU of the mask. `/proc/self/cgroup`
names the process's cgroup below the mount `/sys/fs/cgroup`; inside a container with its own
cgroup namespace (Docker's default on cgroup v2) that is `/`, the container's own cgroup. The
CPUs available are the mask, lowered to the tightest quota on the way up, rounded down and never
below one.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

WORKERS_ENV = "PS_BUILD_WORKERS"
MAX_DEFAULT_WORKERS = 8
CGROUP_ROOT = Path("/sys/fs/cgroup")
MEMBERSHIP = Path("/proc/self/cgroup")


def cgroup_cpus(root: Path = CGROUP_ROOT, membership: Path = MEMBERSHIP) -> int | None:
    """CPUs granted by the tightest cgroup v2 quota over this process; `None` without one.

    A missing or unreadable `cpu.max` (no cgroup v2, another OS, the root cgroup) and `max` both
    mean no quota at that level. Without a readable membership file only the mount root is read.
    """
    quotas = [_quota(level / "cpu.max") for level in _levels(root, membership)]
    granted = [quota for quota in quotas if quota is not None]
    return min(granted) if granted else None


def available_cpus(root: Path = CGROUP_ROOT, membership: Path = MEMBERSHIP) -> int:
    """CPUs this process may use: its affinity mask, lowered to a cgroup quota if there is one."""
    mask = len(os.sched_getaffinity(0))
    quota = cgroup_cpus(root, membership)
    return mask if quota is None else min(mask, quota)


def build_workers(
    environ: Mapping[str, str] | None = None,
    root: Path = CGROUP_ROOT,
    membership: Path = MEMBERSHIP,
) -> int:
    """Worker processes for one build: `PS_BUILD_WORKERS` when set, else the CPUs available, at
    most `MAX_DEFAULT_WORKERS`. One means the build runs in its own process, as before.
    """
    raw = (os.environ if environ is None else environ).get(WORKERS_ENV, "").strip()
    if not raw:
        return min(available_cpus(root, membership), MAX_DEFAULT_WORKERS)
    if not raw.isdigit() or int(raw) < 1:
        raise ValueError(f"{WORKERS_ENV} must be a whole number of at least 1, not {raw!r}")
    return int(raw)


def _levels(root: Path, membership: Path) -> list[Path]:
    """The process's cgroup directory and every one above it, up to and including `root`."""
    try:
        lines = membership.read_text(encoding="ascii").splitlines()
    except OSError:
        return [root]
    own = next((line[3:] for line in lines if line.startswith("0::")), "/")
    here = root / own.strip("/")
    return [here, *(level for level in here.parents if root in (level, *level.parents))]


def _quota(cpu_max: Path) -> int | None:
    """`quota // period` of one `cpu.max`, at least 1; `None` when unlimited or unreadable."""
    try:
        fields = cpu_max.read_text(encoding="ascii").split()
    except OSError:
        return None
    if not fields or fields[0] == "max":
        return None
    if len(fields) != 2 or not all(field.isdigit() for field in fields) or fields[1] == "0":
        raise ValueError(f"{cpu_max} holds {' '.join(fields)!r}, not '<quota> <period>' or 'max'")
    return max(1, int(fields[0]) // int(fields[1]))
