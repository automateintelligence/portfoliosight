"""The build context holds the package and the committed data, and nothing personal (spec 5.3)."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSV = "data/holdings/holdings_guide2017_step2.csv"


def _rules() -> list[tuple[bool, str]]:
    rules = []
    for raw in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            rules.append((line.startswith("!"), line.lstrip("!").strip("/")))
    return rules


def _matches(pattern: str, path: str) -> bool:
    """Docker's rule for these patterns: a match on the path or on any parent directory."""
    parts = path.split("/")
    candidates = ["/".join(parts[:k]) for k in range(1, len(parts) + 1)]
    if pattern.startswith("**/"):
        return any(fnmatch.fnmatchcase(part, pattern[3:]) for part in parts)
    depth = pattern.count("/") + 1
    return any(
        candidate.count("/") + 1 == depth and fnmatch.fnmatchcase(candidate, pattern)
        for candidate in candidates
    )


def ignored(path: str) -> bool:
    out = False
    for negated, pattern in _rules():
        if _matches(pattern, path):
            out = not negated
    return out


def test_only_the_package_and_committed_data_enter_the_context():
    for kept in (
        "pyproject.toml",
        "README.md",
        "portfoliosight/api/app.py",
        "portfoliosight/engine/tensor.schema.json",
        "data/presets.json",
        "data/universes/tiers.json",
        "qse/qse.lock.json",
        "qse/README.md",
        "qse/distributions/joint/fhs.py",
        "qse/exceptions.py",
        CSV,
    ):
        assert not ignored(kept), kept
    for dropped in (
        "data/holdings/personal_test.csv",
        "data/holdings/holdings_2026-10.csv",
        "runs/x",
        "runs/2026/a/b.parquet",
        ".venv/bin/python",
        "web/node_modules/a/index.js",
        "web/dist/index.html",
        "web/src/main.ts",
        ".git/config",
        ".env",
        "deploy/.env",
        "deploy/.local-store/prices/VTI.parquet",
        "tests/fixtures/synthetic_23.parquet",
        "docs/specs/x.md",
        "assertions/x/tests/t.py",
        "scripts/deploy_ks001.sh",
        "portfoliosight/api/__pycache__/app.cpython-312.pyc",
        "qse/distributions/__pycache__/models.cpython-312.pyc",
        "tests/test_qse_sync.py",
        "scripts/sync_qse.py",
        "portfoliosight.egg-info/PKG-INFO",
    ):
        assert ignored(dropped), dropped


def test_tracked_files_hold_one_holdings_file_and_no_runs():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert [name for name in tracked if name.startswith("data/holdings/")] == [CSV]
    assert not [name for name in tracked if name.startswith("runs/") or "/runs/" in name]
    assert ".dockerignore" in tracked and "deploy/Dockerfile" in tracked
