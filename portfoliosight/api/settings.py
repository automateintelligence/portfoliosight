"""What the service reads from the environment, apart from the store and the cache.

The menu limit per access tier (engines spec 6.2) is ``PS_MENU_MAX_PUBLIC`` (default 30) and
``PS_MENU_MAX_ADMIN`` (default 100); the Worker holds the same two numbers as vars.

The simulation engines a build computes (engines spec 7, "Precompute or on demand") are
``PS_ENGINES`` for the presets (default: every engine this engine version computes) and
``PS_ENGINES_CUSTOM`` for custom menus (default: ``PS_ENGINES`` without the copula).

The store comes from ``PS_STORE`` / ``PS_LOCAL_STORE_DIR`` / ``PS_R2_BUCKET``
(``portfoliosight.data.store.store_from_env``) and the scratch cache from ``PS_CACHE_DIR`` /
``PS_CACHE_MAX_MB`` (``portfoliosight.data.cache``); both modules read their own variables.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from portfoliosight.api.gate import GATE_SECRET_ENV, Tier
from portfoliosight.api.models import MIN_FUNDS
from portfoliosight.engine.ladder import LEVELS
from portfoliosight.engine.optimize import NX
from portfoliosight.engine.ranges import DEFAULT_ENGINE, ENGINES
from portfoliosight.engine.surface import NY

GRID_NX_ENV = "PS_GRID_NX"
GRID_NY_ENV = "PS_GRID_NY"
GRID_LEVELS_ENV = "PS_GRID_LEVELS"
MIN_GATE_SECRET_LENGTH = 16
MENU_MAX_PUBLIC_ENV = "PS_MENU_MAX_PUBLIC"
MENU_MAX_ADMIN_ENV = "PS_MENU_MAX_ADMIN"
DEFAULT_MENU_MAX_PUBLIC = 30
DEFAULT_MENU_MAX_ADMIN = 100
ENGINES_ENV = "PS_ENGINES"
ENGINES_CUSTOM_ENV = "PS_ENGINES_CUSTOM"
KNOWN_ENGINES: tuple[str, ...] = ENGINES  # what a build of this engine version can compute
PRESETS_ONLY_ENGINE = "copula"  # left out of custom menus unless PS_ENGINES_CUSTOM names it


class SettingsError(Exception):
    """The environment does not describe a service that can start."""


class GridSettings(BaseModel):
    """The tensor grid: 48 risk columns, 12 ladder levels a column and a 32-row raster.

    A host that cannot meet the build-time target of spec 4.12 sets fewer ladder levels.
    """

    model_config = ConfigDict(frozen=True)

    nx: int = Field(default=NX, ge=2)
    ny: int = Field(default=NY, ge=2)
    levels: int = Field(default=LEVELS, ge=1)

    @classmethod
    def from_env(cls) -> GridSettings:
        try:
            return cls(
                nx=int(os.environ.get(GRID_NX_ENV) or NX),
                ny=int(os.environ.get(GRID_NY_ENV) or NY),
                levels=int(os.environ.get(GRID_LEVELS_ENV) or LEVELS),
            )
        except ValueError as exc:
            raise SettingsError(
                f"{GRID_NX_ENV} and {GRID_NY_ENV} must be integers >= 2 "
                f"and {GRID_LEVELS_ENV} an integer >= 1"
            ) from exc


class EngineSettings(BaseModel):
    """The simulation engines a build computes: ``engines`` for presets, ``engines_custom`` for
    custom menus. History replay, the default engine, is in both; an engine a tensor does not
    carry is marked unavailable in it, with the reason, and nothing computes it on demand.
    """

    model_config = ConfigDict(frozen=True)

    engines: tuple[str, ...] = ENGINES
    engines_custom: tuple[str, ...] = ENGINES

    def for_menu(self, preset_id: str | None) -> tuple[str, ...]:
        """The engines of a preset's build (``preset_id`` set) or of a custom menu's."""
        return self.engines if preset_id is not None else self.engines_custom

    @classmethod
    def from_env(cls) -> EngineSettings:
        """Refuses an engine id this engine does not compute and a list without History replay.

        A variable that is unset or blank takes its default.
        """
        engines = _engine_list(ENGINES_ENV) or KNOWN_ENGINES
        custom = _engine_list(ENGINES_CUSTOM_ENV)
        if custom is None:
            custom = tuple(engine for engine in engines if engine != PRESETS_ONLY_ENGINE)
        return cls(engines=engines, engines_custom=custom)


def _engine_list(name: str) -> tuple[str, ...] | None:
    """``parse_engines`` of the variable ``name``; ``None`` when it is unset or blank."""
    raw = (os.environ.get(name) or "").strip()
    return parse_engines(raw, name) if raw else None


def parse_engines(raw: str, source: str) -> tuple[str, ...]:
    """The engines a comma-separated list names, once each, in ``KNOWN_ENGINES`` order.

    Raises ``SettingsError`` naming ``source`` for an id this engine does not compute and for a
    list without History replay.
    """
    named = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [engine for engine in named if engine not in KNOWN_ENGINES]
    if unknown:
        raise SettingsError(
            f"{source}: unknown engine {unknown[0]!r}; a build computes {', '.join(KNOWN_ENGINES)}"
        )
    if DEFAULT_ENGINE not in named:
        raise SettingsError(f"{source} must name {DEFAULT_ENGINE}: every build computes it")
    return tuple(engine for engine in KNOWN_ENGINES if engine in named)


class Settings(BaseModel):
    """The API's own settings."""

    model_config = ConfigDict(frozen=True)

    gate_secret: str = Field(repr=False)
    menu_max_public: int = DEFAULT_MENU_MAX_PUBLIC
    menu_max_admin: int = DEFAULT_MENU_MAX_ADMIN

    def menu_max(self, tier: Tier) -> int:
        """The most funds a menu may hold for a caller of ``tier``."""
        return self.menu_max_admin if tier == "admin" else self.menu_max_public

    @classmethod
    def from_env(cls) -> Settings:
        """Refuses to start without a gate secret: an empty one would admit every request.

        Also refuses menu limits that are not whole numbers with
        ``MIN_FUNDS <= public <= admin``.
        """
        secret = os.environ.get(GATE_SECRET_ENV, "")
        if len(secret) < MIN_GATE_SECRET_LENGTH:
            raise SettingsError(
                f"{GATE_SECRET_ENV} must be set to at least {MIN_GATE_SECRET_LENGTH} characters"
            )
        try:
            public = int(os.environ.get(MENU_MAX_PUBLIC_ENV) or DEFAULT_MENU_MAX_PUBLIC)
            admin = int(os.environ.get(MENU_MAX_ADMIN_ENV) or DEFAULT_MENU_MAX_ADMIN)
        except ValueError:
            public = admin = -1
        if not MIN_FUNDS <= public <= admin:
            raise SettingsError(
                f"{MENU_MAX_PUBLIC_ENV} and {MENU_MAX_ADMIN_ENV} must be whole numbers with "
                f"{MIN_FUNDS} <= {MENU_MAX_PUBLIC_ENV} <= {MENU_MAX_ADMIN_ENV}"
            )
        return cls(gate_secret=secret, menu_max_public=public, menu_max_admin=admin)
