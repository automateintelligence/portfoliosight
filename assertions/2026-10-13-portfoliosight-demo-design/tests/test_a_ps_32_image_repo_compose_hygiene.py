"""A-PS-32 — the image, the repository and the compose file hold no holdings, no secrets, no data
mount, and cap resources.

Claim: the built image contains no `runs/`, no `data/holdings/*` other than
`holdings_guide2017_step2.csv`, no `.venv`, `web/node_modules` or `web/dist`; neither the image
nor any git-tracked file contains any secret value from `~/.secrets/portfoliosight.env` or the
string `qse.env`; `deploy/docker-compose.yml` mounts only the named volume `ps-cache` at
`/app/cache`, publishes only `127.0.0.1:8010:8000`, sets `cpus: "4"`, `memory: 1536M`,
`PS_CACHE_MAX_MB=300`, `PS_STORE=r2`; and the image runs as uid 10001.

Pinned interface (the product must provide exactly this): `deploy/Dockerfile` (buildable with the
repository root as context; final image has the application under `/app`, the Step 2 CSV at
`/app/data/holdings/holdings_guide2017_step2.csv`, the tools `tar` and `id`, and runs as uid
10001), `.dockerignore` at the repository root, `deploy/docker-compose.yml` with services `api`
and `nightly` (spec 9.1). Secret values are read from the environment (the caller loads the env
file); PyYAML must be importable in the interpreter that runs this file.
"""

from __future__ import annotations

import os
import re
import secrets as _secrets
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CSV = "data/holdings/holdings_guide2017_step2.csv"
COMPOSE = ROOT / "deploy" / "docker-compose.yml"
DOCKERFILE = ROOT / "deploy" / "Dockerfile"
QSE = b"qse.env"
# The six credentials of the env file. PS_SHARE_TEST_RECIPIENT is left out on purpose: it is an
# e-mail address, not a credential, and may equal an address the repository legitimately names.
SECRET_NAMES = (
    "PS_GATE_SECRET",
    "TIINGO_API_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
)
# The spec, its assertions and the review notes legitimately NAME the forbidden env file, so the
# name scan (not the secret-value scan) leaves these trees out; the gate dir is never in scope.
QSE_EXEMPT = ("docs/", "assertions/", ".bubo/")
QSE_CONTROL = "docs/specs/2026-10-13-portfoliosight-demo-design.md"
MARKER = ("ps-gate-planted-a32-" + _secrets.token_hex(8)).encode()
PLANTED = (
    "data/holdings/personal_test.csv",
    "runs/x",
    ".venv/ps_gate_planted_a32.cfg",
    "web/node_modules/ps_gate_planted_a32/index.js",
    "web/dist/ps_gate_planted_a32.js",
)
_COPY: dict = {}


def _run(cmd, *, timeout, cwd=ROOT, **kwargs):
    try:
        return subprocess.run([str(c) for c in cmd], cwd=cwd, timeout=timeout, **kwargs)
    except FileNotFoundError as exc:
        pytest.fail(f"A-PS-32 red: cannot run {cmd[0]}: {exc}")
    except subprocess.TimeoutExpired:
        pytest.fail(f"A-PS-32 red: {' '.join(str(c) for c in cmd[:3])} ... timed out ({timeout}s)")


def _secret_values() -> dict[str, bytes]:
    """Secret values by variable name; never printed. Fewer than five would make the scan vacuous."""
    values = {name: os.environ.get(name, "").strip() for name in SECRET_NAMES}
    usable = {name: value.encode() for name, value in values.items() if len(value) >= 8}
    if len(usable) < 5:
        absent = sorted(set(SECRET_NAMES) - set(usable))
        pytest.fail(
            f"A-PS-32 red: secret env not loaded ({len(usable)} of {len(SECRET_NAMES)} values "
            f"usable, need >= 5; missing or too short: {absent})"
        )
    return usable


def _tracked_files() -> list[str]:
    proc = _run(["git", "ls-files", "-z"], timeout=60, capture_output=True)
    if proc.returncode != 0:
        pytest.fail(f"A-PS-32 red: `git ls-files` failed: {proc.stderr.decode(errors='replace')}")
    return [name for name in proc.stdout.decode().split("\0") if name]


def _scan(blobs, needles: dict[str, bytes]) -> dict[str, list[str]]:
    """Which needle (by label) occurs in which blob (by name). `blobs` yields (name, bytes)."""
    hits: dict[str, list[str]] = {}
    for name, data in blobs:
        for label, needle in needles.items():
            if needle in data:
                hits.setdefault(label, []).append(name)
    return hits


def _tracked_blobs(names):
    for name in names:
        path = ROOT / name
        if path.is_file():
            yield name, path.read_bytes()


# ---------------------------------------------------------------- compose leg


def _load_compose() -> dict:
    try:
        import yaml
    except Exception as exc:
        pytest.fail(f"A-PS-32 red: PyYAML is not importable in the gate interpreter: {exc}")
    if not COMPOSE.is_file():
        pytest.fail("A-PS-32 red: deploy/docker-compose.yml does not exist")
    try:
        data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    except Exception as exc:
        pytest.fail(f"A-PS-32 red: deploy/docker-compose.yml does not parse: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
        pytest.fail("A-PS-32 red: deploy/docker-compose.yml has no `services` mapping")
    return data


def _volume(entry) -> tuple[str, str, str]:
    """(kind, source, target) of one compose volume entry, short or long syntax."""
    if isinstance(entry, dict):
        return (
            str(entry.get("type", "volume")),
            str(entry.get("source", "")),
            str(entry.get("target")),
        )
    parts = str(entry).split(":")
    if len(parts) == 1:
        return "volume", "", parts[0]
    source, target = parts[0], parts[1]
    named = re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", source) is not None
    return ("volume" if named else "bind"), source, target


def _port(entry) -> str:
    if isinstance(entry, dict):
        host = entry.get("host_ip", "")
        return f"{host}:{entry.get('published')}:{entry.get('target')}"
    return str(entry)


def _environment(service: dict) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, list):
        pairs = [str(item).partition("=") for item in env]
        return {key: value for key, _, value in pairs}
    return {str(k): str(v) for k, v in env.items()}


def _env_files(service: dict) -> list[str]:
    raw = service.get("env_file") or []
    raw = raw if isinstance(raw, list) else [raw]
    return [str(item.get("path")) if isinstance(item, dict) else str(item) for item in raw]


def test_compose_leg():
    data = _load_compose()
    services = data["services"]
    assert "include" not in data, "A-PS-32 red: compose `include` hides services from this check"
    assert "api" in services and "nightly" in services, (
        f"A-PS-32 red: compose must define `api` and `nightly`; found {sorted(services)}"
    )
    api, nightly = services["api"], services["nightly"]

    published = []
    for name, service in services.items():
        assert "extends" not in service, f"A-PS-32 red: service {name} uses `extends`"
        assert service.get("network_mode") != "host", f"A-PS-32 red: {name} uses host networking"
        assert not service.get("privileged"), f"A-PS-32 red: service {name} is privileged"
        for entry in service.get("volumes") or []:
            kind, source, target = _volume(entry)
            assert kind != "bind", f"A-PS-32 red: service {name} has a bind mount {source!r}"
            assert (source, target.split(":")[0]) == ("ps-cache", "/app/cache"), (
                f"A-PS-32 red: service {name} mounts {source!r} at {target!r}; only "
                "ps-cache:/app/cache is allowed"
            )
        published += [(name, _port(entry)) for entry in service.get("ports") or []]

    assert len(api.get("volumes") or []) == 1, (
        f"A-PS-32 red: `api` must have exactly one volume mapping, has {api.get('volumes')}"
    )
    assert "ps-cache" in (data.get("volumes") or {}), (
        "A-PS-32 red: named volume ps-cache undeclared"
    )
    volume_spec = (data.get("volumes") or {}).get("ps-cache") or {}
    assert "driver_opts" not in volume_spec, "A-PS-32 red: ps-cache is a disguised bind mount"

    assert published == [("api", "127.0.0.1:8010:8000")], (
        f"A-PS-32 red: the only published port must be api 127.0.0.1:8010:8000; found {published}"
    )
    assert "ports" not in nightly or not nightly["ports"], "A-PS-32 red: `nightly` publishes a port"
    assert nightly.get("profiles") == ["jobs"], (
        f"A-PS-32 red: `nightly` must sit under profiles ['jobs'], has {nightly.get('profiles')}"
    )
    assert not api.get("profiles"), "A-PS-32 red: `api` must not be behind a profile"

    resources = (api.get("deploy") or {}).get("resources") or {}
    limits, reservations = resources.get("limits") or {}, resources.get("reservations") or {}
    assert str(limits.get("cpus")) in ("4", "4.0") and str(limits.get("memory")) == "1536M", (
        f"A-PS-32 red: api limits must be cpus 4 / memory 1536M, are {limits}"
    )
    assert str(reservations.get("cpus")) == "0.5" and str(reservations.get("memory")) == "256M", (
        f"A-PS-32 red: api reservations must be cpus 0.5 / memory 256M, are {reservations}"
    )

    env = _environment(api)
    assert env.get("PS_CACHE_MAX_MB") == "300", "A-PS-32 red: api PS_CACHE_MAX_MB must be 300"
    assert env.get("PS_STORE") == "r2", "A-PS-32 red: api PS_STORE must be r2"
    assert api.get("restart") == "unless-stopped", "A-PS-32 red: api restart must be unless-stopped"
    allowed = {"~/.secrets/portfoliosight.env", "${HOME}/.secrets/portfoliosight.env"}
    allowed.add("$HOME/.secrets/portfoliosight.env")
    for name, service in services.items():
        files = _env_files(service)
        assert all(f in allowed for f in files), (
            f"A-PS-32 red: service {name} env_file must be ~/.secrets/portfoliosight.env, is {files}"
        )
    assert len(_env_files(api)) == 1, (
        "A-PS-32 red: api needs env_file ~/.secrets/portfoliosight.env"
    )
    assert QSE.decode() not in COMPOSE.read_text(encoding="utf-8")


# ------------------------------------------------------------------- repo leg


def test_repo_leg_tracked_paths():
    tracked = _tracked_files()
    assert CSV in tracked, f"A-PS-32 red: {CSV} is not tracked (control for the listing)"
    holdings = [name for name in tracked if name.startswith("data/holdings/") and name != CSV]
    assert not holdings, (
        f"A-PS-32 red: tracked holdings files other than the Step 2 CSV: {holdings}"
    )
    runs = [name for name in tracked if name.startswith("runs/") or "/runs/" in name]
    assert not runs, f"A-PS-32 red: tracked paths under runs/: {runs[:10]}"


def test_repo_leg_no_secret_value_and_no_qse_env_in_tracked_files():
    values = _secret_values()
    tracked = _tracked_files()
    blobs = list(_tracked_blobs(tracked))
    assert len(blobs) >= 10 and len(blobs) >= len(tracked) - 5, (
        f"A-PS-32 red: read only {len(blobs)} of {len(tracked)} tracked files"
    )

    hits = _scan(blobs, values)
    report = {name: (len(files), files[:5]) for name, files in hits.items()}
    assert not hits, (
        f"A-PS-32 red: secret values found in tracked files (variable: count, files): {report}"
    )

    control = _scan(blobs, {"qse": QSE})
    assert QSE_CONTROL in control.get("qse", []), (
        f"A-PS-32 red: the scan did not find the env-file name in {QSE_CONTROL}, where the spec "
        "names it; the scan is not reading real file content"
    )
    in_scope = [(name, data) for name, data in blobs if not name.startswith(QSE_EXEMPT)]
    assert len(in_scope) >= 5, f"A-PS-32 red: only {len(in_scope)} tracked files in scan scope"
    named = _scan(in_scope, {"qse": QSE}).get("qse", [])
    assert not named, f"A-PS-32 red: tracked files reference qse.env: {named}"


# ------------------------------------------------------------ ignore-rule leg


def _ignore_rules(text: str) -> list[tuple[bool, re.Pattern]]:
    """.dockerignore patterns as (is_exception, regex), in file order (the last match wins)."""
    rules = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pattern = line[1:].strip() if negated else line
        pattern = re.sub(r"^(\./)+", "", pattern).strip("/")
        if not pattern or pattern == ".":
            continue
        out, i = [], 0
        while i < len(pattern):
            char = pattern[i]
            if pattern.startswith("**", i):
                i += 2
                if pattern.startswith("/", i):
                    i += 1
                    out.append("(?:.*/)?")
                else:
                    out.append(".*")
                continue
            if char == "*":
                out.append("[^/]*")
            elif char == "?":
                out.append("[^/]")
            elif char == "[" and "]" in pattern[i + 1 :]:
                end = pattern.index("]", i + 1)
                out.append(pattern[i : end + 1])
                i = end
            elif char == "\\" and i + 1 < len(pattern):
                i += 1
                out.append(re.escape(pattern[i]))
            else:
                out.append(re.escape(char))
            i += 1
        rules.append((negated, re.compile("^" + "".join(out) + "$")))
    return rules


def _ignored(path: str, rules) -> bool:
    """Docker's rule: a pattern applies when it matches the path or any parent directory."""
    parts = path.split("/")
    candidates = ["/".join(parts[:k]) for k in range(1, len(parts) + 1)]
    ignored = False
    for negated, regex in rules:
        if any(regex.match(candidate) for candidate in candidates):
            ignored = not negated
    return ignored


def _temp_copy() -> Path:
    """A copy of the working tree (heavy, ignorable directories left out) with planted files."""
    if "path" in _COPY:
        return _COPY["path"]
    base = Path(tempfile.mkdtemp(prefix="ps-gate-a32-"))
    _COPY["base"] = base
    skip = {".git", ".venv", "node_modules", "runs", ".worktrees", ".conductor", ".omx"}
    skip |= {"__pycache__", ".pytest_cache", ".ruff_cache", ".wrangler"}

    def ignore(directory, names):
        drop = {n for n in names if n in skip or n.endswith(".egg-info")}
        if Path(directory).name == "web" and "dist" in names:
            drop.add("dist")
        return drop

    copy = base / "tree"
    shutil.copytree(ROOT, copy, symlinks=True, ignore=ignore)
    for name in PLANTED:
        target = copy / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"planted by the A-PS-32 gate test\n" + MARKER + b"\n")
    _COPY["path"] = copy
    return copy


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    if "base" in _COPY:
        shutil.rmtree(_COPY["base"], ignore_errors=True)


def test_ignore_matcher_follows_docker_semantics():
    """Control for the matcher itself, on the two rule styles a .dockerignore can take."""
    deny = _ignore_rules(
        "# c\nruns/\n.venv\nweb/node_modules\nweb/dist\n**/__pycache__\n"
        "data/holdings/*\n!data/holdings/holdings_guide2017_step2.csv\n"
    )
    assert _ignored("runs/x", deny) and _ignored(".venv/bin/python", deny)
    assert _ignored("web/node_modules/a/b.js", deny) and _ignored("web/dist/i.html", deny)
    assert _ignored("data/holdings/personal_test.csv", deny)
    assert _ignored("portfoliosight/engine/__pycache__/a.pyc", deny)
    assert not _ignored(CSV, deny) and not _ignored("web/src/main.ts", deny)
    assert not _ignored("portfoliosight/runs.py", deny)
    allow = _ignore_rules("*\n!portfoliosight\n!pyproject.toml\n!data\ndata/holdings/*\n!" + CSV)
    assert _ignored("runs/x", allow) and _ignored("data/holdings/p.csv", allow)
    assert not _ignored("portfoliosight/api/app.py", allow) and not _ignored(CSV, allow)


def test_ignore_rule_leg():
    dockerignore = ROOT / ".dockerignore"
    if not dockerignore.is_file():
        pytest.fail("A-PS-32 red: .dockerignore does not exist at the repository root")
    copy = _temp_copy()
    rules = _ignore_rules((copy / ".dockerignore").read_text(encoding="utf-8"))
    assert rules, "A-PS-32 red: .dockerignore has no rule"

    files = [p.relative_to(copy).as_posix() for p in copy.rglob("*") if p.is_file()]
    for local in (ROOT / "data" / "holdings", ROOT / "runs"):  # the owner's real local files
        if local.is_dir():
            files += [p.relative_to(ROOT).as_posix() for p in list(local.rglob("*"))[:2000]]
    kept = sorted({name for name in files if not _ignored(name, rules)})
    assert len(files) >= len(PLANTED) + 3

    leaked = [name for name in PLANTED if name in kept]
    assert not leaked, f"A-PS-32 red: .dockerignore lets planted files into the build: {leaked}"
    assert CSV in kept, f"A-PS-32 red: .dockerignore excludes {CSV}, which the image must carry"
    assert "pyproject.toml" in kept, "A-PS-32 red: .dockerignore excludes pyproject.toml"
    holdings = [n for n in kept if n.startswith("data/holdings/") and n != CSV]
    assert not holdings, f"A-PS-32 red: holdings files reach the build context: {holdings}"
    forbidden = [
        n for n in kept if n.startswith(("runs/", ".venv/", "web/node_modules/", "web/dist/"))
    ]
    assert not forbidden, f"A-PS-32 red: ignored trees reach the build context: {forbidden[:10]}"


# ------------------------------------------------------------------ image leg


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        info = subprocess.run(["docker", "info"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return info.returncode == 0


def _build(context: Path, tag: str, timeout: int) -> None:
    cmd = ["docker", "build", "-q", "-f", context / "deploy" / "Dockerfile", "-t", tag, context]
    proc = _run(cmd, timeout=timeout, capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"A-PS-32 red: `docker build -f deploy/Dockerfile` failed (rc {proc.returncode}):\n"
        + proc.stderr[-3000:]
    )


def _image_files(tag: str, workdir: Path) -> list[tuple[str, bytes]]:
    """(path below /app, content) of every regular file in the image's /app; dirs have b''."""
    archive = workdir / (tag.replace(":", "_") + ".tar")
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        "0:0",
        "--entrypoint",
        "tar",
        tag,
    ]
    with archive.open("wb") as sink:
        proc = _run(cmd + ["-cf", "-", "/app"], timeout=600, stdout=sink, stderr=subprocess.PIPE)
    assert proc.returncode == 0, (
        "A-PS-32 red: could not archive /app from the image (it needs `tar`): "
        f"{proc.stderr.decode(errors='replace')[-800:]}"
    )
    entries = []
    with tarfile.open(archive) as tar:
        for member in tar:
            name = member.name.lstrip("./")
            name = name[4:] if name.startswith("app/") else ("" if name == "app" else name)
            if not name:
                continue
            handle = tar.extractfile(member) if member.isfile() else None
            entries.append((name, handle.read() if handle is not None else b""))
    archive.unlink()
    return entries


def _path_violations(names: list[str]) -> list[str]:
    bad = []
    for name in names:
        parts = name.split("/")
        if "data/holdings/" in name + "/" and parts[-1] != "holdings" and not name.endswith(CSV):
            bad.append(name)
        elif ".venv" in parts or "node_modules" in parts:
            bad.append(name)
        elif "runs" in parts and "site-packages" not in parts:
            bad.append(name)
        elif any(a == "web" and b == "dist" for a, b in zip(parts, parts[1:])):
            bad.append(name)
    return bad


def test_path_rule_control():
    bad = ["data/holdings/p.csv", "runs/x", ".venv/bin/python", "web/dist/index.html"]
    bad += ["web/node_modules/a/index.js", "src/data/holdings/holdings_2026-10.csv", "runs"]
    assert _path_violations(bad) == bad
    assert not _path_violations([CSV, "data/holdings", "portfoliosight/engine/stats.py", "cache"])


def test_image_leg():
    if not DOCKERFILE.is_file():
        pytest.fail("A-PS-32 red: deploy/Dockerfile does not exist")
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    users = re.findall(r"(?im)^\s*USER\s+(\S+)", dockerfile)
    assert users and "10001" in dockerfile, "A-PS-32 red: deploy/Dockerfile sets no uid-10001 user"
    assert users[-1].split(":")[0] not in ("root", "0"), "A-PS-32 red: the image runs as root"
    values = _secret_values()
    if not _docker_available():
        # The spec's allowance: without docker the ignore-rule leg (always run above) stands in.
        return

    copy = _temp_copy()
    suffix = f"{os.getpid()}-{_secrets.token_hex(4)}"
    real_tag, planted_tag = f"ps-gate-a32-real:{suffix}", f"ps-gate-a32-planted:{suffix}"
    workdir = _COPY["base"]
    try:
        _build(ROOT, real_tag, 1000)
        uid = _run(
            ["docker", "run", "--rm", "--network", "none", "--entrypoint", "id", real_tag, "-u"],
            timeout=120,
            capture_output=True,
            text=True,
        )
        assert uid.stdout.strip() == "10001", (
            f"A-PS-32 red: the image runs as uid {uid.stdout.strip()!r}, not 10001 {uid.stderr[-300:]}"
        )

        files = _image_files(real_tag, workdir)
        names = [name for name, _ in files]
        assert len(names) >= 5, f"A-PS-32 red: the image's /app holds only {len(names)} paths"
        carried = dict(files).get(CSV)
        assert carried == (ROOT / CSV).read_bytes(), (
            f"A-PS-32 red: the image does not carry /app/{CSV} with the repository's content"
        )
        bad = _path_violations(names)
        assert not bad, f"A-PS-32 red: the image's /app contains excluded paths: {bad[:15]}"
        hits = _scan(files, values)
        report = {name: (len(found), found[:5]) for name, found in hits.items()}
        assert not hits, (
            f"A-PS-32 red: secret values inside the image (variable: count, files): {report}"
        )
        in_scope = [(name, data) for name, data in files if not name.startswith(QSE_EXEMPT)]
        named = _scan(in_scope, {"qse": QSE}).get("qse", [])
        assert not named, f"A-PS-32 red: files in the image reference qse.env: {named}"

        _build(copy, planted_tag, 600)
        planted_files = _image_files(planted_tag, workdir)
        planted_names = [name for name, _ in planted_files]
        assert CSV in planted_names, "A-PS-32 red: the image built from the temp copy lacks the CSV"
        bad = _path_violations(planted_names)
        assert not bad, f"A-PS-32 red: planted or excluded paths reached the image: {bad[:15]}"
        marked = _scan(planted_files, {"marker": MARKER}).get("marker", [])
        assert not marked, f"A-PS-32 red: planted file content reached the image: {marked}"
    finally:
        for tag in (real_tag, planted_tag):
            try:
                subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, timeout=120)
            except (OSError, subprocess.TimeoutExpired):
                pass
