"""Sector-year point-in-time features builder.

Features:
  - Allocation level & growth (be_current_cr, growth_vs_prev_be_pct, be_previous_cr, re_previous_cr)
  - Surprise vs previous RE (alloc_vs_prev_re_pct)
  - 3-year execution credibility (credibility_pct, credibility_years_used)
  - Capex ratio (capex_share_be_pct)
  - Scheme-level push (scheme_push_total_cr)
  - Fiscal-stance controls (fiscal_total_expenditure_cr, fiscal_deficit_be_cr, fiscal_subsidies_cr)
  - Pre-budget momentum (momentum_1m, momentum_3m, momentum_6m, momentum_12m)
  - Pre-budget volatility (volatility_30d, volatility_90d)
  - Pre-budget FPI flow (fpi_net_equity_1f_cr, fpi_net_equity_1m_cr, fpi_equity_aum_cr)
  - Macro controls (macro_usd_inr, macro_usd_inr_1y_pct, macro_brent_crude_usd,
                    macro_brent_crude_1y_pct, macro_policy_rate, macro_cpi_inflation, macro_gdp_growth)
  - Regime flags (regime_is_interim, regime_is_election_year, regime_is_covid_era, regime_high_vix)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from bsp.common.config import get_project_root
from bsp.features.baskets import MarketDataBundle, build_market_data_bundle
from bsp.features.fpi_window import expected_periods


def load_macro_series(project_root: Path | None = None) -> pd.DataFrame:
    root = project_root or get_project_root()
    path = root / "data" / "csv" / "macro.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["date"] = df["date"].astype(str)
    return df


def load_fpi_flows(project_root: Path | None = None) -> pd.DataFrame:
    root = project_root or get_project_root()
    path = root / "data" / "csv" / "fpi_sector_fortnightly.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["period_end"] = df["period_end"].astype(str)
    return df


def load_fiscal_data(project_root: Path | None = None) -> pd.DataFrame:
    root = project_root or get_project_root()
    path = root / "data" / "csv" / "budget_fiscal.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_schemes_data(project_root: Path | None = None) -> pd.DataFrame:
    root = project_root or get_project_root()
    path = root / "data" / "csv" / "budget_schemes.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def build_sector_features(
    bundle: MarketDataBundle | None = None,
    project_root: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build point-in-time features for all sector-years.

    Returns:
      (df_long, df_wide)
      where df_long matches database table features_sector_year:
        sector_id, budget_id, feature_name, value, as_of_date
    """
    root = project_root or get_project_root()
    bundle = bundle or build_market_data_bundle(root)

    panel_path = root / "data" / "csv" / "sector_budget_panel.csv"
    events_path = root / "config" / "budget_events.csv"
    sec_map_path = root / "config" / "sector_map.json"

    df_panel = pd.read_csv(panel_path)
    df_events = pd.read_csv(events_path).drop_duplicates(subset=["budget_id"])
    with sec_map_path.open("r", encoding="utf-8") as fh:
        sector_map_data = json.load(fh)

    # Sector ID -> NSDL FPI sector mapping
    sec_fpi_map: dict[str, str] = {}
    sec_lines_map: dict[str, list[str]] = {}
    for s in sector_map_data.get("sectors", []):
        sec_fpi_map[s["sector_id"]] = s.get("nsdl_fpi_sector", "")
        sec_lines_map[s["sector_id"]] = [line.lower() for line in s.get("budget_lines", [])]

    # Map events by fiscal_year
    event_by_fy: dict[str, dict[str, Any]] = {}
    for _, erow in df_events.iterrows():
        fy = str(erow["fiscal_year"])
        b_type = str(erow.get("budget_type", "full"))
        if b_type == "full" or fy not in event_by_fy:
            event_by_fy[fy] = dict(erow)

    df_macro = load_macro_series(root)
    df_fpi = load_fpi_flows(root)
    df_fiscal = load_fiscal_data(root)
    df_schemes = load_schemes_data(root)

    # Pre-index macro series
    macro_by_series: dict[str, pd.DataFrame] = {}
    if not df_macro.empty:
        for sname, grp in df_macro.groupby("series"):
            macro_by_series[str(sname)] = grp.sort_values("date")

    # Index Daily for VIX
    index_path = root / "data" / "csv" / "index_daily.csv"
    df_idx = pd.read_csv(index_path)
    df_idx["date"] = df_idx["date"].astype(str)
    vix_df = df_idx[df_idx["index_name"] == "India VIX"].sort_values("date")

    trading_days = bundle.trading_days

    long_records: list[dict[str, Any]] = []
    wide_records: list[dict[str, Any]] = []

    # Sort panel by budget_year and sector_id
    for _, row in df_panel.iterrows():
        sec_id = str(row["sector_id"])
        fy = str(row["budget_year"])
        event = event_by_fy.get(fy, {})
        b_id = str(event.get("budget_id", f"FY{fy}"))
        p_date = str(row.get("budget_date") or event.get("presented_on", "2005-02-28"))

        # Find trading day on or before p_date
        past_tds = [d for d in trading_days if d <= p_date]
        as_of_trading_day = past_tds[-1] if past_tds else p_date
        as_of_date = min(p_date, as_of_trading_day)

        features: dict[str, float | None] = {}

        # 1. Budget Money & Growth
        features["be_current_cr"] = float(row["be_current_cr"]) if pd.notna(row.get("be_current_cr")) else None
        features["growth_vs_prev_be_pct"] = (
            float(row["growth_vs_prev_be_pct"]) if pd.notna(row.get("growth_vs_prev_be_pct")) else None
        )
        features["be_previous_cr"] = float(row["be_previous_cr"]) if pd.notna(row.get("be_previous_cr")) else None
        features["re_previous_cr"] = float(row["re_previous_cr"]) if pd.notna(row.get("re_previous_cr")) else None

        # 2. Surprise vs RE
        features["alloc_vs_prev_re_pct"] = (
            float(row["surprise_vs_prev_re_pct"]) if pd.notna(row.get("surprise_vs_prev_re_pct")) else None
        )

        # 3. Credibility (3-year execution gap using past Actuals only)
        features["credibility_pct"] = (
            float(row["credibility_pct"]) if pd.notna(row.get("credibility_pct")) else None
        )
        features["credibility_years_used"] = (
            float(row["credibility_years_used"]) if pd.notna(row.get("credibility_years_used")) else 0.0
        )

        # 4. Capex ratio
        features["capex_share_be_pct"] = (
            float(row["capex_share_be_pct"]) if pd.notna(row.get("capex_share_be_pct")) else None
        )

        # 5. Scheme-level push
        scheme_tot = 0.0
        scheme_found = False
        if not df_schemes.empty and "fiscal_year" in df_schemes.columns:
            m_schemes = df_schemes[
                (df_schemes["fiscal_year"] == fy) & (df_schemes["stage"] == "BE")
            ]
            lines = sec_lines_map.get(sec_id, [])
            for _, s_row in m_schemes.iterrows():
                c_name = str(s_row.get("canonical_name") or s_row.get("line_item", "")).lower()
                if any(k in c_name for k in lines if len(k) > 3):
                    amt = float(s_row.get("amount_cr") or 0.0)
                    scheme_tot += amt
                    scheme_found = True
        features["scheme_push_total_cr"] = scheme_tot if scheme_found else None

        # 6. Fiscal Stance (from budget_fiscal)
        f_exp: float | None = None
        f_def: float | None = None
        f_sub: float | None = None
        if not df_fiscal.empty and "fiscal_year" in df_fiscal.columns:
            m_fiscal = df_fiscal[(df_fiscal["fiscal_year"] == fy) & (df_fiscal["stage"] == "BE")]
            for _, fi_row in m_fiscal.iterrows():
                item_name = str(fi_row.get("line_item", "")).lower()
                raw_amt = fi_row.get("amount_cr")
                if pd.notna(raw_amt):
                    f_val = float(raw_amt)
                    if "total expenditure" in item_name and f_exp is None:
                        f_exp = f_val
                    elif "fiscal deficit" in item_name and f_def is None:
                        f_def = f_val
                    elif "subsidies" in item_name and f_sub is None:
                        f_sub = f_val
        features["fiscal_total_expenditure_cr"] = f_exp
        features["fiscal_deficit_be_cr"] = f_def
        features["fiscal_subsidies_cr"] = f_sub

        # 7. Pre-budget Price Momentum (1m, 3m, 6m, 12m)
        sec_ret = bundle.sector_returns[sec_id]
        past_idx = [i for i, d in enumerate(trading_days) if d <= p_date]
        first_active = bundle.sector_first_active_idx.get(sec_id)
        features["basket_active_stocks"] = (
            float(bundle.sector_stock_count[sec_id].iloc[past_idx[-1]])
            if past_idx and sec_id in bundle.sector_stock_count.columns else None
        )
        # A basket with no stock yet on the as-of day has no price history: its price features are MISSING, not a flat 0%.
        if past_idx and first_active is not None and past_idx[-1] >= first_active:
            curr_idx = past_idx[-1]
            cum_sec = (1.0 + sec_ret.fillna(0.0)).cumprod()
            curr_val = cum_sec.iloc[curr_idx]

            features["momentum_1m"] = (
                float((curr_val / cum_sec.iloc[max(0, curr_idx - 21)]) - 1.0) if curr_idx >= 5 else None
            )
            features["momentum_3m"] = (
                float((curr_val / cum_sec.iloc[max(0, curr_idx - 63)]) - 1.0) if curr_idx >= 15 else None
            )
            features["momentum_6m"] = (
                float((curr_val / cum_sec.iloc[max(0, curr_idx - 126)]) - 1.0) if curr_idx >= 30 else None
            )
            features["momentum_12m"] = (
                float((curr_val / cum_sec.iloc[max(0, curr_idx - 252)]) - 1.0) if curr_idx >= 60 else None
            )

            # 8. Volatility (30d, 90d)
            w30 = sec_ret.iloc[max(0, curr_idx - 30) : curr_idx + 1].dropna()
            features["volatility_30d"] = float(w30.std()) if len(w30) >= 10 else None
            w90 = sec_ret.iloc[max(0, curr_idx - 90) : curr_idx + 1].dropna()
            features["volatility_90d"] = float(w90.std()) if len(w90) >= 20 else None
        else:
            features["momentum_1m"] = None
            features["momentum_3m"] = None
            features["momentum_6m"] = None
            features["momentum_12m"] = None
            features["volatility_30d"] = None
            features["volatility_90d"] = None

        # 9. FPI Flows: only from the exact reports of the lookback window (features/fpi_window.py). A missing report
        # leaves the feature missing; it is never filled with 0 or with an older report.
        features["fpi_net_equity_1f_cr"] = None
        features["fpi_net_equity_1m_cr"] = None
        features["fpi_equity_aum_cr"] = None
        nsdl_sec = sec_fpi_map.get(sec_id, "")
        if nsdl_sec and not df_fpi.empty:
            earlier_end, latest_end = expected_periods(p_date)
            by_period = {
                str(r["period_end"]): r
                for r in df_fpi[df_fpi["nsdl_sector"] == nsdl_sec].drop_duplicates("period_end").to_dict("records")
            }
            latest, earlier = by_period.get(latest_end), by_period.get(earlier_end)
            if latest is not None:
                net_latest = latest.get("equity_net_cr")
                features["fpi_net_equity_1f_cr"] = float(net_latest) if pd.notna(net_latest) else None
                aum = latest.get("equity_aum_cr")
                features["fpi_equity_aum_cr"] = float(aum) if pd.notna(aum) else None
                if earlier is not None and pd.notna(net_latest) and pd.notna(earlier.get("equity_net_cr")):
                    features["fpi_net_equity_1m_cr"] = float(net_latest) + float(earlier["equity_net_cr"])

        # 10. Macro Controls
        # USD/INR
        usd_df = macro_by_series.get("usd_inr")
        if usd_df is not None:
            sub = usd_df[usd_df["date"] <= p_date]
            if not sub.empty:
                v_curr = float(sub.iloc[-1]["value"])
                features["macro_usd_inr"] = v_curr
                # 1y prior
                sub_1y = sub[sub["date"] <= str(pd.to_datetime(p_date) - pd.DateOffset(years=1))[:10]]
                if not sub_1y.empty:
                    v_prev = float(sub_1y.iloc[-1]["value"])
                    features["macro_usd_inr_1y_pct"] = float((v_curr / v_prev) - 1.0)
                else:
                    features["macro_usd_inr_1y_pct"] = None
            else:
                features["macro_usd_inr"] = None
                features["macro_usd_inr_1y_pct"] = None
        else:
            features["macro_usd_inr"] = None
            features["macro_usd_inr_1y_pct"] = None

        # Brent crude
        brent_df = macro_by_series.get("brent_crude_usd")
        if brent_df is None:
            brent_df = macro_by_series.get("wti_crude_usd")
        if brent_df is not None:
            sub = brent_df[brent_df["date"] <= p_date]
            if not sub.empty:
                v_curr = float(sub.iloc[-1]["value"])
                features["macro_brent_crude_usd"] = v_curr
                sub_1y = sub[sub["date"] <= str(pd.to_datetime(p_date) - pd.DateOffset(years=1))[:10]]
                if not sub_1y.empty:
                    v_prev = float(sub_1y.iloc[-1]["value"])
                    features["macro_brent_crude_1y_pct"] = float((v_curr / v_prev) - 1.0)
                else:
                    features["macro_brent_crude_1y_pct"] = None
            else:
                features["macro_brent_crude_usd"] = None
                features["macro_brent_crude_1y_pct"] = None
        else:
            features["macro_brent_crude_usd"] = None
            features["macro_brent_crude_1y_pct"] = None

        # Policy rate
        pol_df = macro_by_series.get("policy_discount_rate")
        if pol_df is not None:
            sub = pol_df[pol_df["date"] <= p_date]
            features["macro_policy_rate"] = float(sub.iloc[-1]["value"]) if not sub.empty else None
        else:
            features["macro_policy_rate"] = None

        # CPI inflation
        cpi_df = macro_by_series.get("cpi_inflation_annual")
        if cpi_df is not None:
            sub = cpi_df[cpi_df["date"] <= p_date]
            features["macro_cpi_inflation"] = float(sub.iloc[-1]["value"]) if not sub.empty else None
        else:
            features["macro_cpi_inflation"] = None

        # GDP growth
        gdp_df = macro_by_series.get("gdp_growth_annual")
        if gdp_df is not None:
            sub = gdp_df[gdp_df["date"] <= p_date]
            features["macro_gdp_growth"] = float(sub.iloc[-1]["value"]) if not sub.empty else None
        else:
            features["macro_gdp_growth"] = None

        # 11. Regime Flags
        features["regime_is_interim"] = 1.0 if bool(event.get("is_interim", False)) else 0.0
        features["regime_is_election_year"] = 1.0 if bool(event.get("is_election_year", False)) else 0.0
        features["regime_is_covid_era"] = 1.0 if fy in ("2021-22", "2022-23") else 0.0

        # High VIX flag: VIX > 20 on budget day
        is_high_vix = 0.0
        if not vix_df.empty:
            v_sub = vix_df[vix_df["date"] <= p_date]
            if not v_sub.empty:
                v_last = float(v_sub.iloc[-1]["close"])
                if v_last > 20.0:
                    is_high_vix = 1.0
        features["regime_high_vix"] = is_high_vix

        # Add to wide record
        wide_row: dict[str, Any] = {
            "sector_id": sec_id,
            "sector_name": row.get("sector_name", sec_id),
            "budget_id": b_id,
            "fiscal_year": fy,
            "presented_on": p_date,
            "as_of_date": as_of_date,
            **features,
        }
        wide_records.append(wide_row)

        # Add to long records
        for fname, fval in features.items():
            long_records.append(
                {
                    "sector_id": sec_id,
                    "budget_id": b_id,
                    "feature_name": fname,
                    "value": fval,
                    "as_of_date": as_of_date,
                }
            )

    df_long = pd.DataFrame(long_records)
    df_wide = pd.DataFrame(wide_records)
    return df_long, df_wide


def build_and_save_sector_features(
    bundle: MarketDataBundle | None = None,
    project_root: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build and save sector-year features to CSVs."""
    root = project_root or get_project_root()
    df_long, df_wide = build_sector_features(bundle, root)

    out_long = root / "data" / "csv" / "features_sector_year.csv"
    out_wide = root / "data" / "csv" / "features_sector_year_wide.csv"

    df_long.to_csv(out_long, index=False, float_format="%.10g")
    df_wide.to_csv(out_wide, index=False, float_format="%.10g")
    return df_long, df_wide
