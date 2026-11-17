"""Made-up inputs of the recipes check, shared by its tests: seeded, no data files.

`MENU12` has 12 holdings and 40% limits (at least 11 holdings are needed, or D10's 10% limits
cannot sum to 100%). `THREE_U` and `THREE_E` are three uncorrelated holdings with known tops.
`recorded` builds what the run would have recorded for a menu."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from portfoliosight.engine import caps, optimize
from portfoliosight.research.fixedrisk import analysis3 as A
from portfoliosight.research.fixedrisk import knee
from portfoliosight.research.fixedrisk import recipes3 as RC
from tests.research.fixedrisk.optimizer_data import synthetic_context

MENU12 = synthetic_context(funds=12, rows=400, cap=0.4, seed=7)
# Three uncorrelated holdings with limits 40% each, where the unlimited top (100% in the first
# holding, risk 0.10) sits inside the limited range (0.0726 to 0.1266): the settings 0.1023 and
# above are over the unlimited top.
THREE_U = SimpleNamespace(
    mu_s=np.array([0.10, 0.08, 0.01]),
    cov=np.diag(np.array([0.10, 0.30, 0.02]) ** 2),
    lower=np.zeros(3),
    upper=np.full(3, 0.4),
)
# Three uncorrelated holdings, limits 100%: equal weight has risk 0.1424, the top has risk 0.05.
THREE_E = SimpleNamespace(
    mu_s=np.array([0.10, 0.02, 0.01]),
    cov=np.diag(np.array([0.05, 0.30, 0.30]) ** 2),
    lower=np.zeros(3),
    upper=np.ones(3),
)
M12 = SimpleNamespace(
    mu_s=MENU12.mu_s,
    cov=MENU12.cov,
    lower=np.array(MENU12.menu.lower),
    upper=np.array(MENU12.menu.upper),
)
M12_OPEN = SimpleNamespace(mu_s=MENU12.mu_s, cov=MENU12.cov, lower=np.zeros(12), upper=np.ones(12))


def programs(m) -> optimize.MenuPrograms:
    return optimize.MenuPrograms(m.mu_s, m.cov, m.lower, m.upper)


def recorded(m) -> RC.Recorded:
    """What the run would have recorded: the ends of the limited domain, the six risks on them and
    the app's frontier mix at each (`knee.side_frontier_node`, the code that made the real rows)."""
    menu = programs(m)
    sigma_min = menu.sigma(menu.min_variance())
    sigma_top = menu.sigma(caps.greedy_fill(m.mu_s, m.lower, m.upper))
    front = optimize.frontier(menu)
    r = np.array([sigma_min + a * (sigma_top - sigma_min) for a in A.RFS])
    w = np.vstack([knee.side_frontier_node(menu, front, float(x)) for x in r])
    return RC.Recorded(r=r, sigma_min=sigma_min, sigma_top=sigma_top, w_f=w, w_app=w.copy())
