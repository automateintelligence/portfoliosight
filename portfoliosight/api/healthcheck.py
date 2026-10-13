"""The container's own health probe (spec 9.1).

    python -m portfoliosight.api.healthcheck

Asks the service in this container for ``/v1/health`` with the gate secret from the
environment; exit status 0 only for HTTP 200. The secret is never printed.
"""

from __future__ import annotations

import http.client
import os
import sys

from portfoliosight.api.gate import GATE_HEADER
from portfoliosight.api.settings import GATE_SECRET_ENV

HOST = "127.0.0.1"
PORT = 8000
PATH = "/v1/health"
TIMEOUT_SECONDS = 8.0


def probe(host: str = HOST, port: int = PORT) -> int:
    """0 when the service answers 200, else 1."""
    connection = http.client.HTTPConnection(host, port, timeout=TIMEOUT_SECONDS)
    try:
        headers = {GATE_HEADER: os.environ.get(GATE_SECRET_ENV, "")}
        connection.request("GET", PATH, headers=headers)
        status = connection.getresponse().status
    except (OSError, http.client.HTTPException) as exc:
        print(f"health probe failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    if status != 200:
        print(f"health probe: HTTP {status}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(probe())
