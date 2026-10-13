"""Build one tensor (spec 7) from prepared inputs.

`build_tensor` is the engine's entry point. It reads nothing and writes nothing: the caller
hands it the menu's returns and catalog facts and stores the document it returns. Building twice
from the same inputs gives the same document apart from the telemetry fields `built_at` and
`build_seconds`.
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

from . import ENGINE_VERSION
from .caps import RULE, CapsError, resolve_bounds
from .invariants import check_floor, check_weights
from .optimize import NX, Frontier, MenuPrograms, frontier
from .stats import EW_HALFLIFE_DAYS, estimate_moments, menu_beta_blend, risk_free_rate
from .stress import stress_returns
from .suggest import suggested_floor
from .surface import NY, Surface, frontier_curve, s_safe, surface
from .torsion import TorsionBasis, enb, torsion_basis
from .windows import WindowSelection, select_window

SCHEMA_VERSION = 2
TELEMETRY_FIELDS = ("built_at", "build_seconds")
NOTES = (
    "Expected returns are a 50/50 blend of the sample mean and a menu-beta heuristic.",
    "The suggested point is the lowest return floor whose give-up versus the frontier mix is "
    "within one standard error of the paired daily return difference (a heuristic, not a "
    "significance test).",
)


@dataclass(frozen=True)
class FundInput:
    """What the catalog knows about one fund of the menu."""

    id: str
    name: str
    kind: str  # etf | mutual_fund | stock | tsp
    source: str  # seed | tiingo | tsp | seed+tiingo
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
    tr_index: Mapping[str, pd.Series] | None = None  # for stress; else cumulated from returns
    rf_series: Mapping[str, pd.Series] | None = None  # served SGOV / TSP-G daily returns
    xnys_sessions: Sequence | None = None  # for the stress three-session rule; default XNYS
    engine_version: str = ENGINE_VERSION
    nx: int = NX
    ny: int = NY


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
        {"schema": SCHEMA_VERSION, "funds": rows}, sort_keys=True, separators=(",", ":")
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


def build_tensor(inputs: TensorInputs) -> dict:
    """Compute the tensor of one (menu, lookback, asof).

    Raises `WindowUnavailable` when the window has too little shared history, `CapsError` when
    the requested caps cannot be met by the funds included in the window, and an error from the
    post-check when any computed mix breaks an invariant.
    """
    started = time.perf_counter()
    funds = list(inputs.funds)
    ids = [fund.id for fund in funds]
    if len(set(ids)) != len(ids):
        raise ValueError("a fund is listed more than once in the menu")
    by_id = {fund.id: fund for fund in funds}
    requested = _requested_by_id(inputs.requested_bounds, by_id)
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
    basis = torsion_basis(moments.cov)
    programs = MenuPrograms(mu_s, moments.cov, lo, hi)
    front = frontier(programs, inputs.nx)
    surf = surface(programs, front, basis, inputs.ny)
    _post_check(programs, front, surf, basis)
    y_sug = _suggested_floors(front, surf, mu_s, sample, selection.omega)
    curve_sigma, curve_mu = frontier_curve(front.w, mu_s, moments.cov)

    history = frame.loc[frame.index <= asof]
    tr_index = {}
    for fund in included:
        given = None if inputs.tr_index is None else inputs.tr_index.get(fund)
        if given is None:
            tr_index[fund] = (1.0 + history[fund].dropna()).cumprod()
        else:
            tr_index[fund] = given.loc[given.index <= asof]

    default = {"min": None, "max": None}
    tensor = {
        "schema": SCHEMA_VERSION,
        "engine_version": inputs.engine_version,
        "generation": f"{asof_iso}-{inputs.engine_version}",
        "asof": asof_iso,
        "frontier_curve": {"sigma": curve_sigma.tolist(), "mu": curve_mu.tolist()},
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
            "s_safe": s_safe(curve_sigma, curve_mu),
        },
        "grid": {
            "y": surf.y.tolist(),
            "z": [[None if np.isnan(v) else float(v) for v in column] for column in surf.z],
            "w": [[None if mix is None else mix.tolist() for mix in column] for column in surf.w],
            "k_div": [int(k) for k in surf.k_div],
            "y_div": surf.y_div.tolist(),
            "w_div": surf.w_div.tolist(),
            "y_sug": y_sug,
        },
        "enb_ref": surf.enb_ref,
        "stress": stress_returns(tr_index, inputs.xnys_sessions),
        "notes": list(NOTES),
    }
    tensor["built_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    tensor["build_seconds"] = round(time.perf_counter() - started, 3)
    validate_tensor(tensor)
    return tensor


def _requested_by_id(
    requested: Sequence[Mapping[str, object]] | None, menu: Mapping[str, FundInput]
) -> dict[str, dict[str, object]]:
    """Requested caps keyed by fund id; every entry must name a fund of the menu, once."""
    by_id: dict[str, dict[str, object]] = {}
    for entry in requested or ():
        fund = entry.get("id")
        if not isinstance(fund, str):
            raise CapsError("every cap entry needs a fund id")
        if fund not in menu:
            raise CapsError(f"{fund}: not a fund of this menu")
        if fund in by_id:
            raise CapsError(f"{fund}: capped more than once")
        by_id[fund] = {"min": entry.get("min"), "max": entry.get("max")}
    return by_id


def _post_check(
    programs: MenuPrograms, front: Frontier, surf: Surface, basis: TorsionBasis
) -> None:
    """Every vector the tensor will carry meets the 1e-6 invariants, or the build fails."""
    lo, hi, cov = programs.lo, programs.hi, programs.cov
    for j, ceiling in enumerate(front.x):
        check_weights(front.w[j], lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=surf.enb_front[j])
        for k, mix in enumerate(surf.w[j]):
            if mix is not None:
                check_weights(mix, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=surf.z[j, k])
                check_floor(mix, mu=programs.mu, floor=surf.y[k])
        diversified = surf.w_div[j]
        check_weights(
            diversified, lo=lo, hi=hi, cov=cov, ceiling=ceiling, enb=enb(diversified, cov, basis)
        )


def _suggested_floors(
    front: Frontier, surf: Surface, mu_s: np.ndarray, sample: np.ndarray, omega
) -> list[float]:
    """`y_sug` per column: the walk of spec 4.8 over the ladder from the top down to k_div."""
    floors = []
    for j in range(len(front.x)):
        ladder = [
            k
            for k in range(len(surf.y) - 1, surf.k_div[j] - 1, -1)
            if surf.k_div[j] >= 0 and surf.w[j][k] is not None
        ]
        floors.append(
            suggested_floor(
                front.w[j],
                float(front.y[j]),
                [surf.w[j][k] for k in ladder],
                [float(surf.y[k]) for k in ladder],
                mu_s,
                sample,
                omega,
            )
        )
    return floors


def _number_or_none(value: float | None) -> float | None:
    return None if value is None else float(value)
