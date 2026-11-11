"""Evaluation of locked selections and the outcomes table (protocol 5 step 8, 6 and 9).

Everything here happens after the lock (`research.selection`): it reads locked rows, draws the
independent banks and reads realized horizons. Nothing in the search or the selection imports it.

- `evaluate_group(task)` evaluates the locked rows of one (profile, menu, origin), which the
  runner reads once from the locked file (verified against its digest) and hands over with the
  origin model and the realized horizon; it never sees a search result. A reference locked as
  `infeasible` (equal weight above the cell's ceiling) keeps that status and is evaluated all the
  same; its row says so in `reference_infeasible`, beside its evaluated `train_status`. Each row
  is replayed on
  its own optimization bank (whose figures must equal the locked ones bit for bit,
  `InvarianceError` otherwise), on the five independent banks `TEST_SEEDS` one by one and pooled
  (10,000 outcomes; pooled within one optimizer seed's selection, never across optimizer seeds),
  and over the realized horizon; calibration is scored as pinball loss and `1[y <= f]` for each
  training and pooled-test quantile, and the PIT of the realized return among the pooled outcomes.
- `finish_outcomes(table, months)`: the outcomes table with the cross-row columns:
  `forecast_error` (realized annual return minus `mu_s'w`), `paired_realized_difference` (an
  `R+D` or `R+E` row's realized annual return minus `R`'s in the same cell), `turnover_prev`
  (`0.5 L1` to the same role at the previous scheduled origin, one per prescribed ceiling the row
  stands for) and `seed_l1` (L1 to the same role of each other optimizer seed).
- `forecast_error_diagnostic(frame)`: per menu and prescribed risk cell, the correlation across
  mature origins of `w_R`'s forecast error with the paired realized difference (protocol 6,
  mechanism (a)) and its sign. The block-bootstrap interval belongs to the report.

Realized definitions (`DEFINITIONS`, also written to the manifest): maximum drawdown
`max_t 1 - W_t / max(1, max_{s<=t} W_s)` along the 252-day wealth path; realized volatility
`sqrt(252)` times the ddof-1 standard deviation of the 252 daily returns.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa

from portfoliosight.engine import preference
from portfoliosight.research import evaluate
from portfoliosight.research.evaluate import COMPLETE, OK, Horizon, OriginModel
from portfoliosight.research.search import INFEASIBLE, PRIMARY_ALLOWANCE, InvarianceError
from portfoliosight.research.selection import LOCKED_SCHEMA, MEASURE_ARMS, PRIMARY_SEED

_F = pa.float64()
_I = pa.int64()
_S = pa.string()
_B = pa.bool_()
_D = pa.date32()
_FL = pa.list_(pa.float64())
_SL = pa.list_(pa.string())
_IL = pa.list_(pa.int64())

TEST_SEEDS = (20261113, 20261114, 20261115, 20261116, 20261117)  # protocol 5 step 8
QUANTILES = (("bad", 0.025), ("typical", 0.50), ("good", 0.975))

DEFINITIONS = {
    "annual_return": "prod_t(1 + sum_i w_i r_it) - 1 over the 252 horizon days, constant weights",
    "max_drawdown": "max_t 1 - W_t / max(1, max_{s<=t} W_s), W_t the wealth after day t",
    "volatility": "sqrt(252) * std(ddof=1) of the 252 daily portfolio returns",
    "es_25": "mean of the worst ceil(0.025 P) of P annual outcomes (50 of 2,000; 250 of 10,000)",
    "utility": "U = k_B B + k_T T + k_G G, k = (0.60, 0.30, 0.10) unless a profile says otherwise",
    "dr2": "(sum_i w_i sigma_i)^2 / (w' Sigma w), production estimate_moments, fixed window",
    "forecast_error": "realized annual return minus mu_s'w",
    "turnover_prev": "0.5 * L1(w_t - w_previous scheduled origin), same role, ceiling and seed",
}


_FIGURES = ("bad", "typical", "good", "utility", "mean", "es_25", "p_loss", "p_below_20")
OUTCOMES_SCHEMA = pa.schema(
    list(LOCKED_SCHEMA)
    + [
        ("train_status", _S),
        ("reference_infeasible", _B),  # locked infeasible (status), evaluated nonetheless
        ("train_paths", _I),
        ("train_p_loss", _F),
        ("train_p_below_20", _F),
        ("test_status", _S),
        ("test_paths", _I),
        *[(f"test_{name}", _F) for name in _FIGURES],
        ("bank_seeds", _IL),
        ("bank_index_sha256", _SL),
        *[(f"bank_{name}", _FL) for name in _FIGURES],
        ("realized_status", _S),
        ("horizon_start", _D),
        ("horizon_end", _D),
        ("realized_sha256", _S),
        ("annual_return", _F),
        ("loss", _B),
        ("below_20", _B),
        ("worst_day", _F),
        ("max_drawdown", _F),
        ("volatility", _F),
        ("forecast_error", _F),
        ("paired_role", _S),
        ("paired_realized_difference", _F),
        *[
            (f"{forecast}_{score}_{name}", _B if score == "at_or_below" else _F)
            for forecast in ("train", "test")
            for score in ("pinball", "at_or_below")
            for name, _ in QUANTILES
        ],
        ("test_pit", _F),
        ("turnover_prev", _FL),
        ("seed_l1_seeds", _IL),
        ("seed_l1", _FL),
    ]
)
CROSS_ROW = (
    "forecast_error",
    "paired_role",
    "paired_realized_difference",
    "turnover_prev",
    "seed_l1_seeds",
    "seed_l1",
)
EVALUATED_SCHEMA = pa.schema([f for f in OUTCOMES_SCHEMA if f.name not in CROSS_ROW])


# ------------------------------------------------------------------------------ evaluation


@dataclass(frozen=True)
class EvaluationTask:
    """The locked rows of one (profile, menu, origin) and what they are evaluated on.

    ``rows`` are this group's rows of the locked file, in its order, read by the runner after it
    verified the file against ``locked_sha256`` (`selection.read_locked`).
    """

    profile: str
    menu: str
    month: str
    model: OriginModel
    horizon: Horizon
    rows: tuple[dict[str, Any], ...]
    locked_sha256: str
    test_seeds: tuple[int, ...] = TEST_SEEDS


def evaluation_groups(table: pa.Table) -> list[tuple[tuple[str, str, str], list[dict[str, Any]]]]:
    """The locked rows by (profile, menu, month), in file order; each group must be contiguous."""
    keys = list(
        zip(
            table["profile"].to_pylist(),
            table["menu"].to_pylist(),
            table["month"].to_pylist(),
            strict=True,
        )
    )
    groups: list[tuple[tuple[str, str, str], list[dict[str, Any]]]] = []
    start = 0
    for end in range(1, len(keys) + 1):
        if end == len(keys) or keys[end] != keys[start]:
            groups.append((keys[start], table.slice(start, end - start).to_pylist()))
            start = end
    seen = [key for key, _ in groups]
    if len(set(seen)) != len(seen):
        raise ValueError("the locked file is not in canonical order: a group is split")
    return groups


def _hexes(values: Sequence[float]) -> tuple[str, ...]:
    return tuple(float(value).hex() for value in values)


def evaluate_group(task: EvaluationTask) -> pa.Table:
    """Every locked row of the task's group on its training bank, the test banks and history.

    The rows come back in the locked file's order, as a table of `EVALUATED_SCHEMA`.
    """
    want = (task.profile, task.menu, task.month)
    rows = [dict(row) for row in task.rows]
    if not rows:
        raise ValueError(f"no locked selection for {want}")
    foreign = {(row["profile"], row["menu"], row["month"]) for row in rows} - {want}
    if foreign:
        raise ValueError(f"{want}: the task holds locked rows of {sorted(foreign)}")
    model = task.model
    digest = model.inputs_sha256
    stale = {row["model_inputs_sha256"] for row in rows} - {digest}
    if stale:
        raise ValueError(f"{want}: the locked rows were chosen on another origin model {stale}")
    mixes = np.array([row["weights"] for row in rows], dtype=float)

    simulations = []
    bank_hashes = []
    for seed in task.test_seeds:
        drawn = evaluate.bank(model, seed)
        bank_hashes.append(drawn.index_sha256)
        simulations.append(evaluate.simulate(model, drawn, mixes))
        del drawn
    per_bank = [evaluate.summarize([simulation]) for simulation in simulations]
    pooled = evaluate.summarize(simulations)

    training: dict[int, evaluate.Evaluation] = {}
    positions: dict[int, list[int]] = {}
    for j, row in enumerate(rows):
        positions.setdefault(row["seed"], []).append(j)
    for seed, where in sorted(positions.items()):
        drawn = evaluate.bank(model, seed)
        recorded = {rows[j]["train_bank_sha256"] for j in where}
        if recorded != {drawn.index_sha256}:
            raise InvarianceError(
                f"{want} seed {seed}: optimization bank {recorded} redrawn as {drawn.index_sha256}"
            )
        training[seed] = evaluate.evaluate(model, drawn, mixes[where])
    realized = evaluate.realized(task.horizon, mixes)
    metrics = realized.metrics
    horizon = task.horizon

    out = []
    for j, row in enumerate(rows):
        k = row["coefficients"]
        seed = row["seed"]
        local = positions[seed].index(j)
        figures = training[seed]
        train = {name: float(getattr(figures, name)[local]) for name in evaluate.FIGURES}
        train["utility"] = preference.utility(train["bad"], train["typical"], train["good"], k)
        if row["status"] == OK:
            locked = [
                row[f"train_{name}"]
                for name in ("bad", "typical", "good", "utility", "mean", "es_25")
            ]
            redrawn = [
                train[name] for name in ("bad", "typical", "good", "utility", "mean", "es_25")
            ]
            if _hexes(locked) != _hexes(redrawn):
                raise InvarianceError(
                    f"{want} {row['role']}: locked figures {locked} redrawn as {redrawn}"
                )
        test = {name: float(getattr(pooled, name)[j]) for name in evaluate.FIGURES}
        test["utility"] = preference.utility(test["bad"], test["typical"], test["good"], k)
        result = {
            **row,
            **{f"train_{name}": value for name, value in train.items()},
            "train_status": figures.status[local],
            "reference_infeasible": row["status"] == INFEASIBLE,
            "train_paths": figures.paths,
            "test_status": pooled.status[j],
            "test_paths": pooled.paths,
            **{f"test_{name}": value for name, value in test.items()},
            "bank_seeds": list(task.test_seeds),
            "bank_index_sha256": bank_hashes,
            "realized_status": realized.status,
            "horizon_start": horizon.days[0] if horizon.days else None,
            "horizon_end": horizon.days[-1] if horizon.days else None,
            "realized_sha256": horizon.returns_sha256,
        }
        for name in evaluate.FIGURES:
            result[f"bank_{name}"] = [float(getattr(one, name)[j]) for one in per_bank]
        result["bank_utility"] = [
            preference.utility(b, t, g, k)
            for b, t, g in zip(
                result["bank_bad"], result["bank_typical"], result["bank_good"], strict=True
            )
        ]
        if metrics is not None:
            y = float(metrics.annual_return[j])
            result.update(
                {
                    "annual_return": y,
                    "loss": bool(metrics.loss[j]),
                    "below_20": bool(metrics.below_20[j]),
                    "worst_day": float(metrics.worst_day[j]),
                    "max_drawdown": float(metrics.max_drawdown[j]),
                    "volatility": float(metrics.volatility[j]),
                }
            )
            for forecast, values in (("train", train), ("test", test)):
                for name, q in QUANTILES:
                    f = values[name]
                    if math.isfinite(f):
                        result[f"{forecast}_pinball_{name}"] = float(evaluate.pinball(q, y, f))
                        result[f"{forecast}_at_or_below_{name}"] = bool(evaluate.at_or_below(y, f))
            if pooled.status[j] == OK:
                outcomes = np.concatenate([simulation.years[:, j] for simulation in simulations])
                result["test_pit"] = evaluate.pit(y, outcomes)
        out.append(result)
    return pa.Table.from_pylist(out, schema=EVALUATED_SCHEMA)


# ---------------------------------------------------------------------------------- outcomes


def finish_outcomes(table: pa.Table, months: Mapping[str, Sequence[str]]) -> pa.Table:
    """The outcomes table: evaluated rows in canonical order plus the cross-row columns.

    ``table`` holds `EVALUATED_SCHEMA` rows already in canonical order (`cell_sort_key`, then
    the locked roles); ``months`` gives each profile's scheduled origins in order, for turnover.
    """
    names = ("profile", "menu", "month", "ceiling_id", "seed", "role", "allowance", "stands_for")
    cols = {name: table[name].to_pylist() for name in names}
    weights = table["weights"].to_pylist()
    annual = table["annual_return"].to_pylist()
    expected = table["expected_return"].to_pylist()
    rows = range(table.num_rows)

    def ident(i: int) -> tuple:
        return tuple(cols[name][i] for name in names[:5])

    reference_return: dict[tuple, float | None] = {}
    by_fraction: dict[tuple, list[float]] = {}
    by_seed: dict[tuple, dict[int, list[float]]] = {}
    for i in rows:
        profile, menu, month, ceiling_id, seed = ident(i)
        role = (cols["role"][i], cols["allowance"][i])
        if role[0] == "R":
            reference_return[ident(i)] = annual[i]
        for ceiling in cols["stands_for"][i]:
            by_fraction[(profile, menu, month, ceiling, seed, *role)] = weights[i]
        by_seed.setdefault((profile, menu, month, ceiling_id, *role), {})[seed] = weights[i]
    added: dict[str, list[Any]] = {name: [] for name in CROSS_ROW}
    for i in rows:
        profile, menu, month, ceiling_id, seed = ident(i)
        role = (cols["role"][i], cols["allowance"][i])
        y = annual[i]
        added["forecast_error"].append(None if y is None else y - expected[i])
        paired = role[0] in MEASURE_ARMS
        base = reference_return.get(ident(i)) if paired else None
        added["paired_role"].append("R" if paired else None)
        added["paired_realized_difference"].append(None if y is None or base is None else y - base)
        sequence = list(months[profile])
        position = sequence.index(month)
        turnover: list[float | None] = []
        for ceiling in cols["stands_for"][i]:
            previous = None
            if position > 0:
                key = (profile, menu, sequence[position - 1], ceiling, seed, *role)
                previous = by_fraction.get(key)
            turnover.append(None if previous is None else 0.5 * _l1(weights[i], previous))
        added["turnover_prev"].append(turnover)
        seeds = by_seed[(profile, menu, month, ceiling_id, *role)]
        others = sorted(other for other in seeds if other != seed)
        added["seed_l1_seeds"].append(others)
        added["seed_l1"].append([_l1(weights[i], seeds[other]) for other in others])
    out = table.cast(EVALUATED_SCHEMA)
    for name in CROSS_ROW:
        out = out.append_column(
            OUTCOMES_SCHEMA.field(name),
            pa.array(added[name], type=OUTCOMES_SCHEMA.field(name).type),
        )
    return out.select(OUTCOMES_SCHEMA.names)


def _l1(a: Sequence[float], b: Sequence[float]) -> float:
    return math.fsum(abs(x - y) for x, y in zip(a, b, strict=True))


def forecast_error_diagnostic(
    frame: pd.DataFrame,
    *,
    profile: str = "stage-1",
    seed: int = PRIMARY_SEED,
    arm: str = "R+D",
    allowance: float = PRIMARY_ALLOWANCE,
) -> pd.DataFrame:
    """Per menu and prescribed risk cell: corr(w_R forecast error, arm minus R realized return).

    Rows: the profile's ``seed`` with complete realized outcomes; a distinct cell counts in every
    prescribed risk cell it stands for. Columns: menu, ceiling_id, n (mature origins with both
    values), correlation (Pearson; None below two origins or without variation) and sign (+1, -1,
    0 or None).
    """
    errors: dict[tuple[str, str, str], float] = {}
    paired: dict[tuple[str, str, str], float] = {}
    for row in frame.to_dict("records"):
        if row["profile"] != profile or row["seed"] != seed or row["realized_status"] != COMPLETE:
            continue
        for ceiling in row["stands_for"]:
            key = (str(row["menu"]), str(ceiling), str(row["month"]))
            if row["role"] == "R":
                errors[key] = float(row["forecast_error"])
            elif row["role"] == arm and row["allowance"] == allowance:
                paired[key] = float(row["paired_realized_difference"])
    groups: dict[tuple[str, str], list[tuple[float, float]]] = {}
    for key in sorted(errors.keys() & paired.keys()):
        groups.setdefault(key[:2], []).append((errors[key], paired[key]))
    out = []
    for (menu, ceiling), pairs in groups.items():
        x = np.array([a for a, _ in pairs])
        y = np.array([b for _, b in pairs])
        correlation = None
        if len(pairs) >= 2 and np.std(x) > 0.0 and np.std(y) > 0.0:
            correlation = float(np.corrcoef(x, y)[0, 1])
        sign = None if correlation is None else int(np.sign(correlation))
        out.append(
            {
                "menu": menu,
                "ceiling_id": ceiling,
                "n": len(pairs),
                "correlation": correlation,
                "sign": sign,
            }
        )
    return pd.DataFrame(out, columns=["menu", "ceiling_id", "n", "correlation", "sign"])
