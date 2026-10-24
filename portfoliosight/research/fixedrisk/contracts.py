"""Shared contracts of the fixed-risk experiment (protocol v2, revision 6).

`docs/plans/2026-10-21-fixed-risk-optimization-experiment-protocol.md` is the specification. This
module holds only the names, constants and interfaces the four build pieces agree on, so that the
optimizer, the data/driver, the GARCH engine and the measurements can be written in parallel:

- piece 1, optimizer: `banks.py` (ReplayBank), `objective.py`, `anchors.py`, `optimizer.py`,
  `agreement.py`; exposes `search_origin` with the signature of `SearchOrigin` below.
- piece 2, data and driver: `menus.py`, `data.py`, `driver.py`, `manifest.py`, `cli.py`,
  `scripts/freeze_fixed_risk_inputs.py`, `scripts/ks002_sync.sh`.
- piece 3, GARCH engine: `garch_bank.py` (GarchBank, implementing `PathBank`).
- piece 4, measurements and report: `realized.py`, `measures.py`, `cscv.py`, `dsr.py`,
  `report.py`.

Units: weights are fractions summing to 1; returns are simple decimals (0.05 = 5%); risks and
expected returns are annual decimals; daily data have one row per training day.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- protocol constants

PROTOCOL_PATH = "docs/plans/2026-10-21-fixed-risk-optimization-experiment-protocol.md"
PROTOCOL_REVISION = 6

Engine = Literal["replay", "garch"]
ENGINES: tuple[Engine, ...] = ("replay", "garch")

PATHS = 2_000
HORIZON = 252
LOOKBACK = "3y"  # 756 union-calendar rows, 90% complete (protocol §3)
SENSITIVITY_LOOKBACK = "5y"

PRIMARY_SEED = 20261013
STABILITY_SEEDS = (20261014, 20261015, 20261016, 20261017)
TEST_SEEDS = (20261113, 20261114, 20261115, 20261116, 20261117)
STABILITY_STRIDE = 4  # stability seeds on scheduled origin indices 0, 4, 8, ... (protocol §3)

RISK_FRACTIONS = (0.10, 0.25, 0.40, 0.55, 0.70, 0.85)  # X(a) = s_min + a (s(w_top) - s_min)
Cell = Literal["free", "d25", "d50", "d75"]
CELLS: tuple[Cell, ...] = ("d25", "d50", "d75", "free")  # run order: interior by d, free last
CELL_D: dict[str, float | None] = {"d25": 0.25, "d50": 0.50, "d75": 0.75, "free": None}


def cell_name(d: float) -> str:
    """The name of the interior cell at slider position `d` ("d25"; showcase "d05".."d95")."""
    return f"d{int(round(d * 100)):02d}"


# Arms: four U triples (Bad, Typical, Good weights) and max-Bad (protocol §2, owner 2026-10-23).
ARMS: dict[str, tuple[float, float, float]] = {
    "U1": (0.60, 0.30, 0.10),  # primary
    "U2": (0.70, 0.20, 0.10),
    "U3": (0.50, 0.35, 0.15),
    "U4": (0.40, 0.40, 0.20),
    "B": (1.0, 0.0, 0.0),  # max-Bad: maximizes the 2.5th percentile
}
ARM_ORDER = ("U1", "U2", "U3", "U4", "B")
QUANTILES = (0.025, 0.50, 0.975)  # Bad, Typical, Good; NumPy "linear" percentiles

TAU_R = 0.01  # risk band half-width, fraction of r
TAU_R_SENSITIVITY = 0.001
TAU_D = 0.025  # measure band half-width, fraction of the span M(w_MDP) - M(w_F)
COLLAPSE_SPAN = 1e-6
FEASIBILITY_TOL = 1e-8
STARTS = 3
SOBOL_POINTS = 256
ANCHOR_STARTS = 8
KERNEL_BANDWIDTH = 0.01
KERNEL_TRUNCATION = 4.0
SLSQP_MAXITER = 200
SLSQP_FTOL = 1e-9

# Cell labels (protocol §4), besides "ok".
OK = "ok"
INSUFFICIENT_STARTS = "insufficient_starts"
SEARCH_FAILED = "search_failed"
NOT_FOUND = "not_found"
COLLAPSED = "collapsed"
GROWTH_BOUND_FAILED = "growth_bound_failed"
FIT_FAILED = "garch_fit_failed"
# Not a row status: the task summary's count of holdings whose GARCH fit failed and that the bank
# holds at constant volatility (protocol amendment 1); their rows keep their own labels.
FIT_FALLBACK = "garch_fallback"
ANCHOR_FAILED = "anchor_failed"  # a column's anchor programs found no answer (anchors.py)
ARM_SECONDS_EXCEEDED = "arm_seconds_exceeded"  # the driver's per-task wall alarm rang
# Labels that still carry a locked mix (protocol §4: insufficient starts run with what they have;
# a growth-bound-failed bank is searched by COBYLA). Every other label is a row without a mix.
USABLE = (OK, INSUFFICIENT_STARTS, GROWTH_BOUND_FAILED)

# --------------------------------------------------------------------------- menus


@dataclass(frozen=True)
class MenuSpec:
    """A research menu: fixed holding order and per-holding bounds."""

    name: str  # "research2003" | "tsp"
    holdings: tuple[str, ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]


# --------------------------------------------------------------------------- one origin


@dataclass(frozen=True)
class OriginContext:
    """The training side of one (menu, origin, lookback). Nothing in it postdates the origin.

    Built by piece 2 (`data.origin_context`) from the v1 harness's `origin_model` machinery.
    """

    menu: MenuSpec
    month: str  # YYYY-MM ledger row
    origin: date
    lookback: str
    days: tuple[date, ...]  # training rows' dates
    sample: np.ndarray  # T x N daily simple returns of the complete rows (read-only)
    mu_hat: np.ndarray  # N, annualized sample mean (production estimate_moments().mu)
    mu_s: np.ndarray  # N, production menu_beta_blend(mu_hat, cov, rf)[0]
    cov: np.ndarray  # N x N annual covariance (production estimate_moments().cov)
    sigma: np.ndarray  # N, annual volatilities sqrt(diag(cov))
    risk_free_rate: float
    inputs_sha256: str  # digest of the above (v1 OriginModel.inputs_sha256 rule)
    # The GARCH fit window (protocol amendment 1): each holding's daily simple returns from its
    # first price up to and including the origin, on the holdings' own calendar (rows where at
    # least one has a return), NaN where a holding has none; columns in menu order. Not in
    # `inputs_sha256`; replay never reads it. `data.origin_context` always sets it.
    history: pd.DataFrame | None = field(default=None, repr=False, compare=False)


class PathBank(Protocol):
    """One engine's 2,000 simulated one-year paths for one origin and seed.

    `years(mixes)` returns a (P, M) array of compounded one-year simple returns, one column per
    mix (rows of `mixes`, each summing to 1). An absorbed GARCH path is exactly -1.0.

    `years_and_vjp(w)` returns the (P,) years of one mix and a function `vjp(a)` that, for path
    weights `a` (P,), returns the gradient with respect to `w` of `sum_p a_p R_p(w)` (N,).
    Replay: `A' [C' (a * (1 + R)) / g]` (protocol §4). GARCH: includes the `(x'w) grad k` term;
    absorbed paths contribute zero.

    `growth_bound_ok` is True when every mix in the menu's domain (w >= 0, 1'w = 1) has positive
    daily growth on every simulated day (replay: min_{t,i} b_ti > 0; GARCH: always True, since
    absorption is handled per path).
    """

    engine: Engine
    seed: int
    paths: int
    growth_bound_ok: bool

    def years(self, mixes: np.ndarray) -> np.ndarray: ...

    def years_and_vjp(
        self, w: np.ndarray
    ) -> tuple[np.ndarray, Callable[[np.ndarray], np.ndarray]]: ...


BankFactory = Callable[[OriginContext, Engine, int], PathBank]
"""`make_bank(ctx, engine, seed)`: replay from piece 1's `banks.replay_bank`, GARCH from piece 3's
`garch_bank.garch_bank`. GARCH fits per holding are cached by (holding, origin, fit window) inside
piece 3's module so every menu, seed and lookback at an origin reuses them."""


# --------------------------------------------------------------------------- search results


@dataclass(frozen=True)
class Figures:
    """Exact figures of one mix on one bank (linear percentiles of the P years)."""

    bad: float
    typical: float
    good: float
    mean: float
    es_25: float  # mean of the years at or below the 2.5th percentile

    def utility(self, arm: str) -> float:
        b, t, g = ARMS[arm]
        return b * self.bad + t * self.typical + g * self.good


NO_FIGURES = Figures(math.nan, math.nan, math.nan, math.nan, math.nan)


@dataclass(frozen=True)
class Anchors:
    """The column's fixed-risk anchors and comparators (protocol §2, §5). Engine-independent."""

    r_fraction: float
    r: float  # the fixed risk
    sigma_min: float
    sigma_top: float
    w_F: np.ndarray  # max mu_s on the band (slider top, d = 0)
    w_MDP: np.ndarray  # max M on the band (slider bottom, d = 1)
    w_BS: np.ndarray  # max Bayes-Stein mu on the band (second comparator)
    M_F: float
    M_MDP: float
    collapsed: bool  # M_MDP - M_F <= COLLAPSE_SPAN
    status: str  # OK or a named failure
    starts: int
    iterations: int
    seconds: float


@dataclass(frozen=True)
class Selection:
    """One arm's locked choice in one cell (or a native-only result for stability)."""

    menu: str
    origin: date
    engine: Engine
    seed: int  # the bank's seed
    r_fraction: float
    r: float
    cell: Cell
    arm: str
    pooled: bool  # True: the cell pool's best (free cell also pools interior visits); False: native
    weights: np.ndarray
    sigma: float
    measure: float  # M(w) = DR^2
    d: float | None  # d(w); None on a collapsed column
    figures: Figures  # exact, on this bank
    status: str  # OK or a cell label
    starts: int
    iterations: int
    seconds: float
    solver: str  # "exact_grad" | "kernel_grad" | "cobyla768" | "cobyla128"


@dataclass
class OriginResult:
    """Everything one (menu, origin, engine, seed) search produced."""

    menu: str
    origin: date
    engine: Engine
    seed: int
    anchors: list[Anchors] = field(default_factory=list)
    selections: list[Selection] = field(default_factory=list)
    comparators: list[Selection] = field(default_factory=list)  # w_F, w_BS as arm "F", "BS"
    # One row per scheduled outcome without a locked mix (status = its label, see `unselected`):
    # cells whose search found nothing, collapsed columns' interior cells, failed anchors' cells
    # and comparators. `selections` + `comparators` + `unselected` cover every scheduled outcome.
    unselected: list[Selection] = field(default_factory=list)
    labels: dict[str, int] = field(default_factory=dict)  # label -> count
    seconds: float = 0.0
    evaluations: int = 0


def unselected(
    *,
    menu: str,
    origin: date,
    engine: Engine,
    seed: int,
    r_fraction: float,
    r: float,
    cell: str,
    arm: str,
    pooled: bool,
    status: str,
    solver: str,
    starts: int = 0,
    iterations: int = 0,
    seconds: float = 0.0,
) -> Selection:
    """The row of a scheduled (r, cell, arm) outcome that has no locked mix: empty weights, NaN
    figures, `status` its label. Statistics exclude such rows and count them."""
    return Selection(
        menu=menu,
        origin=origin,
        engine=engine,
        seed=seed,
        r_fraction=r_fraction,
        r=r,
        cell=cell,  # type: ignore[arg-type]
        arm=arm,
        pooled=pooled,
        weights=np.empty(0),
        sigma=math.nan,
        measure=math.nan,
        d=None,
        figures=NO_FIGURES,
        status=status,
        starts=starts,
        iterations=iterations,
        seconds=seconds,
        solver=solver,
    )


def scheduled_outcomes(
    *,
    risk_fractions: tuple[float, ...],
    cells: tuple[str, ...],
    arms: tuple[str, ...],
    native_only: bool,
) -> list[tuple[float, str, str, bool]]:
    """`(r_fraction, cell, arm, pooled)` of every row a search is scheduled to report, comparators
    (arms "F", "BS", free cell, native) included: a pooled row per cell and arm, plus the native row
    in the free cell; native rows only when `native_only` (which runs arm U1 alone)."""
    out: list[tuple[float, str, str, bool]] = []
    arms = ("U1",) if native_only else arms
    for a in risk_fractions:
        for cell in cells:
            for arm in arms:
                if native_only:
                    out.append((a, cell, arm, False))
                    continue
                out.append((a, cell, arm, True))
                if cell == "free":
                    out.append((a, cell, arm, False))
        if not native_only:
            out += [(a, "free", "F", False), (a, "free", "BS", False)]
    return out


class SearchOrigin(Protocol):
    """Piece 1's entry point, called by piece 2's driver once per (menu, origin, engine, seed).

    `anchors` may be passed in (computed once per origin and shared by engines and seeds);
    when None they are computed. `native_only=True` runs only arm U1 on the interior and free
    cells without cross-cell pooling (the stability procedure of protocol §3). `tau_r` defaults to
    TAU_R; the sensitivity passes TAU_R_SENSITIVITY. `solver` is the engine's agreed solver.
    `risk_fractions` defaults to RISK_FRACTIONS; showcase surfaces pass 48 columns.
    `d_grid` overrides the interior cells (showcase: 19 positions d = 0.05..0.95, arm U1 only).
    Every scheduled outcome (`scheduled_outcomes`) appears once in `selections`, `comparators` or
    `unselected`.
    """

    def __call__(
        self,
        ctx: OriginContext,
        bank: PathBank,
        *,
        anchors: list[Anchors] | None = None,
        arms: tuple[str, ...] = ARM_ORDER,
        risk_fractions: tuple[float, ...] = RISK_FRACTIONS,
        d_grid: tuple[float, ...] | None = None,
        include_free: bool = True,
        native_only: bool = False,
        tau_r: float = TAU_R,
        solver: str = "exact_grad",
        starts: int = STARTS,
    ) -> OriginResult: ...
