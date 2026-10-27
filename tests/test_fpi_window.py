"""FPI start date, the lookback window, and missing (never zero / forward-filled) FPI features before the data starts."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from bsp.common.config import get_project_root
from bsp.features.fpi_window import coverage_table, expected_periods, window_start, window_status
from bsp.ingest import _common, fpi
from bsp.models.baselines import RidgeBaseline

ROOT = get_project_root()
FPI_COLUMNS = ["fpi_net_equity_1f_cr", "fpi_net_equity_1m_cr", "fpi_equity_aum_cr"]


# ------------------------------------------------------------------ collector start -----------------------------------

def test_collector_never_requests_a_period_before_2018_09_15(tmp_path, monkeypatch) -> None:
    assert fpi.FPI_START == date(2018, 9, 15)
    ends = list(fpi._fortnight_ends())
    assert ends[0] == date(2018, 9, 15) and min(ends) == date(2018, 9, 15)
    monkeypatch.setattr(fpi, "CSV_DIR", tmp_path / "csv")
    monkeypatch.setattr(fpi, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(_common, "CSV_DIR", tmp_path / "csv")
    monkeypatch.setattr(_common, "RAW_DIR", tmp_path / "raw")
    (tmp_path / "csv").mkdir()
    urls: list[str] = []

    class Rejected:
        text = "<html>Request Rejected. Your support ID is: 1</html>"
        status_code = 200

    def get(url, **kwargs):
        urls.append(url)
        return Rejected()

    fpi.collect_fpi(get=get, pause=0)
    assert urls and urls[0] == fpi.fpi_url(date(2018, 9, 15))
    allowed = {fpi.fpi_url(d) for d in fpi._fortnight_ends()}
    assert set(urls) <= allowed  # nothing before 2018-09-15 (the 2017-01 to 2018-08 pages) is ever requested


# ------------------------------------------------------------------ window arithmetic ---------------------------------

def test_expected_periods_and_window_start() -> None:
    assert expected_periods("2019-02-01") == ("2019-01-15", "2019-01-31")
    assert expected_periods("2024-07-23") == ("2024-06-30", "2024-07-15")
    assert expected_periods("2020-03-15") == ("2020-02-29", "2020-03-15")  # a report ending on the budget day counts
    assert window_start("2019-01-15") == "2019-01-01" and window_start("2024-06-30") == "2024-06-16"


def test_window_status_complete_partial_empty() -> None:
    assert window_status({"2019-01-15", "2019-01-31"}, "2019-02-01") == "complete"
    assert window_status({"2019-01-31", "2018-09-15"}, "2019-02-01") == "partial"
    assert window_status({"2018-09-15", "2020-08-31"}, "2019-02-01") == "empty"  # older / later reports do not count


def test_coverage_report_matches_the_data() -> None:
    reported = pd.read_csv(ROOT / "reports" / "fpi_coverage.csv")
    expected = coverage_table(ROOT)
    pd.testing.assert_frame_equal(reported, expected, check_dtype=False)
    before = reported[reported["window_start"] < "2018-09-15"]
    assert len(before) and (before["status"] != "complete").all()


# ------------------------------------------------------------------ features ------------------------------------------

def test_budgets_before_the_data_starts_have_nan_fpi_features_never_zero_or_filled() -> None:
    wide = pd.read_csv(ROOT / "data" / "csv" / "features_sector_year_wide.csv")
    coverage = pd.read_csv(ROOT / "reports" / "fpi_coverage.csv").set_index("budget_id")
    early = coverage[coverage["window_start"] < "2018-09-15"].index
    assert "FY2018-19" in early
    rows = wide[wide["budget_id"].isin(early)]
    assert len(rows) > 0
    assert rows[FPI_COLUMNS].isna().all().all()  # every one is NaN: not 0, not carried forward
    # later budgets whose window has no reports are NaN too, even though older reports exist (no forward fill)
    empty = wide[wide["budget_id"].isin(coverage[coverage["status"] == "empty"].index)]
    assert empty[FPI_COLUMNS].isna().all().all()
    for column in FPI_COLUMNS:
        assert not (wide[column] == 0).any()


def test_partial_window_gives_a_1f_value_but_no_1m_value() -> None:
    wide = pd.read_csv(ROOT / "data" / "csv" / "features_sector_year_wide.csv")
    partial = wide[wide["budget_id"] == "FY2019-20"]  # 2019-06-30 present, 2019-06-15 never collected
    assert partial["fpi_net_equity_1f_cr"].notna().any()
    assert partial["fpi_net_equity_1m_cr"].isna().all()


# ------------------------------------------------------------------ model handling ------------------------------------

def test_ridge_keeps_every_row_when_fpi_is_missing() -> None:
    rng = np.random.default_rng(0)
    n = 40
    train = pd.DataFrame({"momentum_3m": rng.normal(size=n), "fpi_net_equity_1m_cr": np.nan})
    train["excess_return"] = train["momentum_3m"] * 0.1
    test = pd.DataFrame({"momentum_3m": rng.normal(size=5), "fpi_net_equity_1m_cr": np.nan})
    model = RidgeBaseline(with_interval=False).fit(train, ["momentum_3m", "fpi_net_equity_1m_cr"])
    assert "fpi_net_equity_1m_cr" not in model.cols  # below the 60% training coverage: the column is dropped, not zero-filled
    out = model.predict(test)
    assert len(out) == len(test) and out["score"].notna().all()  # no row is dropped


def test_ridge_median_imputes_a_partly_missing_column() -> None:
    train = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0], "b": [1.0, np.nan, 3.0, 5.0, np.nan]})
    train["excess_return"] = [0.1, 0.2, 0.3, 0.4, 0.5]
    model = RidgeBaseline(with_interval=False, min_coverage=0.5).fit(train, ["a", "b"])
    assert model.cols == ["a", "b"] and model.stats is not None and model.stats.loc["b", "median"] == 3.0
    assert len(model.predict(pd.DataFrame({"a": [2.5], "b": [np.nan]}))) == 1


@pytest.mark.parametrize("budget_id", ["FY2020-21", "FY2024-25"])
def test_complete_windows_have_all_three_fpi_features(budget_id: str) -> None:
    wide = pd.read_csv(ROOT / "data" / "csv" / "features_sector_year_wide.csv")
    rows = wide[wide["budget_id"] == budget_id]
    assert rows[FPI_COLUMNS].notna().all(axis=1).sum() >= 4
