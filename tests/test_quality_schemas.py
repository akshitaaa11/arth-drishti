"""pandera checks on the committed Phase 2 CSVs, plus hand-made frames showing each check can fail."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pandera.errors as pa_errors
import pytest

from bsp.quality.schemas import validate_benchmarks, validate_macro, validate_prices

CSV = Path(__file__).resolve().parents[1] / "data" / "csv"


def test_committed_prices_pass_all_checks() -> None:
    validate_prices(pd.read_csv(CSV / "prices_daily.csv"))


def test_committed_benchmarks_pass_all_checks() -> None:
    validate_benchmarks(pd.read_csv(CSV / "index_daily.csv"))


def test_committed_macro_passes_all_checks() -> None:
    validate_macro(pd.read_csv(CSV / "macro.csv"))


def _row(**overrides):
    row = {"symbol": "HAL", "date": "2020-01-01", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
           "adj_close": 10.5, "volume": 100.0}
    return {**row, **overrides}


@pytest.mark.parametrize(
    "bad",
    [
        _row(date="2999-01-01"),   # future date
        _row(close=0.0),           # non-positive price
        _row(volume=-1.0),         # negative volume
    ],
)
def test_prices_checks_reject_bad_rows(bad) -> None:
    with pytest.raises(pa_errors.SchemaErrors):
        validate_prices(pd.DataFrame([_row(), bad]) if bad["date"] != "2020-01-01" else pd.DataFrame([bad]))


def test_prices_checks_reject_duplicate_symbol_days() -> None:
    with pytest.raises(pa_errors.SchemaErrors):
        validate_prices(pd.DataFrame([_row(), _row()]))
