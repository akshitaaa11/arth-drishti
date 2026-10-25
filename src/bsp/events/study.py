"""Market-model event study for sectors and stocks.

Estimates alpha and beta over trading days [-250, -31] before the budget,
and computes CAR and t-stats for windows:
  - [-5, -1]
  - 0
  - [0, +5]
  - [0, +30]
  - [0, +90]
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from bsp.common.config import get_project_root

if TYPE_CHECKING:
    from bsp.features.baskets import MarketDataBundle

WINDOWS = (
    ("[-5,-1]", -5, -1),
    ("0", 0, 0),
    ("[0,+5]", 0, 5),
    ("[0,+30]", 0, 30),
    ("[0,+90]", 0, 90),
)


@dataclass
class MarketModelFit:
    """Estimated market model parameters and residual variance."""

    alpha: float
    beta: float
    residual_variance: float
    estimation_days: int
    mean_market_return: float
    var_market_return: float


def fit_market_model(
    asset_returns: np.ndarray, market_returns: np.ndarray
) -> MarketModelFit | None:
    """Fit OLS r_asset = alpha + beta * r_market over the estimation window."""
    valid_mask = ~np.isnan(asset_returns) & ~np.isnan(market_returns)
    if valid_mask.sum() < 15:
        return None

    y = asset_returns[valid_mask]
    x = market_returns[valid_mask]
    m = len(y)

    x_mean = float(np.mean(x))
    y_mean = float(np.mean(y))
    x_dev = x - x_mean
    y_dev = y - y_mean

    denom = float(np.sum(x_dev**2))
    if denom <= 1e-12:
        beta = 1.0
        alpha = 0.0
    else:
        beta = float(np.sum(x_dev * y_dev) / denom)
        alpha = y_mean - beta * x_mean

    residuals = y - (alpha + beta * x)
    dof = max(1, m - 2)
    s2 = float(np.sum(residuals**2) / dof)
    var_x = denom / max(1, m - 1)

    return MarketModelFit(
        alpha=alpha,
        beta=beta,
        residual_variance=s2,
        estimation_days=m,
        mean_market_return=x_mean,
        var_market_return=var_x,
    )


def compute_car_and_tstat(
    fit: MarketModelFit,
    asset_window_returns: np.ndarray,
    market_window_returns: np.ndarray,
) -> tuple[float | None, float | None]:
    """Calculate CAR and t-stat for an event window."""
    valid_mask = ~np.isnan(asset_window_returns) & ~np.isnan(market_window_returns)
    l_eff = int(valid_mask.sum())
    if l_eff == 0:
        return None, None

    y = asset_window_returns[valid_mask]
    x = market_window_returns[valid_mask]

    abnormal_returns = y - (fit.alpha + fit.beta * x)
    car = float(np.sum(abnormal_returns))

    s2 = fit.residual_variance
    m = fit.estimation_days
    denom = fit.var_market_return * (m - 1) if fit.var_market_return > 0 else 0.0

    if denom > 1e-12 and m > 0:
        mean_x_window = float(np.mean(x))
        adj = 1.0 + (l_eff / m) + (((mean_x_window - fit.mean_market_return) ** 2) / denom)
        var_car = l_eff * s2 * adj
    else:
        var_car = l_eff * s2

    std_car = float(np.sqrt(max(0.0, var_car)))
    t_stat = (car / std_car) if std_car > 1e-9 else 0.0

    return car, t_stat


def run_event_study(
    bundle: MarketDataBundle,
    budget_events: pd.DataFrame,
) -> pd.DataFrame:
    """Run market-model event study for all sectors and stocks across all budgets.

    Returns DataFrame with columns:
      entity, entity_type, budget_id, window, car, t_stat, alpha, beta
    """
    trading_days = bundle.trading_days
    max_idx = len(trading_days) - 1

    records: list[dict[str, object]] = []

    # Filter to unique budgets
    b_df = budget_events.drop_duplicates(subset=["budget_id"]).sort_values("presented_on")

    for _, b_row in b_df.iterrows():
        b_id = str(b_row["budget_id"])
        p_date = str(b_row["presented_on"])

        # Find Day 0: first trading day on or after presented_on
        cand_indices = [i for i, d in enumerate(trading_days) if d >= p_date]
        if not cand_indices:
            continue
        day0_idx = cand_indices[0]

        # Estimation window: [-250, -31]
        est_start = max(0, day0_idx - 250)
        est_end = max(0, day0_idx - 30)  # exclusive end: day -31 is the last estimation day

        if est_end <= est_start:
            continue

        mkt_all = np.asarray(bundle.market_returns.values)
        mkt_est = mkt_all[est_start:est_end]

        # 1. Sector baskets
        for sec_id in bundle.sector_returns.columns:
            sec_all = np.asarray(bundle.sector_returns[sec_id].values)
            sec_est = sec_all[est_start:est_end]

            fit = fit_market_model(sec_est, mkt_est)
            if fit is None:
                continue

            for win_name, w_start, w_end in WINDOWS:
                idx_start = max(0, min(max_idx, day0_idx + w_start))
                idx_end = max(0, min(max_idx, day0_idx + w_end + 1))
                if idx_end <= idx_start:
                    continue

                sec_w = sec_all[idx_start:idx_end]
                mkt_w = mkt_all[idx_start:idx_end]
                car, t_stat = compute_car_and_tstat(fit, sec_w, mkt_w)

                records.append(
                    {
                        "entity": sec_id,
                        "entity_type": "sector",
                        "budget_id": b_id,
                        "window": win_name,
                        "car": car,
                        "t_stat": t_stat,
                        "alpha": fit.alpha,
                        "beta": fit.beta,
                    }
                )

        # 2. Individual stocks (active on Day 0)
        for sym in bundle.stock_returns.columns:
            first_d = bundle.first_price_dates.get(sym)
            if first_d and first_d > p_date:
                # Stock not yet listed as of budget date
                continue

            stock_all = np.asarray(bundle.stock_returns[sym].values)
            stock_est = stock_all[est_start:est_end]

            fit = fit_market_model(stock_est, mkt_est)
            if fit is None:
                continue

            for win_name, w_start, w_end in WINDOWS:
                idx_start = max(0, min(max_idx, day0_idx + w_start))
                idx_end = max(0, min(max_idx, day0_idx + w_end + 1))
                if idx_end <= idx_start:
                    continue

                stk_w = stock_all[idx_start:idx_end]
                mkt_w = mkt_all[idx_start:idx_end]
                car, t_stat = compute_car_and_tstat(fit, stk_w, mkt_w)

                records.append(
                    {
                        "entity": sym,
                        "entity_type": "stock",
                        "budget_id": b_id,
                        "window": win_name,
                        "car": car,
                        "t_stat": t_stat,
                        "alpha": fit.alpha,
                        "beta": fit.beta,
                    }
                )

    df_out = pd.DataFrame(records)
    return df_out


def build_and_save_event_study(
    bundle: Any = None,
    project_root: Path | None = None,
) -> pd.DataFrame:
    """Build event study panel and save to data/csv/event_study.csv."""
    from bsp.features.baskets import build_market_data_bundle

    root = project_root or get_project_root()
    bundle = bundle or build_market_data_bundle(root)
    events_path = root / "config" / "budget_events.csv"
    budget_events = pd.read_csv(events_path)

    df_es = run_event_study(bundle, budget_events)

    out_csv = root / "data" / "csv" / "event_study.csv"
    df_es.to_csv(out_csv, index=False, float_format="%.10g")
    return df_es
