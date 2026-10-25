"""Price-flag decisions on small hand-made series (fixtures, never fed to the feature store)."""

from __future__ import annotations

import pandas as pd

from bsp.quality.price_cleaning import clean_prices, flag_jumps


def _series(symbol: str, closes: list[float], volumes: list[float] | None = None, start: str = "2020-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(closes)).strftime("%Y-%m-%d")
    volumes = volumes or [1000.0] * len(closes)
    return pd.DataFrame({"symbol": symbol, "date": dates, "open": closes, "high": [c * 1.01 for c in closes],
                         "low": [c * 0.99 for c in closes], "close": closes, "adj_close": closes, "volume": volumes})


def test_placeholder_row_before_first_trade_is_dropped_and_followup_jump_disappears() -> None:
    prices = _series("AAA", [400.0, 10.0, 10.1, 10.2], [0, 500, 600, 700])
    prices.loc[0, ["open", "high", "low"]] = 400.0  # flat row, zero volume: non-trading placeholder
    result = clean_prices(prices)
    assert list(result.prices["date"]) == list(prices["date"][1:])
    assert result.dropped.iloc[0]["rule"] == "placeholder"
    assert len(flag_jumps(result.prices)) == 0
    row = result.decisions.iloc[0]
    assert (row["decision"], row["likely_cause"]) == ("keep", "data error")  # the placeholder itself was unflagged


def test_bad_close_and_one_day_spike_are_dropped() -> None:
    prices = _series("BBB", [100.0, 101.0, 50.0, 102.0, 103.0, 104.0])
    spike = clean_prices(prices)
    assert list(spike.dropped["rule"]) == ["spike_reversal"]
    assert 50.0 not in set(spike.prices["close"])

    bad = _series("CCC", [100.0, 101.0, 102.0, 103.0])
    bad.loc[2, "close"] = 205.0  # close far above the day's high
    out = clean_prices(bad)
    assert list(out.dropped["rule"]) == ["bad_close"]


def test_split_listed_in_downloaded_history_is_adjusted_not_dropped() -> None:
    prices = _series("DDD", [20.0, 21.0, 20.5, 41.0, 41.5, 42.0])
    splits = pd.DataFrame({"symbol": ["DDD"], "date": [prices.loc[3, "date"]], "ratio": [2.0]})
    result = clean_prices(prices, splits)
    assert result.dropped.empty
    assert len(flag_jumps(result.prices)) == 0
    assert result.decisions.iloc[0]["decision"] == "adjust"
    assert result.adjustments.iloc[0]["split_ratio"] == 2.0


def test_unexplained_persistent_shift_is_kept_for_manual_review() -> None:
    prices = _series("EEE", [100.0, 101.0, 24.0, 24.5, 24.2, 24.4])
    result = clean_prices(prices)
    assert result.dropped.empty
    row = result.decisions.iloc[0]
    assert (row["decision"], row["likely_cause"]) == ("keep", "real")
    assert "manual review" in row["evidence"]
