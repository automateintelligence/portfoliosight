"""The rolling-origin harness: the origins ledger and its evidence gate (protocol 4 and 8).

`build_ledger` is pure: from the price records, the XNYS session list, D*, the menus and a
lookback it decides, for every month, whether the month is a training-eligible origin, whether it
is administratively mature and whether its realized horizon is complete in each menu, with a
named reason for everything it excludes. Nothing is filled in, backdated or dropped, and no menu
shrinks to a subset of its funds. `coverage` reads a ledger and reports the protocol 4 evidence
gate; `read_snapshot` loads the inputs from a frozen research snapshot after verifying it.

Months. One row per month from the boundary month, the month that contains the latest first
price among the fixed-menu funds (the funds of every menu passed), through the last month whose
calendar month-end is on or before D*. Earlier months are structurally ineligible for the full
fixed menu: the ledger records that once, as the boundary month, the fund that sets it, its first
price date and the reason `prehistory_full_fixed_menu_unavailable` (`Ledger.boundary`), not as
rows. A month's origin is its last XNYS session.

Status of a month, the first that applies:
  origin_price_missing       a fixed-menu fund has no finite, positive total-return value at the
                             origin (a coverage failure, listed by fund and date)
  training_ineligible        some menu fails its training window (reasons on that menu)
  administratively_immature  training-eligible, and the 252nd XNYS session after the origin is
                             after D*: scheduled, but outside the realized denominator
  mature                     training-eligible and administratively mature: the realized
                             denominator

Training window of a menu. Its returns are built with the production `build_returns` from the
records dated on or before the origin; the window is the production `select_window` window (the
last `LOOKBACK_ROWS[lookback]` union-calendar rows ending at the origin, 1,260 for `5y`) and its
complete-case rows over every menu fund. A menu is training-eligible when the union calendar has
at least the window's rows on or before the origin, every fund has a price dated on or before the
window's first date (no 10% inception slack; checked only once the union calendar is long
enough, since a short calendar is already named as the cause), and the window has complete rows
for at least 90% of its length, rounded up (1,134 of 1,260).

Realized horizon of a menu, for administratively mature months: the next 252 dates of the menu's
frozen union price calendar (every record date of its funds) after the origin. It is complete when
all 252 dates exist, the last is on or before D*, and every fund has a finite, positive
total-return value on the origin (the predecessor price) and on each of them; no value dated
after D* is consulted. Otherwise the outcome is `mature_horizon_missing`, with the reason, and per
fund the first date and count of its gaps. Horizons are evaluated for every mature month,
whatever its status, so that the per-menu facts of training-ineligible months stay descriptive;
only `mature` months enter the realized denominator.

Disjoint intervals of a menu are chosen greedily in origin order among the `mature` months whose
outcome is complete in that menu: an origin is retained only when it is strictly later than the
previously retained horizon end. `overlap_prev_dates` counts the horizon dates a panel origin
shares with the previous panel origin's horizon, `overlap_origins` the other panel origins whose
horizons share a date with its own.

Risk-free source at an origin: SGOV when its records up to the origin give 252 own-date returns,
else TSP-G, else the production fallback (`risk_free_rate`), recorded with its value.

`ledger_frame` schema, one row per (month, menu):
  lookback, origins (monthly | quarter-end | year-end), month (YYYY-MM), origin, status,
  training_eligible, realized_denominator, maturity_session (NaT when beyond the session list),
  mature, risk_free_source (SGOV | TSP-G | fallback), risk_free_rate, month_issues (JSON),
  menu, funds (comma-joined, fixed order), origin_priced, union_rows, window_start, window_rows,
  complete_rows, menu_training_eligible, outcome (complete | mature_horizon_missing |
  administratively_immature), horizon_start, horizon_end (NaT unless 252 dates exist),
  horizon_rows, disjoint, overlap_prev_dates, overlap_origins (null outside the panel),
  menu_issues (JSON). An issue is {"code", "fund", "date", "note"}.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from portfoliosight.data.returns import build_returns, window_sample
from portfoliosight.engine.stats import RISK_FREE_SOURCES, TRADING_DAYS, risk_free_rate
from portfoliosight.engine.windows import LOOKBACK_ROWS, select_window

HORIZON_ROWS = TRADING_DAYS  # the production trading-day convention, not 252 XNYS sessions
MATURITY_SESSIONS = TRADING_DAYS
COMPLETE_SHARE = (9, 10)  # complete rows needed, as a share of the window's length
FALLBACK_SOURCE = "fallback"
DAY = timedelta(days=1)

# Why the months before the boundary month are not in the ledger (recorded once, not per month).
PREHISTORY = "prehistory_full_fixed_menu_unavailable"
# Month statuses.
ORIGIN_PRICE_MISSING = "origin_price_missing"
TRAINING_INELIGIBLE = "training_ineligible"
IMMATURE = "administratively_immature"
MATURE = "mature"
STATUSES = (ORIGIN_PRICE_MISSING, TRAINING_INELIGIBLE, IMMATURE, MATURE)
# Menu outcomes (and IMMATURE).
COMPLETE = "complete"
HORIZON_MISSING = "mature_horizon_missing"
# Issue codes on a menu.
UNION_ROWS_SHORT = "training_union_rows_short"
FUND_AFTER_START = "training_fund_after_window_start"
COMPLETE_ROWS_SHORT = "training_complete_rows_short"
PREDECESSOR_MISSING = "horizon_predecessor_missing"
HORIZON_DATES_SHORT = "horizon_union_dates_short"
HORIZON_PAST_D_STAR = "horizon_past_d_star"
HORIZON_VALUE_MISSING = "horizon_value_missing"

ORIGIN_KINDS = ("monthly", "quarter-end", "year-end")
_KIND_MONTHS = {"quarter-end": (3, 6, 9, 12), "year-end": (12,)}
# Spec 10: the 40 quarter-end origins 2015-12-31 .. 2025-09-30 and the ten year-ends to 2024.
VALIDATION_MONTHS = {"quarter-end": ("2015-12", "2025-09"), "year-end": ("2015-12", "2024-12")}

# Protocol 4: the minimum evidence gate and the panel size that stops for a resource amendment.
MIN_MATURE_ORIGINS = 60
MIN_COMPLETE_PERCENT = 95
MIN_DISJOINT_INTERVALS = 5
MAX_SCHEDULED_ORIGINS = 120


@dataclass(frozen=True)
class Issue:
    """One named reason: a code, and the fund and date it concerns when there is one."""

    code: str
    fund: str | None = None
    day: date | None = None
    note: str = ""


@dataclass(frozen=True)
class MenuOrigin:
    """One menu at one origin: its training window and its realized horizon."""

    menu: str
    origin_priced: bool  # every fund has a finite, positive total-return value at the origin
    union_rows: int  # union-calendar rows on or before the origin
    window_start: date | None
    window_rows: int  # union-calendar rows in the window
    complete_rows: int  # complete-case rows of the window over every menu fund
    training_eligible: bool
    outcome: str  # COMPLETE | HORIZON_MISSING | IMMATURE
    horizon_start: date | None
    horizon_end: date | None  # the 252nd union date, None when there are fewer
    horizon_rows: int  # union dates after the origin, at most 252
    issues: tuple[Issue, ...]
    disjoint: bool = False
    overlap_prev_dates: int | None = None
    overlap_origins: int | None = None


@dataclass(frozen=True)
class OriginRow:
    """One month of the ledger."""

    month: str  # YYYY-MM
    origin: date
    status: str
    maturity_session: date | None  # the 252nd XNYS session after the origin
    mature: bool
    risk_free_source: str
    risk_free_rate: float
    issues: tuple[Issue, ...]  # the month's own reasons: missing origin prices
    menus: tuple[MenuOrigin, ...]

    @property
    def training_eligible(self) -> bool:
        return self.status in (IMMATURE, MATURE)

    @property
    def in_realized_panel(self) -> bool:
        return self.status == MATURE

    def menu(self, name: str) -> MenuOrigin:
        for entry in self.menus:
            if entry.menu == name:
                return entry
        raise KeyError(name)


@dataclass(frozen=True)
class Ledger:
    """Every month with its status, for one lookback; `origins` names the subset it holds."""

    d_star: date
    lookback: str
    window_rows: int
    menus: tuple[tuple[str, tuple[str, ...]], ...]
    boundary_month: str  # the first month: it holds the latest first price of a fixed-menu fund
    boundary_fund: str  # the fund with that price
    boundary_date: date  # its first price date
    origins: str
    rows: tuple[OriginRow, ...]
    calendars: dict[str, pd.DatetimeIndex] = field(default_factory=dict, repr=False, compare=False)

    @property
    def boundary(self) -> Issue:
        """Why no month before ``boundary_month`` is in the ledger, recorded once."""
        return Issue(
            PREHISTORY,
            self.boundary_fund,
            self.boundary_date,
            f"{self.boundary_fund} is the last fixed-menu fund to start ({self.boundary_date}); "
            f"the months before {self.boundary_month} are structurally ineligible",
        )

    def row(self, month: str) -> OriginRow:
        for row in self.rows:
            if row.month == month:
                return row
        raise KeyError(month)


@dataclass(frozen=True)
class Gate:
    name: str
    value: int | float | None
    rule: str
    met: bool | None  # None: the gate is defined on the monthly ledger only


@dataclass(frozen=True)
class MenuCoverage:
    menu: str
    complete: int  # mature months whose horizon is complete in this menu
    missing: int  # mature months whose horizon is not
    unexplained: int  # missing outcomes without a named reason
    disjoint: int


@dataclass(frozen=True)
class Coverage:
    """The protocol 4 evidence-gate numbers of one ledger."""

    lookback: str
    origins: str
    d_star: date
    fixed_menu: tuple[str, ...]
    boundary_month: str
    boundary_fund: str
    boundary_date: date
    boundary_reason: str  # PREHISTORY: why earlier months are not in the ledger
    months: int
    counts: dict[str, int]
    scheduled: int  # common training-eligible origins, immature ones included
    mature: int  # the realized denominator
    menus: tuple[MenuCoverage, ...]
    gates: tuple[Gate, ...]
    met: bool | None

    def menu(self, name: str) -> MenuCoverage:
        for entry in self.menus:
            if entry.menu == name:
                return entry
        raise KeyError(name)

    def gate(self, name: str) -> Gate:
        for entry in self.gates:
            if entry.name == name:
                return entry
        raise KeyError(name)


# ------------------------------------------------------------------------------------ ledger


@dataclass(frozen=True)
class _MenuPrices:
    """A menu's frozen union price calendar and, per date and fund, a usable total-return value."""

    funds: tuple[str, ...]
    calendar: pd.DatetimeIndex
    valid: np.ndarray  # (dates, funds) bool

    @classmethod
    def of(cls, funds: tuple[str, ...], records: Mapping[str, pd.DataFrame]) -> _MenuPrices:
        calendar = pd.DatetimeIndex(build_returns({fund: records[fund] for fund in funds}).index)
        valid = np.empty((len(calendar), len(funds)), dtype=bool)
        for column, fund in enumerate(funds):
            record = records[fund]
            values = pd.Series(
                record["tr_index"].to_numpy(dtype=float), index=pd.DatetimeIndex(record["date"])
            ).reindex(calendar)
            tr = values.to_numpy(dtype=float)
            valid[:, column] = np.isfinite(tr) & (tr > 0)
        return cls(funds, calendar, valid)

    def at(self, stamp: pd.Timestamp) -> np.ndarray:
        """Usable values at ``stamp``: all False when no fund has a record row that day."""
        position = _position(self.calendar, stamp)
        if position < len(self.calendar) and to_stamp(self.calendar[position]) == stamp:
            return self.valid[position]
        return np.zeros(len(self.funds), dtype=bool)


def to_stamp(day: Any) -> pd.Timestamp:
    """A date as a midnight Timestamp; NaT or a non-date is an error."""
    stamp = pd.Timestamp(day)
    if not isinstance(stamp, pd.Timestamp):
        raise ValueError(f"{day!r} is not a date")
    return stamp.normalize()


def _position(
    index: pd.DatetimeIndex, stamp: pd.Timestamp, side: Literal["left", "right"] = "left"
) -> int:
    """Where ``stamp`` sorts in ``index`` (``side`` as in ``searchsorted``)."""
    return int(index.searchsorted(stamp.to_datetime64(), side=side))


def _month(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _months(first: str, last: str) -> list[str]:
    """Every YYYY-MM month from ``first`` through ``last``."""
    year, month, months = int(first[:4]), int(first[5:]), []
    while f"{year:04d}-{month:02d}" <= last:
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def build_ledger(
    records: Mapping[str, pd.DataFrame],
    sessions: Iterable[Any],
    d_star: date,
    menus: Mapping[str, Sequence[str]],
    lookback: str = "5y",
) -> Ledger:
    """The origins ledger of protocol 4 for one lookback; see the module docstring.

    ``records`` maps a symbol to its canonical price record (``date`` and ``tr_index`` at least,
    dates strictly increasing) and holds every menu fund, plus SGOV and TSP-G when available for
    the risk-free rate. ``sessions`` are the XNYS sessions; they must reach past D*.
    """
    if lookback not in LOOKBACK_ROWS:
        raise ValueError(f"unknown lookback {lookback!r}; expected one of {list(LOOKBACK_ROWS)}")
    menu_items = _menu_items(menus, records)
    fixed = list(dict.fromkeys(fund for _, funds in menu_items for fund in funds))
    used = [*fixed, *(symbol for symbol in RISK_FREE_SOURCES if symbol in records)]
    dates = {symbol: record_dates(symbol, records[symbol]) for symbol in dict.fromkeys(used)}
    calendar = _session_index(sessions)
    d_stamp = to_stamp(d_star)

    first = {fund: to_stamp(dates[fund][0]).date() for fund in fixed}
    latest = max(first.values())
    boundary_fund = next(fund for fund in fixed if first[fund] == latest)
    boundary = _month(latest)
    after_d_star = d_star + timedelta(days=1)
    last = _month(d_star if after_d_star.month != d_star.month else d_star.replace(day=1) - DAY)
    month_ends = {_month(stamp.date()): stamp for stamp in map(to_stamp, calendar)}
    prices = {name: _MenuPrices.of(funds, records) for name, funds in menu_items}

    rows = []
    for month in _months(boundary, last):
        if month not in month_ends:
            raise ValueError(f"the XNYS session list has no session in {month}")
        stamp = month_ends[month]
        maturity = _maturity(calendar, stamp, d_stamp)
        mature = maturity is not None and maturity <= d_stamp
        source, rate = risk_free_at(records, dates, stamp)
        entries, unpriced = [], []
        for name, funds in menu_items:
            entries.append(
                _menu_origin(
                    name, funds, records, dates, prices[name], stamp, lookback, mature, d_stamp
                )
            )
            priced = prices[name].at(stamp)
            unpriced += [fund for fund, ok in zip(funds, priced, strict=True) if not ok]
        if unpriced:
            status = ORIGIN_PRICE_MISSING
            issues = tuple(
                Issue(ORIGIN_PRICE_MISSING, fund, stamp.date(), "no total-return value")
                for fund in dict.fromkeys(unpriced)
            )
        elif not all(entry.training_eligible for entry in entries):
            status, issues = TRAINING_INELIGIBLE, ()
        else:
            status, issues = (MATURE if mature else IMMATURE), ()
        rows.append(
            OriginRow(
                month=month,
                origin=stamp.date(),
                status=status,
                maturity_session=None if maturity is None else maturity.date(),
                mature=mature,
                risk_free_source=source,
                risk_free_rate=rate,
                issues=issues,
                menus=tuple(entries),
            )
        )

    calendars = {name: prices[name].calendar for name, _ in menu_items}
    return Ledger(
        d_star=d_star,
        lookback=lookback,
        window_rows=LOOKBACK_ROWS[lookback],
        menus=menu_items,
        boundary_month=boundary,
        boundary_fund=boundary_fund,
        boundary_date=latest,
        origins="monthly",
        rows=_assign_intervals(rows, calendars),
        calendars=calendars,
    )


def _menu_items(
    menus: Mapping[str, Sequence[str]], records: Mapping[str, pd.DataFrame]
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if not menus:
        raise ValueError("at least one menu is needed")
    items = []
    for name, funds in menus.items():
        funds = tuple(funds)
        if not funds or len(set(funds)) != len(funds):
            raise ValueError(f"menu {name!r} must list its funds once each: {funds}")
        absent = [fund for fund in funds if fund not in records]
        if absent:
            raise ValueError(f"menu {name!r}: no price record for {', '.join(absent)}")
        items.append((name, funds))
    return tuple(items)


def record_dates(symbol: str, record: pd.DataFrame) -> pd.DatetimeIndex:
    """A price record's dates, checked: ``date`` and ``tr_index`` present, dates strictly rising."""
    missing = {"date", "tr_index"} - set(record.columns)
    if missing:
        raise ValueError(f"{symbol}: the price record lacks {sorted(missing)}")
    dates = pd.DatetimeIndex(record["date"])
    if len(dates) == 0:
        raise ValueError(f"{symbol}: the price record has no rows")
    if dates.hasnans or not (dates.is_monotonic_increasing and dates.is_unique):
        raise ValueError(f"{symbol}: price record dates must be set and strictly increasing")
    return dates


def _session_index(sessions: Iterable[Any]) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex([to_stamp(session) for session in sessions])
    if len(index) == 0 or not (index.is_monotonic_increasing and index.is_unique):
        raise ValueError("the XNYS sessions must be a non-empty, strictly increasing list")
    return index


def rows_through(
    record: pd.DataFrame, dates: pd.DatetimeIndex, stamp: pd.Timestamp
) -> pd.DataFrame:
    """The record's rows dated on or before ``stamp``."""
    return record.iloc[: _position(dates, stamp, "right")]


def _maturity(
    calendar: pd.DatetimeIndex, stamp: pd.Timestamp, d_stamp: pd.Timestamp
) -> pd.Timestamp | None:
    """The 252nd session strictly after the origin; None when it lies beyond the list's end."""
    target = _position(calendar, stamp, "right") + MATURITY_SESSIONS - 1
    if target < len(calendar):
        return to_stamp(calendar[target])
    final = to_stamp(calendar[-1])
    if final > d_stamp:
        return None  # beyond a list that already passes D*: certainly after D*
    raise ValueError(
        f"the XNYS session list ends {final.date()}, not after D* {d_stamp.date()}: "
        f"the maturity of {stamp.date()} cannot be decided"
    )


def risk_free_at(
    records: Mapping[str, pd.DataFrame],
    dates: Mapping[str, pd.DatetimeIndex],
    stamp: pd.Timestamp,
) -> tuple[str, float]:
    """The production risk-free rate at an origin and the source it came from."""
    series = {}
    for symbol in RISK_FREE_SOURCES:
        if symbol in records:
            own = rows_through(records[symbol], dates[symbol], stamp)
            series[symbol] = build_returns({symbol: own})[symbol]
    # The source is the first one `risk_free_rate` accepts: TRADING_DAYS returns that are set.
    source = next(
        (s for s in RISK_FREE_SOURCES if s in series and series[s].notna().sum() >= TRADING_DAYS),
        FALLBACK_SOURCE,
    )
    return source, risk_free_rate(series)


def _menu_origin(
    name: str,
    funds: tuple[str, ...],
    records: Mapping[str, pd.DataFrame],
    dates: Mapping[str, pd.DatetimeIndex],
    prices: _MenuPrices,
    stamp: pd.Timestamp,
    lookback: str,
    mature: bool,
    d_stamp: pd.Timestamp,
) -> MenuOrigin:
    origin = stamp.date()
    truncated = {fund: rows_through(records[fund], dates[fund], stamp) for fund in funds}
    returns = build_returns(truncated)
    length = LOOKBACK_ROWS[lookback]
    window_start = select_window(returns, lookback, origin).start
    union_rows = len(returns)
    complete = 0
    if window_start is not None:
        complete = len(window_sample(returns, list(funds), window_start, origin))
    needed = -(-length * COMPLETE_SHARE[0] // COMPLETE_SHARE[1])

    issues: list[Issue] = []
    if union_rows < length:
        note = f"{union_rows} union-calendar rows on or before the origin, {length} needed"
        issues.append(Issue(UNION_ROWS_SHORT, note=note))
    elif window_start is not None:  # every fund must have a price on or before the first date
        for fund in funds:
            record = truncated[fund]
            if record.empty:
                note = "no price on or before the origin"
                issues.append(Issue(FUND_AFTER_START, fund, None, note))
                continue
            day = to_stamp(record["date"].iloc[0]).date()
            if day > window_start:
                note = f"first price {day}, after the window's first date {window_start}"
                issues.append(Issue(FUND_AFTER_START, fund, day, note))
    if complete < needed:
        note = f"{complete} complete rows in the window, {needed} needed"
        issues.append(Issue(COMPLETE_ROWS_SHORT, note=note))
    training_eligible = not issues

    priced = prices.at(stamp)
    horizon_start: date | None = None
    horizon_end: date | None = None
    horizon_rows = 0
    if mature:
        horizon, horizon_issues = _horizon(prices, stamp, priced, d_stamp)
        issues += horizon_issues
        outcome = HORIZON_MISSING if horizon_issues else COMPLETE
        horizon_rows = len(horizon)
        if horizon_rows:
            horizon_start = to_stamp(horizon[0]).date()
        if horizon_rows == HORIZON_ROWS:
            horizon_end = to_stamp(horizon[-1]).date()
    else:
        outcome = IMMATURE
    return MenuOrigin(
        menu=name,
        origin_priced=bool(priced.all()),
        union_rows=union_rows,
        window_start=window_start,
        window_rows=min(length, union_rows),
        complete_rows=complete,
        training_eligible=training_eligible,
        outcome=outcome,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        horizon_rows=horizon_rows,
        issues=tuple(issues),
    )


def _horizon(
    prices: _MenuPrices, stamp: pd.Timestamp, priced: np.ndarray, d_stamp: pd.Timestamp
) -> tuple[pd.DatetimeIndex, list[Issue]]:
    """The next 252 union dates after the origin and every reason the outcome is incomplete.

    No value dated after D* is consulted; each fund's gaps are reported once, with the first
    date and the count of horizon dates it lacks.
    """
    origin = stamp.date()
    after = _position(prices.calendar, stamp, "right")
    horizon = pd.DatetimeIndex(prices.calendar[after : after + HORIZON_ROWS])
    issues = [
        Issue(PREDECESSOR_MISSING, fund, origin, "no total-return value at the origin")
        for fund, ok in zip(prices.funds, priced, strict=True)
        if not ok
    ]
    if len(horizon) < HORIZON_ROWS:
        note = f"{len(horizon)} union dates after the origin, {HORIZON_ROWS} needed"
        issues.append(Issue(HORIZON_DATES_SHORT, note=note))
    elif to_stamp(horizon[-1]) > d_stamp:
        day = to_stamp(horizon[-1]).date()
        note = f"the {HORIZON_ROWS}th union date {day} is after D* {d_stamp.date()}"
        issues.append(Issue(HORIZON_PAST_D_STAR, None, day, note))
    readable = np.asarray(horizon <= d_stamp)
    block = prices.valid[after : after + len(horizon)]
    for column, fund in enumerate(prices.funds):
        gaps = [to_stamp(day).date() for day in horizon[readable & ~block[:, column]]]
        if gaps:
            note = (
                f"{len(gaps)} horizon date(s) without a total-return value, "
                f"{gaps[0]} through {gaps[-1]}"
            )
            issues.append(Issue(HORIZON_VALUE_MISSING, fund, gaps[0], note))
    return horizon, issues


def _assign_intervals(
    rows: Sequence[OriginRow], calendars: Mapping[str, pd.DatetimeIndex]
) -> tuple[OriginRow, ...]:
    """Greedy disjoint membership and exact overlaps, per menu, among the rows given."""
    if not rows:
        return ()
    updated = [list(row.menus) for row in rows]
    for k, name in enumerate(entry.menu for entry in rows[0].menus):
        calendar = calendars[name]
        panel = [
            i
            for i, row in enumerate(rows)
            if row.status == MATURE and row.menus[k].outcome == COMPLETE
        ]
        spans = []
        for i in panel:
            entry = rows[i].menus[k]  # complete, so both horizon ends are set
            first = _position(calendar, to_stamp(entry.horizon_start))
            last = _position(calendar, to_stamp(entry.horizon_end))
            spans.append((first, last))
        retained_end: date | None = None
        for j, i in enumerate(panel):
            entry = rows[i].menus[k]
            member = retained_end is None or rows[i].origin > retained_end
            if member:
                retained_end = entry.horizon_end
            first, last = spans[j]
            previous = 0
            if j:
                shared = min(last, spans[j - 1][1]) - max(first, spans[j - 1][0]) + 1
                previous = max(shared, 0)
            overlapping = sum(
                1 for h, (a, b) in enumerate(spans) if h != j and a <= last and first <= b
            )
            updated[i][k] = replace(
                entry, disjoint=member, overlap_prev_dates=previous, overlap_origins=overlapping
            )
        members = set(panel)
        for i, row in enumerate(rows):
            if i not in members:
                updated[i][k] = replace(
                    row.menus[k], disjoint=False, overlap_prev_dates=None, overlap_origins=None
                )
    return tuple(
        replace(row, menus=tuple(entries)) for row, entries in zip(rows, updated, strict=True)
    )


# ----------------------------------------------------------------------------------- subsets


def select_origins(
    ledger: Ledger, kind: str, first: str | None = None, last: str | None = None
) -> Ledger:
    """The months of ``kind`` (monthly, quarter-end, year-end) of a monthly ledger.

    ``first`` and ``last`` (YYYY-MM, inclusive) must be months the ledger holds. Disjoint
    membership and overlaps are recomputed among the rows kept.
    """
    if kind not in ORIGIN_KINDS:
        raise ValueError(f"unknown origins {kind!r}; expected one of {list(ORIGIN_KINDS)}")
    if ledger.origins != "monthly":
        raise ValueError(f"origins are derived from the monthly ledger, not a {ledger.origins} one")
    held = [row.month for row in ledger.rows]
    absent = [month for month in (first, last) if month is not None and month not in held]
    if absent:
        span = f"{held[0]} through {held[-1]}" if held else "no month"
        raise ValueError(f"the ledger holds {span}, not {', '.join(absent)}")
    wanted = _KIND_MONTHS.get(kind)
    kept = [
        row
        for row in ledger.rows
        if (wanted is None or int(row.month[5:]) in wanted)
        and (first is None or row.month >= first)
        and (last is None or row.month <= last)
    ]
    return replace(ledger, origins=kind, rows=_assign_intervals(kept, ledger.calendars))


def validation_origins(ledger: Ledger, kind: str) -> Ledger:
    """The spec 10 origins of ``kind``: the 40 quarter-ends or the ten year-ends, or every month."""
    if kind == "monthly":
        return select_origins(ledger, kind)
    if kind not in VALIDATION_MONTHS:
        raise ValueError(f"unknown origins {kind!r}; expected one of {list(ORIGIN_KINDS)}")
    first, last = VALIDATION_MONTHS[kind]
    return select_origins(ledger, kind, first, last)


# ---------------------------------------------------------------------------------- coverage


def coverage(ledger: Ledger) -> Coverage:
    """Counts by status, the realized denominator and the protocol 4 gates of one ledger.

    The gates are defined on the monthly ledger; on a quarter-end or year-end subset the numbers
    are reported and every gate is not applicable (``met`` None).
    """
    counts = {status: sum(row.status == status for row in ledger.rows) for status in STATUSES}
    scheduled, mature = counts[IMMATURE] + counts[MATURE], counts[MATURE]
    applies = ledger.origins == "monthly"

    def judged(ok: bool) -> bool | None:
        return ok if applies else None

    gates = [
        Gate(
            "scheduled_origins",
            scheduled,
            f"<= {MAX_SCHEDULED_ORIGINS}",
            judged(scheduled <= MAX_SCHEDULED_ORIGINS),
        ),
        Gate(
            "mature_origins",
            mature,
            f">= {MIN_MATURE_ORIGINS}",
            judged(mature >= MIN_MATURE_ORIGINS),
        ),
    ]
    menus = []
    for k, (name, _) in enumerate(ledger.menus):
        outcomes = [row.menus[k] for row in ledger.rows if row.status == MATURE]
        complete = sum(entry.outcome == COMPLETE for entry in outcomes)
        unexplained = sum(entry.outcome != COMPLETE and not entry.issues for entry in outcomes)
        disjoint = sum(row.menus[k].disjoint for row in ledger.rows)
        menus.append(MenuCoverage(name, complete, mature - complete, unexplained, disjoint))
        share = complete / mature if mature else None
        enough = mature > 0 and 100 * complete >= MIN_COMPLETE_PERCENT * mature
        gates += [
            Gate(f"{name}_completeness", share, f">= {MIN_COMPLETE_PERCENT}%", judged(enough)),
            Gate(f"{name}_unexplained_missing", unexplained, "= 0", judged(unexplained == 0)),
            Gate(
                f"{name}_disjoint_intervals",
                disjoint,
                f">= {MIN_DISJOINT_INTERVALS}",
                judged(disjoint >= MIN_DISJOINT_INTERVALS),
            ),
        ]
    return Coverage(
        lookback=ledger.lookback,
        origins=ledger.origins,
        d_star=ledger.d_star,
        fixed_menu=tuple(name for name, _ in ledger.menus),
        boundary_month=ledger.boundary_month,
        boundary_fund=ledger.boundary_fund,
        boundary_date=ledger.boundary_date,
        boundary_reason=ledger.boundary.code,
        months=len(ledger.rows),
        counts=counts,
        scheduled=scheduled,
        mature=mature,
        menus=tuple(menus),
        gates=tuple(gates),
        met=all(gate.met for gate in gates) if applies else None,
    )


# ------------------------------------------------------------------------------------- table

LEDGER_COLUMNS = (
    "lookback", "origins", "month", "origin", "status", "training_eligible",
    "realized_denominator", "maturity_session", "mature", "risk_free_source", "risk_free_rate",
    "month_issues", "menu", "funds", "origin_priced", "union_rows", "window_start", "window_rows",
    "complete_rows", "menu_training_eligible", "outcome", "horizon_start", "horizon_end",
    "horizon_rows", "disjoint", "overlap_prev_dates", "overlap_origins", "menu_issues",
)  # fmt: skip
_DATE_COLUMNS = ("origin", "maturity_session", "window_start", "horizon_start", "horizon_end")


def _issues_json(issues: Iterable[Issue]) -> str:
    return json.dumps(
        [
            {
                "code": issue.code,
                "fund": issue.fund,
                "date": None if issue.day is None else issue.day.isoformat(),
                "note": issue.note,
            }
            for issue in issues
        ]
    )


def ledger_frame(ledger: Ledger) -> pd.DataFrame:
    """The ledger as a table, one row per (month, menu), columns ``LEDGER_COLUMNS``."""
    rows = []
    for row in ledger.rows:
        for entry, (_, funds) in zip(row.menus, ledger.menus, strict=True):
            rows.append(
                {
                    "lookback": ledger.lookback,
                    "origins": ledger.origins,
                    "month": row.month,
                    "origin": row.origin,
                    "status": row.status,
                    "training_eligible": row.training_eligible,
                    "realized_denominator": row.in_realized_panel,
                    "maturity_session": row.maturity_session,
                    "mature": row.mature,
                    "risk_free_source": row.risk_free_source,
                    "risk_free_rate": row.risk_free_rate,
                    "month_issues": _issues_json(row.issues),
                    "menu": entry.menu,
                    "funds": ",".join(funds),
                    "origin_priced": entry.origin_priced,
                    "union_rows": entry.union_rows,
                    "window_start": entry.window_start,
                    "window_rows": entry.window_rows,
                    "complete_rows": entry.complete_rows,
                    "menu_training_eligible": entry.training_eligible,
                    "outcome": entry.outcome,
                    "horizon_start": entry.horizon_start,
                    "horizon_end": entry.horizon_end,
                    "horizon_rows": entry.horizon_rows,
                    "disjoint": entry.disjoint,
                    "overlap_prev_dates": entry.overlap_prev_dates,
                    "overlap_origins": entry.overlap_origins,
                    "menu_issues": _issues_json(entry.issues),
                }
            )
    frame = pd.DataFrame(rows, columns=list(LEDGER_COLUMNS))
    for column in _DATE_COLUMNS:
        frame[column] = pd.to_datetime(frame[column])
    for column in ("overlap_prev_dates", "overlap_origins"):
        frame[column] = frame[column].astype("Int64")
    return frame


# ---------------------------------------------------------------------------------- snapshot


class SnapshotChanged(Exception):
    """A snapshot file read after verification does not match its recorded digest."""


@dataclass(frozen=True)
class SnapshotInputs:
    """What the ledger reads from a verified snapshot."""

    root: Path
    manifest_sha256: str
    source_root: str  # the mirror the snapshot was copied from
    d_star: date
    menus: dict[str, tuple[str, ...]]
    records: dict[str, pd.DataFrame]  # every price file, by symbol
    sessions: pd.DatetimeIndex


def read_snapshot(path: str | Path, verify: Callable[[Path], Mapping[str, Any]]) -> SnapshotInputs:
    """Verify a frozen research snapshot with ``verify`` and read its ledger inputs.

    ``verify`` is ``verify_snapshot`` of scripts/freeze_research_inputs.py: it raises unless every
    file matches the snapshot's manifest and is read-only, and returns that manifest. Each file
    read here is hashed again, so the bytes used are the bytes verified.
    """
    root = Path(path).resolve()
    manifest = verify(root)
    digests = {entry["path"]: entry["sha256"] for entry in manifest["files"]}

    def read(relative: str) -> bytes:
        data = (root / relative).read_bytes()
        if hashlib.sha256(data).hexdigest() != digests.get(relative):
            raise SnapshotChanged(f"{root}: {relative} no longer matches the verified manifest")
        return data

    records = {
        Path(relative).stem: pd.read_parquet(io.BytesIO(read(relative)))
        for relative in sorted(digests)
        if relative.startswith("prices/") and relative.endswith(".parquet")
    }
    lines = read(manifest["calendar"]["file"]).decode("utf-8").splitlines()
    if not lines or lines[0] != "session":
        raise ValueError(f"{root}: the XNYS session export has no 'session' header")
    return SnapshotInputs(
        root=root,
        manifest_sha256=str(manifest["manifest_sha256"]),
        source_root=str(manifest.get("source_root") or ""),
        d_star=date.fromisoformat(manifest["d_star"]),
        menus={key: tuple(entry["funds"]) for key, entry in manifest["menus"].items()},
        records=records,
        sessions=pd.DatetimeIndex(pd.to_datetime(lines[1:], format="%Y-%m-%d")),
    )
