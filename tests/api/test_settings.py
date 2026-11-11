"""Which simulation engines a build computes (engines spec 7, "Precompute or on demand")."""

from __future__ import annotations

import pytest

from portfoliosight.api import settings as settings_mod
from portfoliosight.api.settings import EngineSettings, SettingsError


@pytest.fixture
def no_engine_env(monkeypatch):
    monkeypatch.delenv("PS_ENGINES", raising=False)
    monkeypatch.delenv("PS_ENGINES_CUSTOM", raising=False)
    return monkeypatch


def test_presets_and_custom_menus_compute_both_engines_by_default(no_engine_env):
    settings = EngineSettings.from_env()
    assert settings.engines == ("replay", "garch")
    assert settings.engines_custom == ("replay", "garch")
    assert settings.for_menu("guide2017") == ("replay", "garch")
    assert settings.for_menu(None) == ("replay", "garch")


def test_custom_menus_follow_ps_engines_unless_told_otherwise(no_engine_env):
    no_engine_env.setenv("PS_ENGINES", "replay")
    assert EngineSettings.from_env().engines_custom == ("replay",)
    no_engine_env.setenv("PS_ENGINES", "replay,garch")
    no_engine_env.setenv("PS_ENGINES_CUSTOM", "replay")
    settings = EngineSettings.from_env()
    assert settings.engines == ("replay", "garch") and settings.engines_custom == ("replay",)
    assert settings.for_menu("tsp") == ("replay", "garch")
    assert settings.for_menu(None) == ("replay",)


def test_the_custom_default_leaves_the_copula_out(no_engine_env):
    """The copula is measured on presets first (decision 4): custom menus get it only by name."""
    no_engine_env.setattr(settings_mod, "KNOWN_ENGINES", ("replay", "garch", "copula"))
    no_engine_env.setenv("PS_ENGINES", "replay,garch,copula")
    settings = EngineSettings.from_env()
    assert settings.engines == ("replay", "garch", "copula")
    assert settings.engines_custom == ("replay", "garch")
    no_engine_env.setenv("PS_ENGINES_CUSTOM", "replay,copula")
    assert EngineSettings.from_env().engines_custom == ("replay", "copula")


def test_lists_are_read_in_the_engines_own_order_once_each(no_engine_env):
    no_engine_env.setenv("PS_ENGINES", " garch , replay,garch, ")
    assert EngineSettings.from_env().engines == ("replay", "garch")
    no_engine_env.setenv("PS_ENGINES", "  ")
    assert EngineSettings.from_env().engines == ("replay", "garch")


@pytest.mark.parametrize("name", ["PS_ENGINES", "PS_ENGINES_CUSTOM"])
@pytest.mark.parametrize(
    ("value", "says"),
    [
        ("replay,copula", "unknown engine 'copula'"),
        ("replay,GARCH", "unknown engine 'GARCH'"),
        ("garch", "replay"),
        (",", "replay"),
    ],
)
def test_an_unknown_engine_or_a_list_without_replay_is_refused(no_engine_env, name, value, says):
    no_engine_env.setenv(name, value)
    with pytest.raises(SettingsError, match=name) as caught:
        EngineSettings.from_env()
    assert says in str(caught.value)
