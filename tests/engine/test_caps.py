"""Caps: the default rule, validation and the minimums-first greedy fill (spec 4.4)."""

from __future__ import annotations

import numpy as np
import pytest

from portfoliosight.engine import caps
from portfoliosight.engine.caps import (
    CapsError,
    default_max,
    greedy_fill,
    greedy_is_unique,
    requested_caps,
    resolve_bounds,
)


def _ids(n: int) -> list[str]:
    return [f"F{i:02d}" for i in range(n)]


def test_default_max_is_three_over_n_clamped():
    spot = {2: 1.0, 3: 1.0, 4: 0.75, 5: 0.6, 10: 0.3, 12: 0.25, 23: 0.25, 30: 0.25}
    for n in range(2, 31):
        lo, hi = resolve_bounds(_ids(n))
        assert lo.shape == (n,) and hi.shape == (n,)
        assert (lo == 0.0).all()
        assert np.abs(hi - min(max(3.0 / n, 0.25), 1.0)).max() <= 1e-15
        assert default_max(n) == hi[0]
        if n in spot:
            assert abs(hi[0] - spot[n]) <= 1e-12
    assert caps.RULE == "max(0.25, 3/N)"


def test_requested_overrides_replace_only_what_they_name():
    ids = ["A", "B", "C", "D", "E"]
    requested = [
        {"id": "B", "min": 0.1, "max": None},
        {"id": "D", "min": None, "max": 0.35},
        {"id": "E"},
    ]
    lo, hi = resolve_bounds(ids, requested)
    assert lo.tolist() == [0.0, 0.1, 0.0, 0.0, 0.0]
    assert np.abs(hi - np.array([0.6, 0.6, 0.6, 0.35, 0.6])).max() <= 1e-15
    assert resolve_bounds(ids, [])[1].tolist() == resolve_bounds(ids, None)[1].tolist()
    # boundary sums are valid, also when they are 1 only up to rounding
    pinned_lo, pinned_hi = resolve_bounds(
        _ids(4), [{"id": i, "min": 0.25, "max": 0.25} for i in _ids(4)]
    )
    assert pinned_lo.tolist() == pinned_hi.tolist() == [0.25] * 4
    for shortfall, accepted in ((5e-10, True), (1e-8, False)):
        short = [{"id": i, "min": None, "max": (1.0 - shortfall) / 4} for i in _ids(4)]
        over = [{"id": i, "min": (1.0 + shortfall) / 4, "max": 0.5} for i in _ids(4)]
        for request in (short, over):
            if accepted:
                assert len(resolve_bounds(_ids(4), request)) == 2
            else:
                with pytest.raises(CapsError, match="sum"):
                    resolve_bounds(_ids(4), request)


@pytest.mark.parametrize(
    ("ids", "requested", "token"),
    [
        (["AAA", "BBB", "CCC", "DDD"], [{"id": "BBB", "min": 0.5, "max": 0.3}], "BBB"),
        (["AAA", "BBB", "CCC", "DDD"], [{"id": "CCC", "min": None, "max": 1.2}], "CCC"),
        (["AAA", "BBB", "CCC", "DDD"], [{"id": "DDD", "min": -0.1, "max": None}], "DDD"),
        (["AAA", "BBB", "CCC", "DDD"], [{"id": "AAA", "min": float("nan"), "max": None}], "AAA"),
        (["AAA", "BBB", "CCC", "DDD"], [{"id": "AAA", "min": None, "max": "half"}], "AAA"),
        (["AAA", "BBB", "CCC", "DDD"], [{"id": "AAA", "min": True, "max": None}], "AAA"),
        (_ids(23), [{"id": "F03", "min": 0.3, "max": None}], "F03"),  # above the default max
        (["AAA", "BBB"], [{"id": "ZZZ", "min": None, "max": 0.5}], "ZZZ"),
        (["AAA", "BBB"], [{"id": "AAA", "max": 0.9}, {"id": "AAA", "max": 0.8}], "AAA"),
        (["AAA", "BBB"], [{"min": 0.1}], "id"),
        (["AAA", "AAA"], None, "AAA"),
        (["AAA"], None, "at least 2"),
        ([], None, "at least 2"),
    ],
)
def test_invalid_caps_name_the_fund(ids, requested, token):
    with pytest.raises(CapsError, match=token) as caught:
        resolve_bounds(ids, requested)
    assert isinstance(caught.value, ValueError)


def test_infeasible_sums_say_sum():
    ids = ["AAA", "BBB", "CCC", "DDD"]
    with pytest.raises(CapsError, match="sum of the minimums"):
        resolve_bounds(ids, [{"id": i, "min": 0.3, "max": None} for i in ids])
    with pytest.raises(CapsError, match="sum of the maximums"):
        resolve_bounds(ids, [{"id": i, "min": None, "max": 0.2} for i in ids])


def test_greedy_fill_places_every_minimum_first():
    lo, hi = np.array([0.3, 0.3, 0.0, 0.0]), np.array([0.3, 0.3, 0.4, 0.4])
    for mu, expected in (
        ([0.10, 0.08, 0.02, 0.05], [0.3, 0.3, 0.0, 0.4]),
        ([0.01, 0.02, 0.10, 0.05], [0.3, 0.3, 0.4, 0.0]),
        ([0.01, 0.02, 0.05, 0.10], [0.3, 0.3, 0.0, 0.4]),
    ):
        w = greedy_fill(np.array(mu), lo, hi)
        assert w[0] == 0.3 and w[1] == 0.3
        assert np.abs(w - np.array(expected)).max() <= 1e-12
    # the lowest-return fill runs the same rule in ascending order
    low = greedy_fill(np.array([0.10, 0.08, 0.02, 0.05]), lo, hi, ascending=True)
    assert np.abs(low - np.array([0.3, 0.3, 0.4, 0.0])).max() <= 1e-12
    # ties keep menu order, so the fill is deterministic
    tied = greedy_fill(np.array([0.05, 0.05, 0.05]), np.zeros(3), np.full(3, 0.6))
    assert np.abs(tied - np.array([0.6, 0.4, 0.0])).max() <= 1e-12
    tied_low = greedy_fill(
        np.array([0.05, 0.05, 0.05]), np.zeros(3), np.full(3, 0.6), ascending=True
    )
    assert np.abs(tied_low - np.array([0.6, 0.4, 0.0])).max() <= 1e-12


def test_greedy_fill_is_the_extreme_return_under_the_bounds():
    rng = np.random.default_rng(3401)
    for _ in range(40):
        n = int(rng.integers(2, 31))
        lo = rng.uniform(0.0, 0.6 / n, n) * (rng.random(n) < 0.5)
        hi = np.minimum(np.maximum(lo + 0.05, rng.uniform(1.2 / n, min(1.0, 4.0 / n), n)), 1.0)
        mu = rng.uniform(-0.02, 0.12, n)
        top, bottom = greedy_fill(mu, lo, hi), greedy_fill(mu, lo, hi, ascending=True)
        for w in (top, bottom):
            assert abs(w.sum() - 1.0) <= 1e-12
            assert (w >= lo - 1e-12).all() and (w <= hi + 1e-12).all()
        for _ in range(20):  # no other feasible mix earns more than the top or less than the bottom
            other = lo + (hi - lo) * rng.dirichlet(np.ones(n)) * 0.5
            other += (1.0 - other.sum()) * (hi - other) / (hi - other).sum()
            assert (other >= lo - 1e-12).all() and (other <= hi + 1e-12).all()
            assert mu @ bottom - 1e-12 <= mu @ other <= mu @ top + 1e-12


def test_greedy_is_unique_unless_tied_funds_can_trade_weight():
    lo, hi = np.zeros(4), np.full(4, 0.6)
    assert greedy_is_unique(np.array([0.08, 0.07, 0.05, 0.03]), lo, hi)
    # the two top funds tie: 0.6/0.4 and 0.4/0.6 earn the same
    assert not greedy_is_unique(np.array([0.08, 0.08, 0.05, 0.03]), lo, hi)
    # a tie below the filled funds changes nothing
    assert greedy_is_unique(np.array([0.08, 0.07, 0.05, 0.05]), lo, hi)
    # a tie between a full fund and an empty one, with no partly filled fund between them
    half = np.full(4, 0.5)
    assert not greedy_is_unique(np.array([0.08, 0.07, 0.07, 0.03]), lo, half)
    assert greedy_is_unique(np.array([0.08, 0.07, 0.06, 0.03]), lo, half)
    # tied funds that cannot trade (both pinned) leave one mix
    pinned = np.array([0.4, 0.3, 0.2, 0.1])
    assert greedy_is_unique(np.full(4, 0.05), pinned, pinned)
    assert not greedy_is_unique(np.full(3, 0.05), np.zeros(3), np.ones(3))
    # the lowest-return fill is judged the same way
    assert not greedy_is_unique(np.array([0.08, 0.07, 0.03, 0.03]), lo, hi, ascending=True)
    assert greedy_is_unique(np.array([0.08, 0.08, 0.04, 0.03]), lo, hi, ascending=True)


def test_requested_caps_are_checked_fund_by_fund_whatever_the_window():
    ids = ["AAA", "BBB", "CCC"]
    request = [{"id": "BBB", "min": 0.1, "max": None}, {"id": "CCC", "max": 1}, {"id": "AAA"}]
    assert requested_caps(ids, request) == {
        "BBB": {"min": 0.1, "max": None},
        "CCC": {"min": None, "max": 1},  # kept as given: the universe hash covers the request
        "AAA": {"min": None, "max": None},
    }
    assert requested_caps(ids, None) == {} and requested_caps(ids, []) == {}
    for entry, token in (
        ({"id": "AAA", "min": 2, "max": -1}, "AAA"),
        ({"id": "AAA", "min": 0.6, "max": 0.4}, "AAA: min 0.6 is above max 0.4"),
        ({"id": "AAA", "max": 1.0000001}, "AAA: max must be a number between 0 and 1"),
        ({"id": "AAA", "min": float("inf")}, "AAA"),
        ({"id": "ZZZ", "max": 0.5}, "ZZZ: not a fund of this menu"),
        ({"max": 0.5}, "fund id"),
    ):
        with pytest.raises(CapsError, match=token):
            requested_caps(ids, [entry])
    with pytest.raises(CapsError, match="AAA: capped more than once"):
        requested_caps(ids, [{"id": "AAA"}, {"id": "AAA", "max": 0.5}])
