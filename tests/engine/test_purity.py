"""The engine is pure: no I/O imports, no file access, nothing from the data layer."""

from __future__ import annotations

import ast

from tests.engine.helpers import ROOT

ENGINE = ROOT / "portfoliosight" / "engine"
FORBIDDEN_ROOTS = {"requests", "boto3", "urllib", "socket", "pathlib", "http", "os", "subprocess"}
EXPECTED = {
    "builder",
    "caps",
    "invariants",
    "optimize",
    "stats",
    "stress",
    "suggest",
    "surface",
    "tensor",
    "torsion",
    "windows",
}
PRAGMA = "pragma: " + "no cover"


def _violations(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:  # relative: stays inside the engine unless it climbs out of it
                if node.level > 1:
                    found.append(f"line {node.lineno}: import from above the engine package")
                continue
            names = [module] + [f"{module}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if called in {"open", "__import__", "import_module"}:
                found.append(f"line {node.lineno}: {called}( call")
        for name in names:
            parts = name.split(".")
            if parts[0] in FORBIDDEN_ROOTS or parts[:2] == ["portfoliosight", "data"]:
                found.append(f"line {getattr(node, 'lineno', 0)}: imports {name}")
    return found


def test_scanner_catches_each_forbidden_form():
    dirty = [
        "import requests",
        "import urllib.request",
        "from urllib import parse",
        "import boto3 as b",
        "from socket import socket",
        "from pathlib import Path",
        "import os",
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
        assert _violations(source), source
    clean = "import numpy as np\nfrom .stats import ew_weights\nfrom . import ENGINE_VERSION\n"
    assert not _violations(clean)


def test_engine_modules_do_no_io():
    modules = sorted(path for path in ENGINE.glob("*.py") if path.name != "__init__.py")
    assert {path.stem for path in modules} == EXPECTED and len(modules) >= 8
    for path in [*modules, ENGINE / "__init__.py"]:
        source = path.read_text(encoding="utf-8")
        assert not _violations(source), f"{path.name}: {_violations(source)}"
        assert PRAGMA not in source, f"{path.name} excludes lines from coverage"
        assert "TYPE_CHECKING" not in source, f"{path.name} hides imports from coverage"
    assert (ENGINE / "tensor.schema.json").is_file()
