"""A-PS-29 — the universe hash is canonical.

Claim: the hash is sha256(canonical_json({"schema": 2, "funds": [{"id","min","max"} sorted by
id]}))[:16] over the requested policy with null for defaults, so it is independent of input order
and of the lookback, and changes with any cap override.

Pinned interface (the product must provide exactly this):
- `portfoliosight.api.hashing.universe_hash(funds) -> str`, where `funds` is a list of mappings
  with keys `id` (str), `min` and `max` (float or None; None = the default rule). It takes the
  funds only: there is no lookback (or window) parameter, which is what makes the hash the same
  for every lookback. A-PS-28 checks the same value on the API's responses across lookbacks.
- The function feeds the canonical JSON bytes to `hashlib.sha256` in one piece (constructor
  argument or a single `update`). This file replaces `hashlib.sha256` with a recording wrapper
  for the whole process before the product is imported, so either import style is seen.
- The guide menu is read from `data/holdings/holdings_guide2017_step2.csv` (column `Symbol`).
"""

from __future__ import annotations

import csv
import hashlib
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _project_python() -> Path | None:
    """The project's virtualenv interpreter: this checkout's, else the main checkout's (worktree)."""
    roots = [ROOT]
    dot_git = ROOT / ".git"
    if dot_git.is_file():  # linked worktree: "gitdir: <main>/.git/worktrees/<name>"
        roots.append(Path(dot_git.read_text().split(":", 1)[1].strip()).parents[2])
    for root in roots:
        candidate = root / ".venv" / "bin" / "python"
        if candidate.exists():
            return candidate
    return None


_VENV_PY = _project_python()
_OUTER = (
    os.environ.get("PS_GATE_INNER") != "1"
    and _VENV_PY is not None
    and Path(sys.prefix).resolve() != _VENV_PY.parents[1].resolve()
)


def _need(module: str):
    """Import a product (or dev-dependency) module, failing the test cleanly when it is absent."""
    try:
        return importlib.import_module(module)
    except Exception as exc:  # ImportError, or an import-time crash in the product
        pytest.fail(f"A-PS-29 red: cannot import {module}: {type(exc).__name__}: {exc}")


HOLDINGS_CSV = ROOT / "data" / "holdings" / "holdings_guide2017_step2.csv"
_REAL_SHA256 = hashlib.sha256
_FED: list[bytes] = []


class _RecordingSha256:
    """Stands in for hashlib.sha256 and records every buffer fed to it."""

    def __init__(self, data=b"", **kwargs):
        self._h = _REAL_SHA256(data, **kwargs)
        if data:
            _FED.append(bytes(data))

    def update(self, data):
        _FED.append(bytes(data))
        return self._h.update(data)

    def __getattr__(self, name):
        return getattr(self._h, name)


def _expected(funds) -> tuple[bytes, str]:
    """Independent reference: canonical bytes and the 16-hex hash."""
    rows = sorted(
        ({"id": f["id"], "min": f["min"], "max": f["max"]} for f in funds), key=lambda f: f["id"]
    )
    canon = json.dumps({"schema": 2, "funds": rows}, sort_keys=True, separators=(",", ":"))
    data = canon.encode("utf-8")
    return data, _REAL_SHA256(data).hexdigest()[:16]


def _hash_fn():
    fn = getattr(_need("portfoliosight.api.hashing"), "universe_hash", None)
    if fn is None:
        pytest.fail("A-PS-29 red: portfoliosight.api.hashing.universe_hash is missing")
    return fn


def _call(fn, funds) -> tuple[str, list[bytes]]:
    """Run the product hash on a deep copy of `funds`; return its value and the bytes it hashed."""
    del _FED[:]
    value = fn([dict(f) for f in funds])
    return value, list(_FED)


def _guide_ids() -> list[str]:
    assert HOLDINGS_CSV.exists(), f"A-PS-29 red: {HOLDINGS_CSV.relative_to(ROOT)} is missing"
    with HOLDINGS_CSV.open(newline="") as fh:
        ids = [row["Symbol"].strip() for row in csv.DictReader(fh)]
    assert len(ids) == 23 and len(set(ids)) == 23, "the Step 2 CSV must list 23 distinct symbols"
    return ids


def _random_menu(rng, pool):
    n = int(rng.integers(2, min(30, len(pool)) + 1))
    ids = [str(i) for i in rng.choice(pool, size=n, replace=False)]
    funds = []
    for i in ids:
        lo = None if rng.random() < 0.7 else round(float(rng.uniform(0.0, 0.02)), 4)
        hi = None if rng.random() < 0.7 else round(float(rng.uniform(0.3, 0.9)), 4)
        funds.append({"id": i, "min": lo, "max": hi})
    return funds


if not _OUTER:
    hashlib.sha256 = _RecordingSha256


if _OUTER:

    def test_a_ps_29_in_project_venv():
        env = dict(os.environ, PS_GATE_INNER="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        proc = subprocess.run(
            [
                str(_VENV_PY),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                __file__,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        print(proc.stdout[-8000:], proc.stderr[-2000:])
        assert proc.returncode == 0, "A-PS-29 is red inside the project virtualenv (output above)"

else:

    def test_matches_the_spec_formula_and_feeds_canonical_json_to_sha256():
        fn = _hash_fn()
        np = _need("numpy")
        rng = np.random.default_rng(29)
        guide = [{"id": i, "min": None, "max": None} for i in _guide_ids()]
        pool = sorted(
            {f["id"] for f in guide} | {"TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I", "SGOV"}
        )
        pool += ["VOO", "SPY", "QQQ", "IWM", "EFA", "TLT", "GLD", "VXUS", "BNDX", "SCHD", "VTSAX"]
        menus = [guide] + [_random_menu(rng, pool) for _ in range(60)]
        seen = set()
        for funds in menus:
            data, want = _expected(funds)
            got, fed = _call(fn, funds)
            assert isinstance(got, str) and re.fullmatch(r"[0-9a-f]{16}", got), (
                f"universe_hash returned {got!r}, expected 16 lowercase hex characters"
            )
            assert got == want, f"hash {got} is not sha256(canonical JSON)[:16] = {want}"
            assert fed, "nothing was fed to hashlib.sha256 while hashing"
            assert data in fed, (
                "the bytes fed to hashlib.sha256 are not the canonical JSON; first buffer was "
                f"{fed[0][:120]!r}"
            )
            text = data.decode()
            captured = fed[fed.index(data)].decode()
            assert '"schema":2' in captured
            assert not re.search(r"\s", captured), "canonical JSON contains whitespace"
            assert captured.index('"funds"') < captured.index('"schema"'), (
                "top-level keys not sorted"
            )
            for row in json.loads(captured)["funds"]:
                assert list(row) == ["id", "max", "min"], f"fund keys not sorted: {list(row)}"
            assert [r["id"] for r in json.loads(captured)["funds"]] == sorted(
                f["id"] for f in funds
            )
            assert captured == text
            seen.add(got)
        assert len(seen) == len(menus), "distinct menus must not collide in this sample"
        # The spec §7 example: guide2017, all defaults -> null, never 0 or 1.
        _, fed = _call(fn, guide)
        doc = json.loads(_expected(guide)[0])
        assert all(r["min"] is None and r["max"] is None for r in doc["funds"])
        canon = next(b for b in fed if b == _expected(guide)[0]).decode()
        assert canon.count('"max":null,"min":null') == 23
        assert '"min":0' not in canon and '"max":1' not in canon

    def test_order_and_lookback_do_not_change_the_hash():
        fn = _hash_fn()
        np = _need("numpy")
        rng = np.random.default_rng(2929)
        guide = [{"id": i, "min": None, "max": None} for i in _guide_ids()]
        pool = [f["id"] for f in guide] + ["TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I"]
        checked = 0
        for case in range(40):
            funds = guide if case == 0 else _random_menu(rng, pool)
            base, _ = _call(fn, funds)
            for _ in range(5):
                order = [int(k) for k in rng.permutation(len(funds))]
                if order == list(range(len(funds))):
                    continue
                shuffled = [funds[k] for k in order]
                assert [f["id"] for f in shuffled] != [f["id"] for f in funds]
                assert _call(fn, shuffled)[0] == base, "hash varies with the order of the funds"
                checked += 1
            # key order inside a fund mapping must not matter either
            flipped = [{"max": f["max"], "min": f["min"], "id": f["id"]} for f in reversed(funds)]
            assert _call(fn, flipped)[0] == base
        assert checked >= 150, f"only {checked} permutations were checked"
        # Lookback independence: the function has no way to see a lookback.
        params = inspect.signature(fn).parameters
        required = [
            p
            for p in params.values()
            if p.default is inspect.Parameter.empty
            and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        ]
        assert len(required) == 1, f"universe_hash must take the funds only, got {list(params)}"
        assert not [n for n in params if "look" in n.lower() or "window" in n.lower()], (
            f"universe_hash must not take a lookback: {list(params)}"
        )
        for lookback in ("1y", "5y"):
            del _FED[:]
            fn([dict(f) for f in guide])
            assert not [b for b in _FED if lookback.encode() in b], "a lookback id reached the hash"

    def test_any_cap_override_changes_the_hash():
        fn = _hash_fn()
        np = _need("numpy")
        rng = np.random.default_rng(292929)
        guide = [{"id": i, "min": None, "max": None} for i in _guide_ids()]
        base, _ = _call(fn, guide)
        values = {base}
        for k in range(len(guide)):
            for field, value in (("max", 0.10), ("min", 0.10), ("max", 1.0), ("min", 0.0)):
                changed = [dict(f) for f in guide]
                changed[k][field] = value
                got, _ = _call(fn, changed)
                assert got == _expected(changed)[1]
                assert got != base, f"hash unchanged after setting {guide[k]['id']}.{field}={value}"
                values.add(got)
        assert len(values) == 1 + 4 * len(guide), "two different cap policies share a hash"
        for _ in range(40):
            funds = _random_menu(rng, [f["id"] for f in guide])
            before, _ = _call(fn, funds)
            k = int(rng.integers(0, len(funds)))
            changed = [dict(f) for f in funds]
            old = changed[k]["max"]
            changed[k]["max"] = 0.10 if old != 0.10 else 0.11
            after, _ = _call(fn, changed)
            assert after != before, "hash equal across a cap change"
            swapped = [dict(f) for f in funds]
            swapped[k]["min"], swapped[k]["max"] = 0.05, None
            mirror = [dict(f) for f in funds]
            mirror[k]["min"], mirror[k]["max"] = None, 0.05
            assert _call(fn, swapped)[0] != _call(fn, mirror)[0], (
                "min and max overrides are confused"
            )
