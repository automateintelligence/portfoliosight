"""The small Cloudflare API client shared by cloudflare_rules.py and cloudflare_dns.py.

The base URL comes from ``--api-base`` or ``CLOUDFLARE_API_BASE`` and the token from
``CLOUDFLARE_API_TOKEN``; neither is spelled in this repository. Every message this module
produces has the token and any other registered secret replaced by ``[redacted]``.
"""

from __future__ import annotations

import os
from typing import Any

import requests

ZONE_NAME = "portfoliosight.ai"
REDACTED = "[redacted]"
TIMEOUT_S = 30
EXIT_API = 1
EXIT_SETTINGS = 3
EXIT_USAGE = 64


class SettingsError(RuntimeError):
    """A required setting is absent."""


class CloudflareError(RuntimeError):
    """The API refused a call. The message is already redacted."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def setting(name: str, override: str | None = None) -> str:
    value = override or os.environ.get(name, "")
    if not value:
        raise SettingsError(f"{name} is not set")
    return value


class Client:
    def __init__(self, base: str, token: str, secrets: tuple[str, ...] = ()):
        self._base = base.rstrip("/")
        self._token = token
        self._secrets = tuple(s for s in (token, *secrets) if s)
        self._session = requests.Session()

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return text

    def call(self, method: str, path: str, *, params: dict | None = None, body: Any = None) -> Any:
        """One API call; returns ``result``. A refusal raises CloudflareError (redacted)."""
        what = f"{method} {path}"
        try:
            response = self._session.request(
                method,
                f"{self._base}{path}",
                params=params,
                json=body,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=TIMEOUT_S,
            )
        except requests.RequestException as error:
            raise CloudflareError(self.redact(f"{what}: {type(error).__name__}")) from None
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if response.status_code >= 400 or payload.get("success") is not True:
            errors = payload.get("errors") or []
            detail = "; ".join(
                f"{item.get('code')}: {item.get('message')}"
                for item in errors
                if isinstance(item, dict)
            )
            message = f"{what} answered {response.status_code} ({detail or 'no error detail'})"
            raise CloudflareError(self.redact(message), response.status_code)
        return payload.get("result")

    def zone_id(self, name: str = ZONE_NAME) -> str:
        """The id of the one zone with exactly this name; anything else is an error."""
        zones = self.call("GET", "/zones", params={"name": name}) or []
        if len(zones) != 1 or zones[0].get("name") != name or not zones[0].get("id"):
            raise CloudflareError(f"the token did not return exactly the zone {name}; nothing done")
        return str(zones[0]["id"])


def client_from_settings(api_base: str | None, secrets: tuple[str, ...] = ()) -> Client:
    base = setting("CLOUDFLARE_API_BASE", api_base)
    return Client(base, setting("CLOUDFLARE_API_TOKEN"), secrets)
