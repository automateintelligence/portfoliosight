"""Origin authentication (spec 6, 9.4): every request must carry the gate secret.

The Worker's same-zone fetch bypasses the WAF, so this comparison is the authentication of
record. It is constant-time, runs on every request (also one without the header, which is
compared as an empty value) and its result alone decides.

The caller's access tier (engines spec 6.2) rides on the same proof: the Worker sends
``x-ps-tier: admin`` only for a visitor whose admin cookie verified, and always drops a
visitor's own ``x-ps-tier``. The header counts only on a request that also carries the gate
secret, so nobody without that secret can claim a tier.
"""

from __future__ import annotations

import hmac
from typing import Literal

GATE_HEADER = "x-ps-gate"
GATE_SECRET_ENV = "PS_GATE_SECRET"
TIER_HEADER = "x-ps-tier"

Tier = Literal["public", "admin"]


def gate_open(presented: str | None, secret: str) -> bool:
    """True only when ``presented`` equals ``secret``, compared in constant time."""
    return hmac.compare_digest((presented or "").encode("utf-8"), secret.encode("utf-8"))


def caller_tier(gate: str | None, tier: str | None, secret: str) -> Tier:
    """``admin`` only for ``x-ps-tier: admin`` together with the gate secret; else ``public``."""
    if not gate_open(gate, secret):
        return "public"
    return "admin" if tier == "admin" else "public"
