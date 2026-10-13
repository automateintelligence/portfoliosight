"""scripts/make_local_store.py: an unpublished fixture store any uid can write."""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data.store import LocalStore
from portfoliosight.jobs.fixture_store import TSP_CORE, fixture_asof

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "make_local_store.py"


def _run(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(target)], cwd=ROOT, capture_output=True, text=True
    )


def test_a_directory_that_is_not_a_fixture_store_is_never_replaced(tmp_path):
    precious = tmp_path / "documents"
    precious.mkdir()
    (precious / "thesis.txt").write_text("years of work")
    done = _run(precious)
    assert done.returncode == 2 and "is not a fixture store" in done.stderr
    assert (precious / "thesis.txt").read_text() == "years of work"
    a_file = tmp_path / "file"
    a_file.write_text("x")
    assert _run(a_file).returncode == 2 and a_file.read_text() == "x"
    # A real local store has a catalog too; only this script's own marker allows replacing.
    real = tmp_path / "real-store"
    (real / "meta").mkdir(parents=True)
    (real / "meta" / "manifest.json").write_text('{"symbols": {}}')
    assert _run(real).returncode == 2
    assert (real / "meta" / "manifest.json").read_text() == '{"symbols": {}}'
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _run(empty).returncode == 0 and (empty / ".fixture-store").is_file()


def test_store_is_seeded_unpublished_and_open_to_the_container_uid(tmp_path):
    target = tmp_path / "local-store"
    assert _run(target).returncode == 0
    (target / "left-over").write_text("from an earlier run")
    done = _run(target)  # an earlier store of this script is replaced whole
    assert done.returncode == 0, done.stderr
    assert not (target / "left-over").exists()
    store = LocalStore(target)
    assert not store.exists("meta/current.json") and store.list("tensors/") == []
    catalog = manifest_mod.load_manifest(store).symbols
    assert len(catalog) == 28 and set(TSP_CORE) <= set(catalog)
    served = [symbol for symbol, entry in catalog.items() if entry.status == "ok"]
    assert len(served) == 27 and catalog["FIENX"].status == "unavailable"
    assert {entry.last_date for symbol, entry in catalog.items() if symbol != "FIENX"} == {
        fixture_asof()
    }
    assert len(store.list("prices/")) == 28
    for path in (target, target / ".tmp", target / "prices", target / "meta"):
        assert stat.S_IMODE(path.stat().st_mode) & 0o777 == 0o777, path
    for path in (target / "prices" / "VTI.parquet", target / "meta" / "manifest.json"):
        assert stat.S_IMODE(path.stat().st_mode) & 0o666 == 0o666, path
