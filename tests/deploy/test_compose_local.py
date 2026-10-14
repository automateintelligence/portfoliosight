"""The local compose file is standalone, offline and holds only dummy values (plan task 4.8)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "deploy" / "docker-compose.local.yml"
PRODUCTION = ROOT / "deploy" / "docker-compose.yml"
SHARED = {
    "PS_STORE": "local",
    "PS_LOCAL_STORE_DIR": "/fixture",
    "PS_CACHE_DIR": "/app/cache",
    "PS_CACHE_MAX_MB": "300",
    "PS_GATE_SECRET": "local-dev-secret",
    "TIINGO_API_KEY": "dummy",
    "CLOUDFLARE_ACCOUNT_ID": "dummy",
    "CLOUDFLARE_R2_ACCESS_KEY_ID": "dummy",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY": "dummy",
}
OFFLINE = {
    "PS_NIGHTLY_PROVIDERS": "fixture",
    "PS_FIXTURE_DIR": "/fixtures",
    "PS_FIXED_NOW": "2026-10-13T02:00:00-07:00",
    "PS_PROVIDER_REQ_PER_HOUR": "9000",
    "PS_PROVIDER_REQ_PER_DAY": "90000",
    "PS_PROVIDER_SYMBOLS_PER_MONTH": "100000",
}


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(LOCAL.read_text(encoding="utf-8"))


def test_file_is_standalone(compose):
    text = LOCAL.read_text(encoding="utf-8")
    assert compose["name"] == "portfoliosight-local"
    assert set(compose) == {"name", "services", "volumes"} and "include" not in compose
    assert set(compose["services"]) == {"api", "nightly"}
    for service in compose["services"].values():
        assert "env_file" not in service and "extends" not in service
        assert service["image"] == "portfoliosight:local"
        assert service["build"] == {"context": "..", "dockerfile": "deploy/Dockerfile"}
    # No interpolation at all: nothing from the caller's environment can reach a container.
    assert "${" not in text and "$" not in text.replace("$HOME", "")
    assert ".secrets" not in text


def test_every_value_is_a_dummy(compose):
    api, nightly = compose["services"]["api"], compose["services"]["nightly"]
    assert api["environment"] == SHARED
    assert nightly["environment"] == {**SHARED, **OFFLINE}


def test_nightly_has_no_network_and_reads_the_recorded_fixtures(compose):
    nightly = compose["services"]["nightly"]
    assert nightly["network_mode"] == "none" and "ports" not in nightly
    assert nightly["profiles"] == ["jobs"]
    assert nightly["command"] == "python -m portfoliosight.jobs.nightly"
    assert nightly["volumes"] == [
        "./.local-store:/fixture",
        "../tests/fixtures:/fixtures:ro",
        "ps-cache-local:/app/cache",
    ]


def test_api_keeps_the_production_shape(compose):
    api = compose["services"]["api"]
    production = yaml.safe_load(PRODUCTION.read_text(encoding="utf-8"))["services"]["api"]
    assert api["ports"] == production["ports"] == ["127.0.0.1:8010:8000"]
    assert api["deploy"] == production["deploy"]
    assert api["healthcheck"] == production["healthcheck"]
    assert api["volumes"] == ["./.local-store:/fixture", "ps-cache-local:/app/cache"]
    assert (
        compose["services"]["nightly"]["deploy"]["resources"]["limits"]
        == (production["deploy"]["resources"]["limits"])
    )
    assert compose["volumes"] == {"ps-cache-local": None}


def test_local_store_and_host_env_are_gitignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "deploy/.local-store/" in ignored and "deploy/.env" in ignored
