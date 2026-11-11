"""The engine's public face: building a tensor and the checks around one (spec 4, 7)."""

from .builder import (
    BuildResult,
    FundInput,
    TensorInputs,
    WindowUnavailable,
    build_tensor,
    build_tensor_full,
    canonical_json,
    load_schema,
    shape_panel_for,
    universe_hash,
    validate_tensor,
)
from .invariants import InvariantError, check_floor, check_risk_line, check_weights
from .shape import ShapeError
from .windows import WindowSelection, renormalize_allocation, select_window

__all__ = [
    "BuildResult",
    "FundInput",
    "InvariantError",
    "ShapeError",
    "TensorInputs",
    "WindowSelection",
    "WindowUnavailable",
    "build_tensor",
    "build_tensor_full",
    "canonical_json",
    "check_floor",
    "check_risk_line",
    "check_weights",
    "load_schema",
    "renormalize_allocation",
    "select_window",
    "shape_panel_for",
    "universe_hash",
    "validate_tensor",
]
