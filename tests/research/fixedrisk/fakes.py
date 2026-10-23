"""A tiny fake path bank, fake `search_origin` and synthetic inputs for the driver tests.

The module doubles as a `--hooks` module for spawned workers: it defines `make_bank`,
`search_origin` and `load_inputs(snapshot_dir)`. Calls are recorded in `CALLS` (in-process only);
`FAIL_MONTH` (or the environment variable `FAKE_FAIL_MONTH`) makes a search raise at that month.
"""

from __future__ import annotations

import os
import zlib
from datetime import date

import exchange_calendars as xcals
import numpy as np
import pandas as pd

from portfoliosight.research.fixedrisk import contracts as C
from portfoliosight.research.fixedrisk import data
from tests.research.helpers import random_indices, record

D_STAR = date(2025, 9, 30)
PATHS = 300
CALLS: list[dict] = []
FAIL_MONTH: str | None = None

ALPHA = C.MenuSpec("research2003", ("A", "B", "C", "D"), (0.0,) * 4, (0.6,) * 4)
BETA = C.MenuSpec("tsp", ("X", "Y", "Z"), (0.0,) * 3, (0.8,) * 3)
TEST_MENUS = (ALPHA, BETA)
DRIFT_VOL = {
    "A": (3e-4, 0.010), "B": (2e-4, 0.006), "C": (4e-4, 0.013), "D": (1e-4, 0.003),
    "X": (2e-4, 0.008), "Y": (3e-4, 0.011), "Z": (1e-4, 0.004),
    "SGOV": (1.5e-4, 1e-5),
}  # fmt: skip


class FakeBank:
    growth_bound_ok = True

    def __init__(self, ctx: C.OriginContext, engine: str, seed: int) -> None:
        self.engine, self.seed, self.paths = engine, seed, PATHS
        rng = np.random.default_rng(seed + zlib.crc32(ctx.inputs_sha256.encode()) % 10_000)
        self._draws = ctx.mu_hat + ctx.sigma * rng.standard_normal((PATHS, len(ctx.mu_hat)))

    def years(self, mixes: np.ndarray) -> np.ndarray:
        return self._draws @ np.atleast_2d(mixes).T

    def years_and_vjp(self, w):  # pragma: no cover - unused by the driver
        raise NotImplementedError


def make_bank(ctx: C.OriginContext, engine: str, seed: int) -> FakeBank:
    return FakeBank(ctx, engine, seed)


def _figures(bank: FakeBank, w: np.ndarray) -> C.Figures:
    y = bank.years(w[None, :])[:, 0]
    bad, typ, good = np.percentile(y, [2.5, 50, 97.5])
    return C.Figures(
        float(bad), float(typ), float(good), float(y.mean()), float(y[y <= bad].mean())
    )


def _rng(*parts: object) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32("|".join(map(str, parts)).encode()))


def search_origin(
    ctx, bank, *, anchors=None, arms=C.ARM_ORDER, risk_fractions=C.RISK_FRACTIONS, d_grid=None,
    include_free=True, native_only=False, tau_r=C.TAU_R, solver="exact_grad", starts=C.STARTS,
) -> C.OriginResult:  # fmt: skip
    CALLS.append(
        dict(month=ctx.month, lookback=ctx.lookback, seed=bank.seed, anchors=anchors, arms=arms,
             risk_fractions=risk_fractions, d_grid=d_grid, include_free=include_free,
             native_only=native_only, tau_r=tau_r, solver=solver, starts=starts)
    )  # fmt: skip
    fail = FAIL_MONTH or os.environ.get("FAKE_FAIL_MONTH")
    if fail and ctx.month == fail:
        raise RuntimeError(f"fake failure at {ctx.month}")
    n = len(ctx.menu.holdings)
    result = C.OriginResult(
        menu=ctx.menu.name, origin=ctx.origin, engine=bank.engine, seed=bank.seed
    )
    if native_only:
        arms = ("U1",)
    cells = [f"d{round(100 * d):02d}" for d in (d_grid or (0.25, 0.50, 0.75))]
    cells += ["free"] if include_free else []
    given = {a.r_fraction: a for a in anchors or []}
    for a in risk_fractions:
        anchor = given.get(a) or C.Anchors(
            r_fraction=a, r=0.04 + 0.1 * a, sigma_min=0.03, sigma_top=0.20,
            w_F=_rng("F", ctx.month, a).dirichlet(np.ones(n)),
            w_MDP=_rng("M", ctx.month, a).dirichlet(np.ones(n)),
            w_BS=_rng("B", ctx.month, a).dirichlet(np.ones(n)),
            M_F=1.0, M_MDP=2.0, collapsed=False, status=C.OK, starts=8, iterations=5, seconds=0.001,
        )  # fmt: skip
        result.anchors.append(anchor)
        for cell in cells:
            for arm in arms:
                w = _rng("S", ctx.menu.name, ctx.month, bank.seed, a, cell, arm).dirichlet(
                    np.ones(n)
                )
                result.selections.append(
                    C.Selection(
                        menu=ctx.menu.name,
                        origin=ctx.origin,
                        engine=bank.engine,
                        seed=bank.seed,
                        r_fraction=a,
                        r=anchor.r,
                        cell=cell,
                        arm=arm,
                        pooled=not native_only,
                        weights=w,
                        sigma=anchor.r,
                        measure=1.5,
                        d=None if cell == "free" else float(cell[1:]) / 100.0,
                        figures=_figures(bank, w),
                        status=C.OK,
                        starts=starts,
                        iterations=7,
                        seconds=0.01,
                        solver=solver,
                    )  # fmt: skip
                )
        if not native_only:
            for arm, w in (("F", anchor.w_F), ("BS", anchor.w_BS)):
                result.comparators.append(
                    C.Selection(
                        menu=ctx.menu.name,
                        origin=ctx.origin,
                        engine=bank.engine,
                        seed=bank.seed,
                        r_fraction=a,
                        r=anchor.r,
                        cell="free",
                        arm=arm,
                        pooled=False,
                        weights=w,
                        sigma=anchor.r,
                        measure=1.0,
                        d=0.0,
                        figures=_figures(bank, w),
                        status=C.OK,
                        starts=1,
                        iterations=1,
                        seconds=0.0,
                        solver=solver,
                    )  # fmt: skip
                )
    return result


def synthetic_records(
    first_x: str = "2018-01-02", first_a: str = "2018-01-02", seed: int = 11
) -> dict[str, pd.DataFrame]:
    """Seeded records for both test menus and SGOV; the X..Z menu may start later than A..D."""
    sessions = xcals.get_calendar("XNYS", start="2018-01-01", end="2027-12-31").sessions
    days = pd.DatetimeIndex(sessions[sessions <= pd.Timestamp(D_STAR)])
    series = random_indices(days, DRIFT_VOL, seed)
    out = {}
    for symbol, values in series.items():
        first = first_x if symbol in "XYZ" else first_a
        cut = values[values.index >= pd.Timestamp(first)]
        out[symbol] = record(cut / cut.iloc[0])
    return out


def sessions_index() -> pd.DatetimeIndex:
    return pd.DatetimeIndex(
        xcals.get_calendar("XNYS", start="2018-01-01", end="2027-12-31").sessions
    )


def synthetic_inputs(**kwargs) -> data.ResearchInputs:
    return data.build_inputs(
        synthetic_records(**kwargs), sessions_index(), D_STAR, menus=TEST_MENUS,
        manifest_sha256="f" * 64,
    )  # fmt: skip


def load_inputs(snapshot_dir: str) -> data.ResearchInputs:
    """The `--hooks` loader of spawned workers: the same synthetic inputs, whatever the path."""
    return synthetic_inputs()
