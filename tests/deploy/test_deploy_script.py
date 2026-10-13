"""scripts/deploy_ks001.sh against a fake ssh: what it sends, and what it never sends."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy_ks001.sh"
SHA = "0123456789abcdef0123456789abcdef01234567"
FAKE_SSH = (
    "#!/bin/sh\n"
    'for a in "$@"; do echo "ARG $a"; done > "$LOG/ssh.args"\n'
    'cat > "$LOG/ssh.stdin"\n'
    'exit "${SSH_EXIT:-0}"\n'
)
LAPTOP_SECRET = "laptop-gate-secret-must-not-travel"


class Box:
    def __init__(self, base: Path):
        self.home, self.bin, self.log = base / "home", base / "bin", base / "log"
        for folder in (self.home / ".secrets", self.bin, self.log):
            folder.mkdir(parents=True)
        self.env_file = self.home / ".secrets" / "portfoliosight.env"
        self.env_file.write_text(
            "PS_KS001_SSH_HOST=box-alias\n"
            'export PS_HEALTH_URL="scheme://health.invalid:8010/v1/health"\n'
            f"PS_GATE_SECRET={LAPTOP_SECRET}\n"
        )
        fake = self.bin / "ssh"
        fake.write_text(FAKE_SSH)
        fake.chmod(0o755)

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        environment = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "LOG": str(self.log),
            **env,
        }
        return subprocess.run(
            ["bash", str(SCRIPT), *args], env=environment, capture_output=True, text=True
        )

    def ssh_args(self) -> list[str]:
        lines = (self.log / "ssh.args").read_text().splitlines()
        return [line.removeprefix("ARG ") for line in lines]

    def remote_script(self) -> str:
        return (self.log / "ssh.stdin").read_text()

    def called(self) -> bool:
        return (self.log / "ssh.args").exists()


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


def test_deploy_sends_the_spec_chain_to_the_host_from_the_env_file(box):
    done = box.run(SHA)
    assert done.returncode == 0, done.stderr
    host, command = box.ssh_args()
    assert host == "box-alias"
    assert command == f"bash -s -- {SHA} scheme://health.invalid:8010/v1/health 0 "
    remote = box.remote_script()
    steps = [
        'cd "${HOME}/portfoliosight"',
        "git fetch github",
        'git checkout --detach "${sha}"',
        "printf 'GIT_SHA=%s\\n' \"${sha}\" > deploy/.env",
        'docker compose -f "${compose}" build',
        'docker compose -f "${compose}" up -d api',
        '-H @- "${health_url}"',
    ]
    positions = [remote.index(step) for step in steps]
    assert positions == sorted(positions)
    assert 'compose="deploy/docker-compose.yml"' in remote
    # The gate secret is read on the host and reaches curl on stdin, not as an argument.
    assert "x-ps-gate: %s" in remote and 'env_file="${HOME}/.secrets/portfoliosight.env"' in remote
    assert "gate_header | curl" in remote
    sent = " ".join(box.ssh_args()) + remote + done.stdout + done.stderr
    assert LAPTOP_SECRET not in sent


def test_host_and_health_url_can_come_from_the_environment_or_a_flag(box):
    done = box.run(
        "--host", "other-alias", SHA[:12], PS_HEALTH_URL="scheme://elsewhere.invalid/v1/health"
    )
    assert done.returncode == 0
    host, command = box.ssh_args()
    assert host == "other-alias"
    assert command == f"bash -s -- {SHA[:12]} scheme://elsewhere.invalid/v1/health 0 "
    box.run(SHA, PS_KS001_SSH_HOST="env-alias")
    assert box.ssh_args()[0] == "env-alias"


def test_install_timer_renders_the_unit_from_the_host_account(box):
    assert box.run("--install-timer", SHA).returncode == 0
    assert box.ssh_args()[1].endswith(" 1 ")
    remote = box.remote_script()
    assert "s|__USER__|${USER}|g" in remote and "s|__HOME__|${HOME}|g" in remote
    assert "sudo tee /etc/systemd/system/portfoliosight-nightly.service" in remote
    assert "sudo systemctl enable --now portfoliosight-nightly.timer" in remote
    assert 'if [ "${install_timer}" = 1 ]; then' in remote


def test_health_url_is_quoted_for_the_remote_shell(box):
    box.run(SHA, PS_HEALTH_URL="scheme://h.invalid/v1/health?a=1;touch /tmp/x")
    command = box.ssh_args()[1]
    assert r"\;touch\ /tmp/x" in command and ";touch /tmp/x" not in command


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["not-a-sha"],
        ["ABCDEF0123"],
        ["0123456; rm -rf /"],
        [SHA, SHA],
        ["--host"],
        ["--force", SHA],
    ],
)
def test_bad_arguments_are_refused_before_ssh(box, args):
    done = box.run(*args)
    assert done.returncode == 64 and "usage: deploy_ks001.sh" in done.stderr
    assert not box.called()


def test_missing_settings_stop_the_deploy(box):
    box.env_file.write_text("PS_GATE_SECRET=x\n")
    done = box.run(SHA)
    assert done.returncode == 3 and "deploy not run" in done.stderr and not box.called()
    box.env_file.unlink()
    assert box.run(SHA).returncode == 3
    assert box.run(SHA, PS_ENV_FILE=str(box.home / "nowhere.env")).returncode == 3


def test_a_failed_remote_run_fails_the_deploy(box):
    assert box.run(SHA, SSH_EXIT="1").returncode == 1


def test_script_names_no_host_user_or_address():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "://" not in text and "/home/" not in text and "KS-001-" not in text
    assert os.access(SCRIPT, os.X_OK)
