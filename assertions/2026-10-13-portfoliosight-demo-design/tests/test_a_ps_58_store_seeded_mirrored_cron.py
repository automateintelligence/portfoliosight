"""A-PS-58 — the store is verified, seeded, mirrored, and the cron is installed once.

Claim: `python -m portfoliosight.data.store --verify` passes against the bucket;
`meta/manifest.json` holds at least 1,400 symbols with `source` containing `seed`;
`scripts/r2_backup.sh` has mirrored the bucket to `/mnt/d/portfoliosight-data/`; a dry-run restore
reports zero files to upload; `crontab -l` shows exactly one PortfolioSight line.

Live laptop check, inside the project virtualenv (needs `boto3`; also the AWS CLI v2 and `crontab`).
Environment: `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_R2_ACCESS_KEY_ID`,
`CLOUDFLARE_R2_SECRET_ACCESS_KEY` (never printed). The R2 reads use the test's own boto3 client.

Repeat-safe by construction (the gate runs many times a day, the nightly rewrites `prices/`
objects for hours, and the cron backup runs once a day): the mirror legs first run the product's
own `scripts/r2_backup.sh` once (exit 0 required; it is idempotent and only downloads what
changed), then compare. Objects whose bucket `LastModified` is at or after that backup's start
(minus 5 s) were written while or after it ran and are left out of the size sample and tolerated
in the restore dry-run; every other object must be mirrored exactly.

Pinned interface (the product must provide exactly this):
- `scripts/r2_backup.sh` run from the repo root with the caller's environment exits 0 when
  `/mnt/d` is mounted and leaves `/mnt/d/portfoliosight-data` equal to the bucket.
- `python -m portfoliosight.data.store --verify` (with `PS_STORE=r2`, `PS_R2_BUCKET=portfoliosight-data`)
  exits 0, names the bucket `portfoliosight-data` in its output, prints no secret value, and
  leaves no `meta/_probe` object behind.
- `meta/manifest.json` in the bucket: per-symbol entries with `source` and `adjusted_through`
  (`{"symbols": {id: entry}}`, or a top-level id-keyed object).
- `prices/{SYMBOL}.parquet` objects mirrored byte-for-byte to `/mnt/d/portfoliosight-data/prices/`.
- The laptop crontab holds exactly one line naming `r2_backup.sh`, equal to
  `30 5 * * * $HOME/programming/portfoliosight/scripts/r2_backup.sh >> $HOME/.local/state/portfoliosight/r2_backup.log 2>&1`
  (`$HOME` literal, spec §5.3).
"""

# ruff: noqa: E501

from __future__ import annotations

import importlib
import json
import os
import random
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
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
        pytest.fail(f"A-PS-58 red: cannot import {module}: {type(exc).__name__}: {exc}")


BUCKET = "portfoliosight-data"
SECRET_NAMES = (
    "PS_GATE_SECRET",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
    "TIINGO_API_KEY",
)


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(
            f"A-PS-58 red: environment variable {name} is not set "
            "(the caller loads ~/.secrets/portfoliosight.env)"
        )
    return value


def _scrub(text: str) -> str:
    """Replace every secret value from the environment by its variable name before printing."""
    for name in SECRET_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            text = text.replace(value, f"<{name}>")
    return text


def _r2_endpoint() -> str:
    return f"https://{_env('CLOUDFLARE_ACCOUNT_ID')}.r2.cloudflarestorage.com"


def _r2_client():
    """The test's own S3 client for R2, built from the environment (not the product's store)."""
    key_id = _env("CLOUDFLARE_R2_ACCESS_KEY_ID")
    secret = _env("CLOUDFLARE_R2_SECRET_ACCESS_KEY")
    endpoint = _r2_endpoint()
    boto3 = _need("boto3")
    config = _need("botocore.config").Config(
        connect_timeout=10, read_timeout=60, retries={"max_attempts": 2}
    )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        config=config,
    )


def _r2_get(client, key: str) -> bytes:
    try:
        return client.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except Exception as exc:  # botocore ClientError / connection errors
        pytest.fail(
            f"A-PS-58 red: cannot read s3://{BUCKET}/{key} from R2: "
            f"{type(exc).__name__}: {_scrub(str(exc))[:300]}"
        )


def _manifest_entries(document) -> dict[str, dict]:
    """Per-symbol entries of meta/manifest.json: `{"symbols": {id: entry}}` or a top-level id dict."""
    assert isinstance(document, dict), "meta/manifest.json is not a JSON object"
    symbols = document.get("symbols")
    entries = symbols if isinstance(symbols, dict) else document
    return {key: value for key, value in entries.items() if isinstance(value, dict)}


def _read_manifest(client) -> dict[str, dict]:
    raw = _r2_get(client, "meta/manifest.json")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        pytest.fail("A-PS-58 red: meta/manifest.json in R2 is not JSON")
    return _manifest_entries(document)


MIRROR = Path("/mnt/d/portfoliosight-data")
MIN_SEEDED = 1400
SAMPLE = 20
CRON_LINE = (
    "30 5 * * * $HOME/programming/portfoliosight/scripts/r2_backup.sh "
    ">> $HOME/.local/state/portfoliosight/r2_backup.log 2>&1"
)


def _require_mirror_drive() -> None:
    if not os.path.ismount("/mnt/d"):
        pytest.fail("A-PS-58 red: D: drive is not mounted at /mnt/d; the mirror cannot be checked")


def _require_mirror() -> None:
    _require_mirror_drive()
    if not MIRROR.is_dir():
        pytest.fail(f"A-PS-58 red: the mirror directory {MIRROR} does not exist (backup never ran)")


_BACKUP: dict = {}


def _backup_started() -> datetime:
    """Run the product's backup once per test session; return the UTC instant it started."""
    if "started" in _BACKUP:
        return _BACKUP["started"]
    _require_mirror_drive()
    script = ROOT / "scripts" / "r2_backup.sh"
    if not script.is_file():
        pytest.fail("A-PS-58 red: scripts/r2_backup.sh does not exist")
    env = dict(os.environ)
    env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
    started = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            [str(script)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=1500
        )
    except subprocess.TimeoutExpired:
        pytest.fail("A-PS-58 red: scripts/r2_backup.sh ran over 1500 s")
    except OSError as exc:
        pytest.fail(f"A-PS-58 red: scripts/r2_backup.sh could not be run: {type(exc).__name__}")
    assert proc.returncode == 0, (
        f"scripts/r2_backup.sh exited {proc.returncode}: {_scrub(proc.stdout + proc.stderr)[-400:]}"
    )
    _BACKUP["started"] = started
    return started


def _list_objects(client, prefix: str) -> dict[str, tuple[int, datetime]]:
    """{key: (size, last modified UTC)} of every object under `prefix` in the bucket."""
    sizes: dict[str, tuple[int, datetime]] = {}
    try:
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
            for item in page.get("Contents", []):
                sizes[item["Key"]] = (int(item["Size"]), item["LastModified"])
    except Exception as exc:  # botocore ClientError / connection errors
        pytest.fail(
            f"A-PS-58 red: cannot list s3://{BUCKET}/{prefix} in R2: "
            f"{type(exc).__name__}: {_scrub(str(exc))[:300]}"
        )
    return sizes


def _sample(keys: list[str], count: int, seed: str) -> list[str]:
    return random.Random(seed).sample(sorted(keys), count)


def _cron_lines(listing: str) -> list[str]:
    """Active (non-comment) crontab lines that name the backup script."""
    lines = [line.strip() for line in listing.splitlines()]
    return [line for line in lines if "r2_backup.sh" in line and not line.startswith("#")]


if _OUTER:

    def test_a_ps_58_in_project_venv():
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
        assert proc.returncode == 0, "A-PS-58 is red inside the project virtualenv (output above)"

else:

    def test_store_verify_passes_against_the_bucket_and_leaves_no_probe():
        client = _r2_client()
        env = dict(os.environ, PS_STORE="r2", PS_R2_BUCKET=BUCKET)
        env.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD", None)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "portfoliosight.data.store", "--verify"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            pytest.fail(
                "A-PS-58 red: `python -m portfoliosight.data.store --verify` ran over 180 s"
            )
        output = proc.stdout + proc.stderr
        assert proc.returncode == 0, (
            f"`python -m portfoliosight.data.store --verify` exited {proc.returncode}: "
            f"{_scrub(output)[-600:]}"
        )
        assert BUCKET in output, "the verify output does not name the bucket portfoliosight-data"
        leaked = [
            n
            for n in SECRET_NAMES
            if os.environ.get(n, "").strip() and os.environ[n].strip() in output
        ]
        assert not leaked, f"the verify output prints the value of {leaked}"
        try:
            client.head_object(Bucket=BUCKET, Key="meta/_probe")
            probe_left = True
        except Exception as exc:
            code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if code not in ("404", "NoSuchKey", "NotFound"):
                pytest.fail(
                    "A-PS-58 red: cannot check meta/_probe in R2: "
                    f"{type(exc).__name__}: {_scrub(str(exc))[:300]}"
                )
            probe_left = False
        assert not probe_left, "meta/_probe still exists: the verify did not delete its probe"

    def test_manifest_holds_at_least_1400_seeded_symbols_with_adjusted_through():
        entries = _read_manifest(_r2_client())
        seeded = {k: v for k, v in entries.items() if "seed" in str(v.get("source") or "")}
        assert len(seeded) >= MIN_SEEDED, (
            f"meta/manifest.json has {len(seeded)} symbols with 'seed' in source "
            f"(of {len(entries)} entries), expected at least {MIN_SEEDED}"
        )
        missing = sorted(k for k, v in seeded.items() if not v.get("adjusted_through"))
        assert not missing, (
            f"{len(missing)} seeded symbols lack adjusted_through, e.g. {missing[:5]}"
        )
        bad = []
        for symbol, entry in seeded.items():
            try:
                date.fromisoformat(str(entry["adjusted_through"])[:10])
            except ValueError:
                bad.append(symbol)
        assert not bad, (
            f"{len(bad)} seeded symbols have a non-date adjusted_through, e.g. {sorted(bad)[:5]}"
        )

    def test_sampled_price_files_are_mirrored_with_the_same_size():
        started = _backup_started()
        _require_mirror()
        cutoff = started - timedelta(seconds=5)
        listing = _list_objects(_r2_client(), "prices/")
        every = [k for k in listing if k.endswith(".parquet")]
        assert len(every) >= MIN_SEEDED, (
            f"the bucket holds {len(every)} prices/*.parquet, expected >= {MIN_SEEDED}"
        )
        sizes = {k: listing[k][0] for k in every if listing[k][1] < cutoff}
        keys = list(sizes)
        print(f"A-PS-58: {len(every) - len(keys)} objects written since the backup started")
        assert len(keys) >= 1000, (
            f"only {len(keys)} of {len(every)} price objects predate the backup this test just "
            "ran: too few settled objects to sample"
        )
        seed = f"A-PS-58:{datetime.now(timezone.utc):%Y-%m-%d}"
        chosen = _sample(keys, SAMPLE, seed)
        print(f"A-PS-58: sample seed {seed!r}: {chosen}")
        checked = 0
        problems = []
        for key in chosen:
            local = MIRROR / key
            if not local.is_file():
                problems.append(f"{key}: not mirrored")
            elif local.stat().st_size != sizes[key]:
                problems.append(
                    f"{key}: mirror {local.stat().st_size} bytes != bucket {sizes[key]} bytes"
                )
            checked += 1
        assert checked == SAMPLE and len(set(chosen)) == SAMPLE, (
            f"checked {checked} keys, expected {SAMPLE}"
        )
        assert not problems, (
            f"mirror differs from the bucket for {len(problems)} of {SAMPLE} sampled keys: {problems}"
        )

    def test_restore_dry_run_would_upload_nothing():
        started = _backup_started()
        _require_mirror()
        endpoint = _r2_endpoint()
        mirrored = (
            sum(1 for p in (MIRROR / "prices").glob("*.parquet"))
            if (MIRROR / "prices").is_dir()
            else 0
        )
        assert mirrored >= MIN_SEEDED, (
            f"control failed: {MIRROR}/prices holds {mirrored} parquet files, expected >= {MIN_SEEDED}; "
            "an empty mirror would make the dry-run vacuous"
        )
        env = dict(
            os.environ,
            AWS_ACCESS_KEY_ID=_env("CLOUDFLARE_R2_ACCESS_KEY_ID"),
            AWS_SECRET_ACCESS_KEY=_env("CLOUDFLARE_R2_SECRET_ACCESS_KEY"),
            AWS_DEFAULT_REGION="auto",
        )
        env.pop("AWS_PROFILE", None)
        env.pop("AWS_SESSION_TOKEN", None)
        argv = [
            "aws",
            "s3",
            "sync",
            str(MIRROR),
            f"s3://{BUCKET}",
            "--dryrun",
            "--endpoint-url",
            endpoint,
        ]
        try:
            proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=600)
        except FileNotFoundError:
            pytest.fail("A-PS-58 red: the AWS CLI (`aws`) is not installed on this machine")
        except subprocess.TimeoutExpired:
            pytest.fail("A-PS-58 red: the restore dry-run (`aws s3 sync --dryrun`) ran over 600 s")
        assert proc.returncode == 0, (
            f"`aws s3 sync --dryrun` (restore direction) exited {proc.returncode}: {_scrub(proc.stderr)[-400:]}"
        )
        cutoff = started - timedelta(seconds=5)
        listing = _list_objects(_r2_client(), "")
        uploads = []
        for line in proc.stdout.splitlines():
            if "upload:" not in line:
                continue
            key = line.rsplit(f"s3://{BUCKET}/", 1)[-1].strip()
            fresh = key in listing and listing[key][1] >= cutoff
            if not fresh:  # only an object rewritten since the backup started may differ
                uploads.append(line)
        assert not uploads, (
            f"the restore dry-run would upload {len(uploads)} files, e.g. {_scrub(uploads[0])[:200]}"
        )
        assert "delete:" not in proc.stdout, (
            "the restore dry-run would delete objects in the bucket"
        )

    def test_crontab_has_exactly_one_backup_line_equal_to_the_spec():
        try:
            proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            pytest.fail("A-PS-58 red: `crontab` is not installed on this machine")
        except subprocess.TimeoutExpired:
            pytest.fail("A-PS-58 red: `crontab -l` did not finish within 30 s")
        lines = _cron_lines(proc.stdout)
        assert len(lines) != 0, (
            "crontab -l shows no r2_backup.sh line: the backup cron is not installed"
        )
        assert not len(lines) > 1, (
            f"crontab -l shows {len(lines)} r2_backup.sh lines, expected exactly one"
        )
        assert lines[0] == CRON_LINE, f"the cron line is {lines[0]!r}, expected {CRON_LINE!r}"
        active = [
            ln.strip()
            for ln in proc.stdout.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        project = [ln for ln in active if "portfoliosight" in ln.lower()]
        assert len(project) == 1, (
            f"crontab -l shows {len(project)} PortfolioSight lines, expected exactly one"
        )
