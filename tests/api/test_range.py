"""``POST /v1/range``: one-year ranges for a mix on a built menu."""

from __future__ import annotations

import json

import numpy as np
import pytest

from portfoliosight.api import ranges as ranges_mod
from portfoliosight.api.hashing import universe_hash
from portfoliosight.api.presets import tensor_key
from portfoliosight.api.queue import build_job
from tests.api.conftest import headers

MENU = ["VTI", "BND", "VNQ"]
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


@pytest.fixture
def built(store, generation, api_env) -> dict:
    """A real tensor of the three-fund menu, written to the store the client reads."""
    funds = [{"id": fund, "min": None, "max": None} for fund in MENU]
    uhash = universe_hash(funds)
    build_job(store, generation, uhash, "1y", funds)
    return json.loads(store.get(tensor_key(generation, uhash, "1y")))


def _body(tensor: dict, mix=(0.5, 0.3, 0.2), **changes) -> dict:
    body = {
        "generation": tensor["generation"],
        "hash": tensor["universe"]["hash"],
        "lookback": tensor["lookback"]["id"],
        "weights": list(mix),
    }
    return {**body, **changes}


def _post(client, body, **extra):
    return client.post("/v1/range", json=body, headers=headers(**extra))


def test_range_of_a_stored_mix_is_the_tensor_s_own(make_client, built):
    client = make_client(start_worker=False)
    for column in (0, 5, 11):
        response = _post(client, _body(built, built["frontier"]["w"][column]))
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        answer = response.json()
        assert set(answer) == {"bad", "typical", "good", "normal"}
        assert set(answer["normal"]) == {"low", "mid", "high"}
        stored = built["frontier"]["range"]  # equal up to the rounding of one product or many
        for name in ("bad", "typical", "good"):
            assert answer[name] == pytest.approx(stored[name][column], rel=1e-12, abs=1e-15)
        for name in ("low", "mid", "high"):
            expected = stored["normal"][name][column]
            assert answer["normal"][name] == pytest.approx(expected, rel=1e-12, abs=1e-15)
    peak = _post(client, _body(built, built["ladder"]["w"][5][-1])).json()
    assert peak["bad"] == pytest.approx(built["ladder"]["range"]["bad"][5][-1], rel=1e-12)


def test_range_of_any_other_mix_of_the_menu(make_client, built):
    """A mix the tensor does not hold, caps or no caps: the entered mix of a custom menu."""
    client = make_client(start_worker=False)
    answer = _post(client, _body(built, [1, 0, 0])).json()  # all in one fund, as integers
    assert answer["bad"] < answer["typical"] < answer["good"]
    mu, cov = np.array(built["mu_s"]), np.array(built["cov"])
    assert answer["normal"]["mid"] == pytest.approx(mu[0], abs=1e-15)
    assert answer["normal"]["low"] == pytest.approx(mu[0] - 1.96 * np.sqrt(cov[0, 0]), abs=1e-15)
    assert abs(answer["typical"] - answer["normal"]["mid"]) <= 0.05
    calm = _post(client, _body(built, [0.0, 1.0, 0.0])).json()
    assert calm["bad"] > answer["bad"] and calm["good"] < answer["good"]
    near_one = _post(client, _body(built, [0.5, 0.25, 0.25 + 5e-7]))  # sums to 1 within 1e-6
    assert near_one.status_code == 200
    again = _post(client, _body(built, [1, 0, 0])).json()
    assert again == answer  # the same mix, the same numbers


def test_the_sample_is_read_once_and_kept(make_client, built, store):
    counting = _Counting(store)
    client = make_client(start_worker=False, store=counting)
    assert _post(client, _body(built, [0.2, 0.3, 0.5])).status_code == 200
    first = counting.calls
    assert first >= 2  # the tensor and the catalog; the records may be in the scratch cache
    for weights in ([0.2, 0.3, 0.5], [0.6, 0.4, 0.0]):
        assert _post(client, _body(built, weights)).status_code == 200
    assert counting.calls == first  # nothing more was read


def test_only_the_most_recently_used_models_are_kept(store, built, api_env, monkeypatch):
    loads = []
    real = ranges_mod.range_model_from_store

    def loading(store_, key, **kwargs):
        loads.append(key)
        return real(store_, key, **kwargs)

    monkeypatch.setattr(ranges_mod, "range_model_from_store", loading)
    models = ranges_mod.RangeModels(store, kept=1)
    generation, uhash = built["generation"], built["universe"]["hash"]
    one = models.get(generation, uhash, "1y")
    assert models.get(generation, uhash, "1y") is one and len(loads) == 1
    store.put(tensor_key(generation, uhash, "2y"), store.get(tensor_key(generation, uhash, "1y")))
    models.get(generation, uhash, "2y")
    assert len(loads) == 2
    assert models.get(generation, uhash, "1y") is not one and len(loads) == 3  # read again
    assert ranges_mod.MODELS_KEPT == 8


@pytest.mark.parametrize(
    ("change", "where"),
    [
        ({"weights": [0.5, 0.5]}, "this menu has 3 funds; 2 weights were sent"),
        ({"weights": [0.5, 0.2, 0.2, 0.1]}, "this menu has 3 funds; 4 weights were sent"),
        ({"weights": [0.5, 0.3, 0.1]}, "the weights add up to 0.9; they must add up to 1"),
        ({"weights": [0.5, 0.3, 0.2 + 2e-6]}, "they must add up to 1"),
        ({"weights": [0.6, 0.6, -0.2]}, "weights.2"),
        ({"weights": [1.2, -0.1, -0.1]}, "weights.0"),
        ({"weights": [0.5, "0.3", 0.2]}, "weights.1"),
        ({"weights": [0.5, None, 0.5]}, "weights.1"),
        ({"weights": [1.0]}, "weights"),
        ({"weights": [1.0 / 31] * 31}, "weights"),
        ({"weights": "all"}, "weights"),
        ({"lookback": "4y"}, "lookback"),
        ({"hash": GOOD_HASH.upper()}, "hash"),
        ({"hash": GOOD_HASH[:-1]}, "hash"),
        ({"generation": "latest"}, "generation"),
        ({"extra": 1}, "extra"),
    ],
)
def test_invalid_requests_are_422_and_say_where(make_client, built, change, where):
    client = make_client(start_worker=False)
    response = _post(client, _body(built, **change))
    assert response.status_code == 422 and response.headers["cache-control"] == "no-store"
    error = response.json()["error"]
    assert error["code"] == "invalid_request"
    assert where in error["message"] or where in json.dumps(error["details"])


def test_shape_errors_never_reach_the_store(make_client, built, store):
    counting = _Counting(store)
    client = make_client(start_worker=False, store=counting)
    for change in ({"weights": [2.0, -1.0, 0.0]}, {"hash": "zz"}, {"lookback": "7y"}):
        assert _post(client, _body(built, **change)).status_code == 422
    missing = {key: value for key, value in _body(built, [1, 0, 0]).items() if key != "weights"}
    assert _post(client, missing).status_code == 422
    not_json = client.post("/v1/range", content=b"{", headers=headers())
    assert not_json.status_code == 422 and counting.calls == 0
    assert "0.5" not in _post(client, _body(built, [0.5, 0.3, 0.9])).text  # nothing echoed


def test_a_tensor_that_was_never_built_is_unknown(make_client, built):
    client = make_client(start_worker=False)
    for change in ({"hash": GOOD_HASH}, {"lookback": "5y"}, {"generation": "2020-01-02-0.2.0"}):
        response = _post(client, _body(built, **change))
        assert response.status_code == 404
        assert response.json()["error"] == {
            "code": "unknown_tensor",
            "message": "No tensor was built under this address.",
            "details": None,
        }


def test_a_tensor_whose_prices_are_gone_cannot_be_ranged(
    make_client, built, store, monkeypatch, tmp_path
):
    store.delete("prices/BND.parquet")
    monkeypatch.setenv("PS_CACHE_DIR", str(tmp_path / "empty-cache"))  # nothing kept from the build
    client = make_client(start_worker=False)
    response = _post(client, _body(built, [0.5, 0.3, 0.2]))
    assert response.status_code == 409 and response.json()["error"]["code"] == "range_unavailable"
    assert "BND" in response.json()["error"]["message"]


def test_a_mix_that_cannot_be_compounded_is_refused(make_client, built, monkeypatch):
    def ruined(model, weights):
        raise ValueError("a day that loses everything cannot be compounded")

    client = make_client(start_worker=False)
    monkeypatch.setattr(ranges_mod, "one_year_ranges", ruined)
    response = _post(client, _body(built, [0.5, 0.3, 0.2]))
    assert response.status_code == 409 and response.json()["error"]["code"] == "range_unavailable"


def test_range_requests_are_gated_limited_and_size_capped(make_client, built):
    client = make_client(start_worker=False)
    body = _body(built, [0.5, 0.3, 0.2])
    assert client.post("/v1/range", json=body).status_code == 403  # no gate secret
    ip = "198.51.100.7"
    codes = [_post(client, body, **{"CF-Connecting-IP": ip}).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429  # the per-IP limit of every route
    big = json.dumps({**body, "pad": "x" * 17_000}).encode()
    oversize = client.post("/v1/range", content=big, headers=headers())
    assert oversize.status_code == 413
    assert oversize.json()["error"]["code"] == "payload_too_large"


def test_scratch_cache_stays_under_its_cap(make_client, built, monkeypatch, tmp_path):
    monkeypatch.setenv("PS_CACHE_MAX_MB", "0.05")
    client = make_client(start_worker=False)
    assert _post(client, _body(built, [0.5, 0.3, 0.2])).status_code == 200
    cached = [path for path in (tmp_path / "cache").rglob("*") if path.is_file()]
    assert sum(path.stat().st_size for path in cached) <= 50_000
