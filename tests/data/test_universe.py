"""Universe tiers, the nightly priority order and the presets (spec 5.2, Appendix A)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from portfoliosight.data import universe

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs" / "specs" / "2026-10-13-portfoliosight-demo-design.md"
STEP2 = ROOT / "data" / "holdings" / "holdings_guide2017_step2.csv"
QSE_CORE = ROOT / "data" / "universes" / "qse_core.txt"
QSE_PORTFOLIOSIGHT = ROOT / "data" / "universes" / "qse_portfoliosight.txt"
TSP_IDS = (
    "TSP-G TSP-F TSP-C TSP-S TSP-I TSP-LINC TSP-L2030 TSP-L2035 TSP-L2040 TSP-L2045 TSP-L2050 "
    "TSP-L2055 TSP-L2060 TSP-L2065 TSP-L2070 TSP-L2075"
).split()
INCOME_MUTUAL_FUNDS = (
    "VBTLX VBMFX VBILX VBIRX VBLAX VSIGX VSCSX VTAPX VIPSX VWEHX VWINX FXNAX FTBFX FUAMX FIPDX "
    "SWAGX SWRSX DODIX PTTAX PTTRX PONAX MWTRX BCOIX LSBDX"
).split()


def _appendix_a_groups() -> dict[str, list[str]]:
    """The tier 2 groups exactly as spec Appendix A lists them."""
    text = SPEC.read_text(encoding="utf-8")
    block = text[text.index("US equity ETFs:") : text.index("TSP (from tsp.gov")]
    groups = {}
    for line in block.strip().splitlines():
        name, symbols = line.split(":", 1)
        groups[name.strip()] = symbols.split()
    return groups


def _file_symbols(path: Path) -> list[str]:
    return [symbol for symbol, _ in universe.parse_universe_lines(path.read_text(encoding="utf-8"))]


def _step2_symbols() -> list[str]:
    with STEP2.open(newline="") as handle:
        return [row["Symbol"] for row in csv.DictReader(handle)]


def test_tier1_is_the_step2_funds_then_the_tsp_funds():
    tiers = universe.load_tiers()
    step2 = _step2_symbols()
    assert len(step2) == 23
    assert list(tiers.tier1) == step2 + TSP_IDS
    assert list(universe.TSP_FUNDS) == TSP_IDS
    assert universe.TSP_FUNDS["TSP-LINC"] == "L Income" and universe.TSP_FUNDS["TSP-G"] == "G Fund"


def test_tier2_is_appendix_a_with_income_tags():
    tiers = universe.load_tiers()
    groups = _appendix_a_groups()
    listed = [symbol for symbols in groups.values() for symbol in symbols]
    assert list(tiers.tier2) == listed
    assert len(set(listed)) == len(listed) == 317
    assert set(_step2_symbols()) <= set(tiers.tier2)
    assert len(INCOME_MUTUAL_FUNDS) == 24
    assert tiers.income == frozenset(groups["Bond ETFs"]) | frozenset(INCOME_MUTUAL_FUNDS)
    assert "VTI" not in tiers.income and "SGOV" in tiers.income and "VBTLX" in tiers.income


def test_tier3_is_the_qse_core_list_then_the_qse_portfoliosight_list():
    tiers = universe.load_tiers()
    core, added = _file_symbols(QSE_CORE), _file_symbols(QSE_PORTFOLIOSIGHT)
    assert len(core) == 1038 and len(added) == 358 == len(set(added))
    assert not set(core) & set(added)
    assert list(tiers.tier3) == core + added
    overlap = set(tiers.tier3) & set(tiers.tier2)
    assert len(tiers.tier3_only()) == 1038 + 358 - len(overlap)
    assert not set(tiers.tier3_only()) & set(tiers.tier2)
    assert {"VTI", "SGOV", "AGG", "IWB"} <= overlap  # IWB is in the added list and in tier 2
    assert list(tiers.tier3_only()[-3:]) == ["XRAY", "YETI", "ZION"]


def test_the_starter_slice_stays_inside_the_qse_core_list():
    tiers = universe.load_tiers()
    core, added = _file_symbols(QSE_CORE), _file_symbols(QSE_PORTFOLIOSIGHT)
    tier2 = set(tiers.tier2)
    core_only = [s for s in core if s not in tier2]
    added_only = [s for s in added if s not in tier2]
    assert universe.priority_order("starter", tiers, only_tiers=(3,)) == core_only[:130]
    assert not set(added_only) & set(universe.priority_order("starter", tiers))
    # Power walks them last; the walk itself spends nothing on a symbol the lake keeps.
    assert universe.priority_order("power", tiers, only_tiers=(3,)) == core_only + added_only


def test_priority_order_starter_and_power():
    tiers = universe.load_tiers()
    starter = universe.priority_order("starter", tiers)
    power = universe.priority_order("power", tiers)
    assert len(starter) == len(set(starter)) and len(power) == len(set(power))

    n1 = len(tiers.tier1)
    assert starter[:n1] == list(tiers.tier1)
    tier1 = set(tiers.tier1)
    income = [s for s in tiers.tier2 if s in tiers.income and s not in tier1]
    rest = [s for s in tiers.tier2 if s not in tiers.income and s not in tier1]
    assert starter[n1 : n1 + len(income)] == income
    assert starter[n1 + len(income) : n1 + len(income) + len(rest)] == rest
    slice_ = starter[n1 + len(income) + len(rest) :]
    assert slice_ == list(tiers.tier3_only()[:130]) and len(slice_) == 130
    assert power[: len(starter) - 130] == starter[:-130]
    assert power[len(starter) - 130 :] == list(tiers.tier3_only())
    # Provider symbols kept current on Starter stay inside the 450 unique-symbols budget.
    assert len([s for s in starter if not universe.is_tsp(s)]) == 317 + 130 <= 450


def test_priority_order_can_be_limited_to_tiers():
    tiers = universe.load_tiers()
    assert universe.priority_order("starter", tiers, only_tiers=(1,)) == list(tiers.tier1)
    only3 = universe.priority_order("starter", tiers, only_tiers=(3,))
    assert only3 == list(tiers.tier3_only()[:130])
    only2 = universe.priority_order("starter", tiers, only_tiers=(2,))
    assert set(only2) == set(tiers.tier2) - set(tiers.tier1)


def test_symbol_info_takes_the_lowest_tier():
    info = universe.load_tiers().info()
    assert info["VTI"] == universe.SymbolInfo("VTI", 1, False, None)
    assert info["BND"].tier == 1 and info["BND"].income is True
    assert info["SGOV"] == universe.SymbolInfo("SGOV", 2, True, None)
    assert info["TSP-G"] == universe.SymbolInfo("TSP-G", 1, False, "tsp")
    assert info["A"] == universe.SymbolInfo("A", 3, False, "stock")
    assert info["ZION"] == universe.SymbolInfo("ZION", 3, False, "stock")  # the added list
    assert info["IWB"].tier == 2  # in both: the lowest tier wins
    assert info["EFA"] == universe.SymbolInfo("EFA", 1, False, None)
    assert info["FIENX"] == universe.SymbolInfo("FIENX", 2, False, None, "converted to an ETF")
    assert [s for s, known in info.items() if known.note] == ["FIENX"]


def test_universe_lines_parse_comments_tags_and_case():
    text = "# group\nvti\nBND,income  # bond\n\n  sgov , INCOME\n"
    assert universe.parse_universe_lines(text) == [("VTI", False), ("BND", True), ("SGOV", True)]
    with pytest.raises(ValueError, match="unknown tag"):
        universe.parse_universe_lines("VTI,growth\n")


def test_duplicate_symbols_are_refused(tmp_path):
    base = tmp_path / "data" / "universes"
    base.mkdir(parents=True)
    (tmp_path / "data" / "h.csv").write_text("Account,Symbol,Description,Qty,Price\nx,VTI,d,1,1\n")
    (base / "t2.txt").write_text("VTI\nVTI\n")
    (base / "t3.txt").write_text("A\n")
    (base / "tiers.json").write_text(
        '{"tiers": [{"tier": 1, "holdings": "data/h.csv"}, '
        '{"tier": 2, "file": "data/universes/t2.txt"}, '
        '{"tier": 3, "file": "data/universes/t3.txt"}]}'
    )
    with pytest.raises(ValueError, match="duplicate symbol VTI"):
        universe.load_tiers(base / "tiers.json")
    (base / "tiers.json").write_text('{"tiers": [{"tier": 1, "holdings": "data/h.csv"}]}')
    with pytest.raises(ValueError, match="tiers 1, 2 and 3"):
        universe.load_tiers(base / "tiers.json")


def _universe_config(tmp_path, tier3: dict, **files: str) -> Path:
    """A tiers.json under ``tmp_path`` whose tier 3 entry is ``tier3`` and whose files are given."""
    base = tmp_path / "data" / "universes"
    base.mkdir(parents=True)
    (tmp_path / "data" / "h.csv").write_text("Account,Symbol,Description,Qty,Price\nx,VTI,d,1,1\n")
    (base / "t2.txt").write_text("VTI\nBND,income\n")
    for name, text in files.items():
        (base / f"{name}.txt").write_text(text)
    config = {
        "tiers": [
            {"tier": 1, "holdings": "data/h.csv"},
            {"tier": 2, "file": "data/universes/t2.txt"},
            {"tier": 3, **tier3},
        ]
    }
    (base / "tiers.json").write_text(json.dumps(config))
    return base / "tiers.json"


def test_a_tier_takes_one_file_or_a_list_of_files(tmp_path):
    one = _universe_config(tmp_path / "one", {"file": "data/universes/a.txt"}, a="A\nB\n")
    assert universe.load_tiers(one).tier3 == ("A", "B")
    many = _universe_config(
        tmp_path / "many", {"files": ["data/universes/a.txt"], "starter_slice": 7}, a="A\nB\n"
    )
    loaded = universe.load_tiers(many)
    assert loaded.tier3 == ("A", "B") and loaded.starter_slice == 7


def test_tier3_files_are_joined_in_order_without_duplicates(tmp_path):
    path = _universe_config(
        tmp_path,
        {"files": ["data/universes/a.txt", "data/universes/b.txt"]},
        a="A\nVTI\nB,income\n",
        b="C\nA\nD\nB\n",
    )
    tiers = universe.load_tiers(path)
    assert tiers.tier3 == ("A", "VTI", "B", "C", "D")  # the first file's place wins
    assert tiers.tier3_only() == ("A", "B", "C", "D")  # tier 2's VTI stays out
    assert tiers.income == frozenset({"BND", "B"})
    info = tiers.info()
    assert info["VTI"].tier == 1 and info["D"] == universe.SymbolInfo("D", 3, False, "stock")


def test_a_duplicate_inside_one_tier3_file_is_still_refused(tmp_path):
    path = _universe_config(
        tmp_path,
        {"files": ["data/universes/a.txt", "data/universes/b.txt"]},
        a="A\n",
        b="C\nC\n",
    )
    with pytest.raises(ValueError, match=r"b\.txt: duplicate symbol C"):
        universe.load_tiers(path)


@pytest.mark.parametrize(
    "tier3",
    [
        {},
        {"files": []},
        {"files": "data/universes/a.txt"},
        {"file": "data/universes/a.txt", "files": ["data/universes/a.txt"]},
    ],
)
def test_a_tier_needs_exactly_one_of_file_and_files(tmp_path, tier3):
    path = _universe_config(tmp_path, tier3, a="A\n")
    with pytest.raises(ValueError, match=r"tier 3 .*'file' or .*'files'"):
        universe.load_tiers(path)


def test_presets_match_appendix_a():
    presets = {preset.id: preset for preset in universe.load_presets()}
    assert list(presets) == ["guide2017", "tsp"]
    guide, tsp = presets["guide2017"], presets["tsp"]
    assert guide.name == "Example Portfolio"
    assert list(guide.funds) == _step2_symbols()
    assert guide.allocation is not None and guide.allocation_unit == "$"
    assert guide.allocation["VTI"] == 10840.0 and guide.allocation["EFA"] == 0.0
    assert "FIENX" not in guide.funds
    assert sum(1 for amount in guide.allocation.values() if amount > 0) == 18
    assert sum(1 for amount in guide.allocation.values() if amount == 0) == 5
    assert tsp.name == "TSP (G, F, C, S, I)"
    assert list(tsp.funds) == ["TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I"]
    assert tsp.allocation is None and tsp.allocation_unit is None
    spec = SPEC.read_text(encoding="utf-8")
    for preset in (guide, tsp):
        assert re.search(re.escape(f'"{preset.name}"'), spec), preset.name


def test_preset_fund_missing_from_holdings_is_refused(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "h.csv").write_text("Account,Symbol,Description,Qty,Price\nx,VTI,d,2,3\n")
    presets = tmp_path / "data" / "presets.json"
    presets.write_text(
        '{"presets": [{"id": "p", "name": "P", "funds": ["VTI", "BND"], '
        '"allocation_source": "data/h.csv"}]}'
    )
    with pytest.raises(ValueError, match="BND"):
        universe.load_presets(presets)
