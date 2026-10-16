"""The selected pull of QSE code (spec 3 item 3, 13 item 18, S9, M2): lock, guard, read-only.

The repository tests read the real `qse/` tree and its lock. The script's own behaviour is tested
on a throwaway git repository made in `tmp_path` and on copies of `qse/`; the real QSE checkout is
never opened here.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_qse.py"
QSE_DIR = ROOT / "qse"
LOCK = QSE_DIR / "qse.lock.json"
PIN = "ca8c0445a56712c92dc028e68845b94963fdd590"
SOURCE = "automateintelligence/quant-scenario-engine"
FILES = (
    "qse/distributions/__init__.py",
    "qse/distributions/joint/__init__.py",
    "qse/distributions/joint/fhs.py",
    "qse/distributions/joint/panel_fit.py",
    "qse/distributions/joint/portfolio.py",
    "qse/distributions/fitters/garch_t_fitter.py",
    "qse/distributions/garch_recursion.py",
    "qse/distributions/validation/stationarity.py",
    "qse/distributions/models.py",
    "qse/exceptions.py",
)
READ_ONLY = 0o444
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "tester",
    "GIT_AUTHOR_EMAIL": "tester@example.invalid",
    "GIT_COMMITTER_NAME": "tester",
    "GIT_COMMITTER_EMAIL": "tester@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sync_qse", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _lock() -> dict:
    return json.loads(LOCK.read_text(encoding="utf-8"))


def _run_script(
    *args: str | Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        capture_output=True,
        text=True,
        env=env if env is not None else GIT_ENV,
        cwd=ROOT,
    )


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, env=GIT_ENV, check=True
    )
    return done.stdout.strip()


# ------------------------------------------------------------- the repository's own tree


def test_the_script_copies_exactly_the_ten_files():
    assert tuple(_load_script().FILES) == FILES


def test_lock_records_the_plan_pin_and_the_source():
    lock = _lock()
    assert re.fullmatch(r"[0-9a-f]{40}", lock["commit"])
    assert lock["commit"] == PIN
    assert lock["source"] == SOURCE
    assert set(lock) == {"source", "commit", "files"}


def test_lock_names_the_ten_files_and_each_hashes_to_its_entry():
    files = _lock()["files"]
    assert tuple(sorted(files)) == tuple(sorted(FILES))
    for name, digest in files.items():
        path = ROOT / name
        assert path.is_file(), name
        assert re.fullmatch(r"[0-9a-f]{64}", digest), name
        assert _sha256(path) == digest, f"{name} differs from the lock: re-run scripts/sync_qse.py"


def test_lock_file_is_sorted_json_with_a_trailing_newline():
    text = LOCK.read_text(encoding="utf-8")
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"


def test_no_python_file_under_qse_is_outside_the_lock():
    named = set(_lock()["files"])
    found = {
        path.relative_to(ROOT).as_posix()
        for path in QSE_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    assert found == named


def test_the_directories_the_script_does_not_copy_stay_namespace_packages():
    # QSE has no qse/__init__.py or fitters/__init__.py, and validation/__init__.py imports
    # outside the closure; adding any of them here would change what `import qse` does.
    for missing in (
        "qse/__init__.py",
        "qse/distributions/fitters/__init__.py",
        "qse/distributions/validation/__init__.py",
    ):
        assert not (ROOT / missing).exists(), missing


def test_the_lock_sits_beside_the_qse_packages_that_get_installed():
    # `qse` is a namespace package, and `importlib.resources.files("qse")` refuses the extra
    # path entry that an editable install gives it; `qse.distributions` is a regular package.
    resource = importlib.resources.files("qse.distributions").joinpath("..", "qse.lock.json")
    assert json.loads(resource.read_text(encoding="utf-8")) == _lock()


def test_packaging_and_lint_config_cover_qse():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    tool = config["tool"]
    assert tool["setuptools"]["packages"]["find"]["include"] == ["portfoliosight*", "qse*"]
    assert tool["setuptools"]["package-data"]["qse"] == ["qse.lock.json"]
    assert "qse" in tool["ruff"]["extend-exclude"]
    assert "qse" in tool["pyright"]["exclude"]


def test_readme_names_the_rule_the_pin_and_the_three_layers():
    readme = (QSE_DIR / "README.md").read_text(encoding="utf-8")
    assert PIN in readme and "qse.lock.json" in readme
    assert "scripts/sync_qse.py --commit" in readme and "--check" in readme
    # agents, disk, backstop
    assert ".claude/settings.json" in readme
    assert "chmod a-w" in readme
    assert "tests/test_qse_sync.py" in readme
    assert "pre-commit" in readme


def test_agent_settings_deny_edit_and_write_under_qse():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    deny = settings["permissions"]["deny"]
    assert "Edit(/qse/**)" in deny and "Write(/qse/**)" in deny


def test_script_names_no_url_and_no_literal_home_path():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "http://" not in text and "https://" not in text
    assert "/home/" not in text and "/Users/" not in text


# ------------------------------------------------------------------- --check on a copy


@pytest.fixture
def copy_root(tmp_path: Path) -> Path:
    root = tmp_path / "copy"
    root.mkdir()
    shutil.copytree(QSE_DIR, root / "qse", ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _edit(path: Path, data: bytes) -> None:
    path.chmod(0o644)
    path.write_bytes(data)


def test_check_passes_on_a_faithful_copy_and_makes_every_listed_file_read_only(copy_root: Path):
    for name in FILES:
        (copy_root / name).chmod(0o644)  # what a fresh clone looks like
    done = _run_script("--check", "--root", copy_root)
    assert done.returncode == 0, done.stdout + done.stderr
    for name in FILES:
        assert _mode(copy_root / name) == READ_ONLY, name


def test_check_fails_after_one_byte_changes_and_names_the_file(copy_root: Path):
    target = copy_root / "qse/distributions/garch_recursion.py"
    data = bytearray(target.read_bytes())
    data[0] ^= 0x01
    _edit(target, bytes(data))
    done = _run_script("--check", "--root", copy_root)
    assert done.returncode == 1
    assert "qse/distributions/garch_recursion.py" in done.stdout + done.stderr
    others = [name for name in FILES if name != "qse/distributions/garch_recursion.py"]
    assert not any(name in done.stdout + done.stderr for name in others)
    assert _mode(target) == READ_ONLY  # the drift is reported and the file is closed again


def test_check_reports_a_missing_file(copy_root: Path):
    (copy_root / "qse/exceptions.py").unlink()
    done = _run_script("--check", "--root", copy_root)
    assert done.returncode == 1 and "qse/exceptions.py" in done.stdout + done.stderr


def test_check_reports_a_python_file_the_lock_does_not_name(copy_root: Path):
    (copy_root / "qse/distributions/extra.py").write_text("x = 1\n")
    (copy_root / "qse/distributions/fitters").mkdir(exist_ok=True)
    (copy_root / "qse/distributions/fitters/__init__.py").write_text("")
    done = _run_script("--check", "--root", copy_root)
    out = done.stdout + done.stderr
    assert done.returncode == 1
    assert "qse/distributions/extra.py" in out
    assert "qse/distributions/fitters/__init__.py" in out


def test_check_reports_every_drift_not_only_the_first(copy_root: Path):
    _edit(copy_root / "qse/exceptions.py", b"changed\n")
    _edit(copy_root / "qse/distributions/models.py", b"changed\n")
    done = _run_script("--check", "--root", copy_root)
    out = done.stdout + done.stderr
    assert done.returncode == 1
    assert "qse/exceptions.py" in out and "qse/distributions/models.py" in out


def test_check_fails_without_a_lock(copy_root: Path):
    (copy_root / "qse" / "qse.lock.json").unlink()
    done = _run_script("--check", "--root", copy_root)
    assert done.returncode == 1 and "qse.lock.json" in done.stdout + done.stderr


def test_check_fails_when_the_lock_and_the_script_disagree_on_the_files(copy_root: Path):
    lock_path = copy_root / "qse" / "qse.lock.json"
    lock = json.loads(lock_path.read_text())
    lock["files"].pop("qse/exceptions.py")
    _edit(lock_path, json.dumps(lock, indent=2, sort_keys=True).encode() + b"\n")
    done = _run_script("--check", "--root", copy_root)
    assert done.returncode == 1 and "qse/exceptions.py" in done.stdout + done.stderr


def test_check_takes_no_commit_and_a_sync_needs_one(copy_root: Path):
    assert _run_script("--check", "--commit", PIN, "--root", copy_root).returncode == 2
    assert _run_script("--root", copy_root).returncode == 2
    assert _run_script("--commit", "abc123", "--root", copy_root).returncode == 2
    assert _run_script("--commit", PIN.upper(), "--root", copy_root).returncode == 2


# ------------------------------------------------ --commit against a throwaway git repository


def _blob(name: str, generation: int) -> bytes:
    if name == "qse/distributions/__init__.py":
        return b""  # empty at the pin, and it has to stay empty
    return f"# {name} v{generation}\r\nvalue = {generation}\r\n".encode() + b"\xff\xfe\n"


@pytest.fixture
def qse_repo(tmp_path: Path) -> dict:
    """A tiny repository that has the ten paths in two commits and a dirty working tree."""
    repo = tmp_path / "qse-checkout"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    shas = []
    for generation in (1, 2):
        for name in FILES:
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_blob(name, generation))
        (repo / "qse/other.py").write_text(f"other = {generation}\n")
        _git(repo, "add", "-A")
        _git(
            repo, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", str(generation)
        )
        shas.append(_git(repo, "rev-parse", "HEAD"))
    (repo / "qse/exceptions.py").write_text("DIRTY WORKING TREE\n")
    (repo / "untracked.txt").write_text("untracked\n")
    return {"repo": repo, "first": shas[0], "second": shas[1]}


def _sync(qse_repo: dict, root: Path, sha: str) -> subprocess.CompletedProcess:
    return _run_script("--commit", sha, "--qse-dir", qse_repo["repo"], "--root", root)


def test_commit_writes_the_commits_bytes_the_lock_and_closes_the_files(
    qse_repo: dict, tmp_path: Path
):
    root = tmp_path / "ps"
    root.mkdir()
    status_before = _git(qse_repo["repo"], "status", "--porcelain")
    done = _sync(qse_repo, root, qse_repo["first"])
    assert done.returncode == 0, done.stdout + done.stderr
    for name in FILES:
        assert (root / name).read_bytes() == _blob(name, 1), name
        assert _mode(root / name) == READ_ONLY, name
    assert not (root / "qse/other.py").exists()  # only the ten files
    lock_text = (root / "qse" / "qse.lock.json").read_text(encoding="utf-8")
    assert lock_text == json.dumps(json.loads(lock_text), indent=2, sort_keys=True) + "\n"
    lock = json.loads(lock_text)
    assert lock["source"] == SOURCE and lock["commit"] == qse_repo["first"]
    assert lock["files"] == {
        name: hashlib.sha256(_blob(name, 1)).hexdigest() for name in sorted(FILES)
    }
    # The QSE working tree (a dirty file, an untracked one) is never read or touched.
    assert _git(qse_repo["repo"], "status", "--porcelain") == status_before
    assert (qse_repo["repo"] / "qse/exceptions.py").read_text() == "DIRTY WORKING TREE\n"
    assert _run_script("--check", "--root", root).returncode == 0


def test_a_second_sync_replaces_read_only_files_with_the_new_pin(qse_repo: dict, tmp_path: Path):
    root = tmp_path / "ps"
    root.mkdir()
    assert _sync(qse_repo, root, qse_repo["first"]).returncode == 0
    done = _sync(qse_repo, root, qse_repo["second"])
    assert done.returncode == 0, done.stdout + done.stderr
    for name in FILES:
        assert (root / name).read_bytes() == _blob(name, 2), name
        assert _mode(root / name) == READ_ONLY, name
    assert json.loads((root / "qse" / "qse.lock.json").read_text())["commit"] == qse_repo["second"]
    assert _run_script("--check", "--root", root).returncode == 0


def test_the_qse_dir_comes_from_the_environment_when_not_given(qse_repo: dict, tmp_path: Path):
    root = tmp_path / "ps"
    root.mkdir()
    env = {**GIT_ENV, "PS_QSE_DIR": str(qse_repo["repo"])}
    done = _run_script("--commit", qse_repo["first"], "--root", root, env=env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (root / "qse/exceptions.py").read_bytes() == _blob("qse/exceptions.py", 1)


def test_an_unknown_commit_exits_3_and_writes_nothing(qse_repo: dict, tmp_path: Path):
    root = tmp_path / "ps"
    root.mkdir()
    done = _sync(qse_repo, root, "0" * 40)
    assert done.returncode == 3
    assert "fetch" in done.stderr and "github" in done.stderr
    assert list(root.iterdir()) == []


def test_a_path_missing_at_the_commit_writes_nothing(qse_repo: dict, tmp_path: Path):
    repo = qse_repo["repo"]
    (repo / "qse/exceptions.py").unlink()
    _git(repo, "add", "-A")
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", "drop")
    sha = _git(repo, "rev-parse", "HEAD")
    root = tmp_path / "ps"
    root.mkdir()
    done = _sync(qse_repo, root, sha)
    assert done.returncode == 4 and "qse/exceptions.py" in done.stderr
    assert list(root.iterdir()) == []


def test_a_directory_that_is_not_a_repository_is_refused(tmp_path: Path):
    root = tmp_path / "ps"
    root.mkdir()
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    done = _run_script("--commit", PIN, "--qse-dir", not_a_repo, "--root", root)
    assert done.returncode == 3 and list(root.iterdir()) == []


# ------------------------------------- a root or a destination that reaches the QSE checkout


def _snapshot(tree: Path) -> dict[str, tuple[int, bytes]]:
    """Mode and bytes of every file under `tree` (not following links), `.git` excluded."""
    return {
        path.relative_to(tree).as_posix(): (_mode(path), path.read_bytes())
        for path in sorted(tree.rglob("*"))
        if ".git" not in path.relative_to(tree).parts and path.is_file()
    }


@pytest.mark.parametrize("where", ["the checkout", "inside the checkout", "a link to it"])
def test_a_root_in_the_qse_checkout_is_refused_before_anything_is_written(
    qse_repo: dict, tmp_path: Path, where: str
):
    repo = qse_repo["repo"]
    if where == "the checkout":
        root = repo
    elif where == "inside the checkout":
        root = repo / "sub"
        root.mkdir()
    else:
        root = tmp_path / "link"
        root.symlink_to(repo, target_is_directory=True)
    before = _snapshot(repo)
    status_before = _git(repo, "status", "--porcelain")
    for args in (
        ("--commit", qse_repo["first"], "--qse-dir", repo, "--root", root),
        ("--check", "--qse-dir", repo, "--root", root),
    ):
        done = _run_script(*args)
        assert done.returncode == 2, done.stdout + done.stderr
        assert "QSE checkout" in done.stderr and "Traceback" not in done.stderr
    assert _snapshot(repo) == before
    assert _git(repo, "status", "--porcelain") == status_before


def test_a_qse_checkout_inside_the_root_is_refused(qse_repo: dict, tmp_path: Path):
    # The fixture's checkout lives at tmp_path/qse-checkout, so tmp_path contains it.
    repo = qse_repo["repo"]
    before = _snapshot(repo)
    done = _sync(qse_repo, tmp_path, qse_repo["first"])
    assert done.returncode == 2 and "QSE checkout" in done.stderr
    assert not (tmp_path / "qse").exists()
    assert _snapshot(repo) == before


@pytest.mark.parametrize(
    "link",
    [
        "qse",
        "qse/distributions",
        "qse/distributions/joint",
        "qse/exceptions.py",
        "qse/qse.lock.json",
    ],
)
def test_a_destination_that_is_a_link_is_refused_by_sync_and_check(
    qse_repo: dict, tmp_path: Path, link: str
):
    # Each link points into a stand-in for a working tree outside the root: an open copy.
    outside = tmp_path / "outside"
    shutil.copytree(QSE_DIR, outside / "qse", ignore=shutil.ignore_patterns("__pycache__"))
    for path in (outside / "qse").rglob("*"):
        if path.is_file():
            path.chmod(0o644)
    root = tmp_path / "ps"
    shutil.copytree(outside, root)
    target = root / link
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    target.symlink_to(outside / link, target_is_directory=(outside / link).is_dir())
    before = _snapshot(outside)
    for args in (
        ("--commit", qse_repo["first"], "--qse-dir", qse_repo["repo"], "--root", root),
        ("--check", "--qse-dir", qse_repo["repo"], "--root", root),
    ):
        done = _run_script(*args)
        assert done.returncode == 2, done.stdout + done.stderr
        assert "link" in done.stderr and link in done.stderr
        assert "Traceback" not in done.stderr
    assert _snapshot(outside) == before


def test_a_destination_with_a_second_hard_link_is_refused(qse_repo: dict, tmp_path: Path):
    # A hard link writes through to the other name's bytes and mode, as a symbolic link would.
    root = tmp_path / "ps"
    assert _sync(qse_repo, root, qse_repo["first"]).returncode == 0
    other = tmp_path / "other.py"
    os.link(root / "qse/exceptions.py", other)
    other.chmod(0o644)
    for args in (
        ("--commit", qse_repo["second"], "--qse-dir", qse_repo["repo"], "--root", root),
        ("--check", "--qse-dir", qse_repo["repo"], "--root", root),
    ):
        done = _run_script(*args)
        assert done.returncode == 2 and "qse/exceptions.py" in done.stderr, done.stderr
    assert other.read_bytes() == _blob("qse/exceptions.py", 1) and _mode(other) == 0o644


def test_check_reports_lock_entries_outside_the_ten_and_never_reads_or_closes_them(
    copy_root: Path, tmp_path: Path
):
    # Write-only files: a read raises, a close (chmod a-w) changes the mode.
    absolute = tmp_path / "absolute.py"
    parent = tmp_path / "parent.py"
    inside = copy_root / "qse/distributions/inside.py"
    for path in (absolute, parent, inside):
        path.write_text("x = 1\n")
        path.chmod(0o200)
    lock_path = copy_root / "qse" / "qse.lock.json"
    lock = json.loads(lock_path.read_text())
    entries = (str(absolute), "../parent.py", "qse/../../parent.py", "qse/distributions/inside.py")
    for entry in entries:
        lock["files"][entry] = "0" * 64
    _edit(lock_path, json.dumps(lock, indent=2, sort_keys=True).encode() + b"\n")
    done = _run_script("--check", "--root", copy_root)
    assert done.returncode == 1, done.stdout + done.stderr
    assert "Traceback" not in done.stderr
    for entry in entries:
        assert f"drift: {entry}: " in done.stdout, entry
    for path in (absolute, parent, inside):
        assert _mode(path) == 0o200, path
