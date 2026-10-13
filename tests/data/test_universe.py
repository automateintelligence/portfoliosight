"""Universe tiers, the nightly priority order and the presets (spec 5.2, Appendix A)."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from portfoliosight.data import universe

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "docs" / "specs" / "2026-10-13-portfoliosight-demo-design.md"
STEP2 = ROOT / "data" / "holdings" / "holdings_guide2017_step2.csv"
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


def test_tier3_is_the_unchanged_qse_core_list():
    tiers = universe.load_tiers()
    assert len(tiers.tier3) == 1038
    overlap = set(tiers.tier3) & set(tiers.tier2)
    assert len(tiers.tier3_only()) == 1038 - len(overlap)
    assert not set(tiers.tier3_only()) & set(tiers.tier2)
    assert {"VTI", "SGOV", "AGG"} <= overlap


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


def test_presets_match_appendix_a():
    presets = {preset.id: preset for preset in universe.load_presets()}
    assert list(presets) == ["guide2017", "tsp"]
    guide, tsp = presets["guide2017"], presets["tsp"]
    assert guide.name == "The 2017 guide portfolio"
    assert list(guide.funds) == _step2_symbols()
    assert guide.allocation is not None and guide.allocation_unit == "$"
    assert guide.allocation["VTI"] == 10840.0 and guide.allocation["FIENX"] == 0.0
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
