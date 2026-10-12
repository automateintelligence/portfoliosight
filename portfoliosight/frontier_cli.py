#!/usr/bin/env python
"""
Efficient frontier for a multi-account portfolio.

Reads a holdings CSV (Account, Symbol, Description, Qty, Price), downloads
adjusted daily prices for every symbol, and produces:

  * the mean-variance efficient frontier (long-only, fully invested)
  * where the CURRENT allocation sits relative to the frontier
  * three optimized allocations:
      - Tangency / max-Sharpe portfolio (best risk-vs-return trade-off)
      - Same risk as current, maximum return
      - Same return as current, minimum risk
      - Halfway: same risk as current, return midway between current and the
        same-risk maximum, with the least change from the current holdings
  * a static PNG and an interactive HTML plot in the style of the
    "Example Portfolio Efficient Frontier" figure (return vs. std. dev.,
    each ticker plotted, frontier, tangency, CML)
  * CSV files of the frontier and of every allocation

Usage
-----
    python efficient_frontier_portfolio.py --label baseline
    python efficient_frontier_portfolio.py --label cap10 --max-weight 0.10
    python efficient_frontier_portfolio.py --label noRothBonds_cap06 \
            --exclude SCHO,SCHP,SGOV --max-weight 0.06
    python efficient_frontier_portfolio.py --years 3 --rf 0.04 --label 3yr

Iteration tracking
------------------
Every run is written to its own folder  runs/r<NNN>_<label>/  containing
    run_config.json     every input: holdings file, exclusions, years, dates,
                        rf, cap, ticker count, short-history tickers
    holdings_used.csv   the exact positions analysed (after exclusions)
    summary.csv, allocations.csv, frontier.csv, assets.csv
    frontier.png, frontier.html
and one row is appended to  runs/run_log.csv  (the master index) with the
key metrics of every portfolio, so runs can be compared side by side.
The console prints that log at the end of each run.

Daily prices are cached in runs/_cache/ keyed by the date window, so all
iterations made on the same day use identical data; only tickers not yet in
the cache are downloaded.  The risk-free rate is cached per end date too.

Notes
-----
* Expected return = annualized arithmetic mean of daily simple returns (x252).
  Risk = annualized standard deviation of daily returns (x sqrt(252)).
  Both are backward-looking sample statistics over the lookback window and
  are NOT forecasts.  Max-Sharpe optimizers are notoriously sensitive to the
  mean estimates, so treat the "optimal" weights as directional, not literal.
* Prices are Yahoo Finance adjusted closes (auto_adjust=True): dividends,
  bond-ETF coupon distributions and splits are folded in, so returns are
  TOTAL returns, not price returns (e.g. SGOV shows ~+3.8 %/yr, not ~0 %).
* Tickers with less history than the lookback window (e.g. GEV, listed 2024)
  are kept: their mean is computed over the data they have and the
  covariance is estimated pairwise, then nudged to the nearest
  positive-semidefinite matrix.  The console report lists them.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

TRADING_DAYS = 252


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_holdings(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Qty"] = pd.to_numeric(df["Qty"].astype(str).str.replace(",", ""), errors="raise")
    df["Price"] = pd.to_numeric(df["Price"].astype(str).str.replace(",", ""), errors="raise")
    df["Value"] = df["Qty"] * df["Price"]
    return df


def current_weights(holdings: pd.DataFrame) -> pd.Series:
    """Combine all accounts; weight = market value / total."""
    by_symbol = holdings.groupby("Symbol")["Value"].sum()
    return (by_symbol / by_symbol.sum()).sort_index()


def download_prices(tickers: list[str], start: date, end: date,
                    cache_dir: Path | None = None) -> pd.DataFrame:
    """Adjusted closes for tickers; uses/extends a per-window CSV cache."""
    cache_file = cache_dir / f"prices_{start}_{end}.csv" if cache_dir else None
    cached = pd.DataFrame()
    if cache_file and cache_file.exists():
        cached = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        print(f"Price cache: {cache_file.name} ({cached.shape[1]} tickers)")
    need = [t for t in tickers if t not in cached.columns]
    if need:
        fresh = _yahoo_download(need, start, end)
        cached = pd.concat([cached, fresh], axis=1) if not cached.empty else fresh
        if cache_file:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached.to_csv(cache_file)
    prices = cached.reindex(columns=[t for t in tickers if t in cached.columns])
    prices = prices.dropna(how="all")
    missing = [t for t in tickers if t not in prices.columns or prices[t].dropna().empty]
    if missing:
        print(f"WARNING: no data for {missing}; they will be dropped from the analysis.")
    return prices.drop(columns=missing, errors="ignore")


def _yahoo_download(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    import yfinance as yf

    print(f"Downloading {len(tickers)} tickers from Yahoo Finance "
          f"({start} to {end}) ...")
    raw = yf.download(
        tickers, start=start, end=end, auto_adjust=True,
        progress=False, group_by="column", threads=True,
    )
    if raw.empty:
        sys.exit("No price data returned. Check network / ticker symbols.")
    prices = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    prices = prices.copy()
    prices.columns = [str(c) for c in prices.columns]
    prices.index = pd.to_datetime(prices.index).tz_localize(None)
    return prices.dropna(how="all")


def fetch_risk_free_rate(fallback: float, cache_dir: Path | None = None,
                         end: date | None = None) -> float:
    """Latest 13-week T-bill yield (^IRX) as a decimal, else fallback.
    Cached per end date so same-day iterations share one value."""
    cache_file = cache_dir / f"rf_{end}.json" if (cache_dir and end) else None
    if cache_file and cache_file.exists():
        rf = json.loads(cache_file.read_text())["rf"]
        print(f"Risk-free rate (cached for {end}): {rf:.3%}")
        return rf
    try:
        import yfinance as yf

        irx = yf.Ticker("^IRX").history(period="10d")["Close"].dropna()
        rf = float(irx.iloc[-1]) / 100.0
        if 0 <= rf < 0.2:
            print(f"Risk-free rate from ^IRX (13-week T-bill): {rf:.3%}")
            if cache_file:
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps({"rf": rf, "source": "^IRX"}))
            return rf
    except Exception as exc:  # noqa: BLE001
        print(f"Could not fetch ^IRX ({exc}); using fallback.")
    print(f"Risk-free rate (fallback): {fallback:.3%}")
    return fallback


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #
def nearest_psd(cov: np.ndarray, eps: float = 1e-10) -> np.ndarray:
    """Clip negative eigenvalues so the covariance is positive semidefinite."""
    sym = (cov + cov.T) / 2
    vals, vecs = np.linalg.eigh(sym)
    if vals.min() >= eps:
        return sym
    vals = np.clip(vals, eps, None)
    fixed = vecs @ np.diag(vals) @ vecs.T
    return (fixed + fixed.T) / 2


def annualized_stats(prices: pd.DataFrame):
    rets = prices.pct_change(fill_method=None)
    # Need at least ~6 months for a usable estimate
    counts = rets.count()
    mu = rets.mean() * TRADING_DAYS
    cov_daily = rets.cov(min_periods=60)          # pairwise, NaN-aware
    cov = nearest_psd(cov_daily.values) * TRADING_DAYS
    cov = pd.DataFrame(cov, index=rets.columns, columns=rets.columns)
    sigma = pd.Series(np.sqrt(np.diag(cov.values)), index=rets.columns)
    return rets, mu, cov, sigma, counts


def port_return(w, mu):
    return float(w @ mu)


def port_vol(w, cov):
    return float(np.sqrt(max(w @ cov @ w, 0.0)))


def sharpe(w, mu, cov, rf):
    v = port_vol(w, cov)
    return (port_return(w, mu) - rf) / v if v > 0 else np.nan


# --------------------------------------------------------------------------- #
# Optimization
# --------------------------------------------------------------------------- #
def _solve(obj, n, bounds, cons, x0=None):
    from scipy.optimize import minimize

    if x0 is None:
        x0 = np.full(n, 1.0 / n)
    best = None
    for guess in (x0, np.full(n, 1.0 / n)):
        res = minimize(obj, guess, method="SLSQP", bounds=bounds, constraints=cons,
                       options={"maxiter": 1000, "ftol": 1e-12})
        if res.success and (best is None or res.fun < best.fun):
            best = res
    if best is None:
        res = minimize(obj, x0, method="SLSQP", bounds=bounds, constraints=cons,
                       options={"maxiter": 3000, "ftol": 1e-10})
        best = res
    w = np.clip(best.x, 0, None)
    return w / w.sum()


def min_variance(mu, cov, bounds):
    n = len(mu)
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    return _solve(lambda w: w @ cov @ w, n, bounds, cons)


def min_variance_for_return(mu, cov, bounds, target, x0=None):
    n = len(mu)
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1},
            {"type": "eq", "fun": lambda w: w @ mu - target}]
    return _solve(lambda w: w @ cov @ w, n, bounds, cons, x0)


def max_return_for_vol(mu, cov, bounds, target_vol, x0=None):
    n = len(mu)
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1},
            {"type": "ineq", "fun": lambda w: target_vol**2 - w @ cov @ w}]
    return _solve(lambda w: -(w @ mu), n, bounds, cons, x0)


def min_turnover_for_return_and_vol(mu, cov, bounds, w_cur, target_ret, target_vol):
    """Closest portfolio to w_cur (least squared weight change) with the given
    expected return and the same volatility.  Falls back to vol <= target."""
    n = len(mu)
    base = [{"type": "eq", "fun": lambda w: w.sum() - 1},
            {"type": "eq", "fun": lambda w: w @ mu - target_ret}]
    obj = lambda w: float(((w - w_cur) ** 2).sum())
    for vol_con in ({"type": "eq", "fun": lambda w: w @ cov @ w - target_vol**2},
                    {"type": "ineq", "fun": lambda w: target_vol**2 - w @ cov @ w}):
        w = _solve(obj, n, bounds, base + [vol_con], w_cur)
        if abs(w @ mu - target_ret) < 1e-4 and port_vol(w, cov) <= target_vol * 1.01:
            return w
    return w


def max_sharpe(mu, cov, bounds, rf):
    n = len(mu)
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}]

    def neg_sharpe(w):
        v = np.sqrt(max(w @ cov @ w, 1e-16))
        return -(w @ mu - rf) / v

    return _solve(neg_sharpe, n, bounds, cons)


def efficient_frontier(mu, cov, bounds, n_points=60):
    """Return DataFrame of (ret, vol, weights) along the efficient frontier."""
    w_min = min_variance(mu, cov, bounds)
    r_min = port_return(w_min, mu)
    # Highest return achievable under the bounds: greedy fill of top assets
    order = np.argsort(-mu)
    w_max = np.zeros(len(mu))
    remaining = 1.0
    for i in order:
        take = min(bounds[i][1], remaining)
        w_max[i] = take
        remaining -= take
        if remaining <= 1e-12:
            break
    r_max = port_return(w_max, mu)

    targets = np.linspace(r_min, r_max, n_points)
    rows, x0 = [], w_min
    for t in targets:
        w = min_variance_for_return(mu, cov, bounds, t, x0)
        x0 = w
        rows.append({"ret": port_return(w, mu), "vol": port_vol(w, cov), "w": w})
    df = pd.DataFrame(rows)
    # keep only the upper (efficient) branch: vol must be non-decreasing in ret
    df = df.sort_values("ret").reset_index(drop=True)
    return df, w_min


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def describe(name, w, mu, cov, rf):
    return {"Portfolio": name,
            "Expected return": port_return(w, mu),
            "Std deviation": port_vol(w, cov),
            "Sharpe": sharpe(w, mu, cov, rf)}


def weights_table(allocs: dict[str, np.ndarray], tickers, total_value) -> pd.DataFrame:
    df = pd.DataFrame(allocs, index=tickers)
    df.index.name = "Symbol"
    return df


def print_alloc(name, w, tickers, total_value, mu, sigma, min_w=0.005):
    s = pd.Series(w, index=tickers)
    s = s[s >= min_w].sort_values(ascending=False)
    print(f"\n{name}  (holdings >= {min_w:.1%}; {len(s)} positions)")
    print(f"{'Symbol':<8}{'Weight':>9}{'$ Value':>14}{'Exp.Ret':>10}{'StdDev':>9}")
    for t, v in s.items():
        print(f"{t:<8}{v:>9.2%}{v * total_value:>14,.0f}{mu[t]:>10.1%}{sigma[t]:>9.1%}")
    print(f"{'TOTAL':<8}{s.sum():>9.2%}{s.sum() * total_value:>14,.0f}")


# --------------------------------------------------------------------------- #
# Plotting
# --------------------------------------------------------------------------- #
def capped_style(name: str) -> dict:
    """Marker style for the optional 'Capped X%' allocations (and any unknown name)."""
    if name.startswith("Capped") and "Sharpe" in name:
        return dict(marker="v", s=150, color="#bcbd22", plotly="triangle-down")
    if name.startswith("Capped"):
        return dict(marker="<", s=130, color="#7f7f7f", plotly="triangle-left")
    return dict(marker="o", s=80, color="black", plotly="circle")


def plot_matplotlib(frontier, assets, ports, rf, w_tan, mu, cov, title, out_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(13, 8.5))
    ax.plot(frontier["vol"], frontier["ret"], "-o", ms=3, lw=1.5, color="#1f77b4",
            label="Efficient Frontier", zorder=3)

    # Capital market line through tangency portfolio
    tan_ret, tan_vol = port_return(w_tan, mu), port_vol(w_tan, cov)
    x_cml = np.array([0, frontier["vol"].max() * 1.05])
    ax.plot(x_cml, rf + (tan_ret - rf) / tan_vol * x_cml, "--", color="grey", lw=1,
            label=f"Capital market line (rf={rf:.2%})", zorder=2)

    # Individual assets
    bonds = assets["is_bond"]
    ax.scatter(assets.loc[~bonds, "vol"], assets.loc[~bonds, "ret"], marker="^", s=28,
               color="#999999", alpha=0.8, label="Holdings (equity)", zorder=2)
    ax.scatter(assets.loc[bonds, "vol"], assets.loc[bonds, "ret"], marker="^", s=40,
               color="#2ca02c", alpha=0.9, label="Holdings (bond ETF)", zorder=2)
    for t, row in assets.iterrows():
        ax.annotate(t, (row["vol"], row["ret"]), fontsize=6.5, alpha=0.8,
                    xytext=(2, 2), textcoords="offset points")

    styles = {
        "Current portfolio": dict(marker="o", s=160, color="#d62728"),
        "Tangency (max Sharpe)": dict(marker="*", s=300, color="#ff7f0e"),
        "Min variance": dict(marker="D", s=90, color="#17becf"),
        "Same risk, max return": dict(marker="s", s=110, color="#9467bd"),
        "Halfway (same risk, mid return)": dict(marker="h", s=140, color="#e377c2"),
        "Same return, min risk": dict(marker="P", s=130, color="#8c564b"),
    }
    left_labels = {"Same return, min risk", "Min variance"}
    for name, (r, v, sr) in ports.items():
        st = styles.get(name, capped_style(name))
        ax.scatter(v, r, label=f"{name}: {r:.1%} / {v:.1%}, Sharpe {sr:.2f}",
                   edgecolor="black", linewidth=0.8, zorder=5,
                   **{k: x for k, x in st.items() if k != "plotly"})
        if name in left_labels:
            xy, ha = (-8, 8), "right"
        else:
            xy, ha = (8, -4), "left"
        ax.annotate(name, (v, r), fontsize=8.5, fontweight="bold", xytext=xy, ha=ha,
                    textcoords="offset points", color=st["color"], zorder=6)

    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlabel("Standard Deviation (annualized)")
    ax.set_ylabel("Expected Return (annualized)")
    ax.set_title(title)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlim(0, assets["vol"].max() * 1.08)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def plot_plotly(frontier, assets, ports, rf, w_tan, mu, cov, title, tickers, out_html):
    try:
        import plotly.graph_objects as go
    except ImportError:
        print("plotly not installed; skipping interactive HTML.")
        return

    fig = go.Figure()
    hover = [
        "<br>".join(f"{t}: {w:.1%}" for t, w in
                    sorted(zip(tickers, wv), key=lambda x: -x[1]) if w >= 0.005)
        for wv in frontier["w"]
    ]
    fig.add_trace(go.Scatter(
        x=frontier["vol"], y=frontier["ret"], mode="lines+markers",
        name="Efficient Frontier", marker=dict(size=5, color="#1f77b4"),
        customdata=hover,
        hovertemplate="Return %{y:.2%}<br>Std dev %{x:.2%}<br><br>%{customdata}<extra></extra>",
    ))
    tan_ret, tan_vol = port_return(w_tan, mu), port_vol(w_tan, cov)
    xm = float(frontier["vol"].max()) * 1.05
    fig.add_trace(go.Scatter(x=[0, xm], y=[rf, rf + (tan_ret - rf) / tan_vol * xm],
                             mode="lines", line=dict(dash="dash", color="grey"),
                             name="Capital market line"))
    for is_bond, label, color in [(False, "Equity holdings", "#888"),
                                  (True, "Bond ETFs", "#2ca02c")]:
        sub = assets[assets["is_bond"] == is_bond]
        fig.add_trace(go.Scatter(
            x=sub["vol"], y=sub["ret"], mode="markers+text", text=sub.index,
            textposition="top center", textfont=dict(size=9),
            marker=dict(symbol="triangle-up", size=9, color=color), name=label,
            customdata=np.stack([sub["weight"], sub["sharpe"]], axis=1),
            hovertemplate="<b>%{text}</b><br>Return %{y:.2%}<br>Std dev %{x:.2%}"
                          "<br>Current weight %{customdata[0]:.2%}"
                          "<br>Sharpe %{customdata[1]:.2f}<extra></extra>",
        ))
    symbols = {"Current portfolio": "circle", "Tangency (max Sharpe)": "star",
               "Min variance": "diamond", "Same risk, max return": "square",
               "Halfway (same risk, mid return)": "hexagon",
               "Same return, min risk": "cross"}
    colors = {"Current portfolio": "#d62728", "Tangency (max Sharpe)": "#ff7f0e",
              "Min variance": "#17becf", "Same risk, max return": "#9467bd",
              "Halfway (same risk, mid return)": "#e377c2",
              "Same return, min risk": "#8c564b"}
    for name, (r, v, sr) in ports.items():
        cs = capped_style(name)
        fig.add_trace(go.Scatter(
            x=[v], y=[r], mode="markers+text", text=[name], textposition="middle right",
            marker=dict(symbol=symbols.get(name, cs["plotly"]), size=16,
                        color=colors.get(name, cs["color"]), line=dict(width=1, color="black")),
            name=name,
            hovertemplate=f"<b>{name}</b><br>Expected return {r:.2%}<br>"
                          f"Standard deviation {v:.2%}<br>Sharpe {sr:.3f}<extra></extra>",
        ))
    fig.update_layout(
        title=title, xaxis=dict(title="Standard Deviation", tickformat=".0%", rangemode="tozero"),
        yaxis=dict(title="Expected Return", tickformat=".0%"),
        template="plotly_white", width=1250, height=800, hovermode="closest",
    )
    fig.write_html(out_html, include_plotlyjs="cdn")


# --------------------------------------------------------------------------- #
# Run tracking
# --------------------------------------------------------------------------- #
RUN_LOG_COLS = ["run_id", "timestamp", "label", "holdings_file", "excluded", "years",
                "window_start", "window_end", "rf", "max_weight", "cap_alloc", "n_tickers",
                "portfolio_value"]
LOGGED_PORTFOLIOS = {
    "Current portfolio": "cur",
    "Tangency (max Sharpe)": "tan",
    "Same risk, max return": "sameRisk",
    "Halfway (same risk, mid return)": "half",
    "Same return, min risk": "sameRet",
}


def next_run_id(runs_dir: Path, label: str) -> str:
    existing = sorted(p.name for p in runs_dir.glob("r[0-9][0-9][0-9]_*") if p.is_dir())
    n = int(existing[-1][1:4]) + 1 if existing else 1
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    return f"r{n:03d}_{safe}"


def append_run_log(runs_dir: Path, row: dict) -> pd.DataFrame:
    log_file = runs_dir / "run_log.csv"
    log = pd.read_csv(log_file) if log_file.exists() else pd.DataFrame()
    log = pd.concat([log, pd.DataFrame([row])], ignore_index=True)
    log.to_csv(log_file, index=False, float_format="%.6f")
    return log


def print_run_log(log: pd.DataFrame):
    cols = ["run_id", "excluded", "years", "max_weight", "cap_alloc", "n_tickers",
            "cur_ret", "cur_vol", "cur_sharpe",
            "tan_ret", "tan_vol", "tan_sharpe", "tan_turnover",
            "half_ret", "half_vol", "half_turnover",
            "capTan_ret", "capTan_vol", "capTan_sharpe", "capTan_turnover"]
    view = log[[c for c in cols if c in log.columns]].copy()
    for c in view.columns:
        if c.endswith(("_ret", "_vol", "_turnover")) or c in ("max_weight", "rf", "cap_alloc"):
            view[c] = view[c].map(lambda x: "" if pd.isna(x) else f"{x:.1%}")
        elif c.endswith("_sharpe"):
            view[c] = view[c].map(lambda x: "" if pd.isna(x) else f"{x:.2f}")
    view["excluded"] = view["excluded"].fillna("").astype(str).replace("nan", "")
    print("\n=== Run log (all iterations) ===")
    print(view.to_string(index=False))


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="run", help="short name for this iteration (used in the folder name)")
    ap.add_argument("--holdings", default="data/holdings/holdings_2026-10.csv", help="holdings CSV")
    ap.add_argument("--exclude", default="", help="comma-separated tickers to drop, e.g. SCHO,SCHP,SGOV")
    ap.add_argument("--years", type=float, default=5.0, help="lookback window in years")
    ap.add_argument("--end", default=None, help="end date YYYY-MM-DD (default: today)")
    ap.add_argument("--rf", type=float, default=None,
                    help="annual risk-free rate as decimal; default = latest 13-week T-bill")
    ap.add_argument("--max-weight", type=float, default=1.0,
                    help="cap on any single holding in optimized portfolios (e.g. 0.06)")
    ap.add_argument("--cap-alloc", type=float, default=None,
                    help="also evaluate SEPARATE capped allocations (max Sharpe and same-risk "
                         "max return with this per-ticker cap, e.g. 0.06) as extra points; "
                         "the frontier and other portfolios keep --max-weight")
    ap.add_argument("--points", type=int, default=60, help="number of frontier points")
    ap.add_argument("--runs-dir", default="runs", help="root folder for all iterations")
    ap.add_argument("--out", default=None, help="explicit output folder (bypasses runs/ numbering)")
    ap.add_argument("--no-cache", action="store_true", help="always re-download prices and rf")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent
    holdings_path = Path(args.holdings)
    if not holdings_path.is_absolute():
        holdings_path = here / holdings_path
    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_absolute():
        runs_dir = here / runs_dir
    runs_dir.mkdir(parents=True, exist_ok=True)
    if args.out:
        out = Path(args.out)
        out = out if out.is_absolute() else here / out
        run_id = out.name
    else:
        run_id = next_run_id(runs_dir, args.label)
        out = runs_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    cache_dir = None if args.no_cache else runs_dir / "_cache"
    print(f"Run: {run_id}  ->  {out}")

    excluded = [t.strip().upper() for t in args.exclude.split(",") if t.strip()]
    holdings = load_holdings(holdings_path)
    if excluded:
        dropped = holdings[holdings["Symbol"].isin(excluded)]
        print(f"Excluding {len(dropped)} positions: {', '.join(sorted(set(dropped['Symbol'])))} "
              f"(${dropped['Value'].sum():,.0f})")
        holdings = holdings[~holdings["Symbol"].isin(excluded)].reset_index(drop=True)
    holdings.to_csv(out / "holdings_used.csv", index=False)
    w_cur_s = current_weights(holdings)
    total_value = holdings["Value"].sum()
    tickers = list(w_cur_s.index)

    end = date.fromisoformat(args.end) if args.end else date.today()
    start = end - timedelta(days=int(args.years * 365.25))
    prices = download_prices(tickers, start, end, cache_dir)
    tickers = list(prices.columns)
    w_cur_s = w_cur_s.reindex(tickers).fillna(0.0)
    w_cur_s = w_cur_s / w_cur_s.sum()

    rets, mu, cov, sigma, counts = annualized_stats(prices)
    rf = args.rf if args.rf is not None else fetch_risk_free_rate(0.04, cache_dir, end)

    n = len(tickers)
    cap = min(max(args.max_weight, 1.0 / n), 1.0)
    bounds = tuple((0.0, cap) for _ in range(n))
    mu_v, cov_v = mu.values, cov.values
    w_cur = w_cur_s.values

    # --- short-history report
    full = counts.max()
    short = counts[counts < 0.9 * full]
    if not short.empty:
        print("\nTickers with shorter history than the lookback window "
              "(stats computed from available data):")
        for t, c in short.items():
            print(f"  {t:<7} {c:>5} trading days  (first date "
                  f"{prices[t].first_valid_index().date()})")

    # --- optimizations
    print("\nComputing efficient frontier ...")
    frontier, w_minvar = efficient_frontier(mu_v, cov_v, bounds, args.points)
    w_tan = max_sharpe(mu_v, cov_v, bounds, rf)
    cur_ret, cur_vol = port_return(w_cur, mu_v), port_vol(w_cur, cov_v)
    w_same_risk = max_return_for_vol(mu_v, cov_v, bounds, cur_vol, w_tan)
    w_same_ret = min_variance_for_return(mu_v, cov_v, bounds, cur_ret, w_minvar)
    mid_ret = (cur_ret + port_return(w_same_risk, mu_v)) / 2
    w_half = min_turnover_for_return_and_vol(mu_v, cov_v, bounds, w_cur, mid_ret, cur_vol)

    allocs = {
        "Current portfolio": w_cur,
        "Tangency (max Sharpe)": w_tan,
        "Same risk, max return": w_same_risk,
        "Halfway (same risk, mid return)": w_half,
        "Same return, min risk": w_same_ret,
        "Min variance": w_minvar,
    }
    cap_alloc = None
    if args.cap_alloc is not None:
        cap_alloc = min(max(args.cap_alloc, 1.0 / n), 1.0)
        bounds_c = tuple((0.0, cap_alloc) for _ in range(n))
        w_cap_tan = max_sharpe(mu_v, cov_v, bounds_c, rf)
        w_cap_same_risk = max_return_for_vol(mu_v, cov_v, bounds_c, cur_vol, w_cap_tan)
        allocs[f"Capped {cap_alloc:.0%}: max Sharpe"] = w_cap_tan
        allocs[f"Capped {cap_alloc:.0%}: same risk, max return"] = w_cap_same_risk
    summary = pd.DataFrame([describe(k, v, mu_v, cov_v, rf) for k, v in allocs.items()])
    # one-way turnover: fraction of the portfolio that must be sold/bought to get there
    summary["Turnover"] = [0.5 * np.abs(v - w_cur).sum() for v in allocs.values()]
    summary["Positions >=0.5%"] = [int((v >= 0.005).sum()) for v in allocs.values()]
    ports = {k: (port_return(v, mu_v), port_vol(v, cov_v), sharpe(v, mu_v, cov_v, rf))
             for k, v in allocs.items()}

    # --- per-asset table
    bond_etfs = {"SCHO", "SCHP", "SGOV", "IEF", "TLT", "VCIT", "BND", "AGG", "TIP", "VTIP", "LQD"}
    assets = pd.DataFrame({"ret": mu, "vol": sigma, "weight": w_cur_s,
                           "sharpe": (mu - rf) / sigma,
                           "days": counts})
    assets["is_bond"] = assets.index.isin(bond_etfs)
    assets["value"] = assets["weight"] * total_value

    # --- console report
    pd.set_option("display.width", 160)
    print(f"\nPortfolio value (all accounts): ${total_value:,.0f}   "
          f"Window: {prices.index[0].date()} to {prices.index[-1].date()}   "
          f"Risk-free: {rf:.2%}   Max weight: {cap:.0%}")
    print(f"\n=== {run_id}: portfolio comparison (annualized) ===")
    fmt = summary.copy()
    for c in ("Expected return", "Std deviation"):
        fmt[c] = fmt[c].map("{:.2%}".format)
    fmt["Sharpe"] = fmt["Sharpe"].map("{:.3f}".format)
    fmt["Turnover"] = fmt["Turnover"].map("{:.1%}".format)
    print(fmt.to_string(index=False))

    print_alloc("CURRENT allocation (combined accounts)", w_cur, tickers, total_value, mu, sigma)
    print_alloc("TANGENCY / max-Sharpe allocation", w_tan, tickers, total_value, mu, sigma)
    print_alloc("SAME RISK as current, max return", w_same_risk, tickers, total_value, mu, sigma)
    print_alloc("HALFWAY: same risk, return midway between current and max "
                "(minimum change from current)", w_half, tickers, total_value, mu, sigma)
    print_alloc("SAME RETURN as current, min risk", w_same_ret, tickers, total_value, mu, sigma)
    if cap_alloc is not None:
        print_alloc(f"CAPPED {cap_alloc:.0%}: max Sharpe (separate allocation, cap applied only here)",
                    w_cap_tan, tickers, total_value, mu, sigma)
        print_alloc(f"CAPPED {cap_alloc:.0%}: same risk as current, max return",
                    w_cap_same_risk, tickers, total_value, mu, sigma)

    # --- files
    wt = weights_table(allocs, tickers, total_value)
    wt["Exp return"] = mu
    wt["Std dev"] = sigma
    wt["Current $"] = w_cur_s * total_value
    wt["Tangency $"] = pd.Series(w_tan, index=tickers) * total_value
    wt["Tangency - Current $"] = wt["Tangency $"] - wt["Current $"]
    wt["Halfway $"] = pd.Series(w_half, index=tickers) * total_value
    wt["Halfway - Current $"] = wt["Halfway $"] - wt["Current $"]
    if cap_alloc is not None:
        wt["Capped max Sharpe $"] = pd.Series(w_cap_tan, index=tickers) * total_value
        wt["Capped max Sharpe - Current $"] = wt["Capped max Sharpe $"] - wt["Current $"]
    wt.to_csv(out / "allocations.csv", float_format="%.6f")
    summary.to_csv(out / "summary.csv", index=False, float_format="%.6f")
    fr_out = frontier[["ret", "vol"]].copy()
    fr_out[tickers] = np.vstack(frontier["w"].values)
    fr_out.to_csv(out / "frontier.csv", index=False, float_format="%.6f")
    assets.to_csv(out / "assets.csv", float_format="%.6f")

    title = (f"{run_id}: Efficient Frontier ({prices.index[0]:%b %Y} - {prices.index[-1]:%b %Y}), "
             f"{n} holdings, rf={rf:.2%}" + (f", max weight {cap:.0%}" if cap < 1 else ""))
    plot_matplotlib(frontier, assets, ports, rf, w_tan, mu_v, cov_v, title, out / "frontier.png")
    plot_plotly(frontier, assets, ports, rf, w_tan, mu_v, cov_v, title, tickers, out / "frontier.html")

    # --- run config + master log
    config = {
        "run_id": run_id, "label": args.label, "timestamp": datetime.now().isoformat(timespec="seconds"),
        "holdings_file": str(holdings_path), "excluded": excluded,
        "years": args.years, "end_arg": args.end, "window_start": str(prices.index[0].date()),
        "window_end": str(prices.index[-1].date()), "rf": rf,
        "rf_source": "arg" if args.rf is not None else "^IRX 13-week T-bill",
        "max_weight": cap, "cap_alloc": cap_alloc, "frontier_points": args.points, "n_tickers": n,
        "portfolio_value": float(total_value), "price_cache": str(cache_dir) if cache_dir else None,
        "short_history_tickers": {t: int(c) for t, c in short.items()},
        "return_model": "annualized mean daily total return x252; std x sqrt(252); pairwise cov -> nearest PSD",
        "command": " ".join(sys.argv),
    }
    (out / "run_config.json").write_text(json.dumps(config, indent=2))
    shutil.copy(holdings_path, out / "holdings_source.csv")

    row = {k: config[k] for k in RUN_LOG_COLS if k in config}
    row["excluded"] = ",".join(excluded)
    logged = dict(LOGGED_PORTFOLIOS)
    if cap_alloc is not None:
        logged[f"Capped {cap_alloc:.0%}: max Sharpe"] = "capTan"
        logged[f"Capped {cap_alloc:.0%}: same risk, max return"] = "capSameRisk"
    for name, key in logged.items():
        r, v, sr = ports[name]
        row[f"{key}_ret"], row[f"{key}_vol"], row[f"{key}_sharpe"] = r, v, sr
        row[f"{key}_turnover"] = float(summary.loc[summary["Portfolio"] == name, "Turnover"].iloc[0])
    log = append_run_log(runs_dir, row)
    print_run_log(log)

    print(f"\nWrote outputs to {out}")
    for f in sorted(out.iterdir()):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()
