"""The PortfolioSight engine: pure functions from daily returns to a tensor (spec 4, 7).

No module here performs I/O. Callers read prices and write tensors; the engine computes.
"""

ENGINE_VERSION = "0.2.0"
