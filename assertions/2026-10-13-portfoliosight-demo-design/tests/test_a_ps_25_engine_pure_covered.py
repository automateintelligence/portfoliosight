"""A-PS-25 — the engine is pure and fully covered.

Claim: `pytest --cov=portfoliosight/engine` reports 100% line coverage for every module under
`portfoliosight/engine/`, and no module there imports `requests`, `boto3`, `urllib`, `socket`,
`pathlib`/`open` for I/O, or anything from `portfoliosight.data`.

Pinned interface (the product must provide exactly this): the package `portfoliosight/engine/`
with at least six of the modules `stats`, `torsion`, `optimize`, `surface`, `suggest`, `stress`,
`caps`, `builder` (each with code); the test suite under `tests/`; `pytest` and `pytest-cov` in
the project virtualenv `.venv`. Coverage is measured with an EMPTY coverage configuration
(the product's own omit / exclude settings do not apply), `# pragma: no cover` is not allowed in
engine sources, and no engine line may be excluded.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "portfoliosight" / "engine"
NAMED = {"stats", "torsion", "optimize", "surface", "suggest", "stress", "caps", "builder"}
FORBIDDEN_ROOTS = {"requests", "boto3", "urllib", "socket", "pathlib"}
PRAGMA = "pragma: " + "no cover"


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


def _engine_modules() -> list[Path]:
    if not ENGINE.is_dir():
        pytest.fail("A-PS-25 red: portfoliosight/engine/ does not exist")
    return sorted(p for p in ENGINE.rglob("*.py") if "__pycache__" not in p.parts)


def _engine_coverage() -> tuple[dict, dict]:
    """Run the product's tests under coverage; return (engine rows by relative path, totals)."""
    py = _project_python()
    if py is None:
        pytest.fail("A-PS-25 red: no project virtualenv (.venv/bin/python) to run the test suite")
    if not (ROOT / "tests").is_dir():
        pytest.fail("A-PS-25 red: tests/ does not exist")
    env = dict(os.environ)
    for name in ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PS_GATE_INNER", "PS_LIVE_TESTS", "PYTHONPATH"):
        env.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="ps-gate-a25-") as tmp:
        rc_file = Path(tmp) / "empty.coveragerc"
        rc_file.write_text("")  # our own, empty: no omit, no extra exclusions
        report = Path(tmp) / "coverage.json"
        env["COVERAGE_FILE"] = str(Path(tmp) / ".coverage")
        cmd = [str(py), "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"]
        cmd += ["--cov=portfoliosight/engine", f"--cov-config={rc_file}"]
        cmd += ["--cov-report=term-missing", f"--cov-report=json:{report}"]
        try:
            proc = subprocess.run(
                cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1000
            )
        except subprocess.TimeoutExpired:
            pytest.fail("A-PS-25 red: the test suite did not finish within 1000 s")
        tail = (proc.stdout[-3000:] + "\n" + proc.stderr[-1500:]).strip()
        assert proc.returncode == 0, (
            f"A-PS-25 red: `pytest tests --cov=portfoliosight/engine` exited {proc.returncode}:\n"
            + tail
        )
        if not report.is_file():
            pytest.fail("A-PS-25 red: pytest wrote no coverage JSON report:\n" + tail)
        data = json.loads(report.read_text())
    rows = {}
    for name, row in data.get("files", {}).items():
        path = (ROOT / name).resolve()
        if ENGINE.resolve() in path.parents:
            rows[path.relative_to(ROOT.resolve()).as_posix()] = row
    return rows, data.get("totals", {})


def _io_violations(source: str) -> list[str]:
    """Forbidden imports and `open(` calls of one module's source (the spec's AST scan)."""
    found: list[str] = []

    def check_module(name: str, line: int) -> None:
        parts = name.split(".")
        if parts[0] in FORBIDDEN_ROOTS:
            found.append(f"line {line}: imports {name}")
        if parts[:2] == ["portfoliosight", "data"]:
            found.append(f"line {line}: imports {name}")

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                check_module(alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [alias.name for alias in node.names]
            if node.level:  # relative: `from ..data import x`, `from .. import data`
                if module.split(".")[0] == "data" or (not module and "data" in names):
                    found.append(f"line {node.lineno}: relative import of the data package")
                continue
            check_module(module, node.lineno)
            if module == "portfoliosight" and "data" in names:
                found.append(f"line {node.lineno}: imports portfoliosight.data")
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if called == "open":
                found.append(f"line {node.lineno}: open( call")
            if called in ("__import__", "import_module") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    check_module(arg.value, node.lineno)
    return found


def test_scanner_detects_what_it_must_and_nothing_else():
    """Control: the AST scan flags each forbidden form and leaves pure numeric code alone."""
    dirty = [
        "import requests",
        "import urllib.request",
        "from urllib import parse",
        "import boto3 as b",
        "from socket import socket",
        "from pathlib import Path",
        "from portfoliosight.data import store",
        "import portfoliosight.data.store",
        "from portfoliosight import data",
        "from ..data import store",
        "from .. import data",
        "def f(p):\n    return open(p).read()",
        "def f(p):\n    return p.open()",
        "import importlib\nm = importlib.import_module('requests')",
    ]
    for source in dirty:
        assert _io_violations(source), f"scanner missed: {source!r}"
    clean = "import numpy as np\nfrom .stats import moments\nfrom . import caps\nx = np.ones(3)\n"
    assert not _io_violations(clean)


def test_every_engine_module_is_free_of_io_imports():
    modules = _engine_modules()
    real = [p for p in modules if p.stem in NAMED and p.read_text(encoding="utf-8").strip()]
    assert len({p.stem for p in real}) >= 6, (
        "A-PS-25 red: portfoliosight/engine/ must hold at least six of "
        f"{sorted(NAMED)}; found {sorted(p.stem for p in real)}"
    )
    violations = {}
    for path in modules:
        source = path.read_text(encoding="utf-8")
        hits = _io_violations(source)
        if hits:
            violations[path.relative_to(ROOT).as_posix()] = hits
    assert not violations, f"A-PS-25 red: engine modules perform or import I/O: {violations}"


def test_every_engine_module_has_full_line_coverage():
    modules = _engine_modules()
    pragma = [
        p.relative_to(ROOT).as_posix() for p in modules if PRAGMA in p.read_text(encoding="utf-8")
    ]
    assert not pragma, f"A-PS-25 red: coverage exclusion pragmas in engine sources: {pragma}"

    rows, _totals = _engine_coverage()
    on_disk = {p.relative_to(ROOT).as_posix() for p in modules}
    unreported = sorted(on_disk - set(rows))
    assert not unreported, (
        f"A-PS-25 red: engine modules absent from the coverage report: {unreported}"
    )

    with_code = {
        Path(name).stem for name, row in rows.items() if row["summary"]["num_statements"] > 0
    }
    assert len(with_code & NAMED) >= 6, (
        "A-PS-25 red: the coverage report must list at least six engine modules with code out of "
        f"{sorted(NAMED)}; it lists {sorted(with_code)}"
    )

    below = {}
    for name, row in sorted(rows.items()):
        summary = row["summary"]
        full = (
            summary["percent_covered"] == 100
            and summary["missing_lines"] == 0
            and not row.get("missing_lines")
        )
        if not full:
            below[name] = (round(summary["percent_covered"], 2), row.get("missing_lines", [])[:20])
        assert summary.get("excluded_lines", 0) == 0 and not row.get("excluded_lines"), (
            f"A-PS-25 red: {name} reaches its figure by excluding lines {row.get('excluded_lines')}"
        )
    assert not below, f"A-PS-25 red: engine modules below 100% line coverage (missing): {below}"
