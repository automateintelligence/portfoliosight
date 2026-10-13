"""The universe hash (spec 6): canonical over the requested policy, blind to order and lookback."""

from __future__ import annotations

import hashlib
import inspect
import json
import re

from portfoliosight.api.hashing import universe_hash
from portfoliosight.engine import tensor as engine_tensor


def _fund(fund_id: str, low=None, high=None) -> dict:
    return {"id": fund_id, "min": low, "max": high}


def test_hash_is_sixteen_hex_of_sha256_over_the_canonical_json(monkeypatch):
    fed: list[bytes] = []
    real = hashlib.sha256

    def recording(data: bytes = b""):
        fed.append(bytes(data))
        return real(data)

    monkeypatch.setattr(hashlib, "sha256", recording)
    funds = [_fund("VTI"), _fund("BND", high=0.1), _fund("AGG", low=0.05)]
    value = universe_hash(funds)
    assert re.fullmatch(r"[0-9a-f]{16}", value)
    canonical = (
        '{"funds":[{"id":"AGG","max":null,"min":0.05},{"id":"BND","max":0.1,"min":null},'
        '{"id":"VTI","max":null,"min":null}],"schema":2}'
    )
    assert fed == [canonical.encode()]
    assert value == real(canonical.encode()).hexdigest()[:16]
    assert json.loads(canonical)["schema"] == 2


def test_order_does_not_matter_and_any_cap_does():
    funds = [_fund("VTI"), _fund("BND"), _fund("AGG")]
    base = universe_hash(funds)
    assert universe_hash(list(reversed(funds))) == base
    assert universe_hash([{"max": None, "id": f["id"], "min": None} for f in funds]) == base
    assert universe_hash([_fund("VTI", high=0.1), *funds[1:]]) != base
    assert universe_hash([_fund("VTI", low=0.1), *funds[1:]]) != base
    assert universe_hash([_fund("VTI", low=0.1), *funds[1:]]) != universe_hash(
        [_fund("VTI", high=0.1), *funds[1:]]
    )


def test_the_function_cannot_see_a_lookback_and_matches_the_engine():
    assert list(inspect.signature(universe_hash).parameters) == ["funds"]
    funds = [_fund("TSP-G"), _fund("TSP-C", 0.1, 0.9)]
    assert universe_hash(funds) == engine_tensor.universe_hash(funds)
