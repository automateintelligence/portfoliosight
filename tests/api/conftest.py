"""Fixtures for the API tests: a seeded local store, a published generation, a gated client."""

from __future__ import annotations

import itertools
import json
import shutil
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from portfoliosight.data.store import LocalStore, put_json
from portfoliosight.engine import ENGINE_VERSION
from portfoliosight.jobs.fixture_store import fixture_asof, write_fixture_store

GATE = "unit-test-gate-secret-0123456789"
_IPS = itertools.count(1)


def fresh_ip() -> str:
    """A CF-Connecting-IP no other request used, so the limiter never couples two tests."""
    n = next(_IPS)
    return f"10.{(n >> 16) & 255}.{(n >> 8) & 255}.{n & 255}"


def headers(ip: str | None = None, **extra: str) -> dict[str, str]:
    return {"x-ps-gate": GATE, "CF-Connecting-IP": ip or fresh_ip(), **extra}


class FakeClock:
    """Epoch seconds that move only when a test moves them."""

    def __init__(self, start: float = 1_800_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


@pytest.fixture(scope="session")
def _fixture_store_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("fixture-store")
    write_fixture_store(directory)
    return directory


@pytest.fixture(scope="session")
def d_g() -> date:
    return fixture_asof()


@pytest.fixture(scope="session")
def generation(d_g: date) -> str:
    return f"{d_g.isoformat()}-{ENGINE_VERSION}"


@pytest.fixture
def store(_fixture_store_dir: Path, tmp_path: Path, d_g: date, generation: str) -> LocalStore:
    """A private copy of the fixture store with a hand-published generation and no tensors."""
    root = tmp_path / "store"
    shutil.copytree(_fixture_store_dir, root)
    store = LocalStore(root)
    put_json(
        store,
        f"meta/{generation}/generation.json",
        {"generation": generation, "asof": d_g.isoformat(), "engine_version": ENGINE_VERSION},
    )
    put_json(
        store,
        f"meta/{generation}/presets.json",
        {"generation": generation, "asof": d_g.isoformat(), "presets": []},
    )
    put_json(
        store,
        "meta/current.json",
        {"generation": generation, "published_at": "2026-10-13T09:30:00+00:00"},
    )
    return store


@pytest.fixture
def api_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The gate secret, a scratch cache and a small grid, so a real build takes seconds."""
    monkeypatch.setenv("PS_GATE_SECRET", GATE)
    monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PS_CACHE_MAX_MB", "300")
    monkeypatch.setenv("PS_GRID_NX", "12")
    monkeypatch.setenv("PS_GRID_NY", "8")


@pytest.fixture
def make_client(api_env: None, store: LocalStore) -> Iterator[Callable[..., TestClient]]:
    """``make_client(**create_app_kwargs)``: an entered ``TestClient`` over the test store."""
    from portfoliosight.api.app import create_app

    opened: list[TestClient] = []

    def _make(**kwargs) -> TestClient:
        kwargs.setdefault("store", store)
        client = TestClient(create_app(**kwargs), raise_server_exceptions=False)
        client.__enter__()
        opened.append(client)
        return client

    yield _make
    for client in opened:
        client.__exit__(None, None, None)


def body_of(response) -> dict:
    return json.loads(response.content)
