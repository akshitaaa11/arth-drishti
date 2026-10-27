from __future__ import annotations

import pandas as pd
import yfinance as yf

from bsp.ingest._common import (
    CFG_DIR,
    CSV_DIR,
    RAW_DIR,
    REPORT_DIR,
    append_fetch_log,
    ensure_dirs,
    load_stocks,
    write_csv_guarded,
)
from bsp.quality.price_cleaning import clean_prices, flag_jumps, write_reports
from bsp.quality.schemas import validate_prices

START = "2004-12-01"


def _history(ticker: str, retries: int = 3) -> pd.DataFrame:
    last_error = ""
    for attempt in range(retries):
        try:
            frame = yf.Ticker(ticker).history(start=START, auto_adjust=False, actions=False)
            if len(frame):
                frame = frame.reset_index()
                frame["Date"] = pd.to_datetime(frame["Date"]).dt.tz_localize(None).dt.date
                return frame
            last_error = "empty response"
        except Exception as exc:  # pragma: no cover - exercised by the real scraper.
            last_error = str(exc)
        if attempt < retries - 1:
            import time
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(last_error)


def _load_splits(stocks: pd.DataFrame) -> pd.DataFrame:
    """Split history per symbol, cached under data/raw/yahoo_actions/ (one download per symbol)."""
    actions_dir = RAW_DIR / "yahoo_actions"
    actions_dir.mkdir(parents=True, exist_ok=True)
    frames: list[pd.DataFrame] = []
    for stock in stocks.itertuples():
        path = actions_dir / f"{stock.symbol}_splits.csv"
        if not path.exists():
            try:
                series = yf.Ticker(str(stock.yahoo_symbol)).splits
            except Exception:  # pragma: no cover - network can fail during collection.
                continue
            frame = pd.DataFrame({"date": pd.to_datetime(series.index).tz_localize(None).strftime("%Y-%m-%d"),
                                  "ratio": series.to_numpy()})
            frame.insert(0, "symbol", stock.symbol)
            frame.to_csv(path, index=False)
        frames.append(pd.read_csv(path))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["symbol", "date", "ratio"])


def _fill_listing_dates(first_dates: pd.DataFrame) -> None:
    """Record config/stocks.csv ``listing_date`` from the first real trading day.

    Only for stocks whose first trading day falls clearly inside the download window; a stock already
    trading when the window opens has no observable listing date and is left blank.
    """
    path = CFG_DIR / "stocks.csv"
    stocks = pd.read_csv(path)
    cutoff = (pd.Timestamp(START) + pd.Timedelta(days=14)).date().isoformat()
    seen = first_dates.set_index("symbol")["first_price_date"].astype(str)
    observed = seen[seen > cutoff]
    stocks["listing_date"] = stocks["listing_date"].astype("string")
    mask = stocks["symbol"].isin(observed.index)
    stocks.loc[mask, "listing_date"] = stocks.loc[mask, "symbol"].map(observed)
    stocks.to_csv(path, index=False)


def collect_prices() -> pd.DataFrame:
    ensure_dirs()
    rows: list[pd.DataFrame] = []
    failed: list[str] = []
    for stock in load_stocks().itertuples():
        try:
            history = _history(str(stock.yahoo_symbol))
            history = history.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
            history.insert(0, "symbol", stock.symbol)
            rows.append(history[["symbol", "date", "open", "high", "low", "close", "adj_close", "volume"]])
        except Exception as exc:  # pragma: no cover
            failed.append(f"{stock.symbol}({exc})")
    if not rows:
        empty = pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "adj_close", "volume", "traded_value_cr", "source", "source_url", "fetched_at"])
        write_csv_guarded(empty, CSV_DIR / "prices_daily.csv")
        append_fetch_log("prices", "failed", 0, "no stock prices downloaded")
        return empty
    raw = pd.concat(rows, ignore_index=True).drop_duplicates(subset=["symbol", "date"]).sort_values(["symbol", "date"]).reset_index(drop=True)
    raw_dir = RAW_DIR / "yahoo_prices"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw.to_csv(raw_dir / "prices_raw.csv", index=False)

    # Flag >50% single-day moves in the raw download, then apply the documented decisions (price_cleaning.py).
    flags = flag_jumps(raw)
    result = clean_prices(raw, _load_splits(load_stocks()))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not flags.empty:
        flags.to_csv(REPORT_DIR / "price_quality_flags.csv", index=False)
    write_reports(result, REPORT_DIR)

    frame = result.prices
    validate_prices(frame)  # raises (and leaves the previous CSV untouched) on future dates, duplicates, non-positive prices
    frame["traded_value_cr"] = (frame["close"] * frame["volume"] / 1e7).round(3)
    frame["source"] = "Yahoo Finance via yfinance"
    frame["source_url"] = "https://finance.yahoo.com"
    frame["fetched_at"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    frame.to_csv(CSV_DIR / "prices_daily.csv", index=False)

    first_dates = frame.groupby("symbol")["date"].min().reset_index(name="first_price_date")
    first_dates.to_csv(CSV_DIR / "stock_first_price_date.csv", index=False)
    _fill_listing_dates(first_dates)

    append_fetch_log("prices", "ok" if not failed else "partial", len(frame), ", ".join(failed)[:200])
    return frame


if __name__ == "__main__":
    collect_prices()
