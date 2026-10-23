"""Synthetic origin contexts for the optimizer tests (piece 1): seeded, no data files."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import numpy as np

from portfoliosight.engine.stats import estimate_moments, menu_beta_blend
from portfoliosight.research.fixedrisk.contracts import MenuSpec, OriginContext


def synthetic_context(
    funds: int = 5, rows: int = 300, cap: float = 0.6, seed: int = 7, name: str = "synth"
) -> OriginContext:
    """A T x N sample of correlated daily returns with drifts and vols spread across funds."""
    rng = np.random.default_rng(seed)
    vols = np.linspace(0.002, 0.016, funds)
    drifts = np.linspace(1e-4, 5e-4, funds)
    loadings = rng.normal(size=(funds, 2)) * 0.6
    corr = loadings @ loadings.T + np.eye(funds)
    d = np.sqrt(np.diag(corr))
    corr = corr / np.outer(d, d)
    chol = np.linalg.cholesky(corr)
    shocks = rng.standard_t(5, size=(rows, funds)) / np.sqrt(5 / 3)
    sample = drifts + (shocks @ chol.T) * vols
    moments = estimate_moments(sample)
    rf = 0.03
    mu_s = menu_beta_blend(moments.mu, moments.cov, rf)[0]
    holdings = tuple(f"F{i}" for i in range(funds))
    menu = MenuSpec(name, holdings, (0.0,) * funds, (cap,) * funds)
    sample.setflags(write=False)
    digest = hashlib.sha256(sample.tobytes() + name.encode() + str(cap).encode()).hexdigest()
    origin = date(2020, 1, 31)
    return OriginContext(
        menu=menu,
        month="2020-01",
        origin=origin,
        lookback="3y",
        days=tuple(origin - timedelta(days=rows - i) for i in range(rows)),
        sample=sample,
        mu_hat=moments.mu,
        mu_s=mu_s,
        cov=moments.cov,
        sigma=moments.sigma,
        risk_free_rate=rf,
        inputs_sha256=digest,
    )
