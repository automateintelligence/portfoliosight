"""The owner's withheld list (spec 5.4): one strict validator for the whole file."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from portfoliosight.data import withheld as withheld_mod
from portfoliosight.data.universe import is_tsp, load_tiers

COVERED = frozenset({"AAPL", "CTVA", "VTI"})
GOOD = {"note": "price error under repair", "good_through": "2026-03-20", "since": "2026-11-26"}


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "withheld.json"
    path.write_text(text, encoding="utf-8")
    return path


def _load(tmp_path: Path, document) -> dict[str, withheld_mod.Withheld]:
    return withheld_mod.load_withheld(_write(tmp_path, json.dumps(document)), COVERED)


def test_a_valid_file_gives_each_symbol_its_note_and_dates(tmp_path):
    got = _load(tmp_path, {"CTVA": GOOD, "AAPL": {**GOOD, "note": "split applied twice"}})
    assert set(got) == {"CTVA", "AAPL"}
    ctva = got["CTVA"]
    assert ctva.note == "price error under repair"
    assert ctva.good_through == date(2026, 3, 20) and ctva.since == date(2026, 11, 26)
    # The spec 5.6 "{note}; no data since {date}" template, as FIENX's reason uses it.
    assert ctva.reason() == "price error under repair; no data since 2026-03-20"


def test_an_empty_file_withholds_nothing(tmp_path):
    assert _load(tmp_path, {}) == {}


@pytest.mark.parametrize(
    ("document", "says"),
    [
        ([], "must be an object"),
        ({"ZZZZ": GOOD}, "ZZZZ"),
        ({"ctva": GOOD}, "ctva"),
        ({"CTVA": "price error"}, "CTVA"),
        ({"CTVA": {k: v for k, v in GOOD.items() if k != "note"}}, "note"),
        ({"CTVA": {k: v for k, v in GOOD.items() if k != "good_through"}}, "good_through"),
        ({"CTVA": {k: v for k, v in GOOD.items() if k != "since"}}, "since"),
        ({"CTVA": {**GOOD, "reason": "x"}}, "reason"),
        ({"CTVA": {**GOOD, "note": ""}}, "note"),
        ({"CTVA": {**GOOD, "note": "   "}}, "note"),
        ({"CTVA": {**GOOD, "note": "two\nlines"}}, "note"),
        ({"CTVA": {**GOOD, "note": 7}}, "note"),
        ({"CTVA": {**GOOD, "good_through": "2026-3-20"}}, "good_through"),
        ({"CTVA": {**GOOD, "good_through": "2026-02-30"}}, "good_through"),
        ({"CTVA": {**GOOD, "good_through": 20260320}}, "good_through"),
        ({"CTVA": {**GOOD, "since": "2026-11-26T00:00:00"}}, "since"),
        ({"CTVA": {**GOOD, "good_through": "2026-11-27"}}, "after"),
    ],
    ids=[
        "not-an-object",
        "not-in-universe",
        "lowercase",
        "entry-not-an-object",
        "missing-note",
        "missing-good-through",
        "missing-since",
        "unknown-key",
        "empty-note",
        "blank-note",
        "multi-line-note",
        "note-not-text",
        "date-not-iso",
        "date-not-a-day",
        "date-a-number",
        "date-a-timestamp",
        "good-through-after-since",
    ],
)
def test_a_malformed_file_is_refused_whole_with_a_named_reason(tmp_path, document, says):
    with pytest.raises(withheld_mod.WithheldError, match=says) as raised:
        _load(tmp_path, document)
    assert "withheld.json" in str(raised.value)


def test_a_symbol_listed_twice_is_refused(tmp_path):
    entry = json.dumps(GOOD)
    path = _write(tmp_path, f'{{"CTVA": {entry}, "CTVA": {entry}}}')
    with pytest.raises(withheld_mod.WithheldError, match="CTVA.*twice"):
        withheld_mod.load_withheld(path, COVERED)


def test_a_file_that_is_not_json_or_is_missing_is_refused(tmp_path):
    with pytest.raises(withheld_mod.WithheldError, match="JSON"):
        withheld_mod.load_withheld(_write(tmp_path, '{"CTVA": '), COVERED)
    with pytest.raises(withheld_mod.WithheldError, match="cannot read"):
        withheld_mod.load_withheld(tmp_path / "absent.json", COVERED)


def test_the_checked_in_file_is_valid_for_the_symbols_the_lake_sync_covers():
    covered = {symbol for symbol in load_tiers().info() if not is_tsp(symbol)}
    got = withheld_mod.load_withheld(withheld_mod.WITHHELD_FILE, covered)
    assert got["CTVA"].reason() == "price error under repair; no data since 2026-03-20"
