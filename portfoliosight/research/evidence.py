"""Statistics and the predeclared decision rules of the return-optimization report (protocol 6, 7).

The report writer (`research.report`) reads a run's artifacts and hands this module the outcome
rows; everything here is a pure function of those rows and of the predeclared thresholds.

Origin index and masks (protocol 4, 6). Every statistic is a function of the chronological monthly
origin index: every ledger month from the first to the last scheduled origin. `Grid` places one
outcome column of one (menu, arm, optimizer seed) on that index as a 3 x K array, one row per
prescribed risk cell (`RISK_CELLS`); a distinct cell that stands for collapsed aliases fills every
risk cell it stands for. Missing values stay on the index as NaN: a failed cell, an unscheduled
month or, for realized columns, an origin outside the realized mask. The realized mask is the
intersection over both menus of the origins whose 252-day horizon is complete
(`intersection_mask`; ruling 6): one mask across both arms and both menus. Nothing is imputed.

Aggregation order (protocol 6). A linear statistic (a mean paired difference) is averaged first
over the risk cells of an origin (equal weights, so an alias carries its prescribed weight; a
failed cell is left out of its origin's average), then over the origins of a menu
(`origin_mean`); a risk-cell figure averages its origins (`cell_mean`). A nonlinear statistic (a
quantile of returns across origins, a correlation) is computed within each menu and risk cell
before the cells' contrasts are averaged. Menus are then averaged 50/50; the aggregate never
decides anything.

Bootstrap (protocol 6). Paired circular moving-block bootstrap over the origin index: each
resample joins `ceil(K / L)` blocks of `L` consecutive positions (wrapping past the end) whose
starts come from `numpy.random.default_rng(20261201).integers(0, K)`, cut to K positions
(`block_index`, `resample_index`). `Bootstrap` draws one index matrix of 2,000 resamples per block
length (24 primary, 12 and 36 sensitivity, the same seed for each) and applies it to every arm,
risk cell and menu, recomputing the complete statistic per resample from the available paired
rows. Intervals are percentile intervals (linear), 99% for the four realized-support endpoints and
95% elsewhere; resamples with no available row are counted as undefined, never filled.

Measurements, per menu (primary optimizer seed unless stated): `replay_contrast` (pooled-test and
per-bank paired ΔU/ΔB/ΔT/ΔG), `stability` (all optimizer seeds: pooled median and 90th-percentile
pairwise weight L1 per risk cell, the share of origins whose across-seed pooled-test Bad standard
deviation (ddof 1) is at most 0.10 times the primary-seed selection's model risk, and the pooled
adjacent-origin turnover median), `score_change` (mean DR² gain, share of cells with
L1 >= .02), `realized` (paired realized returns and drawdowns with 99% intervals, and the
per-risk-cell guardrail figures; median loss is the difference of per-arm medians across origins,
ruling 7), `cost` (Stage 1 per-cell arm wall times), `calibration` (coverage and pinball loss per
quantile; never an input of `decide`).

Decisions (protocol 7, applied mechanically by `decide`): per menu the replay-return branch, the
stability branch (evaluated only when the pooled ΔU is under 5 bp, ruling 3), meaningful score
change, general stability and cost give positive conditional-model evidence (PCME); realized
guardrails and realized benefit support give realized policy support; any breached realized
guardrail or independent-replay floor is material harm at its location. An invalid experiment
(ruling R25: any unresolved failure, among others) gets no protocol 7 verdict label: every menu
label is inconclusive/invalid and no branch qualifies. Stage 2 runs iff the experiment is valid,
both menus have PCME and no sensitivity disclosure blocks progression (ruling 1): a sign
reversal, a failed floor or bank check, or an unavailable setting or stability sensitivity. A
setting's sign reversal is judged against Stage 1 on the same six indexed origins, not the
full-panel ΔU (protocol amendment R27); without that baseline a reversal is unverified and
blocks. A menu that qualifies only through the stability branch therefore cannot authorize
Stage 2. The 0 bp cap is a diagnostic control, inert by construction: it never blocks Stage 2,
unavailable or tied included (protocol amendment R26). Confirmed worthwhile benefit (positive
conditional-model evidence and realized support in both menus, no material harm, a valid
experiment) is reported and never gates Stage 2.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pyarrow as pa

from portfoliosight.engine.measures import TAIL_FRACTION
from portfoliosight.research import evaluate
from portfoliosight.research.search import PRIMARY_ALLOWANCE

BP = 1e-4  # one basis point, decimal
RISK_CELLS = ("x25", "x50", "x100")
QUANTILES = (("bad", 0.025), ("typical", 0.50), ("good", 0.975))

BLOCK = 24  # protocol 6: block length in origins, primary
BLOCKS = (24, 12, 36)  # the primary length, then the sensitivity lengths
RESAMPLES = 2000
BOOTSTRAP_SEED = 20261201
SUPPORT_LEVEL = 0.99  # the four realized-support endpoints (two menus x return/drawdown)
DESCRIPTIVE_LEVEL = 0.95

# protocol 7 thresholds, decimal
REPLAY_GAIN = 5 * BP
U_FLOOR = -2.5 * BP
B_FLOOR = -5 * BP
T_FLOOR = -10 * BP
G_FLOOR = -20 * BP
BANKS_NEEDED = 4  # of five
L1_RELATIVE = 0.20
L1_ABSOLUTE = 0.02
DR2_GAIN = 0.10
CHANGED_L1 = 0.02
CHANGED_SHARE = 0.20
BAD_SD_FACTOR = 0.10
BAD_SD_SHARE = 0.95
MEDIAN_L1 = 0.20
P90_L1 = 0.40
TURNOVER_SLACK = 0.05
MEDIAN_LOSS = 25 * BP
MEAN_LOSS = 25 * BP
LOSS_FREQUENCY = 0.05
DRAWDOWN_WORSENING = 0.01
SUPPORT_GAIN = 25 * BP
SUPPORT_DRAWDOWN = 0.01
SUPPORT_DISJOINT = 20
TAIL_DISJOINT = 200
COST_R_P95 = {"tsp": 10.0, "example": 30.0}  # seconds, per scheduled cell
COST_RATIO_P95 = 1.25

Arm = tuple[str, float | None]  # (role, allowance)
BASE_ARM: Arm = ("R", None)
PRIMARY_ARM: Arm = ("R+D", PRIMARY_ALLOWANCE)
SENSITIVITY_SETTINGS = (
    "cap-0bp",
    "cap-5bp",
    "cap-10bp",
    "coefficients-70-20-10",
    "coefficients-50-35-15",
    "lookback-252",
    "budget-x2",
)
# R+D = w_R or a 1e-12 U tie: a diagnostic control that never blocks (protocol amendment R26)
INERT_SETTINGS = frozenset({"cap-0bp"})

VALID = "valid experiment"
INVALID = "inconclusive/invalid"
PCME = "positive conditional-model evidence"
NOT_MET = "did not meet observed conditional screening criteria"
SUPPORT = "realized policy support"
INCONCLUSIVE = "inconclusive historical evidence"
ROBUST = "robust across the predeclared sensitivities"
SENSITIVE = "parameter/search sensitive or unverified"
NO_BRANCH = "not assessed: no qualifying branch"
ACTIVE = "active at the 2.5 bp primary cap"
INACTIVE = "inactive/near-inactive at the 2.5 bp primary cap"
UNDERPOWERED = "underpowered"
TAIL_ADEQUATE = "at least 200 disjoint annual intervals (a warning threshold, not precision)"
EXPLORATORY = "exploratory"
NOT_EXPLORATORY = "at least 20 disjoint annual intervals"
REPLAY_BRANCH = "replay-return"
STABILITY_BRANCH = "stability"
_NOISE = 1e-24  # a squared deviation per observation this small is rounding, not variation


# ------------------------------------------------------------------------------- bootstrap


def block_index(starts: np.ndarray, n: int, block: int) -> np.ndarray:
    """Circular blocks: row r joins `starts[r, j] + 0..block-1 (mod n)` over j, cut to n."""
    first = np.asarray(starts, dtype=np.int64)
    if first.ndim != 2 or n < 1 or block < 1:
        raise ValueError("starts must be resamples x blocks; n and block must be positive")
    joined = ((first[:, :, None] + np.arange(block)) % n).reshape(first.shape[0], -1)
    if joined.shape[1] < n:
        raise ValueError(f"{first.shape[1]} blocks of {block} cannot cover {n} origins")
    return joined[:, :n]


def resample_index(
    n: int, block: int, resamples: int = RESAMPLES, seed: int = BOOTSTRAP_SEED
) -> np.ndarray:
    """The resamples x n origin index of the circular moving-block bootstrap."""
    if n < 1:
        raise ValueError("the origin index is empty")
    starts = np.random.default_rng(seed).integers(0, n, size=(resamples, math.ceil(n / block)))
    return block_index(starts, n, block)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


@dataclass(frozen=True)
class Estimate:
    """A point statistic, its origin count and its percentile intervals by block length."""

    value: float | None
    n: int
    level: float
    intervals: Mapping[int, tuple[float | None, float | None]]
    undefined: Mapping[int, int]

    def lower(self, block: int = BLOCK) -> float | None:
        interval = self.intervals.get(block)
        return None if interval is None else interval[0]

    def record(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "n": self.n,
            "level": self.level,
            "interval": {str(block): list(bounds) for block, bounds in self.intervals.items()},
            "undefined_resamples": {str(block): k for block, k in self.undefined.items()},
        }


Statistic = Callable[[np.ndarray], np.ndarray]  # an index matrix (R x K) -> R values


class Bootstrap:
    """One index matrix per block length, shared by every arm, risk cell and menu."""

    def __init__(
        self,
        n: int,
        *,
        blocks: Sequence[int] = BLOCKS,
        resamples: int = RESAMPLES,
        seed: int = BOOTSTRAP_SEED,
    ) -> None:
        self.n = n
        self.blocks = tuple(blocks)
        self.resamples = resamples
        self.seed = seed
        self.identity = np.arange(n)[None, :]
        self.indices = {block: resample_index(n, block, resamples, seed) for block in blocks}

    def estimate(self, statistic: Statistic, level: float, n: int) -> Estimate:
        value = _number(np.asarray(statistic(self.identity), dtype=float)[0])
        tail = round(50.0 * (1.0 - level), 12)
        intervals: dict[int, tuple[float | None, float | None]] = {}
        undefined: dict[int, int] = {}
        for block, index in self.indices.items():
            draws = np.asarray(statistic(index), dtype=float)
            finite = draws[np.isfinite(draws)]
            undefined[block] = int(draws.size - finite.size)
            if finite.size == 0:
                intervals[block] = (None, None)
            else:
                low, high = np.percentile(finite, [tail, 100.0 - tail])
                intervals[block] = (float(low), float(high))
        return Estimate(value, n, level, intervals, undefined)


# ---------------------------------------------------------------------- vectorized statistics


def _masked_mean(values: np.ndarray, axis: int) -> np.ndarray:
    ok = np.isfinite(values)
    count = ok.sum(axis=axis)
    total = np.where(ok, values, 0.0).sum(axis=axis)
    return np.where(count > 0, total / np.maximum(count, 1), np.nan)


def cell_mean(x: np.ndarray, index: np.ndarray) -> np.ndarray:
    """The mean of a K-vector over each resample's available origins (NaN when none)."""
    return _masked_mean(np.asarray(x, dtype=float)[index], axis=1)


def origin_mean(x: np.ndarray, index: np.ndarray) -> np.ndarray:
    """Risk cells (rows) averaged within each origin, then origins, per resample."""
    return cell_mean(_masked_mean(np.asarray(x, dtype=float), axis=0), index)


def quantile(x: np.ndarray, q: float, index: np.ndarray) -> np.ndarray:
    """The linear q-quantile of each resample's available origins (NaN when none).

    NumPy's linear method (virtual index `q (n - 1)`, its two-sided interpolation), vectorized
    over the resamples: `np.nanpercentile` loops over rows in Python once any value is missing.
    """
    ordered = np.sort(np.asarray(x, dtype=float)[index], axis=1)  # NaN sorts last
    n = np.isfinite(ordered).sum(axis=1)
    position = q * (np.maximum(n, 1) - 1)
    low = np.floor(position).astype(np.int64)
    high = np.minimum(low + 1, np.maximum(n, 1) - 1)
    rows = np.arange(ordered.shape[0])
    a, b = ordered[rows, low], ordered[rows, high]
    t = position - low
    with np.errstate(invalid="ignore"):
        difference = b - a
        out = np.where(t >= 0.5, b - difference * (1.0 - t), a + difference * t)
    return np.where(n > 0, out, np.nan)


def expected_shortfall(x: np.ndarray, index: np.ndarray) -> np.ndarray:
    """Mean of the worst `ceil(0.025 n)` of each resample's n available origins (NaN if none)."""
    ordered = np.sort(np.asarray(x, dtype=float)[index], axis=1)  # NaN sorts last
    n = np.isfinite(ordered).sum(axis=1)
    tail = np.maximum(-(-(TAIL_FRACTION.numerator * n) // TAIL_FRACTION.denominator), 1)
    sums = np.cumsum(np.where(np.isfinite(ordered), ordered, 0.0), axis=1)
    rows = np.arange(ordered.shape[0])
    return np.where(n > 0, sums[rows, tail - 1] / tail, np.nan)


def correlation(x: np.ndarray, y: np.ndarray, index: np.ndarray) -> np.ndarray:
    """Pearson correlation of the origins available in both (NaN below two or without spread)."""
    a, b = np.asarray(x, dtype=float)[index], np.asarray(y, dtype=float)[index]
    ok = np.isfinite(a) & np.isfinite(b)
    n = ok.sum(axis=1)
    safe = np.maximum(n, 1)
    da = np.where(ok, a - (np.where(ok, a, 0.0).sum(axis=1) / safe)[:, None], 0.0)
    db = np.where(ok, b - (np.where(ok, b, 0.0).sum(axis=1) / safe)[:, None], 0.0)
    sxx, syy, sxy = (da * da).sum(axis=1), (db * db).sum(axis=1), (da * db).sum(axis=1)
    defined = (n >= 2) & (sxx > _NOISE * n) & (syy > _NOISE * n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(defined, sxy / np.sqrt(sxx * syy), np.nan)


def _point(statistic: Statistic, n: int) -> float | None:
    return _number(statistic(np.arange(n)[None, :])[0])


def _count(x: np.ndarray) -> int:
    """Origins with a value in any row of a (cells x K) array, or in a K-vector."""
    values = np.asarray(x, dtype=float)
    ok = np.isfinite(values)
    return int((ok.any(axis=0) if values.ndim == 2 else ok).sum())


def percentile(values: Sequence[float], q: float) -> float | None:
    """The linear percentile ``q`` (0-100) of the finite values, None when there is none."""
    finite = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    return float(np.percentile(finite, q)) if finite else None


# ------------------------------------------------------------------------------- the grid


def intersection_mask(complete: Mapping[str, Sequence[bool]], menus: Sequence[str]) -> np.ndarray:
    """Origins whose realized outcome is complete in every menu (ruling 6)."""
    return np.logical_and.reduce([np.asarray(complete[menu], dtype=bool) for menu in menus])


def disjoint_count(origins: Sequence[Any], ends: Sequence[Any]) -> int:
    """Greedy disjoint annual intervals in origin order: an origin strictly after the last end."""
    count, last = 0, None
    for origin, end in sorted(zip(origins, ends, strict=True)):
        if last is None or origin > last:
            count, last = count + 1, end
    return count


def _allowance(value: Any) -> float | None:
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else value


class Grid:
    """The outcome rows of one profile on the origin index (module docstring)."""

    def __init__(
        self,
        table: pa.Table,
        months: Sequence[str],
        *,
        profile: str,
        realized_mask: Sequence[bool] | np.ndarray | None = None,
    ) -> None:
        self.months = tuple(months)
        self.k = len(self.months)
        position = {month: i for i, month in enumerate(self.months)}
        self.mask = (
            np.ones(self.k, dtype=bool)
            if realized_mask is None
            else np.asarray(realized_mask, dtype=bool)
        )
        if self.mask.shape != (self.k,):
            raise ValueError("the realized mask must have one entry per origin")
        names = ("profile", "menu", "month", "seed", "role", "allowance", "stands_for")
        columns = [table[name].to_pylist() for name in names]
        groups: dict[tuple, list[tuple[int, int, int, int]]] = {}
        for i, (p, menu, month, seed, role, allowance, stands) in enumerate(
            zip(*columns, strict=True)
        ):
            if p != profile or month not in position:
                continue
            key = (menu, role, _allowance(allowance), int(seed))
            for slot, cell in enumerate(stands):
                groups.setdefault(key, []).append(
                    (i, RISK_CELLS.index(cell), position[month], slot)
                )
        self._groups: dict[tuple, tuple[np.ndarray, ...]] = {}
        for key, entries in groups.items():
            if len({(c, t) for _, c, t, _ in entries}) != len(entries):
                raise ValueError(f"{key}: two outcome rows for one risk cell and origin")
            self._groups[key] = tuple(
                np.array(part, dtype=np.int64) for part in zip(*entries, strict=True)
            )
        self.menus = tuple(dict.fromkeys(key[0] for key in groups))
        self._menu_rows = {
            menu: np.unique(
                np.concatenate([g[0] for key, g in self._groups.items() if key[0] == menu])
            )
            for menu in self.menus
        }
        self.seeds = tuple(sorted({key[3] for key in groups}))
        self._table = table
        self._floats: dict[str, np.ndarray] = {}
        self._lists: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    def has(self, menu: str, arm: Arm, seed: int) -> bool:
        return (menu, arm[0], arm[1], seed) in self._groups

    def _float(self, name: str) -> np.ndarray:
        if name not in self._floats:
            column = self._table[name].cast(pa.float64())
            self._floats[name] = np.asarray(column.to_numpy(zero_copy_only=False), dtype=float)
        return self._floats[name]

    def _list(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        """The list column padded with NaN to its longest row, and each row's length."""
        if name not in self._lists:
            rows = self._table[name].to_pylist()
            lengths = np.array([0 if row is None else len(row) for row in rows], dtype=np.int64)
            out = np.full((len(rows), int(lengths.max(initial=0))), np.nan)
            for i, row in enumerate(rows):
                if row is not None:
                    out[i, : len(row)] = [np.nan if v is None else float(v) for v in row]
            self._lists[name] = (out, lengths)
        return self._lists[name]

    def _blank(self, *lead: int) -> np.ndarray:
        return np.full((*lead, len(RISK_CELLS), self.k), np.nan)

    def values(
        self, menu: str, arm: Arm, column: str, seed: int, *, realized: bool = False
    ) -> np.ndarray:
        """A float column as cells x K (NaN missing); ``realized`` applies the realized mask."""
        out = self._blank()
        found = self._groups.get((menu, arm[0], arm[1], seed))
        if found is not None:
            rows, cells, origins, _ = found
            out[cells, origins] = self._float(column)[rows]
        if realized:
            out[:, ~self.mask] = np.nan
        return out

    def lists(self, menu: str, arm: Arm, column: str, seed: int) -> np.ndarray:
        """A list column (weights, bank figures) as entries x cells x K.

        The entries are as many as the longest list among this menu's rows of the column (the
        menu's fund count for weights), so menus of different sizes never pad each other.
        """
        table, lengths = self._list(column)
        found = self._groups.get((menu, arm[0], arm[1], seed))
        mine = self._menu_rows.get(menu)
        width = 0 if mine is None or mine.size == 0 else int(lengths[mine].max())
        out = self._blank(width)
        if found is not None:
            rows, cells, origins, _ = found
            out[:, cells, origins] = table[rows, :width].T
        return out

    def slots(self, menu: str, arm: Arm, column: str, seed: int) -> np.ndarray:
        """A list column with one entry per stood-for risk cell (turnover) as cells x K."""
        table, _ = self._list(column)
        out = self._blank()
        found = self._groups.get((menu, arm[0], arm[1], seed))
        if found is not None and table.shape[1]:
            rows, cells, origins, slots = found
            out[cells, origins] = table[rows, slots]
        return out

    def objects(self, menu: str, arm: Arm, column: str, seed: int) -> list[list[Any]]:
        """Any column as cells x K Python values (None missing)."""
        out: list[list[Any]] = [[None] * self.k for _ in RISK_CELLS]
        found = self._groups.get((menu, arm[0], arm[1], seed))
        if found is not None:
            values = self._table[column].to_pylist()
            for row, cell, origin in zip(*(part.tolist() for part in found[:3]), strict=True):
                out[cell][origin] = values[row]
        return out


# ---------------------------------------------------------------------------- measurements


@dataclass(frozen=True)
class BankReplay:
    u: float | None
    bad: float | None
    typical: float | None
    good: float | None
    cells_u: Mapping[str, float | None]
    es: float | None = None  # ΔES_2.5, a diagnostic (protocol 6, D4), never a criterion


@dataclass(frozen=True)
class Replay:
    """Paired replay contrasts (first minus second) of one menu under one setting."""

    u: float | None
    bad: float | None
    typical: float | None
    good: float | None
    cells_u: Mapping[str, float | None]
    banks: tuple[BankReplay, ...]
    es: float | None = None  # ΔES_2.5, a diagnostic (protocol 6, D4), never a criterion


def _points(d: np.ndarray, k: int) -> tuple[float | None, dict[str, float | None]]:
    whole = _point(lambda i: origin_mean(d, i), k)
    return whole, {
        c: _point(lambda i, x=d[j]: cell_mean(x, i), k) for j, c in enumerate(RISK_CELLS)
    }


def replay_contrast(grid: Grid, menu: str, first: Arm, second: Arm, seed: int) -> Replay:
    """Pooled-test and per-bank paired ΔU/ΔB/ΔT/ΔG (and ΔES) of ``first`` minus ``second``."""
    names = ("utility", "bad", "typical", "good", "es_25")
    pooled = {
        name: grid.values(menu, first, f"test_{name}", seed)
        - grid.values(menu, second, f"test_{name}", seed)
        for name in names
    }
    banks = {
        name: grid.lists(menu, first, f"bank_{name}", seed)
        - grid.lists(menu, second, f"bank_{name}", seed)
        for name in names
    }
    count = banks["utility"].shape[0]
    if any(values.shape[0] not in (0, count) for values in banks.values()):
        raise ValueError(f"{menu}: the bank columns hold different numbers of banks")

    def bank(name: str, b: int) -> float | None:
        return _points(banks[name][b], grid.k)[0] if banks[name].shape[0] else None

    u, cells = _points(pooled["utility"], grid.k)
    out = []
    for b in range(count):
        bank_u, bank_cells = _points(banks["utility"][b], grid.k)
        out.append(
            BankReplay(
                u=bank_u,
                bad=bank("bad", b),
                typical=bank("typical", b),
                good=bank("good", b),
                cells_u=bank_cells,
                es=bank("es_25", b),
            )
        )
    return Replay(
        u=u,
        bad=_points(pooled["bad"], grid.k)[0],
        typical=_points(pooled["typical"], grid.k)[0],
        good=_points(pooled["good"], grid.k)[0],
        cells_u=cells,
        banks=tuple(out),
        es=_points(pooled["es_25"], grid.k)[0],
    )


def _weights_l1(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """L1 between two (funds x cells x K) weight grids, NaN where either is missing."""
    if first.shape[0] == 0:
        return np.full(first.shape[1:], np.nan)
    missing = ~(np.isfinite(first).all(axis=0) & np.isfinite(second).all(axis=0))
    return np.where(missing, np.nan, np.abs(first - second).sum(axis=0))


@dataclass(frozen=True)
class Stability:
    """Across-optimizer-seed stability of one arm in one menu, per risk cell (protocol 6)."""

    median_l1: Mapping[str, float | None]
    p90_l1: Mapping[str, float | None]
    bad_sd_share: Mapping[str, float | None]
    turnover_median: Mapping[str, float | None]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


def stability(
    grid: Grid, menu: str, arm: Arm, primary_seed: int, volatility_arm: Arm | None = None
) -> Stability:
    """Pairwise L1, the Bad SD share, turnover and diagnostics across every optimizer seed."""
    seeds = grid.seeds
    weights = {seed: grid.lists(menu, arm, "weights", seed) for seed in seeds}
    figures = {
        name: np.stack([grid.values(menu, arm, f"test_{name}", seed) for seed in seeds])
        for name in ("bad", "typical", "good", "utility", "es_25")
    }
    vol = grid.values(menu, volatility_arm or arm, "risk", primary_seed)
    turnover = np.stack([grid.slots(menu, arm, "turnover_prev", seed) for seed in seeds])
    primary_turnover = grid.slots(menu, arm, "turnover_prev", primary_seed)
    bank = {
        name: grid.lists(menu, arm, f"bank_{name}", primary_seed)
        for name in ("bad", "typical", "good", "utility", "es_25")
    }
    sd = {name: _seed_sd(values) for name, values in figures.items()}
    median_l1, p90_l1, share, turn = {}, {}, {}, {}
    diagnostics: dict[str, Any] = {"seeds": list(seeds), "cells": {}}
    for j, cell in enumerate(RISK_CELLS):
        pairs = []
        for t in range(grid.k):
            present = [s for s in seeds if np.isfinite(weights[s][:, j, t]).all()]
            present = [s for s in present if weights[s].shape[0] > 0]
            for a, b in itertools.combinations(present, 2):
                pairs.append(math.fsum(np.abs(weights[a][:, j, t] - weights[b][:, j, t])))
        median_l1[cell], p90_l1[cell] = percentile(pairs, 50), percentile(pairs, 90)
        defined = np.isfinite(sd["bad"][j]) & np.isfinite(vol[j])
        share[cell] = (
            float(np.mean(sd["bad"][j][defined] <= BAD_SD_FACTOR * vol[j][defined]))
            if defined.any()
            else None
        )
        pooled_turnover = turnover[:, j, :].ravel()
        turn[cell] = percentile(pooled_turnover.tolist(), 50)
        diagnostics["cells"][cell] = {
            "pairs": len(pairs),
            "origins_with_seed_sd": int(defined.sum()),
            "seed_sd_median": {name: percentile(sd[name][j].tolist(), 50) for name in sd},
            # the primary seed's fixed weights across the five test banks: Monte Carlo variation
            "bank_sd_median_primary": {
                name: percentile(_seed_sd(values[:, j, :]).tolist(), 50)
                if values.shape[0]
                else None
                for name, values in bank.items()
            },
            "turnover_median_primary": percentile(primary_turnover[j].tolist(), 50),
            "turnover_values": int(np.isfinite(pooled_turnover).sum()),
        }
    return Stability(median_l1, p90_l1, share, turn, diagnostics)


def _seed_sd(values: np.ndarray) -> np.ndarray:
    """The ddof-1 standard deviation across seeds (axis 0) where at least two seeds have one."""
    ok = np.isfinite(values)
    count = ok.sum(axis=0)
    out = np.full(values.shape[1:], np.nan)
    for index in zip(*np.nonzero(count >= 2), strict=True):
        column = values[(slice(None), *index)]
        out[index] = float(np.std(column[np.isfinite(column)], ddof=1))
    return out


def score_change(
    grid: Grid, menu: str, first: Arm, second: Arm, seed: int
) -> tuple[float | None, float | None]:
    """Mean raw DR² gain and the share of cells whose weights differ by L1 >= .02."""
    gain = grid.values(menu, first, "dr2", seed) - grid.values(menu, second, "dr2", seed)
    l1 = _weights_l1(
        grid.lists(menu, first, "weights", seed), grid.lists(menu, second, "weights", seed)
    )
    changed = np.where(np.isfinite(l1), (l1 >= CHANGED_L1).astype(float), np.nan)
    return _point(lambda i: origin_mean(gain, i), grid.k), _point(
        lambda i: origin_mean(changed, i), grid.k
    )


@dataclass(frozen=True)
class RealizedCell:
    """The protocol 7 realized guardrail figures of one risk cell (positive is worse)."""

    median_loss: float | None  # median(R) - median(R+D) across origins (ruling 7)
    mean_loss: float | None  # minus the mean paired annual-return difference
    loss_increase: float | None  # loss frequency of R+D minus that of R
    drawdown_worsening: float | None  # mean paired maximum-drawdown difference, R+D minus R


@dataclass(frozen=True)
class RealizedEvidence:
    gain: Estimate  # mean paired realized annual-return difference, 99%
    drawdown_improvement: Estimate  # mean paired maximum-drawdown improvement, 99%
    mean_loss: float | None  # menu-level minus the mean paired difference
    cells: Mapping[str, RealizedCell]
    disjoint: int  # disjoint annual intervals of the realized panel in this menu


def realized(
    grid: Grid,
    menu: str,
    first: Arm,
    second: Arm,
    seed: int,
    boot: Bootstrap,
    disjoint: int,
) -> RealizedEvidence:
    """Realized benefit endpoints (99% intervals) and the guardrail figures per risk cell."""
    y1 = grid.values(menu, first, "annual_return", seed, realized=True)
    y2 = grid.values(menu, second, "annual_return", seed, realized=True)
    paired = np.isfinite(y1) & np.isfinite(y2)
    y1, y2 = np.where(paired, y1, np.nan), np.where(paired, y2, np.nan)
    dd1 = np.where(paired, grid.values(menu, first, "max_drawdown", seed), np.nan)
    dd2 = np.where(paired, grid.values(menu, second, "max_drawdown", seed), np.nan)
    loss1 = np.where(paired, grid.values(menu, first, "loss", seed), np.nan)
    loss2 = np.where(paired, grid.values(menu, second, "loss", seed), np.nan)
    difference, improvement = y1 - y2, dd2 - dd1
    n = _count(difference)
    gain = boot.estimate(lambda i: origin_mean(difference, i), SUPPORT_LEVEL, n)
    drawdown = boot.estimate(lambda i: origin_mean(improvement, i), SUPPORT_LEVEL, n)
    cells = {}
    for j, cell in enumerate(RISK_CELLS):
        mean_difference = _point(lambda i, x=difference[j]: cell_mean(x, i), grid.k)
        median1, median2 = percentile(y1[j].tolist(), 50), percentile(y2[j].tolist(), 50)
        rate1 = _point(lambda i, x=loss1[j]: cell_mean(x, i), grid.k)
        rate2 = _point(lambda i, x=loss2[j]: cell_mean(x, i), grid.k)
        cells[cell] = RealizedCell(
            median_loss=None if median1 is None or median2 is None else median2 - median1,
            mean_loss=None if mean_difference is None else -mean_difference,
            loss_increase=None if rate1 is None or rate2 is None else rate1 - rate2,
            drawdown_worsening=_point(lambda i, x=dd1[j] - dd2[j]: cell_mean(x, i), grid.k),
        )
    mean_gain = gain.value
    return RealizedEvidence(
        gain=gain,
        drawdown_improvement=drawdown,
        mean_loss=None if mean_gain is None else -mean_gain,
        cells=cells,
        disjoint=disjoint,
    )


def calibration(grid: Grid, menu: str, arm: Arm, seed: int, forecast: str) -> dict[str, Any]:
    """Per quantile: nominal level, empirical coverage `1[y <= f]` and mean pinball loss."""
    y = grid.values(menu, arm, "annual_return", seed, realized=True)
    out: dict[str, Any] = {}
    for name, q in QUANTILES:
        f = grid.values(menu, arm, f"{forecast}_{name}", seed)
        ok = np.isfinite(y) & np.isfinite(f)
        loss, cover = np.full(y.shape, np.nan), np.full(y.shape, np.nan)
        if ok.any():
            loss[ok] = evaluate.pinball(q, y[ok], f[ok])
            cover[ok] = evaluate.at_or_below(y[ok], f[ok]).astype(float)
        out[name] = {
            "nominal": q,
            "menu": {
                "coverage": _point(lambda i, x=cover: origin_mean(x, i), grid.k),
                "pinball": _point(lambda i, x=loss: origin_mean(x, i), grid.k),
                "n": _count(cover),
            },
            "cells": {
                cell: {
                    "coverage": _point(lambda i, x=cover[j]: cell_mean(x, i), grid.k),
                    "pinball": _point(lambda i, x=loss[j]: cell_mean(x, i), grid.k),
                    "n": _count(cover[j]),
                }
                for j, cell in enumerate(RISK_CELLS)
            },
        }
    return out


@dataclass(frozen=True)
class Cost:
    """The protocol 7 cost figures of one menu (Stage 1 cells, warm arm-search wall time)."""

    r_wall_p95: float | None
    ratio_p95: float | None
    cells: int


def arm_walls(records: Sequence[Mapping[str, Any]], menu: str, profile: str = "stage-1"):
    """Per Stage 1 cell of ``menu``: {arm: wall} from the `cell` records of resources.jsonl."""
    out = []
    for record in records:
        if record.get("kind") != "cell" or record.get("profile") != profile:
            continue
        if json.loads(record["cell_key"])[0] != menu:
            continue
        out.append({arm["arm"]: float(arm["wall"]) for arm in record.get("arms", [])})
    return out


def cost(records: Sequence[Mapping[str, Any]], menu: str) -> Cost:
    walls = arm_walls(records, menu)
    r_walls = [cell["R"] for cell in walls if "R" in cell]
    ratios = [
        cell["R+D"] / cell["R"] for cell in walls if {"R", "R+D"} <= set(cell) and cell["R"] > 0
    ]
    return Cost(percentile(r_walls, 95), percentile(ratios, 95), len(r_walls))


@dataclass(frozen=True)
class MenuEvidence:
    """Everything protocol 7 decides one menu on (primary seed; stability over every seed)."""

    menu: str
    replay: Replay
    stability: Mapping[str, Stability]  # by arm label: "R", "R+D"
    dr2_gain: float | None
    changed_share: float | None
    cost: Cost
    realized: RealizedEvidence


# -------------------------------------------------------------------------------- decisions


@dataclass(frozen=True)
class Criterion:
    menu: str
    dimension: str
    key: str
    location: str  # "menu" or a risk cell
    test: str
    value: float | None
    threshold: float | None  # None when the line itself is undefined (see `reason`)
    passed: bool | None  # None: recorded for completeness, not assessed (see `reason`)
    reason: str | None = None

    def text(self) -> str:
        where = "" if self.location == "menu" else f" in {self.location}"
        value = "undefined" if self.value is None else f"{self.value:.6g}"
        why = "" if self.reason is None else f"; {self.reason}"
        return f"{self.menu}: {self.dimension}: {self.test}{where} (value {value}{why})"

    def record(self) -> dict[str, Any]:
        return {
            "menu": self.menu,
            "dimension": self.dimension,
            "key": self.key,
            "location": self.location,
            "test": self.test,
            "value": self.value,
            "threshold": self.threshold,
            "passed": self.passed,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Validity:
    valid: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Disclosure:
    """One sensitivity setting of one menu against its qualifying branch (protocol 7)."""

    menu: str
    setting: str
    available: bool
    u: float | None
    sign_reversal: bool
    floors: bool  # every return floor of the branch holds
    banks_positive: int
    bank_floors: int
    inert: bool
    blocking: bool
    reasons: tuple[str, ...]
    branch: str | None = None  # the menu's qualifying branch it is judged against
    baseline: float | None = None  # Stage 1's pooled ΔU on the same six origins (R27)

    def record(self) -> dict[str, Any]:
        return {
            "menu": self.menu,
            "setting": self.setting,
            "branch": self.branch,
            "baseline_u": self.baseline,
            "available": self.available,
            "u": self.u,
            "sign_reversal": self.sign_reversal,
            "floors": self.floors,
            "banks_positive_u": self.banks_positive,
            "banks_meeting_floors": self.bank_floors,
            "inert": self.inert,
            "blocking": self.blocking,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class MenuVerdict:
    conditional: str
    branch: str | None
    pcme: bool
    score_change: str
    realized: str
    support: bool
    tail_power: str
    intervals: str
    sensitivity: str


@dataclass(frozen=True)
class Verdict:
    valid: bool
    validity_reasons: tuple[str, ...]
    criteria: tuple[Criterion, ...]
    menus: Mapping[str, MenuVerdict]
    disclosures: tuple[Disclosure, ...]
    material_harm: tuple[Criterion, ...]
    confirmed_worthwhile_benefit: bool
    stage_2: Mapping[str, Any]


def _test(value: float | None, threshold: float, op: str) -> bool:
    if value is None or not math.isfinite(value):
        return False
    return {"ge": value >= threshold, "le": value <= threshold, "gt": value > threshold}[op]


Check = tuple[str, str, float | None, float, str]  # key, test, value, line, operator


class _Rules:
    """Collects the criteria of one menu."""

    def __init__(self, menu: str) -> None:
        self.menu = menu
        self.items: list[Criterion] = []

    def check(self, dimension: str, checks: Sequence[Check], location: str = "menu") -> bool:
        """Record every check (no short circuit); True when all of them pass."""
        passed = []
        for key, test, value, line, op in checks:
            ok = _test(value, line, op)
            self.items.append(Criterion(self.menu, dimension, key, location, test, value, line, ok))
            passed.append(ok)
        return all(passed)

    def record(
        self,
        dimension: str,
        key: str,
        test: str,
        value: float | None,
        threshold: float | None,
        reason: str,
        *,
        passed: bool | None = None,
        location: str = "menu",
    ) -> bool:
        """A criterion that is not assessed (``passed`` None) or cannot pass, with its reason."""
        self.items.append(
            Criterion(self.menu, dimension, key, location, test, value, threshold, passed, reason)
        )
        return passed is True


def _mean(values: Sequence[float | None]) -> float | None:
    finite = [v for v in values if v is not None and math.isfinite(v)]
    return sum(finite) / len(finite) if finite else None


def _floors_hold(r: Replay | BankReplay, pooled_u: bool) -> bool:
    checks = [
        _test(r.bad, B_FLOOR, "ge"),
        _test(r.typical, T_FLOOR, "ge"),
        _test(r.good, G_FLOOR, "ge"),
        *(_test(r.cells_u.get(cell), U_FLOOR, "ge") for cell in RISK_CELLS),
    ]
    if pooled_u:
        checks.append(_test(r.u, U_FLOOR, "ge"))
    return all(checks)


def _positive_banks(r: Replay) -> int:
    return sum(1 for bank in r.banks if _test(bank.u, 0.0, "gt"))


def _floor_banks(r: Replay) -> int:
    return sum(1 for bank in r.banks if _floors_hold(bank, pooled_u=True))


def _return_checks(prefix: str, r: Replay, u_line: float, u_test: str) -> list[Check]:
    return [
        (f"{prefix}.u", u_test, r.u, u_line, "ge"),
        (f"{prefix}.bad", "mean paired ΔB >= -5 bp", r.bad, B_FLOOR, "ge"),
        (f"{prefix}.typical", "mean paired ΔT >= -10 bp", r.typical, T_FLOOR, "ge"),
        (f"{prefix}.good", "mean paired ΔG >= -20 bp", r.good, G_FLOOR, "ge"),
    ]


def _cell_floors(rules: _Rules, dimension: str, prefix: str, r: Replay) -> bool:
    test = "risk-cell mean ΔU >= -2.5 bp"
    return all(
        [
            rules.check(dimension, [(f"{prefix}.cell_u", test, r.cells_u.get(c), U_FLOOR, "ge")], c)
            for c in RISK_CELLS
        ]
    )


def _replay_branch(rules: _Rules, r: Replay) -> bool:
    dim = "Independent replay return gain"
    banks = float(_positive_banks(r))
    return all(
        [
            rules.check(
                dim, _return_checks("replay", r, REPLAY_GAIN, "pooled mean paired ΔU >= 5 bp")
            ),
            _cell_floors(rules, dim, "replay", r),
            rules.check(
                dim,
                [
                    (
                        "replay.banks",
                        "test banks with positive mean ΔU >= 4 of 5",
                        banks,
                        BANKS_NEEDED,
                        "ge",
                    )
                ],
            ),
        ]
    )


_L1_TESTS = (
    ("stability.l1_relative", "median pairwise L1 reduction >= 20% (R+D vs R)", L1_RELATIVE, "ge"),
    ("stability.l1_absolute", "median pairwise L1 reduction >= .02", L1_ABSOLUTE, "ge"),
    ("stability.l1_p90", "90th-percentile pairwise L1 not worse (R+D - R <= 0)", 0.0, "le"),
)


def _stability_branch(rules: _Rules, r: Replay, arms: Mapping[str, Stability]) -> bool:
    """The stable-gain alternative, assessed only below a 5 bp pooled ΔU (ruling R24-3).

    Above that line the branch is recorded as not assessed, with the cross-seed L1 comparison
    kept as information, so that the threshold table lists every row of protocol 7.
    """
    dim = "Stable gain alternative"
    base, arm = arms["R"], arms["R+D"]
    median_r, median_rd = _mean(list(base.median_l1.values())), _mean(list(arm.median_l1.values()))
    p90_r, p90_rd = _mean(list(base.p90_l1.values())), _mean(list(arm.p90_l1.values()))
    relative = absolute = p90_change = None
    if median_r is not None and median_rd is not None:
        absolute = median_r - median_rd
        relative = absolute / median_r if median_r > 0 else None
    if p90_r is not None and p90_rd is not None:
        p90_change = p90_rd - p90_r
    l1 = dict(zip((key for key, *_ in _L1_TESTS), (relative, absolute, p90_change), strict=True))
    if r.u is None or r.u >= REPLAY_GAIN:
        why = "pooled ΔU undefined" if r.u is None else "pooled ΔU >= 5 bp"
        rules.record(
            dim,
            "stability.assessed",
            "evaluated only when pooled mean paired ΔU < 5 bp",
            r.u,
            REPLAY_GAIN,
            f"not assessed: {why} (R24-3)",
        )
        for key, test, line, _ in _L1_TESTS:
            rules.record(
                dim, key, test, l1[key], line, "informational: the stability branch is not assessed"
            )
        return False
    floors = float(_floor_banks(r))
    return all(
        [
            rules.check(
                dim, _return_checks("stability", r, U_FLOOR, "pooled mean paired ΔU >= -2.5 bp")
            ),
            _cell_floors(rules, dim, "stability", r),
            rules.check(
                dim,
                [
                    (
                        "stability.bank_floors",
                        "test banks meeting every floor >= 4 of 5",
                        floors,
                        BANKS_NEEDED,
                        "ge",
                    ),
                    *[(key, test, l1[key], line, op) for key, test, line, op in _L1_TESTS],
                ],
            ),
        ]
    )


def _general_stability(rules: _Rules, arms: Mapping[str, Stability]) -> bool:
    dim = "General stability"
    arm, base = arms["R+D"], arms["R"]
    turnover_test = "median adjacent-origin turnover <= R's + .05"
    ok = []
    for cell in RISK_CELLS:
        checks: list[Check] = [
            (
                "general.bad_sd",
                "share of origins with seed SD of Bad <= .10 x primary volatility >= 95%",
                arm.bad_sd_share.get(cell),
                BAD_SD_SHARE,
                "ge",
            ),
            (
                "general.median_l1",
                "median pairwise weight L1 <= .20",
                arm.median_l1.get(cell),
                MEDIAN_L1,
                "le",
            ),
            (
                "general.p90_l1",
                "90th-percentile pairwise weight L1 <= .40",
                arm.p90_l1.get(cell),
                P90_L1,
                "le",
            ),
        ]
        base_turnover = base.turnover_median.get(cell)
        if base_turnover is not None:
            line = base_turnover + TURNOVER_SLACK
            checks.append(
                ("general.turnover", turnover_test, arm.turnover_median.get(cell), line, "le")
            )
        ok.append(rules.check(dim, checks, cell))
        if base_turnover is None:
            reason = (
                "R's median adjacent-origin turnover is undefined in this risk cell (no adjacent "
                "pair of origins), so the comparison cannot pass"
            )
            ok.append(
                rules.record(
                    dim,
                    "general.turnover",
                    turnover_test,
                    arm.turnover_median.get(cell),
                    None,
                    reason,
                    passed=False,
                    location=cell,
                )
            )
    return all(ok)


def _realized_rules(rules: _Rules, e: RealizedEvidence) -> bool:
    """The guardrails per risk cell, then realized benefit support (returned)."""
    guard = []
    for cell in RISK_CELLS:
        f = e.cells.get(cell, RealizedCell(None, None, None, None))
        guard.append(
            rules.check(
                "Realized guardrails",
                [
                    (
                        "guard.median_loss",
                        "annual-return median loss <= 25 bp",
                        f.median_loss,
                        MEDIAN_LOSS,
                        "le",
                    ),
                    (
                        "guard.mean_loss",
                        "mean annual-return loss <= 25 bp",
                        f.mean_loss,
                        MEAN_LOSS,
                        "le",
                    ),
                    (
                        "guard.loss_frequency",
                        "loss-frequency increase <= 5 pp",
                        f.loss_increase,
                        LOSS_FREQUENCY,
                        "le",
                    ),
                    (
                        "guard.drawdown",
                        "mean maximum-drawdown worsening <= 1 pp",
                        f.drawdown_worsening,
                        DRAWDOWN_WORSENING,
                        "le",
                    ),
                ],
                cell,
            )
        )
    dim = "Realized benefit support"
    gain = rules.check(
        dim,
        [
            (
                "support.gain",
                "mean paired realized annual-return gain >= 25 bp",
                e.gain.value,
                SUPPORT_GAIN,
                "ge",
            ),
            ("support.gain_lower", "its 99% interval lower bound > 0", e.gain.lower(), 0.0, "gt"),
        ],
    )
    drawdown = rules.check(
        dim,
        [
            (
                "support.drawdown",
                "mean maximum-drawdown improvement >= 1 pp",
                e.drawdown_improvement.value,
                SUPPORT_DRAWDOWN,
                "ge",
            ),
            (
                "support.drawdown_lower",
                "its 99% improvement lower bound > 0",
                e.drawdown_improvement.lower(),
                0.0,
                "gt",
            ),
            (
                "support.mean_loss",
                "mean annual-return loss <= 25 bp (drawdown route)",
                e.mean_loss,
                MEAN_LOSS,
                "le",
            ),
        ],
    )
    breaches = float(len(guard) - sum(guard))
    required = rules.check(
        dim,
        [
            (
                "support.disjoint",
                "disjoint annual intervals >= 20",
                float(e.disjoint),
                SUPPORT_DISJOINT,
                "ge",
            ),
            (
                "support.guardrails",
                "every realized guardrail holds (risk cells breaching)",
                breaches,
                0.0,
                "le",
            ),
        ],
    )
    return (gain or drawdown) and required


_HARM_KEYS = {"replay.bad", "replay.typical", "replay.good", "replay.cell_u", "harm.u"}
_PCME_DIMENSIONS = {
    "Independent replay return gain",
    "Stable gain alternative",
    "Meaningful score change",
    "General stability",
    "Cost",
}
_UNAVAILABLE = (
    "unavailable: the setting was not run, failed its validity checks or produced no paired outcome"
)
_NO_STABILITY = "stability sensitivity unavailable: the sensitivities run the primary seed only"


_INERT = (
    "a diagnostic control, inert by construction (R+D = w_R or a 1e-12 U tie): never blocks "
    "Stage 2 (protocol amendment R26)"
)
_NO_BASELINE = "Stage 1 six-origin baseline unavailable: a sign reversal cannot be ruled out (R27)"


def _disclose(
    menu: str, branch: str | None, baseline: Replay | None, setting: str, found: Replay | None
) -> Disclosure:
    """One setting against the menu's qualifying branch (ruling 1) and, for its sign, against
    ``baseline``, Stage 1 on the same six origins (R27); the 0 bp cap never blocks (R26)."""
    inert = setting in INERT_SETTINGS
    base = None if baseline is None else baseline.u
    if found is None:
        return Disclosure(
            menu,
            setting,
            False,
            None,
            False,
            False,
            0,
            0,
            inert,
            not inert and branch is not None,
            (_INERT, _UNAVAILABLE) if inert else (_UNAVAILABLE,),
            branch,
            base,
        )
    reversal = bool(
        found.u is not None and base is not None and np.sign(found.u) == -np.sign(base) != 0
    )
    positive, floor_banks = _positive_banks(found), _floor_banks(found)
    floors = _floors_hold(found, pooled_u=branch != REPLAY_BRANCH)
    reasons: list[str] = []
    if branch == REPLAY_BRANCH:
        reasons += [_NO_BASELINE] if base is None else []
        reasons += ["replay-return sign reversal"] if reversal else []
        reasons += [] if floors else ["a return floor fails"]
        reasons += (
            [] if positive >= BANKS_NEEDED else [f"positive mean ΔU in {positive} of 5 banks"]
        )
    elif branch == STABILITY_BRANCH:
        reasons += [] if floors else ["a return floor fails"]
        reasons += (
            []
            if floor_banks >= BANKS_NEEDED
            else [f"every floor holds in {floor_banks} of 5 banks"]
        )
    if inert:
        reasons.insert(0, _INERT)
    blocking = not inert and branch is not None and bool(reasons)
    return Disclosure(
        menu,
        setting,
        True,
        found.u,
        reversal,
        floors,
        positive,
        floor_banks,
        inert,
        blocking,
        tuple(reasons),
        branch,
        base,
    )


def decide(
    validity: Validity,
    menus: Mapping[str, MenuEvidence],
    sensitivities: Mapping[str, Mapping[str, Replay | None]],
    baselines: Mapping[str, Replay | None],
) -> Verdict:
    """Every protocol 7 criterion, label and the Stage 2 decision (module docstring).

    ``sensitivities`` holds each menu's six-origin setting contrasts (None: unavailable),
    ``baselines`` each menu's Stage 1 contrast on the same six origins.
    """
    criteria: list[Criterion] = []
    verdicts: dict[str, MenuVerdict] = {}
    disclosures: list[Disclosure] = []
    failing: list[str] = [f"validity: {reason}" for reason in validity.reasons]
    for name, e in menus.items():
        if name not in COST_R_P95:
            raise ValueError(f"no protocol 7 cost line for menu {name!r}")
        rules = _Rules(name)
        replay_ok = _replay_branch(rules, e.replay)
        stability_ok = _stability_branch(rules, e.replay, e.stability)  # ruling 3 inside
        branch = REPLAY_BRANCH if replay_ok else STABILITY_BRANCH if stability_ok else None
        score = rules.check(
            "Meaningful score change",
            [
                ("score.dr2", "mean raw DR² gain >= .10", e.dr2_gain, DR2_GAIN, "ge"),
                (
                    "score.changed",
                    "share of cells with L1(R+D, R) >= .02 >= 20%",
                    e.changed_share,
                    CHANGED_SHARE,
                    "ge",
                ),
            ],
        )
        general = _general_stability(rules, e.stability)
        cost_ok = rules.check(
            "Cost",
            [
                (
                    "cost.r_wall",
                    f"p95 warm R arm-search wall <= {COST_R_P95[name]:g} s per cell",
                    e.cost.r_wall_p95,
                    COST_R_P95[name],
                    "le",
                ),
                (
                    "cost.ratio",
                    "p95 of paired wall(R+D)/wall(R) <= 1.25",
                    e.cost.ratio_p95,
                    COST_RATIO_P95,
                    "le",
                ),
            ],
        )
        rules.check(
            "Independent replay return floors",
            [
                ("harm.u", "pooled mean paired ΔU >= -2.5 bp", e.replay.u, U_FLOOR, "ge"),
            ],
        )
        support = _realized_rules(rules, e.realized) and validity.valid
        pcme = validity.valid and branch is not None and score and general and cost_ok
        # an invalid experiment has no qualifying branch: no label derives from its statistics
        assessed = branch if validity.valid else None
        settings = sensitivities.get(name, {})
        baseline = baselines.get(name)
        found = [
            _disclose(name, assessed, baseline, setting, settings.get(setting))
            for setting in SENSITIVITY_SETTINGS
        ]
        if assessed == STABILITY_BRANCH:
            found.append(
                Disclosure(
                    name,
                    "cross-seed stability",
                    False,
                    None,
                    False,
                    False,
                    0,
                    0,
                    False,
                    True,
                    (_NO_STABILITY,),
                    assessed,
                    None if baseline is None else baseline.u,
                )
            )
        disclosures += found
        blocked = [d for d in found if d.blocking]
        if validity.valid and not pcme:
            failing += [
                c.text()
                for c in rules.items
                if c.dimension in _PCME_DIMENSIONS and c.passed is False
            ]
        elif pcme:
            failing += [f"{name}: sensitivity {d.setting}: {'; '.join(d.reasons)}" for d in blocked]
        disjoint = e.realized.disjoint
        valid = validity.valid
        verdicts[name] = MenuVerdict(
            conditional=INVALID if not valid else PCME if pcme else NOT_MET,
            branch=assessed,
            pcme=pcme,
            score_change=INVALID if not valid else ACTIVE if score else INACTIVE,
            realized=INVALID if not valid else SUPPORT if support else INCONCLUSIVE,
            support=support,
            tail_power=UNDERPOWERED if disjoint < TAIL_DISJOINT else TAIL_ADEQUATE,
            intervals=EXPLORATORY if disjoint < SUPPORT_DISJOINT else NOT_EXPLORATORY,
            sensitivity=INVALID
            if not valid
            else NO_BRANCH
            if branch is None
            else SENSITIVE
            if blocked
            else ROBUST,
        )
        criteria += rules.items
    harm = tuple(
        c
        for c in criteria
        if c.passed is False and (c.key in _HARM_KEYS or c.key.startswith("guard."))
    )
    pcme_all = bool(verdicts) and all(v.pcme for v in verdicts.values())
    blocking = any(d.blocking for d in disclosures if verdicts[d.menu].pcme)
    run = validity.valid and pcme_all and not blocking
    if run:
        reason = (
            "Stage 2 (R+E, ENB) runs: positive conditional-model evidence in both menus and "
            "no blocking sensitivity disclosure (protocol 1 and 7, D7)."
        )
    else:
        why = (
            "the experiment is inconclusive/invalid"
            if not validity.valid
            else "positive conditional-model evidence is not reached in both menus"
            if not pcme_all
            else "a sensitivity disclosure (parameter/search sensitive or "
            "unverified) blocks Stage 2 progression"
        )
        reason = (
            f"Stage 2 (R+E, ENB) is skipped under the owner's stopping policy (D7): {why}. "
            "ENB unevaluated, not ineffective."
        )
    return Verdict(
        valid=validity.valid,
        validity_reasons=validity.reasons,
        criteria=tuple(criteria),
        menus=verdicts,
        disclosures=tuple(disclosures),
        material_harm=harm,
        confirmed_worthwhile_benefit=pcme_all
        and all(v.support for v in verdicts.values())
        and not harm
        and validity.valid,
        stage_2={"run": run, "reason": reason, "failing_criteria": [] if run else failing},
    )


# ----------------------------------------------------------------------- estimate tables


def paired_estimates(
    grid: Grid,
    menus: Sequence[str],
    first: Arm,
    second: Arm,
    column: str,
    seed: int,
    boot: Bootstrap,
    *,
    level: float = DESCRIPTIVE_LEVEL,
    realized: bool = False,
    reverse: bool = False,
) -> dict[str, Any]:
    """Mean paired difference (``first - second``, or reversed) per cell, menu and 50/50."""
    sign = -1.0 if reverse else 1.0
    diffs = {}
    for menu in menus:
        a = grid.values(menu, first, column, seed, realized=realized)
        b = grid.values(menu, second, column, seed, realized=realized)
        diffs[menu] = sign * (a - b)
    return _linear_table(diffs, boot, level)


def _linear_table(diffs: Mapping[str, np.ndarray], boot: Bootstrap, level: float) -> dict:
    by_cell = {
        menu: {
            cell: boot.estimate(lambda i, x=d[j]: cell_mean(x, i), level, _count(d[j]))
            for j, cell in enumerate(RISK_CELLS)
        }
        for menu, d in diffs.items()
    }
    by_menu = {
        menu: boot.estimate(lambda i, x=d: origin_mean(x, i), level, _count(d))
        for menu, d in diffs.items()
    }

    def both(index: np.ndarray) -> np.ndarray:
        return np.mean([origin_mean(d, index) for d in diffs.values()], axis=0)

    total = _count(np.vstack(list(diffs.values())))
    return {"by_cell": by_cell, "by_menu": by_menu, "aggregate": boot.estimate(both, level, total)}


def nonlinear_table(
    cell_statistics: Mapping[str, Sequence[Statistic]],
    counts: Mapping[str, Sequence[int]],
    boot: Bootstrap,
    level: float = DESCRIPTIVE_LEVEL,
) -> dict[str, Any]:
    """A statistic computed within each menu and risk cell, then averaged over cells, 50/50."""
    by_cell = {
        menu: {
            cell: boot.estimate(stats[j], level, counts[menu][j])
            for j, cell in enumerate(RISK_CELLS)
        }
        for menu, stats in cell_statistics.items()
    }

    def menu_stat(stats: Sequence[Statistic]) -> Statistic:
        return lambda index: _masked_mean(np.stack([s(index) for s in stats]), axis=0)

    by_menu = {
        menu: boot.estimate(menu_stat(stats), level, max(counts[menu], default=0))
        for menu, stats in cell_statistics.items()
    }

    def both(index: np.ndarray) -> np.ndarray:
        return np.mean([menu_stat(stats)(index) for stats in cell_statistics.values()], axis=0)

    total = max((max(c, default=0) for c in counts.values()), default=0)
    return {"by_cell": by_cell, "by_menu": by_menu, "aggregate": boot.estimate(both, level, total)}


def table_record(table: Mapping[str, Any]) -> dict[str, Any]:
    """An estimate table as JSON-ready dicts."""
    return {
        "by_cell": {
            menu: {cell: est.record() for cell, est in cells.items()}
            for menu, cells in table["by_cell"].items()
        },
        "by_menu": {menu: est.record() for menu, est in table["by_menu"].items()},
        "aggregate": table["aggregate"].record(),
    }
