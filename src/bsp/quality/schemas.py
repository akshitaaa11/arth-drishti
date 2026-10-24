from __future__ import annotations

from datetime import date

import pandas as pd
import pandera as pa
from pandera import Check, Column, DataFrameSchema


def validate_prices(frame: pd.DataFrame) -> pd.DataFrame:
    schema = DataFrameSchema(
        {
            "symbol": Column(str, checks=Check.str_matches(r"^[A-Z0-9._-]+$")),
            "date": Column(str, checks=Check.str_matches(r"^\d{4}-\d{2}-\d{2}$")),
            "open": Column(float, checks=[Check.ge(0)]),
            "high": Column(float, checks=[Check.ge(0)]),
            "low": Column(float, checks=[Check.ge(0)]),
            "close": Column(float, checks=[Check.ge(0)]),
            "adj_close": Column(float, checks=[Check.ge(0)]),
            "volume": Column(float, checks=[Check.ge(0)]),
        },
        checks=[
            Check(lambda frame: frame["date"].max() <= date.today().isoformat(), element_wise=False),
            Check(lambda frame: not frame.duplicated(subset=["symbol", "date"]).any(), element_wise=False),
        ],
    )
    return schema.validate(frame)


def validate_benchmarks(frame: pd.DataFrame) -> pd.DataFrame:
    schema = DataFrameSchema(
        {
            "index_name": Column(str),
            "ticker": Column(str),
            "date": Column(str, checks=Check.str_matches(r"^\d{4}-\d{2}-\d{2}$")),
            "close": Column(float, checks=[Check.ge(0)]),
            "volume": Column(float, checks=[Check.ge(0)]),
        },
        checks=[
            Check(lambda frame: frame["date"].max() <= date.today().isoformat(), element_wise=False),
            Check(lambda frame: not frame.duplicated(subset=["index_name", "date"]).any(), element_wise=False),
        ],
    )
    return schema.validate(frame)


def validate_macro(frame: pd.DataFrame) -> pd.DataFrame:
    schema = DataFrameSchema(
        {
            "series": Column(str),
            "date": Column(str, checks=Check.str_matches(r"^\d{4}-\d{2}-\d{2}$|^\d{4}$")),
            "value": Column(float, checks=[Check.not_null()]),
            "unit": Column(str),
            "source": Column(str),
        },
        checks=[
            Check(lambda frame: frame["date"].max() <= date.today().isoformat(), element_wise=False),
        ],
    )
    return schema.validate(frame)
