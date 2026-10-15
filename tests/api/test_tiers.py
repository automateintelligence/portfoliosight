"""Menu size by access tier (engines spec 6.2): 30 funds for the public, 100 for an admin.

The tier comes only from ``x-ps-tier: admin``, and only on a request that also carries the
gate secret (the proof the request came through the Worker).
"""

from __future__ import annotations

import json

import pytest

from portfoliosight.api.gate import caller_tier
from portfoliosight.api.settings import Settings, SettingsError
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from tests.api.conftest import GATE, fresh_ip, headers

ADMIN = {"x-ps-tier": "admin"}


def _ids(n: int) -> list[str]:
    return [f"T{i:03d}" for i in range(n)]


@pytest.fixture
def wide_catalog(store):
    """The fixture catalog plus 101 synthetic symbols, so menus of any tested size are known."""
    manifest = store_mod.get_json(store, manifest_mod.MANIFEST_KEY)
    template = next(iter(manifest["symbols"].values()))
    for symbol in _ids(101):
        manifest["symbols"][symbol] = {**template, "name": symbol}
    store_mod.put_json(store, manifest_mod.MANIFEST_KEY, manifest)
    return store


@pytest.fixture
def paused(make_client, wide_catalog):
    built = []
    client = make_client(start_worker=False, build_fn=lambda *a, **k: built.append(a))
    yield client
    assert built == []


def _menu(n: int) -> dict:
    return {"funds": [{"id": symbol} for symbol in _ids(n)], "lookback": "5y"}


def _post_menu(client, n: int, **extra: str):
    return client.post("/v1/tensors", json=_menu(n), headers=headers(**extra))


def _post_range(client, n: int, **extra: str):
    body = {
        "generation": "2026-10-12-0.1.0",
        "hash": "0123456789abcdef",
        "lookback": "5y",
        "weights": [1.0 / n] * n,
    }
    return client.post("/v1/range", json=body, headers=headers(**extra))


def _is_count_refusal(response) -> bool:
    if response.status_code != 422:
        return False
    error = response.json()["error"]
    return error["code"] == "invalid_request" and "at most" in json.dumps(error)


# ---------------------------------------------------------------- the trust rule


def test_admin_only_with_the_gate_secret_and_the_exact_header():
    assert caller_tier(GATE, "admin", GATE) == "admin"
    assert caller_tier(None, "admin", GATE) == "public"
    assert caller_tier("", "admin", GATE) == "public"
    assert caller_tier(GATE[:-1], "admin", GATE) == "public"
    assert caller_tier("wrong-value", "admin", GATE) == "public"
    for value in (None, "", "ADMIN", "admin ", "public", "paid", "admin,admin"):
        assert caller_tier(GATE, value, GATE) == "public", value


def test_a_direct_request_with_the_tier_header_alone_is_refused(paused):
    response = paused.post(
        "/v1/tensors", json=_menu(31), headers={"CF-Connecting-IP": fresh_ip(), **ADMIN}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_the_tier_header_with_a_wrong_gate_value_is_refused(paused):
    for gate in ("wrong-value", GATE[:-1], GATE + "0"):
        response = paused.post(
            "/v1/tensors",
            json=_menu(31),
            headers={"x-ps-gate": gate, "CF-Connecting-IP": fresh_ip(), **ADMIN},
        )
        assert response.status_code == 403, gate


# ---------------------------------------------------------------- settings


def test_menu_limits_default_to_30_and_100(api_env):
    settings = Settings.from_env()
    assert (settings.menu_max_public, settings.menu_max_admin) == (30, 100)
    assert settings.menu_max("public") == 30 and settings.menu_max("admin") == 100


def test_menu_limits_come_from_the_environment(api_env, monkeypatch):
    monkeypatch.setenv("PS_MENU_MAX_PUBLIC", "12")
    monkeypatch.setenv("PS_MENU_MAX_ADMIN", "50")
    settings = Settings.from_env()
    assert settings.menu_max("public") == 12 and settings.menu_max("admin") == 50


@pytest.mark.parametrize(
    ("public", "admin"),
    [("31", "30"), ("1", "100"), ("thirty", "100"), ("30", "1e2"), ("-5", "100")],
)
def test_menu_limits_that_cannot_hold_refuse_to_start(api_env, monkeypatch, public, admin):
    monkeypatch.setenv("PS_MENU_MAX_PUBLIC", public)
    monkeypatch.setenv("PS_MENU_MAX_ADMIN", admin)
    with pytest.raises(SettingsError, match="PS_MENU_MAX_PUBLIC"):
        Settings.from_env()


# ---------------------------------------------------------------- POST /v1/tensors


def test_public_menu_holds_30_funds_and_refuses_the_31st(paused):
    assert _post_menu(paused, 30).status_code == 202
    refused = _post_menu(paused, 31)
    assert _is_count_refusal(refused), refused.text
    assert "30" in json.dumps(refused.json()["error"])


def test_admin_menu_accepts_31_and_100_funds_and_refuses_the_101st(paused):
    assert _post_menu(paused, 31, **ADMIN).status_code == 202
    assert _post_menu(paused, 100, **ADMIN).status_code == 202
    refused = _post_menu(paused, 101, **ADMIN)
    assert _is_count_refusal(refused), refused.text
    assert "100" in json.dumps(refused.json()["error"])


def test_an_unrecognized_tier_value_gets_the_public_limit(paused):
    for value in ("ADMIN", "paid", "admin "):
        assert _is_count_refusal(_post_menu(paused, 31, **{"x-ps-tier": value})), value


def test_the_minimum_stays_two_for_every_tier(paused):
    for extra in ({}, ADMIN):
        response = _post_menu(paused, 1, **extra)
        assert response.status_code == 422, response.text


def test_the_tier_limits_follow_the_settings(make_client, wide_catalog, monkeypatch):
    monkeypatch.setenv("PS_MENU_MAX_PUBLIC", "3")
    monkeypatch.setenv("PS_MENU_MAX_ADMIN", "4")
    client = make_client(start_worker=False, build_fn=lambda *a, **k: None)
    assert _post_menu(client, 3).status_code == 202
    assert _is_count_refusal(_post_menu(client, 4))
    assert _post_menu(client, 4, **ADMIN).status_code == 202
    assert _is_count_refusal(_post_menu(client, 5, **ADMIN))


# ---------------------------------------------------------------- POST /v1/range


def test_range_weights_follow_the_callers_limit(paused):
    # The count is checked before the store is read: past it, an unknown tensor is a 404.
    assert _post_range(paused, 30).status_code == 404
    assert _is_count_refusal(_post_range(paused, 31))
    assert _post_range(paused, 31, **ADMIN).status_code == 404
    assert _post_range(paused, 100, **ADMIN).status_code == 404
    assert _is_count_refusal(_post_range(paused, 101, **ADMIN))


def test_a_parser_without_the_callers_limit_is_a_programming_error():
    from portfoliosight.api.models import TensorRequest

    with pytest.raises(RuntimeError, match="max_funds"):
        TensorRequest.model_validate_json(json.dumps(_menu(2)))
