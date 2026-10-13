"""LocalStore and R2Store behind one interface, and the verify command (spec 5.3, 9.5 step 1)."""

from __future__ import annotations

import io

import boto3
import numpy as np
import pandas as pd
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from portfoliosight.data import store as store_mod

BUCKET = "portfoliosight-data"


@pytest.fixture(params=["local", "r2"])
def store(request, tmp_path, monkeypatch):
    if request.param == "local":
        yield store_mod.LocalStore(tmp_path / "store")
        return
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield store_mod.R2Store(BUCKET, client)


def test_the_five_methods(store):
    assert store.list() == [] and store.exists("meta/a.json") is False
    with pytest.raises(KeyError):
        store.get("meta/a.json")
    store.put("meta/a.json", b"one")
    store.put("prices/VTI.parquet", b"two")
    store.put("prices/AGG.parquet", b"three")
    assert store.get("meta/a.json") == b"one" and store.exists("meta/a.json") is True
    store.put("meta/a.json", b"one again")
    assert store.get("meta/a.json") == b"one again"
    assert store.list() == ["meta/a.json", "prices/AGG.parquet", "prices/VTI.parquet"]
    assert store.list("prices/") == ["prices/AGG.parquet", "prices/VTI.parquet"]
    assert store.list("prices/V") == ["prices/VTI.parquet"]
    assert store.size("prices/AGG.parquet") == 5 and store.size("prices/NONE.parquet") is None
    store.delete("meta/a.json")
    store.delete("meta/a.json")  # deleting an absent key is not an error
    assert store.exists("meta/a.json") is False and "meta/a.json" not in store.list()
    assert isinstance(store, store_mod.Store)


@pytest.mark.parametrize("key", ["", "/abs", "a//b", "../escape", "a/../b", "a/./b"])
def test_bad_keys_are_refused(store, key):
    with pytest.raises(ValueError, match="invalid store key"):
        store.put(key, b"x")


def test_json_and_record_helpers(store):
    store_mod.put_json(store, "meta/x.json", {"b": 1, "a": [1, 2]})
    assert store_mod.get_json(store, "meta/x.json") == {"a": [1, 2], "b": 1}
    record = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-05", "2026-01-02", "2026-01-06"]),
            "close": [10.5, 10.0, 11.0],
            "tr_index": [1.05, 1.0, np.nan],
            "div_cash": [0.0, 0.0, np.nan],
            "split_factor": [1.0, 1.0, np.nan],
            "extra": ["dropped", "dropped", "dropped"],
        }
    )
    store_mod.put_record(store, "VTI", record)
    assert store.exists("prices/VTI.parquet")
    raw = pd.read_parquet(io.BytesIO(store.get("prices/VTI.parquet")))
    assert list(raw.columns) == ["date", "close", "tr_index", "div_cash", "split_factor"]
    assert str(raw["date"].dtype) == "datetime64[ns]"
    back = store_mod.get_record(store, "VTI")
    assert [str(d)[:10] for d in back["date"]] == ["2026-01-02", "2026-01-05", "2026-01-06"]
    np.testing.assert_array_equal(back["tr_index"].to_numpy(), [1.0, 1.05, np.nan])
    with pytest.raises(ValueError, match="tr_index"):
        store_mod.put_record(store, "BAD", record.drop(columns=["tr_index"]))


def test_local_put_is_atomic_and_hides_its_temp_files(tmp_path):
    store = store_mod.LocalStore(tmp_path / "s")
    store.put("meta/manifest.json", b"{}")
    assert store.list() == ["meta/manifest.json"]
    assert list((tmp_path / "s" / ".tmp").iterdir()) == []
    (tmp_path / "s" / ".tmp" / "leftover").write_bytes(b"half")
    assert store.list() == ["meta/manifest.json"]
    (tmp_path / "s" / "prices").mkdir()
    with pytest.raises(KeyError):
        store.get("prices")
    assert store_mod.LocalStore(tmp_path / "absent").list() == []


def test_r2_from_env(monkeypatch):
    for name in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_R2_ACCESS_KEY_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "secret")
    with pytest.raises(store_mod.StoreConfigError, match="CLOUDFLARE_ACCOUNT_ID"):
        store_mod.R2Store.from_env()
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "keyid")
    monkeypatch.delenv("PS_R2_BUCKET", raising=False)
    store = store_mod.R2Store.from_env()
    client = store._client
    assert store.bucket == BUCKET
    assert client.meta.endpoint_url == "https://acct123.r2.cloudflarestorage.com"
    assert client.meta.region_name == "auto"
    # three retries after the first attempt
    assert client.meta.config.retries == {"total_max_attempts": 4, "mode": "standard"}
    monkeypatch.setenv("PS_R2_BUCKET", "other-bucket")
    assert store_mod.R2Store.from_env().bucket == "other-bucket"


def test_store_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PS_STORE", "local")
    monkeypatch.delenv("PS_LOCAL_STORE_DIR", raising=False)
    with pytest.raises(store_mod.StoreConfigError, match="PS_LOCAL_STORE_DIR"):
        store_mod.store_from_env()
    monkeypatch.setenv("PS_LOCAL_STORE_DIR", str(tmp_path))
    local = store_mod.store_from_env()
    assert isinstance(local, store_mod.LocalStore) and local.root == tmp_path
    monkeypatch.setenv("PS_STORE", "tape")
    with pytest.raises(store_mod.StoreConfigError, match="'r2' or 'local'"):
        store_mod.store_from_env()
    monkeypatch.delenv("PS_STORE")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct123")
    monkeypatch.setenv("CLOUDFLARE_R2_ACCESS_KEY_ID", "keyid")
    monkeypatch.setenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "secret")
    assert isinstance(store_mod.store_from_env(), store_mod.R2Store)


def test_verify_reports_each_operation_and_leaves_no_probe(store):
    store.put("meta/_probe", b"planted")
    lines: list[str] = []
    assert store_mod.verify(store, emit=lines.append) == 0
    assert store.exists("meta/_probe") is False
    assert lines[1:6] == ["head_bucket ok", "put ok", "get ok", "delete ok", "list ok"]
    assert ("portfoliosight-data" in lines[0]) == isinstance(store, store_mod.R2Store)
    assert "passed" in lines[-1]


def _client_error(status: int, code: str) -> ClientError:
    response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
    return ClientError(response, "HeadBucket")  # type: ignore[arg-type]


class _FailingStore(store_mod.LocalStore):
    def __init__(self, root, fail_at: str, error: Exception):
        super().__init__(root)
        self.fail_at, self.error, self.bucket = fail_at, error, BUCKET

    def check(self):
        if self.fail_at == "head_bucket":
            raise self.error
        super().check()

    def get(self, key):
        if self.fail_at == "get":
            return b"something else"
        return super().get(key)

    def delete(self, key):
        if self.fail_at == "delete":
            return
        super().delete(key)

    def list(self, prefix=""):
        if self.fail_at == "list":
            return ["meta/_probe"]
        return super().list(prefix)


def test_verify_names_the_missing_scope_on_403(tmp_path):
    lines: list[str] = []
    failing = _FailingStore(tmp_path, "head_bucket", _client_error(403, "403"))
    assert store_mod.verify(failing, emit=lines.append) == 2
    assert lines[1] == "head_bucket failed: ClientError, code 403, HTTP 403"
    assert "Object Read & Write" in lines[2] and "portfoliosight-data only" in lines[2]
    assert "CLOUDFLARE_R2_ACCESS_KEY_ID" in lines[2] and len(lines) == 3


@pytest.mark.parametrize("fail_at", ["get", "delete", "list"])
def test_verify_fails_when_an_operation_does_not_do_its_job(tmp_path, fail_at):
    lines: list[str] = []
    failing = _FailingStore(tmp_path, fail_at, OSError())
    assert store_mod.verify(failing, emit=lines.append) == 2
    assert lines[-1].startswith(f"{fail_at} failed: OSError")
    assert not any("Object Read" in line for line in lines)
    if fail_at == "get":
        assert not (tmp_path / "meta" / "_probe").exists()


def test_main(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PS_STORE", "local")
    monkeypatch.setenv("PS_LOCAL_STORE_DIR", str(tmp_path / "s"))
    assert store_mod.main(["--verify"]) == 0
    out = capsys.readouterr().out
    for operation in ("head_bucket", "put", "get", "delete", "list"):
        assert f"{operation} ok" in out.splitlines()
    assert store_mod.main([]) == 64
    monkeypatch.delenv("PS_LOCAL_STORE_DIR")
    assert store_mod.main(["--verify"]) == 2
    assert "PS_LOCAL_STORE_DIR" in capsys.readouterr().err
