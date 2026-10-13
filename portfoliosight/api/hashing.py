"""The universe hash of spec 6.

``sha256(canonical_json({"schema": 2, "funds": [{"id", "min", "max"} sorted by id]}))[:16]`` over
the requested policy, ``None`` standing for a default bound. The engine stamps the same value
into every tensor, so the two cannot drift: this is the engine's function.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from portfoliosight.engine import tensor as engine_tensor


def universe_hash(funds: Sequence[Mapping[str, object]]) -> str:
    """16 lowercase hex digits for a menu and its requested caps, whatever the order."""
    return engine_tensor.universe_hash(funds)
