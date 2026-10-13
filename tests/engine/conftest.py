"""Session fixtures for the engine tests: the fixture tensor is built once."""

from __future__ import annotations

import pandas as pd
import pytest

from portfoliosight.engine.tensor import build_tensor
from tests.engine.helpers import FIXTURE, fixture_inputs


@pytest.fixture(scope="session")
def fixture_frame() -> pd.DataFrame:
    return pd.read_parquet(FIXTURE)


@pytest.fixture(scope="session")
def fixture_tensor() -> dict:
    """The fixture tensor: the synthetic 23-fund menu, 5y, full 48 x 32 grid."""
    return build_tensor(fixture_inputs("5y"))
