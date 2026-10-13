"""scripts/ks001_secrets.sh and scripts/cloudflared_ingress.sh against fake commands on PATH."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SECRETS_SCRIPT = ROOT / "scripts" / "ks001_secrets.sh"
INGRESS_SCRIPT = ROOT / "scripts" / "cloudflared_ingress.sh"

HOST_KEYS = [
    "TIINGO_API_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
    "PS_GATE_SECRET",
]
LAPTOP_ONLY_KEYS = [
    "PS_SHARE_TEST_RECIPIENT",
    "MAILCHANNELS_API_KEY",
    "MAILCHANNELS_DKIM_PRIVATE_KEY",
]
VALUES = {
    "TIINGO_API_KEY": "tiingo-value-1",
    "CLOUDFLARE_ACCOUNT_ID": "account-value-2",
    "CLOUDFLARE_R2_ACCESS_KEY_ID": "r2-id-value-3",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY": "r2-secret-value-4",
    "PS_GATE_SECRET": "gate-value-5",
    "PS_SHARE_TEST_RECIPIENT": "recipient-value-6",
    "MAILCHANNELS_API_KEY": "mail-value-7",
    "MAILCHANNELS_DKIM_PRIVATE_KEY": "dkim-value-8",
    "CLOUDFLARE_API_TOKEN": "api-token-value-9",
}
REMOTE_COMMAND = (
    "umask 077 && mkdir -p ~/.secrets && cat > ~/.secrets/portfoliosight.env "
    "&& chmod 600 ~/.secrets/portfoliosight.env"
)
FAKE_SSH = (
    "#!/bin/sh\n"
    'for a in "$@"; do echo "ARG $a"; done > "$LOG/ssh.args"\n'
    'cat > "$LOG/ssh.stdin"\n'
    'exit "${SSH_EXIT:-0}"\n'
)
FAKE_OPENSSL = (
    "#!/bin/sh\n"
    'echo "$*" >> "$LOG/openssl.args"\n'
    "echo 0123456789abcdef0123456789abcdef0123456789abcdef\n"
)
GENERATED = "0123456789abcdef0123456789abcdef0123456789abcdef"


def _write_exe(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


class SecretsBox:
    def __init__(self, base: Path, drop: tuple[str, ...] = ()):
        self.home, self.bin, self.log = base / "home", base / "bin", base / "log"
        for folder in (self.home / ".secrets", self.bin, self.log):
            folder.mkdir(parents=True)
        self.env_file = self.home / ".secrets" / "portfoliosight.env"
        lines = ["# laptop settings", "PS_KS001_SSH_HOST=box-alias"]
        for index, (key, value) in enumerate(VALUES.items()):
            if key in drop:
                continue
            # the three spellings an env file is allowed to use
            lines.append(
                (f"export {key}={value}", f'{key}="{value}"', f"{key}='{value}'")[index % 3]
            )
        self.env_file.write_text("\n".join(lines) + "\n")
        self.env_file.chmod(0o600)
        _write_exe(self.bin / "ssh", FAKE_SSH)
        _write_exe(self.bin / "openssl", FAKE_OPENSSL)

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        environment = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "LOG": str(self.log),
            **env,
        }
        return subprocess.run(
            ["bash", str(SECRETS_SCRIPT), *args], env=environment, capture_output=True, text=True
        )

    def ssh_args(self) -> list[str]:
        lines = (self.log / "ssh.args").read_text().splitlines()
        return [line.removeprefix("ARG ") for line in lines]

    def sent(self) -> str:
        return (self.log / "ssh.stdin").read_text()

    def called(self) -> bool:
        return (self.log / "ssh.args").exists()


def _no_value(text: str) -> bool:
    return not any(value in text for value in (*VALUES.values(), GENERATED))


def test_secrets_sends_only_the_five_host_keys_as_plain_lines(tmp_path):
    box = SecretsBox(tmp_path)
    done = box.run()
    assert done.returncode == 0, done.stderr
    assert box.ssh_args() == ["box-alias", REMOTE_COMMAND]
    assert box.sent() == "".join(f"{key}={VALUES[key]}\n" for key in HOST_KEYS)
    for key in HOST_KEYS:
        assert key in done.stdout
    assert _no_value(done.stdout + done.stderr)
    assert not (box.log / "openssl.args").exists()


def test_secrets_host_argument_and_environment_override_the_file(tmp_path):
    box = SecretsBox(tmp_path)
    assert box.run(PS_KS001_SSH_HOST="env-alias").returncode == 0
    assert box.ssh_args()[0] == "env-alias"
    assert box.run("--host", "arg-alias", PS_KS001_SSH_HOST="env-alias").returncode == 0
    assert box.ssh_args()[0] == "arg-alias"


@pytest.mark.parametrize(
    "missing", [k for k in HOST_KEYS if k != "PS_GATE_SECRET"] + LAPTOP_ONLY_KEYS
)
def test_secrets_stops_before_ssh_when_a_key_is_missing(tmp_path, missing):
    box = SecretsBox(tmp_path, drop=(missing,))
    done = box.run()
    assert done.returncode != 0
    assert missing in done.stderr
    assert not box.called()
    assert _no_value(done.stdout + done.stderr)


def test_secrets_generates_the_gate_secret_into_the_laptop_file_once(tmp_path):
    box = SecretsBox(tmp_path, drop=("PS_GATE_SECRET",))
    before = box.env_file.read_text()
    done = box.run()
    assert done.returncode == 0, done.stderr
    assert (box.log / "openssl.args").read_text().splitlines() == ["rand -hex 24"]
    assert box.env_file.read_text() == before + f"PS_GATE_SECRET={GENERATED}\n"
    assert box.env_file.stat().st_mode & 0o777 == 0o600
    assert f"PS_GATE_SECRET={GENERATED}\n" in box.sent()
    assert _no_value(done.stdout + done.stderr)
    assert box.run().returncode == 0
    assert box.env_file.read_text().count("PS_GATE_SECRET=") == 1
    assert len((box.log / "openssl.args").read_text().splitlines()) == 1


def test_secrets_appends_on_a_new_line_when_the_file_has_no_final_newline(tmp_path):
    box = SecretsBox(tmp_path, drop=("PS_GATE_SECRET",))
    box.env_file.write_text(box.env_file.read_text().rstrip("\n"))
    assert box.run("--ensure-gate-secret").returncode == 0
    assert box.env_file.read_text().splitlines()[-1] == f"PS_GATE_SECRET={GENERATED}"


def test_ensure_gate_secret_is_local_only(tmp_path):
    box = SecretsBox(tmp_path, drop=("PS_GATE_SECRET", "TIINGO_API_KEY"))
    done = box.run("--ensure-gate-secret")
    assert done.returncode == 0, done.stderr
    assert not box.called()
    assert f"PS_GATE_SECRET={GENERATED}\n" in box.env_file.read_text()
    assert _no_value(done.stdout + done.stderr)
    again = box.run("--ensure-gate-secret")
    assert again.returncode == 0 and not box.called()
    assert box.env_file.read_text().count("PS_GATE_SECRET=") == 1


def test_secrets_fails_when_generation_fails(tmp_path):
    box = SecretsBox(tmp_path, drop=("PS_GATE_SECRET",))
    _write_exe(box.bin / "openssl", "#!/bin/sh\nexit 1\n")
    before = box.env_file.read_text()
    assert box.run().returncode != 0
    assert box.env_file.read_text() == before
    assert not box.called()


def test_secrets_reports_a_failed_copy(tmp_path):
    box = SecretsBox(tmp_path)
    done = box.run(SSH_EXIT="255")
    assert done.returncode != 0
    assert _no_value(done.stdout + done.stderr)


# --- cloudflared_ingress.sh -------------------------------------------------------------------

RULE_ONE = "  - hostname: one.example.com\n    service: scheme-a://localhost:8000\n"
RULE_TWO = (
    '  - hostname: "two.example.com"   # second service\n'
    "    service: scheme-a://localhost:8001\n"
    "    originRequest:\n"
    "      noTLSVerify: true\n"
)
CATCH_ALL = "  - service: http_status:404\n"
HEAD = (
    "tunnel: 00000000-0000-4000-8000-000000000000\n"
    "credentials-file: /etc/cloudflared/t.json\n\ningress:\n"
)
TAIL = "\nloglevel: info\n"
FIXTURE = HEAD + RULE_ONE + RULE_TWO + CATCH_ALL + TAIL
SERVICE_URL = "scheme-a://localhost:8010"
NEW_RULE = f"  - hostname: api.portfoliosight.ai\n    service: {SERVICE_URL}\n"
EXPECTED = HEAD + RULE_ONE + RULE_TWO + NEW_RULE + CATCH_ALL + TAIL

FAKE_CLOUDFLARED = (
    "#!/bin/sh\n"
    'echo "$*" >> "$LOG/cloudflared.args"\n'
    'cp "$3" "$LOG/validated.yml"\n'
    'exit "${CLOUDFLARED_EXIT:-0}"\n'
)
# Fails on the restart whose ordinal is $SYSTEMCTL_FAIL_ON.
FAKE_SYSTEMCTL = (
    "#!/bin/sh\n"
    'echo "$*" >> "$LOG/systemctl.args"\n'
    'cp "$CONFIG_PATH" "$LOG/config-at-restart-$(wc -l < "$LOG/systemctl.args" | tr -d " ").yml"\n'
    'n=$(wc -l < "$LOG/systemctl.args" | tr -d " ")\n'
    '[ "$n" = "${SYSTEMCTL_FAIL_ON:-0}" ] && exit 1\n'
    "exit 0\n"
)
# Prints the status for the URL's host: $LOG/status-before/<host> until the first restart,
# $LOG/status-after/<host> after it (falling back to the before value), else 200.
FAKE_CURL = (
    "#!/bin/sh\n"
    'for a in "$@"; do url="$a"; done\n'
    'echo "$url" >> "$LOG/curl.urls"\n'
    'host=$(printf "%s" "$url" | sed -e "s|^[a-z]*://||" -e "s|/.*$||")\n'
    "restarts=0\n"
    'if [ -f "$LOG/systemctl.args" ]; then\n'
    '  restarts=$(wc -l < "$LOG/systemctl.args" | tr -d " ")\n'
    "fi\n"
    'after="$LOG/status-after/$host"\n'
    'before="$LOG/status-before/$host"\n'
    'if [ "$restarts" = 1 ] && [ -f "$after" ]; then cat "$after"\n'
    'elif [ -f "$before" ]; then cat "$before"\n'
    "else printf 200; fi\n"
)


class IngressBox:
    def __init__(self, base: Path, config_text: str = FIXTURE):
        self.etc, self.bin, self.log = base / "etc", base / "bin", base / "log"
        for folder in (self.etc, self.bin, self.log / "status-before", self.log / "status-after"):
            folder.mkdir(parents=True)
        self.config = self.etc / "config.yml"
        self.config.write_text(config_text)
        self.config.chmod(0o640)
        _write_exe(self.bin / "cloudflared", FAKE_CLOUDFLARED)
        _write_exe(self.bin / "systemctl", FAKE_SYSTEMCTL)
        _write_exe(self.bin / "curl", FAKE_CURL)
        _write_exe(self.bin / "sudo", '#!/bin/sh\necho "$*" >> "$LOG/sudo.args"\nexit 97\n')

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        environment = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "LOG": str(self.log),
            "CONFIG_PATH": str(self.config),
            "PS_CLOUDFLARED_CONFIG": str(self.config),
            "PS_API_SERVICE_URL": SERVICE_URL,
            "PS_INGRESS_CHECK_ATTEMPTS": "2",
            "PS_INGRESS_CHECK_SLEEP": "0",
            **env,
        }
        return subprocess.run(
            ["bash", str(INGRESS_SCRIPT), *args], env=environment, capture_output=True, text=True
        )

    def lines(self, name: str) -> list[str]:
        path = self.log / name
        return path.read_text().splitlines() if path.exists() else []

    def backups(self) -> list[Path]:
        return sorted(self.etc.glob("config.yml.bak-*"))

    def leftovers(self) -> list[str]:
        return sorted(
            p.name for p in self.etc.iterdir() if p != self.config and ".bak-" not in p.name
        )


def _existing_rules_intact(text: str) -> bool:
    return RULE_ONE in text and RULE_TWO in text and CATCH_ALL in text


def test_ingress_install_inserts_the_rule_above_the_catch_all(tmp_path):
    box = IngressBox(tmp_path)
    (box.log / "status-before" / "two.example.com").write_text("302")
    done = box.run("install")
    assert done.returncode == 0, done.stderr
    assert box.config.read_text() == EXPECTED
    assert box.config.stat().st_mode & 0o777 == 0o640
    # validated the staged file beside the destination, before anything was replaced
    (validate,) = box.lines("cloudflared.args")
    assert re.fullmatch(
        rf"tunnel --config {re.escape(str(box.config))}\.new\.\w+ ingress validate", validate
    )
    assert (box.log / "validated.yml").read_text() == EXPECTED
    assert box.lines("systemctl.args") == ["restart cloudflared"]
    assert (box.log / "config-at-restart-1.yml").read_text() == EXPECTED
    # the baseline of every pre-existing hostname, then the same hostnames after the restart
    hosts = [re.sub(r"^[a-z]+://|/$", "", url) for url in box.lines("curl.urls")]
    assert hosts == ["one.example.com", "two.example.com"] * 2
    assert all(url.startswith("https://") for url in box.lines("curl.urls"))
    (backup,) = box.backups()
    assert backup.read_text() == FIXTURE
    assert re.fullmatch(r"config\.yml\.bak-\d{8}T\d{6}Z(-\d+)?", backup.name)
    assert str(backup) in done.stdout
    assert box.leftovers() == []
    assert box.lines("sudo.args") == []


def test_ingress_install_twice_changes_nothing_the_second_time(tmp_path):
    box = IngressBox(tmp_path)
    assert box.run("install").returncode == 0
    again = box.run("install")
    assert again.returncode == 0, again.stderr
    assert box.config.read_text() == EXPECTED
    assert box.config.read_text().count("api.portfoliosight.ai") == 1
    assert box.lines("systemctl.args") == ["restart cloudflared"]
    assert len(box.backups()) == 1
    assert box.leftovers() == []


def test_ingress_validate_failure_leaves_the_live_file_alone(tmp_path):
    box = IngressBox(tmp_path)
    done = box.run("install", CLOUDFLARED_EXIT="1")
    assert done.returncode != 0
    assert box.config.read_text() == FIXTURE
    assert box.lines("systemctl.args") == []
    assert box.leftovers() == [] and box.backups() == []


def test_ingress_restart_failure_restores_the_backup_and_restarts_again(tmp_path):
    box = IngressBox(tmp_path)
    done = box.run("install", SYSTEMCTL_FAIL_ON="1")
    assert done.returncode != 0
    assert box.config.read_text() == FIXTURE
    assert box.lines("systemctl.args") == ["restart cloudflared"] * 2
    assert (box.log / "config-at-restart-2.yml").read_text() == FIXTURE
    assert box.leftovers() == []
    assert [b.read_text() for b in box.backups()] == [FIXTURE]


def test_ingress_hostname_failure_restores_the_backup_and_restarts_again(tmp_path):
    box = IngressBox(tmp_path)
    (box.log / "status-after" / "two.example.com").write_text("502")
    done = box.run("install")
    assert done.returncode != 0
    assert "two.example.com" in done.stderr
    assert box.config.read_text() == FIXTURE
    assert _existing_rules_intact((box.log / "config-at-restart-1.yml").read_text())
    assert box.lines("systemctl.args") == ["restart cloudflared"] * 2
    assert (box.log / "config-at-restart-2.yml").read_text() == FIXTURE
    assert box.leftovers() == []


def test_ingress_hostname_that_stops_answering_restores_the_backup(tmp_path):
    box = IngressBox(tmp_path)
    (box.log / "status-after" / "one.example.com").write_text("000")
    done = box.run("install")
    assert done.returncode != 0
    assert "one.example.com" in done.stderr
    assert box.config.read_text() == FIXTURE
    assert box.lines("systemctl.args") == ["restart cloudflared"] * 2


@pytest.mark.parametrize("answer", ["000", ""])
def test_ingress_stops_when_an_existing_hostname_gives_no_answer_beforehand(tmp_path, answer):
    box = IngressBox(tmp_path)
    (box.log / "status-before" / "two.example.com").write_text(answer)
    done = box.run("install")
    assert done.returncode != 0
    assert "two.example.com" in done.stderr
    assert box.config.read_text() == FIXTURE
    assert box.lines("systemctl.args") == [] and box.lines("cloudflared.args") == []
    assert box.backups() == [] and box.leftovers() == []


def test_ingress_can_leave_out_a_hostname_that_never_answered(tmp_path):
    box = IngressBox(tmp_path)
    (box.log / "status-before" / "two.example.com").write_text("000")
    done = box.run("install", PS_INGRESS_ALLOW_UNREACHABLE="1")
    assert done.returncode == 0, done.stderr
    assert box.config.read_text() == EXPECTED
    hosts = [re.sub(r"^[a-z]+://|/$", "", url) for url in box.lines("curl.urls")]
    assert hosts == ["one.example.com", "two.example.com", "one.example.com"]


def test_ingress_explicit_rollback_restores_and_names_the_backup(tmp_path):
    box = IngressBox(tmp_path)
    assert box.run("install").returncode == 0
    (backup,) = box.backups()
    done = box.run("rollback", str(backup))
    assert done.returncode == 0, done.stderr
    assert str(backup) in done.stdout
    assert box.config.read_text() == FIXTURE
    assert box.config.stat().st_mode & 0o777 == 0o640
    assert box.lines("systemctl.args") == ["restart cloudflared"] * 2
    assert backup.read_text() == FIXTURE
    assert box.leftovers() == []


# A real `cp`/`mv` that fails on its Nth call, to break a restore half way.
FAKE_FAILING = (
    "#!/bin/sh\n"
    'echo x >> "$LOG/{name}.calls"\n'
    'n=$(wc -l < "$LOG/{name}.calls" | tr -d " ")\n'
    '[ "$n" = "${{{var}:-0}}" ] && exit 1\n'
    'exec /bin/{name} "$@"\n'
)


@pytest.mark.parametrize(("tool", "var"), [("cp", "CP_FAIL_ON"), ("mv", "MV_FAIL_ON")])
def test_ingress_rollback_that_cannot_put_the_file_back_says_so(tmp_path, tool, var):
    box = IngressBox(tmp_path)
    assert box.run("install").returncode == 0
    (backup,) = box.backups()
    _write_exe(box.bin / tool, FAKE_FAILING.format(name=tool, var=var))
    done = box.run("rollback", str(backup), **{var: "1"})
    assert done.returncode != 0
    assert "could NOT be put back" in done.stderr
    assert "restored" not in done.stdout
    assert box.config.read_text() == EXPECTED
    assert box.lines("systemctl.args") == ["restart cloudflared"]
    assert box.leftovers() == []


def test_ingress_failed_restore_after_a_failed_restart_is_reported_as_such(tmp_path):
    box = IngressBox(tmp_path)
    # install: mv #1 puts the candidate live; the restart fails; mv #2 (the restore) fails too
    _write_exe(box.bin / "mv", FAKE_FAILING.format(name="mv", var="MV_FAIL_ON"))
    done = box.run("install", SYSTEMCTL_FAIL_ON="1", MV_FAIL_ON="2")
    assert done.returncode != 0
    assert "could NOT be put back" in done.stderr
    assert "previous config is back" not in done.stderr
    assert box.lines("systemctl.args") == ["restart cloudflared"]
    assert box.leftovers() == []


def test_ingress_never_removes_a_staged_file_it_did_not_create(tmp_path):
    box = IngressBox(tmp_path)
    foreign = box.etc / "config.yml.new"
    foreign.write_text("someone else's staged file\n")
    assert box.run("install").returncode == 0
    assert box.run("install").returncode == 0  # the "already installed" path
    assert box.run(
        "install", CLOUDFLARED_EXIT="1", PS_API_HOSTNAME="x.portfoliosight.ai"
    ).returncode
    assert foreign.read_text() == "someone else's staged file\n"
    assert box.leftovers() == ["config.yml.new"]


def test_ingress_refuses_to_run_beside_another_run(tmp_path):
    box = IngressBox(tmp_path)
    holder = subprocess.Popen(
        ["flock", str(box.etc), "sh", "-c", "echo held; read _"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        done = box.run("install")
    finally:
        holder.communicate("\n")
    assert done.returncode != 0
    assert "lock" in done.stderr
    assert box.config.read_text() == FIXTURE
    assert box.lines("systemctl.args") == [] and box.lines("curl.urls") == []
    assert box.run("install").returncode == 0


def test_ingress_rollback_refuses_a_file_that_is_not_a_backup_of_this_config(tmp_path):
    box = IngressBox(tmp_path)
    stray = tmp_path / "other.yml"
    stray.write_text("ingress: []\n")
    for argument in (str(stray), str(box.etc / "config.yml.bak-missing"), ""):
        done = box.run("rollback", argument)
        assert done.returncode != 0
    assert box.config.read_text() == FIXTURE
    assert box.lines("systemctl.args") == []


def test_ingress_refuses_a_rule_for_the_hostname_with_another_service(tmp_path):
    other = FIXTURE.replace(
        CATCH_ALL,
        "  - hostname: api.portfoliosight.ai\n    service: scheme-a://localhost:9999\n" + CATCH_ALL,
    )
    box = IngressBox(tmp_path, other)
    done = box.run("install")
    assert done.returncode != 0
    assert box.config.read_text() == other
    assert box.lines("systemctl.args") == [] and box.backups() == []


@pytest.mark.parametrize(
    "config_text",
    [
        "tunnel: x\n",
        HEAD + RULE_ONE,
        HEAD + RULE_ONE + "  - hostname: last.example.com\n    service: scheme-a://localhost:1\n",
    ],
)
def test_ingress_refuses_a_config_without_a_catch_all(tmp_path, config_text):
    box = IngressBox(tmp_path, config_text)
    done = box.run("install")
    assert done.returncode != 0
    assert box.config.read_text() == config_text
    assert box.lines("systemctl.args") == [] and box.lines("cloudflared.args") == []
    assert box.leftovers() == []


def test_ingress_handles_list_items_at_column_zero(tmp_path):
    flat = FIXTURE.replace("\n  ", "\n")
    box = IngressBox(tmp_path, flat)
    assert box.run("install").returncode == 0
    assert box.config.read_text() == EXPECTED.replace("\n  ", "\n")


@pytest.mark.parametrize("url", ["", "scheme-a://localhost:8010 #x", "no-scheme", "a://b\n- x"])
def test_ingress_refuses_a_service_url_that_is_not_one_plain_url(tmp_path, url):
    box = IngressBox(tmp_path)
    done = box.run("install", PS_API_SERVICE_URL=url)
    assert done.returncode != 0
    assert box.config.read_text() == FIXTURE
    assert box.lines("systemctl.args") == []


def test_ingress_asks_for_root_when_the_config_is_not_writable(tmp_path):
    box = IngressBox(tmp_path)
    box.etc.chmod(0o555)
    try:
        done = box.run("install")
    finally:
        box.etc.chmod(0o755)
    assert done.returncode == 97
    (sudo_line,) = box.lines("sudo.args")
    assert f"PS_API_SERVICE_URL={SERVICE_URL}" in sudo_line and sudo_line.endswith("install")
    assert box.config.read_text() == FIXTURE


def test_the_scripts_spell_no_url():
    for script in (SECRETS_SCRIPT, INGRESS_SCRIPT):
        assert not re.search(r"https?://", script.read_text()), script.name
