"""The measured provider plan ``meta/provider_limits.json`` and the probe that writes it (5.2)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from portfoliosight.data import store as store_mod
from portfoliosight.data.budget import BudgetLedger, BudgetSpent, Limits
from portfoliosight.data.providers.base import RateLimited

logger = logging.getLogger(__name__)

LIMITS_KEY = "meta/provider_limits.json"
STARTER = Limits(req_per_hour=45, req_per_day=900, unique_symbols_per_month=450)
POWER = Limits(req_per_hour=9_000, req_per_day=90_000, unique_symbols_per_month=100_000)
ENV_FALLBACKS = {
    "req_per_hour": "PS_PROVIDER_REQ_PER_HOUR",
    "req_per_day": "PS_PROVIDER_REQ_PER_DAY",
    "unique_symbols_per_month": "PS_PROVIDER_SYMBOLS_PER_MONTH",
}
TIER_STARTER = "starter"
TIER_POWER = "power"
TIER_UNCAPPED_PROBE = "at least 60/10 min"


class ProviderLimits(BaseModel):
    """Exactly the seven keys of the limits file."""

    provider: str = "tiingo"
    tier: str
    req_per_hour: int
    req_per_day: int
    unique_symbols_per_month: int
    measured_on: str
    method: Literal["probe", "documented"]


def _recorded(store: store_mod.Store) -> dict[str, Any]:
    try:
        doc = store_mod.get_json(store, LIMITS_KEY)
    except KeyError:
        return {}
    return doc if isinstance(doc, dict) else {}


def load_limits(store: store_mod.Store) -> Limits:
    """The limits in force: the file's keys win, else the environment, else 45/900/450."""
    recorded = _recorded(store)
    values: dict[str, int] = {}
    for key, env_name in ENV_FALLBACKS.items():
        if key in recorded:
            values[key] = int(recorded[key])
        elif os.environ.get(env_name):
            values[key] = int(os.environ[env_name])
        else:
            values[key] = int(getattr(STARTER, key))
    return Limits(**values)


def plan_tier(store: store_mod.Store) -> Literal["starter", "power"]:
    """``power`` only when the limits file says so; anything else keeps the Starter slice."""
    tier = str(_recorded(store).get("tier", "")).lower()
    return "power" if tier == TIER_POWER else "starter"


def measure_limits(
    *,
    store: store_mod.Store,
    ledger: BudgetLedger,
    provider: Any,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None],
    symbol: str,
    account: bool = True,
    max_requests: int = 60,
    window_seconds: float = 600,
    pause_seconds: float = 2.0,
) -> ProviderLimits | None:
    """Issue up to 60 meta requests for one symbol within ten minutes and record the plan.

    A 429 before the 60th request records Starter (45/900/450). No 429 records the tier
    "at least 60/10 min" with the same conservative limits: Power is only ever recorded with the
    owner's confirmation. ``provider`` must raise ``RateLimited`` on the first 429. ``account``
    is False when the provider already calls ``ledger.before_request`` itself. Returns ``None``
    (and writes nothing) when a budget stops the probe before it can conclude.
    """
    rate_limited = False
    made = 0
    with ledger.probe(max_requests=max_requests, window_seconds=window_seconds):
        for attempt in range(max_requests):
            try:
                if account:
                    ledger.before_request(symbol)
                provider.fetch_meta(symbol)
            except RateLimited:
                made += 1
                rate_limited = True
                break
            except BudgetSpent as spent:
                logger.warning("limits probe stopped: %s budget spent", spent.scope)
                return None
            made += 1
            if attempt + 1 < max_requests:
                sleep(pause_seconds)
    tier = TIER_STARTER if rate_limited else TIER_UNCAPPED_PROBE
    limits = ProviderLimits(
        tier=tier,
        req_per_hour=STARTER.req_per_hour,
        req_per_day=STARTER.req_per_day,
        unique_symbols_per_month=STARTER.unique_symbols_per_month,
        measured_on=clock().astimezone(UTC).date().isoformat(),
        method="probe",
    )
    store_mod.put_json(store, LIMITS_KEY, limits.model_dump())
    logger.info("limits probe: %d request(s), tier %s", made, tier)
    return limits
