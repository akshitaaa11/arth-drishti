"""Top-k portfolio backtests with transaction costs (README Phase 4, FR-11).

Rules (identical for every strategy and for the Nifty 500 benchmark, so the comparison is like for like):
  * each test budget is one holding window: buy at the close of the day after the budget (``start``), sell at the
    close of the next budget's day 0 (``label_end``) - exactly the window the 12m target measures;
  * equal weights, buy-and-hold inside the window (weights drift with prices);
  * costs: ``round_trip_cost`` (0.2%) on the full portfolio each window, i.e. half on the buy and half on the sell.
    This slightly overcharges strategies that would hold names across windows; turnover is reported separately;
  * between windows the money sits in cash earning 0%, and risk-free is taken as 0 in the Sharpe ratio;
  * a stock without a price on the sell day is not in the panel (its target is incomplete), so stock portfolios
    carry survivorship bias; this is stated in the report.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass
class BacktestResult:
    daily: pd.Series  # net daily return of the strategy over the whole calendar span (cash days = 0)
    periods: pd.DataFrame  # one row per window
    summary: dict[str, float]


def _window_path(values: pd.DataFrame, start: str, end: str) -> pd.Series:
    """Buy-and-hold equal-weight value path of the columns of ``values`` (price/level frame) inside a window."""
    window = values.loc[start:end]
    return (window / window.iloc[0]).mean(axis=1)


def run_backtest(
    selections: dict[str, list[str]],
    windows: pd.DataFrame,
    levels: pd.DataFrame,
    round_trip_cost: float,
) -> BacktestResult:
    """Backtest equal-weight portfolios.

    ``selections``: budget_id -> entities held in that window.  ``windows``: columns budget_id, start, label_end.
    ``levels``: date-indexed price / index-level frame whose columns are the entities (sectors or stocks).
    """
    levels = levels.copy()
    levels.index = levels.index.astype(str)
    all_days = list(levels.index)
    daily = pd.Series(0.0, index=all_days)
    rows = []
    previous: set[str] = set()
    first_start = last_end = None
    for window in windows.itertuples():
        budget_id, start, end = str(window.budget_id), str(window.start), str(window.label_end)
        held = selections.get(budget_id)
        if not held:
            continue
        path = _window_path(levels[held].ffill(), start, end)
        gross = float(path.iloc[-1] - 1.0)
        half = round_trip_cost / 2
        value = path * (1.0 - half)  # buy cost paid on the first day
        value.iloc[-1] *= 1.0 - half  # sell cost paid on the last day
        net_r = value.pct_change()
        net_r.iloc[0] = value.iloc[0] - 1.0
        net = float(value.iloc[-1] - 1.0)
        daily.loc[net_r.index] = net_r.to_numpy()
        current = set(held)
        turnover = 1.0 if not previous else 1.0 - len(current & previous) / max(len(current), len(previous))
        previous = current
        first_start = first_start or start
        last_end = end
        rows.append({"budget_id": budget_id, "start": start, "end": end,
                     "n_held": len(held), "gross_return": gross, "net_return": net, "turnover": turnover})
    periods = pd.DataFrame(rows)
    if periods.empty or first_start is None or last_end is None:
        return BacktestResult(daily.iloc[0:0], periods, {})
    span = daily.loc[first_start:last_end]
    return BacktestResult(span, periods, summarise(span, periods))


def summarise(daily: pd.Series, periods: pd.DataFrame) -> dict[str, float]:
    equity = (1.0 + daily).cumprod()
    years = len(daily) / TRADING_DAYS
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and equity.iloc[-1] > 0 else float("nan")
    std = float(daily.std(ddof=1))
    sharpe = float(daily.mean() / std * np.sqrt(TRADING_DAYS)) if std > 0 else float("nan")
    drawdown = equity / equity.cummax() - 1.0
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": float(drawdown.min()),
        "turnover": float(periods["turnover"].iloc[1:].mean()) if len(periods) > 1 else float("nan"),
        "mean_period_net_return": float(periods["net_return"].mean()),
        "n_periods": float(len(periods)),
        "total_return": float(equity.iloc[-1] - 1.0),
    }


def top_k_selection(predictions: pd.DataFrame, k: int, selects_all: bool) -> dict[str, list[str]]:
    """budget_id -> entities with the k highest scores (ties broken by entity name for reproducibility)."""
    out: dict[str, list[str]] = {}
    for budget_id, group in predictions.groupby("budget_id"):
        ordered = group.sort_values(["score", "entity"], ascending=[False, True])
        out[str(budget_id)] = list(ordered["entity"]) if selects_all else list(ordered["entity"].head(k))
    return out
