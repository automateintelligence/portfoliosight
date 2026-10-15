"""The production compose file and the systemd units (spec 9.1): limits, one port, no bind."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
COMPOSE = DEPLOY / "docker-compose.yml"
ENV_FILE = "~/.secrets/portfoliosight.env"
ENVIRONMENT = {
    "PS_STORE": "r2",
    "PS_R2_BUCKET": "portfoliosight-data",
    "PS_CACHE_DIR": "/app/cache",
    "PS_CACHE_MAX_MB": "300",
}
LOGGING = {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_api_service_is_the_spec_s(compose):
    api = compose["services"]["api"]
    assert api["image"] == "portfoliosight:${GIT_SHA}"
    assert api["build"] == {"context": "..", "dockerfile": "deploy/Dockerfile"}
    assert api["container_name"] == "portfoliosight-api"
    assert api["restart"] == "unless-stopped"
    assert api["ports"] == ["127.0.0.1:8010:8000"]
    assert api["volumes"] == ["ps-cache:/app/cache"]
    assert api["env_file"] == ENV_FILE and api["environment"] == ENVIRONMENT
    assert api["deploy"]["resources"] == {
        "limits": {"cpus": "4", "memory": "1536M"},
        "reservations": {"cpus": "0.5", "memory": "256M"},
    }
    assert api["logging"] == LOGGING
    health = api["healthcheck"]
    assert health["test"] == ["CMD", "python", "-m", "portfoliosight.api.healthcheck"]
    assert health["interval"] == "30s"
    assert "profiles" not in api and "privileged" not in api and "network_mode" not in api


def test_nightly_is_a_job_on_the_same_image_with_no_port(compose):
    nightly = compose["services"]["nightly"]
    assert nightly["image"] == compose["services"]["api"]["image"]
    assert nightly["profiles"] == ["jobs"]
    assert nightly["command"] == "python -m portfoliosight.jobs.nightly"
    assert "ports" not in nightly and "container_name" not in nightly
    assert nightly["volumes"] == ["ps-cache:/app/cache"]
    assert nightly["env_file"] == ENV_FILE and nightly["environment"] == ENVIRONMENT
    assert nightly["deploy"]["resources"]["limits"] == {"cpus": "4", "memory": "1536M"}
    assert nightly["logging"] == LOGGING


def test_file_holds_nothing_else(compose):
    assert set(compose) == {"name", "services", "volumes"}
    assert compose["name"] == "portfoliosight"
    assert set(compose["services"]) == {"api", "nightly"}
    assert compose["volumes"] == {"ps-cache": None}
    text = COMPOSE.read_text(encoding="utf-8")
    # The offline knobs of the local run never reach production.
    for knob in ("PS_NIGHTLY_PROVIDERS", "PS_FIXED_NOW", "PS_FIXTURE_DIR", "PS_GATE_SECRET"):
        assert knob not in text
    assert re.findall(r"\$\{([^}]+)\}", text) == ["GIT_SHA", "GIT_SHA"]


def test_systemd_units_are_templated_and_scheduled_at_two():
    service = (DEPLOY / "systemd" / "portfoliosight-nightly.service.in").read_text()
    assert "Type=oneshot" in service
    assert "User=__USER__" in service
    assert "WorkingDirectory=__HOME__/portfoliosight" in service
    assert (
        "ExecStart=/usr/bin/docker compose -f deploy/docker-compose.yml run --rm --no-deps nightly"
        in service
    )
    assert "/home/" not in service
    timer = (DEPLOY / "systemd" / "portfoliosight-nightly.timer").read_text()
    assert "OnCalendar=*-*-* 02:00:00" in timer and "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer
    assert sorted(path.name for path in (DEPLOY / "systemd").iterdir()) == [
        "portfoliosight-nightly.service.in",
        "portfoliosight-nightly.timer",
    ]


def test_dockerfile_follows_the_spec():
    text = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    assert re.findall(r"(?m)^FROM (\S+)", text) == ["python:3.12-slim", "python:3.12-slim"]
    assert 'pip install --no-cache-dir --prefix=/install ".[api]"' in text
    assert "--uid 10001" in text and re.findall(r"(?m)^USER (\S+)", text) == ["app"]
    assert "mkdir -p /app/cache && chown app:app /app/cache" in text
    assert (
        'CMD ["uvicorn", "portfoliosight.api.app:app", "--host", "0.0.0.0", "--port", "8000", '
        '"--limit-concurrency", "32"]' in text
    )
    # Nothing secret is baked in: no build argument, and ENV sets only runtime switches.
    assert "ARG " not in text and "SECRET" not in text and "KEY" not in text
