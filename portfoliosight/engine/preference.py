"""The two-stage preference contract (protocol 2, simulation engines spec 5.5).

Which portfolio a pool of evaluated candidates selects. Each candidate carries its weights in
fixed menu order, its unrounded annual Bad / Typical / Good (`B = q(.025)`, `T = q(.50)`,
`G = q(.975)` of the engine's simulated years, in decimal units: 1 bp is 0.0001) and, for Stage B,
a diversification measure `M` (DR² or ENB) supplied by the caller. In order:

1. Filter. A candidate is removed when another pool member dominates it: no quantile lower at
   all and at least one higher by more than `DOMINANCE_TOLERANCE` (1e-10). Because "lower" has
   no tolerance this is a strict partial order, so no order of visiting the pool can form a
   cycle; a tolerance on both sides (no quantile lower BY MORE than 1e-10) is not transitive and
   cycles on three candidates a few 1e-10 apart. 1e-10 is numerical resolution, not materiality.
2. Stage A, return. `w_R` is the filtered pool's maximum `U = 0.60 B + 0.30 T + 0.10 G`: a finite
   trade-off (one bp of Bad is worth two of Typical or six of Good), not a lexicographic rule, and
   with no kink at Bad = 0. The measure plays no part.
3. Admissible set at allowance `a`, relative to `w_R`'s unrounded figures: `B >= B_R - 10 bp`,
   `T >= T_R - 25 bp`, `G >= G_R - 50 bp`, `U >= U_R - a`, and not both `B < B_R - 1e-10` and
   `T < T_R - 1e-10` (the veto). Every guard bounds a reduction only; an improvement in any
   outcome never counts against a candidate. `w_R` always passes, and the set at a smaller
   allowance is contained in the set at a larger one.
4. Stage B, diversification. The selection is the admissible set's maximum measure.

Guard names are `bad`, `typical`, `good`, `u` (the allowance on U) and `veto`. A selection
records two things about them: `guards`, the spec 7 ladder field, the constraints among `bad`,
`typical`, `good` and `u` that the selection sits on (equality within `BINDING_TOLERANCE`, 1e-10;
empty when the selection is `w_R` itself); and `excluding_guards`, the guards, veto included,
that keep a more diversified pool member out.

Ties, for each ranking: take its global maximum, form the tie set of everything within
`TIE_TOLERANCE` (1e-12) of that maximum, then pick from the tie set by exact comparisons. Stage A
prefers higher B, then T, then G, then the lexicographically smaller weight vector; Stage B
prefers higher U, then the same order. Never pairwise approximate ties: those chain, and the
result would depend on the order candidates were visited. Nothing is rounded before comparing.

What this does not promise. The pool is whatever the caller evaluated, so the selection is the
most diversified admissible mix *found*, not a certified optimum. Along increasing allowances the
selected measure does not fall and the selected U does not rise; nothing says Bad improves, and
no safer-direction promise is made: the one promise is the admissible set. Two edge cases of the
tie width, both under 1e-12 of U: at allowance 0 a Stage A tie member whose U exceeds `U_R` is
admissible, so Stage B may pick it and report a sacrifice just below zero; and the selected
measure can sit up to 1e-12 below the admissible maximum.

The coefficients, guards and tolerances are the owner's policy of 2026-10-18 (protocol 2).
Protocol 7 (b) asks what the selection would be under other U coefficients, (.70, .20, .10) and
(.50, .35, .15): `utility`, Stage A, the guards, Stage B and `select` take an optional
`coefficients` (Bad, Typical, Good), by default exactly `COEFFICIENTS`, the owner's, which gives
the same bits as before the argument existed. A `Candidate`'s own `utility` is always the owner's.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

BAD_WEIGHT = 0.60
TYPICAL_WEIGHT = 0.30
GOOD_WEIGHT = 0.10
BAD_GUARD = 0.0010  # 10 bp: the largest Bad reduction versus w_R that stays admissible
TYPICAL_GUARD = 0.0025  # 25 bp
GOOD_GUARD = 0.0050  # 50 bp
DOMINANCE_TOLERANCE = 1e-10  # "higher" in the dominance filter means higher by more than this
VETO_TOLERANCE = 1e-10  # "lower" in the Bad-and-Typical veto means lower by more than this
TIE_TOLERANCE = 1e-12  # the width of a ranking's tie set below its global maximum
BINDING_TOLERANCE = 1e-10  # a guard binds a selection that meets it with equality within this
GUARDS = ("bad", "typical", "good", "u", "veto")  # the order every guard list follows
COEFFICIENTS = (BAD_WEIGHT, TYPICAL_WEIGHT, GOOD_WEIGHT)  # U's (Bad, Typical, Good) weights

Coefficients = tuple[float, float, float]


@dataclass(frozen=True)
class Candidate:
    """One evaluated mix: weights in menu order, unrounded B/T/G, and its measure if scored."""

    weights: tuple[float, ...]
    bad: float
    typical: float
    good: float
    measure: float | None = None  # DR² or ENB; Stage B refuses an admissible candidate without one

    def __post_init__(self) -> None:
        weights = tuple(float(x) for x in self.weights)
        if not weights:
            raise ValueError("a candidate's weights must hold at least one fund")
        if not all(math.isfinite(x) for x in weights):
            raise ValueError("a candidate's weights must be finite")
        object.__setattr__(self, "weights", weights)
        for name in ("bad", "typical", "good"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"a candidate's {name} return must be finite, got {value}")
            object.__setattr__(self, name, value)
        if self.measure is not None:
            measure = float(self.measure)
            if not math.isfinite(measure):
                raise ValueError(f"a candidate's measure must be finite or None, got {measure}")
            object.__setattr__(self, "measure", measure)

    @property
    def utility(self) -> float:
        """The owner's `U` of this candidate's unrounded Bad, Typical and Good."""
        return utility(self.bad, self.typical, self.good)


@dataclass(frozen=True)
class Selection:
    """What `select` decided at one allowance, with the figures a run records beside it.

    The filtered pool's unconstrained most diversified member, which protocol 2 also reports, is
    `select_diversified(pool)` once every member of `pool` is scored.
    """

    pool: tuple[Candidate, ...]  # the filtered pool: the input without dominated members, in order
    reference: Candidate  # w_R, Stage A's maximum-U member of `pool`
    allowance: float  # the U allowance in decimal (2.5 bp = 0.00025)
    admissible: tuple[Candidate, ...]  # the admissible members of `pool`, in pool order
    selected: Candidate  # Stage B's maximum-measure member of `admissible`
    # U_R - U(selected), unrounded: in [0, allowance] up to rounding, except the tie-width edge
    # case of the module docstring (just below zero at allowance 0)
    sacrifice: float
    # spec 7: those of bad, typical, good, u whose constraint the selection meets with equality
    # within BINDING_TOLERANCE; empty when the selection is w_R itself (the ladder's level 0)
    guards: frozenset[str]
    # the guards that exclude at least one scored member of `pool` with a strictly higher measure
    # than the selection, in GUARDS order; empty when no excluded member is more diversified
    excluding_guards: tuple[str, ...]
    coefficients: Coefficients = COEFFICIENTS  # the U coefficients every stage used


def utility(
    bad: float, typical: float, good: float, coefficients: Sequence[float] = COEFFICIENTS
) -> float:
    """The return utility `U = k_B B + k_T T + k_G G`, in the inputs' decimal units.

    `coefficients` is `(k_B, k_T, k_G)`, by default the owner's `(0.60, 0.30, 0.10)`.
    """
    k_bad, k_typical, k_good = checked_coefficients(coefficients)
    return k_bad * bad + k_typical * typical + k_good * good


def dominates(a: Candidate, b: Candidate) -> bool:
    """`a` dominates `b`: no quantile of `a` lower at all, one higher by more than 1e-10."""
    pairs = ((a.bad, b.bad), (a.typical, b.typical), (a.good, b.good))
    no_lower = all(x >= y for x, y in pairs)
    return no_lower and any(x - y > DOMINANCE_TOLERANCE for x, y in pairs)


def nondominated(pool: Sequence[Candidate]) -> tuple[Candidate, ...]:
    """The members of `pool` that no other member dominates, in their input order.

    Duplicates on all three quantiles do not dominate each other and are all kept.
    """
    pool = _checked(pool)
    figures = np.array([(c.bad, c.typical, c.good) for c in pool])
    kept = []
    for candidate, row in zip(pool, figures, strict=True):
        no_lower = (figures >= row).all(axis=1)
        higher = (figures - row > DOMINANCE_TOLERANCE).any(axis=1)
        if not (no_lower & higher).any():
            kept.append(candidate)
    return tuple(kept)


def select_reference(
    pool: Sequence[Candidate], coefficients: Sequence[float] = COEFFICIENTS
) -> Candidate:
    """Stage A: `w_R`, the maximum-U member of `pool`, by the tie-set rule; no measure is read.

    The tie set is every member within `TIE_TOLERANCE` of the global maximum U; it resolves by
    higher Bad, then Typical, then Good, then the lexicographically smaller weight vector.
    Run on the filtered pool (`nondominated`); a dominated member's U is at least 1e-11 below
    its dominator's, so it can never be `w_R` either way.
    """
    pool = _checked(pool)
    k = checked_coefficients(coefficients)
    scores = [_u(c, k) for c in pool]
    best = max(scores)
    ties = [c for c, score in zip(pool, scores, strict=True) if score >= best - TIE_TOLERANCE]
    return min(ties, key=lambda c: (-c.bad, -c.typical, -c.good, c.weights))


def failed_guards(
    candidate: Candidate,
    reference: Candidate,
    allowance: float,
    coefficients: Sequence[float] = COEFFICIENTS,
) -> tuple[str, ...]:
    """The guards `candidate` fails relative to `reference` (`w_R`) at `allowance`, GUARDS order.

    Each compares unrounded figures, and each bounds a reduction only: a candidate above the
    reference on a quantile can never fail that quantile's guard.
    """
    k = checked_coefficients(coefficients)
    floor = _u(reference, k) - _checked_allowance(allowance)
    failed = []
    if not candidate.bad >= reference.bad - BAD_GUARD:
        failed.append("bad")
    if not candidate.typical >= reference.typical - TYPICAL_GUARD:
        failed.append("typical")
    if not candidate.good >= reference.good - GOOD_GUARD:
        failed.append("good")
    if not _u(candidate, k) >= floor:
        failed.append("u")
    bad_lower = candidate.bad < reference.bad - VETO_TOLERANCE
    if bad_lower and candidate.typical < reference.typical - VETO_TOLERANCE:
        failed.append("veto")
    return tuple(failed)


def admissible(
    candidate: Candidate,
    reference: Candidate,
    allowance: float,
    coefficients: Sequence[float] = COEFFICIENTS,
) -> bool:
    """Whether `candidate` passes every guard relative to `reference` (`w_R`) at `allowance`."""
    return not failed_guards(candidate, reference, allowance, coefficients)


def admissible_set(
    pool: Sequence[Candidate],
    reference: Candidate,
    allowance: float,
    coefficients: Sequence[float] = COEFFICIENTS,
) -> tuple[Candidate, ...]:
    """The members of `pool` admissible relative to `reference` at `allowance`, in pool order."""
    pool = _checked(pool)
    _checked_allowance(allowance)
    return tuple(c for c in pool if admissible(c, reference, allowance, coefficients))


def select_diversified(
    candidates: Sequence[Candidate], coefficients: Sequence[float] = COEFFICIENTS
) -> Candidate:
    """Stage B: the maximum-measure member of an admissible set, by the tie-set rule.

    The tie set is every member within `TIE_TOLERANCE` of the global maximum measure; it resolves
    by higher U, then Bad, Typical, Good, then the lexicographically smaller weight vector.
    Raises `ValueError` when a member carries no measure: the caller scores what it offers.
    """
    return _stage_b(_checked(candidates), checked_coefficients(coefficients))[0]


def select(
    pool: Sequence[Candidate], allowance: float, coefficients: Sequence[float] = COEFFICIENTS
) -> Selection:
    """The whole contract on one pool at one U allowance (decimal): filter, Stage A, guards, B.

    `coefficients` are U's (Bad, Typical, Good) weights, the owner's by default; every stage
    that reads U (Stage A, the U allowance, Stage B's tie order, the sacrifice) uses them.
    """
    allowance = _checked_allowance(allowance)
    k = checked_coefficients(coefficients)
    filtered = nondominated(pool)
    reference = select_reference(filtered, k)
    allowed = admissible_set(filtered, reference, allowance, k)
    selected, measure = _stage_b(allowed, k)
    excluded = set()
    for candidate in filtered:
        if candidate.measure is not None and candidate.measure > measure:
            excluded.update(failed_guards(candidate, reference, allowance, k))
    return Selection(
        pool=filtered,
        reference=reference,
        allowance=allowance,
        admissible=allowed,
        selected=selected,
        sacrifice=_u(reference, k) - _u(selected, k),
        guards=_guards_met(selected, reference, allowance, k),
        excluding_guards=tuple(guard for guard in GUARDS if guard in excluded),
        coefficients=k,
    )


def _u(candidate: Candidate, k: Coefficients) -> float:
    return utility(candidate.bad, candidate.typical, candidate.good, k)


def _stage_b(candidates: tuple[Candidate, ...], k: Coefficients) -> tuple[Candidate, float]:
    """Stage B on a checked set: the selection and its measure."""
    scored = []
    for i, candidate in enumerate(candidates):
        if candidate.measure is None:
            raise ValueError(
                f"admissible candidate {i} (weights {candidate.weights}) carries no measure"
            )
        scored.append((candidate, candidate.measure))
    best = max(measure for _, measure in scored)
    ties = [pair for pair in scored if pair[1] >= best - TIE_TOLERANCE]
    return min(
        ties, key=lambda p: (-_u(p[0], k), -p[0].bad, -p[0].typical, -p[0].good, p[0].weights)
    )


def _guards_met(
    selected: Candidate, reference: Candidate, allowance: float, k: Coefficients
) -> frozenset[str]:
    """Spec 7's `guards`: the constraints `selected` meets with equality within 1e-10."""
    if selected == reference:
        return frozenset()
    gaps = {
        "bad": selected.bad - (reference.bad - BAD_GUARD),
        "typical": selected.typical - (reference.typical - TYPICAL_GUARD),
        "good": selected.good - (reference.good - GOOD_GUARD),
        "u": _u(selected, k) - (_u(reference, k) - allowance),
    }
    return frozenset(name for name, gap in gaps.items() if abs(gap) <= BINDING_TOLERANCE)


def _checked(pool: Sequence[Candidate]) -> tuple[Candidate, ...]:
    pool = tuple(pool)
    if not pool:
        raise ValueError("the pool is empty: there is nothing to select")
    funds = {len(c.weights) for c in pool}
    if len(funds) != 1:
        raise ValueError(f"every candidate's weights must cover one menu; got lengths {funds}")
    return pool


def checked_coefficients(coefficients: Sequence[float]) -> Coefficients:
    """Three finite, positive U coefficients (Bad, Typical, Good) as floats."""
    values = tuple(float(x) for x in coefficients)
    if len(values) != 3 or not all(math.isfinite(x) and x > 0.0 for x in values):
        raise ValueError(
            f"U coefficients must be three finite positive numbers (Bad, Typical, Good), "
            f"got {tuple(coefficients)}"
        )
    k_bad, k_typical, k_good = values
    return (k_bad, k_typical, k_good)


def _checked_allowance(allowance: float) -> float:
    allowance = float(allowance)
    if not (math.isfinite(allowance) and allowance >= 0.0):
        raise ValueError(f"the U allowance must be finite and non-negative, got {allowance}")
    return allowance
