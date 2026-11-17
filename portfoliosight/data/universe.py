"""The served universe by tier, the nightly priority order and the presets (spec 5.2)."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from portfoliosight.data.manifest import unnamed
from portfoliosight.engine.caps import CapsError, resolve_bounds

REPO_ROOT = Path(__file__).resolve().parents[2]
TIERS_FILE = REPO_ROOT / "data" / "universes" / "tiers.json"
FUNDS_FILE = REPO_ROOT / "data" / "universes" / "funds.json"
FUND_KINDS = ("etf", "mutual_fund", "stock")
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
class FundMeta:
    """What ``funds.json`` says about one wanted symbol: its display name and its kind."""

    name: str
    kind: str


@dataclass(frozen=True)
class SymbolInfo:
    """What the universe files say about one symbol."""

    id: str
    tier: int
    income: bool
    kind: str | None  # "tsp", "stock", or None when the provider's meta decides (etf/mutual fund)
    note: str | None = None  # why a fund has no recent data, e.g. "converted to an ETF"
    requested: bool = False  # a requested ticker whose lowest tier is 3 (spec 4.1)


@dataclass(frozen=True)
class Tiers:
    tier1: tuple[str, ...]  # the 23 Step 2 funds, the 16 TSP funds, then the other preset funds
    tier2: tuple[str, ...]  # file order
    tier3: tuple[str, ...]  # file order across its files, repeats dropped, tier 2 symbols kept
    income: frozenset[str]
    starter_slice: int
    notes: Mapping[str, str] = field(default_factory=dict)
    preset_funds: tuple[str, ...] = ()  # the funds tier 1 adds from the presets, in its order
    requested: tuple[str, ...] = ()  # the tier 3 request list (spec 4.1), file order

    def tier3_only(self) -> tuple[str, ...]:
        """Tier 3 symbols that are not already in tier 2, in file order."""
        tier2 = set(self.tier2)
        return tuple(s for s in self.tier3 if s not in tier2)

    def info(self) -> dict[str, SymbolInfo]:
        """Every symbol of every tier with its lowest tier.

        A symbol whose lowest tier in the universe files is 3 is a stock, also when a preset
        lifts it to tier 1.
        """
        listed1 = set(self.tier1) - set(self.preset_funds)
        stocks = {s for s in self.tier3_only() if s not in listed1}
        asked = set(self.requested)
        out: dict[str, SymbolInfo] = {}
        for tier, symbols in ((1, self.tier1), (2, self.tier2), (3, self.tier3)):
            for symbol in symbols:
                if symbol in out:
                    continue
                if is_tsp(symbol):
                    kind = "tsp"
                elif symbol in stocks:
                    kind = "stock"
                else:
                    kind = None
                out[symbol] = SymbolInfo(
                    symbol,
                    tier,
                    symbol in self.income,
                    kind,
                    self.notes.get(symbol),
                    requested=tier == 3 and symbol in asked,
                )
        return out


@dataclass(frozen=True)
class Preset:
    """A ready-made menu. ``caps`` holds the per-fund limits it declares, as fractions of 1:
    ``{fund: {"min": float | None, "max": float | None}}``; a fund it does not list, and a bound
    that is ``None``, take the default rule (spec 4.4)."""

    id: str
    name: str
    funds: tuple[str, ...]
    allocation: dict[str, float] | None
    allocation_unit: str | None
    caps: dict[str, dict[str, float | None]] = field(default_factory=dict)


def load_funds(path: Path = FUNDS_FILE) -> dict[str, FundMeta]:
    """Symbol to ``FundMeta`` from ``funds.json`` (spec 2026-11-16 section 8).

    Refuses a kind outside ``etf``, ``mutual_fund`` and ``stock``, and a name that is empty or
    only the ticker, as the catalog counts an entry unnamed (``manifest.unnamed``).
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path.name} must be an object of symbol to {{name, kind}}")
    funds: dict[str, FundMeta] = {}
    for raw_symbol, row in document.items():
        symbol = str(raw_symbol).upper()
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ValueError(f"{path.name}: {symbol} needs an object with a name and a kind")
        name, kind = row["name"], row.get("kind")
        if unnamed(symbol, name):
            raise ValueError(f"{path.name}: {symbol} has no name of its own: {name!r}")
        if kind not in FUND_KINDS:
            raise ValueError(f"{path.name}: {symbol} kind {kind!r} not in {list(FUND_KINDS)}")
        funds[symbol] = FundMeta(name.strip(), kind)
    return funds


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


def _universe_files(item: Mapping[str, Any], tier: int, tiers_file: Path) -> list[str]:
    """The files of a tier 2 or 3 entry: one ``file``, or a ``files`` list read in order."""
    single, several = item.get("file"), item.get("files")
    if single is not None and several is None:
        return [str(single)]
    if single is None and isinstance(several, list) and several:
        return [str(name) for name in several]
    raise ValueError(f"{tiers_file.name}: tier {tier} needs either 'file' or a 'files' list")


def _requested_file(item: Mapping[str, Any], files: list[str], tiers_file: Path) -> str | None:
    """The tier 3 file the entry names as the request list; it must be one of the tier's files."""
    named = item.get("requested")
    if named is None:
        return None
    if str(named) not in files:
        raise ValueError(
            f"{tiers_file.name}: tier 3 'requested' must name one of its files, not {named!r}"
        )
    return str(named)


def load_tiers(tiers_file: Path = TIERS_FILE) -> Tiers:
    root = tiers_file.resolve().parents[2]
    config = json.loads(tiers_file.read_text(encoding="utf-8"))
    by_tier = {int(item["tier"]): item for item in config["tiers"]}
    if sorted(by_tier) != [1, 2, 3]:
        raise ValueError(f"{tiers_file.name} must list tiers 1, 2 and 3, found {sorted(by_tier)}")
    tier3_files = _universe_files(by_tier[3], 3, tiers_file)
    requested_file = _requested_file(by_tier[3], tier3_files, tiers_file)

    holdings = root / by_tier[1]["holdings"]
    tier1 = _holdings_symbols(holdings)
    if by_tier[1].get("tsp"):
        tier1 += list(TSP_FUNDS)
    added: dict[str, None] = {}  # every preset's funds, refreshed before the presets are built
    if by_tier[1].get("presets"):
        for preset in load_presets(root / by_tier[1]["presets"]):
            added.update((fund, None) for fund in preset.funds if fund not in tier1)
    income: set[str] = set()
    requested: tuple[str, ...] = ()
    files: dict[int, tuple[str, ...]] = {}
    for tier in (2, 3):
        joined: dict[str, None] = {}  # the files' symbols in order; a repeat keeps its first place
        names = tier3_files if tier == 3 else _universe_files(by_tier[tier], tier, tiers_file)
        for name in names:
            path = root / name
            lines = parse_universe_lines(path.read_text(encoding="utf-8"))
            symbols = _unique([symbol for symbol, _ in lines], path)
            joined.update(dict.fromkeys(symbols))
            income.update(symbol for symbol, tagged in lines if tagged)
            if tier == 3 and name == requested_file:
                requested = symbols
        files[tier] = tuple(joined)
    return Tiers(
        tier1=_unique(tier1, holdings) + tuple(added),
        tier2=files[2],
        tier3=files[3],
        income=frozenset(income),
        starter_slice=int(by_tier[3].get("starter_slice", 130)),
        notes={str(k).upper(): str(v) for k, v in config.get("notes", {}).items()},
        preset_funds=tuple(added),
        requested=requested,
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


ALLOCATION_UNITS = ("$", "%")
PERCENT_TOLERANCE = 0.05  # the page accepts percentages that add up to 100 within this
CAP_KEYS = frozenset({"min", "max"})


def _declared_caps(item: Mapping[str, Any], funds: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """The ``caps`` of a preset entry, each bound checked as the engine would check a request.

    ``{"SPY": {"max": 0.4}, ...}``: fractions of 1, a missing bound is the default rule. The
    declared limits go through ``resolve_bounds`` with the whole menu, so a bound outside [0, 1],
    a minimum above its maximum or limits that cannot add up to 100% refuse the file here and not
    the nightly build.
    """
    declared = item.get("caps")
    if declared is None:
        return {}
    where = f"preset {item['id']!r}"
    if not isinstance(declared, dict):
        raise ValueError(f"{where}: caps must be an object of fund id to {{min, max}}")
    caps: dict[str, dict[str, Any]] = {}
    for fund, bounds in declared.items():
        fund = str(fund).upper()
        if not isinstance(bounds, dict):
            raise ValueError(f"{where}: caps for {fund} must be an object with min and/or max")
        unknown = sorted(set(bounds) - CAP_KEYS)
        if unknown:
            raise ValueError(f"{where}: caps for {fund} has unknown key(s) {unknown}")
        caps[fund] = {"min": bounds.get("min"), "max": bounds.get("max")}
    try:
        resolve_bounds(funds, [{"id": fund, **bounds} for fund, bounds in caps.items()])
    except CapsError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    return {
        fund: {name: None if bound is None else float(bound) for name, bound in bounds.items()}
        for fund, bounds in caps.items()
    }


def _declared_allocation(item: Mapping[str, Any], funds: tuple[str, ...]) -> dict[str, float]:
    """The ``allocation`` written in a preset entry: an amount for every fund, in ``$`` or ``%``.

    Percentages must add up to 100 within the page's tolerance, so the page accepts them as the
    mix entered.
    """
    where = f"preset {item['id']!r}"
    amounts = item["allocation"]
    unit = item.get("allocation_unit")
    if unit not in ALLOCATION_UNITS:
        raise ValueError(f"{where}: allocation_unit must be one of {list(ALLOCATION_UNITS)}")
    if not isinstance(amounts, dict):
        raise ValueError(f"{where}: allocation must be an object of fund id to amount")
    allocation: dict[str, float] = {}
    for fund, amount in amounts.items():
        fund = str(fund).upper()
        if isinstance(amount, bool) or not isinstance(amount, int | float):
            raise ValueError(f"{where}: the amount for {fund} must be a number")
        if not math.isfinite(amount) or amount < 0:
            raise ValueError(f"{where}: the amount for {fund} must not be negative")
        allocation[fund] = float(amount)
    unlisted = [fund for fund in funds if fund not in allocation]
    if unlisted:
        raise ValueError(f"{where}: allocation has no amount for fund(s) {unlisted}")
    extra = sorted(set(allocation) - set(funds))
    if extra:
        raise ValueError(f"{where}: allocation names fund(s) {extra} that are not in the menu")
    total = sum(allocation.values())
    if total <= 0:
        raise ValueError(f"{where}: allocation adds up to nothing")
    if unit == "%" and abs(total - 100.0) > PERCENT_TOLERANCE + 1e-9:
        raise ValueError(f"{where}: percentages add up to {total:g}, not 100")
    return {fund: allocation[fund] for fund in funds}


def load_presets(presets_file: Path = PRESETS_FILE) -> list[Preset]:
    """The presets of ``data/presets.json``, each entry checked as the nightly will use it.

    An entry has ``id``, ``name``, ``funds`` and optionally ``caps`` (per-fund limits, above),
    and at most one source of a starting mix: ``allocation_source`` (a holdings CSV, dollars as
    Qty x Price) or ``allocation`` with ``allocation_unit`` (``"$"`` or ``"%"``).
    """
    root = presets_file.resolve().parents[1]
    config = json.loads(presets_file.read_text(encoding="utf-8"))
    presets: list[Preset] = []
    for item in config["presets"]:
        funds = tuple(str(fund).upper() for fund in item["funds"])
        source = item.get("allocation_source")
        written = item.get("allocation")
        if source and written is not None:
            raise ValueError(
                f"preset {item['id']!r}: give allocation_source or allocation, not both"
            )
        allocation: dict[str, float] | None = None
        unit: str | None = None
        if source:
            allocation, unit = _allocation_from_holdings(root / source, funds), "$"
        elif written is not None:
            allocation, unit = _declared_allocation(item, funds), item["allocation_unit"]
        presets.append(
            Preset(
                id=item["id"],
                name=item["name"],
                funds=funds,
                allocation=allocation,
                allocation_unit=unit,
                caps=_declared_caps(item, funds),
            )
        )
    return presets
