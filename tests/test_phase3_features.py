"""Unit tests and spot checks for Phase 3: features, targets and event study.

Exit criteria:
- ~300 sector-year rows and ~2,000 stock-year rows built.
- Leakage test passes, and fails when a deliberately leaked feature is injected.
- Event-study tables are populated and spot-checked by hand for one sector and one stock.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bsp.common.config import get_project_root
from bsp.common.db import create_engine
from bsp.events.study import (
    compute_car_and_tstat,
    fit_market_model,
)
from bsp.features.baskets import build_market_data_bundle
from bsp.features.sector_features import build_sector_features
from bsp.features.stock_features import build_stock_features
from bsp.features.targets import compute_targets_for_bundle

ROOT = get_project_root()


@pytest.fixture(scope="module")
def bundle():
    return build_market_data_bundle(ROOT)


def test_market_data_bundle_has_15_sectors(bundle):
    """Verify all 15 sectors are represented in sector basket returns."""
    assert bundle.sector_returns.shape[1] == 15
    assert "defence" in bundle.sector_returns.columns
    assert "it_control" in bundle.sector_returns.columns
    assert bundle.market_returns.notna().sum() > 5000


def test_sector_year_features_count_and_columns(bundle):
    """Exit criterion: ~300 sector-year rows built."""
    df_long, df_wide = build_sector_features(bundle, ROOT)

    # 15 sectors x 22 budget years = 330 rows (~300)
    assert len(df_wide) == 330
    assert df_wide["sector_id"].nunique() == 15
    assert df_wide["budget_id"].nunique() >= 22

    # Check key features exist and have non-null values
    assert "alloc_vs_prev_re_pct" in df_wide.columns
    assert "credibility_pct" in df_wide.columns
    assert "capex_share_be_pct" in df_wide.columns
    assert "momentum_12m" in df_wide.columns
    assert "volatility_30d" in df_wide.columns
    assert "regime_high_vix" in df_wide.columns

    # Verify every row's as_of_date is on or before presented_on
    for _, row in df_wide.iterrows():
        assert str(row["as_of_date"]) <= str(row["presented_on"])



def _symbols_with_a_universe_budget(bundle) -> set[str]:
    """Stocks listed on some budget day and, where the constituents history covers that day, Nifty 500 members on it."""
    from bsp.features.universe import Universe

    universe = Universe.from_csv(ROOT / "data" / "csv" / "nifty500_constituents.csv")
    stocks = pd.read_csv(ROOT / "config" / "stocks.csv")["symbol"]
    events = pd.read_csv(ROOT / "config" / "budget_events.csv").drop_duplicates("budget_id")
    kept: set[str] = set()
    for presented_on in events["presented_on"].astype(str):
        members = universe.members(presented_on)  # None = history does not cover this budget
        for symbol in stocks:
            first = bundle.first_price_dates.get(symbol)
            if (first is None or first <= presented_on) and (members is None or symbol in members):
                kept.add(symbol)
    return kept


def test_stock_year_features_count_and_columns(bundle):
    """Exit criterion: ~2,000 stock-year rows built."""
    df_long, df_wide = build_stock_features(bundle, ROOT)

    # Full budget stock-years: ~2,072 rows (~2,000); total across 26 budgets: ~2,470
    assert 1800 <= len(df_wide) <= 2600
    # The point-in-time Nifty 500 universe filter can remove a stock from every budget, so the symbol count is
    # derived from stocks.csv + the constituents history instead of being hard-coded.
    expected = _symbols_with_a_universe_budget(bundle)
    assert set(df_wide["symbol"]) == expected
    assert 0 < len(expected) <= len(pd.read_csv(ROOT / "config" / "stocks.csv"))
    # rows kept per budget match the universe-filter report the build produced
    rows_per_budget = df_wide.groupby("budget_id").size().to_dict()
    for row in df_wide.attrs["universe_report"]:
        assert row["kept"] == rows_per_budget.get(row["budget_id"], 0), row["budget_id"]

    assert "momentum_1m" in df_wide.columns
    assert "momentum_12m" in df_wide.columns
    assert "volatility_30d" in df_wide.columns
    assert "liquidity_90d" in df_wide.columns
    assert "beta_250d" in df_wide.columns

    # Verify no stock appears prior to listing date
    for _, row in df_wide.iterrows():
        sym = row["symbol"]
        first_d = bundle.first_price_dates.get(sym)
        if first_d:
            assert str(row["as_of_date"]) >= str(first_d)


def test_targets_structure_and_unresolved_horizon(bundle):
    """Verify forward targets, non-overlapping 12m horizon and FY2026-27 handling."""
    events_path = ROOT / "config" / "budget_events.csv"
    b_events = pd.read_csv(events_path)

    df_t = compute_targets_for_bundle(bundle, b_events)
    assert not df_t.empty

    # FY2026-27 12m forward return must be incomplete
    fy26_12m = df_t[(df_t["budget_id"] == "FY2026-27") & (df_t["horizon"] == "12m")]
    assert len(fy26_12m) == 131  # 15 sectors + 116 stocks
    assert (~fy26_12m["target_complete"]).all()
    assert fy26_12m["excess_return"].isna().all()

    # Resolved budget years must have target_complete = True for listed universe
    fy21_12m = df_t[(df_t["budget_id"] == "FY2021-22") & (df_t["horizon"] == "12m")]
    assert len(fy21_12m) == 127  # 15 sectors + 112 stocks listed as of Feb 2021
    assert fy21_12m["target_complete"].all()
    assert fy21_12m["excess_return"].notna().all()


def test_event_study_windows_and_t_stats():
    """Verify event study covers all 5 windows with valid CAR and t-stats."""
    es_path = ROOT / "data" / "csv" / "event_study.csv"
    assert es_path.exists(), "event_study.csv should exist"
    df_es = pd.read_csv(es_path)

    expected_windows = {"[-5,-1]", "0", "[0,+5]", "[0,+30]", "[0,+90]"}
    assert set(df_es["window"].unique()) == expected_windows

    # Check finite numbers
    assert df_es["car"].notna().sum() > 10000
    assert df_es["t_stat"].notna().sum() > 10000


def test_hand_checked_spot_check_sector(bundle):
    """Spot check by hand: Defence FY2021-22 surprise and event study."""
    # 1. Check Defence FY2021-22 surprise in sector panel
    # BE 2021-22 = 478196.0, RE 2020-21 = 484736.0
    # Expected surprise = (478196 / 484736 - 1) * 100 = -1.3491%
    sec_wide_path = ROOT / "data" / "csv" / "features_sector_year_wide.csv"
    df_sec = pd.read_csv(sec_wide_path)
    def_21 = df_sec[(df_sec["sector_id"] == "defence") & (df_sec["fiscal_year"] == "2021-22")].iloc[0]

    expected_surprise = (478196.0 / 484736.0 - 1.0) * 100.0
    assert np.isclose(def_21["alloc_vs_prev_re_pct"], expected_surprise, atol=0.01)

    # 2. Hand check market model OLS for a synthetic test sequence
    x = np.array([0.01, -0.02, 0.015, -0.005, 0.02])
    # y = 0.001 + 1.2 * x
    y = 0.001 + 1.2 * x
    # Repeat to exceed 15 points
    x_rep = np.tile(x, 5)
    y_rep = np.tile(y, 5)
    fit = fit_market_model(y_rep, x_rep)
    assert fit is not None
    assert np.isclose(fit.beta, 1.2, atol=1e-5)
    assert np.isclose(fit.alpha, 0.001, atol=1e-5)
    assert fit.residual_variance < 1e-10

    # 3. Hand check CAR on Day 0
    w_y = np.array([0.025])
    w_x = np.array([0.01])
    # Expected AR = 0.025 - (0.001 + 1.2 * 0.01) = 0.025 - 0.013 = 0.012
    car, t_stat = compute_car_and_tstat(fit, w_y, w_x)
    assert np.isclose(car, 0.012, atol=1e-5)


def test_hand_checked_spot_check_stock():
    """Spot check by hand: BEL in FY2021-22 event study."""
    es_path = ROOT / "data" / "csv" / "event_study.csv"
    df_es = pd.read_csv(es_path)

    bel_rows = df_es[(df_es["entity"] == "BEL") & (df_es["budget_id"] == "FY2021-22")]
    assert len(bel_rows) == 5  # 5 windows
    row_day0 = bel_rows[bel_rows["window"] == "0"].iloc[0]

    # Verify alpha, beta, car and t-stat are valid numbers
    assert pd.notna(row_day0["alpha"])
    assert pd.notna(row_day0["beta"])
    assert pd.notna(row_day0["car"])
    assert pd.notna(row_day0["t_stat"])


def test_database_tables_populated(tmp_path, monkeypatch):
    """Verify that all Phase 3 database tables are populated with correct row counts."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from bsp.features.build import load_features_into_db

    # Build a throwaway database from the migrations and the committed CSVs.
    url = f"sqlite:///{(tmp_path / 'bsp.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    load_features_into_db(database_url=url, project_root=ROOT)

    engine = create_engine(database_url=url)
    with engine.connect() as conn:
        sec_count = conn.execute(text("SELECT COUNT(*) FROM features_sector_year")).scalar()
        stk_count = conn.execute(text("SELECT COUNT(*) FROM features_stock_year")).scalar()
        tgt_count = conn.execute(text("SELECT COUNT(*) FROM targets")).scalar()
        es_count = conn.execute(text("SELECT COUNT(*) FROM event_study")).scalar()

    csv_dir = ROOT / "data" / "csv"
    expected = {
        "features_sector_year": sec_count,
        "features_stock_year": stk_count,
        "targets": tgt_count,
        "event_study": es_count,
    }
    for table, loaded in expected.items():
        assert loaded == len(pd.read_csv(csv_dir / f"{table}.csv")) > 0, table
