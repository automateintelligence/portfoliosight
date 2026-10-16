"""The built image: uid 10001, the package and committed data under /app, nothing personal.

The build context is made as a checkout under a restrictive umask (007) leaves it, because the
image must not depend on the modes of the host's files.

Built only when a docker daemon answers; without one the ignore rules of
``tests/deploy/test_dockerignore.py`` stand in, as spec 10 allows.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CSV = "data/holdings/holdings_guide2017_step2.csv"
PLANTED = ("data/holdings/personal_test.csv", "runs/x", ".venv/planted.cfg", "web/dist/planted.js")


def _docker(*args: str, timeout: int = 900, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, **kwargs
    )


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return _docker("info", timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(scope="module")
def image(tmp_path_factory: pytest.TempPathFactory):
    """An image built from a copy of the tree with personal files planted, or ``None``."""
    if not _docker_available():
        yield None
        return
    context = tmp_path_factory.mktemp("image-context") / "tree"
    for name in ("pyproject.toml", "README.md", ".dockerignore"):
        context.mkdir(exist_ok=True)
        shutil.copy2(ROOT / name, context / name)
    for folder in ("portfoliosight", "qse", "data", "deploy"):
        shutil.copytree(
            ROOT / folder,
            context / folder,
            ignore=shutil.ignore_patterns("__pycache__", ".local-store", ".env"),
        )
    for name in PLANTED:
        planted = context / name
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_text("planted by tests/deploy/test_image.py\n")
    for path in context.rglob("*"):
        path.chmod(0o770)
    tag = f"ps-unit-image:{uuid.uuid4().hex[:12]}"
    built = _docker(
        "build", "-q", "-f", str(context / "deploy" / "Dockerfile"), "-t", tag, ".", cwd=context
    )
    assert built.returncode == 0, built.stderr[-3000:]
    yield tag
    _docker("rmi", "-f", tag, timeout=120)


def _run(tag: str, *command: str) -> subprocess.CompletedProcess:
    return _docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        command[0],
        tag,
        *command[1:],
        timeout=180,
    )


def test_image_runs_as_uid_10001_and_owns_only_its_cache(image):
    if image is None:
        return
    assert _run(image, "id", "-u").stdout.strip() == "10001"
    owners = _run(image, "stat", "-c", "%u %n", "/app/cache", "/app/portfoliosight", "/app/data")
    assert owners.stdout.split("\n")[:3] == [
        "10001 /app/cache",
        "0 /app/portfoliosight",
        "0 /app/data",
    ]
    assert _run(image, "sh", "-c", "touch /app/portfoliosight/x").returncode != 0
    assert _run(image, "sh", "-c", "touch /app/cache/x").returncode == 0


def test_image_files_do_not_carry_the_modes_of_the_build_host(image):
    if image is None:
        return
    closed = _run(image, "find", "/app/portfoliosight", "/app/data", "!", "-perm", "-o=r")
    assert closed.returncode == 0 and closed.stdout.strip() == "", closed.stdout[:500]
    shut = _run(
        image, "find", "/app/portfoliosight", "/app/data", "-type", "d", "!", "-perm", "-o=x"
    )
    assert shut.returncode == 0 and shut.stdout.strip() == "", shut.stdout[:500]
    loose = _run(image, "find", "/app/portfoliosight", "/app/data", "-perm", "/go=w")
    assert loose.returncode == 0 and loose.stdout.strip() == "", loose.stdout[:500]
    read = _run(image, "python", "-c", "open('/app/data/presets.json').read()")
    assert read.returncode == 0, read.stderr


def test_image_holds_the_package_and_committed_data_and_no_planted_file(image):
    if image is None:
        return
    listing = _run(image, "find", "/app", "-type", "f").stdout.splitlines()
    files = {line.removeprefix("/app/") for line in listing}
    assert {CSV, "data/presets.json", "data/universes/tiers.json"} <= files
    assert "portfoliosight/api/app.py" in files and "portfoliosight/jobs/nightly.py" in files
    assert [name for name in files if name.startswith("data/holdings/")] == [CSV]
    assert all(name.startswith(("portfoliosight/", "data/")) for name in files), sorted(files)[:5]
    assert not [name for name in files if name.endswith(".pyc")]
    assert "planted" not in "\n".join(listing)


def test_image_imports_the_service_from_app_and_needs_a_secret_to_start(image):
    if image is None:
        return
    where = _run(
        image, "python", "-c", "import portfoliosight, sys; print(portfoliosight.__file__)"
    )
    assert where.stdout.strip() == "/app/portfoliosight/__init__.py", where.stderr
    imports = _run(
        image, "python", "-c", "import portfoliosight.api.app, portfoliosight.jobs.nightly"
    )
    assert imports.returncode == 0, imports.stderr
    refused = _run(image, "python", "-c", "from portfoliosight.api.app import app")
    assert refused.returncode != 0 and "PS_GATE_SECRET" in refused.stderr
    env = _run(image, "env")
    assert "SECRET" not in env.stdout and "API_KEY" not in env.stdout


def test_image_imports_qse_from_site_packages_and_carries_its_lock(image):
    if image is None:
        return
    done = _run(
        image,
        "python",
        "-c",
        "import json, importlib.resources as r, qse.distributions.joint as j, arch; "
        "print(j.__file__); "
        "print(json.loads(r.files('qse').joinpath('qse.lock.json').read_text())['commit'])",
    )
    assert done.returncode == 0, done.stderr
    where, commit = done.stdout.split()
    lock = json.loads((ROOT / "qse" / "qse.lock.json").read_text(encoding="utf-8"))
    assert where.startswith("/usr/local/lib/python3.12/site-packages/qse/"), where
    assert commit == lock["commit"]
