"""Fixed-risk diversification: each risk column's peak and ladder (spec 4.7).

At a risk level `X` the mixes the page can show all have risk exactly `X`. Among them

    peak     maximize ENB(w)   s.t.  sigma(w) = X,                1'w = 1,  min <= w <= max
    level    maximize ENB(w)   s.t.  sigma(w) = X,  mu_s'w >= Y,  1'w = 1,  min <= w <= max

with `Y` on evenly spaced return levels from the frontier's return down to the peak's. ENB is the
exact minimum-torsion measure of `torsion.py`. The torsion is fixed for the build, so ENB is a
smooth function of `w`.

The programs are solved in the coordinates the measure is written in. With exposures
`b = T^-T w`, put `u = sqrt(Lambda) b / X`. Then `w'cov w = X^2 |u|^2`, the bet shares are
`p_i = u_i^2 / |u|^2`, and the programs read

    maximize H(u) = -sum p ln p   s.t.  |u|^2 = 1,  linear constraints on w = M u,
    M = X T' Lambda^-1/2

a separable entropy on the unit sphere, cut by planes. `ENB = exp(H)`, so maximizing `H`
maximizes ENB. Where every bet has the same share, the curvature of `H` along the sphere is
exactly `-4 I`; elsewhere it is `-4 I - 2 diag(ln p + H)`. The objective handed to the solver is
therefore `-H / 4`: a scale that makes the identity its quasi-Newton model starts from about
right, and roughly halves the iterations. It is a choice of scale, not a property the answers
depend on.

The programs are not convex (an equality on risk, an entropy to maximize), so each is solved
with SLSQP from several starting points and the answers are pooled: every mix of a column that
passed the feasibility check is a candidate for every level whose return it reaches. A level
holds the highest-ENB candidate that earns at least its return, which makes two statements true
by construction, whatever the solver did: ENB never falls as the return level falls, and the
bottom of the ladder is the highest ENB found in the column. "Found" is the honest word: a
search from a handful of starting points proves nothing about mixes it never visited.

Three tolerances are in play. A solver answer becomes a candidate at 1e-8 (`FEASIBLE`). The
frontier mix, which heads every pool, comes from the conic program and sits on its risk line
within 1e-6 (`optimize.frontier`). The builder checks every mix it writes at 1e-6, the one
tolerance of spec 4.11.

The mixes of one risk line need not hang together. Close to a menu's highest risk the line can
fall apart into separate pieces around different funds, and ENB can dip between two of its
maxima; the best mix for a slightly lower return may then be a different portfolio altogether.
Two neighbouring levels are marked as a hop when the straight blend between them would leave
the risk line: the page then shows one or the other, never the blend.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from .caps import greedy_fill
from .optimize import Frontier, MenuPrograms, onto_risk
from .parallel import by_column
from .torsion import TorsionBasis, enb

LEVELS = 12  # return levels strictly between the frontier mix and the peak
PASSES = 2  # times a ladder is laid out again after one of its own levels beat the peak
SEED = 20261013  # the random starting points; one stream per column
TOL = 1e-6  # the one tolerance of spec 4.11: what counts as a gain, in return or in ENB
FEASIBLE = 1e-8  # what a solver answer must meet to become a candidate
HOP_TOL = 0.01  # two levels are blended only if the blend keeps 99% of the column's risk
OBJECTIVE_SCALE = 0.25  # the solver minimizes -H / 4 (see the module docstring)
SOLVER_OPTIONS = {"maxiter": 200, "ftol": 1e-9}
RANDOM_STARTS = 3  # random points on the risk line each peak is solved from
RANDOM_VERTICES = 3  # a random start is the average of this many random greedy fills


@dataclass(frozen=True)
class Candidate:
    """A mix on its column's risk line, with what the ladder needs to know about it."""

    w: np.ndarray
    y: float  # mu_s' w
    z: float  # ENB


@dataclass(frozen=True)
class Column:
    """One risk column: `LEVELS + 2` mixes from the frontier mix (first) down to the peak (last)."""

    w: np.ndarray  # levels x n
    y: np.ndarray  # expected return of each mix, never rising
    z: np.ndarray  # ENB of each mix, never falling
    hop: np.ndarray  # per step between two levels: True where the two must not be blended
    collapsed: bool  # no mix found at this risk is more diversified than the frontier mix


def bet_entropy(u) -> tuple[float, np.ndarray]:
    """`H = ln ENB` of bet coordinates `u`, and its gradient.

    With shares `p = u^2 / |u|^2`, `H = -sum(p ln p)` and `dH/du = -(2 / |u|^2) u (ln p + H)`.
    A coordinate of zero has a zero share and a zero gradient. `H` does not change when `u` is
    scaled, so the gradient is at right angles to `u`.
    """
    squares = u * u
    total = squares.sum()
    shares = squares / total
    logs = np.log(np.where(shares > 0.0, shares, 1.0))
    entropy = -float(shares @ logs)
    return entropy, (-2.0 / total) * (u * (logs + entropy))


class EnbProgram:
    """ENB maximization at a fixed risk for one menu: moments, bounds and torsion fixed."""

    def __init__(self, mu_s, cov, lo, hi, basis: TorsionBasis):
        self.mu = np.asarray(mu_s, dtype=float)
        self.cov = np.asarray(cov, dtype=float)
        self.lo = np.asarray(lo, dtype=float)
        self.hi = np.asarray(hi, dtype=float)
        self.basis = basis
        root = np.sqrt(basis.lam)
        self._to_bets = root[:, None] * basis.inv_t  # sqrt(Lambda) T^-T: u = _to_bets w / X
        self._from_bets = basis.t.T / root[None, :]  # T' Lambda^-1/2:   w = X _from_bets u
        self._budget = self._from_bets.sum(axis=0)  # 1'w = X _budget'u
        self._earned = self.mu @ self._from_bets  # mu_s'w = X _earned'u

    def sigma(self, w) -> float:
        return float(np.sqrt(w @ self.cov @ w))

    def candidate(self, w) -> Candidate:
        return Candidate(w=w, y=float(self.mu @ w), z=enb(w, self.cov, self.basis))

    def bets(self, w, risk: float) -> np.ndarray:
        """The bet coordinates `u` of a mix at risk level `risk`; `|u| = sigma(w) / risk`."""
        return self._to_bets @ np.asarray(w, dtype=float) / risk

    def solve(self, risk: float, floor: float | None, start) -> Candidate | None:
        """One SLSQP run from the mix `start`; the answer when it is feasible, else `None`.

        An answer is judged by `feasible` alone, in the weights themselves: a run that stopped
        early on a feasible mix still gives a mix the page may show, and the pool decides how
        good it is.
        """
        to_mix = risk * self._from_bets
        budget = risk * self._budget
        rows = [to_mix, -to_mix]
        offsets = [-self.lo, self.hi]
        if floor is not None:
            rows.append(risk * self._earned[None, :])
            offsets.append(np.array([-floor]))
        normals = np.vstack(rows)
        offset = np.concatenate(offsets)

        def objective(u):
            entropy, gradient = bet_entropy(u)
            return -OBJECTIVE_SCALE * entropy, -OBJECTIVE_SCALE * gradient

        constraints = [
            {
                "type": "eq",
                "fun": lambda u: np.array([u @ u - 1.0, budget @ u - 1.0]),
                "jac": lambda u: np.vstack([2.0 * u, budget]),
            },
            {"type": "ineq", "fun": lambda u: normals @ u + offset, "jac": lambda u: normals},
        ]
        result = minimize(
            objective,
            self.bets(start, risk),
            jac=True,
            method="SLSQP",
            constraints=constraints,
            options=SOLVER_OPTIONS,
        )
        mix = to_mix @ np.asarray(result.x, dtype=float)
        if not self.feasible(mix, risk, floor):
            return None
        return self.candidate(mix)

    def feasible(self, w, risk: float, floor: float | None) -> bool:
        """Whether `w` is on the risk line, inside the bounds, fully invested and above `floor`."""
        if not np.isfinite(w).all():
            return False
        inside = (w >= self.lo - FEASIBLE).all() and (w <= self.hi + FEASIBLE).all()
        on_line = abs(self.sigma(w) - risk) <= FEASIBLE
        earns = floor is None or float(self.mu @ w) >= floor - FEASIBLE
        return bool(inside and on_line and earns and abs(w.sum() - 1.0) <= FEASIBLE)


class Pool:
    """A column's candidates in the order they were found; the frontier mix is the first."""

    def __init__(self, top: Candidate):
        self.members = [top]

    @property
    def top(self) -> Candidate:
        return self.members[0]

    def add(self, candidate: Candidate | None) -> None:
        """Keep a feasible answer, unless it claims more return than the frontier mix.

        Nothing on the risk line earns more than the frontier mix. An answer that seems to, by
        more than the solvers' tolerance, is not one the ladder below the frontier can use; one
        within the tolerance earns the same and is kept, since funds with equal expected returns
        leave room for a more diversified mix at the frontier's own return.
        """
        if candidate is not None and candidate.y <= self.top.y + FEASIBLE:
            self.members.append(candidate)

    def best(self, floor: float | None = None) -> Candidate:
        """The highest-ENB member earning at least `floor`; a tie stays with the earlier one.

        The frontier mix always qualifies: no floor of a ladder is above its return. Because the
        answer is a maximum over the members that qualify, lowering the floor can only raise it.
        """
        chosen = self.top
        for member in self.members[1:]:
            if (floor is None or member.y >= floor - FEASIBLE) and member.z > chosen.z:
                chosen = member
        return chosen


def random_start(rng: np.random.Generator, program: EnbProgram, risk: float, lowest, top):
    """A random mix inside the bounds with risk exactly `risk`.

    The average of a few random vertices of the bounds (greedy fills in random order), moved
    along a straight line until its risk is `risk`: toward the top of the frontier when it is
    too calm, back toward the minimum-variance mix when it is too risky. Both lines stay inside
    the bounds, and each crosses the risk level once.
    """
    vertices = [
        greedy_fill(rng.random(len(program.mu)), program.lo, program.hi)
        for _ in range(RANDOM_VERTICES)
    ]
    mix = np.mean(vertices, axis=0)
    if program.sigma(mix) < risk:
        return onto_risk(mix, top, risk, program.cov)
    return onto_risk(lowest, mix, risk, program.cov)


def open_columns(programs: MenuPrograms, front: Frontier) -> list[int]:
    """The columns that hold more than one mix: those above the menu's minimum risk."""
    sigma_min = programs.sigma(front.w[0])
    return [j for j, risk in enumerate(front.x) if risk - sigma_min > TOL]


def peak_pools(
    program: EnbProgram,
    programs: MenuPrograms,
    front: Frontier,
    seed: int = SEED,
    workers: int = 1,
) -> list[Pool]:
    """One pool per column, holding the most diversified mix found at that column's risk.

    Each column is solved from its frontier mix, from `RANDOM_STARTS` random points on its risk
    line and from the best mix of the column before it; `spread_peaks` then carries each
    column's best to its neighbours. The frontier mix is a member of its pool, so the best of a
    pool never has a lower ENB than the frontier mix.

    The starts that need nothing from another column are solved first, for all columns at once
    on `workers` processes; then, column by column, the start from the column before it. Each
    pool gains its answers in the order the starts are listed above, as if the columns had been
    solved one after another.

    A column whose risk is the menu's minimum has one mix only, the frontier's, and is not
    solved.
    """
    pools = [Pool(program.candidate(mix)) for mix in front.w]
    opened = open_columns(programs, front)
    answers = by_column(_own_starts, (program, front, seed), dict.fromkeys(opened), workers)
    for j in opened:
        for answer in answers[j]:
            pools[j].add(answer)
        if j > 0:
            pools[j].add(program.solve(float(front.x[j]), None, pools[j - 1].best().w))
    spread_peaks(program, programs, front, pools)
    return pools


def _own_starts(shared, j: int, _payload: None) -> list[Candidate | None]:
    """Column `j`'s answers from its frontier mix and its random starts, in that order."""
    program, front, seed = shared
    risk = float(front.x[j])
    rng = np.random.default_rng([seed, j])
    lowest, top = front.w[0], front.w[-1]
    starts = [front.w[j]]
    starts += [random_start(rng, program, risk, lowest, top) for _ in range(RANDOM_STARTS)]
    return [program.solve(risk, None, start) for start in starts]


def spread_peaks(
    program: EnbProgram, programs: MenuPrograms, front: Frontier, pools: list[Pool]
) -> list[int]:
    """Solve each column once from each neighbour's best mix; the columns that gained from it.

    One sweep left to right and one right to left, so a better optimum found anywhere reaches
    every column it is also better for. A column counts as having gained when its best ENB rose
    by more than the tolerance.
    """
    columns = open_columns(programs, front)
    before = {j: pools[j].best().z for j in columns}
    for order, step in ((columns[1:], -1), (columns[-2::-1], 1)):
        for j in order:
            pools[j].add(program.solve(float(front.x[j]), None, pools[j + step].best().w))
    return [j for j in columns if pools[j].best().z > before[j] + TOL]


def column(program: EnbProgram, risk: float, pool: Pool, levels: int = LEVELS) -> Column:
    """The ladder of one column, from its frontier mix down to its peak.

    `pool` holds the column's frontier mix and whatever else was found on its risk line. Return
    levels are evenly spaced between the frontier mix and the pool's best, the peak. Each level
    is solved from the level above it (continuation), from the frontier mix and from the peak,
    and every feasible answer joins the pool. If a level turns out more diversified than the
    peak it becomes the peak, and the levels are laid out and solved once more between the
    frontier and it. The ladder is then read off the pool: a level is the highest-ENB member
    earning at least its return.

    A column is collapsed when nothing in its pool beats the frontier mix's ENB by more than the
    tolerance: every level is then the frontier mix. When the peak does beat it but earns the
    frontier's return (funds with equal expected returns), there are no return levels to lay
    out: the frontier mix is followed by the peak at every level.

    A step between two levels is a hop when the mix halfway between them, where a straight
    blend is farthest from the risk line, has lost more than `HOP_TOL` of the column's risk.
    """
    if levels < 1:
        raise ValueError("a ladder needs at least 1 level between the frontier mix and the peak")
    top = pool.top
    bottom = pool.best()
    for _ in range(PASSES):
        if bottom.y >= top.y - TOL:
            break
        above = top
        for floor in np.linspace(top.y, bottom.y, levels + 2)[1:-1]:
            starts = [above.w, top.w, bottom.w]
            for i, start in enumerate(starts):
                if not any(start is earlier for earlier in starts[:i]):
                    pool.add(program.solve(risk, float(floor), start))
            above = pool.best(float(floor))
        if pool.best() is bottom:
            break
        bottom = pool.best()
    if bottom.z <= top.z + TOL:
        chosen = [top] * (levels + 2)
    elif bottom.y >= top.y - TOL:
        chosen = [top] + [bottom] * (levels + 1)
    else:
        floors = np.linspace(top.y, bottom.y, levels + 2)[1:-1]
        chosen = [top, *(pool.best(float(floor)) for floor in floors), bottom]
    hop = [
        upper is not lower and program.sigma((upper.w + lower.w) / 2.0) < (1.0 - HOP_TOL) * risk
        for upper, lower in zip(chosen[:-1], chosen[1:], strict=True)
    ]
    return Column(
        w=np.array([member.w for member in chosen]),
        y=np.array([member.y for member in chosen]),
        z=np.array([member.z for member in chosen]),
        hop=np.array(hop, dtype=bool),
        collapsed=chosen[-1] is top,
    )


def ladders(
    program: EnbProgram,
    risks: Sequence[float],
    pools: Sequence[Pool],
    columns: Sequence[int],
    levels: int = LEVELS,
    workers: int = 1,
) -> dict[int, Column]:
    """The ladder of each column of `columns`, by index, solved on `workers` processes.

    Each column's pool gains what its ladder found, in the order it was found, exactly as
    `column` leaves it.
    """
    payloads = {j: (float(risks[j]), pools[j]) for j in columns}
    laid_out = {}
    for j, (ladder, found) in by_column(_ladder, (program, levels), payloads, workers).items():
        pools[j].members.extend(found)
        laid_out[j] = ladder
    return laid_out


def _ladder(shared, _j: int, payload: tuple[float, Pool]) -> tuple[Column, list[Candidate]]:
    """One column's ladder, solved on a copy of its pool; the ladder and the copy's new members."""
    program, levels = shared
    risk, pool = payload
    own = Pool(pool.top)
    own.members = list(pool.members)
    return column(program, risk, own, levels), own.members[len(pool.members) :]
