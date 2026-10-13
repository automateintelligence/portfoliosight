"""A-PS-11 — the backup refuses loudly when D: is unmounted, mirrors with --delete, restores
without it, and the cron installer is idempotent.

Claim: scripts/r2_backup.sh exits 2 with the exact message "D: drive is not mounted at /mnt/d;
backup not run" and calls nothing else when `mountpoint -q /mnt/d` fails; when mounted it runs
`aws s3 sync` bucket -> /mnt/d/portfoliosight-data with --delete and the R2 endpoint; --restore
runs the reverse sync without --delete; scripts/install_backup_cron.sh run twice leaves exactly
one PortfolioSight line and every other crontab line unchanged.

Pinned interface (the product must provide exactly this):
- `scripts/r2_backup.sh` and `scripts/install_backup_cron.sh` are executable and take no
  arguments, except `r2_backup.sh --restore`.
- `r2_backup.sh` finds `mountpoint`, `aws` and `mkdir` through `PATH`. It reads plain `KEY=value`
  lines for `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_R2_ACCESS_KEY_ID` and
  `CLOUDFLARE_R2_SECRET_ACCESS_KEY` from the file named by `PS_ENV_FILE` when that is set, else
  from `~/.secrets/portfoliosight.env`, and hands the two keys to `aws` as `AWS_ACCESS_KEY_ID`
  and `AWS_SECRET_ACCESS_KEY` in its environment. It creates the destination with `mkdir -p`
  (trusting its exit status) and runs exactly one `aws ... s3 sync` with
  `--endpoint-url https://<account>.r2.cloudflarestorage.com` (or `--endpoint-url=<same>`).
- `install_backup_cron.sh` reads the crontab with `crontab -l` and writes it back with
  `crontab -` (stdin) or `crontab <file>`; it never calls `crontab -r`. The line it keeps is
  exactly the spec §5.3 line, with a literal `$HOME`, and it is the only line that mentions
  PortfolioSight (no marker comment).

Standard library only; the scripts run against fake `mountpoint`, `aws`, `mkdir` and `crontab`
executables on a temporary PATH with a temporary HOME.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKUP = ROOT / "scripts" / "r2_backup.sh"
INSTALLER = ROOT / "scripts" / "install_backup_cron.sh"

MESSAGE = "D: drive is not mounted at /mnt/d; backup not run"
ACCOUNT = "acct0123456789abcdef"
ENDPOINT = f"https://{ACCOUNT}.r2.cloudflarestorage.com"
BUCKET = "s3://portfoliosight-data"
MIRROR = "/mnt/d/portfoliosight-data"
FAKE_KEY_ID = "gate-fake-access-key-id"
FAKE_SECRET = "gate-fake-secret-access-key"
CRON_LINE = (
    "30 5 * * * $HOME/programming/portfoliosight/scripts/r2_backup.sh"
    " >> $HOME/.local/state/portfoliosight/r2_backup.log 2>&1"
)
SEEDED = [
    "0 5 * * * $HOME/programming/quant-scenario-engine/scripts/backup_lake.sh"
    " >> $HOME/.local/state/qse/backup.log 2>&1",
    "15 3 * * 0 /usr/bin/find /var/tmp -name 'gate-*.tmp' -mtime +7 -delete  # weekly tidy",
]

FAKE_MOUNTPOINT = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG_DIR/mountpoint.log"
[ "$FAKE_MOUNTED" = "1" ] && exit 0
exit 1
"""
FAKE_AWS = """#!/bin/sh
{
  printf 'CALL\\n'
  for arg in "$@"; do printf 'ARG %s\\n' "$arg"; done
  printf 'KEYID %s\\n' "$AWS_ACCESS_KEY_ID"
  printf 'SECRET %s\\n' "$AWS_SECRET_ACCESS_KEY"
} >> "$FAKE_LOG_DIR/aws.log"
exit 0
"""
FAKE_MKDIR = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG_DIR/mkdir.log"
for arg in "$@"; do
  case "$arg" in
    /mnt/*) exit 0 ;;
  esac
done
exec /bin/mkdir "$@"
"""
FAKE_CRONTAB = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG_DIR/crontab.log"
case "$1" in
  -l)
    if [ -f "$FAKE_CRONTAB_FILE" ]; then cat "$FAKE_CRONTAB_FILE"; exit 0; fi
    echo "no crontab for gate" >&2
    exit 1
    ;;
  -r) rm -f "$FAKE_CRONTAB_FILE"; exit 0 ;;
  -) cat > "$FAKE_CRONTAB_FILE"; exit 0 ;;
  "") cat > "$FAKE_CRONTAB_FILE"; exit 0 ;;
  -*) echo "fake crontab: unsupported option $1" >&2; exit 2 ;;
  *) cat "$1" > "$FAKE_CRONTAB_FILE"; exit 0 ;;
esac
"""


class _Sandbox:
    def __init__(self, base: Path):
        self.home = base / "home"
        self.bin = base / "bin"
        self.logs = base / "logs"
        self.crontab = base / "crontab.txt"
        for folder in (self.home / ".secrets", self.bin, self.logs):
            folder.mkdir(parents=True)
        self.env_file = self.home / ".secrets" / "portfoliosight.env"
        self.env_file.write_text(
            f"CLOUDFLARE_ACCOUNT_ID={ACCOUNT}\n"
            f"CLOUDFLARE_R2_ACCESS_KEY_ID={FAKE_KEY_ID}\n"
            f"CLOUDFLARE_R2_SECRET_ACCESS_KEY={FAKE_SECRET}\n"
        )
        for name, body in (
            ("mountpoint", FAKE_MOUNTPOINT),
            ("aws", FAKE_AWS),
            ("mkdir", FAKE_MKDIR),
            ("crontab", FAKE_CRONTAB),
        ):
            path = self.bin / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def run(
        self, script: Path, *args: str, mounted: bool, env_file: Path | None | str = "default"
    ) -> subprocess.CompletedProcess:
        if not script.is_file():
            pytest.fail(f"A-PS-11 red: {script.relative_to(ROOT)} does not exist")
        if not os.access(script, os.X_OK):
            pytest.fail(f"A-PS-11 red: {script.relative_to(ROOT)} is not executable")
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.home),
            "FAKE_LOG_DIR": str(self.logs),
            "FAKE_MOUNTED": "1" if mounted else "0",
            "FAKE_CRONTAB_FILE": str(self.crontab),
            "LANG": "C",
        }
        if env_file == "default":
            env["PS_ENV_FILE"] = str(self.env_file)
        elif env_file is not None:
            env["PS_ENV_FILE"] = str(env_file)
        try:
            return subprocess.run(
                [str(script), *args],
                cwd=self.home,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(f"A-PS-11 red: {script.name} {' '.join(args)} did not finish in 60 s")
        except OSError as exc:
            pytest.fail(f"A-PS-11 red: cannot run {script.name}: {exc}")

    def log(self, name: str) -> str:
        path = self.logs / f"{name}.log"
        return path.read_text() if path.exists() else ""

    def aws_calls(self) -> list[dict]:
        calls: list[dict] = []
        for line in self.log("aws").splitlines():
            if line == "CALL":
                calls.append({"argv": [], "key_id": None, "secret": None})
            elif line.startswith("ARG "):
                calls[-1]["argv"].append(line[4:])
            elif line.startswith("KEYID "):
                calls[-1]["key_id"] = line[6:]
            elif line.startswith("SECRET "):
                calls[-1]["secret"] = line[7:]
        return calls


def _position(argv: list[str], location: str) -> int:
    hits = [i for i, arg in enumerate(argv) if arg.rstrip("/") == location]
    assert len(hits) == 1, f"expected {location} once in the aws argv, got {argv}"
    return hits[0]


def _check_sync(box: _Sandbox, *, restore: bool) -> None:
    calls = box.aws_calls()
    assert len(calls) == 1, f"expected exactly one aws call, got {[c['argv'] for c in calls]}"
    argv = calls[0]["argv"]
    assert "s3" in argv and argv[argv.index("s3") + 1 : argv.index("s3") + 2] == ["sync"], (
        f"the aws call is not 'aws s3 sync': {argv}"
    )
    if "--endpoint-url" in argv:
        endpoint = argv[argv.index("--endpoint-url") + 1 : argv.index("--endpoint-url") + 2]
        assert endpoint == [ENDPOINT], f"wrong --endpoint-url value in {argv}"
    else:
        assert f"--endpoint-url={ENDPOINT}" in argv, f"no R2 --endpoint-url in {argv}"
    sync_at = argv.index("sync")
    bucket_at, mirror_at = _position(argv, BUCKET), _position(argv, MIRROR)
    assert bucket_at > sync_at and mirror_at > sync_at, f"sync operands misplaced in {argv}"
    delete_flags = [arg for arg in argv if arg.startswith("--delete")]
    if restore:
        assert mirror_at < bucket_at, f"--restore must sync {MIRROR} -> {BUCKET}: {argv}"
        # Must-not-contain: --delete on restore.
        assert not delete_flags, f"--restore must never pass --delete: {argv}"
        assert "--delete" not in argv
    else:
        assert bucket_at < mirror_at, f"backup must sync {BUCKET} -> {MIRROR}: {argv}"
        assert delete_flags == ["--delete"], f"backup must pass --delete once: {argv}"
    assert "--dryrun" not in argv, f"the sync must not be a dry run: {argv}"
    assert calls[0]["key_id"] == FAKE_KEY_ID, "aws did not get AWS_ACCESS_KEY_ID from the env file"
    assert calls[0]["secret"] == FAKE_SECRET, (
        "aws did not get AWS_SECRET_ACCESS_KEY from the env file"
    )
    assert "-q /mnt/d" in box.log("mountpoint").splitlines(), (
        f"mountpoint -q /mnt/d was not called (log: {box.log('mountpoint')!r})"
    )


@pytest.mark.parametrize("args", [(), ("--restore",)], ids=["backup", "restore"])
def test_unmounted_exits_2_with_the_message_and_calls_nothing(args, tmp_path):
    box = _Sandbox(tmp_path)
    proc = box.run(BACKUP, *args, mounted=False)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 2, f"exit status {proc.returncode}, expected 2; output: {output!r}"
    assert MESSAGE in output, f"the exact message is missing from the output: {output!r}"
    assert "-q /mnt/d" in box.log("mountpoint").splitlines(), (
        f"mountpoint -q /mnt/d was not called (log: {box.log('mountpoint')!r})"
    )
    # Must-not-contain: an aws call (or anything else) on the unmounted path.
    assert box.log("aws") == "", f"aws was called with D: unmounted: {box.log('aws')!r}"
    assert not box.aws_calls()
    assert "/mnt/d" not in box.log("mkdir"), "mkdir touched /mnt/d with D: unmounted"
    assert box.log("crontab") == ""


def test_mounted_backup_mirrors_bucket_to_d_with_delete(tmp_path):
    box = _Sandbox(tmp_path)
    proc = box.run(BACKUP, mounted=True)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"exit status {proc.returncode}; output: {output!r}"
    assert MESSAGE not in output
    _check_sync(box, restore=False)


def test_mounted_restore_reverses_the_sync_without_delete(tmp_path):
    box = _Sandbox(tmp_path)
    proc = box.run(BACKUP, "--restore", mounted=True)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"exit status {proc.returncode}; output: {output!r}"
    assert MESSAGE not in output
    _check_sync(box, restore=True)


def test_env_file_is_ps_env_file_else_home_secrets(tmp_path):
    box = _Sandbox(tmp_path)
    other = box.home / "elsewhere.env"
    other.write_text(box.env_file.read_text().replace(ACCOUNT, "otheraccount9"))
    # PS_ENV_FILE pointing at another file: its account id must win.
    proc = box.run(BACKUP, mounted=True, env_file=other)
    assert proc.returncode == 0, f"exit status {proc.returncode}: {proc.stdout + proc.stderr!r}"
    calls = box.aws_calls()
    assert len(calls) == 1, f"expected one aws call, got {[c['argv'] for c in calls]}"
    argv = calls[0]["argv"]
    assert any("otheraccount9.r2.cloudflarestorage.com" in arg for arg in argv), (
        f"PS_ENV_FILE was not honoured: {argv}"
    )
    assert not any(ACCOUNT in arg for arg in argv)
    # PS_ENV_FILE unset: ~/.secrets/portfoliosight.env under the temporary HOME is used.
    (box.logs / "aws.log").unlink()
    proc = box.run(BACKUP, mounted=True, env_file=None)
    assert proc.returncode == 0, f"exit status {proc.returncode}: {proc.stdout + proc.stderr!r}"
    _check_sync(box, restore=False)


def test_cron_installer_is_idempotent(tmp_path):
    box = _Sandbox(tmp_path)
    box.crontab.write_text("\n".join(SEEDED) + "\n")
    snapshots = []
    for attempt in (1, 2):
        proc = box.run(INSTALLER, mounted=True)
        output = proc.stdout + proc.stderr
        assert proc.returncode == 0, f"run {attempt}: exit {proc.returncode}; output: {output!r}"
        assert box.crontab.exists(), f"run {attempt}: the crontab was removed"
        lines = [line for line in box.crontab.read_text().splitlines() if line.strip()]
        ours = [line for line in lines if "r2_backup.sh" in line]
        assert len(ours) == 1, f"run {attempt}: {len(ours)} r2_backup.sh lines: {lines}"
        assert ours[0] == CRON_LINE, f"run {attempt}: cron line is {ours[0]!r}"
        mentions = [line for line in lines if "portfoliosight" in line.lower()]
        # Must-not-contain: a second PortfolioSight line.
        assert len(mentions) == 1, f"run {attempt}: PortfolioSight lines: {mentions}"
        others = [line for line in lines if "portfoliosight" not in line.lower()]
        assert others == SEEDED, f"run {attempt}: other crontab lines changed: {others}"
        assert len(lines) == 3
        snapshots.append(box.crontab.read_text())
    assert snapshots[0] == snapshots[1], "the second installer run changed the crontab"
    crontab_calls = box.log("crontab").splitlines()
    assert "-l" in crontab_calls, f"the installer never read the crontab: {crontab_calls}"
    assert "-r" not in crontab_calls, "the installer must not remove the crontab"
    assert box.log("aws") == "", "the installer must not run aws"
