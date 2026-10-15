"""The request bodies of ``POST /v1/tensors`` and ``POST /v1/range`` and their validation
(spec 6, 4.4).

The most funds a menu may hold depends on the caller's access tier (engines spec 6.2), so the
parsers take it as ``max_funds``; the fewest is always ``MIN_FUNDS``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

from portfoliosight.api.errors import ApiError, invalid_request
from portfoliosight.engine.caps import CapsError, resolve_bounds
from portfoliosight.engine.invariants import TOL

MIN_FUNDS = 2
MAX_BODY_BYTES = 16 * 1024
FUND_ID_PATTERN = r"^[A-Z0-9][A-Z0-9.\-]{0,19}$"
GENERATION_PATTERN = r"^\d{4}-\d{2}-\d{2}-[0-9.]+$"
HASH_PATTERN = r"^[0-9a-f]{16}$"

LookbackId = Literal["1y", "2y", "3y", "5y", "10y", "ew"]
MAX_FUNDS_CONTEXT = "max_funds"


def _at_most_max_funds(items: list[Any], info: ValidationInfo) -> list[Any]:
    """Refuses a list longer than the caller's limit, as ``max_length`` would word it."""
    limit = (info.context or {}).get(MAX_FUNDS_CONTEXT)
    if not isinstance(limit, int):
        raise RuntimeError(f"validation needs the caller's {MAX_FUNDS_CONTEXT} in its context")
    if len(items) > limit:
        raise PydanticCustomError(
            "too_long",
            "List should have at most {max_length} items after validation, not {actual_length}",
            {"field_type": "List", "max_length": limit, "actual_length": len(items)},
        )
    return items


class FundPolicy(BaseModel):
    """One fund of the menu; ``None`` for a bound means the default rule."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=FUND_ID_PATTERN)
    min: float | None = Field(default=None, allow_inf_nan=False)
    max: float | None = Field(default=None, allow_inf_nan=False)


class TensorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    funds: list[FundPolicy] = Field(min_length=MIN_FUNDS)
    lookback: LookbackId

    _funds_limit = field_validator("funds")(_at_most_max_funds)

    def policy(self) -> list[dict[str, Any]]:
        """The requested policy as the hash and the builder take it."""
        return [{"id": fund.id, "min": fund.min, "max": fund.max} for fund in self.funds]


# A weight is in [0, 1] within the tolerance of spec 4.11: a mix the page interpolates between
# solved mixes can sit a rounding error outside, and is sent as it is.
Weight = Annotated[float, Field(ge=-TOL, le=1.0 + TOL, allow_inf_nan=False)]


class RangeRequest(BaseModel):
    """A mix on a built menu: one weight per fund of the tensor, in the tensor's fund order."""

    model_config = ConfigDict(extra="forbid", strict=True)

    generation: str = Field(pattern=GENERATION_PATTERN)
    hash: str = Field(pattern=HASH_PATTERN)
    lookback: LookbackId
    weights: list[Weight] = Field(min_length=MIN_FUNDS)

    _weights_limit = field_validator("weights")(_at_most_max_funds)


def _shape_error(exc: ValidationError) -> ApiError:
    """A 422 naming where the body is wrong and why; the body itself is never echoed."""
    problems = [
        {"where": ".".join(str(part) for part in error["loc"]), "problem": error["msg"]}
        for error in exc.errors(include_input=False, include_url=False, include_context=False)
    ]
    return invalid_request("The request is not valid.", problems)


def parse_range_request(body: bytes, *, max_funds: int) -> RangeRequest:
    """The validated request, or a 422 ``invalid_request`` saying what is wrong.

    Checks the shape only: a generation and a hash of the right form, a known lookback, and 2
    to ``max_funds`` weights, each a number in ``[0, 1]`` within 1e-6. Whether they add up to
    1, and whether there is one per fund of the menu, is checked by ``ranges.range_body``.
    """
    try:
        return RangeRequest.model_validate_json(body, context={MAX_FUNDS_CONTEXT: max_funds})
    except ValidationError as exc:
        raise _shape_error(exc) from None


def parse_tensor_request(body: bytes, *, max_funds: int) -> TensorRequest:
    """The validated request, or a 422 ``invalid_request`` saying what is wrong.

    Checks the shape (2 to ``max_funds`` funds, uppercase ids, a known lookback), that no fund
    is listed twice, and the cap rules of spec 4.4 for the menu as requested. The error names
    the fund or the sum at fault and never echoes the body.
    """
    try:
        request = TensorRequest.model_validate_json(body, context={MAX_FUNDS_CONTEXT: max_funds})
    except ValidationError as exc:
        raise _shape_error(exc) from None
    ids = [fund.id for fund in request.funds]
    repeated = sorted({fund for fund in ids if ids.count(fund) > 1})
    if repeated:
        raise invalid_request(f"{', '.join(repeated)}: listed more than once in the menu")
    try:
        resolve_bounds(ids, request.policy())
    except CapsError as exc:
        raise invalid_request(str(exc)) from None
    return request


def payload_too_large() -> ApiError:
    return ApiError(413, "payload_too_large", f"The request body exceeds {MAX_BODY_BYTES} bytes.")
