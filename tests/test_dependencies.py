"""The shared dependency contract of spec §12 Step P."""

from __future__ import annotations

import importlib
import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

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
