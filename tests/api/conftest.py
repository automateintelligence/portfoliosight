"""Fixtures for the API tests: the gate secret, a fake clock and a gated client."""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from portfoliosight.data.store import LocalStore

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


@pytest.fixture
def api_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The gate secret, a scratch cache and a small grid, so a real build takes seconds."""
    monkeypatch.setenv("PS_GATE_SECRET", GATE)
    monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PS_CACHE_MAX_MB", "300")
    monkeypatch.setenv("PS_GRID_NX", "12")
    monkeypatch.setenv("PS_GRID_NY", "8")
    monkeypatch.setenv("PS_GRID_LEVELS", "3")


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
