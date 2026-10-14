"""The API surface is the six routes of spec 6 and nothing else."""

from __future__ import annotations

import re
from typing import cast

import pytest

from portfoliosight.data.store import Store
from tests.api.conftest import headers

GOOD_HASH = "0123456789abcdef"


class _Counting:
    def __init__(self, inner):
        self._inner = inner
        self.calls = 0

    def __getattr__(self, name):
        attribute = getattr(self._inner, name)
        if name in ("get", "put", "exists", "list", "delete"):
            self.calls += 1
        return attribute


def test_routes_are_exactly_the_six(make_client):
    client = make_client(start_worker=False)
    routes = set()
    for route in client.app.routes:
        for method in route.methods:
            routes.add((method, re.sub(r"\{[^}]*\}", "{}", route.path)))
    assert routes == {
        ("GET", "/v1/health"),
        ("GET", "/v1/presets"),
        ("GET", "/v1/symbols"),
        ("POST", "/v1/tensors"),
        ("GET", "/v1/tensors/{}/{}/{}"),
        ("POST", "/v1/range"),
    }
    forbidden = re.compile(r"login|auth|account|signup|pay|checkout", re.IGNORECASE)
    assert not [route.path for route in client.app.routes if forbidden.search(route.path)]


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/v1/tensors", 405),
        ("DELETE", "/v1/tensors", 405),
        ("POST", "/v1/health", 405),
        ("GET", "/v1/range", 405),
        ("POST", "/v1/ranges", 404),
        ("PUT", f"/v1/tensors/2026-10-12-0.1.0/{GOOD_HASH}/5y", 405),
        ("GET", "/v1/jobs", 404),
        ("GET", "/v1/", 404),
        ("GET", "/login", 404),
        ("GET", "/", 404),
    ],
)
def test_unlisted_methods_and_paths_answer_with_the_envelope(make_client, method, path, status):
    client = make_client(start_worker=False)
    response = client.request(method, path, headers=headers())
    assert response.status_code == status
    assert response.json()["error"]["code"] in ("not_found", "method_not_allowed")
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "path",
    [
        "/v1/tensors/2026-10-12-0.1.0/zz/5y",
        "/v1/tensors/bad/0123456789abcdef/5y",
        f"/v1/tensors/2026-10-12-0.1.0/{GOOD_HASH[:-1]}/5y",
        f"/v1/tensors/2026-10-12-0.1.0/{GOOD_HASH}0/5y",
        f"/v1/tensors/2026-10-12-0.1.0/{GOOD_HASH.upper()}/5y",
        f"/v1/tensors/2026-10-7-0.1.0/{GOOD_HASH}/5y",
        f"/v1/tensors/2026-10-12-/{GOOD_HASH}/5y",
        f"/v1/tensors/2026-10-12-0.1.0a/{GOOD_HASH}/5y",
        f"/v1/tensors/2026-10-12-0.1.0/{GOOD_HASH}/4y",
        f"/v1/tensors/2026-10-12-0.1.0/{GOOD_HASH}/5y.json",
        f"/v1/tensors/2026-10-12-0.1.0%0A/{GOOD_HASH}/5y",
    ],
)
def test_malformed_tensor_addresses_never_reach_the_store(make_client, store, path):
    counting = _Counting(store)
    client = make_client(start_worker=False, store=counting)
    response = client.get(path, headers=headers())
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_request"
    assert counting.calls == 0


def test_a_well_formed_unknown_address_is_unknown_tensor(make_client, generation):
    client = make_client(start_worker=False)
    response = client.get(f"/v1/tensors/{generation}/{GOOD_HASH}/5y", headers=headers())
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "unknown_tensor",
        "message": "No tensor was requested under this address.",
        "details": None,
    }
    assert response.headers["cache-control"] == "no-store"


def test_an_unexpected_error_is_an_envelope_and_a_redacted_log_line(
    api_env, store, monkeypatch, caplog
):
    """The failure is answered and logged here; it never leaves the app for the server to print."""
    from fastapi.testclient import TestClient

    from portfoliosight.api.app import create_app

    monkeypatch.setenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "r2-secret-value-0123456789")

    class Broken:
        def __getattr__(self, name):
            return getattr(store, name)

        def get(self, key):
            raise OSError("signature mismatch for key r2-secret-value-0123456789")

    app = create_app(store=cast(Store, Broken()), start_worker=False)
    # raise_server_exceptions=True: an exception that escaped the app would raise right here.
    with TestClient(app, raise_server_exceptions=True) as client, caplog.at_level("ERROR"):
        response = client.get("/v1/symbols", headers=headers())
        health = client.get("/v1/health", headers=headers())
    for answer in (response, health):
        assert answer.status_code == 500
        assert answer.json()["error"] == {
            "code": "internal_error",
            "message": "The service could not answer.",
            "details": None,
        }
        assert answer.headers["cache-control"] == "no-store"
        assert "r2-secret-value" not in answer.text
    assert "unhandled error" in caplog.text and "OSError: signature mismatch" in caplog.text
    assert "Traceback" in caplog.text and "[redacted]" in caplog.text
    assert "r2-secret-value-0123456789" not in caplog.text
