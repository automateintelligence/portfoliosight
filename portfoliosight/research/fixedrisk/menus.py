"""The two research menus of the fixed-risk experiment (protocol §3a).

`research2003`: eleven funds (cap 40% each) and the eight US companies of the 2004 global top ten
(cap 10% each), 19 holdings. `tsp`: the five TSP funds in v1's order (cap 60% each).
"""

from __future__ import annotations

from portfoliosight.research.fixedrisk.contracts import MenuSpec

FUNDS_2003 = ("SPY", "IWM", "IWD", "EFA", "EEM", "IYR", "TLT", "IEF", "SHY", "LQD", "VIPSX")
STOCKS_2003 = ("GE", "MSFT", "XOM", "PFE", "C", "WMT", "AIG", "INTC")
TSP_FUNDS = ("TSP-G", "TSP-F", "TSP-C", "TSP-S", "TSP-I")
FUND_CAP = 0.40
STOCK_CAP = 0.10
TSP_CAP = 0.60
RISK_FREE_SYMBOLS = ("SGOV",)  # the v1 rule also reads TSP-G, which is a TSP holding

RESEARCH2003 = MenuSpec(
    name="research2003",
    holdings=(*FUNDS_2003, *STOCKS_2003),
    lower=(0.0,) * (len(FUNDS_2003) + len(STOCKS_2003)),
    upper=(FUND_CAP,) * len(FUNDS_2003) + (STOCK_CAP,) * len(STOCKS_2003),
)
TSP = MenuSpec(
    name="tsp",
    holdings=TSP_FUNDS,
    lower=(0.0,) * len(TSP_FUNDS),
    upper=(TSP_CAP,) * len(TSP_FUNDS),
)
MENUS: tuple[MenuSpec, ...] = (RESEARCH2003, TSP)
MENU_BY_NAME = {menu.name: menu for menu in MENUS}
ALL_SYMBOLS = tuple(dict.fromkeys([h for m in MENUS for h in m.holdings] + list(RISK_FREE_SYMBOLS)))


def menu_named(name: str) -> MenuSpec:
    try:
        return MENU_BY_NAME[name]
    except KeyError:
        raise ValueError(f"unknown menu {name!r}; expected one of {sorted(MENU_BY_NAME)}") from None
