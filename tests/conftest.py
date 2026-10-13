"""Shared pytest configuration: the `live` marker, its single sanctioned skip, the fixture store."""

from __future__ import annotations

import os
import shutil
from datetime import date
from pathlib import Path

import pytest

from portfoliosight.data.store import LocalStore, put_json
from portfoliosight.engine import ENGINE_VERSION
from portfoliosight.jobs.fixture_store import fixture_asof, write_fixture_store

LIVE_ENV = "PS_LIVE_TESTS"
LIVE_SKIP_REASON = "PS_LIVE_TESTS=1 required"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: needs ~/.secrets/portfoliosight.env and the network")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get(LIVE_ENV) == "1":
        return
    skip_live = pytest.mark.skip(reason=LIVE_SKIP_REASON)
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


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
