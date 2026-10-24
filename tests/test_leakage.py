"""Leakage tests for point-in-time feature store.

Exit criteria:
- Leakage test passes on real feature store.
- Leakage test fails when deliberately leaked features are injected.
"""

from __future__ import annotations

import pandas as pd
import pytest

from bsp.common.config import get_project_root
from bsp.quality.leakage import (
    LeakageError,
    validate_feature_dates,
    validate_feature_store,
    validate_no_same_year_actuals,
    validate_point_in_time_universe,
)

ROOT = get_project_root()


def test_feature_store_has_zero_leakage() -> None:
    """Real feature store in data/csv/ passes all leakage checks without error."""
    validate_feature_store(ROOT)


def test_leakage_detection_catches_future_as_of_date() -> None:
    """Injecting a future as_of_date must raise LeakageError."""
    budget_events = pd.DataFrame(
        [
            {"budget_id": "FY2021-22", "fiscal_year": "2021-22", "presented_on": "2021-02-01"},
        ]
    )
    # Deliberate leak: as_of_date is 4 days AFTER the budget was presented
    leaked_features = pd.DataFrame(
        [
            {
                "sector_id": "defence",
                "budget_id": "FY2021-22",
                "feature_name": "momentum_1m",
                "value": 0.05,
                "as_of_date": "2021-02-05",  # LEAK!
            }
        ]
    )

    with pytest.raises(LeakageError) as exc_info:
        validate_feature_dates(leaked_features, budget_events)
    assert "look-ahead violations" in str(exc_info.value)
    assert "2021-02-05 is after budget date 2021-02-01" in str(exc_info.value)


def test_leakage_detection_catches_same_year_actuals() -> None:
    """Injecting a same-year Actual basis must raise LeakageError."""
    leaked_panel = pd.DataFrame(
        [
            {
                "sector_id": "defence",
                "budget_year": "2021-22",
                "re_basis": "Actual",  # LEAK: Actuals for year t cannot be known on budget day
                "credibility_years_used": 3,
            }
        ]
    )

    with pytest.raises(LeakageError) as exc_info:
        validate_no_same_year_actuals(leaked_panel, leaked_panel)
    assert "actuals leakage violations" in str(exc_info.value)
    assert "used Actual as current baseline instead of RE" in str(exc_info.value)


def test_leakage_detection_catches_unlisted_stock() -> None:
    """Injecting an unlisted stock into a prior budget must raise LeakageError."""
    budget_events = pd.DataFrame(
        [
            {"budget_id": "FY2015-16", "fiscal_year": "2015-16", "presented_on": "2015-02-28"},
        ]
    )
    # ADANIGREEN was listed on 2018-06-18
    first_price_dates = {"ADANIGREEN": "2018-06-18"}

    leaked_stock_features = pd.DataFrame(
        [
            {
                "symbol": "ADANIGREEN",
                "budget_id": "FY2015-16",
                "feature_name": "momentum_1m",
                "value": 0.10,
                "as_of_date": "2015-02-28",  # LEAK: stock did not exist in 2015!
            }
        ]
    )

    with pytest.raises(LeakageError) as exc_info:
        validate_point_in_time_universe(leaked_stock_features, first_price_dates, budget_events)
    assert "point-in-time universe violations" in str(exc_info.value)
    assert "ADANIGREEN appears in FY2015-16" in str(exc_info.value)
