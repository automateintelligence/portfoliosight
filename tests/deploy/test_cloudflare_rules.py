"""scripts/cloudflare_rules.py against a local stub of the Cloudflare rulesets API (spec 9.4)."""

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
SECRET = "0123456789abcdef0123456789abcdef0123456789abcdef"
WAF = "http_request_firewall_custom"
RATE = "http_ratelimit"
UNRELATED = {
    "id": "unrelated-1",
    "description": "someone-elses-rule",
    "expression": '(http.request.uri.path eq "/other")',
    "action": "block",
    "enabled": True,
    "version": "3",
    "last_updated": "2026-01-01T00:00:00Z",
}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rules_mod = _load("cloudflare_rules")


class Stub:
    """The zone lookup and the two phase entry points, held in memory."""

    def __init__(self, mock: responses.RequestsMock, rulesets: dict[str, list[dict] | None]):
        self.mock = mock
        self.rulesets = rulesets
        self.next_id = 1
        mock.add_callback(responses.GET, f"{BASE}/zones", callback=self._zones)
        for phase in (WAF, RATE):
            entry = f"{BASE}/zones/{ZONE_ID}/rulesets/phases/{phase}/entrypoint"
            mock.add_callback(responses.GET, entry, callback=self._get(phase))
            mock.add_callback(responses.PUT, entry, callback=self._put(phase))
            rules = f"{BASE}/zones/{ZONE_ID}/rulesets/rs-{phase}/rules"
            mock.add_callback(responses.POST, rules, callback=self._post(phase))
            mock.add_callback(
                responses.PATCH,
                re.compile(re.escape(rules) + r"/[\w-]+"),
                callback=self._patch(phase),
            )

    def _ok(self, result) -> tuple[int, dict, str]:
        return 200, {}, json.dumps({"success": True, "errors": [], "result": result})

    def _ruleset(self, phase: str) -> dict:
        return {"id": f"rs-{phase}", "phase": phase, "kind": "zone", "rules": self.rulesets[phase]}

    def _zones(self, request):
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.params == {"name": "portfoliosight.ai"}
        return self._ok([{"id": ZONE_ID, "name": "portfoliosight.ai"}])

    def _get(self, phase: str):
        def callback(request):
            if self.rulesets[phase] is None:
                body = {"success": False, "errors": [{"code": 10003, "message": "not found"}]}
                return 404, {}, json.dumps(body)
            return self._ok(self._ruleset(phase))

        return callback

    def _stored(self, rule: dict) -> dict:
        stored = {**rule, "id": f"new-{self.next_id}", "version": "1"}
        self.next_id += 1
        return stored

    def _put(self, phase: str):
        def callback(request):
            assert self.rulesets[phase] is None, "PUT must only create a missing entry point"
            self.rulesets[phase] = [
                self._stored(rule) for rule in json.loads(request.body)["rules"]
            ]
            return self._ok(self._ruleset(phase))

        return callback

    def _post(self, phase: str):
        def callback(request):
            rules = self.rulesets[phase]
            assert rules is not None
            rules.append(self._stored(json.loads(request.body)))
            return self._ok(self._ruleset(phase))

        return callback

    def _patch(self, phase: str):
        def callback(request):
            rule_id = request.url.rsplit("/", 1)[1]
            rules = self.rulesets[phase]
            assert rules is not None
            (index,) = [i for i, rule in enumerate(rules) if rule["id"] == rule_id]
            rules[index] = {**rules[index], **json.loads(request.body)}
            return self._ok(self._ruleset(phase))

        return callback

    def writes(self) -> list[tuple[str, str]]:
        return [
            (str(call.request.method), str(call.request.url).removeprefix(BASE))
            for call in self.mock.calls
            if call.request.method != "GET"
        ]

    def descriptions(self, phase: str) -> list[str]:
        return [rule["description"] for rule in self.rulesets[phase] or []]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_BASE", BASE)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
    monkeypatch.setenv("PS_GATE_SECRET", SECRET)


@pytest.fixture
def mock():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as requests_mock:
        yield requests_mock


def test_waf_rules_are_exactly_the_spec_expressions():
    challenge, block = rules_mod.build_waf_rules(SECRET)
    assert challenge == {
        "description": "ps-challenge-site",
        "expression": (
            '(http.host in {"portfoliosight.ai" "www.portfoliosight.ai"}) and not '
            f'any(http.request.headers["x-ps-gate"][*] == "{SECRET}")'
        ),
        "action": "managed_challenge",
        "enabled": True,
    }
    assert block == {
        "description": "ps-block-api-direct",
        "expression": (
            '(http.host eq "api.portfoliosight.ai") and not '
            f'any(http.request.headers["x-ps-gate"][*] == "{SECRET}")'
        ),
        "action": "block",
        "enabled": True,
    }


@pytest.mark.parametrize(
    "bad", ["", "short", 'quote"inside' * 3, "back\\slash" * 3, "space inside it all"]
)
def test_a_secret_that_could_break_the_expression_is_refused(bad):
    with pytest.raises(ValueError) as caught:
        rules_mod.build_waf_rules(bad)
    assert bad == "" or bad not in str(caught.value)


def test_ratelimit_rule_is_the_spec_rule():
    assert rules_mod.build_ratelimit_rule() == {
        "description": "ps-tensor-post",
        "expression": '(http.request.uri.path eq "/api/tensors")',
        "action": "block",
        "enabled": True,
        "ratelimit": {
            "characteristics": ["ip.src", "cf.colo.id"],
            "period": 10,
            "requests_per_period": 20,
            "mitigation_timeout": 10,
        },
    }


def test_plan_creates_what_is_missing_and_leaves_unrelated_rules_alone():
    desired = rules_mod.build_waf_rules(SECRET)
    steps = rules_mod.plan_updates([UNRELATED], desired)
    assert [(step.op, step.rule["description"], step.rule_id) for step in steps] == [
        ("create", "ps-challenge-site", None),
        ("create", "ps-block-api-direct", None),
    ]


def test_plan_updates_in_place_by_description_and_is_idempotent():
    desired = rules_mod.build_waf_rules(SECRET)
    stale = {**desired[0], "id": "r1", "expression": '(http.host eq "old")', "version": "7"}
    same = {**desired[1], "id": "r2", "version": "2", "last_updated": "2026-01-01T00:00:00Z"}
    steps = rules_mod.plan_updates([UNRELATED, stale, same], desired)
    assert [(step.op, step.rule_id) for step in steps] == [("update", "r1"), ("unchanged", "r2")]
    assert steps[0].rule == desired[0]
    settled = [UNRELATED, {**stale, **desired[0]}, same]
    assert {step.op for step in rules_mod.plan_updates(settled, desired)} == {"unchanged"}


def test_plan_tolerates_server_side_defaults_inside_ratelimit():
    desired = rules_mod.build_ratelimit_rule()
    stored = {
        **desired,
        "id": "r9",
        "ratelimit": {**desired["ratelimit"], "requests_to_origin": False},
    }
    assert [step.op for step in rules_mod.plan_updates([stored], [desired])] == ["unchanged"]


def test_plan_refuses_two_existing_rules_with_one_name():
    desired = rules_mod.build_waf_rules(SECRET)
    twice = [{**desired[0], "id": "a"}, {**desired[0], "id": "b"}]
    with pytest.raises(ValueError, match="ps-challenge-site"):
        rules_mod.plan_updates(twice, desired)


def test_dry_run_reads_only_and_redacts_the_secret(env, mock, capsys):
    stub = Stub(mock, {WAF: [dict(UNRELATED)], RATE: None})
    assert rules_mod.main(["--dry-run"]) == 0
    out = capsys.readouterr()
    assert stub.writes() == []
    assert SECRET not in out.out + out.err and TOKEN not in out.out + out.err
    assert out.out.count("[redacted]") == 2
    lines = [json.loads(line) for line in out.out.splitlines()]
    assert [(line["phase"], line["op"], line["description"]) for line in lines] == [
        (WAF, "create", "ps-challenge-site"),
        (WAF, "create", "ps-block-api-direct"),
        (RATE, "create", "ps-tensor-post"),
    ]
    assert all(line["applied"] is False for line in lines)
    assert lines[0]["expression"].endswith('[*] == "[redacted]")')


def test_no_flag_means_dry_run(env, mock, capsys):
    stub = Stub(mock, {WAF: None, RATE: None})
    assert rules_mod.main([]) == 0
    assert stub.writes() == []


def test_apply_creates_the_rules_without_touching_unrelated_ones(env, mock, capsys):
    stub = Stub(mock, {WAF: [dict(UNRELATED)], RATE: None})
    assert rules_mod.main(["--apply"]) == 0
    out = capsys.readouterr()
    assert SECRET not in out.out + out.err and TOKEN not in out.out + out.err
    assert stub.writes() == [
        ("POST", f"/zones/{ZONE_ID}/rulesets/rs-{WAF}/rules"),
        ("POST", f"/zones/{ZONE_ID}/rulesets/rs-{WAF}/rules"),
        ("PUT", f"/zones/{ZONE_ID}/rulesets/phases/{RATE}/entrypoint"),
    ]
    waf_rules = stub.rulesets[WAF]
    assert waf_rules is not None and waf_rules[0] == UNRELATED
    assert stub.descriptions(WAF) == [
        "someone-elses-rule",
        "ps-challenge-site",
        "ps-block-api-direct",
    ]
    assert stub.descriptions(RATE) == ["ps-tensor-post"]
    for call in mock.calls:
        body = call.request.body or b""
        assert b"someone-elses-rule" not in (
            body if isinstance(body, bytes) else str(body).encode()
        )


def test_apply_twice_changes_nothing_the_second_time(env, mock, capsys):
    stub = Stub(mock, {WAF: None, RATE: None})
    assert rules_mod.main(["--apply"]) == 0
    first = stub.writes()
    assert first == [
        ("PUT", f"/zones/{ZONE_ID}/rulesets/phases/{WAF}/entrypoint"),
        ("PUT", f"/zones/{ZONE_ID}/rulesets/phases/{RATE}/entrypoint"),
    ]
    capsys.readouterr()
    assert rules_mod.main(["--apply"]) == 0
    assert stub.writes() == first
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["op"] for line in lines] == ["unchanged"] * 3
    assert len(stub.descriptions(WAF)) == 2 and len(stub.descriptions(RATE)) == 1


def test_apply_updates_a_rule_whose_secret_changed(env, mock, monkeypatch, capsys):
    stub = Stub(mock, {WAF: None, RATE: None})
    assert rules_mod.main(["--apply"]) == 0
    waf_rules = stub.rulesets[WAF]
    assert waf_rules is not None
    ids = [rule["id"] for rule in waf_rules]
    rotated = "f" * 48
    monkeypatch.setenv("PS_GATE_SECRET", rotated)
    assert rules_mod.main(["--apply"]) == 0
    assert stub.writes()[2:] == [
        ("PATCH", f"/zones/{ZONE_ID}/rulesets/rs-{WAF}/rules/{ids[0]}"),
        ("PATCH", f"/zones/{ZONE_ID}/rulesets/rs-{WAF}/rules/{ids[1]}"),
    ]
    assert [rule["id"] for rule in waf_rules] == ids
    assert all(rotated in rule["expression"] for rule in waf_rules)
    assert rotated not in capsys.readouterr().out


def test_a_refused_call_fails_without_echoing_secrets(env, mock, capsys):
    mock.add(
        responses.GET,
        f"{BASE}/zones",
        json={
            "success": True,
            "errors": [],
            "result": [{"id": ZONE_ID, "name": "portfoliosight.ai"}],
        },
    )
    mock.add(
        responses.GET,
        f"{BASE}/zones/{ZONE_ID}/rulesets/phases/{WAF}/entrypoint",
        status=403,
        json={
            "success": False,
            "errors": [{"code": 10000, "message": f"Authentication error near {SECRET} {TOKEN}"}],
        },
    )
    assert rules_mod.main(["--apply"]) == 1
    out = capsys.readouterr()
    assert "403" in out.err and "10000" in out.err
    assert SECRET not in out.out + out.err and TOKEN not in out.out + out.err


def test_a_zone_answer_for_another_zone_stops_everything(env, mock, capsys):
    mock.add(
        responses.GET,
        f"{BASE}/zones",
        json={"success": True, "errors": [], "result": [{"id": ZONE_ID, "name": "other.example"}]},
    )
    assert rules_mod.main(["--apply"]) == 1
    assert len(mock.calls) == 1


@pytest.mark.parametrize(
    "missing", ["CLOUDFLARE_API_BASE", "CLOUDFLARE_API_TOKEN", "PS_GATE_SECRET"]
)
def test_a_missing_setting_is_named_and_nothing_is_called(env, mock, monkeypatch, capsys, missing):
    monkeypatch.delenv(missing)
    assert rules_mod.main(["--apply"]) == 3
    assert missing in capsys.readouterr().err
    assert len(mock.calls) == 0


def test_api_base_argument_wins_over_the_environment(env, mock, monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_BASE", "http://wrong.invalid/v4")
    stub = Stub(mock, {WAF: None, RATE: None})
    assert rules_mod.main(["--dry-run", "--api-base", BASE]) == 0
    assert stub.writes() == []


def test_the_scripts_spell_no_url():
    for name in ("cloudflare_rules.py", "cloudflare_dns.py", "cloudflare_api.py"):
        text = (ROOT / "scripts" / name).read_text()
        assert not re.search(r"https?://", text), name
