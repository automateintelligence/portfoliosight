"""The PortfolioSight engine: pure functions from daily returns to a tensor (spec 4, 7).

No module here performs I/O. Callers read prices and write tensors; the engine computes. How
many worker processes a build may use is the host's to say, and `portfoliosight.cpus` reads it;
the count changes how long a build takes, never what it computes.
"""

ENGINE_VERSION = "0.2.0"
