"""One-year ranges for a mix on a built menu (spec 6, ``POST /v1/range``).

A range model holds a menu's lookback sample, which is read back from the price records the
first time a tensor is asked about. The few most recently used models are kept in memory, so a
later request for the same tensor costs one matrix product.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Sequence

import numpy as np

from portfoliosight.api.errors import ApiError, invalid_request
from portfoliosight.api.presets import tensor_key
from portfoliosight.data import cache as cache_mod
from portfoliosight.data import store as store_mod
from portfoliosight.engine.ranges import RangeModel, one_year_ranges
from portfoliosight.jobs.build import RangeUnavailable, range_model_from_store

MODELS_KEPT = 8
WEIGHT_SUM_TOL = 1e-6

Key = tuple[str, str, str]


class RangeModels:
    """The range models of stored tensors, the ``kept`` most recently used held in memory."""

    def __init__(self, store: store_mod.Store, kept: int = MODELS_KEPT):
        self._store = store
        self._kept = kept
        self._models: OrderedDict[Key, RangeModel] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, generation: str, uhash: str, lookback: str) -> RangeModel:
        """The model of one tensor; ``KeyError`` when the store has no such tensor.

        One request at a time loads: a second one for the same tensor then finds it here.
        """
        key = (generation, uhash, lookback)
        with self._lock:
            model = self._models.get(key)
            if model is None:
                cache_dir = cache_mod.cache_dir_from_env()
                try:
                    model = range_model_from_store(
                        self._store, tensor_key(*key), cache_dir=cache_dir
                    )
                finally:
                    cache_mod.evict(cache_dir=cache_dir)
                self._models[key] = model
            self._models.move_to_end(key)
            while len(self._models) > self._kept:
                self._models.popitem(last=False)
            return model


def range_body(models: RangeModels, key: Key, weights: Sequence[float]) -> dict:
    """The body of ``POST /v1/range`` for ``weights`` on the tensor ``key``.

    Refusals: 404 ``unknown_tensor`` when no tensor is stored under the key, 409
    ``range_unavailable`` when its sample cannot be rebuilt or the mix cannot be compounded,
    422 ``invalid_request`` when the weights are not one per fund of the menu or do not add up
    to 1.
    """
    try:
        model = models.get(*key)
    except KeyError:
        raise ApiError(404, "unknown_tensor", "No tensor was built under this address.") from None
    except RangeUnavailable as exc:
        raise ApiError(409, "range_unavailable", str(exc)) from None
    funds = len(model.mu_s)
    if len(weights) != funds:
        raise invalid_request(f"this menu has {funds} funds; {len(weights)} weights were sent")
    mix = np.asarray(weights, dtype=float)
    if abs(float(mix.sum()) - 1.0) > WEIGHT_SUM_TOL:
        raise invalid_request(
            f"the weights add up to {float(mix.sum()):.6g}; they must add up to 1"
        )
    try:
        ranges = one_year_ranges(model, mix)
    except ValueError as exc:
        raise ApiError(409, "range_unavailable", str(exc)) from None
    return {
        "bad": float(ranges["bad"][0]),
        "typical": float(ranges["typical"][0]),
        "good": float(ranges["good"][0]),
        "normal": {name: float(values[0]) for name, values in ranges["normal"].items()},
    }
