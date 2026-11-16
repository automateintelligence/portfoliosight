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


def test_retry_after_is_whole_seconds_until_the_next_admission():
    clock = FakeClock(1_000.0)
    limiter = RateLimiter(3, clock, window=60.0)
    assert limiter.retry_after("a") == 0  # a key never seen would be admitted now
    for at in (1_000.0, 1_010.0, 1_025.5):
        clock.t = at
        assert limiter.admit("a")
    assert limiter.retry_after("a") == 35  # 1_000 + 60 - 1_025.5 = 34.5, rounded up
    clock.t = 1_040.0
    assert limiter.retry_after("a") == 20
    clock.t = 1_059.0
    assert limiter.retry_after("a") == 1
    clock.t = 1_059.01
    assert limiter.retry_after("a") == 1  # under a second left still says 1, never 0
    clock.t = 1_060.0
    assert limiter.retry_after("a") == 0  # the oldest has left the window: a slot is free
    assert limiter.admit("a")
    assert limiter.retry_after("a") == 10  # the next oldest, 1_010, leaves at 1_070


def test_retry_after_counts_nothing_and_is_per_key():
    clock = FakeClock(0.0)
    limiter = RateLimiter(1, clock, window=60.0)
    assert limiter.admit("a")
    clock.t = 20.0
    assert limiter.retry_after("a") == 40
    assert limiter.retry_after("a") == 40  # asking does not change the answer
    assert limiter.retry_after("b") == 0
    assert limiter.admit("b")  # asking about "b" did not use up its slot
    clock.t = 60.0
    assert limiter.admit("a")  # nor did asking about "a"


def test_a_refused_post_says_how_long_to_wait(make_client):
    clock = FakeClock()
    client = make_client(start_worker=False, clock=clock, build_fn=lambda *a, **k: None)
    ids = ["VTI", "VTV", "VOE", "VB", "VBR", "VEA", "VWO"]
    ip = "203.0.113.7"

    def post(n: int, from_ip: str = ip):
        funds = [{"id": ids[0]}, {"id": ids[n + 1]}]
        return client.post(
            "/v1/tensors", json={"funds": funds, "lookback": "1y"}, headers=headers(from_ip)
        )

    for n in range(5):
        accepted = post(n)
        assert accepted.status_code == 202 and "retry-after" not in accepted.headers
        clock.t += 10.0
    # The five admitted POSTs left at 0, 10, ..., 40 s; the first leaves the window at 60 s.
    limited = post(5)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "10"
    assert limited.headers["cache-control"] == "no-store"
    # The envelope is the spec 6 one; the wait is in the header only.
    assert limited.json() == {
        "error": {
            "code": "rate_limited",
            "message": "Too many requests; try again in a minute.",
            "details": None,
        }
    }
    clock.t += 4.5
    again = post(5)
    assert again.status_code == 429 and again.headers["retry-after"] == "6"  # 5.5 s, rounded up
    # Waiting what the header says is enough.
    clock.t += 6.0
    assert post(5).status_code == 202
    # A caller who is not limited gets no header, and neither does another kind of refusal.
    other = post(5, "198.51.100.9")
    assert other.status_code == 202 and "retry-after" not in other.headers
    invalid = client.post("/v1/tensors", json={"funds": [], "lookback": "1y"}, headers=headers())
    assert invalid.status_code == 422 and "retry-after" not in invalid.headers


def test_a_request_over_the_sixty_a_minute_limit_says_how_long_to_wait(make_client):
    clock = FakeClock()
    client = make_client(start_worker=False, clock=clock)
    ip = "203.0.113.50"
    for _ in range(60):
        ok = client.get("/v1/health", headers=headers(ip))
        assert ok.status_code == 200 and "retry-after" not in ok.headers
        clock.t += 0.5
    # The first request was 30 s ago; it leaves the window in 30 more.
    over = client.get("/v1/symbols", headers=headers(ip))
    assert over.status_code == 429 and over.headers["retry-after"] == "30"
    assert over.json()["error"]["code"] == "rate_limited"
    # A POST over this limit is refused by it first, with its wait.
    post = client.post("/v1/tensors", json={"funds": [], "lookback": "1y"}, headers=headers(ip))
    assert post.status_code == 429 and post.headers["retry-after"] == "30"
    clock.t += 0.25
    later = client.get("/v1/symbols", headers=headers(ip))
    assert later.status_code == 429 and later.headers["retry-after"] == "30"  # 29.75 s, rounded up
    clock.t += 30.0
    assert client.get("/v1/health", headers=headers(ip)).status_code == 200
    # A caller refused for the gate is not counted and gets no wait.
    forbidden = client.get("/v1/health", headers={"CF-Connecting-IP": ip})
    assert forbidden.status_code == 403 and "retry-after" not in forbidden.headers


def test_a_post_refused_by_the_request_limiter_waits_for_the_post_limiter_too(make_client):
    clock = FakeClock()
    client = make_client(start_worker=False, clock=clock, build_fn=lambda *a, **k: None)
    ids = ["VTI", "VTV", "VOE", "VB", "VBR", "VEA", "VWO"]
    ip = "203.0.113.60"

    def post(n: int):
        funds = [{"id": ids[0]}, {"id": ids[n + 1]}]
        return client.post(
            "/v1/tensors", json={"funds": funds, "lookback": "1y"}, headers=headers(ip)
        )

    # 55 requests at 0 s, then 5 POSTs at 50 s: both limiters are full at 50 s. The request
    # limiter frees a slot at 60 s, the post limiter not before 110 s.
    for _ in range(55):
        assert client.get("/v1/health", headers=headers(ip)).status_code == 200
    clock.t += 50.0
    for n in range(5):
        assert post(n).status_code == 202
    refused = post(5)
    assert refused.status_code == 429
    assert refused.headers["retry-after"] == "60"  # not 10: waiting 10 s would be refused again
    # A request that is not a POST of a tensor waits for the request limiter alone.
    assert client.get("/v1/health", headers=headers(ip)).headers["retry-after"] == "10"
    clock.t += 60.0
    assert post(5).status_code == 202  # the advertised wait was enough
