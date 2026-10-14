"""The invariants every computed mix satisfies before it is written (spec 4.11).

One tolerance everywhere, 1e-6: weights sum to 1, respect their bounds, sit at or below their
risk ceiling, and have an effective number of bets between 1 and N; a mix of a ladder also sits
on its column's risk line and earns its level's return. A vector that fails is an error, never
something to clip or renormalize.
"""

from __future__ import annotations

import numpy as np

TOL = 1e-6


class InvariantError(ValueError):
    """A weight vector broke an invariant; `invariant` names which one."""

    def __init__(self, invariant: str, detail: str):
        super().__init__(f"{invariant}: {detail}")
        self.invariant = invariant


def check_weights(w, *, lo, hi, cov, ceiling: float, enb: float) -> None:
    """Raise `InvariantError` unless `w` meets the four invariants.

    `enb` is the effective number of bets already computed for `w`; N is `len(w)`. Every test
    is written so that a NaN fails it.
    """
    w = np.asarray(w, dtype=float)
    total = float(w.sum())
    if not abs(total - 1.0) <= TOL:
        raise InvariantError("sum", f"weights add up to {total!r}, not 1 within {TOL}")
    excess = np.maximum(np.asarray(lo, dtype=float) - w, w - np.asarray(hi, dtype=float))
    worst = int(np.argmax(excess))
    if not excess[worst] <= TOL:
        raise InvariantError(
            "bounds", f"fund {worst} holds {w[worst]!r}, outside [{lo[worst]!r}, {hi[worst]!r}]"
        )
    sigma = float(np.sqrt(w @ np.asarray(cov, dtype=float) @ w))
    if not sigma <= ceiling + TOL:
        raise InvariantError("sigma", f"risk {sigma!r} is above its ceiling {ceiling!r}")
    if not 1.0 - TOL <= enb <= len(w) + TOL:
        raise InvariantError("enb", f"effective number of bets {enb!r} is outside [1, {len(w)}]")


def check_risk_line(w, *, cov, risk: float) -> None:
    """Raise unless the mix has its column's risk (spec 4.7), within the tolerance either way."""
    w = np.asarray(w, dtype=float)
    sigma = float(np.sqrt(w @ np.asarray(cov, dtype=float) @ w))
    if not abs(sigma - risk) <= TOL:
        raise InvariantError("risk_line", f"risk {sigma!r} is not its column's risk {risk!r}")


def check_floor(w, *, mu, floor: float) -> None:
    """Raise unless the mix earns its level's return floor (spec 4.7), within the tolerance."""
    earned = float(np.asarray(mu, dtype=float) @ np.asarray(w, dtype=float))
    if not earned >= floor - TOL:
        raise InvariantError("floor", f"return {earned!r} is below its floor {floor!r}")
