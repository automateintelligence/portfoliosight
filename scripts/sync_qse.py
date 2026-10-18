"""Pull the QSE files PortfolioSight needs, byte-identical, at a pinned commit (spec 3 item 3).

Usage, from the repo root:
    python scripts/sync_qse.py --commit <40 hex>   copy the ten files, write qse/qse.lock.json
    python scripts/sync_qse.py --check             verify the copy against the lock

The files are read from the local QSE checkout with `git cat-file blob <commit>:<path>`, so the
QSE working tree is never read or touched. Each file is written, then closed with `chmod a-w`.
`qse/` is edited only in QSE: merge there, then re-run this script at the new commit.

Before anything is written or closed, both modes refuse (exit 2) a root that overlaps the supplied
QSE checkout, destinations in any of its linked worktrees, and any destination (a listed file,
the lock, or a directory between them and the root) that is a link or resolves outside `<root>/qse`.

Exit codes: 0 done or clean, 1 drift found by --check, 2 bad arguments or an unsafe root or
destination, 3 the QSE checkout or commit is not there, 4 a listed path is not in the commit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCE = "automateintelligence/quant-scenario-engine"
LOCK_NAME = "qse/qse.lock.json"
# PortfolioSight's own files under qse/, which the lock does not name.
UNLOCKED = ("qse/README.md", LOCK_NAME)
# `qse/distributions/__init__.py` is empty at the pin; it is copied so that `qse.distributions`
# stays a regular package. Not copied: `qse/distributions/validation/__init__.py` (it imports
# outside the closure); QSE has no `qse/__init__.py` or `fitters/__init__.py`, so those
# directories are namespace packages here, as in QSE.
FILES = (
    "qse/distributions/__init__.py",
    "qse/distributions/joint/__init__.py",
    "qse/distributions/joint/fhs.py",
    "qse/distributions/joint/panel_fit.py",
    "qse/distributions/joint/portfolio.py",
    "qse/distributions/fitters/garch_t_fitter.py",
    "qse/distributions/garch_recursion.py",
    "qse/distributions/validation/stationarity.py",
    "qse/distributions/models.py",
    "qse/exceptions.py",
)
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
READ_ONLY = 0o444


class SyncError(Exception):
    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def default_qse_dir() -> Path:
    env = os.environ.get("PS_QSE_DIR")
    return Path(env) if env else Path.home() / "programming" / "quant-scenario-engine"


def _git(qse_dir: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(qse_dir), *args],
        capture_output=True,
        env={**os.environ, "LC_ALL": "C"},
        timeout=10,
    )


def read_blobs(qse_dir: Path, commit: str) -> dict[str, bytes]:
    """The bytes of every listed file at `commit`; nothing is written before all are read."""
    if not qse_dir.is_dir():
        raise SyncError(f"QSE checkout not found at {qse_dir}", 3)
    if _git(qse_dir, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        raise SyncError(
            f"commit {commit} is not in {qse_dir}: fetch QSE's `github` remote and retry", 3
        )
    blobs: dict[str, bytes] = {}
    for name in FILES:
        done = _git(qse_dir, "cat-file", "blob", f"{commit}:{name}")
        if done.returncode != 0:
            raise SyncError(f"{name} is not in QSE commit {commit}", 4)
        blobs[name] = done.stdout
    return blobs


def qse_checkout(qse_dir: Path) -> Path:
    """The resolved top level of the QSE working tree `qse_dir` is in (git accepts a
    subdirectory), else `qse_dir` itself resolved, when it is no repository or does not exist."""
    if not qse_dir.exists():
        return qse_dir.resolve()
    try:
        done = _git(qse_dir, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyncError(f"cannot inspect QSE repository identity at {qse_dir}", 3) from exc
    if done.returncode == 0 and done.stdout:
        return Path(os.fsdecode(done.stdout.removesuffix(b"\n"))).resolve()
    return qse_dir.resolve()


def _common_dir(directory: Path, *, allow_non_repository: bool = False) -> Path | None:
    """Git's shared identity for main and linked worktrees; other probe errors are unsafe."""
    try:
        done = _git(directory, "rev-parse", "--path-format=absolute", "--git-common-dir")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SyncError(f"cannot inspect QSE repository identity at {directory}", 3) from exc
    if (
        allow_non_repository
        and done.returncode == 128
        and not done.stdout
        and (
            done.stderr.strip()
            == b"fatal: not a git repository (or any of the parent directories): .git"
            or re.fullmatch(
                rb"fatal: not a git repository \(or any parent up to mount point /[^\n\0]*\)\n"
                rb"Stopping at filesystem boundary \(GIT_DISCOVERY_ACROSS_FILESYSTEM not set\)\.",
                done.stderr.strip(),
            )
            is not None
        )
    ):
        return None
    path = Path(os.fsdecode(done.stdout.removesuffix(b"\n")))
    if done.returncode != 0 or not path.is_absolute() or b"\0" in done.stdout:
        raise SyncError(f"cannot inspect QSE repository identity at {directory}", 3)
    return path.resolve()


def _inside(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def guard(root: Path, qse_dir: Path) -> Path:
    """The resolved root, once it and every destination under it are safe to write and close.

    A root that overlaps the QSE checkout, or a destination that is a symbolic link, a second
    hard link or a path outside `<root>/qse`, would let a sync or a --check overwrite or chmod
    files of the QSE working tree.
    """
    real_root, real_qse = root.resolve(), qse_checkout(qse_dir)
    if _inside(real_root, real_qse) or _inside(real_qse, real_root):
        raise SyncError(
            f"refusing: the root {real_root} and the QSE checkout {real_qse} overlap; "
            "--root must name the PortfolioSight checkout",
            2,
        )
    # An unavailable private checkout must not prevent offline --check. When it is present,
    # compare Git identities at every existing destination ancestor: nested repositories can
    # otherwise hide an enclosing QSE worktree. No working-tree listing or path quoting needed.
    if qse_dir.exists():
        source = _common_dir(qse_dir)
        directories = set()
        for target in (real_root, *(real_root / name for name in (*FILES, LOCK_NAME))):
            directories.update(path for path in (target, *target.parents) if path.is_dir())
        for directory in sorted(directories):
            if _common_dir(directory, allow_non_repository=True) == source:
                raise SyncError(
                    f"refusing: {directory} belongs to a QSE checkout; "
                    "--root must name the PortfolioSight checkout",
                    2,
                )
    base = real_root / "qse"
    for name in (*FILES, LOCK_NAME):
        path = real_root
        for part in Path(name).parts:
            path = path / part
            if path.is_symlink():
                raise SyncError(
                    f"refusing: {path.relative_to(real_root).as_posix()} is a symbolic link", 2
                )
        if not _inside(path.resolve(), base):
            raise SyncError(f"refusing: {name} resolves outside {base}", 2)
        if path.is_file() and path.stat().st_nlink > 1:
            raise SyncError(f"refusing: {name} has another hard link", 2)
    return real_root


def _write_closed(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(path.stat().st_mode | stat.S_IWUSR)
    path.write_bytes(data)
    path.chmod(READ_ONLY)


def sync(commit: str, qse_dir: Path, root: Path) -> dict:
    root = guard(root, qse_dir)
    blobs = read_blobs(qse_dir, commit)
    for name, data in blobs.items():
        _write_closed(root / name, data)
    lock = {
        "source": SOURCE,
        "commit": commit,
        "files": {name: hashlib.sha256(blobs[name]).hexdigest() for name in sorted(blobs)},
    }
    _write_closed(root / LOCK_NAME, (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode())
    return lock


def _close(path: Path) -> None:
    if path.is_file():
        path.chmod(path.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def check(root: Path, qse_dir: Path) -> list[str]:
    """Every drift from the lock, one line each; every listed file is closed again."""
    root = guard(root, qse_dir)
    drifts: list[str] = []
    lock_path = root / LOCK_NAME
    listed: dict[str, str] = {}
    if not lock_path.is_file():
        drifts.append(f"{LOCK_NAME}: missing")
    else:
        try:
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            listed = dict(lock["files"])
            if lock["source"] != SOURCE or not COMMIT_RE.fullmatch(str(lock["commit"])):
                drifts.append(f"{LOCK_NAME}: source or commit is malformed")
        except (ValueError, KeyError, TypeError) as exc:
            drifts.append(f"{LOCK_NAME}: unreadable ({exc!r})")
        for name in sorted(set(listed) ^ set(FILES)):
            where = (
                "the lock but not the script" if name in listed else "the script but not the lock"
            )
            drifts.append(f"{name}: named by {where}")
    # Only the ten files are read and closed: guard() has checked those paths, and a lock entry
    # outside them (absolute, `..`, or any other path) is drift above and is never touched.
    for name in sorted(set(listed) & set(FILES)):
        path = root / name
        if not path.is_file():
            drifts.append(f"{name}: missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != listed[name]:
            drifts.append(f"{name}: differs from the lock")
        _close(path)
    _close(lock_path)
    drifts.extend(
        f"{name}: not named by the lock" for name in _unlisted(root) if name not in listed
    )
    return drifts


def _unlisted(root: Path) -> list[str]:
    """Every file or link under qse/, links not followed, but the README, the lock and bytecode.

    Bytecode is a `*.pyc` file directly inside a `__pycache__` directory, where Python writes it.
    """
    found: list[str] = []
    for top, dirs, files in os.walk(root / "qse"):
        here = Path(top)
        links = [name for name in dirs if (here / name).is_symlink()]
        for name in (*links, *files):
            path = here / name
            bytecode = here.name == "__pycache__" and name.endswith(".pyc")
            if not (bytecode and not path.is_symlink()):
                found.append(path.relative_to(root).as_posix())
    return sorted(set(found) - set(UNLOCKED))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull QSE files at a pinned commit.")
    parser.add_argument("--commit", help="the 40-hex QSE commit to pull")
    parser.add_argument(
        "--qse-dir",
        type=Path,
        help="QSE checkout (default: $PS_QSE_DIR); --check uses it only to refuse an overlap",
    )
    parser.add_argument("--root", type=Path, default=REPO, help="repository root to write into")
    parser.add_argument("--check", action="store_true", help="verify qse/ against the lock")
    args = parser.parse_args(argv)
    commit: str | None = args.commit
    if args.check == (commit is not None):
        parser.error("give --commit <40 hex> to sync, or --check to verify (not both)")
    if commit is not None and not COMMIT_RE.fullmatch(commit):
        parser.error("--commit must be 40 lowercase hex characters")
    qse_dir: Path = args.qse_dir or default_qse_dir()
    if commit is None:
        try:
            drifts = check(args.root, qse_dir)
        except SyncError as exc:
            print(str(exc), file=sys.stderr)
            return exc.code
        for line in drifts:
            print(f"drift: {line}")
        if drifts:
            print(
                f"{len(drifts)} drift(s): restore with `git checkout -- qse`, or re-run "
                "scripts/sync_qse.py --commit <sha>",
                file=sys.stderr,
            )
            return 1
        print(f"qse/ matches {LOCK_NAME}")
        return 0
    try:
        lock = sync(commit, qse_dir, args.root)
    except SyncError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    print(f"{len(lock['files'])} files pulled at {lock['commit']}; wrote {LOCK_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
