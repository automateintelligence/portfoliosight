"""Build one tensor (spec 7; simulation engines spec 7) from prepared inputs.

`build_tensor` is the engine's entry point. It reads nothing and writes nothing: the caller
hands it the menu's returns and catalog facts and stores the document it returns. Building twice
from the same inputs gives the same document apart from the telemetry fields `built_at` and
`build_seconds`. `build_tensor_full` returns the same document with the range models and the
fitted artifacts behind it, for a caller that stores the artifacts or answers ranges later.

Every build computes History replay, the default engine, whose figures fill the fields older
readers know (`frontier.range`, `ladder.range`, `entered.range`, `range_method`). The engines
the inputs ask for (`replay` and `garch` unless told otherwise) each add their own figures under
`ranges`; `engines` says, for every engine the page offers, whether the tensor carries it and if
not why.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from importlib import resources

import jsonschema
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from portfoliosight.cpus import build_workers

from . import ENGINE_VERSION
from .caps import RULE, requested_caps, resolve_bounds
from .invariants import TOL, InvariantError, check_floor, check_risk_line, check_weights
from .ladder import LEVELS, EnbProgram
from .optimize import NX, Frontier, MenuPrograms, frontier
from .ranges import (
    DEFAULT_ENGINE,
    ENGINES,
    METHOD,
    GarchRangeModel,
    RangeModel,
    frame_digest,
    garch_range_model,
    one_year_ranges,
    range_model,
)
from .shape import (
    GarchArtifact,
    fit_shape,
    garch_method,
    guarded_splice_dates,
    shape_panel,
    simulate_panel,
)
from .stats import (
    EW_HALFLIFE_DAYS,
    ROUNDING_NOISE,
    estimate_moments,
    menu_beta_blend,
    risk_free_rate,
)
from .stress import segments_from_returns, stress_returns
from .suggest import DEFAULT_POINT, balanced_level, suggested_level
from .surface import NY, Raster, Surface, frontier_curve, raster, s_safe, surface
from .torsion import torsion_basis
from .windows import WindowSelection, renormalize_allocation, select_window

SCHEMA_VERSION = 3
HASH_SCHEMA = 2  # the universe hash's own version: a menu keeps its key across tensor schemas
TELEMETRY_FIELDS = ("built_at", "build_seconds")
NOTES = (
    "Expected returns are a 50/50 blend of the sample mean and a menu-beta heuristic.",
    "Every mix below the frontier has exactly its column's risk and is the most diversified "
    "mix found at that risk for its return level: a local search from several starting points, "
    "not a proof that no better mix exists.",
    "The balanced point is where, going down the column, diversification stops rising faster "
    "than return falls, each measured as a share of what the column offers; the peak is the "
    "most diversified mix found at that risk.",
    "One-year ranges are the 2.5th, 50th and 97.5th percentiles of 2,000 one-year paths "
    "resampled from the mix's own daily history in runs averaging 21 days, recentred on the "
    "expected return, at constant weights.",
)
EW_NOTE = (
    "In the recent-weighted view the weights set each range's centre; its shape comes from the "
    "same five years of daily history, unweighted."
)
# One sentence for each simulation engine a tensor carries beyond History replay, whose own
# sentence is the last of NOTES. They start "One-year ranges" like it (the page's details leave
# such sentences to the Method line).
ENGINE_NOTES = {
    "garch": (
        "One-year ranges under the volatility model are the same percentiles of 2,000 one-year "
        "paths in which each fund's volatility follows the pattern fitted to up to ten years of "
        "its daily history and the funds' shocks are replayed together from days they all "
        "share, centred and scaled to this view's expected return and risk."
    ),
}
EW_ENGINE_NOTES = {
    "garch": (
        "One-year ranges under the volatility model take their centre and their risk from the "
        "recent-weighted view and their shape from the same ten years as every other view."
    ),
}
FIGURES = ("bad", "typical", "good")  # an engine's own figures; the normal range is shared
NOT_COMPUTED = "not computed for this menu"
NOT_COMPUTED_CUSTOM = "not computed for custom menus"
COPULA = {"status": "unavailable", "reason": NOT_COMPUTED, "method": None}


@dataclass(frozen=True)
class FundInput:
    """What the catalog knows about one fund of the menu."""

    id: str
    name: str
    kind: str  # etf | mutual_fund | stock | tsp
    source: str  # seed | tiingo | tsp | seed+tiingo | lake
    adjusted_through: str  # ISO date the corporate actions are verified through
    fetched_at: str  # ISO timestamp of the last provider fetch
    last_close: float | None = None  # raw close on asof, None when unknown
    served: bool = True
    catalog_reason: str | None = None  # the catalog's own reason when not served


@dataclass(frozen=True)
class TensorInputs:
    """Everything one build needs. `returns` may hold more columns than the menu."""

    funds: Sequence[FundInput]  # the menu, in display order
    returns: pd.DataFrame  # the returns-parquet frame: DatetimeIndex, one column per fund
    lookback: str
    asof: date | str  # the generation's D_G; rows after it are never used
    universe_name: str
    preset_id: str | None = None
    requested_bounds: Sequence[Mapping[str, object]] | None = None  # [{"id", "min", "max"}]
    tr_index: Mapping[str, pd.Series] | None = None  # for stress; else rebuilt from returns
    rf_series: Mapping[str, pd.Series] | None = None  # served SGOV / TSP-G daily returns
    xnys_sessions: Sequence | None = None  # for the stress three-session rule; default XNYS
    allocation: Mapping[str, float] | None = None  # the entered mix, amounts by fund id
    engine_version: str = ENGINE_VERSION
    nx: int = NX
    ny: int = NY
    levels: int = LEVELS
    engines: tuple[str, ...] = ENGINES  # what to compute; History replay always
    splice_dates: Mapping[str, str] | None = None  # ISO day each seeded fund's tail starts
    garch_artifact: GarchArtifact | None = None  # reused for its own panel and splice dates


@dataclass(frozen=True)
class BuildResult:
    """A tensor with the range models behind its figures and the artifacts fitted for it."""

    tensor: dict
    models: dict[str, RangeModel | GarchRangeModel]  # by engine, for each engine it carries
    artifacts: dict[str, GarchArtifact]  # by engine, for each engine whose fit ran


class WindowUnavailable(ValueError):
    """The window has no usable sample; `reason` is the sentence the page shows."""

    def __init__(self, selection: WindowSelection):
        super().__init__(f"the {selection.lookback} window is unavailable: {selection.message}")
        self.selection = selection
        self.reason = selection.message


def universe_hash(funds: Sequence[Mapping[str, object]]) -> str:
    """16 hex digits identifying a menu and its requested caps (spec 6), whatever the order.

    `funds` are `{"id", "min", "max"}` with `None` for a default bound. The hash covers the
    requested policy only, never a lookback or the window-resolved bounds.
    """
    rows = [{"id": str(f["id"]), "min": f.get("min"), "max": f.get("max")} for f in funds]
    rows.sort(key=lambda row: row["id"])
    canonical = json.dumps(
        {"schema": HASH_SCHEMA, "funds": rows}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def canonical_json(tensor: Mapping) -> str:
    """The stored form: sorted keys, no whitespace, floats at full `repr` precision, no NaN."""
    return json.dumps(tensor, separators=(",", ":"), sort_keys=True, allow_nan=False)


@lru_cache(maxsize=1)
def load_schema() -> dict:
    """The tensor's JSON Schema, shipped next to this module."""
    schema = resources.files("portfoliosight.engine").joinpath("tensor.schema.json")
    return json.loads(schema.read_text(encoding="utf-8"))


def validate_tensor(tensor: Mapping) -> None:
    """Raise `jsonschema.ValidationError` unless `tensor` matches the schema."""
    jsonschema.Draft202012Validator(load_schema()).validate(tensor)


def build_tensor(inputs: TensorInputs, *, workers: int | None = None) -> dict:
    """Compute the tensor of one (menu, lookback, asof).

    Raises `WindowUnavailable` when the window has too little shared history, `CapsError` when
    the requested caps cannot be met by the funds included in the window, `ShapeError` when the
    volatility model cannot use the menu's history (a fund's splice date shows a move the rest of
    the menu did not make, or the shared days say nothing about a fund that varies),
    `TorsionError` when the funds' correlation matrix is singular (every varying fund switching
    between two values in lockstep leaves Ledoit-Wolf nothing to shrink; nothing is
    regularized), `ValueError` for an engine it cannot compute, and an error from the post-check
    when any computed mix breaks an invariant.

    A build is thousands of small matrix operations, where BLAS threads only get in each
    other's way; they are held to one for its duration. The risk columns' ladders are solved on
    `workers` processes, by default as many as the host lets this process use
    (`portfoliosight.cpus.build_workers`); the tensor is the same whatever the number. The
    volatility model is fitted and simulated once, in the build's own process.
    """
    return build_tensor_full(inputs, workers=workers).tensor


def build_tensor_full(inputs: TensorInputs, *, workers: int | None = None) -> BuildResult:
    """`build_tensor`, with the range models and the fitted artifacts behind the tensor."""
    count = build_workers() if workers is None else workers
    with threadpool_limits(limits=1, user_api="blas"):
        return _build(inputs, count)


def _build(inputs: TensorInputs, workers: int) -> BuildResult:
    started = time.perf_counter()
    engines = _engines(inputs.engines)
    funds = list(inputs.funds)
    ids = [fund.id for fund in funds]
    if len(set(ids)) != len(ids):
        raise ValueError("a fund is listed more than once in the menu")
    by_id = {fund.id: fund for fund in funds}
    requested = requested_caps(ids, inputs.requested_bounds)
    asof = pd.Timestamp(inputs.asof)
    if not isinstance(asof, pd.Timestamp):
        raise ValueError("asof must be a date")
    asof_iso = asof.date().isoformat()

    frame = inputs.returns.reindex(columns=ids)
    catalog = {
        fund.id: {
            "status": "ok" if fund.served else "unserved",
            "reason": fund.catalog_reason,
            "adjusted_through": fund.adjusted_through,
        }
        for fund in funds
    }
    selection = select_window(frame, inputs.lookback, asof, catalog)
    if selection.sample is None:
        raise WindowUnavailable(selection)
    included = selection.funds
    sample = selection.sample.to_numpy()
    lo, hi = resolve_bounds(
        included, [{"id": fund, **requested[fund]} for fund in included if fund in requested]
    )

    moments = estimate_moments(sample, selection.omega)
    rf = risk_free_rate(
        {symbol: series.loc[:asof] for symbol, series in (inputs.rf_series or {}).items()}
    )
    mu_s, _ = menu_beta_blend(moments.mu, moments.cov, rf)
    artifact = None
    if "garch" in engines:  # fitted before the ladders: a history it cannot use fails at once
        panel = shape_panel(frame, included, asof)
        given = inputs.garch_artifact
        reuse = (  # the same panel, guarded with the same splice dates: the guard has run on it
            given is not None
            and given.sample_sha256 == panel.sample_sha256
            and given.splice_dates == guarded_splice_dates(included, inputs.splice_dates)
        )
        artifact = given if reuse else fit_shape(panel, inputs.splice_dates)
    basis = torsion_basis(moments.cov)
    programs = MenuPrograms(mu_s, moments.cov, lo, hi)
    front = frontier(programs, inputs.nx, workers)
    program = EnbProgram(mu_s, moments.cov, lo, hi, basis)
    surf = surface(program, programs, front, inputs.levels, workers)
    grid = raster(surf, front, program, inputs.ny)
    _post_check(program, front, surf, grid)
    last = surf.y.shape[1] - 1
    balanced = [balanced_level(surf.y[j], surf.z[j]) for j in range(inputs.nx)]
    suggested = [suggested_level(surf.y[j], surf.z[j], DEFAULT_POINT) for j in range(inputs.nx)]
    curve_sigma, curve_mu = frontier_curve(front.w, mu_s, moments.cov)
    no_limits = frontier(
        MenuPrograms(mu_s, moments.cov, np.zeros(len(mu_s)), np.ones(len(mu_s))),
        inputs.nx,
        workers,
    )
    models: dict[str, RangeModel | GarchRangeModel] = {
        "replay": range_model(sample, mu_s, moments.cov)
    }
    if artifact is not None and artifact.pool is not None:
        models["garch"] = garch_range_model(simulate_panel(artifact), mu_s, moments.cov)
    mixes = surf.w.reshape(-1, len(mu_s))
    computed = {engine: one_year_ranges(model, mixes) for engine, model in models.items()}
    for engine, ranges in computed.items():
        _check_ranges(engine, ranges, "ladder", surf.y.shape)
    ladder_range = _range_block(computed[DEFAULT_ENGINE], surf.y.shape)
    front_range = _column(ladder_range, 0)
    ladder_ranges = {engine: _figures(r, surf.y.shape) for engine, r in computed.items()}
    front_ranges = {
        engine: {"s_safe": s_safe(_column(block, 0)["bad"]), **_column(block, 0)}
        for engine, block in ladder_ranges.items()
    }

    history = frame.loc[frame.index <= asof]
    tr_index: dict[str, pd.Series | list[pd.Series]] = {}
    for fund in included:
        given = None if inputs.tr_index is None else inputs.tr_index.get(fund)
        if given is None:
            tr_index[fund] = segments_from_returns(history[fund])
        else:
            tr_index[fund] = given.loc[given.index <= asof]

    default = {"min": None, "max": None}
    tensor = {
        "schema": SCHEMA_VERSION,
        "engine_version": inputs.engine_version,
        "generation": f"{asof_iso}-{inputs.engine_version}",
        "asof": asof_iso,
        "frontier_curve": {"sigma": curve_sigma.tolist(), "mu": curve_mu.tolist()},
        "frontier_uncapped": {"sigma": no_limits.x.tolist(), "mu": no_limits.y.tolist()},
        "universe": {
            "hash": universe_hash([{"id": i, **requested.get(i, default)} for i in ids]),
            "name": inputs.universe_name,
            "preset_id": inputs.preset_id,
            "funds": [
                {
                    "id": fund,
                    "name": by_id[fund].name,
                    "kind": by_id[fund].kind,
                    "source": by_id[fund].source,
                    "adjusted_through": by_id[fund].adjusted_through,
                    "fetched_at": by_id[fund].fetched_at,
                    "last_close": _number_or_none(by_id[fund].last_close),
                }
                for fund in included
            ],
            "excluded": [
                {
                    "id": entry["id"],
                    "reason": entry["reason"],
                    "last_close": _number_or_none(by_id[entry["id"]].last_close),
                }
                for entry in selection.excluded
            ],
        },
        "lookback": {
            "id": selection.lookback,
            "start": str(selection.start),
            "end": selection.end.isoformat(),
            "rows": selection.rows,
            "t_eff": float(moments.t_eff),
            "ew_halflife_days": None if selection.omega is None else EW_HALFLIFE_DAYS,
            "sample_sha256": frame_digest(selection.sample),
        },
        "rf": rf,
        "mu_s": mu_s.tolist(),
        "mu_sample": moments.mu.tolist(),
        "sigma": moments.sigma.tolist(),
        "cov": moments.cov.tolist(),
        "torsion": basis.t.tolist(),
        "torsion_inv_t": basis.inv_t.tolist(),
        "torsion_lambda": basis.lam.tolist(),
        "bounds": {
            "requested": [dict(requested.get(fund, default)) for fund in included],
            "min": lo.tolist(),
            "max": hi.tolist(),
            "rule": RULE,
        },
        "frontier": {
            "x": front.x.tolist(),
            "y": front.y.tolist(),
            "w": front.w.tolist(),
            "s_safe": s_safe(front_range["bad"]),
            "range": front_range,
            "ranges": front_ranges,
        },
        "ladder": {
            "y": surf.y.tolist(),
            "z": surf.z.tolist(),
            "w": surf.w.tolist(),
            "hop": surf.hop.tolist(),
            "collapsed": [bool(flag) for flag in surf.collapsed],
            "t_balanced": [level / last for level in balanced],
            "y_balanced": [float(surf.y[j, level]) for j, level in enumerate(balanced)],
            "default_point": DEFAULT_POINT,
            "t_suggested": [level / last for level in suggested],
            "y_suggested": [float(surf.y[j, level]) for j, level in enumerate(suggested)],
            "range": ladder_range,
            "ranges": ladder_ranges,
        },
        "grid": {
            "y": grid.y.tolist(),
            "z": [[None if np.isnan(v) else float(v) for v in column] for column in grid.z],
            "w": [[None if mix is None else mix.tolist() for mix in column] for column in grid.w],
            "k_div": [int(k) for k in grid.k_div],
            "y_div": grid.y_div.tolist(),
            "w_div": surf.w[:, -1].tolist(),
            "y_sug": [
                float(grid.y_div[j] if level == last else surf.y[j, level])
                for j, level in enumerate(suggested)
            ],
        },
        "entered": _entered(inputs.allocation, included, models),
        "range_method": dict(METHOD),
        "engines": _engines_block(artifact, inputs.preset_id),
        "range_default": DEFAULT_ENGINE,
        "shape": None if artifact is None else _shape_block(artifact),
        "enb_ref": surf.enb_ref,
        "stress": stress_returns(tr_index, inputs.xnys_sessions),
        "notes": _notes(models, weighted=selection.omega is not None),
    }
    tensor["built_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    tensor["build_seconds"] = round(time.perf_counter() - started, 3)
    validate_tensor(tensor)
    artifacts = {} if artifact is None else {"garch": artifact}
    return BuildResult(tensor=tensor, models=models, artifacts=artifacts)


def _engines(asked: Sequence[str]) -> tuple[str, ...]:
    """The engines to compute, in `ENGINES` order; the default engine is always among them."""
    unknown = [engine for engine in asked if engine not in ENGINES]
    if unknown:
        raise ValueError(f"unknown engine {unknown[0]!r}: a build computes {', '.join(ENGINES)}")
    if DEFAULT_ENGINE not in asked:
        raise ValueError(f"every build computes {DEFAULT_ENGINE}, the default engine")
    return tuple(engine for engine in ENGINES if engine in asked)


def _engines_block(artifact: GarchArtifact | None, preset_id: str | None) -> dict:
    """`engines`: every engine the page offers, with its status, its reason and its method.

    The volatility model has no artifact exactly when the build was not asked for it.
    """
    if artifact is None:
        reason = NOT_COMPUTED_CUSTOM if preset_id is None else NOT_COMPUTED
        garch: dict = {"status": "unavailable", "reason": reason, "method": None}
    elif artifact.pool is None:
        garch = {"status": "unavailable", "reason": artifact.unavailable_reason, "method": None}
    else:
        garch = {"status": "ready", "reason": None, "method": garch_method(artifact)}
    replay = {"status": "ready", "reason": None, "method": dict(METHOD)}
    return {"replay": replay, "garch": garch, "copula": dict(COPULA)}


def _shape_block(artifact: GarchArtifact) -> dict:
    """`shape`: the fitted volatility model as the tensor reports it (simulation engines spec 7)."""

    def number(value: float) -> float | None:
        return None if np.isnan(value) else float(value)

    funds = [
        {
            "id": fund,
            "status": artifact.status[n],
            "rows": artifact.n_obs[n],
            "mu": float(artifact.mu[n]),
            "omega": float(artifact.omega[n]),
            "alpha": float(artifact.alpha[n]),
            "beta": float(artifact.beta[n]),
            "nu": number(artifact.nu[n]),
            "long_run_sigma_annual": float(artifact.long_run_sigma_annual[n]),
            "margin": None,
        }
        for n, fund in enumerate(artifact.funds)
    ]
    return {
        "rows": artifact.rows,
        "start": artifact.start,
        "end": artifact.end,
        "sample_sha256": artifact.sample_sha256,
        "pool_rows": artifact.pool_rows,
        "funds": funds,
        "outliers": [dict(entry) for entry in artifact.outliers],
        "lower_tail_5pct": None,
        "tree_loglik_share": None,
    }


def _notes(models: Mapping[str, object], *, weighted: bool) -> list[str]:
    carried = [ENGINE_NOTES[engine] for engine in models if engine in ENGINE_NOTES]
    if not weighted:
        return [*NOTES, *carried]
    return [
        *NOTES,
        *carried,
        EW_NOTE,
        *(EW_ENGINE_NOTES[e] for e in models if e in EW_ENGINE_NOTES),
    ]


def _post_check(program: EnbProgram, front: Frontier, surf: Surface, grid: Raster) -> None:
    """Every vector the tensor will carry meets the 1e-6 invariants, or the build fails.

    A ladder is also checked for what it promises by construction: it starts at the frontier
    mix, every mix has the column's risk and earns its level's return, ENB never falls and
    return never rises on the way down.
    """
    lo, hi, cov, mu = program.lo, program.hi, program.cov, program.mu
    levels = surf.y.shape[1]
    for j, risk in enumerate(front.x):
        check_weights(front.w[j], lo=lo, hi=hi, cov=cov, ceiling=risk, enb=surf.z[j, 0])
        if not np.array_equal(surf.w[j, 0], front.w[j]):
            raise InvariantError("ladder", f"column {j} does not start at its frontier mix")
        floors = np.linspace(surf.y[j, 0], surf.y[j, -1], levels)
        for level in range(levels):
            mix = surf.w[j, level]
            check_weights(mix, lo=lo, hi=hi, cov=cov, ceiling=risk, enb=surf.z[j, level])
            check_risk_line(mix, cov=cov, risk=risk)
            check_floor(mix, mu=mu, floor=floors[level])
        if (np.diff(surf.z[j]) < 0).any() or (np.diff(surf.y[j]) > TOL).any():
            raise InvariantError("ladder", f"column {j} is not monotone from frontier to peak")
        for k, mix in enumerate(grid.w[j]):
            if mix is not None:
                check_weights(mix, lo=lo, hi=hi, cov=cov, ceiling=risk, enb=grid.z[j, k])
                check_floor(mix, mu=mu, floor=grid.y[k])


def _check_ranges(engine: str, ranges: Mapping, where: str, shape: tuple[int, ...]) -> None:
    """Every carried mix's bad year is below its typical year, and that below its good year.

    A riskless mix (one whose simulated days do not vary) has one year on every path: its three
    figures may then agree to rounding, and nothing else may. A NaN fails.
    """
    bad, typical, good = (np.asarray(ranges[name], dtype=float) for name in FIGURES)
    ordered = (bad < typical) & (typical < good)
    width = ROUNDING_NOISE * np.maximum(1.0, np.abs(good))
    point = (bad <= typical) & (typical <= good) & (good - bad <= width)
    broken = np.flatnonzero(~(ordered | point))
    if broken.size:
        i = int(broken[0])
        at = ", ".join(str(int(k)) for k in np.unravel_index(i, shape))
        detail = f"bad {bad[i]!r}, typical {typical[i]!r}, good {good[i]!r} are out of order"
        raise InvariantError("range", f"{engine} {where} mix ({at}): {detail}")


def _range_block(ranges: Mapping, shape: tuple[int, ...]) -> dict:
    """The tensor form of `one_year_ranges`: nested lists of `shape`, plain floats for `()`."""
    return {
        **_figures(ranges, shape),
        "normal": {name: _laid_out(values, shape) for name, values in ranges["normal"].items()},
    }


def _figures(ranges: Mapping, shape: tuple[int, ...]) -> dict:
    """An engine's own figures (`ranges.<engine>`): bad, typical and good, laid out as `shape`."""
    return {name: _laid_out(ranges[name], shape) for name in FIGURES}


def _laid_out(values, shape: tuple[int, ...]) -> object:
    return np.asarray(values, dtype=float).reshape(shape).tolist()


def _column(block: Mapping, level: int) -> dict:
    """One ladder level of a range block across all columns (level 0 is the frontier mix)."""

    def pick(rows) -> list:
        return [row[level] for row in rows]

    picked: dict = {name: pick(block[name]) for name in FIGURES}
    if "normal" in block:
        picked["normal"] = {name: pick(rows) for name, rows in block["normal"].items()}
    return picked


def _entered(
    allocation: Mapping[str, float] | None,
    included: Sequence[str],
    models: Mapping[str, RangeModel | GarchRangeModel],
) -> dict | None:
    """The entered mix over the included funds, with its one-year ranges; `None` without one."""
    if allocation is None:
        return None
    weights, set_aside = renormalize_allocation(allocation, included)
    if weights is None:
        return None
    mix = np.array([weights.get(fund, 0.0) for fund in included])
    computed = {engine: one_year_ranges(model, mix) for engine, model in models.items()}
    for engine, ranges in computed.items():
        _check_ranges(engine, ranges, "entered", (1,))
    return {
        "w": mix.tolist(),
        "set_aside": float(set_aside),
        "range": _range_block(computed[DEFAULT_ENGINE], ()),
        "ranges": {engine: _figures(ranges, ()) for engine, ranges in computed.items()},
    }


def _number_or_none(value: float | None) -> float | None:
    return None if value is None else float(value)
