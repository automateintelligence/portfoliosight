"""Write the fixture store the local container run reads (plan task 4.8).

Usage, from the repo root:
    python scripts/make_local_store.py deploy/.local-store

Records and an `ok` catalog at the fixture's last day, and no `meta/current.json`: the local
nightly has to build and publish the generation itself. The directory is made writable for any
uid, because the container runs as uid 10001 and the bind mount belongs to whoever ran this.
"""

from __future__ import annotations

import argparse
import shutil
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # this checkout's package

from portfoliosight.jobs.fixture_store import write_fixture_store  # noqa: E402

READ_WRITE_ALL = (
    stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH
)
SEARCH_ALL = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH


def open_to_any_uid(directory: Path) -> None:
    """`chmod -R a+rwX`: read and write for all, search on directories."""
    for path in (directory, *directory.rglob("*")):
        mode = path.stat().st_mode | READ_WRITE_ALL
        path.chmod(mode | SEARCH_ALL if path.is_dir() else mode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the local fixture store.")
    parser.add_argument("directory", type=Path, help="where to write it, e.g. deploy/.local-store")
    args = parser.parse_args(argv)
    if args.directory.exists():
        shutil.rmtree(args.directory)
    write_fixture_store(args.directory)
    # LocalStore writes through this folder; it must exist and be writable for the container.
    (args.directory / ".tmp").mkdir(exist_ok=True)
    open_to_any_uid(args.directory)
    print(f"fixture store written to {args.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
