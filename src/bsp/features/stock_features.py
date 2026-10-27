"""Stock-year point-in-time features builder.

Features:
  - momentum_1m, momentum_3m, momentum_6m, momentum_12m
  - volatility_30d, volatility_90d
  - liquidity_90d (average daily traded value in crore)
  - beta_250d (market model beta vs Nifty 500 on [-250, -31])
  - beta_90d (short-horizon beta on [-90, -1])
  - size_traded_val (log1p of average daily traded value in crore)

  - avg_traded_value_60d_cr (the liquidity number the universe rule uses; the 60 trading days before the budget date)

Universe (features/universe.py): a stock gets a row for a budget only if it is listed on or before the budget date AND
its average daily traded value over the prior 60 trading days is at least 5 crore. Index membership is not checked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bsp.common.config import get_project_root
from bsp.events.study import fit_market_model
from bsp.features.baskets import MarketDataBundle, build_market_data_bundle
from bsp.features.universe import (
    ILLIQUID,
    NOT_LISTED,
    average_traded_value_cr,
    classify,
    prior_window,
)


def build_stock_features(
    bundle: MarketDataBundle | None = None,
    project_root: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build point-in-time features for all stock-years.

    Returns:
      (df_long, df_wide)
      where df_long matches database table features_stock_year:
        symbol, budget_id, feature_name, value, as_of_date
    """
    root = project_root or get_project_root()
    bundle = bundle or build_market_data_bundle(root)

    events_path = root / "config" / "budget_events.csv"
    df_events = (
        pd.read_csv(events_path)
        .drop_duplicates(subset=["budget_id"])
        .sort_values("presented_on")
        .reset_index(drop=True)
    )

    trading_days = bundle.trading_days
    mkt_returns = bundle.market_returns.values

    long_records: list[dict[str, Any]] = []
    wide_records: list[dict[str, Any]] = []
    universe_report: list[dict[str, Any]] = []

    for _, b_row in df_events.iterrows():
        b_id = str(b_row["budget_id"])
        fy = str(b_row["fiscal_year"])
        p_date = str(b_row["presented_on"])

        # Trading day on or before presented_on
        past_indices = [i for i, d in enumerate(trading_days) if d <= p_date]
        if not past_indices:
            continue
        curr_idx = past_indices[-1]
        as_of_date = min(p_date, trading_days[curr_idx])

        # Market return slice for beta estimation
        # Estimation window [-250, -31]
        est_start = max(0, curr_idx - 250)
        est_end = max(0, curr_idx - 30)  # exclusive end: day -31 is the last estimation day
        mkt_est = mkt_returns[est_start:est_end] if est_end > est_start else np.array([])

        # Short window [-90, -1]
        s90_start = max(0, curr_idx - 90)
        s90_end = max(0, curr_idx)
        mkt_90 = mkt_returns[s90_start:s90_end] if s90_end > s90_start else np.array([])

        report_row: dict[str, Any] = {"budget_id": b_id, "presented_on": p_date, "candidates": 0,
                                      "dropped_not_listed": 0, "dropped_liquidity": 0, "dropped_no_price": 0,
                                      "short_history_kept": 0, "kept": 0}
        universe_report.append(report_row)

        for sym in bundle.stock_prices.columns:
            report_row["candidates"] += 1
            traded = (bundle.stock_traded_val[sym] if sym in bundle.stock_traded_val.columns
                      else pd.Series(np.nan, index=bundle.stock_prices.index))
            liquidity = average_traded_value_cr(traded, trading_days, p_date)
            verdict = classify(bundle.first_price_dates.get(sym), p_date, liquidity)
            if verdict == NOT_LISTED:
                report_row["dropped_not_listed"] += 1  # first trading day is after the budget date
                continue
            if verdict == ILLIQUID:
                report_row["dropped_liquidity"] += 1  # average traded value over the prior 60 days is below 5 crore
                continue

            prices_s = bundle.stock_prices[sym]
            p_curr = prices_s.iloc[curr_idx]
            if pd.isna(p_curr) or p_curr <= 0:
                report_row["dropped_no_price"] += 1  # listed and liquid, but no valid close on the as-of day
                continue
            first_d = bundle.first_price_dates.get(sym)
            if first_d is not None and first_d > trading_days[prior_window(trading_days, p_date)[0]]:
                report_row["short_history_kept"] += 1  # listed inside the 60-day window: its average uses fewer days

            sec_id = bundle.stock_sector_map.get(sym, "unknown")
            ret_s = bundle.stock_returns[sym]
            traded_val_s = (
                bundle.stock_traded_val[sym]
                if sym in bundle.stock_traded_val.columns
                else pd.Series(np.nan, index=bundle.stock_prices.index)
            )

            features: dict[str, float | None] = {}

            # 1. Momentum: 1m (21d), 3m (63d), 6m (126d), 12m (252d)
            if curr_idx >= 5:
                p_1m = prices_s.iloc[max(0, curr_idx - 21)]
                features["momentum_1m"] = float((p_curr / p_1m) - 1.0) if pd.notna(p_1m) and p_1m > 0 else None
            else:
                features["momentum_1m"] = None

            if curr_idx >= 15:
                p_3m = prices_s.iloc[max(0, curr_idx - 63)]
                features["momentum_3m"] = float((p_curr / p_3m) - 1.0) if pd.notna(p_3m) and p_3m > 0 else None
            else:
                features["momentum_3m"] = None

            if curr_idx >= 30:
                p_6m = prices_s.iloc[max(0, curr_idx - 126)]
                features["momentum_6m"] = float((p_curr / p_6m) - 1.0) if pd.notna(p_6m) and p_6m > 0 else None
            else:
                features["momentum_6m"] = None

            if curr_idx >= 60:
                p_12m = prices_s.iloc[max(0, curr_idx - 252)]
                if pd.notna(p_12m) and p_12m > 0:
                    features["momentum_12m"] = float((p_curr / p_12m) - 1.0)
                else:
                    # Fall back to return since earliest available valid price
                    valid_sub = prices_s.iloc[:curr_idx].dropna()
                    features["momentum_12m"] = (
                        float((p_curr / valid_sub.iloc[0]) - 1.0) if len(valid_sub) >= 60 else None
                    )
            else:
                features["momentum_12m"] = None

            # 2. Volatility (30d, 90d daily return std)
            w30 = ret_s.iloc[max(0, curr_idx - 30) : curr_idx + 1].dropna()
            features["volatility_30d"] = float(w30.std()) if len(w30) >= 10 else None

            w90 = ret_s.iloc[max(0, curr_idx - 90) : curr_idx + 1].dropna()
            features["volatility_90d"] = float(w90.std()) if len(w90) >= 20 else None

            # 3. Liquidity (90d average daily traded value in crore)
            t90 = traded_val_s.iloc[max(0, curr_idx - 90) : curr_idx + 1].dropna()
            liq_90 = float(t90.mean()) if len(t90) >= 15 else None
            features["liquidity_90d"] = liq_90
            features["avg_traded_value_60d_cr"] = liquidity.average_cr
            features["size_traded_val"] = float(np.log1p(liq_90)) if liq_90 is not None and liq_90 >= 0 else None

            # 4. Beta vs Nifty 500
            # 250d beta
            if len(mkt_est) >= 15:
                stk_est = np.asarray(ret_s.iloc[est_start:est_end].values)
                fit_250 = fit_market_model(stk_est, np.asarray(mkt_est))
                features["beta_250d"] = fit_250.beta if fit_250 else None
            else:
                features["beta_250d"] = None

            # 90d beta
            if len(mkt_90) >= 15:
                stk_90 = np.asarray(ret_s.iloc[s90_start:s90_end].values)
                fit_90 = fit_market_model(stk_90, np.asarray(mkt_90))
                features["beta_90d"] = fit_90.beta if fit_90 else None
            else:
                features["beta_90d"] = None

            # Build wide row
            wide_row: dict[str, Any] = {
                "symbol": sym,
                "sector_id": sec_id,
                "budget_id": b_id,
                "fiscal_year": fy,
                "presented_on": p_date,
                "as_of_date": as_of_date,
                **features,
            }
            wide_records.append(wide_row)

            # Build long rows
            for fname, fval in features.items():
                long_records.append(
                    {
                        "symbol": sym,
                        "budget_id": b_id,
                        "feature_name": fname,
                        "value": fval,
                        "as_of_date": as_of_date,
                    }
                )

    df_long = pd.DataFrame(long_records)
    df_wide = pd.DataFrame(wide_records)
    if len(df_wide):
        counts = df_wide.groupby("budget_id").size()
        for row in universe_report:
            row["kept"] = int(counts.get(row["budget_id"], 0))
    df_wide.attrs["universe_report"] = universe_report
    return df_long, df_wide


def build_and_save_stock_features(
    bundle: MarketDataBundle | None = None,
    project_root: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build and save stock-year features to CSVs."""
    root = project_root or get_project_root()
    df_long, df_wide = build_stock_features(bundle, root)

    out_long = root / "data" / "csv" / "features_stock_year.csv"
    out_wide = root / "data" / "csv" / "features_stock_year_wide.csv"

    df_long.to_csv(out_long, index=False, float_format="%.10g")
    df_wide.to_csv(out_wide, index=False, float_format="%.10g")
    report_dir = root / "reports"
    report_dir.mkdir(exist_ok=True)
    pd.DataFrame(df_wide.attrs.get("universe_report", [])).to_csv(report_dir / "universe_filter.csv", index=False)
    return df_long, df_wide
