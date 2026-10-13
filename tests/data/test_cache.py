"""The scratch cache: cap, least-recent eviction, protected keys (spec 5.3; A-PS-12)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from portfoliosight.data import cache
from portfoliosight.data.store import LocalStore

KEYS = [f"prices/F{i}.parquet" for i in range(1, 7)]
SIZE = 600_000


@pytest.fixture
def store(tmp_path):
    store = LocalStore(tmp_path / "store")
    for i, key in enumerate(KEYS):
        store.put(key, bytes([i]) * SIZE)
    return store


class Counting(LocalStore):
    def __init__(self, inner: LocalStore):
        super().__init__(inner.root)
        self.gets: list[str] = []

    def get(self, key: str) -> bytes:
        self.gets.append(key)
        return super().get(key)


def _fill(store, cache_dir: Path, numbers, base: float) -> dict[int, Path]:
    paths = {}
    for when, i in enumerate(numbers, start=1):
        paths[i] = cache.fetch_into_cache(store, KEYS[i - 1], cache_dir=cache_dir)
        os.utime(paths[i], (base + when, paths[i].stat().st_mtime))
    return paths


def _size(cache_dir: Path) -> int:
    return sum(p.stat().st_size for p in cache_dir.rglob("*") if p.is_file())


def test_fetch_copies_once_and_a_hit_counts_as_an_access(store, tmp_path):
    counting = Counting(store)
    cache_dir = tmp_path / "cache"
    path = cache.fetch_into_cache(counting, KEYS[0], cache_dir=cache_dir)
    assert path == cache_dir / "prices" / "F1.parquet" and path.read_bytes() == store.get(KEYS[0])
    old = time.time() - 5_000
    os.utime(path, (old, old))
    again = cache.fetch_into_cache(counting, KEYS[0], cache_dir=cache_dir)
    assert again == path and counting.gets == [KEYS[0]]
    assert path.stat().st_atime > old + 4_000 and path.stat().st_mtime == pytest.approx(old)
    assert [p.name for p in (cache_dir / "prices").iterdir()] == ["F1.parquet"]
    with pytest.raises(KeyError):
        cache.fetch_into_cache(store, "prices/NONE.parquet", cache_dir=cache_dir)
    with pytest.raises(ValueError, match="invalid store key"):
        cache.fetch_into_cache(store, "../outside", cache_dir=cache_dir)


def test_evicts_least_recently_accessed_down_to_the_cap(store, tmp_path, monkeypatch):
    monkeypatch.setenv("PS_CACHE_MAX_MB", "2")
    cache_dir = tmp_path / "cache"
    base = time.time() - 10_000
    paths = _fill(store, cache_dir, (1, 2, 3, 4), base)
    cache.fetch_into_cache(store, KEYS[0], cache_dir=cache_dir)  # touch the first again
    assert paths[1].stat().st_atime > base + 4
    paths.update(_fill(store, cache_dir, (5,), time.time()))
    assert _size(cache_dir) == 5 * SIZE
    cache.evict(cache_dir=cache_dir)
    assert _size(cache_dir) == 3 * SIZE <= 2_000_000
    assert [i for i in paths if paths[i].exists()] == [1, 4, 5]
    cache.evict(cache_dir=cache_dir)
    assert [i for i in paths if paths[i].exists()] == [1, 4, 5]


def test_needed_keys_are_never_evicted(store, tmp_path, monkeypatch):
    monkeypatch.setenv("PS_CACHE_MAX_MB", "2")
    cache_dir = tmp_path / "cache"
    paths = _fill(store, cache_dir, (3, 4, 5, 1, 2), time.time() - 10_000)
    needed = {KEYS[2], KEYS[3], KEYS[4]}
    cache.evict(cache_dir=cache_dir, needed=needed)
    assert [i for i in sorted(paths) if paths[i].exists()] == [3, 4, 5]
    # Even when the needed files alone exceed the cap they stay.
    monkeypatch.setenv("PS_CACHE_MAX_MB", "1")
    cache.evict(cache_dir=cache_dir, needed=list(needed))
    assert _size(cache_dir) == 3 * SIZE
    cache.evict(cache_dir=cache_dir)
    assert [i for i in sorted(paths) if paths[i].exists()] == [5]


def test_cap_follows_the_environment_and_defaults(store, tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    _fill(store, cache_dir, (1, 2, 3, 4, 5), time.time() - 10_000)
    monkeypatch.delenv("PS_CACHE_MAX_MB", raising=False)
    assert cache.max_bytes() == 300_000_000
    cache.evict(cache_dir=cache_dir)
    assert _size(cache_dir) == 5 * SIZE
    monkeypatch.setenv("PS_CACHE_MAX_MB", "0.7")
    cache.evict(cache_dir=cache_dir)
    assert _size(cache_dir) == SIZE
    cache.evict(cache_dir=tmp_path / "absent")  # nothing to do, no error


def test_cache_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.delenv("PS_CACHE_DIR", raising=False)
    assert cache.cache_dir_from_env() == Path("/app/cache")
    monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path))
    assert cache.cache_dir_from_env() == tmp_path
