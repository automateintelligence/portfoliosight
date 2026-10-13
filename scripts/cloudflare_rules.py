"""Create or update the three edge rules of spec 9.4 on the portfoliosight.ai zone.

    python scripts/cloudflare_rules.py [--dry-run | --apply] [--api-base URL]

Two WAF custom rules (``ps-challenge-site``, ``ps-block-api-direct``) and one rate-limiting
rule (``ps-tensor-post``). Without ``--apply`` nothing is written: the plan is printed, one JSON
line per rule, with the gate secret shown as ``[redacted]``.

Rules are matched by ``description``. A rule that exists is updated in place by its own id, a
missing one is added, and no other rule of the zone is read back or rewritten: the phase entry
point is only ever written as a whole when it does not exist yet. Running it again changes
nothing.

Settings (environment): ``CLOUDFLARE_API_BASE`` (or ``--api-base``), ``CLOUDFLARE_API_TOKEN``
(needs Zone WAF Edit on the zone), ``PS_GATE_SECRET``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cloudflare_api as api  # noqa: E402

WAF_PHASE = "http_request_firewall_custom"
RATELIMIT_PHASE = "http_ratelimit"
# The secret sits inside a quoted string of the rule expression.
SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{24,128}$")


@dataclass(frozen=True)
class Step:
    op: str  # "create" | "update" | "unchanged"
    rule: dict[str, Any]
    rule_id: str | None


def build_waf_rules(secret: str) -> list[dict[str, Any]]:
    if not SECRET_RE.fullmatch(secret):
        raise ValueError("PS_GATE_SECRET must be 24 to 128 characters of A-Z a-z 0-9 _ -")
    without_header = f'not any(http.request.headers["x-ps-gate"][*] == "{secret}")'
    return [
        {
            "description": "ps-challenge-site",
            "expression": (
                '(http.host in {"portfoliosight.ai" "www.portfoliosight.ai"}) and ' + without_header
            ),
            "action": "managed_challenge",
            "enabled": True,
        },
        {
            "description": "ps-block-api-direct",
            "expression": '(http.host eq "api.portfoliosight.ai") and ' + without_header,
            "action": "block",
            "enabled": True,
        },
    ]


def build_ratelimit_rule() -> dict[str, Any]:
    return {
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


def _matches(existing: Any, desired: Any) -> bool:
    """True when every desired field has that value; fields the server adds are ignored."""
    if isinstance(desired, dict):
        return isinstance(existing, dict) and all(
            _matches(existing.get(key), value) for key, value in desired.items()
        )
    return existing == desired


def plan_updates(existing_rules: list[dict[str, Any]], desired: list[dict[str, Any]]) -> list[Step]:
    """One step per desired rule. Existing rules with other descriptions are never part of it."""
    steps = []
    for rule in desired:
        name = rule["description"]
        found = [item for item in existing_rules if item.get("description") == name]
        if len(found) > 1:
            raise ValueError(f"{len(found)} existing rules are named {name}; nothing done")
        if not found:
            steps.append(Step("create", rule, None))
        elif _matches(found[0], rule):
            steps.append(Step("unchanged", rule, str(found[0]["id"])))
        else:
            steps.append(Step("update", rule, str(found[0]["id"])))
    return steps


def _sync_phase(
    client: api.Client, zone_id: str, phase: str, desired: list[dict[str, Any]], apply: bool
) -> list[Step]:
    entry = f"/zones/{zone_id}/rulesets/phases/{phase}/entrypoint"
    try:
        ruleset = client.call("GET", entry)
    except api.CloudflareError as error:
        if error.status != 404:
            raise
        ruleset = None
    if ruleset is None:
        # No entry point yet, so there is no rule of anyone's to keep.
        if apply:
            client.call("PUT", entry, body={"rules": desired})
        return [Step("create", rule, None) for rule in desired]
    steps = plan_updates(ruleset.get("rules") or [], desired)
    if apply:
        rules_path = f"/zones/{zone_id}/rulesets/{ruleset['id']}/rules"
        for step in steps:
            if step.op == "create":
                client.call("POST", rules_path, body=step.rule)
            elif step.op == "update":
                client.call("PATCH", f"{rules_path}/{step.rule_id}", body=step.rule)
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan only (the default)")
    mode.add_argument("--apply", action="store_true", help="write the rules")
    parser.add_argument("--api-base", help="Cloudflare API base URL (else CLOUDFLARE_API_BASE)")
    args = parser.parse_args(argv)

    try:
        secret = api.setting("PS_GATE_SECRET")
        client = api.client_from_settings(args.api_base, secrets=(secret,))
        phases = [
            (WAF_PHASE, build_waf_rules(secret)),
            (RATELIMIT_PHASE, [build_ratelimit_rule()]),
        ]
    except api.SettingsError as error:
        print(f"{error}; nothing done", file=sys.stderr)
        return api.EXIT_SETTINGS
    except ValueError as error:
        print(f"{error}; nothing done", file=sys.stderr)
        return api.EXIT_SETTINGS

    try:
        zone_id = client.zone_id()
        for phase, desired in phases:
            for step in _sync_phase(client, zone_id, phase, desired, args.apply):
                line = {
                    "phase": phase,
                    "op": step.op,
                    "applied": args.apply and step.op != "unchanged",
                    "description": step.rule["description"],
                    "action": step.rule["action"],
                    "expression": step.rule["expression"],
                }
                print(client.redact(json.dumps(line)))
    except (api.CloudflareError, ValueError) as error:
        print(client.redact(str(error)), file=sys.stderr)
        return api.EXIT_API
    return 0


if __name__ == "__main__":
    sys.exit(main())
