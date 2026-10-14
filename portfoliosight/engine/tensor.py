"""The engine's public face: building a tensor and the checks around one (spec 4, 7)."""

from .builder import (
    FundInput,
    TensorInputs,
    WindowUnavailable,
    build_tensor,
    canonical_json,
    load_schema,
    universe_hash,
    validate_tensor,
)
from .invariants import InvariantError, check_floor, check_risk_line, check_weights
from .windows import WindowSelection, renormalize_allocation, select_window

__all__ = [
    "FundInput",
    "InvariantError",
    "TensorInputs",
    "WindowSelection",
    "WindowUnavailable",
    "build_tensor",
    "canonical_json",
    "check_floor",
    "check_risk_line",
    "check_weights",
    "load_schema",
    "renormalize_allocation",
    "select_window",
    "universe_hash",
    "validate_tensor",
]
