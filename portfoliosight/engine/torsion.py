"""Minimum torsion and the effective number of bets (spec 4.6).

The torsion is Meucci, Santangelo & Deguest (2015), "Risk budgeting and diversification based on
optimized uncorrelated factors" (SSRN 2276632): the uncorrelated factors closest to the funds
themselves. The recursion is the exact method of Meucci's `torsion.m` (BSD), as surveyed in
docs/reviews/2026-10-12_research_05_matlab_meucci_folders.md: with `c` the symmetric root of the
correlation matrix, start from `d = I` and repeat

    u = (d c^2 d)^(1/2),  q = u^-1 d c,  d = diag(diag(q c)),  pi = d q

until `pi` stops moving; then `T = diag(sigma) (pi c^-1) diag(1/sigma)`. Two numerical choices
differ from the MATLAB file, neither changes the recursion:

- `q` is the orthogonal polar factor of `d c`, so it is taken from `scipy.linalg.polar` (an SVD)
  rather than from a matrix root and a solve; `q` is then orthogonal to machine precision.
  Because `q` is orthogonal, `T cov T'` is diagonal at every step; convergence decides only
  that the torsion is the minimum one.
- `torsion.m` stops when the distance `|c - pi|` changes by less than 1e-8 * n of itself, which
  happens after three or four steps and leaves `T` about 1e-4 away from the fixed point (the
  distance is flat near its minimum). Here the iterate itself must stop: the Frobenius change
  of `pi` between two steps is below 1e-8, about a dozen steps as the paper reports.

Nothing here clips or renormalizes: a torsion that does not diagonalize, or bet shares that do
not sum to 1, raise `TorsionError`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import polar
from scipy.special import entr

CONVERGENCE_TOL = 1e-8  # Frobenius change of pi between two steps
MAX_ITERATIONS = 10_000
OFFDIAG_TOL = 1e-8  # max|offdiag(T cov T')| <= OFFDIAG_TOL * trace
SHARE_SUM_TOL = 1e-8  # |sum(p) - 1|


class TorsionError(ValueError):
    """The torsion, or the bet shares built on it, broke one of the spec 4.6 identities."""


@dataclass(frozen=True)
class TorsionBasis:
    """A checked torsion with the two derived arrays the tensor ships."""

    t: np.ndarray  # T, with T cov T' diagonal
    inv_t: np.ndarray  # (T')^-1, so exposures are b = inv_t @ w
    lam: np.ndarray  # Lambda = diag(T cov T')


def min_torsion(cov, *, max_iter: int = MAX_ITERATIONS, tol: float = CONVERGENCE_TOL) -> np.ndarray:
    """The minimum-torsion matrix `T` (n x n) of a covariance matrix: `T cov T'` is diagonal."""
    cov = _covariance(cov)
    sigma = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sigma, sigma)
    corr = (corr + corr.T) / 2.0
    eigenvalues, vectors = np.linalg.eigh(corr)
    # singular up to rounding counts as singular: the usual rank tolerance, n * eps * largest
    if not eigenvalues[0] > len(corr) * np.finfo(float).eps * eigenvalues[-1]:
        raise TorsionError("the correlation matrix is not positive definite")
    root = (vectors * np.sqrt(eigenvalues)) @ vectors.T
    root_inverse = (vectors / np.sqrt(eigenvalues)) @ vectors.T
    x = _perturbation(root, max_iter, tol) @ root_inverse
    return sigma[:, None] * x / sigma[None, :]


def torsion_basis(cov, torsion=None) -> TorsionBasis:
    """Check a torsion against `cov` and derive `(T')^-1` and `Lambda`.

    `torsion=None` computes the minimum torsion. Either way the result is checked, not trusted.
    """
    cov = _covariance(cov)
    t = min_torsion(cov) if torsion is None else np.asarray(torsion, dtype=float)
    if t.shape != cov.shape:
        raise TorsionError(f"torsion shape {t.shape} does not match covariance {cov.shape}")
    rotated = t @ cov @ t.T
    lam = np.diag(rotated).copy()
    trace = float(lam.sum())
    offdiag = float(np.abs(rotated - np.diag(lam)).max())
    if not offdiag <= OFFDIAG_TOL * trace:
        raise TorsionError(
            f"max|offdiag(T cov T')| = {offdiag!r} exceeds {OFFDIAG_TOL} * trace = "
            f"{OFFDIAG_TOL * trace!r}"
        )
    try:
        inv_t = np.linalg.inv(t).T
    except np.linalg.LinAlgError as exc:
        raise TorsionError("the torsion matrix is singular") from exc
    return TorsionBasis(t=t, inv_t=inv_t, lam=lam)


def bet_shares(w, cov, basis: TorsionBasis) -> np.ndarray:
    """Variance shares of the torsion bets: `p_i = Lambda_i b_i^2 / (w' cov w)`, `b = T^-T w`."""
    w = np.asarray(w, dtype=float)
    variance = float(w @ np.asarray(cov, dtype=float) @ w)
    if not variance > 0:
        raise TorsionError("the mix has no variance, so its bet shares are undefined")
    exposures = basis.inv_t @ w
    shares = basis.lam * exposures**2 / variance
    total = float(shares.sum())
    if not abs(total - 1.0) <= SHARE_SUM_TOL:
        raise TorsionError(f"sum(p) = {total!r} is not 1 within {SHARE_SUM_TOL}")
    return shares


def enb(w, cov, basis: TorsionBasis) -> float:
    """Effective number of bets on a checked basis: `exp(-sum p ln p)`, with `0 ln 0 = 0`."""
    return float(np.exp(entr(bet_shares(w, cov, basis)).sum()))


def effective_number_of_bets(w, cov, torsion=None) -> float:
    """ENB of weights `w`; `torsion=None` uses the minimum torsion of `cov`."""
    return enb(w, cov, torsion_basis(cov, torsion))


def _perturbation(root: np.ndarray, max_iter: int, tol: float) -> np.ndarray:
    """Run the recursion on the correlation root `c` and return the converged `pi = d q`."""
    d = np.ones(len(root))
    previous = root  # the perturbation at d = I, q = I
    for _ in range(max_iter):
        rotation, _ = polar(d[:, None] * root, side="left")
        d = np.einsum("ij,ji->i", rotation, root)
        perturbation = d[:, None] * rotation
        if float(np.linalg.norm(perturbation - previous)) < tol:
            return perturbation
        previous = perturbation
    raise TorsionError(f"the minimum-torsion recursion did not converge in {max_iter} iterations")


def _covariance(cov) -> np.ndarray:
    cov = np.asarray(cov, dtype=float)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise TorsionError("a covariance matrix must be square")
    if not np.isfinite(cov).all():
        raise TorsionError("a covariance matrix must be finite")
    if not np.allclose(cov, cov.T, rtol=1e-10, atol=0.0):
        raise TorsionError("a covariance matrix must be symmetric")
    if not (np.diag(cov) > 0).all():
        raise TorsionError("a covariance matrix must have a positive diagonal")
    return cov
