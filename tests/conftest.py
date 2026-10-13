"""Shared pytest configuration: the `live` marker and its single sanctioned skip."""

from __future__ import annotations

import os

import pytest

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
