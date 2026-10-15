"""The backup and cron scripts against fake tools on a temporary PATH (spec 5.3; A-PS-11)."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "scripts" / "r2_backup.sh"
INSTALLER = ROOT / "scripts" / "install_backup_cron.sh"
MESSAGE = "D: drive is not mounted at /mnt/d; backup not run"
CRON_LINE = (
    "30 5 * * * $HOME/programming/portfoliosight/scripts/r2_backup.sh"
    " >> $HOME/.local/state/portfoliosight/r2_backup.log 2>&1"
)
SEEDED = [
    "0 5 * * * $HOME/programming/quant-scenario-engine/scripts/backup_lake.sh >> /dev/null 2>&1",
    "15 3 * * 0 /usr/bin/find /var/tmp -name '*.tmp' -mtime +7 -delete  # weekly tidy",
]
FAKES = {
    "mountpoint": '#!/bin/sh\necho "$*" >> "$LOG/mountpoint"\n[ "$MOUNTED" = 1 ]\n',
    "aws": (
        "#!/bin/sh\n"
        '{ for a in "$@"; do echo "ARG $a"; done\n'
        '  echo "KEYID $AWS_ACCESS_KEY_ID"; echo "SECRET $AWS_SECRET_ACCESS_KEY"; } >> "$LOG/aws"\n'
        'exit "${AWS_EXIT:-0}"\n'
    ),
    "mkdir": (
        '#!/bin/sh\necho "$*" >> "$LOG/mkdir"\n'
        'for a in "$@"; do case "$a" in /mnt/*) exit 0 ;; esac; done\nexec /bin/mkdir "$@"\n'
    ),
    "crontab": (
        '#!/bin/sh\necho "$*" >> "$LOG/crontab"\n'
        'case "$1" in\n'
        '  -l) [ -f "$CRONTAB" ] && cat "$CRONTAB" && exit 0; echo "no crontab" >&2; exit 1 ;;\n'
        '  -) cat > "$CRONTAB" ;;\n'
        "  *) exit 2 ;;\n"
        "esac\n"
    ),
}


class Box:
    def __init__(self, base: Path):
        self.home, self.bin, self.log = base / "home", base / "bin", base / "log"
        self.crontab = base / "crontab.txt"
        for folder in (self.home / ".secrets", self.bin, self.log):
            folder.mkdir(parents=True)
        self.env_file = self.home / ".secrets" / "portfoliosight.env"
        self.env_file.write_text(
            "# settings\n"
            "CLOUDFLARE_ACCOUNT_ID=acct123\n"
            "export CLOUDFLARE_R2_ACCESS_KEY_ID='key-id'\n"
            'CLOUDFLARE_R2_SECRET_ACCESS_KEY="secret-key"\n'
            "TIINGO_API_KEY=not-for-aws"
        )
        for name, body in FAKES.items():
            path = self.bin / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run(self, script: Path, *args: str, mounted=True, env_file: Path | None = None, **extra):
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.home),
            "LOG": str(self.log),
            "MOUNTED": "1" if mounted else "0",
            "CRONTAB": str(self.crontab),
            **extra,
        }
        if env_file is not None:
            env["PS_ENV_FILE"] = str(env_file)
        return subprocess.run(
            [str(script), *args], env=env, cwd=self.home, capture_output=True, text=True, timeout=60
        )

    def logged(self, name: str) -> list[str]:
        path = self.log / name
        return path.read_text().splitlines() if path.exists() else []


@pytest.fixture
def box(tmp_path) -> Box:
    return Box(tmp_path)


def test_scripts_are_executable_bash_with_strict_mode():
    for script in (BACKUP, INSTALLER):
        text = script.read_text()
        assert os.access(script, os.X_OK), script.name
        assert text.startswith("#!/usr/bin/env bash\n") and "set -euo pipefail" in text


@pytest.mark.parametrize("args", [(), ("--restore",)])
def test_unmounted_exits_2_and_runs_nothing(box, args):
    proc = box.run(BACKUP, *args, mounted=False)
    assert proc.returncode == 2 and proc.stderr.strip() == MESSAGE
    assert box.logged("mountpoint") == ["-q /mnt/d"]
    assert box.logged("aws") == [] and box.logged("mkdir") == []


def test_backup_mirrors_the_bucket_with_delete(box):
    proc = box.run(BACKUP)
    assert proc.returncode == 0, proc.stderr
    assert box.logged("mkdir") == ["-p /mnt/d/portfoliosight-data"]
    assert box.logged("aws") == [
        "ARG s3",
        "ARG sync",
        "ARG --endpoint-url",
        "ARG https://acct123.r2.cloudflarestorage.com",
        "ARG s3://portfoliosight-data",
        "ARG /mnt/d/portfoliosight-data",
        "ARG --delete",
        "KEYID key-id",
        "SECRET secret-key",
    ]


def test_restore_reverses_the_sync_and_never_deletes(box):
    proc = box.run(BACKUP, "--restore")
    assert proc.returncode == 0, proc.stderr
    args = [line[4:] for line in box.logged("aws") if line.startswith("ARG ")]
    assert args[-2:] == ["/mnt/d/portfoliosight-data", "s3://portfoliosight-data"]
    assert not [arg for arg in args if arg.startswith("--delete")]
    assert box.logged("mountpoint") == ["-q /mnt/d"]


def test_ps_env_file_wins_over_the_home_file(box):
    other = box.home / "other.env"
    other.write_text(box.env_file.read_text().replace("acct123", "otheracct"))
    assert box.run(BACKUP, env_file=other).returncode == 0
    assert "ARG https://otheracct.r2.cloudflarestorage.com" in box.logged("aws")


def test_missing_settings_and_bad_arguments_are_refused(box):
    proc = box.run(BACKUP, env_file=box.home / "absent.env")
    assert proc.returncode == 3 and "cannot read the settings file" in proc.stderr
    partial = box.home / "partial.env"
    partial.write_text("CLOUDFLARE_ACCOUNT_ID=acct123\n")
    proc = box.run(BACKUP, env_file=partial)
    assert proc.returncode == 3 and "missing" in proc.stderr
    proc = box.run(BACKUP, "--purge")
    assert proc.returncode == 64 and "usage" in proc.stderr
    assert box.logged("aws") == []


def test_a_failing_sync_fails_the_script(box):
    assert box.run(BACKUP, AWS_EXIT="7").returncode == 7


def test_backup_script_sources_nothing_from_the_repository():
    text = BACKUP.read_text()
    assert not [line for line in text.splitlines() if line.strip().startswith((". ", "source "))]
    assert 'PATH="${PATH}:/usr/local/bin:${HOME}/.local/bin"' in text


def test_cron_installer_is_idempotent_and_keeps_other_lines(box):
    box.crontab.write_text("\n".join(SEEDED) + "\n")
    snapshots = []
    for _ in range(2):
        proc = box.run(INSTALLER)
        assert proc.returncode == 0, proc.stderr
        snapshots.append(box.crontab.read_text())
    assert snapshots[0] == snapshots[1] == "\n".join([*SEEDED, CRON_LINE]) + "\n"
    assert (box.home / ".local" / "state" / "portfoliosight").is_dir()
    assert box.logged("crontab") == ["-l", "-", "-l", "-"] and box.logged("aws") == []


def test_cron_installer_starts_an_empty_crontab_and_replaces_an_old_line(box):
    assert box.run(INSTALLER).returncode == 0
    assert box.crontab.read_text() == CRON_LINE + "\n"
    old = "0 1 * * * $HOME/programming/portfoliosight/scripts/r2_backup.sh >> /dev/null"
    other = "0 2 * * * /opt/another-project/r2_backup.sh"
    box.crontab.write_text("\n".join([old, other, SEEDED[1]]) + "\n")
    assert box.run(INSTALLER).returncode == 0
    assert box.crontab.read_text() == "\n".join([other, SEEDED[1], CRON_LINE]) + "\n"


SYNC_INSTALLER = ROOT / "scripts" / "install_sync_lake_cron.sh"
SYNC_LINE = (
    "*/10 7-9 * * 1-5 $HOME/programming/portfoliosight/.venv/bin/python"
    " $HOME/programming/portfoliosight/scripts/sync_lake.py"
    " >> $HOME/.local/state/portfoliosight/sync_lake.log 2>&1"
)


def test_sync_cron_installer_adds_one_line_and_keeps_every_other(box):
    box.crontab.write_text("\n".join([*SEEDED, CRON_LINE]) + "\n")
    for _ in range(2):
        proc = box.run(SYNC_INSTALLER)
        assert proc.returncode == 0, proc.stderr
    assert box.crontab.read_text() == "\n".join([*SEEDED, CRON_LINE, SYNC_LINE]) + "\n"
    # The backup installer, run after it, keeps the sync line too.
    assert box.run(INSTALLER).returncode == 0
    assert box.crontab.read_text() == "\n".join([*SEEDED, SYNC_LINE, CRON_LINE]) + "\n"
    assert (box.home / ".local" / "state" / "portfoliosight").is_dir()
