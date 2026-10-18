"""A-SE-01 (contract): exact pinned QSE bytes, readonly closure, real sync/drift guard.
Canonical SHA-256 values independently verified with git show at the upstream pin on
2026-10-17. Runtime uses a disposable local git source and needs no private checkout.
Pinned CLI: scripts/sync_qse.py --commit SHA|--check --qse-dir PATH --root PATH.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _inner():
    """Reexecute this frozen file with project dependencies, never a sibling product tree."""
    roots = [ROOT]
    dotgit = ROOT / ".git"
    if dotgit.is_file():
        roots.append(Path(dotgit.read_text().split(":", 1)[1].strip()).parents[2])
    interpreter = next(
        (r / ".venv/bin/python" for r in roots if (r / ".venv/bin/python").exists()),
        None,
    )
    if interpreter and Path(sys.prefix).resolve() != interpreter.parents[1].resolve():
        result = subprocess.run(
            [
                str(interpreter),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                str(Path(__file__).resolve()),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=900,
            env={
                **os.environ,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONPATH": str(ROOT),
                "PYTHONNOUSERSITE": "1",
            },
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return True
    return False


def _need(name):
    # An editable install in the shared venv can point at another feature worktree.
    top = name.split(".")[0]
    if top in {"portfoliosight", "qse"}:
        for key in list(sys.modules):
            if key == top or key.startswith(top + "."):
                module = sys.modules[key]
                origins = list(getattr(module, "__path__", []))
                if getattr(module, "__file__", None):
                    origins.append(module.__file__)
                if any(not Path(p).resolve().is_relative_to(ROOT) for p in origins):
                    for stale in list(sys.modules):
                        if stale == top or stale.startswith(top + "."):
                            del sys.modules[stale]
                    break
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        pytest.fail(
            f"Required product interface {name} is unavailable: {type(exc).__name__}: {exc}"
        )
    if top in {"portfoliosight", "qse"}:
        assert Path(module.__file__).resolve().is_relative_to(ROOT), (
            "Product imported from a different checkout"
        )
    return module


def _attr(module, name):
    if not hasattr(module, name):
        pytest.fail(f"Required product interface {module.__name__}.{name} is missing")
    return getattr(module, name)


import hashlib
import shutil

PIN = "ca8c0445a56712c92dc028e68845b94963fdd590"
HASHES = {
    "qse/distributions/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "qse/distributions/fitters/garch_t_fitter.py": "d02be4d7d11178a555303fadaadcfdef3c47a5244e0f381480a8186d0799cce9",
    "qse/distributions/garch_recursion.py": "97c9f7eed011eb8df3db3b3aa8cca685733248ccf92e9b25e6c9b1c68b5e3a69",
    "qse/distributions/joint/__init__.py": "e2dd0cee15e71c61ab38444f41179b2ca2d8a7317af6ccb75e6cbf55b7b66ef6",
    "qse/distributions/joint/fhs.py": "7922f81c1dc8f2feadd31482b19118f87e635eaddf1966c1b970301ba5b48ecb",
    "qse/distributions/joint/panel_fit.py": "077b3abad539857ff9b8e67026732f1215603f1dd40b3d0ce0e73ef96ffb0bd3",
    "qse/distributions/joint/portfolio.py": "5a0462ae0c06653cf33148aa27128418b34626754fd733474a15ab0e1b50695d",
    "qse/distributions/models.py": "c4e84c36a0e69261df134b6b69f56bf4a452304d7e658a6e766dcbbcc3576c8b",
    "qse/distributions/validation/stationarity.py": "932f3c822798e86755eb5992f12c02203d087787149127f9b856835e28e7f27c",
    "qse/exceptions.py": "f67c482bd96bb31ce9f4b77186d1d07620011ce17a191e2fd8c63afdea19bb77",
}


def _canonical(root):
    lock = json.loads((root / "qse/qse.lock.json").read_text())
    assert lock["commit"] == PIN
    assert lock["source"] == "automateintelligence/quant-scenario-engine"
    assert lock["files"] == HASHES
    for name, expected in HASHES.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name


def test_a_se_01_qse_source_and_guard(tmp_path):
    if _inner():
        return
    script = ROOT / "scripts/sync_qse.py"
    assert script.is_file(), "A-SE-01: the actual pinned-source sync entry point is absent"
    _canonical(ROOT)
    tracked = subprocess.run(
        ["git", "ls-files", "qse"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert set(tracked.stdout.splitlines()) == set(HASHES) | {
        "qse/README.md",
        "qse/qse.lock.json",
    }
    deny = json.loads((ROOT / ".claude/settings.json").read_text())["permissions"]["deny"]
    assert "Edit(/qse/**)" in deny and "Write(/qse/**)" in deny

    source, destination = tmp_path / "upstream", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    for name in HASHES:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(source), *args], capture_output=True, check=True
        ).stdout

    git("init", "-q")
    git("add", "qse")
    git(
        "-c",
        "user.name=Gate fixture",
        "-c",
        "user.email=gate@example.invalid",
        "commit",
        "-qm",
        "Pinned source fixture",
    )
    fixture_pin = git("rev-parse", "HEAD").decode().strip()
    changed = source / "qse/exceptions.py"
    changed.write_bytes(changed.read_bytes() + b"\n# dirty working tree must be ignored\n")
    before_status = git("status", "--porcelain=v1", "--untracked-files=all")
    before_bytes = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*.py")}

    def sync(*args):
        return subprocess.run(
            [
                sys.executable,
                str(script),
                *args,
                "--qse-dir",
                str(source),
                "--root",
                str(destination),
            ],
            capture_output=True,
            text=True,
        )

    result = sync("--commit", fixture_pin)
    assert result.returncode == 0, result.stdout + result.stderr
    lock = json.loads((destination / "qse/qse.lock.json").read_text())
    assert lock["commit"] == fixture_pin
    assert set(lock["files"]) == set(HASHES)
    for name in HASHES:
        expected = git("show", fixture_pin + ":" + name)
        assert (destination / name).read_bytes() == expected
        assert lock["files"][name] == hashlib.sha256(expected).hexdigest()
        assert (destination / name).stat().st_mode & 0o222 == 0
    assert sync("--check").returncode == 0
    corrupt = destination / "qse/exceptions.py"
    corrupt.chmod(0o644)
    corrupt.write_bytes(corrupt.read_bytes() + b"\n# drift\n")
    assert sync("--check").returncode != 0, "The real guard accepted a changed source byte"
    assert sync("--commit", fixture_pin).returncode == 0
    rogue = destination / "qse/distributions/unlisted.py"
    rogue.write_text("def hidden_model(): return 0\n")
    assert sync("--check").returncode != 0, "The guard accepted implementation outside the lock"
    rogue.unlink()
    assert sync("--commit", fixture_pin).returncode == 0
    for name in HASHES:
        assert (destination / name).read_bytes() == git("show", fixture_pin + ":" + name)
    assert git("status", "--porcelain=v1", "--untracked-files=all") == before_status
    assert {
        str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*.py")
    } == before_bytes
    assert sync().returncode != 0, "An unpinned sync must be rejected"

    forged = tmp_path / "forged"
    shutil.copytree(ROOT / "qse", forged / "qse")
    target = forged / "qse/exceptions.py"
    target.chmod(0o644)
    target.write_bytes(target.read_bytes() + b"\n# forged model\n")
    forged_lock = json.loads((forged / "qse/qse.lock.json").read_text())
    forged_lock["files"]["qse/exceptions.py"] = hashlib.sha256(target.read_bytes()).hexdigest()
    (forged / "qse/qse.lock.json").chmod(0o644)
    (forged / "qse/qse.lock.json").write_text(json.dumps(forged_lock))
    with pytest.raises(AssertionError):
        _canonical(forged)  # Frozen upstream hashes reject self-consistent local forgery.
