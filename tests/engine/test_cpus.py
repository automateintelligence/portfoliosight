"""How many workers a build may use: the affinity mask, the cgroup v2 quotas and the override."""

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
def host(tmp_path):
    """A fake cgroup v2 mount and membership file: `host(own, {cgroup: cpu.max text})`."""

    made = []

    def make(own: str = "/", limits: dict[str, str] | None = None):
        made.append(own)
        root = tmp_path / f"host{len(made)}" / "cgroup"
        root.mkdir(parents=True)
        for cgroup, text in (limits or {}).items():
            level = root / cgroup.strip("/")
            level.mkdir(parents=True, exist_ok=True)
            (level / "cpu.max").write_text(text, encoding="ascii")
        membership = root.parent / "self-cgroup"
        membership.write_text(f"0::{own}\n", encoding="ascii")
        return root, membership

    return make


@pytest.fixture
def mask(monkeypatch):
    def set_mask(count: int) -> None:
        monkeypatch.setattr(cpus.os, "sched_getaffinity", lambda pid: set(range(count)))

    return set_mask


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("400000 100000\n", 4),  # compose cpus: "4"
        ("200000 100000\n", 2),  # KS-001's container before 2026-10-15
        ("250000 100000\n", 2),  # cpus: "2.5" rounds down
        ("50000 100000\n", 1),  # cpus: "0.5" still gets one
        ("150000 50000\n", 3),  # another period
        ("max 100000\n", None),  # no quota
        ("", None),  # an empty file says nothing
    ],
)
def test_a_container_quota_is_quota_over_period_rounded_down(host, text, expected):
    assert cgroup_cpus(*host("/", {"/": text})) == expected  # cgroup namespace: own cgroup is /


def test_the_tightest_quota_on_the_way_up_applies(host):
    assert cgroup_cpus(*host("/a/b", {"/a": "max 100000", "/a/b": "300000 100000"})) == 3
    assert cgroup_cpus(*host("/a/b", {"/a": "200000 100000"})) == 2  # a parent's is tighter
    assert cgroup_cpus(*host("/a/b", {"/a/b/c": "100000 100000"})) is None  # below: not ours


def test_no_cgroup_files_mean_no_quota(tmp_path, host):
    assert cgroup_cpus(tmp_path / "absent", tmp_path / "absent-membership") is None
    root, _membership = host("/", {"/": "100000 100000"})
    assert cgroup_cpus(root, tmp_path / "absent-membership") == 1  # the mount root alone
    (tmp_path / "other").write_text("1:cpu:/x\n", encoding="ascii")  # no v2 line: the root
    assert cgroup_cpus(root, tmp_path / "other") == 1


@pytest.mark.parametrize("text", ["400000\n", "4e5 100000\n", "400000 0\n", "-1 100000\n"])
def test_a_malformed_quota_is_refused_with_what_it_holds(host, text):
    with pytest.raises(ValueError, match="not '<quota> <period>' or 'max'"):
        cgroup_cpus(*host("/", {"/": text}))


def test_available_cpus_is_the_smaller_of_mask_and_quota(host, mask):
    mask(8)
    assert available_cpus(*host("/", {"/": "400000 100000"})) == 4  # a container, 8-CPU host
    assert available_cpus(*host("/", {"/": "max 100000"})) == 8
    mask(2)  # taskset -c 0,1 inside that container
    assert available_cpus(*host("/", {"/": "400000 100000"})) == 2


def test_the_real_host_answers_at_least_one():
    assert 1 <= available_cpus() <= len(os.sched_getaffinity(0))


def test_workers_default_to_the_cpus_available_at_most_eight(host, mask):
    mask(12)
    assert build_workers({}, *host("/", {"/": "max 100000"})) == MAX_DEFAULT_WORKERS == 8
    assert build_workers({}, *host("/", {"/": "400000 100000"})) == 4
    mask(1)
    assert build_workers({WORKERS_ENV: "  "}, *host("/", {"/": "max 100000"})) == 1  # blank


def test_the_environment_overrides_the_host(host, mask, monkeypatch):
    mask(2)
    quota = host("/", {"/": "200000 100000"})
    assert build_workers({WORKERS_ENV: "1"}, *quota) == 1
    assert build_workers({WORKERS_ENV: "12"}, *quota) == 12  # asked for, so given
    monkeypatch.setenv(WORKERS_ENV, "3")
    assert build_workers() == 3  # read from the process environment by default


@pytest.mark.parametrize("raw", ["0", "-2", "two", "1.5"])
def test_a_bad_override_is_refused(raw):
    with pytest.raises(ValueError, match=f"{WORKERS_ENV} must be a whole number of at least 1"):
        build_workers({WORKERS_ENV: raw})
