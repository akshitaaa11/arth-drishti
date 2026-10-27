"""The stock universe on a budget day: a rule that is knowable on that day, with no index-membership data.

A stock is in the universe for a budget when BOTH hold:

1. **Listed**: its first trading day is on or before the budget date (the listing-date check); and
2. **Liquid**: its average daily traded value over the 60 trading days strictly before the budget date is at least
   ``MIN_AVG_TRADED_VALUE_CR`` (5 crore rupees).

Edge cases, chosen so that nothing beyond the budget date is used:

* The window is the 60 trading days (days on which any stock traded) before the budget date; the budget day itself is
  excluded because the Union Budget is presented during the trading session.
* A stock listed fewer than 60 trading days before the budget has only the days it has: the average is over those
  days (days before listing are not zeros). ``n_days`` is returned so the report can count such cases.
* A day on which the stock has no price row (for example a one-off special trading session that only a few stocks
  traded) is not counted for that stock: the average is over the days it does have.
* A listed stock with no traded value at all in the window (never traded) has no average and is treated as illiquid.

What this rule does NOT do: it does not check index membership on the budget day, and the stock list comes from
today's symbols, so stocks that were delisted before today are absent. Survivorship bias is therefore reduced
(illiquid names are dropped by the same rule in every year) but not removed. See README ground rule 1 and
``reports/data_gaps.md``.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

import pandas as pd

MIN_AVG_TRADED_VALUE_CR = 5.0
LIQUIDITY_WINDOW_DAYS = 60

NOT_LISTED = "not_listed"
ILLIQUID = "illiquid"
IN_UNIVERSE = "in_universe"


@dataclass(frozen=True)
class Liquidity:
    average_cr: float | None  # None when the stock has no traded value in the window
    n_days: int  # trading days with a traded value inside the window (at most 60)


def prior_window(trading_days: list[str], presented_on: str, window: int = LIQUIDITY_WINDOW_DAYS) -> tuple[int, int]:
    """Index range [start, end) of the ``window`` trading days strictly before ``presented_on``."""
    end = bisect_left(trading_days, presented_on)  # number of trading days before the budget date
    return max(0, end - window), end


def average_traded_value_cr(traded_value: pd.Series, trading_days: list[str], presented_on: str,
                            window: int = LIQUIDITY_WINDOW_DAYS) -> Liquidity:
    """Mean daily traded value (crore) over the prior ``window`` trading days; ``traded_value`` is indexed like
    ``trading_days`` (NaN before listing / on days without a price)."""
    start, end = prior_window(trading_days, presented_on, window)
    values = traded_value.iloc[start:end].dropna()
    return Liquidity(float(values.mean()) if len(values) else None, int(len(values)))


def classify(first_price_date: str | None, presented_on: str, liquidity: Liquidity,
             threshold_cr: float = MIN_AVG_TRADED_VALUE_CR) -> str:
    """``not_listed`` / ``illiquid`` / ``in_universe`` for one stock on one budget day (listing is checked first)."""
    if first_price_date is not None and first_price_date > presented_on:
        return NOT_LISTED
    if liquidity.average_cr is None or liquidity.average_cr < threshold_cr:
        return ILLIQUID
    return IN_UNIVERSE
