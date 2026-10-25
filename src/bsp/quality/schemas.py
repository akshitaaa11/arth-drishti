from __future__ import annotations

from datetime import date

import pandas as pd
from pandera import Check, Column, DataFrameSchema


def validate_prices(frame: pd.DataFrame) -> pd.DataFrame:
    schema = DataFrameSchema(
        {
            "symbol": Column(str, checks=Check.str_matches(r"^[A-Z0-9&._-]+$")),
            "date": Column(str, checks=Check.str_matches(r"^\d{4}-\d{2}-\d{2}$"), coerce=True),
            "open": Column(float, checks=[Check.gt(0)], coerce=True),
            "high": Column(float, checks=[Check.gt(0)], coerce=True),
            "low": Column(float, checks=[Check.gt(0)], coerce=True),
            "close": Column(float, checks=[Check.gt(0)], coerce=True),
            "adj_close": Column(float, checks=[Check.gt(0)], coerce=True),
            "volume": Column(float, checks=[Check.ge(0)], coerce=True),
        },
        checks=[
            Check(lambda frame: frame["date"].max() <= date.today().isoformat(), element_wise=False),
            Check(lambda frame: not frame.duplicated(subset=["symbol", "date"]).any(), element_wise=False),
        ],
    )
    return schema.validate(frame, lazy=True)


def validate_benchmarks(frame: pd.DataFrame) -> pd.DataFrame:
    schema = DataFrameSchema(
        {
            "index_name": Column(str),
            "ticker": Column(str),
            "date": Column(str, checks=Check.str_matches(r"^\d{4}-\d{2}-\d{2}$"), coerce=True),
            "close": Column(float, checks=[Check.gt(0)], coerce=True),
            "volume": Column(float, checks=[Check.ge(0)], coerce=True, nullable=True),
        },
        checks=[
            Check(lambda frame: frame["date"].max() <= date.today().isoformat(), element_wise=False),
            Check(lambda frame: not frame.duplicated(subset=["index_name", "date"]).any(), element_wise=False),
        ],
    )
    return schema.validate(frame, lazy=True)


def validate_macro(frame: pd.DataFrame) -> pd.DataFrame:
    schema = DataFrameSchema(
        {
            "series": Column(str),
            "date": Column(str, checks=Check.str_matches(r"^\d{4}-\d{2}-\d{2}"), coerce=True),
            "value": Column(float, nullable=False, coerce=True),
            "unit": Column(str),
            "source": Column(str),
        },
        checks=[
            Check(lambda frame: frame["date"].max() <= date.today().isoformat(), element_wise=False),
        ],
    )
    return schema.validate(frame, lazy=True)
