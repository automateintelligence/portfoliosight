"""Input limits and rate limits: refused requests get their code and leave no job behind."""

from __future__ import annotations

import json

import pytest

from portfoliosight.api.limiter import RateLimiter
from tests.api.conftest import FakeClock, headers

TWO = [{"id": "VTI", "min": None, "max": None}, {"id": "BND", "min": None, "max": None}]


def _raw(client, payload: bytes):
    return client.post(
        "/v1/tensors", content=payload, headers=headers(**{"content-type": "application/json"})
    )


def _body(funds=TWO, lookback="1y", **extra) -> bytes:
    return json.dumps({"funds": funds, "lookback": lookback, **extra}).encode()


def _depth(client) -> int:
    return client.get("/v1/health", headers=headers()).json()["queue"]["depth"]


@pytest.fixture
def paused(make_client):
    built = []
    client = make_client(start_worker=False, build_fn=lambda *a, **k: built.append(a))
    yield client
    assert built == []


@pytest.mark.parametrize(
    ("payload", "names"),
    [
        (b"not json at all", None),
        (b"[]", None),
        (_body(lookback="4y"), "lookback"),
        (_body(lookback="5Y"), "lookback"),
        (_body(funds=TWO[:1]), "funds"),
        (_body(funds=[]), "funds"),
        (_body(funds=[{"id": f"F{n}", "min": None, "max": None} for n in range(31)]), "funds"),
        (_body(funds=[*TWO, TWO[0]]), "VTI"),
        (_body(funds=[{"id": "vti"}, TWO[1]]), "funds.0.id"),
        (_body(funds=[{"id": "VTI/../X"}, TWO[1]]), "funds.0.id"),
        (_body(funds=[{"id": "VTI", "max": "0.5"}, TWO[1]]), "funds.0.max"),
        (_body(funds=[{"id": "VTI", "max": True}, TWO[1]]), "funds.0.max"),
        (b'{"funds":[{"id":"VTI","max":NaN},{"id":"BND"}],"lookback":"1y"}', None),
        (b'{"funds":[{"id":"VTI","max":Infinity},{"id":"BND"}],"lookback":"1y"}', None),
        (_body(funds=[{"id": "VTI", "weight": 1}, TWO[1]]), "funds.0.weight"),
        (_body(extra_key=1), "extra_key"),
        (_body(funds=[{"id": "VTI", "min": 0.5, "max": 0.2}, TWO[1]]), "VTI"),
        (_body(funds=[{"id": "VTI", "max": 1.5}, TWO[1]]), "VTI"),
        (_body(funds=[{"id": "VTI", "min": -0.1}, TWO[1]]), "VTI"),
        (_body(funds=[{"id": "VTI", "min": 0.6}, {"id": "BND", "min": 0.6}]), "sum"),
        (_body(funds=[{"id": "VTI", "max": 0.4}, {"id": "BND", "max": 0.4}]), "sum"),
    ],
)
def test_invalid_requests_are_422_and_enqueue_nothing(paused, store, payload, names):
    tensors_before = store.list("tensors/")
    response = _raw(paused, payload)
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "invalid_request" and isinstance(error["message"], str)
    if names:
        assert names.lower() in json.dumps(error).lower()
    assert response.headers["cache-control"] == "no-store"
    assert _depth(paused) == 0 and store.list("tensors/") == tensors_before


def test_an_invalid_request_is_not_echoed_back(paused):
    marker = "ECHO-MARKER-1234"
    response = _raw(paused, _body(funds=[{"id": "VTI", "max": marker}, TWO[1]]))
    assert response.status_code == 422 and marker not in response.text


def test_integer_caps_are_numbers(paused):
    funds = [{"id": "VTI", "min": 0, "max": 1}, {"id": "BND", "min": None, "max": 1}]
    assert _raw(paused, _body(funds=funds)).status_code == 202


def test_body_limit_is_sixteen_kilobytes(paused):
    core = _body()

    def padded(size: int) -> bytes:
        return core[:-1] + b" " * (size - len(core)) + b"}"

    assert _raw(paused, padded(16 * 1024)).status_code == 202
    for payload in (padded(16 * 1024 + 1), b"x" * (64 * 1024)):
        response = _raw(paused, payload)
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"
    assert _depth(paused) == 1


def test_body_limit_holds_without_a_declared_length(paused):
    def chunks():
        for _ in range(40):
            yield b" " * 1024
        yield _body()

    response = paused.post(
        "/v1/tensors", content=chunks(), headers=headers(**{"content-type": "application/json"})
    )
    assert response.status_code == 413 and _depth(paused) == 0


def test_sixth_post_in_a_minute_from_one_ip_is_limited(make_client):
    clock = FakeClock()
    client = make_client(start_worker=False, clock=clock, build_fn=lambda *a, **k: None)
    ids = ["VTI", "VTV", "VOE", "VB", "VBR", "VEA", "VWO"]

    def post(n: int, ip: str):
        funds = [{"id": ids[0]}, {"id": ids[n + 1]}]
        return client.post(
            "/v1/tensors", json={"funds": funds, "lookback": "1y"}, headers=headers(ip)
        )

    for n in range(5):
        assert post(n, "203.0.113.7").status_code == 202
    limited = post(5, "203.0.113.7")
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"
    assert limited.headers["cache-control"] == "no-store"
    assert post(5, "198.51.100.9").status_code == 202
    assert _depth(client) == 6
    clock.t += 59.0
    assert post(5, "203.0.113.7").status_code == 429
    clock.t += 2.0
    assert post(5, "203.0.113.7").status_code == 202


def test_sixty_first_request_in_a_minute_from_one_ip_is_limited(make_client):
    clock = FakeClock()
    client = make_client(start_worker=False, clock=clock)
    for _ in range(60):
        assert client.get("/v1/health", headers=headers("203.0.113.50")).status_code == 200
    over = client.get("/v1/symbols", headers=headers("203.0.113.50"))
    assert over.status_code == 429 and over.json()["error"]["code"] == "rate_limited"
    assert client.get("/v1/health", headers=headers("198.51.100.51")).status_code == 200
    # A request without the secret is refused before it is counted.
    assert client.get("/v1/health", headers={"CF-Connecting-IP": "203.0.113.50"}).status_code == 403
    clock.t += 61.0
    assert client.get("/v1/health", headers=headers("203.0.113.50")).status_code == 200


def test_requests_without_the_cloudflare_header_share_the_peer_address(make_client):
    clock = FakeClock()
    client = make_client(start_worker=False, clock=clock)
    gate_only = {"x-ps-gate": headers()["x-ps-gate"]}
    statuses = [client.get("/v1/health", headers=gate_only).status_code for _ in range(61)]
    assert statuses[:60] == [200] * 60 and statuses[60] == 429


def test_limiter_window_slides_and_idle_keys_are_swept():
    clock = FakeClock(0.0)
    limiter = RateLimiter(2, clock, window=60.0)
    assert limiter.admit("a") and limiter.admit("a") and not limiter.admit("a")
    clock.t = 30.0
    assert limiter.admit("b")
    clock.t = 60.0
    assert limiter.admit("a") and limiter.admit("a") and not limiter.admit("a")
    clock.t = 1000.0
    for n in range(1024):
        assert limiter.admit(f"k{n}")
    assert "a" not in limiter._admitted and "b" not in limiter._admitted
