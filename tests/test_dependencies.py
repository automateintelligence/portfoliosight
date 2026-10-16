"""The shared dependency contract of spec §12 Step P."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

RUNTIME_IMPORTS = (
    "numpy",
    "pandas",
    "pyarrow",
    "scipy",
    "sklearn",
    "cvxpy",
    "clarabel",
    "requests",
    "pydantic",
    "boto3",
    "exchange_calendars",
    "jsonschema",
    "threadpoolctl",
    "arch",
    "fastapi",
    "uvicorn",
    "pytest",
    "pytest_cov",
    "responses",
    "moto",
    "httpx",
)
RESEARCH_ONLY = ("yfinance", "matplotlib", "plotly", "skfolio")


def _project() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def _names(requirements: list[str]) -> set[str]:
    """Normalized distribution names of a requirement list."""
    names = set()
    for requirement in requirements:
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
        assert match, f"unparseable requirement {requirement!r}"
        names.add(re.sub(r"[-_.]+", "-", match.group(1)).lower())
    return names


@pytest.mark.parametrize("module", RUNTIME_IMPORTS)
def test_runtime_imports(module: str) -> None:
    assert importlib.import_module(module) is not None


def test_research_extra_isolated() -> None:
    project = _project()
    extras = project["optional-dependencies"]
    research = _names(extras["research"])
    for package in RESEARCH_ONLY:
        assert package in research, f"{package} is missing from the research extra"
    groups = {
        "dependencies": project["dependencies"],
        "api": extras["api"],
        "dev": extras["dev"],
    }
    for group, requirements in groups.items():
        leaked = sorted(set(RESEARCH_ONLY) & _names(requirements))
        assert not leaked, f"{leaked} appear under {group}"


def test_yfinance_absent_from_api_dev_venv() -> None:
    assert importlib.util.find_spec("yfinance") is None


def test_requires_python() -> None:
    assert _project()["requires-python"] == ">=3.12"


def test_arch_is_pinned_exact() -> None:
    # Its optimizer decides the fitted parameters, so the tensor bytes (spec 12, Fit library).
    assert "arch==8.0.0" in _project()["dependencies"]


# What QSE's copied files may pull in: numpy, pandas, scipy, statsmodels and arch, and what those
# declare. QSE's own dependency list carries torch and xgboost; none of them may be needed here.
QSE_ROOTS = ("numpy", "scipy", "pandas", "statsmodels", "arch")
NEVER_PULLED = (
    "torch",
    "xgboost",
    "numba",
    "sklearn",
    "cvxpy",
    "matplotlib",
    "plotly",
    "pydantic",
)
# A fit of a 300-row GARCH(1,1) series runs `arch`'s lazy import. The child runs it twice.
# Blocked: it starts with only the standard library, this checkout's `qse` and the packages of the
# closure, every other installed module set to None, so a hard dependency outside the closure fails
# the fit (sufficiency). Unblocked: nothing is set to None, as in an ordinary import, and none of
# NEVER_PULLED may load. The unblocked leg cannot require "only the closure": pandas soft-imports
# pyarrow when it is installed, pyarrow soft-imports cloudpickle, and numpy's f2py soft-imports
# charset_normalizer. Those are optional imports of the closure packages themselves, which the
# blocked leg proves the fit does not need. The child imports only the standard library before
# `qse`, so it loads nothing of NEVER_PULLED itself. It reports every top-level package loaded
# from site-packages during the import and the fit, and every top-level module name in
# `sys.modules` at the end.
QSE_CHILD = """
import json, sys, sysconfig
from pathlib import Path
root, blocked = sys.argv[1], json.loads(sys.argv[2])
sys.path.insert(0, root)
for name in blocked:
    sys.modules.setdefault(name, None)
before = set(sys.modules)
import numpy as np
from qse.distributions.joint import fit_garch_t_panel
rng = np.random.default_rng(7)
shocks = rng.standard_t(6, size=300) / np.sqrt(6 / 4)
omega, alpha, beta = 2e-6, 0.08, 0.9
variance, series = omega / (1 - alpha - beta), []
for shock in shocks:
    series.append(np.sqrt(variance) * shock)
    variance = omega + alpha * series[-1] ** 2 + beta * variance
fit = fit_garch_t_panel(np.column_stack([series, series[::-1]]))
assert "arch" in sys.modules, "the fit did not reach arch"
sites = {Path(sysconfig.get_paths()[key]).resolve() for key in ("purelib", "platlib")}
tops = set()
for name in set(sys.modules) - before:
    file = getattr(sys.modules[name], "__file__", None)
    if not file:
        continue
    path = Path(file).resolve()
    tops.update(
        path.relative_to(site).parts[0].split(".")[0] for site in sites if site in path.parents
    )
modules = sorted({name.split(".")[0] for name in sys.modules})
print(json.dumps({"tops": sorted(tops), "modules": modules, "status": list(fit.status),
                  "messages": fit.messages}))
"""


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _closure(roots: tuple[str, ...]) -> set[str]:
    """Normalized names of the roots and of everything they require that is installed."""
    seen: set[str] = set()
    todo = [_normalized(name) for name in roots]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        try:
            requires = importlib.metadata.requires(name) or []
        except importlib.metadata.PackageNotFoundError:
            continue
        seen.add(name)
        for text in requires:
            requirement = Requirement(text)
            if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
                continue
            todo.append(_normalized(requirement.name))
    return seen


def _run_qse_child(blocked: list[str]) -> dict:
    done = subprocess.run(
        [sys.executable, "-I", "-c", QSE_CHILD, str(ROOT), json.dumps(blocked)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_qse_import_closure() -> None:
    owners = importlib.metadata.packages_distributions()
    allowed = _closure(QSE_ROOTS)
    assert set(QSE_ROOTS) <= allowed
    blocked = sorted(
        module
        for module, dists in owners.items()
        if module != "qse" and not any(_normalized(dist) in allowed for dist in dists)
    )
    # The probe must really hide what QSE's own dependency list would bring.
    assert set(NEVER_PULLED) & set(owners) <= set(blocked)
    report = _run_qse_child(blocked)
    assert report["status"] == ["garch", "garch"], report["messages"]
    tops = set(report["tops"])
    unowned = sorted(tops - set(owners))
    assert not unowned, f"loaded from site-packages without an installed distribution: {unowned}"
    imported = {_normalized(dist) for top in tops for dist in owners[top]}
    assert not sorted(imported - allowed), (
        f"beyond {QSE_ROOTS} and what they declare: {imported - allowed}"
    )
    assert {"numpy", "pandas", "scipy", "arch", "statsmodels"} <= tops
    assert not set(NEVER_PULLED) & tops

    # An ordinary import, nothing blocked: the same fit, and nothing of NEVER_PULLED loads.
    plain = _run_qse_child([])
    assert plain["status"] == report["status"], plain["messages"]
    assert {"numpy", "pandas", "scipy", "arch", "statsmodels"} <= set(plain["tops"])
    loaded = sorted(set(NEVER_PULLED) & (set(plain["modules"]) | set(plain["tops"])))
    assert not loaded, f"an ordinary import of qse.distributions.joint loads {loaded}"
