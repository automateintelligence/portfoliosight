"""A-PS-13 — the R2 store verify passes against portfoliosight-data (LIVE).

Claim: `python -m portfoliosight.data.store --verify` against the real bucket performs
head_bucket, put/get/delete of meta/_probe, and a list, and exits 0.

Pinned interface (the product must provide exactly this):
- `python -m portfoliosight.data.store --verify`, run from the repo root with `PS_STORE=r2` and
  `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY` in
  the environment (the caller loads `~/.secrets/portfoliosight.env`). Exit 0 on success, non-zero
  when any operation fails (bad credentials included).
- Its output (stdout or stderr) names the bucket `portfoliosight-data` and reports each of the
  operations `head_bucket`, `put`, `get`, `delete`, `list` on its own line, the operation name
  followed on that line by `ok` or `passed` (any letter case), and no line reports a failure.
  It overwrites and then deletes `meta/_probe`, and never prints a secret value.

Live legs: the test plants its own object at `meta/_probe` first (so a verify that does nothing
cannot leave the key absent), checks afterwards with its own boto3 client that the key is gone,
and runs the verify once more with made-up credentials, which must not exit 0. The spec's
"403 names the missing scope" leg cannot be forced against the live bucket and is not encoded.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


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


_VENV_PY = _project_python()
_OUTER = (
    os.environ.get("PS_GATE_INNER") != "1"
    and _VENV_PY is not None
    and Path(sys.prefix).resolve() != _VENV_PY.parents[1].resolve()
)


def _need(module: str):
    """Import a product (or dev-dependency) module, failing the test cleanly when it is absent."""
    try:
        return importlib.import_module(module)
    except Exception as exc:  # ImportError, or an import-time crash in the product
        pytest.fail(f"A-PS-13 red: cannot import {module}: {type(exc).__name__}: {exc}")


BUCKET = "portfoliosight-data"
PROBE_KEY = "meta/_probe"
REQUIRED = (
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
)
SECRET_NAMES = (
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
    "CLOUDFLARE_API_TOKEN",
    "TIINGO_API_KEY",
    "PS_GATE_SECRET",
)
OPERATIONS = ("head_bucket", "put", "get", "delete", "list")
PLANTED = b"planted by gate test A-PS-13; the store verify must delete this object\n"


def _scrub(text: str) -> str:
    """Remove every secret value from text before it can reach a failure message."""
    for name in (*SECRET_NAMES, "CLOUDFLARE_ACCOUNT_ID"):
        value = os.environ.get(name, "")
        if len(value) >= 6:
            text = text.replace(value, f"<{name}>")
    return text


def _require_env() -> None:
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        pytest.fail(
            "A-PS-13 red: environment variable(s) not set: "
            + ", ".join(missing)
            + " (load ~/.secrets/portfoliosight.env before running the gate)"
        )


def _client():
    boto3 = _need("boto3")
    config = _need("botocore.config").Config(
        connect_timeout=15, read_timeout=30, retries={"max_attempts": 3}
    )
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['CLOUDFLARE_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"],
        config=config,
    )


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None) or {}
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode", "")
    return f"{type(exc).__name__} code={code or '?'} http={status or '?'}"


def _probe_exists(client) -> bool:
    try:
        client.head_object(Bucket=BUCKET, Key=PROBE_KEY)
        return True
    except Exception as exc:
        response = getattr(exc, "response", None) or {}
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 404:
            return False
        pytest.fail(f"A-PS-13 red: cannot check {PROBE_KEY} in {BUCKET}: {_error_code(exc)}")


def _run_verify(extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    env = dict(os.environ, PS_STORE="r2", **extra_env)
    env.pop("PS_GATE_INNER", None)
    env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    try:
        return subprocess.run(
            [sys.executable, "-m", "portfoliosight.data.store", "--verify"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=240,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("A-PS-13 red: the store verify did not finish in 240 s")


if _OUTER:

    def test_a_ps_13_in_project_venv():
        env = dict(os.environ, PS_GATE_INNER="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        proc = subprocess.run(
            [
                str(_VENV_PY),
                "-m",
                "pytest",
                "-q",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                __file__,
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        print(proc.stdout[-8000:], proc.stderr[-2000:])
        assert proc.returncode == 0, "A-PS-13 is red inside the project virtualenv (output above)"

else:

    def test_verify_passes_and_really_deletes_the_probe():
        _require_env()
        _need("portfoliosight.data.store")
        client = _client()
        try:
            client.put_object(Bucket=BUCKET, Key=PROBE_KEY, Body=PLANTED)
        except Exception as exc:
            pytest.fail(
                f"A-PS-13 red: the R2 keys cannot write {PROBE_KEY} to {BUCKET} "
                f"({_error_code(exc)}); the bucket must exist and the R2 API token must be "
                "scoped Object Read & Write to it (spec 9.5 step 1)"
            )
        assert _probe_exists(client), "setup: the planted probe is not visible"
        try:
            proc = _run_verify({})
            output = proc.stdout + "\n" + proc.stderr
            shown = _scrub(output)[-3000:]
            code = proc.returncode  # plain values only: pytest prints what an assert compares
            assert code == 0, f"store --verify exited {code}:\n{shown}"
            # Must-not-contain: an exit 0 with the probe still there.
            assert not _probe_exists(client), (
                f"{PROBE_KEY} still exists after a verify that exited 0: the delete did not happen"
            )
            names_bucket = BUCKET in output
            assert names_bucket, f"the verify output does not name the bucket:\n{shown}"
            lines = output.splitlines()
            for operation in OPERATIONS:
                pattern = re.compile(
                    rf"(?<![A-Za-z_]){operation}(?![A-Za-z_]).*\b(ok|passed)\b", re.IGNORECASE
                )
                assert any(pattern.search(line) for line in lines), (
                    f"the verify output has no line reporting {operation} as passed:\n{shown}"
                )
            for line in lines:
                if any(re.search(rf"(?<![A-Za-z_]){op}(?![A-Za-z_])", line) for op in OPERATIONS):
                    bad = bool(re.search(r"\b(fail|failed|failure|error|denied)\b", line, re.I))
                    assert not bad, (
                        f"the verify reports a failed operation although it exited 0: "
                        f"{_scrub(line)!r}"
                    )
            leaked = [
                name
                for name in SECRET_NAMES
                if len(os.environ.get(name, "")) >= 6 and os.environ[name] in output
            ]
            assert not leaked, f"the verify output contains the value of {leaked}"
        finally:
            try:
                client.delete_object(Bucket=BUCKET, Key=PROBE_KEY)
            except Exception:
                pass  # the assertions above already decided the result

    def test_verify_does_not_pass_with_made_up_credentials():
        _require_env()
        _need("portfoliosight.data.store")
        proc = _run_verify(
            {
                "CLOUDFLARE_R2_ACCESS_KEY_ID": "0" * 32,
                "CLOUDFLARE_R2_SECRET_ACCESS_KEY": "0" * 64,
            }
        )
        shown = _scrub(proc.stdout + "\n" + proc.stderr)[-2000:]
        code = proc.returncode
        assert code != 0, (
            f"store --verify exited 0 with made-up R2 credentials: it does not test R2\n{shown}"
        )
