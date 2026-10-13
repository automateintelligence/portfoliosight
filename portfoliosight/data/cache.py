"""The size-capped scratch cache of the build container (spec 5.3).

Files are evicted by least-recent access. Access is the file's ``st_atime``, which
``fetch_into_cache`` moves forward itself on every hit, because mounts with ``noatime`` or
``relatime`` do not. Nothing in the cache is authoritative.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Collection
from pathlib import Path

from portfoliosight.data import store as store_mod

DEFAULT_MAX_MB = 300
BYTES_PER_MB = 1_000_000
_TMP_PREFIX = ".tmp-"


def cache_dir_from_env() -> Path:
    """``PS_CACHE_DIR``, else the container's ``/app/cache``."""
    return Path(os.environ.get("PS_CACHE_DIR") or "/app/cache")


def max_bytes() -> int:
    """The cap, read from ``PS_CACHE_MAX_MB`` at call time."""
    return int(float(os.environ.get("PS_CACHE_MAX_MB") or DEFAULT_MAX_MB) * BYTES_PER_MB)


def cached_path(cache_dir: str | os.PathLike[str], key: str) -> Path:
    """Where the cache keeps a store key: the key's own relative path under ``cache_dir``."""
    parts = key.split("/")
    if not key or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"invalid store key {key!r}")
    return Path(cache_dir).joinpath(*parts)


def fetch_into_cache(
    store: store_mod.Store, key: str, *, cache_dir: str | os.PathLike[str]
) -> Path:
    """The path of a file in ``cache_dir`` holding ``store.get(key)``.

    A key already cached is not read from the store again; the hit still counts as an access.
    Never evicts.
    """
    path = cached_path(cache_dir, key)
    if path.is_file():
        os.utime(path, (time.time(), path.stat().st_mtime))
        return path
    data = store.get(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f"{_TMP_PREFIX}{uuid.uuid4().hex}"
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


def evict(*, cache_dir: str | os.PathLike[str], needed: Collection[str] = ()) -> None:
    """Delete least-recently-accessed files until the cache is at most ``PS_CACHE_MAX_MB``.

    The cached files of the store keys in ``needed`` are never deleted, so a build keeps what it
    is reading even when that leaves the cache over its cap until the build ends.
    """
    root = Path(cache_dir)
    if not root.is_dir():
        return
    keep = {cached_path(root, key) for key in needed}
    files = [(path, path.stat()) for path in root.rglob("*") if path.is_file()]
    total = sum(stat.st_size for _, stat in files)
    cap = max_bytes()
    for path, stat in sorted(files, key=lambda item: (item[1].st_atime_ns, str(item[0]))):
        if total <= cap:
            break
        if path in keep:
            continue
        path.unlink(missing_ok=True)
        total -= stat.st_size
