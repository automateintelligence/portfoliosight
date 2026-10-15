"""The canonical store (spec 5.3): Cloudflare R2, or a local directory with the same interface.

This module is the only code that touches R2 (and the only one that imports ``boto3``).

    python -m portfoliosight.data.store --verify
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import logging
import os
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import boto3
import pandas as pd
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from portfoliosight.data.secrets import install_redaction

DEFAULT_BUCKET = "portfoliosight-data"
PROBE_KEY = "meta/_probe"
RECORD_COLUMNS = ("date", "close", "tr_index", "div_cash", "split_factor")
SCOPE_HINT = (
    "403 from R2: the R2 keys are scoped to other buckets. Create a new R2 API token "
    "(R2 > Manage R2 API Tokens > Object Read & Write, bucket {bucket} only) and replace "
    "CLOUDFLARE_R2_ACCESS_KEY_ID and CLOUDFLARE_R2_SECRET_ACCESS_KEY."
)
_MISSING_CODES = {"404", "NoSuchKey", "NotFound"}
_CONDITION_CODES = {"PreconditionFailed", "ConditionalRequestConflict"}
_CLIENT_LOGGERS = ("boto3", "botocore", "s3transfer", "urllib3")


@runtime_checkable
class Store(Protocol):
    def get(self, key: str) -> bytes: ...
    def put(self, key: str, data: bytes) -> None: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str = "") -> list[str]: ...
    def delete(self, key: str) -> None: ...


class StoreConfigError(Exception):
    """The environment does not describe a usable store."""


class ConcurrentUpdate(Exception):
    """A conditional read-modify-write kept losing to other writers of the same key."""


def _check_key(key: str) -> str:
    parts = key.split("/")
    if not key or key.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"invalid store key {key!r}")
    return key


class LocalStore:
    """A directory with the store interface; keys are relative POSIX paths."""

    _TMP_DIR = ".tmp"

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)

    def describe(self) -> str:
        return f"local store {self.root}"

    def check(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*_check_key(key).split("/"))

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            raise KeyError(key) from None

    def put(self, key: str, data: bytes) -> None:
        """Write through a temporary file and a rename, so a reader never sees half a file."""
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = self.root / self._TMP_DIR
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp = tmp_dir / uuid.uuid4().hex
        tmp.write_bytes(data)
        os.replace(tmp, target)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int | None:
        path = self._path(key)
        return path.stat().st_size if path.is_file() else None

    def list(self, prefix: str = "") -> list[str]:
        if not self.root.is_dir():
            return []
        keys = []
        for path in self.root.rglob("*"):
            relative = path.relative_to(self.root)
            if not path.is_file() or relative.parts[0] == self._TMP_DIR:
                continue
            key = relative.as_posix()
            if key.startswith(prefix):
                keys.append(key)
        return sorted(keys)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        tmp_dir = self.root / self._TMP_DIR
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with (tmp_dir / ".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def get_tagged(self, key: str) -> tuple[bytes, str]:
        """The value and its tag (a content digest); ``KeyError`` when absent."""
        data = self.get(key)
        return data, hashlib.sha256(data).hexdigest()

    def put_if(self, key: str, data: bytes, tag: str | None) -> bool:
        """Write only when the key still holds the value tagged ``tag`` (``None``: absent)."""
        with self._locked():
            try:
                _, current = self.get_tagged(key)
            except KeyError:
                current = None
            if current != tag:
                return False
            self.put(key, data)
            return True


class R2Store:
    """The R2 bucket through the S3-compatible API, with botocore's standard retries."""

    def __init__(self, bucket: str, client: Any):
        self.bucket = bucket
        self._client = client

    @classmethod
    def from_env(cls) -> R2Store:
        names = (
            "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_R2_ACCESS_KEY_ID",
            "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
        )
        unset = [name for name in names if not os.environ.get(name)]
        if unset:
            raise StoreConfigError(f"environment variable(s) not set: {', '.join(unset)}")
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ[names[0]]}.r2.cloudflarestorage.com",
            region_name="auto",
            aws_access_key_id=os.environ[names[1]],
            aws_secret_access_key=os.environ[names[2]],
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=15,
                read_timeout=60,
            ),
        )
        _redact_client_logs([os.environ[names[1]], os.environ[names[2]]])
        return cls(os.environ.get("PS_R2_BUCKET") or DEFAULT_BUCKET, client)

    def describe(self) -> str:
        return f"R2 bucket {self.bucket}"

    def check(self) -> None:
        self._client.head_bucket(Bucket=self.bucket)

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=_check_key(key))
        except ClientError as exc:
            if _error_code(exc) in _MISSING_CODES:
                raise KeyError(key) from None
            raise
        return response["Body"].read()

    def put(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self.bucket, Key=_check_key(key), Body=data)

    def size(self, key: str) -> int | None:
        try:
            head = self._client.head_object(Bucket=self.bucket, Key=_check_key(key))
        except ClientError as exc:
            if _error_code(exc) in _MISSING_CODES:
                return None
            raise
        return int(head["ContentLength"])

    def exists(self, key: str) -> bool:
        return self.size(key) is not None

    def list(self, prefix: str = "") -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=_check_key(key))

    def get_tagged(self, key: str) -> tuple[bytes, str]:
        """The value and its ETag; ``KeyError`` when absent."""
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=_check_key(key))
        except ClientError as exc:
            if _error_code(exc) in _MISSING_CODES:
                raise KeyError(key) from None
            raise
        return response["Body"].read(), str(response["ETag"])

    def put_if(self, key: str, data: bytes, tag: str | None) -> bool:
        """A conditional PUT: ``If-Match: tag``, or ``If-None-Match: *`` when ``tag`` is None.

        False when R2 refuses it because the object changed (412) or another conditional write
        to it is in flight (409).
        """
        condition = {"IfMatch": tag} if tag is not None else {"IfNoneMatch": "*"}
        try:
            self._client.put_object(Bucket=self.bucket, Key=_check_key(key), Body=data, **condition)
        except ClientError as exc:
            if _error_code(exc) in _CONDITION_CODES or _http_status(exc) in (409, 412):
                return False
            raise
        return True


def _redact_client_logs(values: list[str]) -> None:
    """Keep the R2 keys out of the S3 client's own log lines.

    At DEBUG level botocore logs the signed request, whose Authorization header carries the
    access key id. A logger's filter only sees that logger's records, so every client logger
    that exists gets one.
    """
    names = [
        name for name in logging.root.manager.loggerDict if name.split(".")[0] in _CLIENT_LOGGERS
    ]
    install_redaction([*_CLIENT_LOGGERS, *names], values=values)


def store_from_env() -> Store:
    """``PS_STORE=r2`` (the default) or ``PS_STORE=local`` with ``PS_LOCAL_STORE_DIR``."""
    kind = (os.environ.get("PS_STORE") or "r2").lower()
    if kind == "local":
        root = os.environ.get("PS_LOCAL_STORE_DIR")
        if not root:
            raise StoreConfigError("PS_STORE=local needs PS_LOCAL_STORE_DIR")
        return LocalStore(root)
    if kind == "r2":
        return R2Store.from_env()
    raise StoreConfigError(f"PS_STORE must be 'r2' or 'local', not {kind!r}")


# Helpers over the five pinned methods; they work with any store, a test's proxy included.


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def put_json(store: Store, key: str, value: Any) -> None:
    store.put(key, _json_bytes(value))


def update_json(
    store: Store, key: str, change: Callable[[Any | None], Any], attempts: int = 5
) -> Any:
    """Read ``key``, write ``change(value)`` back, and never overwrite a write it did not read.

    ``change`` gets the stored JSON value (``None`` when the key is absent) and returns the new
    one; it may be called again when another writer got in first. Stores with ``get_tagged`` and
    ``put_if`` (R2: ``If-Match``; ``LocalStore``: a lock and a digest) make the write
    conditional; on any other store (a test's proxy) it is a plain read and write. Raises
    ``ConcurrentUpdate`` when ``attempts`` conditional writes in a row were refused.
    """
    get_tagged = getattr(store, "get_tagged", None)
    put_if = getattr(store, "put_if", None)
    if get_tagged is None or put_if is None:
        try:
            current = get_json(store, key)
        except KeyError:
            current = None
        value = change(current)
        put_json(store, key, value)
        return value
    for _ in range(attempts):
        try:
            data, tag = get_tagged(key)
            current = json.loads(data)
        except KeyError:
            current, tag = None, None
        value = change(current)
        if put_if(key, _json_bytes(value), tag):
            return value
    raise ConcurrentUpdate(f"{key} kept changing during {attempts} conditional writes")


def get_json(store: Store, key: str) -> Any:
    return json.loads(store.get(key))


def record_key(symbol: str) -> str:
    return f"prices/{symbol}.parquet"


def record_to_bytes(record: pd.DataFrame) -> bytes:
    """The canonical record as parquet: the five columns, ``date`` as tz-naive datetime64[ns]."""
    missing = [column for column in RECORD_COLUMNS if column not in record.columns]
    if missing:
        raise ValueError(f"canonical record lacks column(s) {missing}")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(record["date"]).to_numpy().astype("datetime64[ns]"),
            **{
                column: record[column].to_numpy(dtype=float)
                for column in RECORD_COLUMNS
                if column != "date"
            },
        }
    )
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


def record_from_bytes(data: bytes) -> pd.DataFrame:
    frame = pd.read_parquet(io.BytesIO(data))
    return frame.sort_values("date").reset_index(drop=True)


def put_record(store: Store, symbol: str, record: pd.DataFrame) -> None:
    store.put(record_key(symbol), record_to_bytes(record))


def get_record(store: Store, symbol: str) -> pd.DataFrame:
    return record_from_bytes(store.get(record_key(symbol)))


def _error_code(exc: BaseException) -> str:
    response = getattr(exc, "response", None) or {}
    return str(response.get("Error", {}).get("Code", ""))


def _http_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None) or {}
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return int(status) if status is not None else None


def _describe_failure(exc: BaseException) -> str:
    """Error class, code and HTTP status only: never a message that could echo a credential."""
    parts = [type(exc).__name__]
    if _error_code(exc):
        parts.append(f"code {_error_code(exc)}")
    if _http_status(exc) is not None:
        parts.append(f"HTTP {_http_status(exc)}")
    return ", ".join(parts)


def verify(store: Any, emit: Callable[[str], None] = print) -> int:
    """head_bucket, put/get/delete of ``meta/_probe``, list. 0 when all pass, else 2.

    The probe is deleted again; a 403 prints which token scope is missing (spec 9.5 step 1).
    """
    payload = f"portfoliosight store probe {uuid.uuid4().hex}\n".encode()
    bucket = getattr(store, "bucket", DEFAULT_BUCKET)

    def head_bucket() -> None:
        store.check()

    def put() -> None:
        store.put(PROBE_KEY, payload)

    def get() -> None:
        if store.get(PROBE_KEY) != payload:
            raise OSError("the probe read back differs from the probe written")

    def delete() -> None:
        store.delete(PROBE_KEY)
        if store.exists(PROBE_KEY):
            raise OSError("the probe still exists after delete")

    def list_() -> None:
        if PROBE_KEY in store.list("meta/"):
            raise OSError("the deleted probe is still listed")

    emit(f"verifying {store.describe()}")
    steps = (("head_bucket", head_bucket), ("put", put), ("get", get), ("delete", delete))
    for name, step in (*steps, ("list", list_)):
        try:
            step()
        except (ClientError, BotoCoreError, OSError, KeyError) as exc:
            emit(f"{name} failed: {_describe_failure(exc)}")
            if _http_status(exc) == 403 or _error_code(exc) in ("403", "AccessDenied"):
                emit(SCOPE_HINT.format(bucket=bucket))
            if name in ("put", "get"):
                try:
                    store.delete(PROBE_KEY)
                except (ClientError, BotoCoreError, OSError):
                    pass
            return 2
        emit(f"{name} ok")
    emit(f"store verify passed for {store.describe()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m portfoliosight.data.store")
    parser.add_argument("--verify", action="store_true", help="check the store end to end")
    args = parser.parse_args(argv)
    if not args.verify:
        parser.print_usage(sys.stderr)
        return 64
    try:
        store = store_from_env()
    except StoreConfigError as exc:
        print(f"store verify not run: {exc}", file=sys.stderr)
        return 2
    return verify(store)


if __name__ == "__main__":
    from portfoliosight.data.secrets import load_env

    load_env()
    raise SystemExit(main())
