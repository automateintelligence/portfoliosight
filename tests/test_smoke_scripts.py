"""The smoke runners read their settings from the env file and spell no host (run rules 4, 15)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef"
RUNNERS = {
    "smoke.sh": [
        "playwright",
        "test",
        "e2e/smoke.spec.ts",
        "--project",
        "chromium-desktop",
        "--project",
        "chromium-phone",
        "--workers",
        "1",
    ],
    "smoke_preview.sh": [
        "playwright",
        "test",
        "e2e/preview.spec.ts",
        "--project",
        "chromium-desktop",
        "--workers",
        "1",
    ],
}


def _run(script: str, tmp_path: Path, settings: str | None, *args: str):
    """Runs a runner with a fake ``npx`` first on PATH that records its arguments and settings."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "record"
    fake = bin_dir / "npx"
    fake.write_text(
        "#!/bin/sh\n"
        f'{{ pwd; echo "$PS_SMOKE|${{PS_SMOKE_DRY_RUN-unset}}|$PS_BASE_URL"; '
        f'[ "$PS_GATE_SECRET" = "{SECRET}" ] && echo secret-exported; '
        f'for a in "$@"; do echo "$a"; done; }} > "{record}"\n'
    )
    fake.chmod(0o755)
    env_file = tmp_path / "settings.env"
    if settings is not None:
        env_file.write_text(settings)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "PS_ENV_FILE": str(env_file),
        "PS_SMOKE_DRY_RUN": "1",
    }
    proc = subprocess.run(
        [str(ROOT / "scripts" / script), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc, record.read_text().splitlines() if record.exists() else None


@pytest.mark.parametrize("script", sorted(RUNNERS))
def test_runner_starts_playwright_from_web_with_the_settings(script, tmp_path):
    settings = f"export PS_BASE_URL=http://site.test\nPS_GATE_SECRET={SECRET}\n"
    proc, seen = _run(script, tmp_path, settings, "-g", "DoD-0[1-3]")
    assert proc.returncode == 0, proc.stderr
    assert seen is not None
    assert seen[0] == str(ROOT / "web")
    # a production run: local servers off, and never the local dry run
    assert seen[1] == "1|unset|http://site.test"
    assert seen[2] == "secret-exported"
    assert seen[3:] == [*RUNNERS[script], "-g", "DoD-0[1-3]"]
    assert SECRET not in proc.stdout + proc.stderr


@pytest.mark.parametrize("script", sorted(RUNNERS))
@pytest.mark.parametrize(
    ("settings", "named"),
    [
        (None, "settings.env"),
        (f"PS_GATE_SECRET={SECRET}\n", "PS_BASE_URL"),
        ("PS_BASE_URL=http://site.test\n", "PS_GATE_SECRET"),
    ],
)
def test_runner_stops_before_playwright_when_a_setting_is_missing(
    script, settings, named, tmp_path
):
    proc, seen = _run(script, tmp_path, settings)
    assert proc.returncode == 3
    assert seen is None, "Playwright was started without its settings"
    assert named in proc.stderr
    assert SECRET not in proc.stdout + proc.stderr


@pytest.mark.parametrize("script", sorted(RUNNERS))
def test_runner_spells_no_host(script):
    text = (ROOT / "scripts" / script).read_text()
    assert "://" not in text
    assert "portfoliosight.ai" not in text
