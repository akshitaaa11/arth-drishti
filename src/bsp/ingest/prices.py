from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf

from bsp.ingest._common import CSV_DIR, append_fetch_log, ensure_dirs, load_stocks

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


def collect_prices() -> pd.DataFrame:
    ensure_dirs()
    rows: list[pd.DataFrame] = []
    failed: list[str] = []
    for stock in load_stocks().itertuples():
        try:
            history = _history(stock.yahoo_symbol)
            history = history.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"})
            history.insert(0, "symbol", stock.symbol)
            rows.append(history[["symbol", "date", "open", "high", "low", "close", "adj_close", "volume"]])
        except Exception as exc:  # pragma: no cover
            failed.append(f"{stock.symbol}({exc})")
    if not rows:
        empty = pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "adj_close", "volume", "traded_value_cr", "source", "source_url", "fetched_at"])
        empty.to_csv(CSV_DIR / "prices_daily.csv", index=False)
        append_fetch_log("prices", "failed", 0, "no stock prices downloaded")
        return empty
    frame = pd.concat(rows, ignore_index=True).drop_duplicates(subset=["symbol", "date"]).sort_values(["symbol", "date"]).reset_index(drop=True)
    frame["traded_value_cr"] = (frame["close"] * frame["volume"] / 1e7).round(3)
    frame["source"] = "Yahoo Finance via yfinance"
    frame["source_url"] = "https://finance.yahoo.com"
    frame["fetched_at"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    frame.to_csv(CSV_DIR / "prices_daily.csv", index=False)

    first_dates = frame.groupby("symbol", as_index=False)["date"].min().rename(columns={"date": "first_price_date"})
    first_dates.to_csv(CSV_DIR / "stock_first_price_date.csv", index=False)

    quality = frame.copy()
    quality["ret"] = quality.groupby("symbol")["close"].pct_change()
    flags = quality[(quality["ret"].abs() > 0.5) | (quality["close"] <= 0) | (quality["volume"] < 0)]
    if not flags.empty:
        REPORT_DIR = Path(__file__).resolve().parents[3] / "reports"
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        flags.to_csv(REPORT_DIR / "price_quality_flags.csv", index=False)

    append_fetch_log("prices", "ok" if not failed else "partial", len(frame), ", ".join(failed)[:200])
    return frame


if __name__ == "__main__":
    collect_prices()
