"""Every row of the spec 6 table, over a local store and real (small-grid) builds."""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime

import pytest

from portfoliosight.api.hashing import universe_hash
from portfoliosight.api.presets import preset_definitions, preset_funds
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.engine import ENGINE_VERSION
from portfoliosight.engine.tensor import validate_tensor
from tests.api.conftest import FakeClock, headers

MENU = ["VTI", "BND", "VNQ"]


def _funds(ids, **caps):
    return [
        {"id": i, "min": caps.get(i, (None, None))[0], "max": caps.get(i, (None, None))[1]}
        for i in ids
    ]


def _post(client, ids=MENU, lookback="1y", **caps):
    body = {"funds": _funds(ids, **caps), "lookback": lookback}
    return client.post("/v1/tensors", json=body, headers=headers())


def _poll(client, path: str, want: int, seconds: float = 60.0):
    deadline = time.monotonic() + seconds
    seen = []
    while time.monotonic() < deadline:
        response = client.get(path, headers=headers())
        seen.append(response.status_code)
        if response.status_code == want:
            return response
        time.sleep(0.05)
    pytest.fail(f"GET {path} never answered {want}; saw {seen[-5:]}")


def test_health_reports_generation_queue_and_nightly(make_client, store, generation, d_g):
    store_mod.put_json(store, "meta/status.json", {"D_G": d_g.isoformat(), "errors": []})
    clock = FakeClock(1_791_900_000.0)  # 2026-10-13 21:20 UTC, the day after the fixture's D_G
    client = make_client(start_worker=False, clock=clock)
    response = client.get("/v1/health", headers=headers())
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "status": "ok",
        "version": ENGINE_VERSION,
        "generation": generation,
        "asof": d_g.isoformat(),
        "asof_trading_days_behind": 0,
        "queue": {"depth": 0, "building": False},
        "nightly": {"D_G": d_g.isoformat(), "errors": []},
    }
    # A stopped nightly shows as a growing number while the generation stays the same.
    clock.t += 3 * 86_400
    assert client.get("/v1/health", headers=headers()).json()["asof_trading_days_behind"] == 3


def test_before_the_first_generation_nothing_pretends_to_be_ready(make_client, store):
    store.delete("meta/current.json")
    client = make_client(start_worker=False)
    health = client.get("/v1/health", headers=headers()).json()
    assert health["status"] == "initializing" and health["generation"] is None
    assert health["asof"] is None and health["asof_trading_days_behind"] is None
    assert health["nightly"] is None
    for response in (client.get("/v1/presets", headers=headers()), _post(client)):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "no_generation"
        assert response.headers["cache-control"] == "no-store"
    assert client.get("/v1/health", headers=headers()).json()["queue"]["depth"] == 0


def test_presets_and_symbols_are_served_as_stored(make_client, store, generation):
    client = make_client(start_worker=False)
    presets = client.get("/v1/presets", headers=headers())
    assert presets.status_code == 200
    assert presets.headers["cache-control"] == "public, max-age=300"
    assert presets.content == store.get(f"meta/{generation}/presets.json")
    symbols = client.get("/v1/symbols", headers=headers())
    assert symbols.status_code == 200
    assert symbols.headers["cache-control"] == "public, max-age=3600"
    assert symbols.content == store.get("meta/symbols.json")
    listed = {entry["id"] for entry in symbols.json()["symbols"]}
    assert "VTI" in listed and "FIENX" not in listed  # status ok only


def test_presets_are_composed_when_the_generation_has_no_stored_body(
    make_client, store, generation, d_g
):
    store.delete(f"meta/{generation}/presets.json")
    client = make_client(start_worker=False)
    body = client.get("/v1/presets", headers=headers()).json()
    assert body["generation"] == generation and body["asof"] == d_g.isoformat()
    assert [preset["id"] for preset in body["presets"]] == ["guide2017", "tsp"]
    assert "/v1/" not in json.dumps(body)


def test_symbols_before_the_catalog_exists(make_client, store):
    store.delete("meta/symbols.json")
    client = make_client(start_worker=False)
    response = client.get("/v1/symbols", headers=headers())
    assert response.status_code == 503 and response.json()["error"]["code"] == "no_catalog"


def test_post_then_poll_reaches_the_tensor(make_client, store, generation):
    client = make_client()
    uhash = universe_hash(_funds(MENU))
    path = f"/v1/tensors/{generation}/{uhash}/1y"
    assert client.get(path, headers=headers()).json()["error"]["code"] == "unknown_tensor"
    first = _post(client)
    assert first.status_code == 202 and first.headers["cache-control"] == "no-store"
    body = first.json()
    assert set(body) == {"status", "generation", "hash", "position", "eta_s"}
    assert body["status"] in ("queued", "building") and body["hash"] == uhash
    assert body["generation"] == generation and isinstance(body["eta_s"], int)
    ready = _poll(client, path, 200)
    tensor = ready.json()
    validate_tensor(tensor)
    assert tensor["generation"] == generation and tensor["universe"]["hash"] == uhash
    assert tensor["lookback"]["id"] == "1y" and len(tensor["frontier"]["x"]) == 12
    assert ready.headers["cache-control"] == "public, max-age=86400, immutable"
    assert re.fullmatch(r'"[0-9a-f]{32}"', ready.headers["etag"])
    assert ready.content == store.get(f"tensors/{generation}/{uhash}/1y.json")
    again = _post(client)
    assert again.status_code == 200
    assert again.json() == {
        "status": "ready",
        "generation": generation,
        "hash": uhash,
        "url": f"/api/tensors/{generation}/{uhash}/1y",
    }
    assert client.get(path, headers=headers()).headers["etag"] == ready.headers["etag"]


def test_only_the_requested_lookback_is_built_and_the_hash_is_shared(
    make_client, store, generation
):
    client = make_client()
    first, second = _post(client, lookback="1y"), _post(client, lookback="2y")
    assert first.json()["hash"] == second.json()["hash"]
    uhash = first.json()["hash"]
    _poll(client, f"/v1/tensors/{generation}/{uhash}/1y", 200)
    _poll(client, f"/v1/tensors/{generation}/{uhash}/2y", 200)
    assert store.list(f"tensors/{generation}/") == [
        f"tensors/{generation}/{uhash}/1y.json",
        f"tensors/{generation}/{uhash}/2y.json",
    ]
    assert client.get(f"/v1/tensors/{generation}/{uhash}/5y", headers=headers()).status_code == 404


def test_a_tensor_in_the_store_is_served_without_a_job(make_client, store, generation):
    guide = preset_definitions()[0]
    uhash = universe_hash(preset_funds(guide))
    store.put(f"tensors/{generation}/{uhash}/5y.json", b'{"schema":2}')
    client = make_client(start_worker=False)
    response = client.get(f"/v1/tensors/{generation}/{uhash}/5y", headers=headers())
    assert response.status_code == 200 and response.content == b'{"schema":2}'
    posted = _post(client, ids=list(guide.funds), lookback="5y")
    assert posted.status_code == 200 and posted.json()["status"] == "ready"


def test_unknown_symbols_are_listed_and_a_known_unserved_fund_is_accepted(make_client, generation):
    client = make_client()
    refused = _post(client, ids=["VTI", "ZZZQ", "QQQX"])
    assert refused.status_code == 400
    error = refused.json()["error"]
    assert error["code"] == "unknown_symbols" and error["details"] == {"symbols": ["ZZZQ", "QQQX"]}
    accepted = _post(client, ids=[*MENU, "FIENX"])
    assert accepted.status_code == 202
    tensor = _poll(client, f"/v1/tensors/{generation}/{accepted.json()['hash']}/1y", 200).json()
    assert [fund["id"] for fund in tensor["universe"]["excluded"]] == ["FIENX"]


def test_a_window_without_enough_shared_history_fails_once_with_the_reason(
    make_client, store, generation
):
    """Review focus 1: the short window says why and is not retried; 1y still builds."""
    for symbol in ("VTI", "BND"):
        record = store_mod.get_record(store, symbol)
        short = record.iloc[-400:].reset_index(drop=True)
        short["tr_index"] = short["tr_index"] / short["tr_index"].iloc[0]
        store_mod.put_record(store, symbol, short)
        catalog = manifest_mod.load_manifest(store)
        catalog.symbols[symbol].fetched_at = "2026-10-13T10:00:00+00:00"
        manifest_mod.write_catalog(store, catalog, datetime(2026, 10, 13, tzinfo=UTC))
    client = make_client()
    posted = _post(client, ids=["VTI", "BND"], lookback="5y")
    assert posted.status_code == 202
    uhash = posted.json()["hash"]
    failed = _poll(client, f"/v1/tensors/{generation}/{uhash}/5y", 409)
    assert failed.headers["cache-control"] == "no-store" and "etag" not in failed.headers
    assert failed.json() == {
        "status": "failed",
        "error": "window_unavailable",
        "attempts": 1,
        "retry": False,
        "details": {"lookback": "5y", "reason": "not enough shared history", "rows": 0},
    }
    assert _post(client, ids=["VTI", "BND"], lookback="5y").status_code == 409
    assert _post(client, ids=["VTI", "BND"], lookback="1y").status_code == 202
    _poll(client, f"/v1/tensors/{generation}/{uhash}/1y", 200)


def test_a_generation_pruned_before_the_build_is_generation_gone(make_client, store, generation):
    """Review focus 3."""
    client = make_client(start_worker=False)
    posted = _post(client)
    assert posted.status_code == 202 and posted.json()["status"] == "queued"
    store.delete(f"meta/{generation}/generation.json")
    client.app.state.queue.resume()
    failed = _poll(client, f"/v1/tensors/{generation}/{posted.json()['hash']}/1y", 409)
    body = failed.json()
    assert (body["error"], body["attempts"], body["retry"]) == ("generation_gone", 1, False)


def test_a_failing_build_is_retried_by_later_posts_then_given_up(make_client, generation):
    calls = []

    def failing(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("fault with details that must not reach the client")

    client = make_client(build_fn=failing)
    path = f"/v1/tensors/{generation}/{universe_hash(_funds(MENU))}/1y"
    for attempt in (1, 2, 3):
        assert _post(client).status_code in (202, 409)
        body: dict = {}
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and body.get("attempts") != attempt:
            body = client.get(path, headers=headers()).json()
            time.sleep(0.02)
        assert body == {
            "status": "failed",
            "error": "build_failed",
            "attempts": attempt,
            "retry": attempt < 3,
            "details": None,
        }
    final = _post(client)
    assert final.status_code == 409 and final.json()["retry"] is False
    time.sleep(0.1)
    assert len(calls) == 3


def test_the_generation_is_read_at_post_time(make_client, store, generation, d_g):
    client = make_client(start_worker=False)
    old = _post(client).json()
    newer = f"{d_g.isoformat()}-{ENGINE_VERSION}.1"
    store_mod.put_json(store, "meta/current.json", {"generation": newer, "published_at": "x"})
    new = _post(client).json()
    assert (old["generation"], new["generation"]) == (generation, newer)
    assert old["hash"] == new["hash"]
    assert client.get("/v1/health", headers=headers()).json()["queue"]["depth"] == 2
    still = client.get(f"/v1/tensors/{generation}/{old['hash']}/1y", headers=headers())
    assert still.status_code == 202 and still.json()["generation"] == generation


def test_a_full_queue_answers_busy(make_client, generation):
    client = make_client(start_worker=False)
    ids = ["VTI", "VTV", "VOE", "VB", "VBR", "VEA", "VWO"]
    pairs = [[a, b] for i, a in enumerate(ids) for b in ids[i + 1 :]]
    for pair in pairs[:20]:
        assert _post(client, ids=pair).status_code == 202
    busy = _post(client, ids=pairs[20])
    assert busy.status_code == 503 and busy.json()["error"]["code"] == "busy"
    assert busy.headers["cache-control"] == "no-store"
    assert _post(client, ids=pairs[0]).status_code == 202  # a known key is not a new job
    assert client.get("/v1/health", headers=headers()).json()["queue"]["depth"] == 20
    refused = f"/v1/tensors/{generation}/{universe_hash(_funds(pairs[20]))}/1y"
    assert client.get(refused, headers=headers()).status_code == 404
