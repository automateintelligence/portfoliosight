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


def test_store_is_seeded_unpublished_and_open_to_the_container_uid(tmp_path):
    target = tmp_path / "local-store"
    target.mkdir()
    (target / "left-over").write_text("from an earlier run")
    done = subprocess.run(
        [sys.executable, str(SCRIPT), str(target)], cwd=ROOT, capture_output=True, text=True
    )
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
