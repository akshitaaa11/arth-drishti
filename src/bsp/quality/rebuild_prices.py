"""Rebuild ``prices_daily.csv`` and its reports offline from the saved raw Yahoo download.

``bsp.ingest.prices`` downloads, cleans and writes the price file. When only a cleaning RULE changes (a new sourced
listing date, a new exclusion), re-downloading would also pick up Yahoo's latest adjustments to every other price and
rewrite the whole 93 MB file. This command applies the same ``clean_prices`` rules to the saved raw download instead
(``data/raw/yahoo_prices/prices_raw.csv`` and ``data/raw/yahoo_actions/*_splits.csv``), keeps every surviving row's
values, ``traded_value_cr``, ``source`` and ``fetched_at`` from the current ``prices_daily.csv``, and refuses to run if
the raw download no longer matches it (a different download: run ``bsp.ingest.prices`` instead).

    python -m bsp.quality.rebuild_prices
"""

from __future__ import annotations

import glob
from pathlib import Path

import pandas as pd

from bsp.common.config import get_project_root
from bsp.ingest.prices import _fill_listing_dates
from bsp.quality.price_cleaning import clean_prices
from bsp.quality.price_corrections import load_listing_overrides, load_return_exclusions
from bsp.quality.schemas import validate_prices

META = ["traded_value_cr", "source", "source_url", "fetched_at"]
PRICE_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]


def rebuild(root: Path | None = None) -> pd.DataFrame:
    root = root or get_project_root()
    csv_dir, reports = root / "data" / "csv", root / "reports"
    raw = pd.read_csv(root / "data" / "raw" / "yahoo_prices" / "prices_raw.csv")
    files = sorted(glob.glob(str(root / "data" / "raw" / "yahoo_actions" / "*_splits.csv")))
    splits = pd.concat([pd.read_csv(f) for f in files], ignore_index=True) if files else None
    overrides, exclusions = load_listing_overrides(root), load_return_exclusions(root)
    result = clean_prices(raw, splits, overrides, exclusions)

    current = pd.read_csv(csv_dir / "prices_daily.csv")
    merged = result.prices.merge(current, on=["symbol", "date"], how="left", suffixes=("", "_current"), indicator=True)
    if (merged["_merge"] != "both").any():
        raise SystemExit("the raw download has rows that are not in prices_daily.csv: it is a different download; "
                         "run `python -m bsp.ingest.prices` instead")
    for column in PRICE_COLUMNS:
        if ((merged[column] - merged[f"{column}_current"]).abs() > 1e-9 * merged[column].abs().clip(lower=1)).any():
            raise SystemExit(f"the raw download's {column} differs from prices_daily.csv: it is a different download; "
                             "run `python -m bsp.ingest.prices` instead")
    frame = merged[["symbol", "date", "open", "high", "low", "close", "adj_close", "volume"]].copy()
    for column in META:
        frame[column] = merged[column].to_numpy()
    validate_prices(frame)
    frame = frame[list(current.columns)]
    frame.to_csv(csv_dir / "prices_daily.csv", index=False)
    first_dates = frame.groupby("symbol")["date"].min().reset_index(name="first_price_date")
    first_dates.to_csv(csv_dir / "stock_first_price_date.csv", index=False)
    _fill_listing_dates(first_dates, overrides)

    result.decisions.to_csv(reports / "price_flag_decisions.csv", index=False)
    result.dropped.to_csv(reports / "price_rows_dropped.csv", index=False)
    result.adjustments.to_csv(reports / "price_split_adjustments.csv", index=False)
    print(f"{len(current)} -> {len(frame)} price rows; {len(result.dropped)} rows dropped; "
          f"{len(result.decisions)} flags decided")
    return frame


if __name__ == "__main__":
    rebuild()
