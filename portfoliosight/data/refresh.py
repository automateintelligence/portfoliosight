"""Which symbols a refresh fetches, and from when (spec 5.1, 5.4)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import Any

TAIL_OVERLAP = timedelta(days=7)
LAKE_SOURCE = "lake"  # kept current by the lake sync (spec 5.4), never by a provider


def as_date(value: Any) -> date | None:
    """An ISO string, ``date`` or ``datetime`` as a ``date``; ``None`` stays ``None``."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _field(entry: Any, name: str) -> Any:
    return entry.get(name) if isinstance(entry, Mapping) else getattr(entry, name, None)


def tail_start(adjusted_through: date) -> date:
    """A tail is fetched from a week before the last verified date, so the splice overlaps."""
    return adjusted_through - TAIL_OVERLAP


def is_current(entry: Any, d_g: date) -> bool:
    """True only when both prices and corporate actions reach ``d_g``."""
    last = as_date(_field(entry, "last_date"))
    adjusted = as_date(_field(entry, "adjusted_through"))
    return last is not None and adjusted is not None and last >= d_g and adjusted >= d_g


def plan_refresh(
    entries: Mapping[str, Any], symbols: Iterable[str], d_g: date
) -> list[tuple[str, date]]:
    """``(symbol, start)`` for every symbol whose tail must be fetched, in the given order.

    A symbol is left out only when ``last_date >= d_g`` and ``adjusted_through >= d_g``; a seed
    with recent prices but unverified corporate actions is always refetched from its adjustment
    date. Symbols without a stored record (no ``adjusted_through``) need a full fetch and are
    not part of a tail plan, and neither are those the lake sync keeps (``source: lake``).
    """
    plan: list[tuple[str, date]] = []
    for symbol in symbols:
        entry = entries.get(symbol)
        if entry is None or _field(entry, "source") == LAKE_SOURCE:
            continue
        adjusted = as_date(_field(entry, "adjusted_through"))
        if adjusted is None or is_current(entry, d_g):
            continue
        plan.append((symbol, tail_start(adjusted)))
    return plan
