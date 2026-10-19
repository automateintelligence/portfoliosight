"""The private research snapshot (protocol 4; Conductor plan task 6b.1).

Every test builds a throwaway mirror, a throwaway git repository and a throwaway destination root
in ``tmp_path``. The real mirror and the real checkout are never opened. The expectations are
restated here (explicit holiday lists, ``hashlib`` over the fixture bytes, the canonical-JSON rule),
not computed by calling the code under test.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "freeze_research_inputs.py"
D_STAR = "2026-10-16"
TSP = ["TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I"]
# fmt: off
EXAMPLE = [
    "VTI", "VTV", "VOE", "VB", "VBR", "VEA", "SCHF", "VWO", "VNQ", "VBIAX", "SCHO", "BND",
    "AGG", "TIP", "VTIP", "LQD", "VWOB", "PCY", "EFA", "LTPZ", "EDV", "VGSTX", "DBJP",
]
# fmt: on
MENU_FUNDS = TSP + EXAMPLE
RECORD_COLUMNS = ["date", "close", "tr_index", "div_cash", "split_factor"]
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@example.invalid",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}
# NYSE full-day closures in 2026 and 2027 (published by the exchange), written out by hand.
# fmt: off
HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3),
    date(2026, 5, 25), date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26),
    date(2027, 5, 31), date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6),
    date(2027, 11, 25), date(2027, 12, 24),
}
# fmt: on


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("freeze_research_inputs", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _load_script()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, env=GIT_ENV, check=True
    )
    return done.stdout.strip()


def _price_frame(index: int, last: str = D_STAR, first: str | None = None) -> pd.DataFrame:
    first = first or ("2026-01-05" if index % 2 else "2026-03-02")
    dates = pd.bdate_range(first, last)
    steps = np.arange(len(dates), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "close": 100.0 + index + 0.01 * steps,
            "tr_index": 1.0 + 0.001 * (index + 1) * steps,
            "div_cash": 0.0,
            "split_factor": 1.0,
        }
    )


def _write_price(mirror: Path, symbol: str, frame: pd.DataFrame) -> None:
    path = mirror / "prices" / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def make_mirror(base: Path, *, sgov: bool = True) -> Path:
    mirror = base / "mirror"
    entries = {}
    symbols = [*MENU_FUNDS, *(["SGOV"] if sgov else [])]
    for index, symbol in enumerate(symbols):
        _write_price(mirror, symbol, _price_frame(index))
        entries[symbol] = {
            "name": f"Fund {symbol}",
            "kind": "tsp" if symbol.startswith("TSP-") else "etf",
            "tier": 1,
            "source": "tsp" if symbol.startswith("TSP-") else "seed+tiingo",
            "first_date": "2026-01-05",
            "last_date": D_STAR,
            "adjusted_through": D_STAR,
            "status": "ok",
            "reason": None,
            "relies_on_yfinance": False,
        }
    meta = mirror / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "manifest.json").write_text(json.dumps({"symbols": entries}), encoding="utf-8")
    lake = {"generated_at": "2026-10-17T00:00:00+00:00", "symbols": {}}
    (meta / "lake.json").write_text(json.dumps(lake), encoding="utf-8")
    # A file the snapshot must not take.
    (meta / "budget.json").write_text("{}", encoding="utf-8")
    (mirror / "tensors").mkdir()
    (mirror / "tensors" / "5y.json").write_text("{}", encoding="utf-8")
    return mirror


def make_repo(base: Path, *, tsp: list[str] | None = None) -> Path:
    repo = base / "repo"
    (repo / "data").mkdir(parents=True)
    presets = {
        "presets": [
            {"id": "guide2017", "name": "Example Portfolio", "funds": EXAMPLE},
            {"id": "tsp", "name": "TSP (G, F, C, S, I)", "funds": tsp or TSP},
        ]
    }
    (repo / "data" / "presets.json").write_text(json.dumps(presets, indent=1), encoding="utf-8")
    _git(base, "init", "-q", "-b", "main", str(repo))
    _git(repo, "add", "data/presets.json")
    _git(repo, "commit", "-q", "-m", "presets")
    return repo


@pytest.fixture(scope="module")
def _mirror_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_mirror(tmp_path_factory.mktemp("mirror-template"))


@pytest.fixture(scope="module")
def _repo_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_repo(tmp_path_factory.mktemp("repo-template"))


@pytest.fixture
def mirror(_mirror_template: Path, tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "mirror"
    shutil.copytree(_mirror_template, path)
    yield path
    _make_writable(path)


@pytest.fixture
def repo(_repo_template: Path, tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    shutil.copytree(_repo_template, path, symlinks=True)
    return path


@pytest.fixture
def root(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "snapshots"
    yield path
    _make_writable(path)


def _make_writable(path: Path) -> None:
    if not path.exists():
        return
    for top, dirs, files in os.walk(path):
        for name in (*dirs, *files):
            (Path(top) / name).chmod(0o755)
    path.chmod(0o755)


def _freeze(script: ModuleType, mirror: Path, root: Path, repo: Path, **kwargs) -> Path:
    return script.freeze(mirror=mirror, root=root, repo=repo, **kwargs)


def _read_manifest(snapshot: Path) -> dict:
    return json.loads((snapshot / "snapshot.json").read_text(encoding="utf-8"))


def _tree(path: Path) -> dict[str, bytes]:
    return {
        p.relative_to(path).as_posix(): p.read_bytes()
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


# -------------------------------------------------------------------------- the copy itself


def test_snapshot_holds_exactly_the_listed_inputs_byte_for_byte(script, mirror, repo, root):
    snapshot = _freeze(script, mirror, root, repo)
    files = _tree(snapshot)
    expected = {f"prices/{s}.parquet" for s in [*MENU_FUNDS, "SGOV"]}
    expected |= {"meta/manifest.json", "meta/lake.json", "data/presets.json"}
    expected |= {"calendar/xnys_sessions.csv", "environment/dependency_lock.txt", "snapshot.json"}
    assert set(files) == expected
    for relative in sorted(expected):
        if relative.startswith(("prices/", "meta/")):
            assert files[relative] == (mirror / relative).read_bytes(), relative
    assert files["data/presets.json"] == (repo / "data" / "presets.json").read_bytes()


def test_presets_come_from_head_not_from_the_working_tree(script, mirror, repo, root):
    committed = (repo / "data" / "presets.json").read_bytes()
    (repo / "data" / "presets.json").write_text('{"presets": []}', encoding="utf-8")
    snapshot = _freeze(script, mirror, root, repo)
    assert (snapshot / "data" / "presets.json").read_bytes() == committed


def test_manifest_lists_every_file_with_independent_size_and_digest(script, mirror, repo, root):
    snapshot = _freeze(script, mirror, root, repo)
    manifest = _read_manifest(snapshot)
    listed = {entry["path"]: entry for entry in manifest["files"]}
    assert set(listed) == set(_tree(snapshot)) - {"snapshot.json"}
    assert [entry["path"] for entry in manifest["files"]] == sorted(listed)
    for relative, entry in listed.items():
        data = (snapshot / relative).read_bytes()
        assert entry["bytes"] == len(data), relative
        assert entry["sha256"] == hashlib.sha256(data).hexdigest(), relative
    assert listed["prices/VTI.parquet"]["origin"] == "mirror"
    assert listed["prices/VTI.parquet"]["source"] == "prices/VTI.parquet"
    assert listed["data/presets.json"]["origin"] == "repo_head"
    assert listed["calendar/xnys_sessions.csv"]["origin"] == "generated"


def test_directory_name_is_dstar_and_twelve_hex_of_the_canonical_manifest(
    script, mirror, repo, root
):
    snapshot = _freeze(script, mirror, root, repo)
    manifest = _read_manifest(snapshot)
    body = {k: v for k, v in manifest.items() if k not in ("created_utc", "manifest_sha256")}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert manifest["manifest_sha256"] == digest
    assert snapshot == root.resolve() / f"{D_STAR}-{digest[:12]}"
    assert re.fullmatch(r"2026-10-16-[0-9a-f]{12}", snapshot.name)


def test_manifest_records_provenance(script, mirror, repo, root):
    snapshot = _freeze(script, mirror, root, repo)
    manifest = _read_manifest(snapshot)
    assert manifest["d_star"] == D_STAR
    assert manifest["source_root"] == str(mirror.resolve())
    assert manifest["repo_head"] == _git(repo, "rev-parse", "HEAD")
    assert manifest["menus"] == {
        "tsp": {"preset": "tsp", "funds": TSP},
        "example": {"preset": "guide2017", "funds": EXAMPLE},
    }
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00", manifest["created_utc"]
    )
    assert manifest["python"]["version_string"] == f"Python {platform.python_version()}"
    assert manifest["python"]["version"] == platform.python_version()


def test_price_entries_carry_schema_dates_and_the_manifest_row(script, mirror, repo, root):
    snapshot = _freeze(script, mirror, root, repo)
    listed = {e["path"]: e for e in _read_manifest(snapshot)["files"]}
    record = listed["prices/VTI.parquet"]["record"]
    frame = pd.read_parquet(mirror / "prices" / "VTI.parquet")
    assert record["columns"] == [
        {"name": name, "dtype": str(frame[name].dtype)} for name in RECORD_COLUMNS
    ]
    assert [c["dtype"] for c in record["columns"]][1] == "float64"
    assert record["rows"] == len(frame)
    assert record["first_date"] == frame["date"].min().date().isoformat()
    assert record["last_date"] == D_STAR
    source = json.loads((mirror / "meta" / "manifest.json").read_text())["symbols"]["VTI"]
    assert record["manifest_entry"] == source
    assert "record" not in listed["meta/manifest.json"]


# -------------------------------------------------------------------------- risk-free files


def test_risk_free_availability_with_sgov(script, mirror, repo, root):
    manifest = _read_manifest(_freeze(script, mirror, root, repo))
    risk_free = manifest["risk_free"]
    tsp_g = pd.read_parquet(mirror / "prices" / "TSP-G.parquet")
    assert risk_free["order"] == ["SGOV", "TSP-G", "fallback"]
    assert risk_free["sgov"]["present"] is True
    assert risk_free["sgov"]["path"] == "prices/SGOV.parquet"
    assert risk_free["sgov"]["last_date"] == D_STAR
    assert risk_free["tsp_g"] == {
        "present": True,
        "path": "prices/TSP-G.parquet",
        "rows": len(tsp_g),
        "first_date": tsp_g["date"].min().date().isoformat(),
        "last_date": D_STAR,
    }


def test_missing_sgov_is_recorded_not_an_error(script, tmp_path, root):
    mirror = make_mirror(tmp_path, sgov=False)
    repo = make_repo(tmp_path)
    snapshot = _freeze(script, mirror, root, repo)
    manifest = _read_manifest(snapshot)
    assert manifest["risk_free"]["sgov"] == {"present": False, "path": None}
    assert manifest["risk_free"]["tsp_g"]["present"] is True
    assert not (snapshot / "prices" / "SGOV.parquet").exists()


# -------------------------------------------------------------------------- calendar and lock


def test_calendar_export_is_the_xnys_sessions_through_2027(script, mirror, repo, root):
    snapshot = _freeze(script, mirror, root, repo)
    lines = (snapshot / "calendar" / "xnys_sessions.csv").read_text().splitlines()
    assert lines[0] == "session"
    start, end = date(2026, 1, 1), date(2027, 12, 31)
    expected = [
        (start + timedelta(days=n)).isoformat()
        for n in range((end - start).days + 1)
        if (start + timedelta(days=n)).weekday() < 5 and (start + timedelta(days=n)) not in HOLIDAYS
    ]
    assert lines[1:] == expected
    calendar = _read_manifest(snapshot)["calendar"]
    assert calendar["name"] == "XNYS"
    assert calendar["library"] == "exchange_calendars"
    assert calendar["library_version"] == importlib.metadata.version("exchange_calendars")
    assert calendar["start"] == "2026-01-01"
    assert calendar["end"] == "2027-12-31"
    assert calendar["first_session"] == "2026-01-02"
    assert calendar["last_session"] == "2027-12-31"
    assert calendar["sessions"] == len(expected)
    assert calendar["file"] == "calendar/xnys_sessions.csv"


def test_calendar_starts_in_the_year_of_the_earliest_price_row(script, tmp_path, root):
    mirror = make_mirror(tmp_path)
    _write_price(mirror, "VTI", _price_frame(0, first="2024-03-01"))
    repo = make_repo(tmp_path)
    calendar = _read_manifest(_freeze(script, mirror, root, repo))["calendar"]
    assert calendar["start"] == "2024-01-01"
    assert calendar["first_session"] == "2024-01-02"


def test_calendar_end_before_2027_year_end_is_refused(script, mirror, repo, root):
    with pytest.raises(script.FreezeError, match="2027-12-31"):
        _freeze(script, mirror, root, repo, calendar_end=date(2027, 12, 30))
    assert not root.exists() or list(root.iterdir()) == []


def test_dependency_lock_is_a_freeze_with_python_and_head(script, mirror, repo, root):
    snapshot = _freeze(script, mirror, root, repo)
    text = (snapshot / "environment" / "dependency_lock.txt").read_text()
    lines = text.splitlines()
    head = _git(repo, "rev-parse", "HEAD")
    assert lines[:2] == [f"# python: Python {platform.python_version()}", f"# git HEAD: {head}"]
    packages = [line for line in lines if not line.startswith("#")]
    assert packages == sorted(packages, key=str.lower)
    pinned = {
        re.sub(r"[-_.]+", "-", p.split("==")[0]).lower(): p.split("==")[1]
        for p in packages
        if "==" in p
    }
    for name in ("numpy", "pandas", "pyarrow", "exchange_calendars"):
        assert pinned[re.sub(r"[-_.]+", "-", name).lower()] == importlib.metadata.version(name)
    assert all(re.fullmatch(r"-e \S+|\S+==\S+|\S+ @ \S+", p) for p in packages)
    manifest = _read_manifest(snapshot)
    assert manifest["dependency_lock"] == {
        "file": "environment/dependency_lock.txt",
        "packages": len(packages),
    }


# -------------------------------------------------------------------------- read-only


def test_every_file_and_directory_is_closed(script, mirror, repo, root):
    snapshot = _freeze(script, mirror, root, repo)
    paths = [snapshot, *snapshot.rglob("*")]
    assert len(paths) > 30
    for path in paths:
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode & 0o222 == 0, f"{path} is writable ({oct(mode)})"
        assert mode & 0o400, f"{path} is not readable by its owner"


def test_no_temporary_directory_is_left_beside_the_snapshot(script, mirror, repo, root):
    snapshot = _freeze(script, mirror, root, repo)
    assert [p.name for p in root.iterdir()] == [snapshot.name]


# -------------------------------------------------------------------------- idempotence


def test_second_run_on_unchanged_inputs_returns_the_same_untouched_snapshot(
    script, mirror, repo, root
):
    first = _freeze(script, mirror, root, repo)
    before = _tree(first)
    first_mtime = first.stat().st_mtime_ns
    second = _freeze(script, mirror, root, repo)
    assert second == first
    assert _tree(first) == before
    assert first.stat().st_mtime_ns == first_mtime
    assert [p.name for p in root.iterdir()] == [first.name]


def test_changed_mirror_makes_a_second_snapshot_beside_the_first(script, mirror, repo, root):
    first = _freeze(script, mirror, root, repo)
    _write_price(mirror, "VTI", _price_frame(99))
    second = _freeze(script, mirror, root, repo)
    assert second != first
    assert second.name.startswith(f"{D_STAR}-")
    assert sorted(p.name for p in root.iterdir()) == sorted([first.name, second.name])


def test_existing_directory_with_a_changed_byte_is_refused_and_left_alone(
    script, mirror, repo, root
):
    snapshot = _freeze(script, mirror, root, repo)
    target = snapshot / "prices" / "VTI.parquet"
    snapshot.joinpath("prices").chmod(0o755)
    target.chmod(0o644)
    data = bytearray(target.read_bytes())
    data[-1] ^= 0xFF
    target.write_bytes(bytes(data))
    with pytest.raises(script.FreezeError, match="different contents") as caught:
        _freeze(script, mirror, root, repo)
    assert "prices/VTI.parquet" in str(caught.value)
    assert target.read_bytes() == bytes(data)
    assert [p.name for p in root.iterdir()] == [snapshot.name]


def test_existing_directory_with_an_extra_file_is_refused(script, mirror, repo, root):
    snapshot = _freeze(script, mirror, root, repo)
    snapshot.chmod(0o755)
    (snapshot / "stray.txt").write_text("x", encoding="utf-8")
    with pytest.raises(script.FreezeError, match="different contents") as caught:
        _freeze(script, mirror, root, repo)
    assert "stray.txt" in str(caught.value)


# -------------------------------------------------------------------------- hash failures


def _corrupt_copy(script: ModuleType, monkeypatch, symbol: str) -> None:
    original = script._copy_input

    def corrupting(source, destination: Path) -> None:
        original(source, destination)
        if destination.name == f"{symbol}.parquet":
            data = bytearray(destination.read_bytes())
            data[len(data) // 2] ^= 0x01
            destination.write_bytes(bytes(data))

    monkeypatch.setattr(script, "_copy_input", corrupting)


def test_a_byte_changed_between_hashing_and_copying_is_a_hard_error(
    script, mirror, repo, root, monkeypatch
):
    _corrupt_copy(script, monkeypatch, "BND")
    with pytest.raises(script.FreezeError, match=r"prices/BND\.parquet.*copy") as caught:
        _freeze(script, mirror, root, repo)
    assert caught.value.code == 4
    assert list(root.iterdir()) == []


def test_a_source_that_changes_during_the_run_is_a_hard_error(
    script, mirror, repo, root, monkeypatch
):
    original = script._copy_input

    def mutating(source, destination: Path) -> None:
        original(source, destination)
        if destination.name == "VTI.parquet":
            path = mirror / "prices" / "VTI.parquet"
            path.write_bytes(path.read_bytes() + b"\0")

    monkeypatch.setattr(script, "_copy_input", mutating)
    with pytest.raises(script.FreezeError, match=r"prices/VTI\.parquet.*changed") as caught:
        _freeze(script, mirror, root, repo)
    assert caught.value.code == 4
    assert list(root.iterdir()) == []


def test_a_source_that_changes_after_hashing_before_copy_is_a_hard_error(
    script, mirror, repo, root, monkeypatch
):
    original = script._copy_input

    def racing(source, destination: Path) -> None:
        if destination.name == "SCHO.parquet":
            path = mirror / "prices" / "SCHO.parquet"
            data = bytearray(path.read_bytes())
            data[10] ^= 0x01
            path.write_bytes(bytes(data))
        original(source, destination)

    monkeypatch.setattr(script, "_copy_input", racing)
    with pytest.raises(script.FreezeError, match=r"prices/SCHO\.parquet"):
        _freeze(script, mirror, root, repo)
    assert list(root.iterdir()) == []


def test_the_mirror_is_never_written(script, mirror, repo, root):
    def stamp() -> dict[str, tuple[int, int, int]]:
        return {
            p.relative_to(mirror).as_posix(): (
                p.stat().st_mtime_ns,
                p.stat().st_size,
                p.stat().st_mode,
            )
            for p in sorted(mirror.rglob("*"))
        } | {".": (mirror.stat().st_mtime_ns, 0, mirror.stat().st_mode)}

    for path in [mirror, *mirror.rglob("*")]:
        path.chmod(path.stat().st_mode & ~0o222)
    closed = stamp()
    _freeze(script, mirror, root, repo)
    assert stamp() == closed


# ------------------------------------------------------------------- missing and invalid input


@pytest.mark.parametrize(
    "relative",
    ["prices/VWOB.parquet", "prices/TSP-G.parquet", "meta/manifest.json", "meta/lake.json"],
)
def test_a_missing_required_file_is_named_and_nothing_is_left(script, mirror, repo, root, relative):
    (mirror / relative).unlink()
    with pytest.raises(script.FreezeError, match=re.escape(relative)) as caught:
        _freeze(script, mirror, root, repo)
    assert caught.value.code == 3
    assert not root.exists() or list(root.iterdir()) == []


def test_every_missing_file_is_named(script, mirror, repo, root):
    (mirror / "prices" / "VWOB.parquet").unlink()
    (mirror / "meta" / "lake.json").unlink()
    with pytest.raises(script.FreezeError) as caught:
        _freeze(script, mirror, root, repo)
    assert "prices/VWOB.parquet" in str(caught.value)
    assert "meta/lake.json" in str(caught.value)


def test_a_missing_mirror_is_refused(script, tmp_path, repo, root):
    with pytest.raises(script.FreezeError, match="mirror"):
        _freeze(script, tmp_path / "nowhere", root, repo)


def test_a_menu_fund_without_a_manifest_row_is_refused(script, mirror, repo, root):
    path = mirror / "meta" / "manifest.json"
    manifest = json.loads(path.read_text())
    del manifest["symbols"]["EDV"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(script.FreezeError, match="EDV") as caught:
        _freeze(script, mirror, root, repo)
    assert caught.value.code == 3


def test_a_price_file_with_other_columns_is_refused(script, mirror, repo, root):
    frame = _price_frame(3).drop(columns=["tr_index"])
    _write_price(mirror, "AGG", frame)
    with pytest.raises(script.FreezeError, match=r"AGG.*columns") as caught:
        _freeze(script, mirror, root, repo)
    assert caught.value.code == 3
    assert list(root.iterdir()) == []


def test_a_menu_fund_that_stops_before_dstar_is_refused(script, mirror, repo, root):
    _write_price(mirror, "PCY", _price_frame(5, last="2026-10-15"))
    with pytest.raises(script.FreezeError, match=r"PCY.*2026-10-15.*2026-10-16") as caught:
        _freeze(script, mirror, root, repo)
    assert caught.value.code == 3


def test_rows_after_dstar_are_kept_and_recorded(script, mirror, repo, root):
    _write_price(mirror, "PCY", _price_frame(5, last="2026-10-19"))
    snapshot = _freeze(script, mirror, root, repo)
    listed = {e["path"]: e for e in _read_manifest(snapshot)["files"]}
    assert listed["prices/PCY.parquet"]["record"]["last_date"] == "2026-10-19"


def test_an_empty_price_file_is_refused(script, mirror, repo, root):
    _write_price(mirror, "TIP", _price_frame(1).iloc[0:0])
    with pytest.raises(script.FreezeError, match="TIP"):
        _freeze(script, mirror, root, repo)


def test_presets_that_differ_from_the_protocol_menu_are_refused(script, tmp_path, mirror, root):
    repo = make_repo(tmp_path, tsp=["TSP-G", "TSP-F", "TSP-C", "TSP-I", "TSP-S"])
    with pytest.raises(script.FreezeError, match=r"tsp.*protocol") as caught:
        _freeze(script, mirror, root, repo)
    assert caught.value.code == 3


def test_a_repo_without_presets_at_head_is_refused(script, tmp_path, mirror, root):
    repo = tmp_path / "bare"
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    (repo / "README").write_text("x", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-q", "-m", "x")
    with pytest.raises(script.FreezeError, match=r"data/presets\.json"):
        _freeze(script, mirror, root, repo)


# -------------------------------------------------------------------------- unsafe destinations


def test_destination_inside_the_repository_is_refused(script, mirror, repo, tmp_path):
    for inside in (repo / "snapshots", repo / "data" / "deep" / "er", repo):
        with pytest.raises(script.FreezeError, match="repository") as caught:
            _freeze(script, mirror, inside, repo)
        assert caught.value.code == 2
    assert not (repo / "snapshots").exists()
    assert not (repo / "data" / "deep").exists()


def test_destination_inside_a_linked_worktree_of_the_repository_is_refused(
    script, mirror, repo, tmp_path
):
    worktree = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "other", str(worktree))
    with pytest.raises(script.FreezeError, match="repository") as caught:
        _freeze(script, mirror, worktree / "out", repo)
    assert caught.value.code == 2
    assert not (worktree / "out").exists()


def test_destination_inside_the_mirror_is_refused(script, mirror, repo):
    for inside in (mirror, mirror / "meta", mirror / "new" / "dir"):
        with pytest.raises(script.FreezeError, match="mirror") as caught:
            _freeze(script, mirror, inside, repo)
        assert caught.value.code == 2
    assert not (mirror / "new").exists()
    assert sorted(p.name for p in mirror.iterdir()) == ["meta", "prices", "tensors"]


def test_a_symbolic_link_into_the_repository_is_resolved_and_refused(
    script, mirror, repo, tmp_path
):
    (repo / "inside").mkdir()
    link = tmp_path / "link"
    link.symlink_to(repo / "inside")
    with pytest.raises(script.FreezeError, match="repository"):
        _freeze(script, mirror, link / "out", repo)
    assert list((repo / "inside").iterdir()) == []


def test_a_destination_beside_the_repository_and_mirror_is_accepted(script, mirror, repo, tmp_path):
    try:
        snapshot = _freeze(script, mirror, tmp_path / "elsewhere" / "deeper", repo)
        assert snapshot.is_dir()
    finally:
        _make_writable(tmp_path / "elsewhere")


# -------------------------------------------------------------------------- command line


def test_main_prints_the_path_and_returns_zero(script, mirror, repo, root, capsys):
    argv = ["--mirror", str(mirror), "--root", str(root), "--repo", str(repo)]
    assert script.main(argv) == 0
    printed = capsys.readouterr().out.splitlines()
    assert len(printed) == 1
    assert Path(printed[0]).is_dir() and Path(printed[0]).parent == root.resolve()
    assert script.main(argv) == 0
    assert capsys.readouterr().out.splitlines() == printed


def test_main_reports_a_refusal_on_stderr_with_its_code(script, mirror, repo, root, capsys):
    (mirror / "meta" / "lake.json").unlink()
    argv = ["--mirror", str(mirror), "--root", str(root), "--repo", str(repo)]
    assert script.main(argv) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "meta/lake.json" in captured.err


def test_defaults_are_the_protocol_values(script):
    assert script.D_STAR == date(2026, 10, 16)
    assert script.DEFAULT_MIRROR == Path("/mnt/d/portfoliosight-data")
    assert script.DEFAULT_ROOT == Path.home() / "portfoliosight-research" / "snapshots"
    assert script.MIN_CALENDAR_END == date(2027, 12, 31)
    assert script.TSP_MENU == tuple(TSP)
    assert script.EXAMPLE_MENU == tuple(EXAMPLE)
