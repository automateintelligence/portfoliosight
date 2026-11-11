"""A-SE-02 (contract): isolated import closure and actual fit/build/API/validation denial.
Runs this frozen file in a fresh isolated Python interpreter, with declared runtime dependency
closure plus pytest/httpx as test transport. No install, credential read or network is allowed.
Backtest CLI pin follows Phase 1 plan: compare --store-dir --menus --lookbacks --engines --out.
"""

from __future__ import annotations

import importlib
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


import ast
import builtins
import importlib.abc
import importlib.metadata
import runpy
import socket


def _frozen_store(directory):
    """Frozen nontrivial returns and canonical records; no mutable fixture helper."""
    np, pd = _need("numpy"), _need("pandas")
    sm = _need("portfoliosight.data.store")
    manifest_mod = _need("portfoliosight.data.manifest")
    store = sm.LocalStore(directory)
    ids = [
        "VTI",
        "VTV",
        "VOE",
        "VB",
        "VBR",
        "VEA",
        "SCHF",
        "VWO",
        "VNQ",
        "VBIAX",
        "SCHO",
        "BND",
        "AGG",
        "TIP",
        "VTIP",
        "LQD",
        "VWOB",
        "PCY",
        "EFA",
        "LTPZ",
        "EDV",
        "VGSTX",
        "DBJP",
        "TSP-G",
        "TSP-F",
        "TSP-C",
        "TSP-S",
        "TSP-I",
        "SGOV",
    ]
    days = pd.bdate_range("2005-01-03", "2026-10-12", name="date")
    rng = np.random.default_rng(20261013)
    factors = rng.normal(size=(len(days), 3))
    manifest = manifest_mod.Manifest()
    for j, fid in enumerate(ids):
        if fid in ("TSP-G", "SGOV"):
            returns = np.full(len(days), 0.035 / 252)
        else:
            # Correlated funds with distinct level, volatility, idiosyncratic noise and tails.
            vol = 0.035 + 0.007 * (j % 19)
            loading = np.array([0.65, 0.2 * ((j % 3) - 1), 0.15])
            returns = (0.025 + 0.002 * (j % 13)) / 252 + (
                factors @ loading + rng.standard_t(7, len(days)) * 0.45
            ) * vol / np.sqrt(252)
        active = days >= (pd.Timestamp("2020-05-28") if fid == "SGOV" else days[0])
        calendar, daily = days[active], returns[active]
        growth = np.r_[1.0, np.cumprod(1 + daily)]
        stamps = pd.DatetimeIndex([calendar[0] - pd.offsets.BDay(1)]).append(calendar)
        record = pd.DataFrame(
            {
                "date": stamps,
                "close": growth * 100,
                "tr_index": growth,
                "div_cash": np.zeros(len(stamps)),
                "split_factor": np.ones(len(stamps)),
            }
        )
        sm.put_record(store, fid, record)
        manifest.symbols[fid] = manifest_mod.ManifestEntry(
            name="Frozen " + fid,
            kind="tsp" if fid.startswith("TSP-") else "etf",
            tier=1,
            source="tsp" if fid.startswith("TSP-") else "seed",
            status="ok",
            first_date=stamps[0].date(),
            last_date=stamps[-1].date(),
            adjusted_through=stamps[-1].date(),
            fetched_at="2026-10-13T09:05:11Z",
        )
    sm.put_json(store, "meta/manifest.json", manifest.to_json())
    return store


def _store(tmp_path, monkeypatch):
    stores = _need("portfoliosight.data.store")
    version = _need("portfoliosight.engine").ENGINE_VERSION
    store = _frozen_store(tmp_path / "store")
    asof = _need("pandas").Timestamp("2026-10-12").date()
    generation = f"{asof.isoformat()}-{version}"
    stores.put_json(
        store,
        f"meta/{generation}/generation.json",
        {"generation": generation, "asof": asof.isoformat(), "engine_version": version},
    )
    stores.put_json(
        store,
        f"meta/{generation}/presets.json",
        {"generation": generation, "asof": asof.isoformat(), "presets": []},
    )
    stores.put_json(
        store,
        "meta/current.json",
        {"generation": generation, "published_at": "2026-10-13T09:30:00+00:00"},
    )
    monkeypatch.setenv("PS_GATE_SECRET", "frozen-gate-local-0123456789")
    monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PS_BUILD_WORKERS", "1")
    return store, asof, generation


def _isolated_probe(scratch):
    """Executed in a fresh process: record attempted access even when product catches it."""
    import tomllib

    from packaging.requirements import Requirement
    from packaging.utils import canonicalize_name

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    direct = [Requirement(s) for s in project["dependencies"]]
    arch = [r for r in direct if canonicalize_name(r.name) == "arch"]
    assert len(arch) == 1 and str(arch[0].specifier) == "==8.0.0", "arch must be exactly pinned"
    forbidden = {"torch", "xgboost", "quant-scenario-engine", "qse"}
    direct_names = {canonicalize_name(r.name) for r in direct}
    assert not direct_names & forbidden
    baseline = {
        "numpy",
        "pandas",
        "pyarrow",
        "scipy",
        "scikit-learn",
        "cvxpy",
        "clarabel",
        "requests",
        "pydantic",
        "boto3",
        "exchange-calendars",
        "jsonschema",
        "threadpoolctl",
    }
    assert direct_names <= baseline | {"arch", "pyvinecopulib"}, (
        "Integration introduced undeclared model dependencies"
    )
    # All QSE-facing production imports must stay on the permitted distribution surface.
    for folder in (ROOT / "portfoliosight", ROOT / "scripts"):
        for path in folder.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
                modules = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                for name in modules:
                    if name == "qse" or name.startswith("qse."):
                        assert name == "qse.distributions" or name.startswith(
                            "qse.distributions."
                        ), (path, name)
    pending = (
        [str(r) for r in direct]
        + project.get("optional-dependencies", {}).get("api", [])
        + ["pytest", "httpx"]
    )
    allowed = set()
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker and not requirement.marker.evaluate():
            continue
        name = canonicalize_name(requirement.name)
        if name in allowed:
            continue
        allowed.add(name)
        distribution = importlib.metadata.distribution(requirement.name)
        assert distribution.version in requirement.specifier, (
            f"Installed {name} violates its declaration"
        )
        pending.extend(distribution.requires or [])
    assert not allowed & forbidden
    mapping = importlib.metadata.packages_distributions()
    # Prepare local objects before installing the runtime denial hook. Only this scratch repo
    # can subsequently be read by sync; git writes/network are never permitted by the hook.
    upstream = scratch / "upstream"
    upstream.mkdir()
    lock = __import__("json").loads((ROOT / "qse/qse.lock.json").read_text())
    for name in lock["files"]:
        path = upstream / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(upstream), *args], capture_output=True, check=True
        ).stdout

    git("init", "-q")
    git("add", "qse")
    git(
        "-c",
        "user.name=Isolation gate",
        "-c",
        "user.email=gate@example.invalid",
        "commit",
        "-qm",
        "Local source fixture",
    )
    pin = git("rev-parse", "HEAD").decode().strip()
    before = git("status", "--porcelain=v1", "--untracked-files=all")
    attempted = []

    class DependencyBoundary(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            top = fullname.split(".")[0]
            if fullname.startswith("qse.") and not (
                fullname == "qse.exceptions" or fullname.startswith("qse.distributions")
            ):
                attempted.append(("import", fullname))
                raise ImportError("QSE surface forbidden")
            if top in {"torch", "xgboost"}:
                attempted.append(("dependency", fullname))
                raise ImportError("Forbidden heavy dependency")
            if top not in {"qse", "portfoliosight"} and top in mapping:
                providers = {canonicalize_name(name) for name in mapping[top]}
                if not providers & allowed:
                    raise ImportError("Outside declared runtime closure")
            return None

    sys.meta_path.insert(0, DependencyBoundary())
    # Python's audit hook sees attempted operations below wrappers and cannot be hidden by catching.
    forbidden_paths = (
        "quant-scenario-engine",
        "/.secrets/",
        "/.aws/",
        "/mnt/d/",
        "/lake/",
        "qse-daily-pipeline.lock",
    )

    def audit(event, args):
        if (
            event
            in {
                "open",
                "os.listdir",
                "os.scandir",
                "os.remove",
                "os.rename",
                "os.mkdir",
            }
            and args
        ):
            name = str(args[0])
            if any(part in name for part in forbidden_paths):
                attempted.append((event, name))
                raise PermissionError("Forbidden source/credential/data access")
            if event == "open" and len(args) > 1:
                mode = args[1]
                flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
                writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or flags & (
                    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC
                )
                if writes and not Path(name).resolve().is_relative_to(scratch):
                    attempted.append(("write outside temporary store", name))
                    raise PermissionError("Test permits only its temporary store")
        if event == "subprocess.Popen":
            argv = args[1]
            allowed_git = (
                isinstance(argv, (list, tuple))
                and len(argv) >= 4
                and argv[:3] == ["git", "-C", str(upstream)]
                and argv[3] in {"cat-file", "rev-parse", "status"}
            )
            if allowed_git:
                return
        if event in {
            "socket.connect",
            "socket.getaddrinfo",
            "subprocess.Popen",
            "os.system",
        }:
            attempted.append((event, repr(args)))
            raise PermissionError(
                "Network and subprocess provider routes forbidden during engine execution"
            )

    sys.dont_write_bytecode = True
    sys.addaudithook(audit)
    # These forbidden controls prove the hook is active; erase only these deliberate probes.
    with pytest.raises(PermissionError):
        builtins.open("/nonexistent/.secrets/provider.env")
    with pytest.raises(PermissionError):
        socket.getaddrinfo("provider.invalid", 443)
    assert len(attempted) == 2
    attempted.clear()
    mp = pytest.MonkeyPatch()
    try:
        sync_script = ROOT / "scripts/sync_qse.py"
        assert sync_script.is_file()
        sync = runpy.run_path(str(sync_script))
        assert (
            sync["main"](
                [
                    "--commit",
                    pin,
                    "--qse-dir",
                    str(upstream),
                    "--root",
                    str(scratch / "synced"),
                ]
            )
            == 0
        )
        assert git("status", "--porcelain=v1", "--untracked-files=all") == before
        assert not attempted, f"Sync attempted forbidden data/credential access: {attempted}"
        store, asof, generation = _store(scratch, mp)
        builder = _need("portfoliosight.engine.builder")
        _attr(builder, "build_tensor_full")
        jobs = _need("portfoliosight.jobs.build")
        inputs = jobs.inputs_from_store(
            store,
            funds=[
                {"id": i, "min": 0.0, "max": 1.0}
                for i in ("TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I")
            ],
            lookback="1y",
            asof=asof,
            cache_dir=scratch / "cache",
            preset_id="tsp",
            nx=4,
            ny=4,
            levels=3,
            engines=("replay", "garch"),
        )
        result, _ = _attr(jobs, "build_with_artifacts")(
            store, generation, inputs, cache_dir=scratch / "cache", workers=1
        )
        tensor = result.tensor
        assert tensor["engines"]["garch"]["status"] == "ready"
        assert result.models["garch"].panel.shape == (2000, 252, 5)
        assert "garch" in result.artifacts and result.artifacts["garch"].pool_rows >= 126
        jobs.put_tensor(store, f"tensors/{generation}/{tensor['universe']['hash']}/1y.json", tensor)
        TestClient = _need("fastapi.testclient").TestClient
        create_app = _need("portfoliosight.api.app").create_app
        with TestClient(create_app(store=store, start_worker=False)) as client:
            response = client.post(
                "/v1/range",
                json={
                    "generation": generation,
                    "hash": tensor["universe"]["hash"],
                    "lookback": "1y",
                    "engine": "garch",
                    "weights": [0.1, 0.2, 0.3, 0.2, 0.2],
                },
                headers={
                    "x-ps-gate": "frozen-gate-local-0123456789",
                    "cf-connecting-ip": "192.0.2.2",
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["engine"] == "garch"
            assert response.json()["bad"] < response.json()["good"]
        script = ROOT / "scripts/backtest_ranges.py"
        assert script.is_file(), (
            "Actual validation entry point is required, not a replacement test calculation"
        )
        previous = sys.argv
        sys.argv = [
            str(script),
            "compare",
            "--store-dir",
            str(scratch / "store"),
            "--menus",
            "tsp",
            "--lookbacks",
            "1y",
            "--engines",
            "replay,garch",
            "--out",
            str(scratch / "validation"),
        ]
        try:
            try:
                runpy.run_path(str(script), run_name="__main__")
            except SystemExit as exc:
                assert exc.code in (None, 0), f"Validation failed: {exc.code}"
        finally:
            sys.argv = previous
        products = list(scratch.glob("validation*"))
        assert products, "The actual comparison must emit its result"
        assert not attempted, f"Forbidden operations were attempted even if caught: {attempted}"
        assert not {"torch", "xgboost"} & set(sys.modules)
        for name, module in list(sys.modules.items()):
            if name.startswith("qse.") and getattr(module, "__file__", None):
                assert Path(module.__file__).resolve().is_relative_to(ROOT / "qse")
    finally:
        mp.undo()
    print("ISOLATION_PROBE_COMPLETE: fit tensor range validation; forbidden attempts=0")


def test_a_se_02_distribution_and_data_boundary(tmp_path):
    if _inner():
        return
    # Fail in the test body before launching expensive work when Phase 1 is absent.
    _attr(_need("portfoliosight.engine.builder"), "build_tensor_full")
    command = (
        "import runpy,sys;sys.path.insert(0,"
        + repr(str(ROOT))
        + ");d=runpy.run_path("
        + repr(str(Path(__file__).resolve()))
        + ");d['_isolated_probe'](d['Path']("
        + repr(str(tmp_path))
        + "))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        env={
            k: v
            for k, v in os.environ.items()
            if not any(
                s in k.upper()
                for s in (
                    "SECRET",
                    "TOKEN",
                    "PASSWORD",
                    "API_KEY",
                    "ACCESS_KEY",
                    "AWS_",
                )
            )
        },
    )
    assert result.returncode == 0, result.stdout[-10000:] + result.stderr[-6000:]
    assert (
        "ISOLATION_PROBE_COMPLETE: fit tensor range validation; forbidden attempts=0"
        in result.stdout
    )
