"""The owner's withheld list: symbols whose stored prices are known to be wrong (spec 5.4).

``data/universes/withheld.json`` maps a symbol to ``{"note", "good_through", "since"}``: why it
is withheld, the last day its prices can be trusted, and the day it was withheld. The lake sync
reads it and keeps each listed symbol ``unavailable`` with the reason
``{note}; no data since {good_through}`` until the owner takes it off the list.

The file is checked whole by ``load_withheld`` before anything is written: a key, symbol, note
or date that is not exactly what is allowed refuses the whole file with its reason.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from portfoliosight.data.manifest import no_data_since

REPO_ROOT = Path(__file__).resolve().parents[2]
WITHHELD_FILE = REPO_ROOT / "data" / "universes" / "withheld.json"
KEYS = ("note", "good_through", "since")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class WithheldError(ValueError):
    """The withheld list cannot be used; the message names the file and the reason."""


class Withheld(BaseModel):
    """One withheld symbol: why, the last trustworthy day, and the day it was withheld."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    note: str
    good_through: date
    since: date

    def reason(self) -> str:
        """The catalog reason: ``{note}; no data since {good_through}``."""
        return no_data_since(self.good_through, self.note)


def _no_repeats(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise WithheldError(f"{key} is listed twice")
        out[key] = value
    return out


def _day(symbol: str, key: str, value: Any) -> date:
    if not isinstance(value, str) or not _DAY_RE.match(value):
        raise WithheldError(f"{symbol}: {key} must be a YYYY-MM-DD date, not {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise WithheldError(f"{symbol}: {key} {value!r} is not a calendar day") from None


def _entry(symbol: str, row: Any, covered: Collection[str]) -> Withheld:
    if symbol not in covered:
        raise WithheldError(f"{symbol!r} is not a symbol the lake sync covers")
    if not isinstance(row, dict):
        raise WithheldError(f"{symbol} needs an object with {', '.join(KEYS)}")
    missing = [key for key in KEYS if key not in row]
    if missing:
        raise WithheldError(f"{symbol}: missing {', '.join(missing)}")
    unknown = sorted(set(row) - set(KEYS))
    if unknown:
        raise WithheldError(f"{symbol}: unknown key(s) {', '.join(unknown)}")
    note = row["note"]
    if not isinstance(note, str) or not note.strip() or "\n" in note or "\r" in note:
        raise WithheldError(f"{symbol}: note must be one line of text, not {note!r}")
    good_through = _day(symbol, "good_through", row["good_through"])
    since = _day(symbol, "since", row["since"])
    if good_through > since:
        raise WithheldError(f"{symbol}: good_through {good_through} is after since {since}")
    return Withheld(note=note.strip(), good_through=good_through, since=since)


def load_withheld(path: Path, covered: Collection[str]) -> dict[str, Withheld]:
    """The withheld list at ``path``, each symbol one of ``covered``; refused whole when any
    part of it is not allowed (``WithheldError`` naming the file and the reason)."""
    try:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise WithheldError(f"cannot read it: {type(exc).__name__}") from None
        try:
            document = json.loads(text, object_pairs_hook=_no_repeats)
        except ValueError as exc:
            if isinstance(exc, WithheldError):
                raise
            raise WithheldError(f"not valid JSON: {exc}") from None
        if not isinstance(document, dict):
            raise WithheldError("must be an object of symbol to {note, good_through, since}")
        return {symbol: _entry(symbol, row, covered) for symbol, row in document.items()}
    except WithheldError as exc:
        raise WithheldError(f"{path.name}: {exc}") from None
