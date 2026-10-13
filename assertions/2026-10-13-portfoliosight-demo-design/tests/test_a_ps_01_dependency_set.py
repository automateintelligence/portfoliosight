"""A-PS-01 — the shared dependency set installs, imports and lints.

Claim: a fresh virtual environment built from the committed pyproject.toml with
`uv pip install -e ".[api,dev]"` imports every runtime and dev dependency the spec names, passes
the committed ruff and pyright configuration, collects tests without error, and confines yfinance
to the `research` extra.

Pinned interface (the product must provide exactly this): `pyproject.toml` at the repo root with
`[project].dependencies`, `[project.optional-dependencies]` extras `api`, `dev`, `research`,
a `[tool.ruff]` table and a pyright configuration (`[tool.pyright]` or `pyrightconfig.json`);
`ruff` and `pyright` installed by the `dev` extra. `ruff check .`, `ruff format --check .` and
`pyright .` run over the whole repository from its root, so the committed configuration decides
what they see (the frozen gate tests under `assertions/` included, unless it excludes them).
pyright is run as `pyright -p <repo root> .`: with a path argument alone pyright 1.1.414 does not
apply the project's configuration, and the claim is about the committed configuration.
Needs `uv` on PATH and network access for the install.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = ROOT / "pyproject.toml"

IMPORTS = (
    "numpy, pandas, pyarrow, scipy, sklearn, cvxpy, clarabel, requests, pydantic, boto3, "
    "exchange_calendars, fastapi, uvicorn, pytest, pytest_cov, responses, moto, httpx"
)
RESEARCH_ONLY = ("yfinance", "matplotlib", "plotly", "skfolio")

_STATE: dict = {}


def _child_env(venv: Path | None = None) -> dict:
    env = dict(os.environ)
    for name in ("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PS_GATE_INNER", "VIRTUAL_ENV", "PYTHONPATH"):
        env.pop(name, None)
    env.pop("PYTHONHOME", None)
    if venv is not None:
        env["VIRTUAL_ENV"] = str(venv)
        env["PATH"] = str(venv / "bin") + os.pathsep + env.get("PATH", "")
    return env


def _run(cmd, *, timeout, cwd=ROOT, env=None):
    """Run a command; a missing binary or a timeout is a clean test failure."""
    try:
        return subprocess.run(
            [str(c) for c in cmd],
            cwd=cwd,
            env=env if env is not None else _child_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        pytest.fail(f"A-PS-01 red: cannot run {cmd[0]}: {exc}")
    except subprocess.TimeoutExpired:
        pytest.fail(f"A-PS-01 red: {' '.join(str(c) for c in cmd[:4])} ... timed out ({timeout}s)")


def _tail(proc, n=3000) -> str:
    return (proc.stdout[-n:] + "\n" + proc.stderr[-n:]).strip()


def _fresh_venv() -> dict:
    """Leg (1), built once per session: a clean venv plus the editable `[api,dev]` install."""
    if _STATE:
        return _STATE
    if shutil.which("uv") is None:
        _STATE["error"] = "`uv` is not on PATH (needed to build the fresh virtualenv)"
        return _STATE
    if not PYPROJECT.is_file():
        _STATE["error"] = "pyproject.toml is missing at the repository root"
        return _STATE
    tmp = Path(tempfile.mkdtemp(prefix="ps-gate-a01-"))
    _STATE["tmp"] = tmp
    venv = tmp / "venv"
    made = _run(["uv", "venv", venv], timeout=300)
    py = venv / "bin" / "python"
    if made.returncode != 0 or not py.exists():
        _STATE["error"] = f"`uv venv` failed (rc {made.returncode}): {_tail(made, 1500)}"
        return _STATE
    install = _run(
        ["uv", "pip", "install", "--python", py, "-e", ".[api,dev]"], timeout=900, env=_child_env()
    )
    _STATE.update(venv=venv, py=py, install=install)
    return _STATE


def _venv_or_fail() -> dict:
    state = _fresh_venv()
    if "error" in state:
        pytest.fail(f"A-PS-01 red: {state['error']}")
    install = state["install"]
    assert install.returncode == 0, (
        f'A-PS-01 red: `uv pip install -e ".[api,dev]"` exited {install.returncode}:\n'
        + _tail(install)
    )
    return state


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    tmp = _STATE.get("tmp")
    if tmp is not None:
        shutil.rmtree(tmp, ignore_errors=True)


def _load_pyproject() -> dict:
    if not PYPROJECT.is_file():
        pytest.fail("A-PS-01 red: pyproject.toml is missing at the repository root")
    loads = None
    for name in ("tomllib", "tomli", "pip._vendor.tomli"):
        try:
            loads = __import__(name, fromlist=["loads"]).loads
            break
        except Exception:
            continue
    if loads is None:
        pytest.fail("A-PS-01 red: no TOML parser (tomllib, tomli, pip._vendor.tomli) is importable")
    try:
        return loads(PYPROJECT.read_text(encoding="utf-8"))
    except Exception as exc:
        pytest.fail(f"A-PS-01 red: pyproject.toml does not parse: {exc}")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _req_names(requirements, project: str) -> set[str]:
    """Normalized distribution names of a requirement list; `project[extra]` expands to `@extra`."""
    names: set[str] = set()
    for req in requirements:
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[([^\]]*)\])?", str(req))
        if not match:
            continue
        name = _norm(match.group(1))
        names.add(name)
        if name == project and match.group(3):
            names.update("@" + _norm(e.strip()) for e in match.group(3).split(","))
    return names


def test_leg1_install_exits_zero():
    state = _venv_or_fail()
    extras = _load_pyproject().get("project", {}).get("optional-dependencies", {})
    assert "api" in extras and "dev" in extras, (
        f"A-PS-01 red: pyproject.toml must define the `api` and `dev` extras; found {sorted(extras)}"
    )
    out = (state["install"].stdout + state["install"].stderr).lower()
    assert "does not have an extra" not in out and "extra named" not in out, (
        "A-PS-01 red: the install reported an unknown extra:\n" + _tail(state["install"], 1500)
    )
    listing = _run(["uv", "pip", "list", "--python", state["py"]], timeout=120)
    assert "portfoliosight" in listing.stdout.lower(), "A-PS-01 red: the project is not installed"


def test_leg2_every_named_dependency_imports():
    state = _venv_or_fail()
    proc = _run(
        [state["py"], "-c", f"import {IMPORTS}"], timeout=300, env=_child_env(state["venv"])
    )
    assert proc.returncode == 0, (
        "A-PS-01 red: a named dependency does not import in the fresh [api,dev] venv:\n"
        + proc.stderr[-1500:]
    )


def test_leg3_ruff_and_pyright_pass_with_committed_config():
    state = _venv_or_fail()
    venv = state["venv"]
    env = _child_env(venv)
    data = _load_pyproject()
    tool = data.get("tool", {})
    assert "ruff" in tool or (ROOT / "ruff.toml").is_file(), (
        "A-PS-01 red: no committed ruff configuration"
    )
    assert "pyright" in tool or (ROOT / "pyrightconfig.json").is_file(), (
        "A-PS-01 red: no committed pyright configuration ([tool.pyright] or pyrightconfig.json)"
    )
    for tool_name in ("ruff", "pyright"):
        assert (venv / "bin" / tool_name).exists(), (
            f"A-PS-01 red: the `dev` extra did not install `{tool_name}` into the fresh venv"
        )
    ruff = venv / "bin" / "ruff"

    shown = _run([ruff, "check", "--show-files", "."], timeout=120, env=env)
    files = [Path(line.strip()) for line in shown.stdout.splitlines() if line.strip()]
    product = [f for f in files if "portfoliosight" in f.parts and f.suffix == ".py"]
    product = [f for f in product if "assertions" not in f.parts]
    assert product, "A-PS-01 red: the ruff configuration checks no file under portfoliosight/"

    check = _run([ruff, "check", "."], timeout=300, env=env)
    assert check.returncode == 0, "A-PS-01 red: `ruff check .` failed:\n" + _tail(check)
    fmt = _run([ruff, "format", "--check", "."], timeout=300, env=env)
    assert fmt.returncode == 0, "A-PS-01 red: `ruff format --check .` failed:\n" + _tail(fmt)

    pyright = _run(
        [venv / "bin" / "pyright", "-p", ROOT, "--pythonpath", state["py"], "--outputjson", "."],
        timeout=600,
        env=env,
    )
    try:
        summary = json.loads(pyright.stdout)["summary"]
    except Exception:
        pytest.fail("A-PS-01 red: `pyright .` printed no JSON summary:\n" + _tail(pyright, 1500))
    assert pyright.returncode == 0, (
        f"A-PS-01 red: `pyright .` exited {pyright.returncode} with {summary.get('errorCount')} "
        "error(s):\n" + pyright.stdout[-3000:]
    )
    assert summary.get("errorCount") == 0
    assert summary.get("filesAnalyzed", 0) != 0, "A-PS-01 red: pyright analysed no file"


def test_leg4_pytest_collects_without_error():
    state = _venv_or_fail()
    proc = _run(
        [state["py"], "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        timeout=600,
        env=_child_env(state["venv"]),
    )
    assert proc.returncode in (0, 5), (
        f"A-PS-01 red: `pytest --collect-only -q` exited {proc.returncode}:\n" + _tail(proc)
    )
    error_lines = [
        line
        for line in (proc.stdout + "\n" + proc.stderr).splitlines()
        if re.match(r"\s*(=+ )?ERRORS?\b", line)
    ]
    assert not error_lines, f"A-PS-01 red: collection printed ERROR lines: {error_lines[:5]}"


def test_leg5_research_packages_only_in_research_extra():
    data = _load_pyproject()
    project = data.get("project", {})
    name = _norm(project.get("name", ""))
    dynamic = project.get("dynamic", [])
    assert "dependencies" not in dynamic and "optional-dependencies" not in dynamic, (
        "A-PS-01 red: dependencies must be static in pyproject.toml so they can be checked"
    )
    extras = project.get("optional-dependencies", {})
    assert "research" in extras, "A-PS-01 red: pyproject.toml has no `research` extra"
    research = _req_names(extras["research"], name)
    missing = [pkg for pkg in RESEARCH_ONLY if pkg not in research]
    assert not missing, f"A-PS-01 red: the `research` extra lacks {missing}"

    groups = {"dependencies": project.get("dependencies", [])}
    groups.update({k: v for k, v in extras.items() if k != "research"})
    for group in data.get("dependency-groups", {}).items():
        groups["dependency-groups." + group[0]] = [r for r in group[1] if isinstance(r, str)]
    assert "api" in groups and "dev" in groups, "A-PS-01 red: `api` and `dev` extras are required"
    for group_name, requirements in groups.items():
        names = _req_names(requirements, name)
        leaked = [pkg for pkg in RESEARCH_ONLY if pkg in names]
        assert not leaked, f"A-PS-01 red: {leaked} appear under `{group_name}`, not only `research`"
        assert "@research" not in names, (
            f"A-PS-01 red: `{group_name}` pulls in the `research` extra by self-reference"
        )


def test_leg6_yfinance_is_absent_from_the_api_dev_venv():
    state = _venv_or_fail()
    proc = _run([state["py"], "-c", "import yfinance"], timeout=120, env=_child_env(state["venv"]))
    assert proc.returncode != 0, (
        "A-PS-01 red: `import yfinance` succeeds in the [api,dev] venv; the research extra is "
        "not really separate"
    )
    assert "ModuleNotFoundError" in proc.stderr, (
        "A-PS-01 red: `import yfinance` failed for another reason than its absence:\n"
        + proc.stderr[-800:]
    )
