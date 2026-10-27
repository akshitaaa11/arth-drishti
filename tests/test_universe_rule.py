"""The universe rule: listed on or before the budget date AND average traded value over the prior 60 days >= 5 crore."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bsp.features.universe import (
    ILLIQUID,
    IN_UNIVERSE,
    NOT_LISTED,
    Liquidity,
    average_traded_value_cr,
    classify,
    prior_window,
)

DAYS = [f"2020-{m:02d}-{d:02d}" for m in (1, 2, 3) for d in range(1, 29)]  # 84 fake trading days, all ISO dates


def test_window_is_the_60_trading_days_strictly_before_the_budget_date() -> None:
    start, end = prior_window(DAYS, "2020-03-01")  # 2020-03-01 is index 56
    assert (start, end) == (0, 56)  # only 56 days exist before it
    start, end = prior_window(DAYS, "2020-03-20")
    assert end == 75 and DAYS[end] == "2020-03-20" and start == 15  # exactly 60 days; the budget day itself is excluded
    holiday = [d for d in DAYS if d != "2020-03-20"]  # budget date that is not a trading day: every earlier day counts
    assert prior_window(holiday, "2020-03-20")[1] == len([d for d in holiday if d < "2020-03-20"]) == 75


def test_average_uses_only_prior_days_and_ignores_days_before_listing() -> None:
    traded = pd.Series(np.nan, index=DAYS)
    traded.iloc[50:56] = 12.0          # listed 6 days before 2020-03-01
    traded.iloc[56] = 1000.0           # budget day: must not count
    result = average_traded_value_cr(traded, DAYS, "2020-03-01")
    assert result == Liquidity(12.0, 6)
    assert average_traded_value_cr(pd.Series(np.nan, index=DAYS), DAYS, "2020-03-01") == Liquidity(None, 0)


def test_future_traded_value_never_changes_the_verdict() -> None:
    traded = pd.Series(1.0, index=DAYS)
    base = average_traded_value_cr(traded, DAYS, "2020-03-10")
    traded.iloc[DAYS.index("2020-03-10"):] = 1e9  # huge volume from the budget day on
    assert average_traded_value_cr(traded, DAYS, "2020-03-10") == base


@pytest.mark.parametrize(
    ("first_price", "average", "expected"),
    [
        ("2020-03-02", 50.0, NOT_LISTED),   # listed the day after the budget, however liquid
        ("2020-03-01", 50.0, IN_UNIVERSE),  # listed on the budget date counts as listed
        ("2015-05-26", 4.999, ILLIQUID),
        ("2015-05-26", 5.0, IN_UNIVERSE),   # the rule is >= 5 crore
        ("2015-05-26", None, ILLIQUID),     # never traded in the window
        (None, 20.0, IN_UNIVERSE),          # no first-price date known: only liquidity can decide
    ],
)
def test_classification(first_price, average, expected) -> None:
    assert classify(first_price, "2020-03-01", Liquidity(average, 60)) == expected


def test_not_listed_is_reported_before_illiquid() -> None:
    assert classify("2021-01-01", "2020-03-01", Liquidity(None, 0)) == NOT_LISTED
