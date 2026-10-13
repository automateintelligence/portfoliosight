"""The gate: nothing is served without the secret, and the comparison is constant-time."""

from __future__ import annotations

import hmac

import pytest

from portfoliosight.api import settings as settings_mod
from portfoliosight.api.app import create_app
from portfoliosight.api.gate import gate_open
from portfoliosight.api.settings import Settings, SettingsError
from tests.api.conftest import GATE, fresh_ip, headers


def test_gate_open_only_for_the_exact_secret():
    assert gate_open(GATE, GATE)
    for presented in (None, "", GATE[:-1], GATE + "0", GATE.upper(), "é" + GATE[1:]):
        assert not gate_open(presented, GATE)


def test_health_refuses_without_the_secret_and_answers_with_it(make_client, monkeypatch):
    calls = []
    real = hmac.compare_digest

    def counting(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", counting)
    client = make_client(start_worker=False)
    for sent in (None, "wrong-value", GATE[:-1], GATE + "x"):
        before = len(calls)
        request_headers = {"CF-Connecting-IP": fresh_ip()}
        if sent is not None:
            request_headers["x-ps-gate"] = sent
        response = client.get("/v1/health", headers=request_headers)
        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "forbidden" and error["details"] is None
        assert isinstance(error["message"], str)
        assert GATE not in response.text and (not sent or sent not in response.text)
        assert response.headers["cache-control"] == "no-store"
        assert len(calls) > before
    before = len(calls)
    response = client.get("/v1/health", headers=headers())
    assert response.status_code == 200 and len(calls) > before
    assert response.json()["status"] == "ok"


def test_unknown_paths_are_refused_before_they_are_looked_up(make_client):
    client = make_client(start_worker=False)
    assert client.get("/v1/nothing", headers={"CF-Connecting-IP": fresh_ip()}).status_code == 403
    assert client.get("/docs", headers={"CF-Connecting-IP": fresh_ip()}).status_code == 403
    missing = client.get("/v1/nothing", headers=headers())
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path, headers=headers()).status_code == 404


@pytest.mark.parametrize("value", [None, "", "short"])
def test_the_service_does_not_start_without_a_gate_secret(monkeypatch, store, value):
    if value is None:
        monkeypatch.delenv("PS_GATE_SECRET", raising=False)
    else:
        monkeypatch.setenv("PS_GATE_SECRET", value)
    with pytest.raises(SettingsError):
        create_app(store=store, start_worker=False)


def test_settings_never_show_the_secret(monkeypatch):
    monkeypatch.setenv("PS_GATE_SECRET", GATE)
    settings = Settings.from_env()
    assert settings.gate_secret == GATE and GATE not in repr(settings)


def test_grid_settings(monkeypatch):
    monkeypatch.delenv("PS_GRID_NX", raising=False)
    monkeypatch.delenv("PS_GRID_NY", raising=False)
    assert settings_mod.GridSettings.from_env().model_dump() == {"nx": 48, "ny": 32}
    monkeypatch.setenv("PS_GRID_NX", "32")
    monkeypatch.setenv("PS_GRID_NY", "24")
    assert settings_mod.GridSettings.from_env().model_dump() == {"nx": 32, "ny": 24}
    monkeypatch.setenv("PS_GRID_NX", "many")
    with pytest.raises(SettingsError):
        settings_mod.GridSettings.from_env()
    monkeypatch.setenv("PS_GRID_NX", "1")
    with pytest.raises(SettingsError):
        settings_mod.GridSettings.from_env()
