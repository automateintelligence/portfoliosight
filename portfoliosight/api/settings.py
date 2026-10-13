"""What the service reads from the environment, apart from the store and the cache.

The store comes from ``PS_STORE`` / ``PS_LOCAL_STORE_DIR`` / ``PS_R2_BUCKET``
(``portfoliosight.data.store.store_from_env``) and the scratch cache from ``PS_CACHE_DIR`` /
``PS_CACHE_MAX_MB`` (``portfoliosight.data.cache``); both modules read their own variables.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from portfoliosight.engine.optimize import NX
from portfoliosight.engine.surface import NY

GATE_SECRET_ENV = "PS_GATE_SECRET"
GRID_NX_ENV = "PS_GRID_NX"
GRID_NY_ENV = "PS_GRID_NY"
MIN_GATE_SECRET_LENGTH = 16


class SettingsError(Exception):
    """The environment does not describe a service that can start."""


class GridSettings(BaseModel):
    """The tensor grid: 48 x 32, or the one fallback of spec 4.12 (32 x 24) set on the host."""

    model_config = ConfigDict(frozen=True)

    nx: int = Field(default=NX, ge=2)
    ny: int = Field(default=NY, ge=2)

    @classmethod
    def from_env(cls) -> GridSettings:
        try:
            return cls(
                nx=int(os.environ.get(GRID_NX_ENV) or NX),
                ny=int(os.environ.get(GRID_NY_ENV) or NY),
            )
        except ValueError as exc:
            raise SettingsError(f"{GRID_NX_ENV} and {GRID_NY_ENV} must be integers >= 2") from exc


class Settings(BaseModel):
    """The API's own settings."""

    model_config = ConfigDict(frozen=True)

    gate_secret: str = Field(repr=False)

    @classmethod
    def from_env(cls) -> Settings:
        """Refuses to start without a gate secret: an empty one would admit every request."""
        secret = os.environ.get(GATE_SECRET_ENV, "")
        if len(secret) < MIN_GATE_SECRET_LENGTH:
            raise SettingsError(
                f"{GATE_SECRET_ENV} must be set to at least {MIN_GATE_SECRET_LENGTH} characters"
            )
        return cls(gate_secret=secret)
