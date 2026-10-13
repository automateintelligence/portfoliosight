"""Environment loading and log redaction.

Secrets are read from the process environment only. ``load_env`` fills the environment from the
project's own env file; no other env file is ever read.
"""

from __future__ import annotations

import logging
import os
import re
import traceback
from collections.abc import Iterable
from pathlib import Path

DEFAULT_ENV_FILE = Path("~/.secrets/portfoliosight.env")
SECRET_NAMES = (
    "TIINGO_API_KEY",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
    "PS_GATE_SECRET",
    "MAILCHANNELS_API_KEY",
    "MAILCHANNELS_DKIM_PRIVATE_KEY",
)
REDACTED = "[redacted]"
_TOKEN_RE = re.compile(r"(\bToken\s+|\bapi_token\s*[=:]\s*)\S+")
_MIN_SECRET_LENGTH = 6


def load_env(path: str | Path | None = None) -> list[str]:
    """Set every ``KEY=value`` of the env file that the environment lacks; return those names."""
    env_file = Path(path if path is not None else DEFAULT_ENV_FILE).expanduser()
    if not env_file.is_file():
        return []
    loaded: list[str] = []
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        line = line.removeprefix("export ").lstrip()
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not name.isidentifier() or name in os.environ:
            continue
        os.environ[name] = value
        loaded.append(name)
    return loaded


class RedactingFilter(logging.Filter):
    """Rewrite token headers and secret values in a record before any handler sees it."""

    def __init__(self, values: Iterable[str] = (), env_names: Iterable[str] = SECRET_NAMES):
        super().__init__()
        self._values: set[str] = set()
        self._env_names = tuple(env_names)
        self.add_values(values)

    def add_values(self, values: Iterable[str]) -> None:
        self._values.update(v for v in values if v)

    def redact(self, text: str) -> str:
        secrets_now = set(self._values)
        for name in self._env_names:
            value = os.environ.get(name, "")
            if len(value) >= _MIN_SECRET_LENGTH:
                secrets_now.add(value)
        for value in sorted(secrets_now, key=len, reverse=True):
            text = text.replace(value, REDACTED)
        return _TOKEN_RE.sub(lambda m: m.group(1) + REDACTED, text)

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = None
        return True


def install_redaction(logger_names: Iterable[str], values: Iterable[str] = ()) -> None:
    """Attach one ``RedactingFilter`` to each named logger; a repeat call only adds values."""
    for name in logger_names:
        logger = logging.getLogger(name)
        existing = next((f for f in logger.filters if isinstance(f, RedactingFilter)), None)
        if existing is None:
            logger.addFilter(RedactingFilter(values))
        else:
            existing.add_values(values)


def redacted_traceback(exc: BaseException) -> str:
    """The exception's traceback as text, with secret values and token headers rewritten.

    For a failure that would otherwise reach the interpreter's or the server's own traceback
    printer, which redacts nothing.
    """
    return RedactingFilter().redact("".join(traceback.format_exception(exc))).rstrip()
