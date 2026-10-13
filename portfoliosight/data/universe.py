"""The served universe by tier, the nightly priority order and the presets (spec 5.2)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
TIERS_FILE = REPO_ROOT / "data" / "universes" / "tiers.json"
PRESETS_FILE = REPO_ROOT / "data" / "presets.json"

PlanTier = Literal["starter", "power"]

TSP_FUNDS: dict[str, str] = {
    "TSP-G": "G Fund",
    "TSP-F": "F Fund",
    "TSP-C": "C Fund",
    "TSP-S": "S Fund",
    "TSP-I": "I Fund",
    "TSP-LINC": "L Income",
    "TSP-L2030": "L 2030",
    "TSP-L2035": "L 2035",
    "TSP-L2040": "L 2040",
    "TSP-L2045": "L 2045",
    "TSP-L2050": "L 2050",
    "TSP-L2055": "L 2055",
    "TSP-L2060": "L 2060",
    "TSP-L2065": "L 2065",
    "TSP-L2070": "L 2070",
    "TSP-L2075": "L 2075",
}


@dataclass(frozen=True)
class SymbolInfo:
    """What the universe files say about one symbol."""

    id: str
    tier: int
    income: bool
    kind: str | None  # "tsp", "stock", or None when the provider's meta decides (etf/mutual fund)


@dataclass(frozen=True)
class Tiers:
    tier1: tuple[str, ...]  # the 23 Step 2 funds, then the 16 TSP funds
    tier2: tuple[str, ...]  # file order
    tier3: tuple[str, ...]  # file order, tier 2 symbols included as the file has them
    income: frozenset[str]
    starter_slice: int

    def tier3_only(self) -> tuple[str, ...]:
        """Tier 3 lines that are not already in tier 2, in file order."""
        tier2 = set(self.tier2)
        return tuple(s for s in self.tier3 if s not in tier2)

    def info(self) -> dict[str, SymbolInfo]:
        """Every symbol of every tier with its lowest tier."""
        out: dict[str, SymbolInfo] = {}
        for tier, symbols in ((1, self.tier1), (2, self.tier2), (3, self.tier3)):
            for symbol in symbols:
                if symbol in out:
                    continue
                if is_tsp(symbol):
                    kind = "tsp"
                elif tier == 3:
                    kind = "stock"
                else:
                    kind = None
                out[symbol] = SymbolInfo(symbol, tier, symbol in self.income, kind)
        return out


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    funds: tuple[str, ...]
    allocation: dict[str, float] | None
    allocation_unit: str | None


def is_tsp(symbol: str) -> bool:
    return symbol.startswith("TSP-")


def parse_universe_lines(text: str) -> list[tuple[str, bool]]:
    """``(SYMBOL, income)`` per line; ``#`` starts a comment, ``,income`` tags a fund."""
    out: list[tuple[str, bool]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        tags = {p.lower() for p in parts[1:] if p}
        unknown = tags - {"income"}
        if unknown:
            raise ValueError(f"unknown tag(s) {sorted(unknown)} on universe line {raw!r}")
        out.append((parts[0].upper(), "income" in tags))
    return out


def _holdings_symbols(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [row["Symbol"].strip().upper() for row in csv.DictReader(handle)]


def _unique(symbols: list[str], source: Path) -> tuple[str, ...]:
    seen: set[str] = set()
    for symbol in symbols:
        if symbol in seen:
            raise ValueError(f"{source.name}: duplicate symbol {symbol}")
        seen.add(symbol)
    return tuple(symbols)


def load_tiers(tiers_file: Path = TIERS_FILE) -> Tiers:
    root = tiers_file.resolve().parents[2]
    config = json.loads(tiers_file.read_text(encoding="utf-8"))
    by_tier = {int(item["tier"]): item for item in config["tiers"]}
    if sorted(by_tier) != [1, 2, 3]:
        raise ValueError(f"{tiers_file.name} must list tiers 1, 2 and 3, found {sorted(by_tier)}")

    holdings = root / by_tier[1]["holdings"]
    tier1 = _holdings_symbols(holdings)
    if by_tier[1].get("tsp"):
        tier1 += list(TSP_FUNDS)
    income: set[str] = set()
    files: dict[int, tuple[str, ...]] = {}
    for tier in (2, 3):
        path = root / by_tier[tier]["file"]
        lines = parse_universe_lines(path.read_text(encoding="utf-8"))
        files[tier] = _unique([symbol for symbol, _ in lines], path)
        income.update(symbol for symbol, tagged in lines if tagged)
    return Tiers(
        tier1=_unique(tier1, holdings),
        tier2=files[2],
        tier3=files[3],
        income=frozenset(income),
        starter_slice=int(by_tier[3].get("starter_slice", 130)),
    )


def priority_order(
    plan_tier: PlanTier, tiers: Tiers | None = None, only_tiers: tuple[int, ...] = (1, 2, 3)
) -> list[str]:
    """The configured nightly set in the order requests are spent (spec 5.2).

    Tier 1, tier 2 ``income``, the rest of tier 2, then the tier 3 slice: the first
    ``starter_slice`` tier 3 lines not in tier 2 on ``starter``, all of them on ``power``.
    """
    tiers = tiers or load_tiers()
    order: list[str] = []
    seen: set[str] = set()

    def extend(symbols) -> None:
        for symbol in symbols:
            if symbol not in seen:
                seen.add(symbol)
                order.append(symbol)

    if 1 in only_tiers:
        extend(tiers.tier1)
    else:
        seen.update(tiers.tier1)
    tier2_income = [s for s in tiers.tier2 if s in tiers.income]
    tier2_rest = [s for s in tiers.tier2 if s not in tiers.income]
    if 2 in only_tiers:
        extend(tier2_income)
        extend(tier2_rest)
    else:
        seen.update(tiers.tier2)
    if 3 in only_tiers:
        tier3 = tiers.tier3_only()
        extend(tier3 if plan_tier == "power" else tier3[: tiers.starter_slice])
    return order


def _allocation_from_holdings(path: Path, funds: tuple[str, ...]) -> dict[str, float]:
    """Dollar amounts ``Qty x Price`` per fund; funds the file lists at zero stay at zero."""
    with path.open(newline="", encoding="utf-8") as handle:
        amounts = {
            row["Symbol"].strip().upper(): float(row["Qty"]) * float(row["Price"])
            for row in csv.DictReader(handle)
        }
    missing = [fund for fund in funds if fund not in amounts]
    if missing:
        raise ValueError(f"{path.name} has no row for preset fund(s) {missing}")
    return {fund: amounts[fund] for fund in funds}


def load_presets(presets_file: Path = PRESETS_FILE) -> list[Preset]:
    root = presets_file.resolve().parents[1]
    config = json.loads(presets_file.read_text(encoding="utf-8"))
    presets: list[Preset] = []
    for item in config["presets"]:
        funds = tuple(str(fund).upper() for fund in item["funds"])
        source = item.get("allocation_source")
        allocation = _allocation_from_holdings(root / source, funds) if source else None
        presets.append(
            Preset(
                id=item["id"],
                name=item["name"],
                funds=funds,
                allocation=allocation,
                allocation_unit="$" if allocation is not None else None,
            )
        )
    return presets
