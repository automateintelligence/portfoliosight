"""The two-stage preference contract (protocol 2, spec 5.5): the A-SE-29 oracles.

Hand-built candidate tables first, then a small enumerable three-fund menu on one shared replay
draw. Every expectation comes from the construction of a table or from `_oracle`, an exhaustive
reading of protocol 2 written here in plain loops; no expectation is computed by the selector.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Sequence

import numpy as np
import pytest

from portfoliosight.engine import ranges, stats
from portfoliosight.engine.measures import dr2_from
from portfoliosight.engine.preference import (
    BAD_GUARD,
    BAD_WEIGHT,
    BINDING_TOLERANCE,
    COEFFICIENTS,
    DOMINANCE_TOLERANCE,
    GOOD_GUARD,
    GOOD_WEIGHT,
    GUARDS,
    TIE_TOLERANCE,
    TYPICAL_GUARD,
    TYPICAL_WEIGHT,
    VETO_TOLERANCE,
    Candidate,
    Selection,
    admissible,
    admissible_set,
    dominates,
    failed_guards,
    nondominated,
    select,
    select_diversified,
    select_reference,
    utility,
)

CAPS = (0.0, 0.00025, 0.0005, 0.001)  # U allowances in decimal: 0, 2.5, 5 and 10 bp
BP = 1e-4

Row = tuple[float, float, float, float | None, tuple[float, ...]]  # bad, typical, good, M, w


# ---- independent oracles: protocol 2 written out, never the module ---------------------------


OWNER_K = (0.60, 0.30, 0.10)  # the owner's U coefficients (Bad, Typical, Good)
SENSITIVITY_K = ((0.70, 0.20, 0.10), (0.50, 0.35, 0.15))  # protocol 7 (b)


def _u(bad: float, typical: float, good: float, k: Sequence[float] = OWNER_K) -> float:
    """The return utility with coefficients ``k``, written out here (the owner's by default)."""
    return k[0] * bad + k[1] * typical + k[2] * good


def _cu(candidate: Candidate) -> float:
    return _u(candidate.bad, candidate.typical, candidate.good)


def _oracle_dominates(x: Sequence[float], y: Sequence[float]) -> bool:
    """x dominates y: no quantile lower at all, at least one higher by more than 1e-10."""
    no_lower = all(a >= b for a, b in zip(x, y, strict=True))
    return no_lower and any(a - b > 1e-10 for a, b in zip(x, y, strict=True))


def _oracle_fails(row: Row, ref: Row, allowance: float, k: Sequence[float] = OWNER_K) -> list[str]:
    fails = []
    if not row[0] >= ref[0] - 0.0010:
        fails.append("bad")
    if not row[1] >= ref[1] - 0.0025:
        fails.append("typical")
    if not row[2] >= ref[2] - 0.0050:
        fails.append("good")
    if not _u(*row[:3], k) >= _u(*ref[:3], k) - allowance:
        fails.append("u")
    if row[0] < ref[0] - 1e-10 and row[1] < ref[1] - 1e-10:
        fails.append("veto")
    return fails


def _oracle(
    rows: Sequence[Row], allowance: float, k: Sequence[float] = OWNER_K
) -> tuple[list[Row], Row, list[Row], Row]:
    """Protocol 2 by exhaustion under U coefficients ``k``: (filtered, w_R, admissible, pick)."""
    kept = []
    for row in rows:
        dominated = False
        for other in rows:
            if _oracle_dominates(other[:3], row[:3]):
                dominated = True
        if not dominated:
            kept.append(row)
    best_u = max(_u(row[0], row[1], row[2], k) for row in kept)
    ties = [row for row in kept if _u(row[0], row[1], row[2], k) >= best_u - 1e-12]
    ref = min(ties, key=lambda r: (-r[0], -r[1], -r[2], r[4]))
    adm = [row for row in kept if not _oracle_fails(row, ref, allowance, k)]
    best_m = max(_measure(row) for row in adm)
    ties_b = [row for row in adm if _measure(row) >= best_m - 1e-12]
    pick = min(ties_b, key=lambda r: (-_u(r[0], r[1], r[2], k), -r[0], -r[1], -r[2], r[4]))
    return kept, ref, adm, pick


def _oracle_guards(
    pick: Row, ref: Row, allowance: float, k: Sequence[float] = OWNER_K
) -> frozenset[str]:
    """Spec 7: the guards whose constraint holds with equality within 1e-10; none at w_R itself."""
    if pick == ref:
        return frozenset()
    gaps = {
        "bad": pick[0] - (ref[0] - 0.0010),
        "typical": pick[1] - (ref[1] - 0.0025),
        "good": pick[2] - (ref[2] - 0.0050),
        "u": _u(*pick[:3], k) - (_u(*ref[:3], k) - allowance),
    }
    return frozenset(name for name, gap in gaps.items() if abs(gap) <= 1e-10)


def _measure(row: Row) -> float:
    assert row[3] is not None
    return row[3]


def _scored(candidate: Candidate) -> float:
    assert candidate.measure is not None
    return candidate.measure


def _row(candidate: Candidate) -> Row:
    c = candidate
    return (c.bad, c.typical, c.good, c.measure, c.weights)


def _w(i: int) -> tuple[float, float]:
    """Distinct two-fund weights for hand-built candidates."""
    return (i / 100, 1 - i / 100)


def _c(bad, typical, good, measure=None, weights=(0.5, 0.5)) -> Candidate:
    return Candidate(weights=weights, bad=bad, typical=typical, good=good, measure=measure)


def _at_u(bad, typical, target, weights, measure=None) -> Candidate:
    """A candidate whose Good puts its U at `target` (to rounding, about 1e-17)."""
    good = (target - 0.60 * bad - 0.30 * typical) / 0.10
    return _c(bad, typical, good, measure, weights)


def _exact_input(f: Callable[[float], float], target: float, start: float) -> float:
    """An input near `start` at which the increasing `f` returns exactly `target`."""
    x = start
    for _ in range(200):
        y = f(x)
        if y == target:
            return x
        x = math.nextafter(x, math.inf if y < target else -math.inf)
    raise AssertionError("fixture: no input reproduces the target exactly")


def _exact_u_tie(*candidates: Candidate) -> None:
    """Fixture precondition: the candidates' U are exactly equal, here and in the module."""
    assert len({_cu(c) for c in candidates}) == 1, "fixture: the test's U must tie exactly"
    assert len({c.utility for c in candidates}) == 1, "fixture: the module's U must tie exactly"


# ---- U: the owner's finite trade-off ---------------------------------------------------------

OWNER_A = (-0.0500, 0.04, 0.12)
OWNER_B = (-0.0501, 0.08, 0.18)


def test_coefficients_guards_and_tolerances_are_the_owner_policy():
    assert (BAD_WEIGHT, TYPICAL_WEIGHT, GOOD_WEIGHT) == (0.60, 0.30, 0.10)
    assert (BAD_GUARD, TYPICAL_GUARD, GOOD_GUARD) == (0.0010, 0.0025, 0.0050)
    assert DOMINANCE_TOLERANCE == 1e-10 and VETO_TOLERANCE == 1e-10 and TIE_TOLERANCE == 1e-12
    assert BINDING_TOLERANCE == 1e-10
    assert GUARDS == ("bad", "typical", "good", "u", "veto")
    assert utility(1.0, 0.0, 0.0) == 0.60
    assert utility(0.0, 1.0, 0.0) == 0.30
    assert utility(0.0, 0.0, 1.0) == 0.10
    assert utility(-0.05, 0.06, 0.20) == pytest.approx(_u(-0.05, 0.06, 0.20), abs=1e-17)
    assert _c(-0.05, 0.06, 0.20).utility == utility(-0.05, 0.06, 0.20)


def test_owner_b_beats_owner_a_by_u_where_a_lexicographic_rule_picks_a():
    assert _u(*OWNER_B) - _u(*OWNER_A) == pytest.approx(0.01794, abs=1e-15)
    assert utility(*OWNER_B) - utility(*OWNER_A) == pytest.approx(0.01794, abs=1e-15)
    a, b = _c(*OWNER_A, 2.0, _w(1)), _c(*OWNER_B, 1.0, _w(2))  # A is the more diversified
    lexicographic = max([a, b], key=lambda c: (c.bad, c.typical, c.good))
    assert lexicographic == a  # a strict Bad-first rule would hand the owner A
    for pool in ([a, b], [b, a]):
        assert select_reference(pool) == b
        for cap in CAPS:
            assert select(pool, cap).reference == b
            assert select(pool, cap).selected == b  # A's U is 179.4 bp lower: never admissible


def test_one_bp_of_bad_trades_for_two_of_typical_or_six_of_good():
    b, t, g = -0.02, 0.05, 0.15
    base = utility(b, t, g)
    assert utility(b - BP, t + 2 * BP + 1e-9, g) > base > utility(b - BP, t + 2 * BP - 1e-9, g)
    assert utility(b - BP, t, g + 6 * BP + 1e-9) > base > utility(b - BP, t, g + 6 * BP - 1e-9)


def test_there_is_no_kink_at_zero_bad():
    up_from_zero = utility(BP, 0.05, 0.15) - utility(0.0, 0.05, 0.15)
    up_to_zero = utility(0.0, 0.05, 0.15) - utility(-BP, 0.05, 0.15)
    assert up_from_zero == pytest.approx(0.60 * BP, abs=1e-15)
    assert up_to_zero == pytest.approx(0.60 * BP, abs=1e-15)


# ---- dominance: strict, acyclic, applied before either stage ---------------------------------


def test_dominance_needs_no_quantile_lower_at_all_and_one_higher_by_more_than_1e_10():
    base = _c(0.01, 0.05, 0.10, weights=_w(1))
    assert not dominates(base, base)
    assert dominates(_c(0.01, 0.05, 0.10 + 2e-10, weights=_w(2)), base)
    assert not dominates(_c(0.01, 0.05, 0.10 + 0.5e-10, weights=_w(2)), base)
    assert not dominates(base, _c(0.01, 0.05, 0.10 + 2e-10, weights=_w(2)))
    lower_by_a_hair = _c(0.01 + 0.01, 0.05 - 1e-15, 0.10 + 0.01, weights=_w(3))
    assert not dominates(lower_by_a_hair, base)  # any lower quantile at all blocks it
    assert not dominates(base, lower_by_a_hair)
    twin = _c(0.01, 0.05, 0.10, weights=_w(4))
    assert not dominates(base, twin) and not dominates(twin, base)
    assert set(nondominated([base, twin])) == {base, twin}


E = 1e-10
CYCLE = {
    "A": _c(0.0, 0.0, 0.0, 1.0, _w(1)),
    "B": _c(1.5 * E, -0.75 * E, -0.75 * E, 2.0, _w(2)),
    "C": _c(0.75 * E, 0.75 * E, -1.5 * E, 3.0, _w(3)),
}


def _tolerant(x: Candidate, y: Candidate) -> bool:
    """Dominance with a tolerance on both sides (no quantile lower BY MORE than e): rejected."""
    xs, ys = _row(x)[:3], _row(y)[:3]
    no_lower = all(a >= b - E for a, b in zip(xs, ys, strict=True))
    return no_lower and any(a - b > E for a, b in zip(xs, ys, strict=True))


def test_the_epsilon_cycle_fixture_is_acyclic_in_all_six_orders():
    a, b, c = CYCLE["A"], CYCLE["B"], CYCLE["C"]
    assert _tolerant(b, a) and _tolerant(a, c) and _tolerant(c, b)  # a cycle under tolerance
    outcomes = set()
    for order in itertools.permutations([a, b, c]):
        relation = {(x, y) for x in order for y in order if dominates(x, y)}
        assert relation == set()
        assert set(nondominated(order)) == {a, b, c}
        assert select_reference(order) == b  # U: A 0, B 6e-11, C 5.25e-11
        results = [select(order, cap) for cap in CAPS]
        outcomes.add(tuple((result.reference, result.selected) for result in results))
    assert outcomes == {((b, b), (b, c), (b, c), (b, c))}


def test_a_dominated_candidate_with_the_highest_measure_is_never_selected():
    ref = (-0.05, 0.06, 0.20)
    r = _c(*ref, 1.0, _w(1))
    keeper = _c(ref[0] - 3 * BP, ref[1], ref[2] + 3 * BP, 2.0, _w(2))
    dominated = _c(ref[0] - 4 * BP, ref[1], ref[2] + 3 * BP, 9.0, _w(3))
    assert _oracle_dominates(_row(keeper)[:3], _row(dominated)[:3])
    assert _cu(r) - _cu(dominated) < 0.00025  # its U is within the primary allowance
    assert not _oracle_fails(_row(dominated), _row(r), 0.00025)  # the guards alone would admit it
    pool = [dominated, r, keeper]
    for cap in CAPS:
        result = select(pool, cap)
        assert dominated not in result.pool
        assert result.pool == (r, keeper)
        assert result.selected != dominated
    assert select(pool, 0.00025).selected == keeper  # the dominating member stays eligible
    assert nondominated(pool) == (r, keeper)


# ---- Stage A: max U, tie set against the global maximum --------------------------------------

U0 = 0.02


def _stage_a_by_bad() -> tuple[list[Candidate], Candidate]:
    top = _at_u(-0.0500, 0.0600, U0, _w(1))
    best_bad = _at_u(-0.0490, 0.0560, U0 - 0.6e-12, _w(2))
    middle = _at_u(-0.0495, 0.0580, U0 - 0.3e-12, _w(3))
    chained = _at_u(-0.0480, 0.0520, U0 - 1.4e-12, _w(4))  # within 1e-12 of best_bad, not of U0
    return [top, best_bad, middle, chained], best_bad


def _stage_a_by_typical() -> tuple[list[Candidate], Candidate]:
    first = _at_u(-0.05, 0.0600, U0, _w(1))
    best = _at_u(-0.05, 0.0620, U0 - 0.8e-12, _w(2))
    third = _at_u(-0.05, 0.0610, U0 - 0.4e-12, _w(3))
    return [first, best, third], best


def _stage_a_by_good() -> tuple[list[Candidate], Candidate]:
    g = (U0 - 0.60 * -0.05 - 0.30 * 0.06) / 0.10
    first = _c(-0.05, 0.06, g, weights=_w(1))
    best = _c(-0.05, 0.06, g + 4e-12, weights=_w(2))
    third = _c(-0.05, 0.06, g + 2e-12, weights=_w(3))
    return [first, best, third], best


def _stage_a_by_weights() -> tuple[list[Candidate], Candidate]:
    figures = (-0.05, 0.06, 0.32)
    first = _c(*figures, weights=(0.3, 0.2, 0.5))
    second = _c(*figures, weights=(0.2, 0.5, 0.3))
    best = _c(*figures, weights=(0.2, 0.3, 0.5))
    return [first, second, best], best


@pytest.mark.parametrize(
    "fixture",
    [_stage_a_by_bad, _stage_a_by_typical, _stage_a_by_good, _stage_a_by_weights],
    ids=["bad", "typical", "good", "weights"],
)
def test_stage_a_tie_set_resolves_by_bad_then_typical_then_good_then_weights(fixture):
    pool, expected = fixture()
    best_u = max(_cu(c) for c in pool)
    ties = [c for c in pool if _cu(c) >= best_u - 1e-12]
    assert len(ties) == 3  # a three-candidate tie set
    for order in itertools.permutations(pool):
        assert select_reference(order) == expected
        scored = [_c(c.bad, c.typical, c.good, 1.0, c.weights) for c in order]
        assert select(scored, 0.0).reference.weights == expected.weights


def test_stage_a_tie_set_is_formed_against_the_global_maximum_not_pairwise():
    pool, expected = _stage_a_by_bad()
    top, best_bad, _, chained = pool
    assert _cu(top) - _cu(best_bad) == pytest.approx(0.6e-12, abs=1e-15)
    assert _cu(best_bad) - _cu(chained) == pytest.approx(0.8e-12, abs=1e-15)
    # pairwise approximate ties chain from the top down to `chained`, whose Bad is the highest
    chain = [top]
    for c in sorted(pool, key=_cu, reverse=True):
        if c not in chain and any(abs(_cu(c) - _cu(k)) <= 1e-12 for k in chain):
            chain.append(c)
    assert max(chain, key=lambda c: c.bad) == chained
    assert select_reference(pool) == expected != chained


def test_stage_a_reads_no_measure():
    pool, expected = _stage_a_by_bad()
    unscored = [_c(c.bad, c.typical, c.good, None, c.weights) for c in pool]
    assert select_reference(unscored).weights == expected.weights
    for measures in ([1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0], [0.0, -5.0, 1e9, 7.0]):
        scored = [
            _c(c.bad, c.typical, c.good, m, c.weights) for c, m in zip(pool, measures, strict=True)
        ]
        assert select_reference(scored).weights == expected.weights


# ---- the admissible set: guards bound reductions only ----------------------------------------

# Reference figures that put every quantile guard's boundary on an exactly representable value
# (0 - 0.001, 0.004 - 0.0025, 0.008 - 0.005 are exact), so "at the guard" does not depend on
# how the comparison is arranged; the owner's B serves as a second, everyday reference.
EXACT_REF = (0.0, 0.004, 0.008)


def _guard_case(guard: str, ref: tuple[float, float, float], position: str) -> Candidate:
    """A candidate at / just inside / just outside one quantile guard, other quantiles above."""
    shift = {"at": 0.0, "inside": 1e-9, "outside": -1e-9}[position]
    b, t, g = ref
    if guard == "bad":  # -10 bp Bad, +20 bp Typical, +10 bp Good: U +1 bp
        return _c(b - 0.0010 + shift, t + 0.0020, g + 0.0010, weights=_w(2))
    if guard == "typical":  # +20 bp Bad, -25 bp Typical, +10 bp Good: U +5.5 bp
        return _c(b + 0.0020, t - 0.0025 + shift, g + 0.0010, weights=_w(2))
    return _c(b + 0.0010, t + 0.0010, g - 0.0050 + shift, weights=_w(2))  # U +4 bp


@pytest.mark.parametrize("cap", CAPS)
@pytest.mark.parametrize("position", ["at", "inside", "outside"])
@pytest.mark.parametrize("guard", ["bad", "typical", "good"])
def test_each_quantile_guard_admits_at_and_inside_and_rejects_outside(guard, position, cap):
    refs = [EXACT_REF, OWNER_B] if position != "at" else [EXACT_REF]
    for ref in refs:
        reference = _c(*ref, weights=_w(1))
        candidate = _guard_case(guard, ref, position)
        assert _cu(candidate) > _cu(reference)  # the U allowance is not what decides
        expected = (guard,) if position == "outside" else ()
        assert failed_guards(candidate, reference, cap) == expected
        assert admissible(candidate, reference, cap) is (position != "outside")


@pytest.mark.parametrize("cap", [0.0, 0.00025, 0.0005])
def test_the_u_allowance_admits_at_and_inside_and_rejects_outside(cap):
    reference = _c(0.0, 0.0, 0.0, weights=_w(1))  # U_R = 0 exactly
    at = _c(_exact_input(lambda b: _u(b, 0.0, 0.0), -cap, -cap / 0.60), 0.0, 0.0, weights=_w(2))
    assert _cu(at) == -cap and at.utility == -cap  # fixture precondition: exactly at the cap
    inside = _c((-cap + 1e-9) / 0.60, 0.0, 0.0, weights=_w(3))
    outside = _c((-cap - 1e-9) / 0.60, 0.0, 0.0, weights=_w(4))
    for candidate in (at, inside, outside):
        assert candidate.bad >= -0.0010  # a Bad-only reduction, inside the Bad guard
    assert failed_guards(at, reference, cap) == ()
    assert failed_guards(inside, reference, cap) == ()
    assert failed_guards(outside, reference, cap) == ("u",)


def test_the_ten_bp_allowance_admits_inside_and_rejects_outside():
    reference = _c(0.0, 0.0, 0.0, weights=_w(1))
    # Bad -9 bp (U -5.4 bp) and Good -46 bp (U -4.6 bp): U -10 bp, within both guards
    inside = _c(-0.0009, 0.0, -0.0046 + 1e-8, weights=_w(2))
    outside = _c(-0.0009, 0.0, -0.0046 - 1e-8, weights=_w(3))
    assert _cu(inside) == pytest.approx(-0.001 + 1e-9, abs=1e-15)
    assert _cu(outside) == pytest.approx(-0.001 - 1e-9, abs=1e-15)
    assert failed_guards(inside, reference, 0.001) == ()
    assert failed_guards(outside, reference, 0.001) == ("u",)


@pytest.mark.parametrize("cap", CAPS)
def test_an_improvement_never_fails_a_guard(cap):
    reference = _c(-0.05, 0.06, 0.20, weights=_w(1))
    better = [
        _c(-0.05 + 1 * BP, 0.06 + 1 * BP, 0.20 + 1 * BP, weights=_w(2)),  # above on every quantile
        _c(-0.05 + 0.10, 0.06 + 0.20, 0.20 + 0.50, weights=_w(3)),  # far above on every quantile
        _c(-0.05 + 0.05, 0.06, 0.20, weights=_w(4)),  # 500 bp more Bad, the rest equal
        _c(-0.05, 0.06 + 0.05, 0.20, weights=_w(5)),
        _c(-0.05, 0.06, 0.20 + 0.05, weights=_w(6)),
        _c(-0.05 + 0.05, 0.06 - 0.0020, 0.20, weights=_w(7)),  # a large gain beside a small cut
    ]
    for candidate in better:
        assert failed_guards(candidate, reference, cap) == ()
        assert admissible(candidate, reference, cap)


@pytest.mark.parametrize("cap", CAPS)
def test_the_veto_rejects_bad_and_typical_both_lower_at_every_cap(cap):
    reference = _c(-0.05, 0.06, 0.20, weights=_w(1))
    double = _c(-0.05 - 2e-10, 0.06 - 2e-10, 0.20 + 0.0100, weights=_w(2))  # Good +100 bp
    assert _cu(double) > _cu(reference)  # its U is above w_R's: only the veto stops it
    assert failed_guards(double, reference, cap) == ("veto",)
    assert not admissible(double, reference, cap)
    for alone in (
        _c(-0.05 - 2e-10, 0.06, 0.20 + 0.0100, weights=_w(3)),  # Bad lower alone
        _c(-0.05, 0.06 - 2e-10, 0.20 + 0.0100, weights=_w(4)),  # Typical lower alone
        _c(-0.05 - 0.5e-10, 0.06 - 0.5e-10, 0.20 + 0.0100, weights=_w(5)),  # both within 1e-10
    ):
        assert admissible(alone, reference, cap)


def test_the_veto_holds_through_the_selector_despite_the_highest_measure():
    r = _c(-0.05, 0.06, 0.20, 1.0, _w(1))
    double = _c(-0.05 - 2e-10, 0.06 - 2e-10, 0.20 + 1e-9, 9.0, _w(2))  # U 8e-11 below w_R
    assert 1e-12 < _cu(r) - _cu(double) < 1e-10
    for cap in CAPS:
        result = select([double, r], cap)
        assert result.reference == r and result.selected == r
        assert "veto" in result.excluding_guards
        assert double not in result.admissible


def test_bad_only_and_typical_only_reductions_within_their_guards_are_admissible():
    r = _c(-0.05, 0.06, 0.20, 1.0, _w(1))
    bad_only = _c(-0.05 - 9 * BP, 0.06, 0.20 + 30 * BP, 2.0, _w(2))  # U -2.4 bp
    typical_only = _c(-0.05, 0.06 - 8 * BP, 0.20 + 2 * BP, 3.0, _w(3))  # U -2.2 bp
    for candidate in (bad_only, typical_only):
        assert -0.00025 < _cu(candidate) - _cu(r) < 0
        assert not admissible(candidate, r, 0.0)
        for cap in CAPS[1:]:
            assert admissible(candidate, r, cap)
    assert select([r, bad_only, typical_only], 0.00025).selected == typical_only
    assert select([r, bad_only], 0.00025).selected == bad_only


@pytest.mark.parametrize("cap", CAPS)
def test_w_r_always_passes(cap):
    for figures in [(-0.05, 0.06, 0.20), (0.0, 0.0, 0.0), (3.0, 7.5, 12.0), (-0.9, -0.5, -0.1)]:
        reference = _c(*figures, weights=_w(1))
        assert failed_guards(reference, reference, cap) == ()


@pytest.mark.parametrize("cap", [-1e-12, -0.00025, math.nan, math.inf, -math.inf])
def test_an_allowance_that_is_negative_or_not_finite_is_refused(cap):
    reference = _c(-0.05, 0.06, 0.20, 1.0, _w(1))
    with pytest.raises(ValueError, match="allowance"):
        admissible(reference, reference, cap)
    with pytest.raises(ValueError, match="allowance"):
        select([reference], cap)


# ---- Stage B: most diversified admissible, ties by U then B, T, G, weights -------------------


def test_stage_b_tie_set_is_formed_against_the_maximum_and_prefers_higher_u():
    high_measure = _c(-0.0490, 0.0600, 0.2000, 2.0, _w(1))  # the highest Bad, the lower U
    higher_u = _c(-0.0500, 0.0630, 0.2000, 2.0 - 0.5e-12, _w(2))
    chained = _c(-0.0510, 0.0700, 0.2000, 2.0 - 1.4e-12, _w(3))  # the highest U, out of the tie
    assert _cu(higher_u) > _cu(high_measure) and _cu(chained) > _cu(higher_u)
    assert high_measure.bad > higher_u.bad  # Bad before U would pick high_measure
    for order in itertools.permutations([high_measure, higher_u, chained]):
        assert select_diversified(order) == higher_u


def _stage_b_by_bad() -> tuple[list[Candidate], Candidate]:
    low_bad = _c(0.0, 0.25, 0.5, 2.0, _w(1))
    best = _c(0.0625, 0.125, 0.5, 2.0 - 0.5e-12, _w(2))  # 2 B + T is equal: U ties exactly
    lower_u = _c(0.1, 0.0, 0.5, 2.0 - 0.2e-12, _w(3))  # the highest Bad but a lower U
    _exact_u_tie(low_bad, best)
    assert _cu(lower_u) < _cu(best)
    return [low_bad, best, lower_u], best


def _stage_b_by_typical() -> tuple[list[Candidate], Candidate]:
    middle = _c(0.0, 0.25, 0.5, 2.0, _w(1))
    best_good = _exact_input(lambda g: _u(0.0, 0.26, g), _cu(middle), 0.47)
    low_good = _exact_input(lambda g: _u(0.0, 0.24, g), _cu(middle), 0.53)
    best = _c(0.0, 0.26, best_good, 2.0 - 0.5e-12, _w(2))
    low = _c(0.0, 0.24, low_good, 2.0 - 0.3e-12, _w(3))
    _exact_u_tie(middle, best, low)
    return [middle, best, low], best


def _stage_b_by_good() -> tuple[list[Candidate], Candidate]:
    middle = _c(0.0, 0.25, 0.5, 2.0, _w(1))
    best = _c(0.0, 0.25, math.nextafter(0.5, math.inf), 2.0 - 0.5e-12, _w(2))
    low = _c(0.0, 0.25, math.nextafter(0.5, -math.inf), 2.0 - 0.3e-12, _w(3))
    _exact_u_tie(middle, best, low)
    return [middle, best, low], best


def _stage_b_by_weights() -> tuple[list[Candidate], Candidate]:
    figures = (0.0, 0.25, 0.5)
    first = _c(*figures, 2.0, (0.3, 0.2, 0.5))
    second = _c(*figures, 2.0 - 0.5e-12, (0.2, 0.5, 0.3))
    best = _c(*figures, 2.0 - 0.3e-12, (0.2, 0.3, 0.5))
    return [first, second, best], best


@pytest.mark.parametrize(
    "fixture",
    [_stage_b_by_bad, _stage_b_by_typical, _stage_b_by_good, _stage_b_by_weights],
    ids=["bad", "typical", "good", "weights"],
)
def test_stage_b_u_ties_resolve_by_bad_then_typical_then_good_then_weights(fixture):
    pool, expected = fixture()
    assert max(_scored(c) for c in pool) - min(_scored(c) for c in pool) < 1e-12  # one tie set
    for order in itertools.permutations(pool):
        assert select_diversified(order) == expected


def test_stage_b_requires_a_measure_on_every_admissible_candidate():
    r = _c(-0.05, 0.06, 0.20, 1.0, _w(1))
    unscored = _c(-0.05 - 1 * BP, 0.06 + 1 * BP, 0.20, None, _w(2))  # admissible at 2.5 bp
    with pytest.raises(ValueError, match="measure"):
        select([r, unscored], 0.00025)
    with pytest.raises(ValueError, match="measure"):
        select_diversified([r, unscored])
    outside = _c(-0.05 - 20 * BP, 0.06 + 30 * BP, 0.20, None, _w(3))  # fails the Bad guard
    assert select([r, outside], 0.00025).selected == r  # an inadmissible member may be unscored
    assert select([r, unscored], 0.0).selected == r  # unscored but outside the 0 allowance


# ---- one pool across the allowances ----------------------------------------------------------

REF = (-0.0500, 0.0600, 0.2000)
LADDER = {  # name: (Bad, Typical, Good) moves in bp from w_R, measure; U move in the comment
    "R": ((0, 0, 0), 1.50),  # 0: w_R, the pool's lowest measure
    "C1": ((-2, 1, 0), 1.60),  # -0.9
    "C2": ((-3, 0, 3), 1.70),  # -1.5
    "C3": ((2, -12, 0), 1.65),  # -2.4
    "C4": ((-6, 2, 0), 1.90),  # -3.0
    "C5": ((-8, 0, 6), 2.00),  # -4.2
    "C6": ((-9.5, 2.5, -20), 2.20),  # -6.95
    "C7": ((3, -20, -10), 2.30),  # -5.2, Bad above w_R's
    "bad": ((-12, 15, 10), 3.00),  # -1.7, outside the Bad guard
    "veto": ((-1, -1, 5), 3.50),  # -0.4, Bad and Typical both lower
    "u": ((-9.9, 3, -49.9), 2.50),  # -10.03, outside every allowance up to 10 bp
    "typical": ((10, -26, 0), 2.60),  # -1.8, outside the Typical guard
    "good": ((5, 0, -51), 2.70),  # -2.1, outside the Good guard
    "dominated": ((-4, 0, 3), 5.00),  # -2.1, dominated by C2, the pool's highest measure
}
LADDER_PICKS = {0.0: "R", 0.00025: "C2", 0.0005: "C5", 0.001: "C7"}


def _ladder(measures: dict[str, float] | None = None) -> dict[str, Candidate]:
    pool = {}
    for i, (name, (moves, measure)) in enumerate(LADDER.items()):
        bad, typical, good = (base + move * BP for base, move in zip(REF, moves, strict=True))
        pool[name] = _c(bad, typical, good, measure if measures is None else measures[name], _w(i))
    return pool


def test_one_pool_across_the_allowances_matches_the_oracle_and_its_construction():
    named = _ladder()
    by_weights = {c.weights: name for name, c in named.items()}
    rows = [_row(c) for c in named.values()]
    previous = None
    for cap in CAPS:
        result = select(list(named.values()), cap)
        kept, ref, adm, pick = _oracle(rows, cap)
        assert isinstance(result, Selection) and result.allowance == cap
        assert [by_weights[c.weights] for c in result.pool] == [
            name for name in LADDER if name != "dominated"
        ]
        assert [_row(c) for c in result.pool] == kept
        assert result.reference == named["R"] and _row(result.reference) == ref
        assert [_row(c) for c in result.admissible] == adm
        assert _row(result.selected) == pick
        assert by_weights[result.selected.weights] == LADDER_PICKS[cap]
        assert result.sacrifice == pytest.approx(_cu(named["R"]) - _cu(result.selected), abs=1e-16)
        assert 0.0 <= result.sacrifice <= cap
        assert result.guards == _oracle_guards(pick, ref, cap) == frozenset()  # strictly inside
        if previous is not None:
            assert _scored(result.selected) >= _scored(previous.selected)
            assert _cu(result.selected) <= _cu(previous.selected)
            assert set(previous.admissible) <= set(result.admissible)
        previous = result
    # no safer-direction promise: the selected Bad falls, then rises above w_R's
    bads = [select(list(named.values()), cap).selected.bad for cap in CAPS]
    assert bads[1] < bads[0] and bads[2] < bads[1] and bads[3] > bads[0]


def test_every_guard_is_reported_where_it_excludes_a_more_diversified_member():
    named = _ladder()
    for cap in CAPS:
        assert select(list(named.values()), cap).excluding_guards == GUARDS


def test_excluding_guards_names_only_the_guards_that_exclude_a_more_diversified_member():
    r = _c(*REF, 2.0, _w(1))
    ok = _c(REF[0] - 1 * BP, REF[1] + 1 * BP, REF[2], 2.5, _w(2))  # admissible at 2.5 bp
    bad = _c(REF[0] - 20 * BP, REF[1] + 35 * BP, REF[2], 3.0, _w(3))  # U -1.5 bp
    far = _c(REF[0] + 1 * BP, REF[1] - 20 * BP, REF[2], 2.8, _w(4))  # U -5.4 bp
    weak = _c(REF[0] + 5 * BP, REF[1] - 30 * BP, REF[2], 1.0, _w(5))  # fails Typical, low measure
    unscored = _c(REF[0] - 20 * BP, REF[1] + 30 * BP, REF[2], None, _w(6))  # fails Bad
    assert select([r, ok], 0.00025).excluding_guards == ()
    assert select([r, ok, weak], 0.00025).excluding_guards == ()
    assert select([r, ok, unscored], 0.00025).excluding_guards == ()
    even = _c(REF[0] + 5 * BP, REF[1], REF[2] - 51 * BP, 2.5, _w(7))  # fails Good, measure = ok's
    assert select([r, ok, even], 0.00025).selected == ok
    assert select([r, ok, even], 0.00025).excluding_guards == ()  # not strictly more diversified
    assert select([r, ok, bad, far], 0.00025).excluding_guards == ("bad", "u")
    assert select([r, ok, bad, far], 0.00025).selected == ok


def test_changing_every_measure_leaves_stage_a_and_the_admissible_sets_unchanged():
    base = _ladder()
    reversed_measures = {name: 10.0 - measure for name, (_, measure) in LADDER.items()}
    rng = np.random.default_rng(2910)
    shuffled = dict(zip(LADDER, rng.permutation([m for _, m in LADDER.values()]), strict=True))
    for measures in (reversed_measures, shuffled):
        moved = _ladder({name: float(m) for name, m in measures.items()})
        for cap in CAPS:
            before = select(list(base.values()), cap)
            after = select(list(moved.values()), cap)
            assert after.reference.weights == before.reference.weights == base["R"].weights
            assert after.reference.utility == before.reference.utility
            assert [c.weights for c in after.pool] == [c.weights for c in before.pool]
            assert [c.weights for c in after.admissible] == [c.weights for c in before.admissible]
        assert select(list(moved.values()), 0.0).selected.weights == base["R"].weights


def test_allowance_zero_admits_only_u_at_or_above_w_r():
    w_r = _at_u(-0.0500, 0.0600, U0 - 0.4e-12, _w(1), 1.0)  # the tie set's highest Bad
    above = _at_u(-0.0502, 0.0604, U0, _w(2), 3.0)  # a tie member with U above w_R's
    below = _at_u(-0.0501, 0.0602, U0 - 0.8e-12, _w(3), 4.0)  # a tie member with U below
    other = _at_u(-0.0400, 0.0400, U0 - 1e-5, _w(4), 5.0)
    pool = [other, below, above, w_r]
    result = select(pool, 0.0)
    assert result.reference == w_r
    assert set(result.admissible) == {c for c in pool if _cu(c) >= _cu(w_r)} == {w_r, above}
    # Stage B may take the tie member above U_R: a sacrifice below zero by less than the tie width
    assert result.selected == above
    assert -1e-12 < result.sacrifice < 0.0
    assert result.guards == frozenset({"u"})  # not w_R itself, and U_R - 0 holds within 1e-10
    lower = [
        _c(c.bad, c.typical, c.good, 0.5 if c is above else c.measure, c.weights) for c in pool
    ]
    plain = select(lower, 0.0)
    assert plain.selected.weights == w_r.weights and plain.sacrifice == 0.0
    assert plain.guards == frozenset()


# ---- spec 7 `guards`: the constraints the selection sits on ----------------------------------


@pytest.mark.parametrize(
    ("offset", "binds"),
    [(0.0, True), (0.5e-10, True), (2e-10, False), (1e-9, False)],
    ids=["at", "within-1e-10", "inside-2e-10", "inside-1e-9"],
)
@pytest.mark.parametrize("guard", ["bad", "typical", "good"])
def test_guards_names_the_quantile_guard_the_selection_sits_on(guard, offset, binds):
    b, t, g = EXACT_REF  # each guard's boundary is exactly representable here
    r = _c(b, t, g, 1.0, _w(1))
    selected = {
        "bad": _c(b - 0.0010 + offset, t + 0.0005, g, 2.0, _w(2)),  # U -4.5 bp
        "typical": _c(b + 0.0005, t - 0.0025 + offset, g, 2.0, _w(2)),  # U -4.5 bp
        "good": _c(b + 0.0002, t, g - 0.0050 + offset, 2.0, _w(2)),  # U -3.8 bp
    }[guard]
    result = select([r, selected], 0.001)
    assert result.reference == r and result.selected == selected
    expected = frozenset({guard}) if binds else frozenset()
    assert result.guards == _oracle_guards(_row(selected), _row(r), 0.001) == expected


@pytest.mark.parametrize(
    ("offset", "binds"),
    [(1e-15, True), (0.5e-10, True), (2e-10, False), (1e-9, False)],
    ids=["at", "within-1e-10", "inside-2e-10", "inside-1e-9"],
)
@pytest.mark.parametrize("cap", [0.00025, 0.0005])
def test_guards_names_u_where_the_selection_uses_the_whole_allowance(cap, offset, binds):
    r = _c(0.0, 0.0, -0.0005, 1.0, _w(1))  # U_R = -0.5 bp; Good below the candidate's
    floor = _cu(r) - cap
    selected = _c((floor + offset) / 0.60, 0.0, 0.0, 2.0, _w(2))  # a Bad cut of 5 or 9.2 bp
    assert 0.0 < _cu(selected) - floor < offset + 1e-17  # admissible, `offset` above the floor
    result = select([r, selected], cap)
    assert result.reference == r and result.selected == selected
    expected = frozenset({"u"}) if binds else frozenset()
    assert result.guards == _oracle_guards(_row(selected), _row(r), cap) == expected


def test_guards_can_name_several_constraints_at_once():
    r = _c(0.0, 0.0, -0.0005, 1.0, _w(1))
    selected = _c(-0.0010, 0.0, 0.0, 2.0, _w(2))  # on the Bad guard exactly
    cap = _cu(r) - _cu(selected) + 1e-15  # and the allowance it uses is all but 1e-15 of the cap
    result = select([r, selected], cap)
    assert result.selected == selected
    assert result.guards == frozenset({"bad", "u"}) == _oracle_guards(_row(selected), _row(r), cap)


@pytest.mark.parametrize("cap", CAPS)
def test_guards_is_empty_when_the_selection_is_w_r(cap):
    r = _c(-0.05, 0.06, 0.20, 3.0, _w(1))
    less_diversified = _c(-0.05 - 2 * BP, 0.06 + 2 * BP, 0.20, 2.0, _w(2))
    for pool in ([r], [r, less_diversified]):
        result = select(pool, cap)
        assert result.selected == r == result.reference
        assert result.guards == frozenset()  # at cap 0 its U meets U_R - 0 exactly: still empty


# ---- validation -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"bad": math.nan},
        {"typical": math.inf},
        {"good": -math.inf},
        {"measure": math.nan},
        {"weights": (0.5, math.nan)},
        {"weights": ()},
    ],
)
def test_a_candidate_with_a_missing_or_non_finite_figure_is_refused(fields):
    values = {"weights": (0.5, 0.5), "bad": -0.05, "typical": 0.06, "good": 0.2, "measure": 1.0}
    with pytest.raises(ValueError):
        Candidate(**(values | fields))


def test_candidates_are_frozen_and_hold_their_weights_as_floats():
    c = Candidate(weights=tuple(np.array([0.25, 0.75])), bad=-0.05, typical=0.06, good=0.2)
    assert c.weights == (0.25, 0.75) and all(type(x) is float for x in c.weights)
    assert c.measure is None
    with pytest.raises(AttributeError):
        c.bad = 0.0  # type: ignore[misc]


def test_an_empty_pool_or_mixed_menus_are_refused():
    with pytest.raises(ValueError, match="empty"):
        select([], 0.0)
    with pytest.raises(ValueError, match="empty"):
        select_reference([])
    with pytest.raises(ValueError, match="empty"):
        select_diversified([])
    with pytest.raises(ValueError, match="empty"):
        nondominated([])
    mixed = [_c(-0.05, 0.06, 0.2, 1.0, (0.5, 0.5)), _c(-0.05, 0.06, 0.2, 1.0, (0.2, 0.3, 0.5))]
    for call in (nondominated, select_reference, select_diversified):
        with pytest.raises(ValueError, match="weights"):
            call(mixed)
    with pytest.raises(ValueError, match="weights"):
        admissible_set(mixed, mixed[0], 0.0)


def test_the_selector_never_mutates_its_inputs():
    named = _ladder()
    pool = list(named.values())
    snapshot = list(pool)
    select(pool, 0.001)
    assert pool == snapshot


# ---- the enumerable three-fund menu on one shared replay draw --------------------------------

MENU_SEED = 61303
MENU_ROWS = 756
MENU_VOL = np.array([0.0058, 0.0018, 0.0024])  # daily
MENU_MU = np.array([0.066, 0.061, 0.040])  # annual, the chart's expected returns
MENU_CORR = np.array([[1.0, 0.52, -0.11], [0.52, 1.0, 0.12], [-0.11, 0.12, 1.0]])
GRID_STEP = 25  # weights on multiples of 0.04: 351 mixes


def _menu_sample() -> np.ndarray:
    rng = np.random.default_rng(MENU_SEED)
    shocks = rng.standard_normal((MENU_ROWS, 3)) @ np.linalg.cholesky(MENU_CORR).T
    return shocks * MENU_VOL + MENU_MU / 252


@pytest.fixture(scope="module")
def menu() -> dict:
    """Every grid mix's B/T/G on one replay draw (fixed seed) and its DR² on the sample moments."""
    sample = _menu_sample()
    moments = stats.estimate_moments(sample)
    model = ranges.range_model(sample, MENU_MU, moments.cov)  # seed ranges.SEED, shared by all
    n = GRID_STEP
    grid = [(i / n, j / n, (n - i - j) / n) for i in range(n + 1) for j in range(n + 1 - i)]
    figures = ranges.one_year_ranges(model, np.array(grid))
    rows: list[Row] = [
        (
            float(figures["bad"][k]),
            float(figures["typical"][k]),
            float(figures["good"][k]),
            dr2_from(np.array(w), moments.sigma, moments.cov),
            w,
        )
        for k, w in enumerate(grid)
    ]
    return {"sample": sample, "model": model, "grid": grid, "rows": rows}


def test_menu_figures_are_those_of_the_shared_replay_draw(menu):
    """B/T/G of a few mixes by direct day-by-day compounding of the shared bootstrap paths."""
    sample, model = menu["sample"], menu["model"]
    assert (1.0 + sample > 0.0).all()  # no ruin day, so replay never raises
    index = ranges.bootstrap_index(len(sample), seed=model.seed)
    for k in (0, 7, 100, 200, len(menu["grid"]) - 1):
        w = np.array(menu["grid"][k])
        daily = sample @ w
        growth = 1.0 + daily - daily.mean() + float(MENU_MU @ w) / 252
        years = np.prod(growth[index], axis=1) - 1.0
        bad, typical, good = np.percentile(years, [2.5, 50.0, 97.5])
        row = menu["rows"][k]
        assert row[:3] == pytest.approx((bad, typical, good), rel=1e-12, abs=1e-14)


def test_enumerable_menu_selector_equals_the_exhaustive_oracle_at_every_allowance(menu):
    rows = menu["rows"]
    pool = [Candidate(weights=w, bad=b, typical=t, good=g, measure=m) for b, t, g, m, w in rows]
    picks = []
    for cap in CAPS:
        kept, ref, adm, pick = _oracle(rows, cap)
        result = select(pool, cap)
        assert [_row(c) for c in result.pool] == kept
        assert _row(result.reference) == ref
        assert [_row(c) for c in result.admissible] == adm
        assert _row(result.selected) == pick
        assert result.sacrifice == pytest.approx(_u(*ref[:3]) - _u(*pick[:3]), abs=1e-16)
        assert result.guards == _oracle_guards(pick, ref, cap)
        picks.append(pick)
        # the fixture is not vacuous: the filter bites, and some guard other than the allowance
        # excludes a member whose U is inside it
        assert len(kept) < len(rows)
        if cap == CAPS[-1]:
            excluded = {
                guard
                for row in kept
                for guard in _oracle_fails(row, ref, cap)
                if "u" not in _oracle_fails(row, ref, cap)
            }
            assert excluded == {"bad", "typical", "good", "veto"}
    assert len({pick[4] for pick in picks}) == 4  # every allowance selects a different mix


# ---- U coefficients other than the owner's: the protocol 7 (b) sensitivity ---------------------


def test_the_default_coefficients_are_the_owner_policy_bit_for_bit():
    assert COEFFICIENTS == OWNER_K == (BAD_WEIGHT, TYPICAL_WEIGHT, GOOD_WEIGHT)
    for figures in [(-0.05, 0.06, 0.20), (0.0123, -0.0456, 0.0789), OWNER_A, OWNER_B]:
        assert utility(*figures, COEFFICIENTS).hex() == utility(*figures).hex()
        assert utility(*figures).hex() == _u(*figures).hex()


@pytest.mark.parametrize("k", SENSITIVITY_K)
def test_utility_reads_the_coefficients_given(k):
    assert utility(1.0, 0.0, 0.0, k) == k[0]
    assert utility(0.0, 1.0, 0.0, k) == k[1]
    assert utility(0.0, 0.0, 1.0, k) == k[2]
    assert utility(-0.05, 0.06, 0.20, k).hex() == _u(-0.05, 0.06, 0.20, k).hex()
    assert _c(-0.05, 0.06, 0.20).utility == utility(-0.05, 0.06, 0.20)  # a candidate's U: owner's


@pytest.mark.parametrize(
    "k", [(0.6, 0.3), (0.6, 0.3, 0.1, 0.0), (0.6, math.nan, 0.1), (0.6, 0.3, -0.1), (0, 0.3, 0.1)]
)
def test_coefficients_that_are_not_three_positive_numbers_are_refused(k):
    pool = [_c(-0.01, 0.05, 0.12, 1.0, _w(1))]
    with pytest.raises(ValueError, match="coefficients"):
        select(pool, 0.00025, k)
    with pytest.raises(ValueError, match="coefficients"):
        utility(-0.01, 0.05, 0.12, k)


def test_coefficients_change_stage_a_the_u_allowance_and_stage_b_ties():
    # a: 8 bp more Bad, b: 20 bp more Typical. The owner's U prefers b by 1.2 bp,
    # (.70, .20, .10) prefers a by 1.6 bp.
    a = _c(0.0100, 0.0400, 0.1000, 1.0, _w(1))
    b = _c(0.0092, 0.0420, 0.1000, 2.0, _w(2))
    heavy = SENSITIVITY_K[0]
    assert _u(0.0092, 0.0420, 0.1000) - _u(0.0100, 0.0400, 0.1000) == pytest.approx(1.2 * BP)
    gap = _u(0.0100, 0.0400, 0.1000, heavy) - _u(0.0092, 0.0420, 0.1000, heavy)
    assert gap == pytest.approx(1.6 * BP, abs=1e-15)
    assert select_reference([a, b]) == b
    assert select_reference([a, b], heavy) == a
    owner, sensitive = select([a, b], 0.0), select([a, b], 0.0, heavy)
    assert (owner.reference, owner.selected) == (b, b)
    assert (sensitive.reference, sensitive.selected) == (a, a)
    assert sensitive.coefficients == heavy and owner.coefficients == COEFFICIENTS
    # b sits 1.6 bp of heavy U below a: inside a 2.5 bp allowance, so Stage B takes it
    wide = select([a, b], 0.00025, heavy)
    assert wide.selected == b and wide.sacrifice == pytest.approx(gap, abs=1e-18)
    assert failed_guards(b, a, 0.00005, heavy) == ("u",)
    assert failed_guards(b, a, 0.00005) == ()  # under the owner's U, b is above a
    assert admissible(b, a, 0.00025, heavy) and not admissible(b, a, 0.00005, heavy)
    assert admissible_set([a, b], a, 0.00005, heavy) == (a,)


def test_stage_b_u_ties_resolve_by_the_coefficients_given():
    heavy = SENSITIVITY_K[0]
    a = _c(0.0100, 0.0400, 0.1000, 3.0, _w(1))
    b = _c(0.0092, 0.0420, 0.1000, 3.0, _w(2))  # the same measure: a U tie-break decides
    assert select_diversified([a, b]) == b
    assert select_diversified([a, b], heavy) == a


@pytest.mark.parametrize("k", SENSITIVITY_K)
def test_enumerable_menu_selector_equals_the_oracle_under_sensitivity_coefficients(menu, k):
    rows = menu["rows"]
    pool = [Candidate(weights=w, bad=b, typical=t, good=g, measure=m) for b, t, g, m, w in rows]
    for cap in CAPS:
        kept, ref, adm, pick = _oracle(rows, cap, k)
        result = select(pool, cap, k)
        assert [_row(c) for c in result.pool] == kept
        assert _row(result.reference) == ref
        assert [_row(c) for c in result.admissible] == adm
        assert _row(result.selected) == pick
        assert result.sacrifice == pytest.approx(_u(*ref[:3], k) - _u(*pick[:3], k), abs=1e-16)
        assert result.guards == _oracle_guards(pick, ref, cap, k)
        assert result.coefficients == k
    # not vacuous: these coefficients move w_R away from the owner's
    assert _oracle(rows, 0.0, k)[1] != _oracle(rows, 0.0)[1]
