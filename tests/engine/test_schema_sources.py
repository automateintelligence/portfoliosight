"""The tensor schema accepts every manifest source a served fund can have (spec 5.2, 7)."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from portfoliosight.engine.builder import validate_tensor

FIXTURE = Path(__file__).resolve().parents[2] / "web" / "fixtures" / "guide2017_5y.json"


@pytest.mark.parametrize("source", ["seed", "tiingo", "tsp", "seed+tiingo", "lake"])
def test_every_manifest_source_validates(source):
    tensor = copy.deepcopy(json.loads(FIXTURE.read_text()))
    tensor["universe"]["funds"][0]["source"] = source
    validate_tensor(tensor)


def test_an_unknown_source_is_refused():
    tensor = copy.deepcopy(json.loads(FIXTURE.read_text()))
    tensor["universe"]["funds"][0]["source"] = "unknown"
    with pytest.raises(ValidationError):
        validate_tensor(tensor)
