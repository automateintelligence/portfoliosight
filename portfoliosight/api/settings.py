"""What the service reads from the environment, apart from the store and the cache.

The menu limit per access tier (engines spec 6.2) is ``PS_MENU_MAX_PUBLIC`` (default 30) and
``PS_MENU_MAX_ADMIN`` (default 100); the Worker holds the same two numbers as vars.

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
from portfoliosight.engine.surface import NY

GRID_NX_ENV = "PS_GRID_NX"
GRID_NY_ENV = "PS_GRID_NY"
GRID_LEVELS_ENV = "PS_GRID_LEVELS"
MIN_GATE_SECRET_LENGTH = 16
MENU_MAX_PUBLIC_ENV = "PS_MENU_MAX_PUBLIC"
MENU_MAX_ADMIN_ENV = "PS_MENU_MAX_ADMIN"
DEFAULT_MENU_MAX_PUBLIC = 30
DEFAULT_MENU_MAX_ADMIN = 100


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
