"""The two sourced price corrections: TEXRAIL listing date and the NIITLTD demerger return exclusion."""

from __future__ import annotations

import math

import pandas as pd

from bsp.common.config import get_project_root
from bsp.features.baskets import build_market_data_bundle
from bsp.quality.price_cleaning import clean_prices
from bsp.quality.price_corrections import (
    ListingOverride,
    load_listing_overrides,
    load_return_exclusions,
)

ROOT = get_project_root()
UNVERIFIED = "secondary source, not verified on the exchange"


def _series(symbol: str, start: str, closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(closes)).strftime("%Y-%m-%d")
    return pd.DataFrame({"symbol": symbol, "date": dates, "open": closes, "high": closes, "low": closes,
                         "close": closes, "adj_close": closes, "volume": [1000.0] * len(closes)})


# ---------------------------------------------------------------- TEXRAIL -------------------------------------------

def test_config_files_carry_the_sourced_values() -> None:
    overrides, exclusions = load_listing_overrides(ROOT), load_return_exclusions(ROOT)
    assert overrides["TEXRAIL"].listing_date == "2011-03-03"
    assert overrides["TEXRAIL"].verification == UNVERIFIED
    assert overrides["TEXRAIL"].source_url == "https://www.kotaksecurities.com/stocks/texmaco-rail-engineering-ltd"
    assert [(e.symbol, e.date) for e in exclusions] == [("NIITLTD", "2023-06-08")]
    assert exclusions[0].verification == UNVERIFIED


def test_rows_before_the_listing_date_are_dropped_and_the_listing_day_row_is_kept() -> None:
    prices = _series("ZZZ", "2011-02-28", [50.0, 52.0, 51.0, 90.0, 91.0, 92.0])  # 2011-03-03 is the 4th row
    result = clean_prices(prices, listing_overrides={"ZZZ": ListingOverride("ZZZ", "2011-03-03", UNVERIFIED, "https://x", "")})
    assert result.prices["date"].min() == "2011-03-03"
    assert len(result.prices) == 3
    assert set(result.dropped["rule"]) == {"before_listing"}
    assert (result.decisions["decision"] == "drop").all()
    assert (result.decisions["likely_cause"] == "data error").all()
    assert UNVERIFIED in " ".join(result.decisions["evidence"])


def test_committed_texrail_prices_start_on_the_listing_date() -> None:
    prices = pd.read_csv(ROOT / "data" / "csv" / "prices_daily.csv", usecols=["symbol", "date"])
    texrail = prices[prices["symbol"] == "TEXRAIL"]["date"].astype(str)
    assert texrail.min() >= "2011-03-03"
    first = pd.read_csv(ROOT / "data" / "csv" / "stock_first_price_date.csv").set_index("symbol")["first_price_date"]
    assert str(first["TEXRAIL"]) >= "2011-03-03"
    stocks = pd.read_csv(ROOT / "config" / "stocks.csv").set_index("symbol")
    assert stocks.loc["TEXRAIL", "listing_date"] == "2011-03-03"


def test_texrail_is_not_in_the_universe_for_budgets_before_its_listing() -> None:
    budgets = pd.read_csv(ROOT / "config" / "budget_events.csv").drop_duplicates("budget_id")
    early = set(budgets[budgets["presented_on"].astype(str) < "2011-03-03"]["budget_id"])
    assert "FY2011-12" in early  # presented 2011-02-28
    rows = pd.read_csv(ROOT / "data" / "csv" / "features_stock_year.csv", usecols=["symbol", "budget_id"])
    assert not set(rows[rows["symbol"] == "TEXRAIL"]["budget_id"]) & early


def test_railways_sector_years_with_an_empty_basket_are_missing_not_filled() -> None:
    bundle = build_market_data_bundle(ROOT)
    start = bundle.sector_first_active_idx["railways"]
    assert start is not None
    assert bundle.trading_days[start] == "2008-04-23"
    targets = pd.read_csv(ROOT / "data" / "csv" / "targets.csv")
    railways = targets[(targets["entity"] == "railways") & (targets["entity_type"] == "sector")]
    missing = railways[railways["budget_id"].isin(["FY2005-06", "FY2006-07", "FY2007-08", "FY2008-09"])]
    assert len(missing) and not missing["target_complete"].astype(bool).any()
    assert missing["excess_return"].isna().all()
    features = pd.read_csv(ROOT / "data" / "csv" / "features_sector_year_wide.csv")
    empty = features[(features["sector_id"] == "railways") & (features["budget_id"] == "FY2008-09")]
    assert len(empty) == 1 and empty["basket_active_stocks"].iloc[0] == 0
    assert math.isnan(empty["momentum_3m"].iloc[0]) if "momentum_3m" in empty else True


# ---------------------------------------------------------------- NIITLTD -------------------------------------------

def test_exclusion_decision_row_is_split_adjust_with_no_invented_factor() -> None:
    decisions = pd.read_csv(ROOT / "reports" / "price_flag_decisions.csv")
    row = decisions[(decisions["symbol"] == "NIITLTD") & (decisions["date"] == "2023-06-08")].iloc[0]
    assert (row["likely_cause"], row["decision"]) == ("split", "adjust")
    assert "no adjustment factor is invented" in row["evidence"]
    assert UNVERIFIED in row["evidence"]
    for day in ("2010-11-01", "2011-03-03"):
        tex = decisions[(decisions["symbol"] == "TEXRAIL") & (decisions["date"] == day)].iloc[0]
        assert (tex["likely_cause"], tex["decision"]) == ("data error", "drop")


def test_niitltd_demerger_day_return_is_missing_and_prices_are_untouched() -> None:
    bundle = build_market_data_bundle(ROOT)
    day = "2023-06-08"
    assert ("NIITLTD", day) in bundle.excluded_returns
    assert bundle.excluded_returns[("NIITLTD", day)] < -0.7  # the observed -76% move, kept only for window maths
    assert math.isnan(bundle.stock_returns.loc[day, "NIITLTD"])
    prices = pd.read_csv(ROOT / "data" / "csv" / "prices_daily.csv", usecols=["symbol", "date", "close"])
    n = prices[(prices["symbol"] == "NIITLTD") & (prices["date"].isin(["2023-06-07", day]))]
    assert len(n) == 2  # both rows still present, unadjusted


def test_window_return_spanning_the_demerger_divides_out_only_that_days_return() -> None:
    bundle = build_market_data_bundle(ROOT)
    days = list(bundle.trading_days)
    i_ex = days.index("2023-06-08")
    prices = bundle.stock_prices["NIITLTD"]
    raw = float(prices.iloc[i_ex + 5] / prices.iloc[i_ex - 5]) - 1.0
    adjusted = bundle.window_return("NIITLTD", i_ex - 5, i_ex + 5)
    assert adjusted is not None
    excluded = bundle.excluded_returns[("NIITLTD", "2023-06-08")]
    assert abs(adjusted - ((1.0 + raw) / (1.0 + excluded) - 1.0)) < 1e-12  # only that day's own return is divided out
    assert adjusted > raw + 0.5  # the -76% day no longer drives the window
    after = bundle.window_return("NIITLTD", i_ex, i_ex + 5)  # starts on the ex-date: the break is not inside
    assert after is not None and abs(after - (float(prices.iloc[i_ex + 5] / prices.iloc[i_ex]) - 1.0)) < 1e-12
