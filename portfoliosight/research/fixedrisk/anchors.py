"""Fixed-risk anchors, band projection and the Bayes-Stein comparator (protocol §2, §3, §5).

Engine-independent: everything here uses only `mu_s`, `Sigma`, `sigma`, the bounds and (for
Bayes-Stein) the training sample. For one (menu, origin) a `Geometry` holds `w_min` (minimum
variance), `w_top` (max-`mu_s` greedy fill), the risk span and the three convex surrogate programs;
`column_anchors` solves, at `r = X(a)` and band `|sigma - r| <= tau_r r`:

- `w_F`   = argmax mu_s'w on the band (slider top, d = 0),
- `w_MDP` = argmax M(w) = DR^2 on the band (slider bottom, d = 1),
- `w_BS`  = argmax mu_BS'w on the band (Bayes-Stein comparator, §5),

each by SLSQP from eight starts projected onto the band (convex ceiling surrogate, `w_min`, `w_top`,
equal weight, the first four points of the column's Sobol sequence), keeping the best feasible end.
"""

from __future__ import annotations

import math
import time
import warnings
from dataclasses import dataclass, field

import cvxpy as cp
import numpy as np
from scipy.optimize import minimize
from scipy.stats import qmc

from portfoliosight.engine.caps import greedy_fill
from portfoliosight.engine.optimize import (
    MenuPrograms,
    SolveError,
    cholesky_factor,
    solve_with_retries,
)
from portfoliosight.engine.stats import TRADING_DAYS

from .contracts import (
    ANCHOR_STARTS,
    COLLAPSE_SPAN,
    FEASIBILITY_TOL,
    OK,
    PRIMARY_SEED,
    RISK_FRACTIONS,
    SLSQP_FTOL,
    SLSQP_MAXITER,
    SOBOL_POINTS,
    TAU_R,
    Anchors,
    OriginContext,
)

ANCHOR_FAILED = "anchor_failed"  # no feasible answer for one of the three anchor programs
GENERATOR_SEED = PRIMARY_SEED + 1_000_000  # v1's candidate generator seed (search.GENERATOR_OFFSET)
PROJECTION_HALVINGS = 60
SIMPLEX_STEPS = 80
TINY = 2.0**-53


# --------------------------------------------------------------------------- measures


def dr2(w: np.ndarray, sigma: np.ndarray, cov: np.ndarray) -> float:
    """`M(w) = (sum_i w_i sigma_i)^2 / (w' Sigma w)`."""
    return float((sigma @ w) ** 2 / (w @ cov @ w))


def dr2_grad(w: np.ndarray, sigma: np.ndarray, cov: np.ndarray) -> np.ndarray:
    s = float(sigma @ w)
    cw = cov @ w
    v = float(w @ cw)
    return 2.0 * s * sigma / v - 2.0 * s * s * cw / (v * v)


def slider_position(measure: float, anchors: Anchors) -> float | None:
    """`d(w) = (M(w) - M_F) / (M_MDP - M_F)`; None on a collapsed or failed column."""
    if anchors.collapsed or anchors.status != OK:
        return None
    return (measure - anchors.M_F) / (anchors.M_MDP - anchors.M_F)


def bayes_stein_mu(sample: np.ndarray, mu_hat: np.ndarray) -> np.ndarray:
    """Jorion (1986) Bayes-Stein expected return on the daily sample, annualized (§5).

    `S` = sample covariance scaled by `(T - 1)/(T - N - 2)`; `mu_0` the unconstrained
    minimum-variance portfolio's return;
    `phi = (N + 2) / ((N + 2) + T (mu - mu_0 1)' S^-1 (mu - mu_0 1))`.
    `mu_hat` is the annual sample mean (production `estimate_moments().mu`), used daily as
    `mu_hat / 252`.
    """
    x = np.asarray(sample, dtype=float)
    t, n = x.shape
    if t <= n + 2:
        raise ValueError("Bayes-Stein needs more rows than holdings + 2")
    mu = np.asarray(mu_hat, dtype=float) / TRADING_DAYS
    s = np.cov(x, rowvar=False, ddof=1) * (t - 1) / (t - n - 2)
    ones = np.ones(n)
    s_inv_1 = np.linalg.solve(s, ones)
    mu0 = float(mu @ s_inv_1 / (ones @ s_inv_1))
    excess = mu - mu0
    quad = float(excess @ np.linalg.solve(s, excess))
    phi = (n + 2) / ((n + 2) + t * quad)
    return TRADING_DAYS * ((1.0 - phi) * mu + phi * mu0)


# --------------------------------------------------------------------------- geometry


def project_box_simplex(z: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Euclidean projection on `{lo <= w <= hi, 1'w = 1}`: `clip(z - lam, lo, hi)`, bisection."""
    low, high = float((z - hi).min()), float((z - lo).max())
    for _ in range(SIMPLEX_STEPS):
        mid = 0.5 * (low + high)
        if math.fsum(np.clip(z - mid, lo, hi).tolist()) > 1.0:
            low = mid
        else:
            high = mid
    return np.clip(z - 0.5 * (low + high), lo, hi)


@dataclass(eq=False)
class Geometry:
    """One (menu, origin)'s engine-independent search geometry."""

    lo: np.ndarray
    hi: np.ndarray
    mu_s: np.ndarray
    mu_bs: np.ndarray
    cov: np.ndarray
    sigma: np.ndarray
    w_min: np.ndarray
    w_top: np.ndarray
    sigma_min: float
    sigma_top: float
    programs: MenuPrograms = field(repr=False)
    bs_programs: MenuPrograms = field(repr=False)
    _mdp: tuple = field(repr=False)
    _sobol: dict = field(default_factory=dict, repr=False)

    @property
    def n(self) -> int:
        return len(self.mu_s)

    def risk(self, w: np.ndarray) -> float:
        return float(np.sqrt(max(float(w @ self.cov @ w), 0.0)))

    def measure(self, w: np.ndarray) -> float:
        return dr2(w, self.sigma, self.cov)

    def x(self, a: float) -> float:
        """`X(a) = sigma_min + a (sigma_top - sigma_min)`."""
        return self.sigma_min + a * (self.sigma_top - self.sigma_min)

    def in_domain(self, w: np.ndarray) -> bool:
        return bool(
            (w >= self.lo - FEASIBILITY_TOL).all()
            and (w <= self.hi + FEASIBILITY_TOL).all()
            and abs(math.fsum(w.tolist()) - 1.0) <= FEASIBILITY_TOL
        )

    def in_band(self, w: np.ndarray, r: float, tau: float) -> bool:
        return self.in_domain(w) and abs(self.risk(w) - r) <= tau * r + FEASIBILITY_TOL

    def normalize(self, x: np.ndarray) -> np.ndarray:
        """Clip to the bounds and renormalize to `1'w = 1` (the evaluated mix of an iterate)."""
        c = np.clip(x, self.lo, self.hi)
        return c / c.sum() + 0.0

    def project(self, v: np.ndarray, r: float, tau: float) -> np.ndarray | None:
        """Projection onto the risk band (§2): bisection toward `w_min` or `w_top`; None if not."""
        s = self.risk(v)
        if abs(s - r) <= tau * r:
            return v
        target = self.w_min if s > r else self.w_top
        above = s > r  # the start side is above the line
        low, high = 0.0, 1.0  # low keeps the start's side, high the target's side
        if (self.risk(target) > r) == above:
            return None
        for _ in range(PROJECTION_HALVINGS):
            mid = 0.5 * (low + high)
            w = (1.0 - mid) * v + mid * target
            sw = self.risk(w)
            if abs(sw - r) <= 0.5 * tau * r:
                return w + 0.0
            if (sw > r) == above:
                low = mid
            else:
                high = mid
        return None

    def sobol_mixes(self, block: int = 0) -> np.ndarray:
        """v1's broad candidates (search.broad_candidate's mapping) for `block` of 256 points."""
        if block not in self._sobol:
            engine = qmc.Sobol(
                d=self.n + 1, scramble=True, rng=np.random.default_rng(GENERATOR_SEED + block)
            )
            matrix = engine.random_base2(SOBOL_POINTS.bit_length() - 1)
            out = np.empty((len(matrix), self.n))
            for index, row in enumerate(matrix):
                u, v = row[:-1], float(row[-1])
                if index % 2 == 0:
                    z = -np.log(np.clip(u, TINY, 1.0 - TINY))
                    mix = project_box_simplex(z / z.sum(), self.lo, self.hi)
                else:
                    mix = greedy_fill(u, self.lo, self.hi)
                share = math.sqrt(v)
                out[index] = (1.0 - share) * mix + share * self.w_min
            out.setflags(write=False)
            self._sobol[block] = out
        return self._sobol[block]

    def band_points(self, r: float, tau: float, block: int = 0) -> list[np.ndarray]:
        """The block's Sobol mixes projected onto the band, in Sobol order (failures dropped)."""
        out = []
        for row in self.sobol_mixes(block):
            w = self.project(np.array(row), r, tau)
            if w is not None:
                out.append(w)
        return out

    def frontier_surrogate(self, r: float, bs: bool = False) -> np.ndarray | None:
        try:
            return (self.bs_programs if bs else self.programs).frontier_point(r)
        except SolveError:
            return None

    def mdp_surrogate(self, r: float) -> np.ndarray | None:
        problem, w, x = self._mdp
        x.value = r
        try:
            return solve_with_retries(problem, w, f"MDP surrogate at risk {r!r}")
        except SolveError:
            return None


_GEOMETRY: dict[tuple, Geometry] = {}


def geometry(ctx: OriginContext) -> Geometry:
    """The origin's geometry, cached by inputs digest and bounds (at most 64 kept)."""
    key = (ctx.inputs_sha256, ctx.menu.name, ctx.menu.lower, ctx.menu.upper, ctx.lookback)
    if key in _GEOMETRY:
        return _GEOMETRY[key]
    lo = np.asarray(ctx.menu.lower, dtype=float)
    hi = np.asarray(ctx.menu.upper, dtype=float)
    mu_s = np.asarray(ctx.mu_s, dtype=float)
    cov = np.asarray(ctx.cov, dtype=float)
    sigma = np.asarray(ctx.sigma, dtype=float)
    programs = MenuPrograms(mu_s, cov, lo, hi)
    mu_bs = bayes_stein_mu(ctx.sample, ctx.mu_hat)
    w_min = programs.min_variance() + 0.0
    w_top = greedy_fill(mu_s, lo, hi) + 0.0
    n = len(mu_s)
    var = cp.Variable(n)
    x = cp.Parameter(nonneg=True)
    factor = cp.Parameter((n, n), value=cholesky_factor(cov))
    problem = cp.Problem(
        cp.Maximize(sigma @ var),
        [cp.norm(factor @ var, 2) <= x, cp.sum(var) == 1, var >= lo, var <= hi],  # pyright: ignore[reportArgumentType]
    )
    geo = Geometry(
        lo=lo,
        hi=hi,
        mu_s=mu_s,
        mu_bs=mu_bs,
        cov=cov,
        sigma=sigma,
        w_min=w_min,
        w_top=w_top,
        sigma_min=float(np.sqrt(w_min @ cov @ w_min)),
        sigma_top=float(np.sqrt(w_top @ cov @ w_top)),
        programs=programs,
        bs_programs=MenuPrograms(mu_bs, cov, lo, hi),
        _mdp=(problem, var, x),
    )
    if len(_GEOMETRY) >= 64:
        _GEOMETRY.pop(next(iter(_GEOMETRY)))
    _GEOMETRY[key] = geo
    return geo


# --------------------------------------------------------------------------- band programs


def band_constraints(geo: Geometry, r: float, tau: float) -> list[dict]:
    """Budget equality and the risk band as two smooth inequalities on the variance, scaled."""
    cov = geo.cov
    lo2, hi2 = (1.0 - tau) ** 2, (1.0 + tau) ** 2
    r2 = r * r
    return [
        {"type": "eq", "fun": lambda w: w.sum() - 1.0, "jac": lambda w: np.ones_like(w)},
        {
            "type": "ineq",
            "fun": lambda w: (w @ cov @ w) / r2 - lo2,
            "jac": lambda w: 2.0 * (cov @ w) / r2,
        },
        {
            "type": "ineq",
            "fun": lambda w: hi2 - (w @ cov @ w) / r2,
            "jac": lambda w: -2.0 * (cov @ w) / r2,
        },
    ]


def slsqp(fun, jac, x0, geo: Geometry, constraints: list[dict], maxiter: int = SLSQP_MAXITER):
    """SciPy SLSQP minimizing `fun` under the menu bounds and `constraints`."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return minimize(
            fun,
            x0,
            jac=jac,
            method="SLSQP",
            bounds=list(zip(geo.lo, geo.hi, strict=True)),
            constraints=constraints,
            options={"maxiter": maxiter, "ftol": SLSQP_FTOL},
        )


def _anchor_starts(geo: Geometry, r: float, tau: float, surrogate: np.ndarray | None):
    raw = [
        surrogate,
        geo.w_min,
        geo.w_top,
        project_box_simplex(np.full(geo.n, 1.0 / geo.n), geo.lo, geo.hi),
    ]
    starts = []
    for v in raw:
        if v is None:
            continue
        w = geo.project(np.asarray(v, dtype=float) + 0.0, r, tau)
        if w is not None:
            starts.append(w)
    sobol = iter(geo.band_points(r, tau, 0))
    for w in sobol:
        if len(starts) >= ANCHOR_STARTS:
            break
        starts.append(w)
    return starts


def maximize_on_band(
    geo: Geometry, r: float, tau: float, value, grad, starts: list[np.ndarray]
) -> tuple[np.ndarray | None, int]:
    """Best feasible answer of `max value(w)` on the band from `starts`; total iterations."""
    constraints = band_constraints(geo, r, tau)
    best, best_value, iterations = None, -np.inf, 0
    for x0 in starts:
        candidates = [x0]
        res = slsqp(lambda w: -value(w), lambda w: -grad(w), x0, geo, constraints)
        iterations += int(res.nit)
        end = geo.normalize(res.x)
        if not geo.in_band(end, r, tau):
            end = geo.project(end, r, tau)
        if end is not None:
            candidates.append(end)
        for w in candidates:
            if geo.in_band(w, r, tau):
                v = value(w)
                if v > best_value:
                    best, best_value = w, v
    return best, iterations


def column_anchors(geo: Geometry, r_fraction: float, tau_r: float = TAU_R) -> Anchors:
    """The anchors of one risk column (§2) and the Bayes-Stein comparator (§5)."""
    clock = time.perf_counter()
    r = geo.x(r_fraction)
    sigma, cov = geo.sigma, geo.cov
    programs = (
        (lambda w: float(geo.mu_s @ w), lambda w: geo.mu_s, geo.frontier_surrogate(r)),
        (
            lambda w: dr2(w, sigma, cov),
            lambda w: dr2_grad(w, sigma, cov),
            geo.mdp_surrogate(r),
        ),
        (lambda w: float(geo.mu_bs @ w), lambda w: geo.mu_bs, geo.frontier_surrogate(r, True)),
    )
    answers, starts_used, iterations = [], 0, 0
    for value, grad, surrogate in programs:
        starts = _anchor_starts(geo, r, tau_r, surrogate)
        starts_used += len(starts)
        w, nit = maximize_on_band(geo, r, tau_r, value, grad, starts)
        iterations += nit
        answers.append(w)
    status = OK if all(w is not None for w in answers) else ANCHOR_FAILED
    nan = np.full(geo.n, np.nan)
    w_f, w_mdp, w_bs = (nan if w is None else w for w in answers)
    m_f = geo.measure(w_f) if answers[0] is not None else math.nan
    m_mdp = geo.measure(w_mdp) if answers[1] is not None else math.nan
    collapsed = status == OK and m_mdp - m_f <= COLLAPSE_SPAN
    return Anchors(
        r_fraction=r_fraction,
        r=r,
        sigma_min=geo.sigma_min,
        sigma_top=geo.sigma_top,
        w_F=w_f,
        w_MDP=w_mdp,
        w_BS=w_bs,
        M_F=m_f,
        M_MDP=m_mdp,
        collapsed=bool(collapsed),
        status=status,
        starts=starts_used,
        iterations=iterations,
        seconds=time.perf_counter() - clock,
    )


def origin_anchors(
    ctx: OriginContext,
    risk_fractions: tuple[float, ...] = RISK_FRACTIONS,
    tau_r: float = TAU_R,
) -> list[Anchors]:
    """Anchors of every risk column of one (menu, origin); shared by engines and seeds."""
    geo = geometry(ctx)
    return [column_anchors(geo, a, tau_r) for a in risk_fractions]
