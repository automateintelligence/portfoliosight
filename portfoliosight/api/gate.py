"""Origin authentication (spec 6, 9.4): every request must carry the gate secret.

The Worker's same-zone fetch bypasses the WAF, so this comparison is the authentication of
record. It is constant-time, runs on every request (also one without the header, which is
compared as an empty value) and its result alone decides.
"""

from __future__ import annotations

import hmac

GATE_HEADER = "x-ps-gate"
GATE_SECRET_ENV = "PS_GATE_SECRET"


def gate_open(presented: str | None, secret: str) -> bool:
    """True only when ``presented`` equals ``secret``, compared in constant time."""
    return hmac.compare_digest((presented or "").encode("utf-8"), secret.encode("utf-8"))
