"""The shape of the volatility model (simulation engines spec 4.3): panel, fit, pool and guard.

The volatility model (`garch`) takes each fund's character from up to ten years of its own daily
history and the same for every lookback: fat tails and volatility that clusters, from a
GARCH(1,1)-t fit per fund, and the way the funds' shocks move together, from the days on which
every fund has a return. QSE supplies all of the statistics (`qse.distributions.joint`, pulled
into this repository by `scripts/sync_qse.py` at a pinned commit): the fit, the pool of shock
rows, the row draw and the recursion. This module only arranges them:

1. `shape_panel`: the last 2,520 rows of the included funds' own calendar (the days on which at
   least one of them has a return) ending at the generation's day, each fund on its own rows and
   NaN elsewhere, with the digest of exactly that panel. Two lookbacks that include the same funds
   have the same panel, so they share one fit.
2. `fit_shape`: QSE's panel fit with its defaults, on the panel's daily log returns `log1p(r)`
   (a missing return stays missing; a day at or below -100% has none and fails the fit). A fund
   that cannot be fitted (too short, too calm, the optimizer failed, no long-run variance) is held
   at constant volatility by QSE and the status says so; nothing is filled in or clipped. The
   splice guard, the outliers and the statuses all read that fit's residuals, in log space. The
   pool is the common rows, each column re-standardized to mean 0 and variance 1. Fewer than 126
   such rows leave the engine unavailable for the tensor. Before anything else the splice guard
   looks at each seeded fund's splice date: a move of more than 6 standard deviations there that
   the rest of the menu did not share is a corporate action the record missed, and the build
   fails naming fund and date. The splice dates the guard checked are part of the artifact
   (`splice_dates`): a fit is reused only by a build that names the same ones, so no build skips
   the guard.
3. `simulate_panel`: 2,000 one-year paths of 252 days of daily log returns, from the artifact
   alone. One draw of pool rows (seed 20261013) is shared by every fund, so the funds keep moving
   together as they did on real days, and each fund runs its own recursion from its long-run
   variance. The result is exactly what QSE's
   `simulate_fhs_panel(fit, ..., row_indices=..., start="long_run")` returns; building it from
   the artifact lets a build and a later range request share the same bytes.

The simulated panel supplies shape only: `ranges.garch_range_model` replaces each fund's drift
and volatility with the chart's own (spec 4.5), in log space, and takes the days back to simple
returns.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from importlib import resources

import numpy as np
import pandas as pd

from qse.distributions.garch_recursion import garch11_long_run_variance, simulate_garch11
from qse.distributions.joint import draw_row_indices, fit_garch_t_panel, residual_pool

from .ranges import HORIZON_DAYS, PATHS, RUIN, SCALE, SEED, sample_digest
from .stats import TRADING_DAYS

SHAPE_ROWS = 2520  # ten years of trading days: the longest history a fund's shape is fitted on
MIN_POOL_ROWS = 126  # the fewest shared days that may be resampled, as a window's own floor
OUTLIER_Z = 6.0  # a standardized move this large is recorded; on a splice date it is checked
METHOD_NAME = "garch_t_fhs"
START = "long_run"
RETURNS = "log"  # the fit and the simulation are in daily log returns, log1p(r)
UNAVAILABLE_REASON = "not enough shared history for the volatility model"
# Every missing return is hashed as this one NaN, whatever sign or payload it arrived with.
CANONICAL_NAN = np.array([0x7FF8000000000000], dtype=np.uint64).view(np.float64)[0]
_PARAMETERS = ("mu", "omega", "alpha", "beta", "nu", "long_run_sigma_annual")


class ShapeError(ValueError):
    """The volatility model cannot be fitted to this menu's history as it stands.

    `fund` and `date` name the fund and day when the splice guard tripped or a day lost
    everything, else `None`.
    """

    def __init__(self, message: str, fund: str | None = None, day: str | None = None):
        super().__init__(message)
        self.fund = fund
        self.date = day


@dataclass(frozen=True)
class ShapePanel:
    """The included funds' last `SHAPE_ROWS` days, each fund on its own rows, NaN elsewhere."""

    frame: pd.DataFrame
    start: str  # ISO date of the first row
    end: str  # ISO date of the last row: the generation's day, when a fund traded on it
    rows: int
    sample_sha256: str  # `ranges.sample_digest` of the panel, NaN as the canonical quiet NaN


@dataclass(frozen=True)
class GarchArtifact:
    """A fitted volatility model: everything a simulation needs, and what the tensor reports.

    Arrays are per fund, in `funds` order, and read-only. Fallback funds have `alpha = beta = 0`,
    `omega` their sample variance and `nu` NaN. `pool` is `None` when the engine is unavailable;
    `pool_rows` is then the number of shared rows there were. `splice_dates` are the (fund, ISO
    day) pairs the splice guard checked, the panel's funds only, sorted (`guarded_splice_dates`).
    """

    funds: tuple[str, ...]
    rows: int
    start: str
    end: str
    sample_sha256: str
    mu: np.ndarray
    omega: np.ndarray
    alpha: np.ndarray
    beta: np.ndarray
    nu: np.ndarray
    status: tuple[str, ...]
    messages: tuple[str, ...]
    n_obs: tuple[int, ...]
    long_run_sigma_annual: np.ndarray
    pool: np.ndarray | None  # T_pool x N re-standardized residual rows, float64
    pool_rows: int
    pool_sha256: str | None
    outliers: tuple[dict, ...]  # {"id", "date", "z"} for every |z| > OUTLIER_Z
    splice_dates: tuple[tuple[str, str], ...]  # what the splice guard checked
    unavailable_reason: str | None
    qse: str  # the QSE commit the fit ran on
    arch: str  # the `arch` version the fit ran on
    returns: str  # the space the fit and its pool are in: `RETURNS`


def shape_panel(returns: pd.DataFrame, included: Sequence[str], asof) -> ShapePanel:
    """The shape panel of the funds `included` in a window, from the returns frame up to `asof`.

    The calendar is the funds' own: a day on which none of them has a return is not a row, so
    the panel does not depend on other columns of the frame or on the lookback.
    """
    ids = [str(fund) for fund in included]
    if not ids:
        raise ValueError("a shape panel needs at least one fund")
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise ValueError("returns must be indexed by a DatetimeIndex")
    missing = [fund for fund in ids if fund not in returns.columns]
    if missing:
        raise ValueError(f"the returns frame has no column for {', '.join(missing)}")
    end = pd.Timestamp(asof)
    if not isinstance(end, pd.Timestamp):
        raise ValueError("asof must be a date")
    frame = returns.loc[returns.index <= end.normalize(), ids].astype(np.float64)
    frame = frame.loc[frame.notna().any(axis=1)].iloc[-SHAPE_ROWS:]
    if len(frame) < 2:
        raise ValueError("a shape panel needs at least two rows")
    days = [stamp.date().isoformat() for stamp in frame.index]
    values = frame.to_numpy(dtype=np.float64, copy=True)
    values[np.isnan(values)] = CANONICAL_NAN
    return ShapePanel(
        frame=frame,
        start=days[0],
        end=days[-1],
        rows=len(days),
        sample_sha256=sample_digest(ids, days, values),
    )


def fit_shape(panel: ShapePanel, splice_dates: Mapping[str, str] | None = None) -> GarchArtifact:
    """Fit the volatility model to a shape panel; `splice_dates` maps a seeded fund to its ISO day.

    The fit is on the daily log returns `log1p(r)`. Raises `ShapeError` when a day loses
    everything (it has no log return), when the splice guard trips, or when the shared rows hold
    no information about a fund that does vary (QSE's pool refuses it); a pool shorter than
    `MIN_POOL_ROWS` is not an error but an artifact without a pool, whose `unavailable_reason`
    the tensor shows.
    """
    guarded = guarded_splice_dates([str(fund) for fund in panel.frame.columns], splice_dates)
    _refuse_total_losses(panel)
    fit = fit_garch_t_panel(np.log1p(panel.frame))
    outliers = _guard(panel, fit.std_residuals, guarded)
    pool: np.ndarray | None
    reason = None
    try:
        pool = np.asarray(residual_pool(fit, restandardize=True, min_rows=MIN_POOL_ROWS))
    except ValueError as exc:
        if fit.n_common_rows >= MIN_POOL_ROWS:
            raise ShapeError(f"the volatility model cannot use this menu: {exc}") from exc
        pool, reason = None, UNAVAILABLE_REASON
    long_run = garch11_long_run_variance(fit.omega, fit.alpha, fit.beta)
    return GarchArtifact(
        funds=tuple(fit.assets),
        rows=panel.rows,
        start=panel.start,
        end=panel.end,
        sample_sha256=panel.sample_sha256,
        mu=_frozen(fit.mu),
        omega=_frozen(fit.omega),
        alpha=_frozen(fit.alpha),
        beta=_frozen(fit.beta),
        nu=_frozen(fit.nu),
        status=tuple(str(status) for status in fit.status),
        messages=tuple(fit.messages),
        n_obs=tuple(int(count) for count in fit.n_obs),
        long_run_sigma_annual=_frozen(np.sqrt(TRADING_DAYS * long_run)),
        pool=None if pool is None else _frozen(pool),
        pool_rows=fit.n_common_rows,
        pool_sha256=None if pool is None else _pool_digest(pool),
        outliers=tuple(outliers),
        splice_dates=guarded,
        unavailable_reason=reason,
        qse=qse_commit(),
        arch=_arch_version(),
        returns=RETURNS,
    )


def guarded_splice_dates(
    funds: Sequence[str], splice_dates: Mapping[str, str] | None
) -> tuple[tuple[str, str], ...]:
    """The splice dates a fit of a panel of `funds` is guarded with: (fund, ISO day), sorted.

    Every day must be an ISO date (a malformed one is the caller's error, not a missing splice);
    a fund outside the panel has nothing to check and is left out. Two builds of one panel
    guard alike exactly when this is equal, which is what lets a fit be reused.
    """
    days = {
        str(fund): date.fromisoformat(day).isoformat() for fund, day in (splice_dates or {}).items()
    }
    members = {str(fund) for fund in funds}
    return tuple(sorted((fund, day) for fund, day in days.items() if fund in members))


def simulate_panel(
    artifact: GarchArtifact, paths: int = PATHS, horizon: int = HORIZON_DAYS, seed: int = SEED
) -> np.ndarray:
    """`paths` x `horizon` x N simulated daily log returns of the artifact's funds, float64.

    One pool row per (path, day) is the shock of every fund that day; each fund's recursion
    starts at its long-run variance. A fallback fund's shock is merely scaled by its constant
    volatility. Raises `ValueError` with the artifact's reason when it has no pool.
    """
    if artifact.pool is None:
        raise ValueError(artifact.unavailable_reason or "the volatility model has no pool")
    shocks = artifact.pool[draw_row_indices(artifact.pool_rows, paths, horizon, seed=seed)]
    return simulate_garch11(
        shocks,
        mu=artifact.mu,
        omega=artifact.omega,
        alpha=artifact.alpha,
        beta=artifact.beta,
        sigma2_init=garch11_long_run_variance(artifact.omega, artifact.alpha, artifact.beta),
        out=shocks,  # the gathered shocks are this call's own: the recursion overwrites them
    )


def artifact_to_json(artifact: GarchArtifact) -> dict:
    """The artifact's parameters and facts as plain JSON (the pool travels as `pool_bytes`)."""
    return {
        "name": METHOD_NAME,
        "funds": list(artifact.funds),
        "rows": artifact.rows,
        "start": artifact.start,
        "end": artifact.end,
        "sample_sha256": artifact.sample_sha256,
        **{name: _numbers(getattr(artifact, name)) for name in _PARAMETERS},
        "status": list(artifact.status),
        "messages": list(artifact.messages),
        "n_obs": list(artifact.n_obs),
        "pool_rows": artifact.pool_rows,
        "pool_sha256": artifact.pool_sha256,
        "outliers": [dict(entry) for entry in artifact.outliers],
        "splice_dates": dict(artifact.splice_dates),
        "unavailable_reason": artifact.unavailable_reason,
        "qse": artifact.qse,
        "arch": artifact.arch,
        "returns": artifact.returns,
    }


def artifact_from_json(doc: Mapping, pool: np.ndarray | None) -> GarchArtifact:
    """The artifact `artifact_to_json` described, with its pool; refuses a pool not its own, and
    a fit in another space than `RETURNS` (one written before the fit moved to log returns)."""
    if doc.get("name") != METHOD_NAME:
        raise ValueError(f"not a volatility model artifact: {doc.get('name')!r}")
    if doc.get("returns") != RETURNS:
        raise ValueError(f"an artifact's returns must be {RETURNS!r}, not {doc.get('returns')!r}")
    funds = tuple(str(fund) for fund in doc["funds"])
    arrays = {name: _array(doc[name]) for name in _PARAMETERS}
    lists = {name: list(doc[name]) for name in ("status", "messages", "n_obs")}
    if any(len(values) != len(funds) for values in [*arrays.values(), *lists.values()]):
        raise ValueError("an artifact holds one entry per fund")
    stored = {str(fund): str(day) for fund, day in doc["splice_dates"].items()}
    splices = guarded_splice_dates(funds, stored)
    if dict(splices) != stored:
        raise ValueError("the splice dates are not in the form an artifact stores them")
    expected = doc["pool_sha256"]
    shape = (int(doc["pool_rows"]), len(funds))
    own = pool is not None and pool.shape == shape and _pool_digest(pool) == expected
    if (expected is None) != (pool is None) or (pool is not None and not own):
        raise ValueError("the pool does not match the artifact it was stored with")
    return GarchArtifact(
        funds=funds,
        rows=int(doc["rows"]),
        start=str(doc["start"]),
        end=str(doc["end"]),
        sample_sha256=str(doc["sample_sha256"]),
        **arrays,
        status=tuple(str(status) for status in lists["status"]),
        messages=tuple(str(message) for message in lists["messages"]),
        n_obs=tuple(int(count) for count in lists["n_obs"]),
        pool=None if pool is None else _frozen(pool),
        pool_rows=shape[0],
        pool_sha256=expected,
        outliers=tuple(
            {"id": str(o["id"]), "date": str(o["date"]), "z": float(o["z"])}
            for o in doc["outliers"]
        ),
        splice_dates=splices,
        unavailable_reason=doc["unavailable_reason"],
        qse=str(doc["qse"]),
        arch=str(doc["arch"]),
        returns=RETURNS,
    )


def pool_bytes(artifact: GarchArtifact) -> bytes:
    """The artifact's pool as `.npy` bytes (no pickling), for storage beside its JSON."""
    if artifact.pool is None:
        raise ValueError("this artifact has no pool: the volatility model was unavailable")
    buffer = io.BytesIO()
    np.save(buffer, np.ascontiguousarray(artifact.pool, dtype="<f8"), allow_pickle=False)
    return buffer.getvalue()


def pool_from_bytes(data: bytes) -> np.ndarray:
    """A pool read back from `pool_bytes`; refuses pickled objects and anything not 2-D float64."""
    pool = np.load(io.BytesIO(data), allow_pickle=False)
    if pool.ndim != 2 or pool.dtype != np.float64:
        raise ValueError("a pool is a 2-D float64 array")
    return _frozen(pool)


@lru_cache(maxsize=1)
def qse_commit() -> str:
    """The QSE commit the copied files come from, as `qse/qse.lock.json` records it.

    `qse` is a namespace package (QSE has no `qse/__init__.py`), so the lock is found next to the
    regular package `qse.distributions`, which works for editable, wheel and image installs alike.
    """
    lock = resources.files("qse.distributions").joinpath("..", "qse.lock.json")
    return str(json.loads(lock.read_text(encoding="utf-8"))["commit"])


def garch_method(artifact: GarchArtifact) -> dict:
    """The tensor's `engines.garch.method` block for figures simulated from `artifact`."""
    return {
        "name": METHOD_NAME,
        "paths": PATHS,
        "horizon_days": HORIZON_DAYS,
        "seed": SEED,
        "start": START,
        "shape_rows": SHAPE_ROWS,
        "returns": RETURNS,
        "scale": SCALE,
        "ruin": RUIN,
        "qse": artifact.qse,
        "arch": artifact.arch,
    }


def _refuse_total_losses(panel: ShapePanel) -> None:
    """A daily return at or below -100% has no log return: the fit fails naming fund and day."""
    lost = np.argwhere(panel.frame.to_numpy() <= -1.0)  # a missing return is never a loss
    if lost.size:
        row, n = (int(k) for k in lost[0])
        fund = str(panel.frame.columns[n])
        day = [stamp.date().isoformat() for stamp in panel.frame.index][row]
        message = f"{fund} lost everything on {day}: a daily return at or below -100%"
        raise ShapeError(f"{message} has no log return to fit", fund, day)


def _guard(panel: ShapePanel, z: np.ndarray, splice_dates: Sequence[tuple[str, str]]) -> list[dict]:
    """The splice guard (spec 4.3), then every |z| above `OUTLIER_Z` as `{"id", "date", "z"}`.

    A missing corporate action is the fund's alone; a crash moves the menu. So a fund whose
    residual on its own splice date exceeds 6 and sits more than 6 from the median of the other
    funds' residuals that day fails. Every other large residual is recorded and fails nothing,
    including one on a splice date no other fund has a residual for: nothing shows it apart.
    """
    funds = [str(fund) for fund in panel.frame.columns]
    days = [stamp.date().isoformat() for stamp in panel.frame.index]
    row_of = {day: row for row, day in enumerate(days)}
    for fund, day in splice_dates:  # `guarded_splice_dates`: the panel's funds, ISO days
        if day not in row_of:
            continue
        n, row = funds.index(fund), row_of[day]
        own = float(z[row, n])
        if not abs(own) > OUTLIER_Z:  # also a day the fund has no residual
            continue
        others = np.delete(z[row], n)
        others = others[np.isfinite(others)]
        if others.size == 0:  # the second condition cannot be shown: recorded below
            continue
        centre = float(np.median(others))
        if abs(own - centre) > OUTLIER_Z:
            message = (
                f"{fund} moved {own:+.1f} standard deviations on {day}, the day its price history "
                f"was spliced, while the rest of the menu moved {centre:+.1f}"
            )
            raise ShapeError(f"{message}: the history may miss a corporate action", fund, day)
    large = np.argwhere(np.abs(z) > OUTLIER_Z)  # a missing residual is never large
    return [{"id": funds[n], "date": days[row], "z": float(z[row, n])} for row, n in large]


def _arch_version() -> str:
    """The `arch` version the fit just ran on. QSE's fitter imports `arch` (and statsmodels with
    it) only to fit; importing it here too, not at the top, keeps it out of every process that
    imports the engine without fitting: the build's worker processes, the API."""
    import arch

    return str(arch.__version__)


def _pool_digest(pool: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(pool, dtype="<f8").tobytes()).hexdigest()


def _frozen(values) -> np.ndarray:
    array = np.array(values, dtype=np.float64)
    array.setflags(write=False)
    return array


def _numbers(values: np.ndarray) -> list[float | None]:
    return [None if np.isnan(value) else float(value) for value in values]


def _array(values: Sequence[float | None]) -> np.ndarray:
    return _frozen([np.nan if value is None else float(value) for value in values])
