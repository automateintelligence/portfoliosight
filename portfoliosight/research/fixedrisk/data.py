"""Frozen inputs, ledgers and origin contexts of the fixed-risk experiment (protocol §3, §3a).

`load_inputs(snapshot_dir)` verifies a snapshot written by `scripts/freeze_fixed_risk_inputs.py`,
reads its price records, XNYS calendar, FRED series and market-cap table, and builds one v1
`harness.Ledger` per menu and lookback. Each menu's ledger is built on its own funds, so each
menu has its own boundary month and start (research2003 2006-04, TSP 2006-06 at 3 years); the
5-year ledgers serve the lookback sensitivity.

`origin_context` reuses v1 `evaluate.origin_model` for the training side and hands the optimizer
and the banks the `contracts.OriginContext`; `horizon_returns` gives the realized 252-row horizon
for the measurements. Nothing here reads a value dated after D*.
"""

from __future__ import annotations

import importlib.util
import io
import os
import pickle
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from portfoliosight.research import evaluate, harness
from portfoliosight.research.fixedrisk.contracts import (
    LOOKBACK,
    SENSITIVITY_LOOKBACK,
    STABILITY_STRIDE,
    MenuSpec,
    OriginContext,
)
from portfoliosight.research.fixedrisk.menus import MENUS

SHOWCASE_ORIGINS = 6
MARKET_CAP_FILE = "data/research/ft_global500_2004_top10.csv"
CPI_FILE = "macro/CPIAUCNS.csv"
DGS10_FILE = "macro/DGS10.csv"
REPO = Path(__file__).resolve().parents[3]

Verify = Callable[[Path], Mapping[str, Any]]


@dataclass(frozen=True)
class Interval:
    """One retained disjoint realized interval of a menu (published before the lock)."""

    month: str
    origin: date
    horizon_start: date
    horizon_end: date


@dataclass(frozen=True)
class ResearchInputs:
    """Everything the driver and the measurements read from a snapshot."""

    root: Path | None
    manifest_sha256: str
    d_star: date
    records: dict[str, pd.DataFrame] = field(repr=False)
    sessions: pd.DatetimeIndex = field(repr=False)
    menus: tuple[MenuSpec, ...]
    ledgers: dict[tuple[str, str], harness.Ledger] = field(repr=False)  # (menu, lookback), lazy
    cpi: pd.Series = field(repr=False)  # CPIAUCNS, monthly, indexed by observation date
    dgs10: pd.Series = field(repr=False)  # DGS10, percent, daily, NaN on missing days
    market_caps: pd.DataFrame = field(repr=False)
    manifest: Mapping[str, Any] = field(default_factory=dict, repr=False)
    ledger_cache: Path | None = field(default=None, repr=False)

    def menu(self, name: str) -> MenuSpec:
        for menu in self.menus:
            if menu.name == name:
                return menu
        raise KeyError(name)

    def ledger(self, menu: MenuSpec | str, lookback: str = LOOKBACK) -> harness.Ledger:
        """The menu's ledger at ``lookback``, built on first use (a slow step: minutes).

        With a ``ledger_cache`` directory the ledger is pickled there, keyed by the snapshot digest,
        so the workers of a run read what the parent built.
        """
        key = (_name(menu), lookback)
        if key in self.ledgers:
            return self.ledgers[key]
        spec = self.menu(key[0])
        path = None
        if self.ledger_cache is not None and self.manifest_sha256:
            path = self.ledger_cache / f"{self.manifest_sha256[:16]}_{key[0]}_{lookback}.pkl"
            if path.is_file():
                with path.open("rb") as handle:
                    self.ledgers[key] = pickle.load(handle)
                return self.ledgers[key]
        built = harness.build_ledger(
            self.records, self.sessions, self.d_star, {spec.name: spec.holdings}, lookback
        )
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            with tmp.open("wb") as handle:
                pickle.dump(built, handle)
            os.replace(tmp, path)
        self.ledgers[key] = built
        return built


def _name(menu: MenuSpec | str) -> str:
    return menu if isinstance(menu, str) else menu.name


# ------------------------------------------------------------------------------- loading


def default_verify() -> Verify:
    """`verify_snapshot` of scripts/freeze_research_inputs.py (shared by both freeze scripts)."""
    name = "freeze_research_inputs"
    module = sys.modules.get(name)
    if module is None:
        path = REPO / "scripts" / "freeze_research_inputs.py"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module.verify_snapshot


def read_series(data: bytes, name: str) -> pd.Series:
    """A FRED graph CSV (`observation_date|DATE,<ID>`) as a float series; '.' is NaN."""
    frame = pd.read_csv(io.BytesIO(data), na_values=["."])
    if frame.shape[1] != 2:
        raise ValueError(f"{name}: expected two columns, found {list(frame.columns)}")
    index = pd.DatetimeIndex(pd.to_datetime(frame.iloc[:, 0], format="%Y-%m-%d"))
    series = pd.Series(frame.iloc[:, 1].to_numpy(dtype=float), index=index, name=name)
    if not series.index.is_monotonic_increasing:
        raise ValueError(f"{name}: dates are not increasing")
    return series


def read_market_caps(data: bytes) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(data), comment="#")


def build_inputs(
    records: Mapping[str, pd.DataFrame],
    sessions: Sequence[Any],
    d_star: date,
    *,
    menus: Sequence[MenuSpec] = MENUS,
    cpi: pd.Series | None = None,
    dgs10: pd.Series | None = None,
    market_caps: pd.DataFrame | None = None,
    manifest_sha256: str = "",
    root: Path | None = None,
    manifest: Mapping[str, Any] | None = None,
    ledger_cache: Path | None = None,
) -> ResearchInputs:
    """Inputs with lazily built ledgers (each menu on its own funds); `load_inputs` without I/O."""
    return ResearchInputs(
        root=root,
        manifest_sha256=manifest_sha256,
        d_star=d_star,
        records=dict(records),
        sessions=pd.DatetimeIndex(pd.to_datetime(list(sessions))),
        menus=tuple(menus),
        ledgers={},
        ledger_cache=ledger_cache,
        cpi=cpi if cpi is not None else pd.Series(dtype=float, name="CPIAUCNS"),
        dgs10=dgs10 if dgs10 is not None else pd.Series(dtype=float, name="DGS10"),
        market_caps=market_caps if market_caps is not None else pd.DataFrame(),
        manifest=manifest or {},
    )


def load_inputs(
    snapshot_dir: str | Path,
    verify: Verify | None = None,
    menus: Sequence[MenuSpec] = MENUS,
    ledger_cache: str | Path | None = None,
) -> ResearchInputs:
    """Verify and read a fixed-risk snapshot, then build its ledgers."""
    verifier = verify or default_verify()
    kept: dict[str, Mapping[str, Any]] = {}

    def keep(root: Path) -> Mapping[str, Any]:
        kept["manifest"] = verifier(root)
        return kept["manifest"]

    snap = harness.read_snapshot(snapshot_dir, keep)
    manifest = kept["manifest"]
    recorded = {key: entry for key, entry in manifest["menus"].items()}
    for menu in menus:
        entry = recorded.get(menu.name)
        if (
            entry is None
            or tuple(entry["funds"]) != menu.holdings
            or tuple(entry.get("lower", menu.lower)) != menu.lower
            or tuple(entry.get("upper", menu.upper)) != menu.upper
        ):
            raise ValueError(
                f"{snap.root}: the snapshot's menu {menu.name!r} differs from menus.py"
            )
    digests = {entry["path"]: entry["sha256"] for entry in manifest["files"]}

    def read(relative: str) -> bytes:
        import hashlib

        data = (snap.root / relative).read_bytes()
        if hashlib.sha256(data).hexdigest() != digests.get(relative):
            raise harness.SnapshotChanged(f"{snap.root}: {relative} no longer matches the manifest")
        return data

    return build_inputs(
        snap.records,
        snap.sessions,
        snap.d_star,
        menus=menus,
        cpi=read_series(read(CPI_FILE), "CPIAUCNS"),
        dgs10=read_series(read(DGS10_FILE), "DGS10"),
        market_caps=read_market_caps(read(MARKET_CAP_FILE)),
        manifest_sha256=snap.manifest_sha256,
        root=snap.root,
        manifest=manifest,
        ledger_cache=Path(ledger_cache) if ledger_cache else None,
    )


# ---------------------------------------------------------------------------- schedules


def schedule(inputs: ResearchInputs, menu: MenuSpec | str, lookback: str = LOOKBACK) -> list[str]:
    """The menu's eligible origin months (YYYY-MM): training-eligible at the lookback."""
    name = _name(menu)
    return [
        row.month for row in inputs.ledger(name, lookback).rows if row.menu(name).training_eligible
    ]


def showcase_indices(count: int, points: int = SHOWCASE_ORIGINS) -> list[int]:
    """Indices `floor(j (K - 1) / (points - 1))`, j = 0..points-1, each once (protocol §3)."""
    if count == 0:
        return []
    return sorted({j * (count - 1) // (points - 1) for j in range(points)})


def showcase_months(inputs: ResearchInputs, menu: MenuSpec | str) -> list[str]:
    months = schedule(inputs, menu)
    return [months[i] for i in showcase_indices(len(months))]


def stability_months(inputs: ResearchInputs, menu: MenuSpec | str) -> list[str]:
    """Every fourth scheduled origin: indices 0, 4, 8, ... (protocol §3)."""
    return schedule(inputs, menu)[::STABILITY_STRIDE]


def lookback5_months(inputs: ResearchInputs, menu: MenuSpec | str) -> list[str]:
    """Showcase origins where the 5-year window meets the same eligibility rule."""
    eligible = set(schedule(inputs, menu, SENSITIVITY_LOOKBACK))
    return [month for month in showcase_months(inputs, menu) if month in eligible]


def disjoint_intervals(inputs: ResearchInputs, menu: MenuSpec | str) -> list[Interval]:
    """The retained disjoint realized intervals of the 3-year ledger, in origin order."""
    name = _name(menu)
    found = []
    for row in inputs.ledger(name).rows:
        entry = row.menu(name)
        if entry.disjoint and entry.horizon_start is not None and entry.horizon_end is not None:
            found.append(Interval(row.month, row.origin, entry.horizon_start, entry.horizon_end))
    return found


def realized_intervals(inputs: ResearchInputs, menu: MenuSpec | str) -> list[Interval]:
    """Scheduled origins of the 3-year ledger with a complete realized year (ledger outcome
    `complete`), in origin order: the CSCV adaptation's eligible origins and horizon ends."""
    name = _name(menu)
    found = []
    for row in inputs.ledger(name).rows:
        entry = row.menu(name)
        if (
            row.training_eligible
            and row.in_realized_panel
            and entry.outcome == harness.COMPLETE
            and entry.horizon_start is not None
            and entry.horizon_end is not None
        ):
            found.append(Interval(row.month, row.origin, entry.horizon_start, entry.horizon_end))
    return found


# ------------------------------------------------------------------------------ one origin


def origin_context(
    inputs: ResearchInputs, menu: MenuSpec | str, month: str, lookback: str = LOOKBACK
) -> OriginContext:
    """The training side of (menu, month, lookback) as the optimizer and the banks read it."""
    spec = inputs.menu(_name(menu)) if isinstance(menu, str) else menu
    ledger = inputs.ledger(spec, lookback)
    model = evaluate.origin_model(inputs.records, ledger, month, spec.name)
    if model.funds != spec.holdings:
        raise ValueError(f"{spec.name} at {month}: fund order differs from the menu")
    cov = np.array(model.moments.cov, dtype=float)
    cov.setflags(write=False)
    mu_hat = np.array(model.moments.mu, dtype=float)
    mu_hat.setflags(write=False)
    return OriginContext(
        menu=spec,
        month=month,
        origin=model.origin,
        lookback=lookback,
        days=model.days,
        sample=model.sample,
        mu_hat=mu_hat,
        mu_s=model.mu_s,
        cov=cov,
        sigma=np.sqrt(np.diag(cov)),
        risk_free_rate=float(model.risk_free_rate),
        inputs_sha256=model.inputs_sha256,
    )


def horizon_returns(inputs: ResearchInputs, menu: MenuSpec | str, month: str) -> evaluate.Horizon:
    """The realized 252-row horizon after the 3-year origin (`Horizon.returns` is 252 x N)."""
    name = _name(menu)
    return evaluate.realized_horizon(inputs.records, inputs.ledger(name), month, name)
