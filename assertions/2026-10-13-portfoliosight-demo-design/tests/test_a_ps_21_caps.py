"""A-PS-21 - caps scale with the menu and are validated; no 23-fund mix exceeds 25%.

Claim: the default bound is max = clamp(3/N, 0.25, 1.0), min = 0, N = funds included in the
window; validation rejects min > max, any bound outside [0, 1], sum(min) > 1, sum(max) < 1 and
N < 2; the greedy endpoint fill allocates every minimum first; on the 23-fund fixture no computed
weight exceeds 0.25 + 1e-6.

Pinned interface (the product must provide exactly this), in portfoliosight.engine.caps:
- resolve_bounds(ids, requested=None) -> (min, max) arrays in ids order. requested is the --caps
  shape: a list of {"id", "min", "max"} with null = default rule; funds not listed use defaults.
- CapsError, a ValueError subclass (the error the API maps to 422). Per-fund violations name the
  fund id in the message; sum violations contain the word "sum".
- greedy_fill(mu, lo, hi) -> w: every minimum first, then the remainder in descending mu order up
  to each maximum.
Plus scripts/build_tensor.py (shared CLI pin) and tests/fixtures/synthetic_23.parquet.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

try:  # the gate's outer interpreter may lack them; every test calls _deps() first
    import numpy as np
    import pandas as pd
except Exception:  # pragma: no cover
    np = pd = None

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
        pytest.fail(f"A-PS-21 red: cannot import {module}: {type(exc).__name__}: {exc}")


def _attr(module: str, name: str):
    mod = _need(module)
    if not hasattr(mod, name):
        pytest.fail(f"A-PS-21 red: {module} has no attribute {name!r} (pinned interface)")
    return getattr(mod, name)


def _deps():
    if np is None or pd is None:
        pytest.fail("A-PS-21 red: numpy and pandas are not importable in this interpreter")


BUILD_CLI = ROOT / "scripts" / "build_tensor.py"
FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_23.parquet"
NX, NY = 48, 32
TOL = 1e-6
_CACHE: dict = {}


def _run_cli(script: Path, args: list, timeout: int = 300):
    if not script.exists():
        pytest.fail(f"A-PS-21 red: {script.relative_to(ROOT)} does not exist")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_DISABLE_PLUGIN_AUTOLOAD"}
    try:
        return subprocess.run(
            [sys.executable, str(script), *[str(a) for a in args]],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"A-PS-21 red: {script.name} did not finish within {timeout} s")


def _build(returns: Path, lookback: str, asof: str, out: Path, caps: Path | None = None) -> dict:
    """Build one tensor through the pinned CLI and return the parsed JSON."""
    args = ["--returns", returns, "--lookback", lookback, "--asof", asof, "--out", out]
    if caps is not None:
        args += ["--caps", caps]
    proc = _run_cli(BUILD_CLI, args)
    if proc.returncode != 0 or not Path(out).exists():
        pytest.fail(
            f"A-PS-21 red: build_tensor.py exit {proc.returncode}, file={Path(out).exists()}: "
            f"{proc.stderr[-1500:]}"
        )
    try:
        return json.loads(Path(out).read_text())
    except ValueError as exc:
        pytest.fail(f"A-PS-21 red: {out} is not JSON: {exc}")


def _fixture_frame():
    _deps()
    _need("pyarrow")
    if not FIXTURE.exists():
        pytest.fail(f"A-PS-21 red: fixture {FIXTURE.relative_to(ROOT)} does not exist")
    frame = pd.read_parquet(FIXTURE)
    assert isinstance(frame.index, pd.DatetimeIndex), "fixture index must be a DatetimeIndex"
    return frame


def _fixture_tensor(tmp_path_factory) -> dict:
    """The fixture tensor: synthetic_23.parquet, lookback 5y, asof = the parquet's last date."""
    if "fixture" not in _CACHE:
        frame = _fixture_frame()
        asof = frame.index.max().date().isoformat()
        out = tmp_path_factory.mktemp("fixture") / "tensor.json"
        _CACHE["fixture"] = _build(FIXTURE, "5y", asof, out)
    return _CACHE["fixture"]


def _arrays(t: dict):
    """Numpy views of the tensor fields the recomputations need (shape-checked)."""
    try:
        n = len(t["universe"]["funds"])
        a = SimpleNamespace(
            n=n,
            cov=np.array(t["cov"], float),
            mu=np.array(t["mu_s"], float),
            lo=np.array(t["bounds"]["min"], float),
            hi=np.array(t["bounds"]["max"], float),
            x=np.array(t["frontier"]["x"], float),
            yf=np.array(t["frontier"]["y"], float),
            wf=np.array(t["frontier"]["w"], float),
            gy=np.array(t["grid"]["y"], float),
            gw=t["grid"]["w"],
            gz=t["grid"]["z"],
            k_div=list(t["grid"]["k_div"]),
            y_div=np.array(t["grid"]["y_div"], float),
            w_div=np.array(t["grid"]["w_div"], float),
            y_sug=np.array(t["grid"]["y_sug"], float),
            tor=np.array(t["torsion"], float),
            tor_inv_t=np.array(t["torsion_inv_t"], float),
            lam=np.array(t["torsion_lambda"], float),
        )
    except (KeyError, TypeError, ValueError) as exc:
        pytest.fail(f"A-PS-21 red: tensor lacks a spec 7 field or has a ragged array: {exc!r}")
    assert n >= 2
    assert a.cov.shape == (n, n) and a.mu.shape == (n,)
    assert a.lo.shape == (n,) and a.hi.shape == (n,)
    assert a.x.shape == (NX,) and a.yf.shape == (NX,) and a.wf.shape == (NX, n)
    assert a.gy.shape == (NY,) and len(a.gw) == NX and len(a.gz) == NX
    assert all(len(col) == NY for col in a.gw) and all(len(col) == NY for col in a.gz)
    assert len(a.k_div) == NX and a.y_div.shape == (NX,) and a.w_div.shape == (NX, n)
    assert a.y_sug.shape == (NX,)
    assert a.tor.shape == (n, n) and a.tor_inv_t.shape == (n, n) and a.lam.shape == (n,)
    return a


def _sigma(w, cov) -> float:
    return float(np.sqrt(w @ cov @ w))


def _check_torsion_fields(a):
    """The shipped torsion triple must be a real diagonalizing torsion of the shipped cov."""
    m = a.tor @ a.cov @ a.tor.T
    off = np.abs(m - np.diag(np.diag(m))).max()
    assert off <= 1e-8 * np.trace(m), f"torsion does not diagonalize cov: max offdiag {off}"
    assert np.allclose(np.diag(m), a.lam, rtol=1e-9, atol=0), "torsion_lambda != diag(T cov T')"
    assert np.all(a.lam > 0)
    assert np.abs(a.tor_inv_t @ a.tor.T - np.eye(a.n)).max() <= 1e-8, "torsion_inv_t != inv(T')"


def _enb(w, a) -> float:
    """Independent ENB (spec 4.6) from the tensor's own cov / torsion_inv_t / torsion_lambda."""
    b = a.tor_inv_t @ w
    p = a.lam * b**2 / (w @ a.cov @ w)
    assert abs(p.sum() - 1) <= 1e-8, f"sum(p) = {p.sum()!r}"
    assert not (p < 0).any()
    nz = p[p > 0]
    return float(np.exp(-(nz * np.log(nz)).sum()))


def _greedy(mu, lo, hi, ascending: bool = False):
    """Spec 4.4 endpoint fill: every minimum first, then the remainder in mu order to each max."""
    w = np.array(lo, float)
    rest = 1.0 - w.sum()
    for i in np.argsort(mu if ascending else -np.asarray(mu), kind="stable"):
        add = min(hi[i] - w[i], rest)
        w[i] += add
        rest -= add
    return w


def _default_max(n: int) -> float:
    return min(max(3.0 / n, 0.25), 1.0)


def _random_menu(directory: Path, n: int, seed: int):
    """A seeded SPD menu: simulated daily returns in the pinned parquet format plus random caps.

    Returns (returns_path, caps_path, asof, lo, hi, requested) with lo/hi the expected resolved
    bounds (null entries resolve by the default rule) and requested the per-fund min/max as sent.
    """
    _deps()
    _need("pyarrow")
    rng = np.random.default_rng(seed)
    load = rng.normal(0.0, 1.0, (n, 3)) * np.array([0.10, 0.05, 0.03]) + np.array([0.06, 0.0, 0.0])
    idio = rng.uniform(0.02, 0.10, n)
    cov = load @ load.T + np.diag(idio**2)
    assert np.linalg.eigvalsh(cov).min() > 0
    mean = rng.uniform(0.01, 0.10, n)
    rows = 1400
    draws = rng.multivariate_normal(mean / 252.0, cov / 252.0, size=rows)
    ids = [f"M{i:02d}" for i in range(n)]
    index = pd.bdate_range(end="2026-06-30", periods=rows, name="date")
    path = directory / f"menu_{n}.parquet"
    pd.DataFrame(draws, index=index, columns=ids).to_parquet(path)
    lo, hi, requested, caps = np.zeros(n), np.full(n, _default_max(n)), [], []
    hi_low, hi_high = max(1.5 / n, 0.12), min(1.0, max(4.0 / n, 0.30))
    for i, fid in enumerate(ids):
        mn = float(rng.uniform(0.0, 0.3 / n)) if rng.random() < 0.5 else None
        mx = float(rng.uniform(hi_low, hi_high)) if rng.random() < 0.5 else None
        if mn is not None:
            lo[i] = mn
        if mx is not None:
            hi[i] = mx
        requested.append({"min": mn, "max": mx})
        caps.append({"id": fid, "min": mn, "max": mx})
    assert (lo <= hi).all() and lo.sum() <= 1.0 <= hi.sum()
    caps_path = directory / f"caps_{n}.json"
    caps_path.write_text(json.dumps(caps))
    return path, caps_path, "2026-06-30", lo, hi, requested


if _OUTER:

    def test_a_ps_21_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-21 is red inside the project virtualenv (output above)"

else:

    def _caps():
        _deps()
        mod = _need("portfoliosight.engine.caps")
        for name in ("resolve_bounds", "greedy_fill", "CapsError"):
            if not hasattr(mod, name):
                pytest.fail(f"A-PS-21 red: portfoliosight.engine.caps has no {name!r}")
        assert issubclass(mod.CapsError, ValueError)
        return mod

    def test_default_max_closed_form_for_every_menu_size():
        caps = _caps()
        spot = {2: 1.0, 3: 1.0, 5: 0.6, 10: 0.3, 12: 0.25, 23: 0.25, 30: 0.25}
        checked = 0
        for n in range(2, 31):
            ids = [f"F{i:02d}" for i in range(n)]
            lo, hi = (np.asarray(v, float) for v in caps.resolve_bounds(ids, None))
            expected = min(max(3.0 / n, 0.25), 1.0)
            assert lo.shape == (n,) and hi.shape == (n,)
            assert not (lo != 0.0).any(), f"N={n}: default min is not 0"
            assert np.abs(hi - expected).max() <= 1e-15, f"N={n}: max {hi[0]} != {expected}"
            assert not (hi < 0.25).any() and not (hi > 1.0).any(), f"N={n}: max outside [0.25, 1]"
            if n in spot:
                assert abs(hi[0] - spot[n]) <= 1e-12, f"N={n}: spot value"
            checked += 1
        assert checked == 29
        ids = ["A", "B", "C", "D", "E"]
        lo, hi = caps.resolve_bounds(
            ids, [{"id": "B", "min": 0.1, "max": None}, {"id": "D", "min": None, "max": 0.35}]
        )
        assert list(np.asarray(lo, float)) == [0.0, 0.1, 0.0, 0.0, 0.0]
        assert np.abs(np.asarray(hi, float) - np.array([0.6, 0.6, 0.6, 0.35, 0.6])).max() <= 1e-15

    def test_invalid_inputs_raise_the_validation_error():
        caps = _caps()
        ids = ["AAA", "BBB", "CCC", "DDD"]

        def every(mn, mx):
            return [{"id": i, "min": mn, "max": mx} for i in ids]

        cases = [
            ("min > max", ids, [{"id": "BBB", "min": 0.5, "max": 0.3}], "BBB"),
            ("max above 1", ids, [{"id": "CCC", "min": None, "max": 1.2}], "CCC"),
            ("min below 0", ids, [{"id": "DDD", "min": -0.1, "max": None}], "DDD"),
            ("sum of minimums above 1", ids, every(0.3, None), "sum"),
            ("sum of maximums below 1", ids, every(None, 0.2), "sum"),
            ("N < 2", ["AAA"], None, None),
        ]
        assert caps.resolve_bounds(ids, every(0.25, 0.25)) is not None  # boundary sums are valid
        raised = 0
        for label, menu, requested, token in cases:
            try:
                result = caps.resolve_bounds(menu, requested)
            except caps.CapsError as exc:
                if token is not None:
                    assert token.lower() in str(exc).lower(), (
                        f"{label}: message lacks {token!r}: {exc}"
                    )
                raised += 1
                continue
            except Exception as exc:
                pytest.fail(f"{label}: expected CapsError, got {type(exc).__name__}: {exc}")
            pytest.fail(f"{label}: resolve_bounds returned {result!r} for an invalid input")
        assert raised == len(cases) == 6

    def test_greedy_fill_places_every_minimum_first():
        caps = _caps()
        lo, hi = np.array([0.3, 0.3, 0.0, 0.0]), np.array([0.3, 0.3, 0.4, 0.4])
        for mu, expected in (
            ([0.10, 0.08, 0.02, 0.05], [0.3, 0.3, 0.0, 0.4]),
            ([0.01, 0.02, 0.10, 0.05], [0.3, 0.3, 0.4, 0.0]),
            ([0.01, 0.02, 0.05, 0.10], [0.3, 0.3, 0.0, 0.4]),
        ):
            w = np.asarray(caps.greedy_fill(np.array(mu), lo, hi), float)
            assert w[0] == 0.3 and w[1] == 0.3, f"mu={mu}: minimums not allocated first: {w}"
            assert np.abs(w - np.array(expected)).max() <= 1e-12, f"mu={mu}: {w}"
            assert not np.abs(w - np.array([0.0, 0.2, 0.4, 0.4])).max() < 1e-9  # mu-only fill
        rng = np.random.default_rng(2101)
        checked = 0
        for _ in range(40):
            n = int(rng.integers(2, 31))
            lo = rng.uniform(0.0, 0.6 / n, n) * (rng.random(n) < 0.5)
            hi = np.maximum(lo + 0.05, rng.uniform(1.2 / n, min(1.0, 4.0 / n), n))
            hi = np.minimum(hi, 1.0)
            mu = rng.uniform(-0.02, 0.12, n)
            w = np.asarray(caps.greedy_fill(mu, lo, hi), float)
            assert np.abs(w - _greedy(mu, lo, hi)).max() <= 1e-12
            assert (
                abs(w.sum() - 1.0) <= 1e-12
                and not (w < lo - 1e-12).any()
                and not (w > hi + 1e-12).any()
            )
            checked += 1
        assert checked == 40

    def test_fixture_tensor_weights_and_recorded_bounds(tmp_path_factory):
        t = _fixture_tensor(tmp_path_factory)
        a = _arrays(t)
        n = a.n
        assert n >= 12, f"the fixture menu has {n} funds; the 25% cap needs 12 or more"
        expected = _default_max(n)
        assert expected == 0.25
        assert t["bounds"]["rule"] == "max(0.25, 3/N)"
        requested = t["bounds"]["requested"]
        assert len(requested) == n
        assert not [r for r in requested if r.get("min") is not None or r.get("max") is not None]
        assert all("min" in r and "max" in r for r in requested)
        assert np.abs(a.hi - expected).max() <= 1e-15 and not (a.lo != 0.0).any()
        assert not (a.hi < 0.25).any() and not (a.hi > 1.0).any()
        vectors = [np.asarray(w, float) for w in a.wf] + [np.asarray(w, float) for w in a.w_div]
        cells = [np.asarray(w, float) for col in a.gw for w in col if w is not None]
        vectors += cells
        assert len(cells) >= 500 and len(vectors) == 96 + len(cells)
        worst = max(float(w.max()) for w in vectors)
        assert not worst > 0.25 + TOL, f"a fixture weight reaches {worst}"
        assert worst > 0.25 - 1e-3  # the cap really binds somewhere (max-return fill)
