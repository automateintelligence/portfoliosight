"""Freeze the research inputs as a private immutable snapshot (protocol 4; plan task 6b.1).

Usage, from the repo root:
    .venv/bin/python scripts/freeze_research_inputs.py [--mirror DIR] [--root DIR] [--repo DIR]
        [--d-star YYYY-MM-DD] [--calendar-end YYYY-MM-DD]
    .venv/bin/python scripts/freeze_research_inputs.py --verify SNAPSHOT_DIR

Copies once, from the read-only mirror, every raw input of the return-optimization experiment:
both menus' price records (protocol 3), the SGOV file when the mirror has it, `meta/manifest.json`
and `meta/lake.json` (schema, splice and adjustment metadata), the TSP investigation's saved
tensor `INVESTIGATION_TENSOR` (protocol 5: the runner's preflight recomputes its recorded
ranges; its digest is recorded under `investigation`), `data/presets.json` as committed at
HEAD, a pinned XNYS session export (1 January of the earliest price year through
`--calendar-end`, at least 2027-12-31), and a dependency lock (the installed distributions, the
Python version and the git HEAD). Every copied price record must hold a finite, positive
`tr_index` on every row: a NaN or a value at or below zero in any menu, SGOV or TSP-G record is
refused, naming the file, the counts and the first date. The snapshot is
`<root>/<D*>-<sha12>/`, `sha12` being the first 12 hex characters of the SHA-256 of the canonical
`snapshot.json` (compact, key-sorted JSON without `created_utc` and `manifest_sha256`). Files and
directories end with `chmod a-w`.

Each mirror file is hashed before the copy, the copy is hashed, and the mirror file is hashed
again once every copy is done; any difference is an error that leaves no snapshot behind. The
snapshot is built in a hidden sibling directory and renamed into place. A snapshot already there
with identical contents is verified and returned; one with other contents is an error.

The mirror is only read. The destination root may not lie inside the mirror or inside the git
repository (any of its worktrees). A repository with uncommitted changes to tracked files is
refused: the snapshot names the code by its HEAD.

`--verify SNAPSHOT_DIR` (also `verify_snapshot(path)`) needs neither the mirror nor the repository:
it re-hashes every file against `snapshot.json`, checks the directory name against the canonical
manifest and that every file and directory is still read-only. The runner calls it before replay.

Exit codes: 0 done (or already there, identical, or verified), 2 bad argument or unsafe
destination, 3 a missing or invalid input or a dirty repository, 4 a hash mismatch while copying,
5 an existing snapshot with other contents, 6 a snapshot that fails verification.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from portfoliosight.data.returns import RECORD_COLUMNS

REPO = Path(__file__).resolve().parents[1]
D_STAR = date(2026, 10, 16)
DEFAULT_MIRROR = Path("/mnt/d/portfoliosight-data")
DEFAULT_ROOT = Path.home() / "portfoliosight-research" / "snapshots"
# The protocol needs sessions after D* to decide administrative maturity.
MIN_CALENDAR_END = date(2027, 12, 31)
EXCHANGE = "XNYS"
# Protocol 3: the two menus and their fixed order.
TSP_MENU = ("TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I")
# fmt: off
EXAMPLE_MENU = (
    "VTI", "VTV", "VOE", "VB", "VBR", "VEA", "SCHF", "VWO", "VNQ", "VBIAX", "SCHO", "BND",
    "AGG", "TIP", "VTIP", "LQD", "VWOB", "PCY", "EFA", "LTPZ", "EDV", "VGSTX", "DBJP",
)
# fmt: on
MENU_PRESETS = {"tsp": ("tsp", TSP_MENU), "example": ("guide2017", EXAMPLE_MENU)}
SGOV = "SGOV"
TSP_G = "TSP-G"
RISK_FREE_ORDER = [SGOV, TSP_G, "fallback"]
META_FILES = ("meta/manifest.json", "meta/lake.json")
# Protocol 5: the TSP investigation's saved 5y tensor, whose recorded ranges the runner reproduces.
INVESTIGATION_TENSOR = "tensors/2026-10-16-0.2.0/63643e52f0386317/5y.json"
PRESETS_FILE = "data/presets.json"
SNAPSHOT_FILE = "snapshot.json"
CALENDAR_FILE = "calendar/xnys_sessions.csv"
LOCK_FILE = "environment/dependency_lock.txt"
SCHEMA_VERSION = 1
_WRITE_BITS = 0o222


class FreezeError(Exception):
    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Source:
    """One input to copy: where it lands in the snapshot, where it comes from, how to read it."""

    path: str
    origin: str  # "mirror" or "repo_head"
    read: Callable[[], bytes]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(body: dict[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


# ------------------------------------------------------------------------------------- git


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        env={**os.environ, "LC_ALL": "C"},
        timeout=30,
    )


def repo_head(repo: Path) -> str:
    done = _git(repo, "rev-parse", "HEAD")
    head = done.stdout.decode().strip()
    if done.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise FreezeError(f"cannot read the git HEAD of {repo}", 3)
    return head


def dirty_paths(repo: Path) -> list[str]:
    """Tracked files with staged or unstaged changes; untracked files do not count."""
    done = _git(repo, "status", "--porcelain", "--untracked-files=no")
    if done.returncode != 0:
        raise FreezeError(f"cannot read the git status of {repo}", 3)
    return [line[3:].decode(errors="replace") for line in done.stdout.splitlines() if line]


def repo_blob(repo: Path, head: str, name: str) -> bytes:
    """The bytes of ``name`` as committed at ``head``; the working tree is not read."""
    done = _git(repo, "cat-file", "blob", f"{head}:{name}")
    if done.returncode != 0:
        raise FreezeError(f"{name} is not in the git HEAD ({head}) of {repo}", 3)
    return done.stdout


def repo_locations(repo: Path) -> list[Path]:
    """Every worktree of the repository and its shared git directory, resolved."""
    listing = _git(repo, "worktree", "list", "--porcelain")
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if listing.returncode != 0 or common.returncode != 0:
        raise FreezeError(f"cannot list the worktrees of the git repository {repo}", 3)
    found = [Path(os.fsdecode(common.stdout.strip()))]
    for line in listing.stdout.splitlines():
        if line.startswith(b"worktree "):
            found.append(Path(os.fsdecode(line.removeprefix(b"worktree "))))
    return sorted({path.resolve() for path in found})


def _inside(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def guard_destination(root: Path, mirror: Path, repo: Path) -> Path:
    """The resolved root, once it is known to lie outside the mirror and the repository."""
    real = root.expanduser().resolve()
    for label, bases in (
        ("the mirror", [mirror.resolve()]),
        ("the git repository", repo_locations(repo)),
    ):
        for base in bases:
            if _inside(real, base):
                raise FreezeError(f"refusing: the destination {real} is inside {label} ({base})", 2)
    return real


# ----------------------------------------------------------------------------------- inputs


def check_menus(presets: bytes) -> None:
    """The committed presets must still name the protocol's two menus, in order."""
    try:
        funds = {row["id"]: tuple(row["funds"]) for row in json.loads(presets)["presets"]}
    except (ValueError, KeyError, TypeError) as exc:
        raise FreezeError(f"{PRESETS_FILE} at HEAD is unreadable ({exc!r})", 3) from exc
    for preset, expected in MENU_PRESETS.values():
        if funds.get(preset) != expected:
            raise FreezeError(
                f"{PRESETS_FILE} at HEAD: preset {preset!r} funds {funds.get(preset)} differ "
                f"from the protocol menu {expected}",
                3,
            )


def price_path(symbol: str) -> str:
    return f"prices/{symbol}.parquet"


def collect_sources(mirror: Path, repo: Path, head: str) -> list[Source]:
    """Every input to copy; a required file the mirror lacks is named, all of them at once."""
    wanted = [price_path(symbol) for symbol in (*TSP_MENU, *EXAMPLE_MENU)]
    optional = [price_path(SGOV)]
    present = [name for name in optional if (mirror / name).is_file()]
    required = [*wanted, *META_FILES, INVESTIGATION_TENSOR]
    missing = [name for name in required if not (mirror / name).is_file()]
    if missing:
        raise FreezeError(
            f"required input(s) missing from the mirror {mirror}: {', '.join(missing)}", 3
        )
    sources = [
        Source(name, "mirror", partial(Path.read_bytes, mirror / name))
        for name in sorted([*required, *present])
    ]
    sources.append(Source(PRESETS_FILE, "repo_head", partial(repo_blob, repo, head, PRESETS_FILE)))
    return sources


def _copy_input(source: Source, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read())


def price_record(
    symbol: str, data: bytes, manifest_entry: dict[str, Any], d_star: date, in_menu: bool
) -> dict[str, Any]:
    """Schema, row count, date range and catalog row of one copied price file."""
    name = price_path(symbol)
    frame = pd.read_parquet(io.BytesIO(data))
    if list(frame.columns) != list(RECORD_COLUMNS):
        raise FreezeError(
            f"{name}: columns {list(frame.columns)} differ from the record columns "
            f"{list(RECORD_COLUMNS)}",
            3,
        )
    if frame.empty or not pd.api.types.is_datetime64_any_dtype(frame["date"]):
        raise FreezeError(f"{name}: no rows, or a date column that is not a date", 3)
    unset = int(frame["date"].isna().to_numpy().sum())
    if unset:
        raise FreezeError(f"{name}: {unset} row(s) with a missing date", 3)
    values = frame["tr_index"].to_numpy(dtype=float)
    missing = np.isnan(values)
    invalid = ~missing & ~(np.isfinite(values) & (values > 0.0))
    if missing.any() or invalid.any():
        day = frame["date"][missing | invalid].min().date().isoformat()
        raise FreezeError(
            f"{name}: tr_index has {int(missing.sum())} missing (NaN) and {int(invalid.sum())} "
            f"non-finite or non-positive value(s), the first on {day}",
            3,
        )
    first, last = frame["date"].min().date(), frame["date"].max().date()
    if in_menu and last < d_star:
        raise FreezeError(f"{name} ends {last.isoformat()}, before D* {d_star.isoformat()}", 3)
    return {
        "rows": len(frame),
        "first_date": first.isoformat(),
        "last_date": last.isoformat(),
        "columns": [{"name": c, "dtype": str(frame[c].dtype)} for c in frame.columns],
        "manifest_entry": manifest_entry,
    }


def _requirement_line(dist: importlib.metadata.Distribution, name: str) -> str:
    try:
        direct = json.loads(dist.read_text("direct_url.json") or "null")
    except ValueError:
        direct = None
    if isinstance(direct, dict) and isinstance(direct.get("url"), str):
        if direct.get("dir_info", {}).get("editable"):
            return f"-e {direct['url']}"
        return f"{name} @ {direct['url']}"
    return f"{name}=={dist.version}"


def freeze_requirements() -> list[str]:
    """The installed distributions, one requirement line each (``pip freeze --all`` content).

    ``pip`` is not installed in the project environment, so the lines are read from the
    distribution metadata the running interpreter imports from.
    """
    lines: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        key = re.sub(r"[-_.]+", "-", name or "").lower()
        if name and key not in lines:
            lines[key] = _requirement_line(dist, name)
    return sorted(lines.values(), key=str.lower)


def xnys_sessions(start: date, end: date) -> list[str]:
    """ISO dates of the XNYS sessions from ``start`` through ``end``."""
    calendar = xcals.get_calendar(EXCHANGE, start=start.isoformat(), end=end.isoformat())
    return calendar.sessions.strftime("%Y-%m-%d").tolist()


# ----------------------------------------------------------------------------- file system


def _close_tree(path: Path) -> None:
    """``chmod a-w`` on every file and directory under ``path`` and on ``path``."""
    for top, dirs, files in os.walk(path, topdown=False):
        for name in (*files, *dirs):
            entry = Path(top) / name
            entry.chmod(entry.stat().st_mode & ~_WRITE_BITS)
    path.chmod(path.stat().st_mode & ~_WRITE_BITS)


def _remove_tree(path: Path) -> None:
    for top, dirs, _ in os.walk(path):
        Path(top).chmod(Path(top).stat().st_mode | 0o700)
        for name in dirs:
            (Path(top) / name).chmod((Path(top) / name).stat().st_mode | 0o700)
    shutil.rmtree(path)


def _tree_digests(path: Path) -> dict[str, str]:
    """Relative path to digest for every file; a link is listed, never followed."""
    found: dict[str, str] = {}
    for top, dirs, files in os.walk(path):
        for name in (*dirs, *files):
            entry = Path(top) / name
            relative = entry.relative_to(path).as_posix()
            if entry.is_symlink():
                found[relative] = f"link to {os.readlink(entry)}"
            elif entry.is_file():
                found[relative] = _digest(entry.read_bytes())
    return found


def _comparable_manifest(path: Path) -> Any:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(manifest, dict):
        return {k: v for k, v in manifest.items() if k != "created_utc"}
    return manifest


def differences(new: Path, existing: Path) -> list[str]:
    """How ``existing`` differs from a freshly built snapshot, ``created_utc`` aside."""
    if existing.is_symlink() or not existing.is_dir():
        return [f"{existing} is not a directory"]
    fresh, old = _tree_digests(new), _tree_digests(existing)
    problems = [f"{name}: missing" for name in sorted(fresh.keys() - old.keys())]
    problems += [f"{name}: not part of the snapshot" for name in sorted(old.keys() - fresh.keys())]
    for name in sorted(fresh.keys() & old.keys()):
        if name == SNAPSHOT_FILE:
            if _comparable_manifest(new / name) != _comparable_manifest(existing / name):
                problems.append(f"{name}: differs")
        elif fresh[name] != old[name]:
            problems.append(f"{name}: differs")
    return problems


# --------------------------------------------------------------------------------- freezing


def _file_record(path: str, data: bytes, origin: str, source: str | None) -> dict[str, Any]:
    return {
        "path": path,
        "bytes": len(data),
        "sha256": _digest(data),
        "origin": origin,
        "source": source,
    }


def _risk_free_entry(records: dict[str, dict[str, Any]], symbol: str) -> dict[str, Any]:
    record = records.get(symbol)
    if record is None:
        return {"present": False, "path": None}
    return {
        "present": True,
        "path": price_path(symbol),
        "rows": record["rows"],
        "first_date": record["first_date"],
        "last_date": record["last_date"],
    }


def build_snapshot(
    work: Path,
    *,
    sources: list[Source],
    mirror: Path,
    head: str,
    repo_dirty: bool,
    d_star: date,
    calendar_end: date,
) -> str:
    """Write the snapshot into ``work``; returns the SHA-256 of its canonical manifest."""
    before = {source.path: _digest(source.read()) for source in sources}
    copies: dict[str, bytes] = {}
    for source in sources:
        destination = work / source.path
        _copy_input(source, destination)
        copies[source.path] = destination.read_bytes()
        if _digest(copies[source.path]) != before[source.path]:
            raise FreezeError(
                f"{source.path}: the copy differs from the source as hashed before copying "
                f"(source {before[source.path][:12]}, copy {_digest(copies[source.path])[:12]})",
                4,
            )
    for source in sources:
        if _digest(source.read()) != before[source.path]:
            raise FreezeError(f"{source.path}: the source changed while it was being copied", 4)

    catalog = _catalog(copies["meta/manifest.json"])
    menu_symbols = {*TSP_MENU, *EXAMPLE_MENU}
    prices: dict[str, dict[str, Any]] = {}
    for source in sources:
        if source.path.startswith("prices/"):
            symbol = Path(source.path).stem
            if symbol not in catalog:
                raise FreezeError(f"meta/manifest.json has no entry for {symbol}", 3)
            prices[symbol] = price_record(
                symbol, copies[source.path], catalog[symbol], d_star, symbol in menu_symbols
            )

    if INVESTIGATION_TENSOR not in copies:
        raise FreezeError(f"the investigation tensor {INVESTIGATION_TENSOR} is not an input", 3)
    files = []
    for source in sources:
        entry = _file_record(source.path, copies[source.path], source.origin, source.path)
        if source.path.startswith("prices/"):
            entry["record"] = prices[Path(source.path).stem]
        files.append(entry)

    start = date(min(date.fromisoformat(r["first_date"]) for r in prices.values()).year, 1, 1)
    sessions = xnys_sessions(start, calendar_end)
    calendar_csv = ("session\n" + "".join(f"{day}\n" for day in sessions)).encode()
    version_string = f"Python {platform.python_version()}"
    packages = freeze_requirements()
    lock = "".join(
        f"{line}\n" for line in (f"# python: {version_string}", f"# git HEAD: {head}", *packages)
    ).encode()
    for path, data in ((CALENDAR_FILE, calendar_csv), (LOCK_FILE, lock)):
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).write_bytes(data)
        files.append(_file_record(path, data, "generated", None))

    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "d_star": d_star.isoformat(),
        "source_root": str(mirror),
        "repo_head": head,
        "repo_dirty": repo_dirty,
        "menus": {
            key: {"preset": preset, "funds": list(funds)}
            for key, (preset, funds) in MENU_PRESETS.items()
        },
        "files": sorted(files, key=lambda entry: entry["path"]),
        "investigation": {
            "tensor": INVESTIGATION_TENSOR,
            "sha256": _digest(copies[INVESTIGATION_TENSOR]),
        },
        "risk_free": {
            "order": RISK_FREE_ORDER,
            "sgov": _risk_free_entry(prices, SGOV),
            "tsp_g": _risk_free_entry(prices, TSP_G),
        },
        "calendar": {
            "name": EXCHANGE,
            "library": "exchange_calendars",
            "library_version": importlib.metadata.version("exchange_calendars"),
            "start": start.isoformat(),
            "end": calendar_end.isoformat(),
            "first_session": sessions[0],
            "last_session": sessions[-1],
            "sessions": len(sessions),
            "file": CALENDAR_FILE,
        },
        "python": {
            "version": platform.python_version(),
            "version_string": version_string,
            "implementation": platform.python_implementation(),
        },
        "dependency_lock": {"file": LOCK_FILE, "packages": len(packages)},
    }
    digest = _digest(_canonical(body))
    manifest = {**body, "created_utc": datetime.now(UTC).isoformat(), "manifest_sha256": digest}
    (work / SNAPSHOT_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return digest


def _catalog(manifest_bytes: bytes) -> dict[str, dict[str, Any]]:
    try:
        symbols = json.loads(manifest_bytes)["symbols"]
        if not isinstance(symbols, dict):
            raise TypeError("symbols is not an object")
    except (ValueError, KeyError, TypeError) as exc:
        raise FreezeError(f"meta/manifest.json is unreadable ({exc!r})", 3) from exc
    return symbols


def freeze(
    *,
    mirror: Path,
    root: Path,
    repo: Path = REPO,
    d_star: date = D_STAR,
    calendar_end: date = MIN_CALENDAR_END,
) -> Path:
    """Build, verify and close the snapshot; returns its directory."""
    if calendar_end < MIN_CALENDAR_END:
        raise FreezeError(
            f"--calendar-end {calendar_end} is before {MIN_CALENDAR_END}: the protocol needs "
            "sessions after D* for the maturity test",
            2,
        )
    mirror = Path(mirror).expanduser().resolve()
    if not mirror.is_dir():
        raise FreezeError(f"the mirror {mirror} is not a directory", 3)
    root = guard_destination(Path(root), mirror, repo)
    head = repo_head(repo)
    dirty = dirty_paths(repo)
    if dirty:
        raise FreezeError(
            f"refusing: {repo} has uncommitted changes to tracked files ({', '.join(dirty)}); "
            f"the snapshot names the code by its HEAD {head}",
            3,
        )
    check_menus(repo_blob(repo, head, PRESETS_FILE))
    sources = collect_sources(mirror, repo, head)

    root.mkdir(parents=True, exist_ok=True)
    work = root / f".{d_star.isoformat()}-{uuid.uuid4().hex}.tmp"
    work.mkdir()
    try:
        digest = build_snapshot(
            work,
            sources=sources,
            mirror=mirror,
            head=head,
            repo_dirty=bool(dirty),
            d_star=d_star,
            calendar_end=calendar_end,
        )
        final = root / f"{d_star.isoformat()}-{digest[:12]}"
        if os.path.lexists(final):
            problems = differences(work, final)
            if problems:
                raise FreezeError(
                    f"{final} exists with different contents: {'; '.join(problems)}", 5
                )
            print(f"{final} already exists with identical contents (verified)", file=sys.stderr)
            return final
        _close_tree(work)
        work.rename(final)
        return final
    finally:
        if work.exists():
            _remove_tree(work)


def verify_snapshot(path: Path) -> dict[str, Any]:
    """Check a frozen snapshot against its own ``snapshot.json``; returns that manifest.

    Needs no mirror and no repository. Every file is re-hashed, the directory name must be
    ``<D*>-<sha12>`` of the canonical manifest, nothing may be missing or extra, and every file
    and directory must still be read-only. All problems are raised together as one FreezeError
    with code 6.
    """
    root = Path(path).resolve()
    try:
        manifest = json.loads((root / SNAPSHOT_FILE).read_text(encoding="utf-8"))
        files = {entry["path"]: entry for entry in manifest["files"]}
        d_star = manifest["d_star"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FreezeError(
            f"{root}: cannot read a snapshot from {SNAPSHOT_FILE} ({exc!r})", 6
        ) from exc
    problems: list[str] = []
    body = {k: v for k, v in manifest.items() if k not in ("created_utc", "manifest_sha256")}
    digest = _digest(_canonical(body))
    if manifest.get("manifest_sha256") != digest:
        problems.append(f"{SNAPSHOT_FILE}: manifest_sha256 does not match its contents")
    expected = f"{d_star}-{digest[:12]}"
    if root.name != expected:
        problems.append(
            f"the directory is named {root.name}, the canonical manifest says {expected}"
        )
    if manifest.get("repo_dirty") is not False:
        problems.append(f"{SNAPSHOT_FILE}: repo_dirty is not false")
    for relative, entry in sorted(files.items()):
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            problems.append(f"{relative}: path leaves the snapshot")
            continue
        target = root / relative
        if not os.path.lexists(target):
            problems.append(f"{relative}: missing")
        elif target.is_symlink() or not target.is_file():
            problems.append(f"{relative}: not a regular file")
        elif target.stat().st_size != entry.get("bytes") or _digest(
            target.read_bytes()
        ) != entry.get("sha256"):
            problems.append(f"{relative}: differs")
    listed = {*files, SNAPSHOT_FILE}
    closed = [(".", root)]
    for top, dirs, names in os.walk(root):
        for name in (*dirs, *names):
            entry_path = Path(top) / name
            relative = entry_path.relative_to(root).as_posix()
            closed.append((relative, entry_path))
            if entry_path.is_symlink():
                problems.append(f"{relative}: is a link")
            elif name in names and relative not in listed:
                problems.append(f"{relative}: not part of the snapshot")
    for relative, entry_path in closed:
        if not entry_path.is_symlink() and stat.S_IMODE(entry_path.stat().st_mode) & _WRITE_BITS:
            problems.append(f"{relative}: writable")
    if problems:
        raise FreezeError(f"{root} fails verification: {'; '.join(problems)}", 6)
    return manifest


def _iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{text!r} is not an ISO date") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze the research inputs as a snapshot.")
    parser.add_argument(
        "--verify",
        type=Path,
        metavar="SNAPSHOT_DIR",
        help="only verify an existing snapshot (needs no mirror); the other options are ignored",
    )
    parser.add_argument("--mirror", type=Path, default=DEFAULT_MIRROR, help="read-only data mirror")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="snapshots directory")
    parser.add_argument("--repo", type=Path, default=REPO, help="git repository (HEAD, presets)")
    parser.add_argument("--d-star", type=_iso_date, default=D_STAR, help="frozen data date D*")
    parser.add_argument(
        "--calendar-end",
        type=_iso_date,
        default=MIN_CALENDAR_END,
        help=f"last day of the XNYS export (at least {MIN_CALENDAR_END})",
    )
    args = parser.parse_args(argv)
    try:
        if args.verify is not None:
            manifest = verify_snapshot(args.verify)
            print(f"verified {len(manifest['files']) + 1} files", file=sys.stderr)
            print(args.verify.resolve())
            return 0
        snapshot = freeze(
            mirror=args.mirror,
            root=args.root,
            repo=args.repo,
            d_star=args.d_star,
            calendar_end=args.calendar_end,
        )
    except FreezeError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    print(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
