"""scripts/cloudflare_dns.py against a local stub of the Cloudflare DNS records API (spec 9.2)."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import responses

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://cloudflare.invalid/client/v4"
ZONE_ID = "z" * 32
TOKEN = "stub-token-that-must-never-be-printed"
NAME = "api.portfoliosight.ai"
TARGET = "00000000-0000-4000-8000-000000000000.cfargotunnel.com"
ENSURE = ["ensure-cname", "--name", NAME, "--target", TARGET, "--proxied"]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


dns_mod = _load("cloudflare_dns")


class Stub:
    """The zone lookup and the zone's DNS records, held in memory."""

    def __init__(self, mock: responses.RequestsMock, records: list[dict]):
        self.mock = mock
        self.records = records
        records_url = f"{BASE}/zones/{ZONE_ID}/dns_records"
        mock.add_callback(responses.GET, f"{BASE}/zones", callback=self._zones)
        mock.add_callback(responses.GET, records_url, callback=self._list)
        mock.add_callback(responses.POST, records_url, callback=self._create)
        mock.add_callback(
            responses.DELETE, re.compile(re.escape(records_url) + r"/[\w-]+"), callback=self._delete
        )

    def _ok(self, result) -> tuple[int, dict, str]:
        return 200, {}, json.dumps({"success": True, "errors": [], "result": result})

    def _zones(self, request):
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.params == {"name": "portfoliosight.ai"}
        return self._ok([{"id": ZONE_ID, "name": "portfoliosight.ai"}])

    def _list(self, request):
        return self._ok([r for r in self.records if r["name"] == request.params["name"]])

    def _create(self, request):
        record = {**json.loads(request.body), "id": f"rec-{len(self.records) + 1}"}
        self.records.append(record)
        return self._ok(record)

    def _delete(self, request):
        record_id = request.url.rsplit("/", 1)[1]
        before = len(self.records)
        self.records[:] = [r for r in self.records if r["id"] != record_id]
        if len(self.records) == before:
            body = {
                "success": False,
                "errors": [{"code": 81044, "message": "Record does not exist"}],
            }
            return 404, {}, json.dumps(body)
        return self._ok({"id": record_id})

    def methods(self) -> list[str]:
        return [str(call.request.method) for call in self.mock.calls]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_BASE", BASE)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)


@pytest.fixture
def mock():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as requests_mock:
        yield requests_mock


def _existing() -> dict:
    return {"id": "rec-old", "type": "CNAME", "name": NAME, "content": TARGET, "proxied": True}


def test_ensure_creates_the_record_when_absent(env, mock, capsys):
    stub = Stub(mock, [])
    assert dns_mod.main(ENSURE) == 0
    out = capsys.readouterr()
    result = json.loads(out.out)
    assert result == {
        "record_id": "rec-1",
        "created_this_attempt": True,
        "name": NAME,
        "zone": "portfoliosight.ai",
    }
    assert stub.records == [
        {"id": "rec-1", "type": "CNAME", "name": NAME, "content": TARGET, "proxied": True, "ttl": 1}
    ]
    assert TOKEN not in out.out + out.err


def test_ensure_reuses_an_identical_record_and_never_adds_a_second(env, mock, capsys):
    stub = Stub(mock, [_existing()])
    assert dns_mod.main(ENSURE) == 0
    result = json.loads(capsys.readouterr().out)
    assert (result["record_id"], result["created_this_attempt"]) == ("rec-old", False)
    assert stub.records == [_existing()]
    assert "POST" not in stub.methods()


def test_ensure_twice_creates_once(env, mock, capsys):
    stub = Stub(mock, [])
    assert dns_mod.main(ENSURE) == 0
    assert dns_mod.main(ENSURE) == 0
    first, second = (json.loads(line) for line in capsys.readouterr().out.splitlines())
    assert first["created_this_attempt"] is True and second["created_this_attempt"] is False
    assert first["record_id"] == second["record_id"]
    assert len(stub.records) == 1


@pytest.mark.parametrize(
    "other",
    [
        {"type": "CNAME", "content": "elsewhere.example", "proxied": True},
        {"type": "CNAME", "content": TARGET, "proxied": False},
        {"type": "A", "content": "192.0.2.1", "proxied": True},
    ],
)
def test_ensure_never_changes_a_different_record_at_that_name(env, mock, capsys, other):
    record = {"id": "rec-old", "name": NAME, **other}
    stub = Stub(mock, [dict(record)])
    assert dns_mod.main(ENSURE) == 1
    assert stub.records == [record]
    assert set(stub.methods()) == {"GET"}
    assert "rec-old" in capsys.readouterr().err


@pytest.mark.parametrize(
    "name", ["api.example.com", "portfoliosight.ai.example.com", "xportfoliosight.ai"]
)
def test_ensure_refuses_a_name_outside_the_zone(env, mock, capsys, name):
    Stub(mock, [])
    assert dns_mod.main(["ensure-cname", "--name", name, "--target", TARGET, "--proxied"]) == 64
    assert len(mock.calls) == 0


def test_reused_record_survives_a_failed_attempt(env, mock, capsys, tmp_path):
    """Existing record -> ensure -> the health check fails -> rollback: no delete, record intact."""
    stub = Stub(mock, [_existing()])
    assert dns_mod.main(ENSURE) == 0
    result_file = tmp_path / "dns.json"
    result_file.write_text(capsys.readouterr().out)
    calls_before = len(mock.calls)
    assert dns_mod.main(["rollback-cname", "--result", str(result_file)]) == 0
    out = capsys.readouterr()
    assert "kept pre-existing record" in out.out
    assert len(mock.calls) == calls_before
    assert "DELETE" not in stub.methods()
    assert stub.records == [_existing()]


def test_created_record_is_deleted_once_by_rollback(env, mock, capsys, tmp_path):
    other = {"id": "rec-apex", "type": "A", "name": "portfoliosight.ai", "content": "192.0.2.9"}
    stub = Stub(mock, [dict(other)])
    assert dns_mod.main(ENSURE) == 0
    result_text = capsys.readouterr().out
    assert len(stub.records) == 2
    assert dns_mod.main(["rollback-cname", "--result", result_text.strip()]) == 0
    assert stub.methods().count("DELETE") == 1
    assert stub.records == [other]
    deleted = [c.request.url for c in mock.calls if c.request.method == "DELETE"]
    assert deleted == [f"{BASE}/zones/{ZONE_ID}/dns_records/rec-2"]


def test_rollback_of_a_record_already_gone_is_not_an_error(env, mock, capsys):
    stub = Stub(mock, [])
    result = {"record_id": "rec-gone", "created_this_attempt": True, "name": NAME}
    assert dns_mod.main(["rollback-cname", "--result", json.dumps(result)]) == 0
    assert stub.methods().count("DELETE") == 1
    assert "already absent" in capsys.readouterr().out


@pytest.mark.parametrize(
    "result",
    [
        "not json",
        "{}",
        '{"record_id": "rec-1"}',
        '{"record_id": "", "created_this_attempt": true}',
        '{"record_id": "../../other", "created_this_attempt": true}',
        '{"record_id": "rec-1", "created_this_attempt": "yes"}',
    ],
)
def test_rollback_refuses_a_malformed_result(env, mock, capsys, result):
    Stub(mock, [])
    assert dns_mod.main(["rollback-cname", "--result", result]) == 64
    assert len(mock.calls) == 0


def test_a_refused_call_fails_without_echoing_the_token(env, mock, capsys):
    mock.add(
        responses.GET,
        f"{BASE}/zones",
        status=403,
        json={"success": False, "errors": [{"code": 9109, "message": f"Invalid token {TOKEN}"}]},
    )
    assert dns_mod.main(ENSURE) == 1
    out = capsys.readouterr()
    assert "403" in out.err and "9109" in out.err
    assert TOKEN not in out.out + out.err


@pytest.mark.parametrize("missing", ["CLOUDFLARE_API_BASE", "CLOUDFLARE_API_TOKEN"])
def test_a_missing_setting_is_named_and_nothing_is_called(env, mock, monkeypatch, capsys, missing):
    monkeypatch.delenv(missing)
    assert dns_mod.main(ENSURE) == 3
    assert missing in capsys.readouterr().err
    assert len(mock.calls) == 0
