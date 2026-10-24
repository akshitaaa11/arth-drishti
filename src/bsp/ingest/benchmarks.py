from __future__ import annotations

import pandas as pd
import yfinance as yf

from bsp.ingest._common import CSV_DIR, REPORT_DIR, append_fetch_log, ensure_dirs

INDICES = {
    "^CRSLDX": "Nifty 500",
    "^NSEI": "Nifty 50",
    "^CNXIT": "Nifty IT",
    "^CNXINFRA": "Nifty Infrastructure",
    "^CNXREALTY": "Nifty Realty",
    "^CNXPHARMA": "Nifty Pharma",
    "^CNXHEALTH": "Nifty Healthcare",
    "^CNXFMCG": "Nifty FMCG",
    "^CNXPSUBANK": "Nifty PSU Bank",
    "^CNXENERGY": "Nifty Energy",
    "^CNXAUTO": "Nifty Auto",
    "^CNXPSE": "Nifty PSE",
    "^NSEBANK": "Nifty Bank",
    "^CNXMETAL": "Nifty Metal",
    "^CNXFIN": "Nifty Financial Services",
    "^CNXMEDIA": "Nifty Media",
    "^CNXCONSUM": "Nifty India Consumption",
    "^INDIAVIX": "India VIX",
}


def collect_benchmarks() -> pd.DataFrame:
    ensure_dirs()
    frames: list[pd.DataFrame] = []
    failed: list[str] = []
    for ticker, name in INDICES.items():
        try:
            history = yf.Ticker(ticker).history(start="2004-12-01", auto_adjust=False, actions=False)
            if len(history) == 0:
                raise RuntimeError("empty response")
            history = history.reset_index()
            history["Date"] = pd.to_datetime(history["Date"]).dt.tz_localize(None).dt.date
            history = history.rename(columns={"Date": "date", "Close": "close", "Volume": "volume"})
            history.insert(0, "index_name", name)
            history.insert(1, "ticker", ticker)
            frames.append(history[["index_name", "ticker", "date", "close", "volume"]])
        except Exception as exc:  # pragma: no cover
            failed.append(f"{name}({exc})")
    if frames:
        df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["index_name", "date"]).sort_values(["index_name", "date"]).reset_index(drop=True)
        df["source"] = "Yahoo Finance via yfinance"
        df["fetched_at"] = pd.Timestamp.utcnow().isoformat(timespec="seconds")
        df.to_csv(CSV_DIR / "index_daily.csv", index=False)
        summary = df.groupby("index_name")["date"].agg(["min", "max", "count"]).reset_index()
        summary.columns = ["index_name", "first_date", "last_date", "rows"]
        summary.to_csv(REPORT_DIR / "index_coverage.csv", index=False)
    else:
        empty = pd.DataFrame(columns=["index_name", "ticker", "date", "close", "volume", "source", "fetched_at"])
        empty.to_csv(CSV_DIR / "index_daily.csv", index=False)
    append_fetch_log("indices", "ok" if not failed else "partial", sum(len(frame) for frame in frames), ", ".join(failed)[:200])
    return pd.read_csv(CSV_DIR / "index_daily.csv") if (CSV_DIR / "index_daily.csv").exists() else pd.DataFrame()


if __name__ == "__main__":
    collect_benchmarks()
