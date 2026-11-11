"""Shared models for distribution audit (US6a)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FitResult:
    model_name: str
    log_likelihood: float
    aic: float
    bic: float
    params: dict[str, float]
    n: int
    converged: bool
    heavy_tailed: bool | None = None
    fit_success: bool = True
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    fit_message: str | None = None


__all__ = ["FitResult"]
