"""The post-check every solved weight vector passes before it is written (spec 4.11)."""

from __future__ import annotations

import numpy as np
import pytest

from portfoliosight.engine.invariants import TOL, InvariantError, check_floor, check_weights


def _sigma(w, cov) -> float:
    return float(np.sqrt(w @ cov @ w))


def _case():
    cov = np.diag([0.02, 0.05, 0.08, 0.12]) ** 2 + 1e-4
    w = np.full(4, 0.25)
    return w, np.zeros(4), np.full(4, 0.5), cov, _sigma(w, cov) + 1e-3, 2.0


def _raises(name: str, w, lo, hi, cov, ceiling, enb) -> InvariantError:
    with pytest.raises(InvariantError) as caught:
        check_weights(w, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=enb)
    assert caught.value.invariant == name and name in str(caught.value)
    assert isinstance(caught.value, ValueError)
    return caught.value


def test_a_clean_vector_passes_and_the_tolerance_is_one_in_a_million():
    w, lo, hi, cov, ceiling, enb = _case()
    assert TOL == 1e-6
    assert check_weights(w, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=enb) is None
    check_weights(w + 5e-7 / 4, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=enb)
    check_weights(w, lo=lo, hi=hi, cov=cov, ceiling=_sigma(w, cov) - 5e-7, enb=enb)
    check_weights(w, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=4 + 5e-7)
    check_weights(w, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=1 - 5e-7)
    edge = np.array([0.5 + 5e-7, 0.5 - 5e-7, 0.0, 0.0])
    check_weights(edge, lo=lo, hi=hi, cov=cov, ceiling=_sigma(edge, cov), enb=enb)


def test_each_invariant_alone_raises_and_is_named():
    w, lo, hi, cov, ceiling, enb = _case()
    _raises("sum", w + 1e-4 / 4, lo, hi, cov, ceiling, enb)
    _raises("sum", w - 1e-4 / 4, lo, hi, cov, ceiling, enb)
    over = np.array([0.5 + 1e-4, 0.5 - 1e-4, 0.0, 0.0])
    error = _raises("bounds", over, lo, hi, cov, _sigma(over, cov) + 1e-3, enb)
    assert "fund 0" in str(error)
    under = np.array([0.1 - 1e-4, 0.3 + 1e-4, 0.3, 0.3])
    lo_b = np.array([0.1, 0.0, 0.0, 0.0])
    _raises("bounds", under, lo_b, hi, cov, _sigma(under, cov) + 1e-3, enb)
    _raises("sigma", w, lo, hi, cov, _sigma(w, cov) - 1e-4, enb)
    _raises("enb", w, lo, hi, cov, ceiling, 4 + 1e-4)
    _raises("enb", w, lo, hi, cov, ceiling, 1 - 1e-4)


def test_not_a_number_never_passes():
    w, lo, hi, cov, ceiling, enb = _case()
    broken = w.copy()
    broken[2] = np.nan
    _raises("sum", broken, lo, hi, cov, ceiling, enb)
    _raises("sigma", w, lo, hi, cov, float("nan"), enb)
    _raises("enb", w, lo, hi, cov, ceiling, float("nan"))


def test_return_floor_check():
    mu = np.array([0.02, 0.04, 0.06, 0.08])
    w = np.full(4, 0.25)
    assert check_floor(w, mu=mu, floor=0.05) is None
    check_floor(w, mu=mu, floor=0.05 + 5e-7)
    with pytest.raises(InvariantError, match="floor") as caught:
        check_floor(w, mu=mu, floor=0.05 + 1e-4)
    assert caught.value.invariant == "floor"
