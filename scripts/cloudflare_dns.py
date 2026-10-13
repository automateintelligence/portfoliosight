"""Create, reuse or roll back one proxied CNAME in the portfoliosight.ai zone (spec 9.2).

    python scripts/cloudflare_dns.py ensure-cname --name NAME --target TARGET [--proxied]
    python scripts/cloudflare_dns.py rollback-cname --result JSON_OR_FILE

``ensure-cname`` prints one JSON line, ``{"record_id", "created_this_attempt", "name", "zone"}``.
It creates the record when the name has none, reuses a record that is already exactly the one
asked for, and refuses (changing nothing) when the name holds anything else.

``rollback-cname`` takes that JSON (the text itself or a file holding it). It deletes the record
only when ``created_this_attempt`` is true; a record that was there before is kept and no request
is made at all.

Settings (environment): ``CLOUDFLARE_API_BASE`` (or ``--api-base``), ``CLOUDFLARE_API_TOKEN``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cloudflare_api as api  # noqa: E402

RECORD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


class UsageError(ValueError):
    pass


def _in_zone(name: str) -> bool:
    return name == api.ZONE_NAME or name.endswith("." + api.ZONE_NAME)


def ensure_cname(client: api.Client, name: str, target: str, proxied: bool) -> dict[str, Any]:
    zone_id = client.zone_id()
    records_path = f"/zones/{zone_id}/dns_records"
    existing = client.call("GET", records_path, params={"name": name}) or []
    existing = [record for record in existing if record.get("name") == name]
    if not existing:
        body = {"type": "CNAME", "name": name, "content": target, "proxied": proxied, "ttl": 1}
        created = client.call("POST", records_path, body=body)
        return {"record_id": created["id"], "created_this_attempt": True}
    wanted = {"type": "CNAME", "content": target, "proxied": proxied}
    if len(existing) == 1 and all(existing[0].get(key) == value for key, value in wanted.items()):
        return {"record_id": existing[0]["id"], "created_this_attempt": False}
    ids = ", ".join(str(record.get("id")) for record in existing)
    raise api.CloudflareError(
        f"{name} already has a different record ({ids}); it was not changed and none was added"
    )


def _read_result(argument: str) -> dict[str, Any]:
    text = argument if argument.lstrip().startswith("{") else None
    if text is None:
        try:
            text = Path(argument).read_text(encoding="utf-8")
        except OSError as error:
            raise UsageError(f"--result is neither JSON nor a readable file: {error}") from None
    try:
        result = json.loads(text)
    except ValueError:
        raise UsageError("--result does not hold JSON") from None
    record_id = result.get("record_id") if isinstance(result, dict) else None
    created = result.get("created_this_attempt") if isinstance(result, dict) else None
    if not isinstance(record_id, str) or not RECORD_ID_RE.fullmatch(record_id):
        raise UsageError("--result has no usable record_id")
    if not isinstance(created, bool):
        raise UsageError("--result has no created_this_attempt (true or false)")
    return result


def rollback_cname(client: api.Client, result: dict[str, Any]) -> str:
    """Delete the record this attempt created. Only called when it did create one."""
    zone_id = client.zone_id()
    try:
        client.call("DELETE", f"/zones/{zone_id}/dns_records/{result['record_id']}")
    except api.CloudflareError as error:
        if error.status != 404:
            raise
        return f"record {result['record_id']} already absent"
    return f"deleted record {result['record_id']}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--api-base", help="Cloudflare API base URL (else CLOUDFLARE_API_BASE)")
    commands = parser.add_subparsers(dest="command", required=True)
    ensure = commands.add_parser("ensure-cname")
    ensure.add_argument("--name", required=True)
    ensure.add_argument("--target", required=True)
    ensure.add_argument("--proxied", action="store_true")
    rollback = commands.add_parser("rollback-cname")
    rollback.add_argument("--result", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "ensure-cname":
            name, target = args.name.lower().rstrip("."), args.target.lower().rstrip(".")
            if not HOSTNAME_RE.fullmatch(name) or not _in_zone(name):
                raise UsageError(f"--name must be a host name in the zone {api.ZONE_NAME}")
            if not HOSTNAME_RE.fullmatch(target):
                raise UsageError("--target must be a host name")
            client = api.client_from_settings(args.api_base)
            outcome = ensure_cname(client, name, target, args.proxied)
            print(json.dumps({**outcome, "name": name, "zone": api.ZONE_NAME}))
            return 0
        result = _read_result(args.result)
        if not result["created_this_attempt"]:
            print(f"kept pre-existing record {result['record_id']}")
            return 0
        client = api.client_from_settings(args.api_base)
        print(rollback_cname(client, result))
        return 0
    except UsageError as error:
        print(str(error), file=sys.stderr)
        return api.EXIT_USAGE
    except api.SettingsError as error:
        print(f"{error}; nothing done", file=sys.stderr)
        return api.EXIT_SETTINGS
    except api.CloudflareError as error:
        print(str(error), file=sys.stderr)
        return api.EXIT_API


if __name__ == "__main__":
    sys.exit(main())
