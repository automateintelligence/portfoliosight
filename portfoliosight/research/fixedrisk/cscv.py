"""Purged adaptation of combinatorially symmetric cross-validation (protocol v2 section 7).

`cscv_masks` depends only on the frozen ledger (origin dates and horizon endpoints of the eligible
origins); the parent manifest holds its manifest form (`frozen_record`) before any job runs, and the
report consumes it unchanged. `cscv_run` scores the four U triples'
realized annual returns on those masks.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

BLOCKS = 8
TRAIN_BLOCKS = 4
MIN_SIDE_ORIGINS = 60
MIN_TRAIN_BLOCK_ORIGINS = 5
MIN_EVALUABLE = 50
EMBARGO_MONTHS = 1
CANDIDATES = 4  # U1, U2, U3, U4 in tie order
U_WEIGHTS = (0.60, 0.30, 0.10)  # realized U_1 on the quantiles (2.5, 50, 97.5)
QUANTILES = (2.5, 50.0, 97.5)


@dataclass(frozen=True)
class Split:
    index: int
    train_blocks: tuple[int, ...]
    test_blocks: tuple[int, ...]
    train: np.ndarray  # bool over the eligible origins, after purge and embargo
    test: np.ndarray
    purged: int
    embargoed: int


@dataclass(frozen=True)
class CscvMasks:
    origins: np.ndarray  # datetime64[D], ascending
    ends: np.ndarray  # datetime64[D], horizon endpoint of each origin
    blocks: list[np.ndarray]  # origin indices per block
    splits: list[Split]

    def to_manifest(self) -> dict[str, Any]:
        return {
            "origins": [str(d) for d in self.origins],
            "ends": [str(d) for d in self.ends],
            "blocks": [b.tolist() for b in self.blocks],
            "splits": [
                {
                    "index": s.index,
                    "train_blocks": list(s.train_blocks),
                    "test_blocks": list(s.test_blocks),
                    "train": np.flatnonzero(s.train).tolist(),
                    "test": np.flatnonzero(s.test).tolist(),
                    "purged": s.purged,
                    "embargoed": s.embargoed,
                }
                for s in self.splits
            ],
        }

    @classmethod
    def from_manifest(cls, record: dict[str, Any]) -> CscvMasks:
        origins = np.array(record["origins"], dtype="datetime64[D]")
        k = len(origins)
        splits = []
        for s in record["splits"]:
            train, test = np.zeros(k, dtype=bool), np.zeros(k, dtype=bool)
            train[s["train"]] = True
            test[s["test"]] = True
            splits.append(
                Split(
                    s["index"],
                    tuple(s["train_blocks"]),
                    tuple(s["test_blocks"]),
                    train,
                    test,
                    s["purged"],
                    s["embargoed"],
                )
            )
        return cls(
            origins,
            np.array(record["ends"], dtype="datetime64[D]"),
            [np.array(b, dtype=int) for b in record["blocks"]],
            splits,
        )


def cscv_masks(origins: Sequence[Any], ends: Sequence[Any], *, blocks: int = BLOCKS) -> CscvMasks:
    """All `C(blocks, blocks/2)` purged and embargoed train/test masks from ledger endpoints only.

    `origins`/`ends` are the eligible origins (complete realized year) and their horizon endpoints.
    Training origin `o` is purged when its closed interval `[origin, end]` meets that of any test
    origin; then embargoed when its origin falls within one calendar month after the latest end of a
    test block that precedes it. Test origins are never removed.
    """
    o = np.asarray(origins, dtype="datetime64[D]")
    e = np.asarray(ends, dtype="datetime64[D]")
    if o.shape != e.shape or o.ndim != 1:
        raise ValueError("origins and ends must be equal-length vectors")
    order = np.argsort(o, kind="stable")
    o, e = o[order], e[order]
    if (e < o).any():
        raise ValueError("an interval ends before its origin")
    k = len(o)
    if k < blocks:
        raise ValueError(f"{k} eligible origins cannot fill {blocks} blocks")
    cut = [np.asarray(b, dtype=int) for b in np.array_split(np.arange(k), blocks)]
    block_of = np.empty(k, dtype=int)
    for b, idx in enumerate(cut):
        block_of[idx] = b
    stamps_o = pd.DatetimeIndex(o)
    splits = []
    for number, train_blocks in enumerate(itertools.combinations(range(blocks), blocks // 2)):
        test_blocks = tuple(b for b in range(blocks) if b not in train_blocks)
        train = np.isin(block_of, train_blocks)
        test = ~train
        t = np.flatnonzero(test)
        meets = ((o[:, None] <= e[None, t]) & (o[None, t] <= e[:, None])).any(axis=1)
        purge = train & meets
        keep = train & ~purge
        embargo = np.zeros(k, dtype=bool)
        for b in test_blocks:
            latest = pd.Timestamp(e[cut[b]].max())
            limit = latest + pd.DateOffset(months=EMBARGO_MONTHS)
            later = block_of > b
            embargo |= keep & later & (stamps_o > latest) & (stamps_o <= limit)
        keep &= ~embargo
        splits.append(
            Split(
                number,
                tuple(train_blocks),
                test_blocks,
                keep,
                test,
                int(purge.sum()),
                int((embargo).sum()),
            )
        )
    return CscvMasks(o, e, cut, splits)


def frozen_record(
    months: Sequence[str], origins: Sequence[Any], ends: Sequence[Any], *, blocks: int = BLOCKS
) -> dict[str, Any]:
    """The parent manifest's CSCV record of one menu: the eligible origin months (origin order) and
    their masks (`CscvMasks.to_manifest`), or `unavailable` with the reason when too few."""
    order = sorted(range(len(months)), key=lambda i: (np.datetime64(origins[i], "D"), i))
    record: dict[str, Any] = {"months": [str(months[i]) for i in order]}
    if len(order) < blocks:
        record["unavailable"] = f"{len(order)} eligible origins cannot fill {blocks} blocks"
        return record
    masks = cscv_masks([origins[i] for i in order], [ends[i] for i in order], blocks=blocks)
    return {**record, **masks.to_manifest()}


@dataclass
class CscvResult:
    pairs: int  # (r, cell) pairs present in the common mask
    splits_total: int
    evaluable: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    pbo: float | None = None
    pbo_note: str = ""

    @property
    def computable(self) -> bool:
        return self.pbo is not None

    def choice_shares(self, names: Sequence[str]) -> dict[str, float]:
        n = max(len(self.evaluable), 1)
        return {
            name: sum(r["chosen"] == i for r in self.evaluable) / n for i, name in enumerate(names)
        }


def realized_u1(returns: np.ndarray, side: np.ndarray) -> np.ndarray:
    """Per arm: realized U_1 of `returns` (A x K x C) on the origins in `side`, per (r, cell) pair
    from the linear 2.5/50/97.5 percentiles of that pair's origins, then averaged over pairs."""
    sub = returns[:, side, :]
    q = np.nanpercentile(sub, QUANTILES, axis=1)  # 3 x A x C
    u = U_WEIGHTS[0] * q[0] + U_WEIGHTS[1] * q[1] + U_WEIGHTS[2] * q[2]
    return np.nanmean(u, axis=1)


def cscv_run(masks: CscvMasks, returns: np.ndarray) -> CscvResult:
    """Score the four triples over the frozen masks.

    `returns` is A x K x C (arms U1..U4 in tie order, the masks' K eligible origins, C = (r, cell)
    pairs); entries outside the common mask are NaN in every arm alike. A split is evaluable when,
    in every pair present in the common mask, each side keeps at least 60 distinct origins and every
    training block at least 5; otherwise it is dropped and counted.
    """
    x = np.asarray(returns, dtype=float)
    a, k, c = x.shape
    if a != CANDIDATES or k != len(masks.origins):
        raise ValueError("returns must be 4 arms x eligible origins x pairs")
    finite = np.isfinite(x).all(axis=0)  # K x C common mask
    present = finite.any(axis=0)
    result = CscvResult(pairs=int(present.sum()), splits_total=len(masks.splits))
    if not present.any():
        result.pbo_note = "no rows in the common mask"
        return result
    xp = np.where(finite[None, :, :], x, np.nan)[:, :, present]
    fp = finite[:, present]
    for split in masks.splits:
        train_n = (fp & split.train[:, None]).sum(axis=0)
        test_n = (fp & split.test[:, None]).sum(axis=0)
        block_n = min(
            int((fp[masks.blocks[b]] & split.train[masks.blocks[b], None]).sum(axis=0).min())
            for b in split.train_blocks
        )
        reason = None
        if train_n.min() < MIN_SIDE_ORIGINS:
            reason = f"training side keeps {int(train_n.min())} origins (< {MIN_SIDE_ORIGINS})"
        elif test_n.min() < MIN_SIDE_ORIGINS:
            reason = f"test side keeps {int(test_n.min())} origins (< {MIN_SIDE_ORIGINS})"
        elif block_n < MIN_TRAIN_BLOCK_ORIGINS:
            reason = f"a training block keeps {block_n} origins (< {MIN_TRAIN_BLOCK_ORIGINS})"
        if reason:
            result.dropped.append({"split": split.index, "reason": reason})
            continue
        train_u = realized_u1(xp, split.train)
        test_u = realized_u1(xp, split.test)
        best = float(train_u.max())
        tied = int(np.sum(train_u == best))
        chosen = int(np.argmax(train_u))  # first maximum = fixed tie order U1..U4
        rank = float(stats.rankdata(test_u)[chosen])  # 1 worst, 4 best, average ranks on ties
        omega = rank / (CANDIDATES + 1)
        result.evaluable.append(
            {
                "split": split.index,
                "chosen": chosen,
                "tied": tied > 1,
                "train_u": train_u.tolist(),
                "test_u": test_u.tolist(),
                "rank": rank,
                "omega": omega,
                "lambda": math.log(omega / (1.0 - omega)),
                "train_origins": int(train_n.min()),
                "test_origins": int(test_n.min()),
            }
        )
    if len(result.evaluable) >= MIN_EVALUABLE:
        result.pbo = float(np.mean([r["lambda"] < 0 for r in result.evaluable]))
    else:
        result.pbo_note = (
            f"PBO not computable: {len(result.evaluable)} of {len(masks.splits)} splits evaluable "
            f"(minimum {MIN_EVALUABLE})"
        )
    return result
