"""Self-built sector baskets and benchmark returns.

Each basket is an equal-weight index of the mapped stocks, with each stock
entering only from its listing/first price date.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from bsp.common.config import get_project_root


@dataclass
class MarketDataBundle:
    """In-memory bundle of aligned market series."""

    trading_days: list[str]
    stock_returns: pd.DataFrame
    stock_prices: pd.DataFrame
    stock_traded_val: pd.DataFrame
    sector_returns: pd.DataFrame
    market_returns: pd.Series
    first_price_dates: dict[str, str]
    sector_stocks_map: dict[str, list[str]]
    stock_sector_map: dict[str, str]


def load_sector_map(project_root: Path | None = None) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Return sector -> list[symbol] and symbol -> sector mapping."""
    root = project_root or get_project_root()
    sector_map_path = root / "config" / "sector_map.json"
    with sector_map_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    sector_stocks: dict[str, list[str]] = {}
    stock_sector: dict[str, str] = {}
    for sector in data.get("sectors", []):
        sec_id = sector["sector_id"]
        symbols = [s["symbol"] for s in sector.get("stocks", [])]
        sector_stocks[sec_id] = symbols
        for sym in symbols:
            stock_sector[sym] = sec_id
    return sector_stocks, stock_sector


def load_first_price_dates(project_root: Path | None = None) -> dict[str, str]:
    """Load stock symbol -> first trading day mapping."""
    root = project_root or get_project_root()
    path = root / "data" / "csv" / "stock_first_price_date.csv"
    if not path.exists():
        # Fall back to stocks.csv or prices_daily.csv
        stocks_path = root / "config" / "stocks.csv"
        df_stocks = pd.read_csv(stocks_path)
        return {
            row["symbol"]: str(row["listing_date"])
            for _, row in df_stocks.iterrows()
            if pd.notna(row.get("listing_date"))
        }
    df = pd.read_csv(path)
    return dict(zip(df["symbol"], df["first_price_date"]))


def build_market_data_bundle(project_root: Path | None = None) -> MarketDataBundle:
    """Load daily stock prices, build self-built sector baskets and aligned market return."""
    root = project_root or get_project_root()
    prices_path = root / "data" / "csv" / "prices_daily.csv"
    index_path = root / "data" / "csv" / "index_daily.csv"

    first_price_dates = load_first_price_dates(root)
    sector_stocks, stock_sector = load_sector_map(root)

    # 1. Load prices_daily
    usecols = ["symbol", "date", "close", "adj_close", "traded_value_cr"]
    df_prices = pd.read_csv(prices_path, usecols=usecols)
    df_prices["date"] = df_prices["date"].astype(str)

    # Use adj_close if available and positive, else close
    price_col = "adj_close" if "adj_close" in df_prices.columns else "close"
    df_prices["effective_price"] = np.where(
        df_prices[price_col].notna() & (df_prices[price_col] > 0),
        df_prices[price_col],
        df_prices["close"],
    )

    # Pivot price and traded value
    pvt_price = df_prices.pivot(index="date", columns="symbol", values="effective_price").sort_index()
    pvt_traded_val = df_prices.pivot(index="date", columns="symbol", values="traded_value_cr").sort_index()

    # Enforce point-in-time listing filter: mask dates before first_price_date
    for sym in pvt_price.columns:
        first_d = first_price_dates.get(sym)
        if first_d:
            pvt_price.loc[pvt_price.index < first_d, sym] = np.nan
            if sym in pvt_traded_val.columns:
                pvt_traded_val.loc[pvt_traded_val.index < first_d, sym] = np.nan

    # Calculate stock daily returns
    stock_returns = pvt_price.pct_change(fill_method=None)

    # 2. Build self-built equal-weight sector basket returns
    trading_days = list(stock_returns.index)
    sec_ret_dict: dict[str, pd.Series] = {}

    for sec_id, symbols in sector_stocks.items():
        valid_syms = [s for s in symbols if s in stock_returns.columns]
        if not valid_syms:
            sec_ret_dict[sec_id] = pd.Series(np.nan, index=stock_returns.index)
            continue
        # Equal-weighted mean of available, listed stocks on that date
        sec_ret_dict[sec_id] = stock_returns[valid_syms].mean(axis=1, skipna=True)

    sector_returns = pd.DataFrame(sec_ret_dict, index=stock_returns.index)

    # 3. Market return: Nifty 500 bridged by universe equal-weight before Nifty 500 start
    univ_eq_ret = stock_returns.mean(axis=1, skipna=True)
    df_idx = pd.read_csv(index_path)
    df_idx["date"] = df_idx["date"].astype(str)
    n500 = (
        df_idx[df_idx["index_name"] == "Nifty 500"]
        .set_index("date")["close"]
        .sort_index()
    )
    n500_ret = n500.pct_change(fill_method=None)

    market_returns = n500_ret.reindex(stock_returns.index)
    # Bridge dates before Nifty 500 availability
    market_returns = market_returns.combine_first(univ_eq_ret)

    # Save sector baskets to data/csv/sector_baskets_daily.csv
    baskets_records = []
    for sec_id in sector_returns.columns:
        ret_s = sector_returns[sec_id]
        cum_idx = 100.0 * (1.0 + ret_s.fillna(0.0)).cumprod()
        valid_syms = [s for s in sector_stocks.get(sec_id, []) if s in stock_returns.columns]
        n_stocks = (
            stock_returns[valid_syms].notna().sum(axis=1) if valid_syms else pd.Series(0, index=stock_returns.index)
        )
        for d in trading_days:
            baskets_records.append(
                {
                    "sector_id": sec_id,
                    "date": d,
                    "daily_return": ret_s.loc[d] if pd.notna(ret_s.loc[d]) else None,
                    "index_level": cum_idx.loc[d] if pd.notna(cum_idx.loc[d]) else None,
                    "active_stocks": int(n_stocks.loc[d]),
                }
            )

    df_baskets = pd.DataFrame(baskets_records)
    out_baskets_path = root / "data" / "csv" / "sector_baskets_daily.csv"
    df_baskets.to_csv(out_baskets_path, index=False, float_format="%.10g")

    return MarketDataBundle(
        trading_days=trading_days,
        stock_returns=stock_returns,
        stock_prices=pvt_price,
        stock_traded_val=pvt_traded_val,
        sector_returns=sector_returns,
        market_returns=market_returns,
        first_price_dates=first_price_dates,
        sector_stocks_map=sector_stocks,
        stock_sector_map=stock_sector,
    )
