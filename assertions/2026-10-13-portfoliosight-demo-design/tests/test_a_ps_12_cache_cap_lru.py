"""A-PS-12 — the KS-001 cache never exceeds its cap.

Claim: after any build or nightly step the cache directory's total size is at most
PS_CACHE_MAX_MB, eviction is by least-recent access, and a file needed by the current build is
never evicted during that build.

Pinned interface (the product must provide exactly this), in `portfoliosight/data/cache.py`:
- `fetch_into_cache(store, key, *, cache_dir) -> pathlib.Path`: returns the path of a regular
  file inside `cache_dir` holding `store.get(key)`. A key already cached is not read from the
  store again; the hit still counts as an access (the function moves the file's access time
  forward itself with `os.utime`, since mounts with `noatime`/`relatime` do not). It never
  evicts.
- `evict(*, cache_dir, needed=()) -> None`: deletes least-recently-accessed files (by the file's
  `st_atime`) until the total size of all files under `cache_dir` is at most `PS_CACHE_MAX_MB`
  megabytes, read from the environment at call time. `needed` is a collection of store keys; the
  cached files of those keys are never deleted.
- The store is anything with the five methods of the shared Store pin; this test passes its own
  in-memory one.
"""

from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _project_python() -> Path | None:
    """The project's virtualenv interpreter: this checkout's, else the main checkout's (worktree)."""
    roots = [ROOT]
    dot_git = ROOT / ".git"
    if dot_git.is_file():  # linked worktree: "gitdir: <main>/.git/worktrees/<name>"
        roots.append(Path(dot_git.read_text().split(":", 1)[1].strip()).parents[2])
    for root in roots:
        candidate = root / ".venv" / "bin" / "python"
        if candidate.exists():
            return candidate
    return None


_VENV_PY = _project_python()
_OUTER = (
    os.environ.get("PS_GATE_INNER") != "1"
    and _VENV_PY is not None
    and Path(sys.prefix).resolve() != _VENV_PY.parents[1].resolve()
)


def _need(module: str):
    """Import a product (or dev-dependency) module, failing the test cleanly when it is absent."""
    try:
        return importlib.import_module(module)
    except Exception as exc:  # ImportError, or an import-time crash in the product
        pytest.fail(f"A-PS-12 red: cannot import {module}: {type(exc).__name__}: {exc}")


CAP_MB = 2
CAP_BYTES_LOOSE = CAP_MB * 1024 * 1024  # accept either reading of "MB"; 3 files fit, 4 never do
KEYS = [f"prices/GATE{i}.parquet" for i in range(1, 7)]


class _MemoryStore:
    """The five-method store of the shared pin, in memory, counting reads."""

    def __init__(self, blobs: dict[str, bytes]):
        self._blobs = dict(blobs)
        self.gets: list[str] = []

    def get(self, key: str) -> bytes:
        self.gets.append(key)
        return self._blobs[key]

    def put(self, key: str, data: bytes) -> None:
        self._blobs[key] = data

    def exists(self, key: str) -> bool:
        return key in self._blobs

    def list(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self._blobs if k.startswith(prefix))

    def delete(self, key: str) -> None:
        self._blobs.pop(key, None)


def _blobs() -> dict[str, bytes]:
    """Six synthetic parquet files of about 0.6 MB each, all different."""
    np = _need("numpy")
    pd = _need("pandas")
    _need("pyarrow")
    out = {}
    for i, key in enumerate(KEYS):
        rng = np.random.default_rng(1200 + i)
        frame = pd.DataFrame({"tr_index": rng.standard_normal(60_000)})
        buffer = io.BytesIO()
        frame.to_parquet(buffer, compression=None, index=False)
        data = buffer.getvalue()
        assert 550_000 <= len(data) <= 650_000, f"synthetic parquet is {len(data)} bytes"
        out[key] = data
    assert 3 * 650_000 <= CAP_MB * 1_000_000 and 4 * 550_000 > CAP_BYTES_LOOSE
    return out


def _api():
    mod = _need("portfoliosight.data.cache")
    fetch = getattr(mod, "fetch_into_cache", None)
    evict = getattr(mod, "evict", None)
    assert callable(fetch), "portfoliosight.data.cache.fetch_into_cache is missing"
    assert callable(evict), "portfoliosight.data.cache.evict is missing"
    return fetch, evict


def _dir_size(cache_dir: Path) -> int:
    return sum(p.stat().st_size for p in cache_dir.rglob("*") if p.is_file())


def _bytes(path: Path) -> bytes:
    """Read a cache file without letting the kernel (relatime) move its access time."""
    before = path.stat()
    data = path.read_bytes()
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    return data


def _fetch(fetch, store, key: str, cache_dir: Path, blobs) -> Path:
    try:
        path = Path(fetch(store, key, cache_dir=cache_dir))
    except Exception as exc:
        pytest.fail(f"A-PS-12 red: fetch_into_cache({key}) raised {exc!r}")
    assert path.is_file(), f"fetch_into_cache({key}) returned {path}, which is not a file"
    assert cache_dir.resolve() in path.resolve().parents, f"{path} is outside the cache directory"
    assert _bytes(path) == blobs[key], f"cached bytes for {key} differ from the store's"
    return path


def _set_access(path: Path, when: float) -> None:
    assert path.is_file(), (
        f"{path.name} disappeared before evict() was called (fetch_into_cache must not evict)"
    )
    os.utime(path, (when, path.stat().st_mtime))


if _OUTER:

    def test_a_ps_12_in_project_venv():
        env = dict(os.environ, PS_GATE_INNER="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        proc = subprocess.run(
            [
                str(_VENV_PY),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                __file__,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        print(proc.stdout[-8000:], proc.stderr[-2000:])
        assert proc.returncode == 0, "A-PS-12 is red inside the project virtualenv (output above)"

else:

    def test_evicts_least_recently_accessed_down_to_the_cap(tmp_path, monkeypatch):
        monkeypatch.setenv("PS_CACHE_MAX_MB", str(CAP_MB))
        fetch, evict = _api()
        blobs = _blobs()
        store = _MemoryStore(blobs)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        base = time.time() - 10_000
        paths: dict[int, Path] = {}
        for i in (1, 2, 3, 4):
            paths[i] = _fetch(fetch, store, KEYS[i - 1], cache_dir, blobs)
            _set_access(paths[i], base + i)
        # Touch the first again, through the product, before the fifth is fetched.
        again = _fetch(fetch, store, KEYS[0], cache_dir, blobs)
        assert again == paths[1], "a second fetch of the same key must return the same file"
        assert store.gets.count(KEYS[0]) == 1, "a cached key was read from the store again"
        assert paths[1].stat().st_atime > base + 4, (
            "a cache hit must move the file's access time forward (os.utime), "
            f"st_atime is still {paths[1].stat().st_atime - base:+.0f} s from the test's base"
        )
        _set_access(paths[1], base + 5)
        paths[5] = _fetch(fetch, store, KEYS[4], cache_dir, blobs)
        _set_access(paths[5], base + 6)
        assert len(set(paths.values())) == 5, "five keys must be five cache files"
        for i, path in paths.items():
            assert path.is_file(), f"file {i} disappeared during fetches (fetch must not evict)"
        assert _dir_size(cache_dir) > CAP_BYTES_LOOSE, "setup: five files must exceed the cap"

        evict(cache_dir=cache_dir)

        size = _dir_size(cache_dir)
        # Must-not-contain: a directory size above the cap after evict().
        assert not size > CAP_BYTES_LOOSE, (
            f"cache holds {size} bytes after evict(), cap {CAP_MB} MB"
        )
        assert not paths[2].exists(), "the least recently accessed file (the second) was kept"
        assert paths[1].is_file(), "the recently touched first file was evicted"
        assert paths[5].is_file(), "the most recently fetched file was evicted"
        access_order = [2, 3, 4, 1, 5]  # least recent first
        survived = [paths[i].exists() for i in access_order]
        assert survived == sorted(survived), (
            f"eviction is not by least-recent access: survivors by access order {survived}"
        )
        assert sum(survived) == 3, f"expected the three most recent files to remain, got {survived}"
        assert _dir_size(cache_dir) != 0

        evict(cache_dir=cache_dir)
        assert [paths[i].exists() for i in access_order] == survived, "a second evict removed more"

    def test_needed_files_survive_forced_eviction(tmp_path, monkeypatch):
        monkeypatch.setenv("PS_CACHE_MAX_MB", str(CAP_MB))
        fetch, evict = _api()
        blobs = _blobs()
        store = _MemoryStore(blobs)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        base = time.time() - 10_000
        paths = {i: _fetch(fetch, store, KEYS[i - 1], cache_dir, blobs) for i in (1, 2, 3, 4, 5)}
        # The needed files {3, 4, 5} are the least recently accessed ones.
        for when, i in enumerate((3, 4, 5, 1, 2), start=1):
            _set_access(paths[i], base + when)
        needed = {KEYS[2], KEYS[3], KEYS[4]}

        evict(cache_dir=cache_dir, needed=needed)

        for i in (3, 4, 5):
            # Must-not-contain: a needed file missing mid-build.
            assert paths[i].is_file(), f"needed file {i} was evicted during its build"
            assert _bytes(paths[i]) == blobs[KEYS[i - 1]]
        assert not paths[1].exists() and not paths[2].exists(), (
            "the files the build does not need were kept although the cache was over its cap"
        )
        assert not _dir_size(cache_dir) > CAP_BYTES_LOOSE

        # Mid-build: another file arrives, eviction is forced again, more than once.
        paths[6] = _fetch(fetch, store, KEYS[5], cache_dir, blobs)
        for _ in range(3):
            evict(cache_dir=cache_dir, needed=list(needed))
            for i in (3, 4, 5):
                assert paths[i].is_file(), f"needed file {i} was evicted on a repeated evict()"
        assert not paths[6].exists(), "the newest file was kept in place of nothing evictable"
        assert not _dir_size(cache_dir) > CAP_BYTES_LOOSE

        # The build is over: nothing is needed, the cap still holds and LRU order decides.
        paths[1] = _fetch(fetch, store, KEYS[0], cache_dir, blobs)
        evict(cache_dir=cache_dir)
        assert not _dir_size(cache_dir) > CAP_BYTES_LOOSE
        assert not paths[3].exists(), "after the build the least recent file (3) must go"
        assert paths[1].is_file() and paths[4].is_file() and paths[5].is_file()

    def test_cap_follows_the_environment(tmp_path, monkeypatch):
        fetch, evict = _api()
        blobs = _blobs()
        store = _MemoryStore(blobs)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        base = time.time() - 10_000
        paths = {i: _fetch(fetch, store, KEYS[i - 1], cache_dir, blobs) for i in (1, 2, 3, 4, 5)}
        for i, path in paths.items():
            _set_access(path, base + i)
        monkeypatch.setenv("PS_CACHE_MAX_MB", "300")
        evict(cache_dir=cache_dir)
        assert all(p.is_file() for p in paths.values()), "evict() removed files under a 300 MB cap"
        monkeypatch.setenv("PS_CACHE_MAX_MB", "1")
        evict(cache_dir=cache_dir)
        assert not _dir_size(cache_dir) > 1024 * 1024
        assert [paths[i].exists() for i in (1, 2, 3, 4, 5)] == [False, False, False, False, True]
