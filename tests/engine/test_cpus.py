"""How many workers a build may use: the affinity mask, the cgroup v2 quota and the override."""

from __future__ import annotations

import os

import pytest

from portfoliosight import cpus
from portfoliosight.cpus import (
    MAX_DEFAULT_WORKERS,
    WORKERS_ENV,
    available_cpus,
    build_workers,
    cgroup_cpus,
)


@pytest.fixture
def cpu_max(tmp_path):
    def write(text: str):
        path = tmp_path / "cpu.max"
        path.write_text(text, encoding="ascii")
        return path

    return write


@pytest.fixture
def mask(monkeypatch):
    def set_mask(count: int) -> None:
        monkeypatch.setattr(cpus.os, "sched_getaffinity", lambda pid: set(range(count)))

    return set_mask


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("400000 100000\n", 4),  # compose cpus: "4"
        ("200000 100000\n", 2),  # KS-001's container today
        ("250000 100000\n", 2),  # cpus: "2.5" rounds down
        ("50000 100000\n", 1),  # cpus: "0.5" still gets one
        ("150000 50000\n", 3),  # another period
        ("max 100000\n", None),  # no quota
    ],
)
def test_cgroup_quota_is_quota_over_period_rounded_down(cpu_max, text, expected):
    assert cgroup_cpus(cpu_max(text)) == expected


def test_no_cgroup_file_means_no_quota(tmp_path):
    assert cgroup_cpus(tmp_path / "absent") is None


@pytest.mark.parametrize("text", ["", "400000\n", "4e5 100000\n", "400000 0\n", "-1 100000\n"])
def test_a_malformed_quota_is_refused_with_what_it_holds(cpu_max, text):
    if not text.split():
        assert cgroup_cpus(cpu_max(text)) is None  # an empty file says nothing
        return
    with pytest.raises(ValueError, match="not '<quota> <period>' or 'max'"):
        cgroup_cpus(cpu_max(text))


def test_available_cpus_is_the_smaller_of_mask_and_quota(cpu_max, mask, tmp_path):
    mask(8)
    assert available_cpus(cpu_max("400000 100000")) == 4  # a container on an 8-CPU host
    assert available_cpus(cpu_max("max 100000")) == 8
    assert available_cpus(tmp_path / "absent") == 8
    mask(2)  # taskset -c 0,1 inside that container
    assert available_cpus(cpu_max("400000 100000")) == 2


def test_the_real_host_answers_at_least_one():
    assert 1 <= available_cpus() <= len(os.sched_getaffinity(0))


def test_workers_default_to_the_cpus_available_at_most_eight(cpu_max, mask):
    mask(12)
    assert build_workers({}, cpu_max("max 100000")) == MAX_DEFAULT_WORKERS == 8
    assert build_workers({}, cpu_max("400000 100000")) == 4
    mask(1)
    assert build_workers({WORKERS_ENV: "  "}, cpu_max("max 100000")) == 1  # blank is unset


def test_the_environment_overrides_the_host(cpu_max, mask, monkeypatch):
    mask(2)
    quota = cpu_max("200000 100000")
    assert build_workers({WORKERS_ENV: "1"}, quota) == 1
    assert build_workers({WORKERS_ENV: "12"}, quota) == 12  # asked for, so given
    monkeypatch.setenv(WORKERS_ENV, "3")
    assert build_workers() == 3  # read from the process environment by default


@pytest.mark.parametrize("raw", ["0", "-2", "two", "1.5"])
def test_a_bad_override_is_refused(raw):
    with pytest.raises(ValueError, match=f"{WORKERS_ENV} must be a whole number of at least 1"):
        build_workers({WORKERS_ENV: raw})
