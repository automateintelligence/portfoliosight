"""The suggested point on a column: the balanced point or the peak (spec 4.8).

Walking a column's ladder down from the frontier mix, each step gives up some return and gains
some diversification. The balanced point is the knee of that curve: the place where the gains
stop outrunning the cost. The peak is the bottom of the ladder, the most diversified mix found
at that risk. Both are stored; `DEFAULT_POINT` says which one the page opens on.

A point is a level of the ladder: 0 is the frontier mix, the last one the peak.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

from .invariants import TOL

DEFAULT_POINT: Literal["balanced", "peak"] = "balanced"
POINTS = ("balanced", "peak")


def balanced_level(returns, enbs) -> int:
    """The ladder level at the knee of ENB gained against return given up.

    `returns` and `enbs` are a column's ladder from the frontier mix (first) to the peak (last):
    returns never rise, ENB never falls. Both are rescaled to run from 0 to 1 over the column,
    `g` the share of the return span given up and `e` the share of the ENB span gained. The
    chord from the top of the ladder to its bottom is then the diagonal `e = g`, and the knee is
    the level farthest above it: the one that maximizes `e - g`, which is the perpendicular
    distance to the chord up to a factor. Between levels the curve is taken as straight, so no
    point between two levels is farther than both. A tie goes to the level that gives up less
    return.

    Two ladders have no curve to read. One that gains no ENB (a collapsed column) answers 0, the
    frontier mix. One that gains ENB for no return at all (funds with equal expected returns)
    answers the last level: the diversification is free.
    """
    returns = np.asarray(returns, dtype=float)
    enbs = np.asarray(enbs, dtype=float)
    if returns.shape != enbs.shape or returns.ndim != 1 or len(returns) < 2:
        raise ValueError("a ladder needs one return and one ENB per level, and two levels")
    given_up = returns[0] - returns[-1]
    gained = enbs[-1] - enbs[0]
    if not gained > TOL:
        return 0
    if not given_up > TOL:
        return len(returns) - 1
    above_chord = (enbs - enbs[0]) / gained - (returns[0] - returns) / given_up
    return int(np.argmax(above_chord))


def suggested_level(returns, enbs, point: str = DEFAULT_POINT) -> int:
    """The level the page opens on: the balanced one, or the peak (the last) when asked.

    A ladder that gains no ENB has nothing to walk to: its answer is 0 for either point.
    """
    if point not in POINTS:
        raise ValueError(f"unknown point {point!r}; expected one of {list(POINTS)}")
    balanced = balanced_level(returns, enbs)
    if point == "peak" and enbs[-1] - enbs[0] > TOL:
        return len(returns) - 1
    return balanced
