"""Point-in-time forward return targets over Nifty 500.

Horizons:
  - 12m (budget-to-budget, non-overlapping): primary horizon
  - to_march_31: excess return to end of financial year (next March 31)
  - 5d: 5 trading days post-budget reaction
  - 30d: 30 trading days post-budget reaction

Unresolved targets (e.g. FY2026-27 forward 12-month return) have target_complete = False.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bsp.common.config import get_project_root
from bsp.features.baskets import MarketDataBundle, build_market_data_bundle

HORIZONS = ("12m", "to_march_31", "5d", "30d")


def compute_targets_for_bundle(
    bundle: MarketDataBundle,
    budget_events: pd.DataFrame,
) -> pd.DataFrame:
    """Compute excess return targets for all sectors and stocks across all budgets."""
    trading_days = bundle.trading_days
    max_idx = len(trading_days) - 1

    # Filter to budgets and sort by date
    b_df = budget_events.drop_duplicates(subset=["budget_id"]).sort_values("presented_on").reset_index(drop=True)

    records: list[dict[str, object]] = []

    # Pre-map Day 0 and next trading day (start date) for each budget
    budget_meta: list[dict[str, object]] = []
    for i, b_row in b_df.iterrows():
        b_id = str(b_row["budget_id"])
        p_date = str(b_row["presented_on"])

        cands = [idx for idx, d in enumerate(trading_days) if d >= p_date]
        if not cands:
            continue
        day0_idx = cands[0]
        # Start of post-budget reaction is next trading day if available, else day0
        start_idx = min(max_idx, day0_idx + 1)
        budget_meta.append(
            {
                "budget_id": b_id,
                "presented_on": p_date,
                "day0_idx": day0_idx,
                "start_idx": start_idx,
                "order": i,
            }
        )

    for meta in budget_meta:
        b_id = str(meta["budget_id"])
        p_date = str(meta["presented_on"])
        day0_idx = int(str(meta["day0_idx"]))
        start_idx = int(str(meta["start_idx"]))
        order_idx = int(str(meta["order"]))

        # Determine target end dates for each horizon:
        # 1. 12m (Budget-to-budget): Next budget's day0
        next_budget_day0_idx: int | None = None
        if order_idx + 1 < len(budget_meta):
            next_budget_day0_idx = int(str(budget_meta[order_idx + 1]["day0_idx"]))

        # 2. to_march_31: next March 31 trading day
        p_year = int(p_date[:4])
        p_month = int(p_date[5:7])
        target_year = p_year if p_month <= 3 else p_year + 1
        march31_str = f"{target_year}-03-31"
        march_cands = [idx for idx, d in enumerate(trading_days) if d <= march31_str and idx >= start_idx]
        march_idx = march_cands[-1] if march_cands else None

        # 3. 5d
        d5_idx = min(max_idx, start_idx + 4) if start_idx + 4 <= max_idx else None

        # 4. 30d
        d30_idx = min(max_idx, start_idx + 29) if start_idx + 29 <= max_idx else None

        # Entities: 15 sectors
        for sec_id in bundle.sector_returns.columns:
            sec_cum = (1.0 + bundle.sector_returns[sec_id].fillna(0.0)).cumprod()
            mkt_cum = (1.0 + bundle.market_returns.fillna(0.0)).cumprod()

            for h in HORIZONS:
                excess_ret: float | None = None
                complete = True

                if h == "12m":
                    if next_budget_day0_idx is not None and next_budget_day0_idx > start_idx:
                        r_sec = float((sec_cum.iloc[next_budget_day0_idx] / sec_cum.iloc[start_idx]) - 1.0)
                        r_mkt = float((mkt_cum.iloc[next_budget_day0_idx] / mkt_cum.iloc[start_idx]) - 1.0)
                        excess_ret = r_sec - r_mkt
                        complete = True
                    else:
                        excess_ret = None
                        complete = False
                elif h == "to_march_31":
                    if march_idx is not None and march_idx >= start_idx:
                        r_sec = float((sec_cum.iloc[march_idx] / sec_cum.iloc[start_idx]) - 1.0)
                        r_mkt = float((mkt_cum.iloc[march_idx] / mkt_cum.iloc[start_idx]) - 1.0)
                        excess_ret = r_sec - r_mkt
                        complete = True
                    else:
                        excess_ret = None
                        complete = False
                elif h == "5d":
                    if d5_idx is not None:
                        r_sec = float((sec_cum.iloc[d5_idx] / sec_cum.iloc[start_idx]) - 1.0)
                        r_mkt = float((mkt_cum.iloc[d5_idx] / mkt_cum.iloc[start_idx]) - 1.0)
                        excess_ret = r_sec - r_mkt
                        complete = True
                    else:
                        excess_ret = None
                        complete = False
                elif h == "30d":
                    if d30_idx is not None:
                        r_sec = float((sec_cum.iloc[d30_idx] / sec_cum.iloc[start_idx]) - 1.0)
                        r_mkt = float((mkt_cum.iloc[d30_idx] / mkt_cum.iloc[start_idx]) - 1.0)
                        excess_ret = r_sec - r_mkt
                        complete = True
                    else:
                        excess_ret = None
                        complete = False

                records.append(
                    {
                        "entity": sec_id,
                        "entity_type": "sector",
                        "budget_id": b_id,
                        "horizon": h,
                        "excess_return": excess_ret,
                        "target_complete": complete,
                    }
                )

        # Entities: Stocks
        for sym in bundle.stock_prices.columns:
            first_d = bundle.first_price_dates.get(sym)
            if first_d and first_d > p_date:
                # Stock was not listed on budget day
                continue

            prices_s = bundle.stock_prices[sym]
            p_start = prices_s.iloc[start_idx]
            if pd.isna(p_start) or p_start <= 0:
                continue

            mkt_cum = (1.0 + bundle.market_returns.fillna(0.0)).cumprod()

            for h in HORIZONS:
                excess_ret = None
                complete = True

                if h == "12m":
                    if next_budget_day0_idx is not None and next_budget_day0_idx > start_idx:
                        p_end = prices_s.iloc[next_budget_day0_idx]
                        if pd.notna(p_end) and p_end > 0:
                            r_stk = float((p_end / p_start) - 1.0)
                            r_mkt = float((mkt_cum.iloc[next_budget_day0_idx] / mkt_cum.iloc[start_idx]) - 1.0)
                            excess_ret = r_stk - r_mkt
                            complete = True
                        else:
                            complete = False
                    else:
                        complete = False
                elif h == "to_march_31":
                    if march_idx is not None and march_idx >= start_idx:
                        p_end = prices_s.iloc[march_idx]
                        if pd.notna(p_end) and p_end > 0:
                            r_stk = float((p_end / p_start) - 1.0)
                            r_mkt = float((mkt_cum.iloc[march_idx] / mkt_cum.iloc[start_idx]) - 1.0)
                            excess_ret = r_stk - r_mkt
                            complete = True
                        else:
                            complete = False
                    else:
                        complete = False
                elif h == "5d":
                    if d5_idx is not None:
                        p_end = prices_s.iloc[d5_idx]
                        if pd.notna(p_end) and p_end > 0:
                            r_stk = float((p_end / p_start) - 1.0)
                            r_mkt = float((mkt_cum.iloc[d5_idx] / mkt_cum.iloc[start_idx]) - 1.0)
                            excess_ret = r_stk - r_mkt
                            complete = True
                        else:
                            complete = False
                    else:
                        complete = False
                elif h == "30d":
                    if d30_idx is not None:
                        p_end = prices_s.iloc[d30_idx]
                        if pd.notna(p_end) and p_end > 0:
                            r_stk = float((p_end / p_start) - 1.0)
                            r_mkt = float((mkt_cum.iloc[d30_idx] / mkt_cum.iloc[start_idx]) - 1.0)
                            excess_ret = r_stk - r_mkt
                            complete = True
                        else:
                            complete = False
                    else:
                        complete = False

                records.append(
                    {
                        "entity": sym,
                        "entity_type": "stock",
                        "budget_id": b_id,
                        "horizon": h,
                        "excess_return": excess_ret,
                        "target_complete": complete,
                    }
                )

    df_out = pd.DataFrame(records)
    return df_out


def build_and_save_targets(
    bundle: MarketDataBundle | None = None,
    project_root: Path | None = None,
) -> pd.DataFrame:
    """Build targets for all entities and save to data/csv/targets.csv."""
    root = project_root or get_project_root()
    bundle = bundle or build_market_data_bundle(root)
    events_path = root / "config" / "budget_events.csv"
    budget_events = pd.read_csv(events_path)

    df_targets = compute_targets_for_bundle(bundle, budget_events)

    out_csv = root / "data" / "csv" / "targets.csv"
    df_targets.to_csv(out_csv, index=False)
    return df_targets
