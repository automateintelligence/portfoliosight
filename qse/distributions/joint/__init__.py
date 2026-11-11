"""Joint (multi-asset) return simulation: panel GARCH fits and filtered historical simulation."""

from qse.distributions.joint.fhs import (
    MIN_POOL_ROWS,
    ShockSource,
    draw_row_indices,
    residual_pool,
    row_bootstrap_shock_source,
    simulate_fhs_panel,
)
from qse.distributions.joint.panel_fit import (
    MIN_GARCH_HISTORY,
    NEAR_CONSTANT_DAILY_VOL,
    PERSISTENCE_TOL,
    ZERO_VOL_FLOOR,
    GarchPanelFit,
    PanelStatus,
    fit_garch_t_panel,
)
from qse.distributions.joint.portfolio import (
    DEFAULT_CHUNK_BYTES,
    RuinPolicy,
    compound_horizon_returns,
    constant_mix_daily_returns,
    constant_mix_horizon_returns,
    rescale_to_targets,
    rescaled_horizon_returns,
)

__all__ = [
    "DEFAULT_CHUNK_BYTES",
    "MIN_GARCH_HISTORY",
    "MIN_POOL_ROWS",
    "NEAR_CONSTANT_DAILY_VOL",
    "PERSISTENCE_TOL",
    "ZERO_VOL_FLOOR",
    "GarchPanelFit",
    "PanelStatus",
    "RuinPolicy",
    "ShockSource",
    "compound_horizon_returns",
    "constant_mix_daily_returns",
    "constant_mix_horizon_returns",
    "draw_row_indices",
    "fit_garch_t_panel",
    "rescale_to_targets",
    "rescaled_horizon_returns",
    "residual_pool",
    "row_bootstrap_shock_source",
    "simulate_fhs_panel",
]
