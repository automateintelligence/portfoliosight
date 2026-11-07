"""Pool recording of the v3 run (protocol v3 §4.4): one row per mix evaluated at a column.

`PoolBuffer` collects rows column-wise while a task runs (weights and the `objectives3.FIELDS`
vector as NumPy rows, keys as plain lists), so a task of about 45,000 rows holds about 15 MB.
`table(...)` turns it into one Arrow table with the task's constant keys, sorted by
`(lookback, r_fraction, arm, start, call)` with the record order as the last key, and
`write_pool` writes it as one zstd Parquet file per origin task.

Columns: keys (menu, month, origin, engine, seed, lookback, r_fraction, r, lam, arm, start,
call, source, record), `weights` (a fixed-size list of N float64, so a reader can take
`flatten().to_numpy().reshape(-1, N)`), then every field of `objectives3.FIELDS` (the band flags
as booleans, `absorbed` as an integer).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .objectives3 import FIELDS

SOURCES = ("search", "sobol", "anchor", "knee_ladder")
BOOL_FIELDS = ("in_narrow", "in_wide")
INT_FIELDS = ("absorbed",)
COMPRESSION = "zstd"


def pool_schema(n: int) -> pa.Schema:
    """The pool table's schema for a menu of `n` holdings."""
    cols = [
        ("menu", pa.string()),
        ("month", pa.string()),
        ("origin", pa.date32()),
        ("engine", pa.string()),
        ("seed", pa.int64()),
        ("lookback", pa.string()),
        ("r_fraction", pa.float64()),
        ("r", pa.float64()),
        ("lam", pa.float64()),  # arm 4's crash-penalty weight; null for every other row
        ("arm", pa.string()),  # the arm whose search or program produced the row; "" for Sobol
        ("start", pa.int32()),  # start index of a search row; -1 otherwise
        ("call", pa.int32()),  # solver call index of a search row (the end point last); -1 else
        ("source", pa.string()),
        ("record", pa.int64()),  # order of evaluation within the task
        ("weights", pa.list_(pa.float64(), n)),
    ]
    for name in FIELDS:
        kind = pa.bool_() if name in BOOL_FIELDS else pa.int32() if name in INT_FIELDS else None
        cols.append((name, kind or pa.float64()))
    return pa.schema(cols)


@dataclass
class PoolBuffer:
    """Rows of one task's pool, column-wise."""

    lookback: list[str] = field(default_factory=list)
    r_fraction: list[float] = field(default_factory=list)
    r: list[float] = field(default_factory=list)
    lam: list[float | None] = field(default_factory=list)
    arm: list[str] = field(default_factory=list)
    start: list[int] = field(default_factory=list)
    call: list[int] = field(default_factory=list)
    source: list[str] = field(default_factory=list)
    weights: list[np.ndarray] = field(default_factory=list)
    values: list[np.ndarray] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.arm)

    def add(
        self,
        *,
        lookback: str,
        r_fraction: float,
        r: float,
        lam: float | None,
        arm: str,
        start: int,
        call: int,
        source: str,
        weights: np.ndarray,
        values: np.ndarray,
    ) -> int:
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
        if len(values) != len(FIELDS):
            raise ValueError(f"a pool row holds {len(FIELDS)} values, got {len(values)}")
        self.lookback.append(lookback)
        self.r_fraction.append(float(r_fraction))
        self.r.append(float(r))
        self.lam.append(None if lam is None else float(lam))
        self.arm.append(arm)
        self.start.append(int(start))
        self.call.append(int(call))
        self.source.append(source)
        self.weights.append(np.asarray(weights, dtype=np.float64))
        self.values.append(values)
        return len(self.arm) - 1

    def extend(self, other: PoolBuffer) -> None:
        for name in self.__dataclass_fields__:
            getattr(self, name).extend(getattr(other, name))

    def table(self, *, menu: str, month: str, origin: date, engine: str, seed: int) -> pa.Table:
        """The pool as one Arrow table, sorted (see the module docstring)."""
        rows = len(self)
        n = len(self.weights[0]) if rows else 0
        schema = pool_schema(n)
        weights = np.vstack(self.weights) if rows else np.empty((0, n))
        values = np.vstack(self.values) if rows else np.empty((0, len(FIELDS)))
        order = sorted(
            range(rows),
            key=lambda i: (
                self.lookback[i], self.r_fraction[i], self.arm[i], self.start[i], self.call[i], i,
            ),
        )  # fmt: skip
        idx = np.asarray(order, dtype=np.int64)

        def pick(items: list) -> list:
            return [items[i] for i in order]

        arrays: list[pa.Array] = [
            pa.array([menu] * rows, pa.string()),
            pa.array([month] * rows, pa.string()),
            pa.array([origin] * rows, pa.date32()),
            pa.array([engine] * rows, pa.string()),
            pa.array(np.full(rows, seed, dtype=np.int64)),
            pa.array(pick(self.lookback), pa.string()),
            pa.array(np.asarray(self.r_fraction, dtype=float)[idx] if rows else []),
            pa.array(np.asarray(self.r, dtype=float)[idx] if rows else []),
            pa.array(pick(self.lam), pa.float64()),
            pa.array(pick(self.arm), pa.string()),
            pa.array(np.asarray(self.start, dtype=np.int32)[idx] if rows else [], pa.int32()),
            pa.array(np.asarray(self.call, dtype=np.int32)[idx] if rows else [], pa.int32()),
            pa.array(pick(self.source), pa.string()),
            pa.array(idx),
            pa.FixedSizeListArray.from_arrays(
                pa.array(weights[idx].reshape(-1) if rows else [], pa.float64()), n
            ),
        ]
        for j, name in enumerate(FIELDS):
            column = values[idx, j] if rows else np.empty(0)
            if name in BOOL_FIELDS:
                arrays.append(pa.array(column == 1.0))
            elif name in INT_FIELDS:
                arrays.append(pa.array(column.astype(np.int32)))
            else:
                arrays.append(pa.array(column, pa.float64()))
        return pa.Table.from_arrays(arrays, schema=schema)


def write_pool(path: Path, table: pa.Table, metadata: dict[bytes, bytes]) -> int:
    """Write the pool atomically (zstd); returns the file's bytes."""
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), **metadata})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(table, tmp, compression=COMPRESSION)
    os.replace(tmp, path)
    return path.stat().st_size


def read_weights(table: pa.Table) -> np.ndarray:
    """The pool's weights as an (rows, N) array."""
    column = table.column("weights").combine_chunks()
    n = column.type.list_size
    return column.flatten().to_numpy(zero_copy_only=False).reshape(-1, n)
