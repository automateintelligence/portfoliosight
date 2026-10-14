"""The R2 verify against the real bucket (spec 9.5 step 1). Needs the env file and the network."""

from __future__ import annotations

import pytest

from portfoliosight.data import store as store_mod


@pytest.mark.live
def test_r2_verify(monkeypatch):
    monkeypatch.setenv("PS_STORE", "r2")
    lines: list[str] = []
    store = store_mod.store_from_env()
    assert isinstance(store, store_mod.R2Store) and store.bucket == "portfoliosight-data"
    assert store_mod.verify(store, emit=lines.append) == 0, lines
    assert lines[1:6] == ["head_bucket ok", "put ok", "get ok", "delete ok", "list ok"]
    assert store.exists(store_mod.PROBE_KEY) is False
