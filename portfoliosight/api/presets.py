"""The two ready-made menus and the body of ``GET /v1/presets`` (spec 6, Appendix A)."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from portfoliosight.api.hashing import universe_hash
from portfoliosight.data import manifest as manifest_mod
from portfoliosight.data import store as store_mod
from portfoliosight.data.universe import TSP_FUNDS, Preset, load_presets
from portfoliosight.engine.windows import LOOKBACK_ROWS

LOOKBACKS: tuple[str, ...] = tuple(LOOKBACK_ROWS)
_SHAPE16 = re.compile(r"[0-9a-f]{16}")


def tensor_key(generation: str, uhash: str, lookback: str) -> str:
    """The store key of one tensor (spec 5.3)."""
    return f"tensors/{generation}/{uhash}/{lookback}.json"


def model_key(generation: str, shape16: str, name: str) -> str:
    """The store key of one model file of a generation (engines spec 7).

    ``shape16`` is the first 16 hex digits of the shape panel's digest, which names the fund set
    and its history; ``name`` is the file, e.g. ``garch.json`` or ``pool.npy``.
    """
    if not _SHAPE16.fullmatch(shape16):
        raise ValueError(f"a shape digest prefix is 16 hex digits, not {shape16!r}")
    return f"models/{generation}/{shape16}/{name}"


def tensor_url(generation: str, uhash: str, lookback: str) -> str:
    """The public path of one tensor: the page reaches the service as same-origin ``/api``."""
    return f"/api/tensors/{generation}/{uhash}/{lookback}"


def preset_definitions() -> list[Preset]:
    """The presets of ``data/presets.json``; a dollar allocation is rounded to cents."""
    presets = []
    for preset in load_presets():
        allocation = preset.allocation
        if allocation is not None:
            allocation = {fund: round(amount, 2) for fund, amount in allocation.items()}
        presets.append(replace(preset, allocation=allocation))
    return presets


def preset_funds(preset: Preset) -> list[dict[str, Any]]:
    """A preset's requested policy: every fund at the default caps."""
    return [{"id": fund, "min": None, "max": None} for fund in preset.funds]


def presets_body(generation: str, asof: str, store: store_mod.Store) -> dict[str, Any]:
    """The body of ``GET /v1/presets`` for ``generation``, as the store stands now."""
    catalog = manifest_mod.load_manifest(store).symbols
    presets = []
    for preset in preset_definitions():
        uhash = universe_hash(preset_funds(preset))
        lookbacks = {}
        for lookback in LOOKBACKS:
            ready = store.exists(tensor_key(generation, uhash, lookback))
            lookbacks[lookback] = {
                "status": "ready" if ready else "unavailable",
                "url": tensor_url(generation, uhash, lookback) if ready else None,
            }
        presets.append(
            {
                "id": preset.id,
                "name": preset.name,
                "hash": uhash,
                "funds": [
                    {
                        "id": fund,
                        "name": catalog[fund].name
                        if fund in catalog
                        else TSP_FUNDS.get(fund, fund),
                    }
                    for fund in preset.funds
                ],
                "allocation": preset.allocation,
                "allocation_unit": preset.allocation_unit,
                "lookbacks": lookbacks,
            }
        )
    return {"generation": generation, "asof": asof, "presets": presets}
