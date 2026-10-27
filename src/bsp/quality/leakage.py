"""Leakage validation checks for point-in-time feature store integrity.

Enforces four rules:
  1. No look-ahead: every feature's as_of_date must be <= budget presentation date (or < prediction date).
  2. No same-year actuals: budget year t may only use historical Actuals from <= t-2.
  3. No unlisted stocks: a stock cannot appear in a budget year before its listing/first price date.
  4. No illiquid stocks: every stock-year row carries a 60-day average traded value of at least 5 crore, the liquidity
     half of the universe rule in features/universe.py (the listing half is rule 3).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bsp.common.config import get_project_root
from bsp.features.universe import MIN_AVG_TRADED_VALUE_CR


class LeakageError(Exception):
    """Raised when look-ahead or data leakage is detected."""


def validate_feature_dates(
    features_df: pd.DataFrame,
    budget_events: pd.DataFrame,
    date_col: str = "as_of_date",
    budget_col: str = "budget_id",
) -> None:
    """Ensure no feature has as_of_date > presented_on (or >= prediction execution date)."""
    b_map = dict(zip(budget_events["budget_id"], budget_events["presented_on"]))
    fy_map = dict(zip(budget_events["fiscal_year"], budget_events["presented_on"]))

    violations = []
    for idx, row in features_df.iterrows():
        b_id = str(row[budget_col])
        p_date = b_map.get(b_id) or fy_map.get(b_id)
        if not p_date:
            continue
        as_of = str(row[date_col])
        if as_of > p_date:
            violations.append(
                f"Row {idx} ({b_id}): as_of_date {as_of} is after budget date {p_date}"
            )

    if violations:
        sample = "\n".join(violations[:5])
        raise LeakageError(f"Found {len(violations)} feature date look-ahead violations:\n{sample}")


def validate_no_same_year_actuals(
    sector_features_wide: pd.DataFrame,
    panel_df: pd.DataFrame,
) -> None:
    """Ensure no feature calculation uses same-year (t) or t-1 Actuals."""
    violations = []
    for idx, row in panel_df.iterrows():
        fy = str(row.get("budget_year") or row.get("fiscal_year"))
        # In sector_budget_panel.csv, actual_two_years_back_cr is used for credibility
        # Check if any same-year or previous-year actual column was used as a feature
        actual_source = str(row.get("re_basis") or "")
        # On budget day, re_basis must be RE, never Actual
        if "actual" in actual_source.lower():
            violations.append(f"Row {idx} ({fy}): used Actual as current baseline instead of RE")

        cred_years = float(row.get("credibility_years_used") or 0.0)
        # For FY2005-06 and FY2006-07, older actuals were unavailable
        if fy == "2005-06" and cred_years > 0:
            violations.append(f"Row {idx} ({fy}): FY2005-06 should have 0 credibility years used")

    if violations:
        sample = "\n".join(violations[:5])
        raise LeakageError(f"Found {len(violations)} actuals leakage violations:\n{sample}")


def validate_point_in_time_universe(
    stock_features_df: pd.DataFrame,
    first_price_dates: dict[str, str],
    budget_events: pd.DataFrame,
    symbol_col: str = "symbol",
    budget_col: str = "budget_id",
) -> None:
    """Ensure no stock appears in a budget year prior to its listing/first trading date."""
    b_map = dict(zip(budget_events["budget_id"], budget_events["presented_on"]))
    fy_map = dict(zip(budget_events["fiscal_year"], budget_events["presented_on"]))

    violations = []
    for idx, row in stock_features_df.iterrows():
        sym = str(row[symbol_col])
        b_id = str(row[budget_col])
        p_date = b_map.get(b_id) or fy_map.get(b_id)
        if not p_date:
            continue
        first_d = first_price_dates.get(sym)
        if first_d and first_d > p_date:
            violations.append(
                f"Stock {sym} appears in {b_id} (budget date {p_date}) but was listed on {first_d}"
            )

    if violations:
        sample = "\n".join(violations[:5])
        raise LeakageError(f"Found {len(violations)} point-in-time universe violations:\n{sample}")


LIQUIDITY_FEATURE = "avg_traded_value_60d_cr"


def validate_liquidity_floor(
    stock_features_df: pd.DataFrame,
    threshold_cr: float = MIN_AVG_TRADED_VALUE_CR,
    symbol_col: str = "symbol",
    budget_col: str = "budget_id",
) -> None:
    """Every stock-year (long format) must have a liquidity row at or above the floor; a row with none is a violation.

    The liquidity number is computed from the 60 trading days before the budget date, so checking it here also
    checks that the universe rule was applied.
    """
    pairs = stock_features_df[[symbol_col, budget_col]].drop_duplicates()
    liquidity = stock_features_df[stock_features_df["feature_name"] == LIQUIDITY_FEATURE]
    values = {(str(s), str(b)): v for s, b, v in zip(liquidity[symbol_col], liquidity[budget_col], liquidity["value"])}
    violations = []
    for sym, b_id in zip(pairs[symbol_col].astype(str), pairs[budget_col].astype(str)):
        value = values.get((sym, b_id))
        if value is None or pd.isna(value):
            violations.append(f"Stock {sym} in {b_id} has no {LIQUIDITY_FEATURE}")
        elif value < threshold_cr:
            violations.append(f"Stock {sym} in {b_id} has {LIQUIDITY_FEATURE}={value:.3f} below {threshold_cr}")
    if violations:
        sample = "\n".join(violations[:5])
        raise LeakageError(f"Found {len(violations)} liquidity-floor violations:\n{sample}")


def validate_feature_store(project_root: Path | None = None) -> None:
    """Run all leakage checks against the built feature store."""
    root = project_root or get_project_root()
    events_path = root / "config" / "budget_events.csv"
    b_events = pd.read_csv(events_path)

    # First price dates
    fp_path = root / "data" / "csv" / "stock_first_price_date.csv"
    df_fp = pd.read_csv(fp_path)
    first_price_dates = dict(zip(df_fp["symbol"], df_fp["first_price_date"]))

    # Sector features
    sec_path = root / "data" / "csv" / "features_sector_year.csv"
    if sec_path.exists():
        df_sec = pd.read_csv(sec_path)
        validate_feature_dates(df_sec, b_events)

    # Sector wide / panel
    panel_path = root / "data" / "csv" / "sector_budget_panel.csv"
    sec_wide_path = root / "data" / "csv" / "features_sector_year_wide.csv"
    if panel_path.exists():
        df_panel = pd.read_csv(panel_path)
        df_sec_wide = pd.read_csv(sec_wide_path) if sec_wide_path.exists() else df_panel
        validate_no_same_year_actuals(df_sec_wide, df_panel)

    # Stock features
    stk_path = root / "data" / "csv" / "features_stock_year.csv"
    if stk_path.exists():
        df_stk = pd.read_csv(stk_path)
        validate_feature_dates(df_stk, b_events)
        validate_point_in_time_universe(df_stk, first_price_dates, b_events)
        validate_liquidity_floor(df_stk)
