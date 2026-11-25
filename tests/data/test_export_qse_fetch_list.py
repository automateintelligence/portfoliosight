"""The export of QSE's second fetch list (spec 2026-11-16 section 4)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from portfoliosight.data.universe import Tiers, load_tiers, parse_universe_lines
from tests.data.test_sync_lake import _load_script

export = _load_script("export_qse_fetch_list")

ROOT = Path(__file__).resolve().parents[2]
UNIVERSES = ROOT / "data" / "universes"


def _symbols(path: Path) -> list[str]:
    return [s for s, _ in parse_universe_lines(path.read_text(encoding="utf-8"))]


@pytest.fixture(scope="module")
def committed():
    """``(tiers, QSE's current list, QSE's core list)`` as committed."""
    return (
        load_tiers(),
        _symbols(UNIVERSES / "qse_portfoliosight.txt"),
        _symbols(UNIVERSES / "qse_core.txt"),
    )


def test_export_on_the_committed_lists(committed):
    tiers, current, core = committed
    out = export.fetch_list(current, tiers, core)
    assert len(out) == 629
    assert out == sorted(set(out))
    assert set(current) <= set(out)
    assert not [s for s in out if s.startswith("TSP-")]
    assert "FIENX" not in out
    assert not set(out) & set(core)
    assert {"VTSAX", "VTV", "NSRGY"} <= set(out)
    assert not {"WMT", "FCX", "TSM"} & set(out)  # on the core list already


def _write_universe(base: Path) -> Path:
    """A small universe under ``base``; returns its tiers file."""
    universes = base / "data" / "universes"
    universes.mkdir(parents=True)
    (base / "data" / "h.csv").write_text("Account,Symbol,Description,Qty,Price\nx,VTI,d,1,1\n")
    (universes / "t2.txt").write_text("VTI\nAAPL\nTSP-G\nGONE\n")
    (universes / "t3.txt").write_text("AAPL\n")
    (universes / "requested.txt").write_text("# a request log\nFCX\nNEWT\n")
    (universes / "qse_current.txt").write_text("# a comment\nZTS\nADC\n")
    (universes / "qse_core.txt").write_text("AAPL\nFCX\n")
    config = {
        "tiers": [
            {"tier": 1, "holdings": "data/h.csv"},
            {"tier": 2, "file": "data/universes/t2.txt"},
            {
                "tier": 3,
                "files": ["data/universes/t3.txt", "data/universes/requested.txt"],
                "requested": "data/universes/requested.txt",
            },
        ],
        "notes": {"GONE": "data ended"},
    }
    tiers_file = universes / "tiers.json"
    tiers_file.write_text(json.dumps(config))
    return tiers_file


def test_export_on_a_small_universe(tmp_path, capsys):
    tiers = Tiers(
        tier1=("VTI", "TSP-G"),
        tier2=("VTI", "AAPL", "TSP-G", "GONE"),
        tier3=("AAPL", "FCX", "NEWT"),
        income=frozenset(),
        starter_slice=130,
        notes={"GONE": "data ended"},
        requested=("FCX", "NEWT"),
    )
    assert export.wanted_symbols(tiers) == {"VTI", "AAPL", "FCX", "NEWT"}
    out = export.fetch_list(["ADC", "ZTS"], tiers, ["AAPL", "FCX"])
    assert out == ["ADC", "NEWT", "VTI", "ZTS"]

    # The command gives the same list from files, and with --new-only only what QSE lacks.
    tiers_file = _write_universe(tmp_path)
    base = tiers_file.parent
    args = [
        "--tiers-file",
        str(tiers_file),
        "--qse-file",
        str(base / "qse_current.txt"),
        "--core-file",
        str(base / "qse_core.txt"),
    ]
    assert export.main(args) == 0
    assert capsys.readouterr().out.splitlines() == ["ADC", "NEWT", "VTI", "ZTS"]
    assert export.main([*args, "--new-only"]) == 0
    assert capsys.readouterr().out.splitlines() == ["NEWT", "VTI"]
    target = tmp_path / "out.txt"
    assert export.main([*args, "--new-only", "--out", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == "NEWT\nVTI\n"
    assert capsys.readouterr().out == ""


def test_adding_a_line_to_requested_txt_reaches_the_export(tmp_path, capsys):
    shutil.copytree(UNIVERSES, tmp_path / "data" / "universes")
    shutil.copy(ROOT / "data" / "presets.json", tmp_path / "data" / "presets.json")
    holdings = tmp_path / "data" / "holdings"
    holdings.mkdir()
    shutil.copy(ROOT / "data" / "holdings" / "holdings_guide2017_step2.csv", holdings)
    base = tmp_path / "data" / "universes"
    args = [
        "--tiers-file",
        str(base / "tiers.json"),
        "--qse-file",
        str(base / "qse_portfoliosight.txt"),
        "--core-file",
        str(base / "qse_core.txt"),
    ]
    assert export.main(args) == 0
    before = capsys.readouterr().out.splitlines()
    assert len(before) == 629 and "ZZNEW" not in before

    with (base / "requested.txt").open("a", encoding="utf-8") as handle:
        handle.write("ZZNEW\n")
    assert export.main(args) == 0
    after = capsys.readouterr().out.splitlines()
    assert after == sorted([*before, "ZZNEW"])
    assert export.main([*args, "--new-only"]) == 0
    assert "ZZNEW" in capsys.readouterr().out.splitlines()


def test_the_committed_export_is_629_symbols_and_273_new(capsys):
    assert export.main([]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 629
    assert export.main(["--new-only"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 273


def test_help_states_the_four_steps_for_adding_a_ticker(capsys):
    with pytest.raises(SystemExit) as stopped:
        export.main(["--help"])
    assert stopped.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "requested.txt" in text and "pull request" in text
    for step in ("1.", "2.", "3.", "4."):
        assert step in text
