"""The request body of ``POST /v1/tensors`` and its validation (spec 6, 4.4)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from portfoliosight.api.errors import ApiError, invalid_request
from portfoliosight.engine.caps import CapsError, resolve_bounds

MIN_FUNDS = 2
MAX_FUNDS = 30
MAX_BODY_BYTES = 16 * 1024
FUND_ID_PATTERN = r"^[A-Z0-9][A-Z0-9.\-]{0,19}$"
GENERATION_PATTERN = r"^\d{4}-\d{2}-\d{2}-[0-9.]+$"
HASH_PATTERN = r"^[0-9a-f]{16}$"

LookbackId = Literal["1y", "2y", "3y", "5y", "10y", "ew"]


class FundPolicy(BaseModel):
    """One fund of the menu; ``None`` for a bound means the default rule."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=FUND_ID_PATTERN)
    min: float | None = Field(default=None, allow_inf_nan=False)
    max: float | None = Field(default=None, allow_inf_nan=False)


class TensorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    funds: list[FundPolicy] = Field(min_length=MIN_FUNDS, max_length=MAX_FUNDS)
    lookback: LookbackId

    def policy(self) -> list[dict[str, Any]]:
        """The requested policy as the hash and the builder take it."""
        return [{"id": fund.id, "min": fund.min, "max": fund.max} for fund in self.funds]


def parse_tensor_request(body: bytes) -> TensorRequest:
    """The validated request, or a 422 ``invalid_request`` saying what is wrong.

    Checks the shape (2 to 30 funds, uppercase ids, a known lookback), that no fund is listed
    twice, and the cap rules of spec 4.4 for the menu as requested. The error names the fund
    or the sum at fault and never echoes the body.
    """
    try:
        request = TensorRequest.model_validate_json(body)
    except ValidationError as exc:
        problems = [
            {"where": ".".join(str(part) for part in error["loc"]), "problem": error["msg"]}
            for error in exc.errors(include_input=False, include_url=False, include_context=False)
        ]
        raise invalid_request("The request is not valid.", problems) from None
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
