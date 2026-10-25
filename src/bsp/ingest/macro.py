from __future__ import annotations

import io

import pandas as pd
import requests

from bsp.ingest._common import (
    CSV_DIR,
    RAW_DIR,
    UA,
    append_fetch_log,
    ensure_dirs,
    write_csv_guarded,
)
from bsp.quality.schemas import validate_macro

YAHOO_MACRO = {
    "USDINR=X": ("usd_inr", "INR per USD"),
    "BZ=F": ("brent_crude_usd", "USD per barrel"),
    "CL=F": ("wti_crude_usd", "USD per barrel"),
    "^INDIAVIX": ("india_vix", "index"),
}
FRED_SERIES = {
    "INDCPIALLMINMEI": ("cpi_index_2015", "index 2015=100"),
    "IRLTLT01INM156N": ("g_sec_10y_yield", "percent"),
    "INTDSRINM193N": ("policy_discount_rate", "percent"),
}
WORLD_BANK = {
    "FP.CPI.TOTL.ZG": ("cpi_inflation_annual", "percent"),
    "NY.GDP.MKTP.KD.ZG": ("gdp_growth_annual", "percent"),
}


def _fetch_yahoo_history(ticker: str):
    import yfinance as yf
    return yf.Ticker(ticker).history(start="2004-12-01", auto_adjust=False, actions=False).reset_index()


def _fred_csv(series: str) -> pd.DataFrame:
    response = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series}, headers=UA, timeout=60)
    response.raise_for_status()
    frame = pd.read_csv(io.StringIO(response.text))
    frame.columns = ["date", "value"]
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame.dropna()


def _world_bank(indicator: str) -> pd.DataFrame:
    params: dict[str, str | int] = {"format": "json", "per_page": 200}
    response = requests.get(f"https://api.worldbank.org/v2/country/IND/indicator/{indicator}", params=params, headers=UA, timeout=60)
    response.raise_for_status()
    rows = response.json()[1]
    frame = pd.DataFrame([{"date": f"{x['date']}-12-31", "value": x["value"]} for x in rows if x.get("value") is not None])
    return frame


def collect_macro() -> pd.DataFrame:
    ensure_dirs()
    parts: list[pd.DataFrame] = []
    errors: list[str] = []
    for ticker, (name, unit) in YAHOO_MACRO.items():
        try:
            h = _fetch_yahoo_history(ticker)
            temp = pd.DataFrame({"series": name, "date": h["Date"], "value": h["Close"], "unit": unit, "source": "Yahoo Finance"})
            parts.append(temp[["series", "date", "value", "unit", "source"]])
        except Exception as exc:  # pragma: no cover
            errors.append(f"{name}({exc})")
    for series, (name, unit) in FRED_SERIES.items():
        try:
            d = _fred_csv(series)
            parts.append(d.assign(series=name, unit=unit, source=f"FRED {series}")[["series", "date", "value", "unit", "source"]])
        except Exception as exc:  # pragma: no cover
            errors.append(f"{name}({exc})")
    for series, (name, unit) in WORLD_BANK.items():
        try:
            d = _world_bank(series)
            parts.append(d.assign(series=name, unit=unit, source=f"World Bank {series}")[["series", "date", "value", "unit", "source"]])
        except Exception as exc:  # pragma: no cover
            errors.append(f"{name}({exc})")
    manual = RAW_DIR / "rbi" / "repo_rate.csv"
    if manual.exists():
        d = pd.read_csv(manual)
        parts.append(d.assign(series="repo_rate", unit="percent", source="RBI DBIE (manual download)")[["series", "date", "value", "unit", "source"]])
    else:
        errors.append("repo_rate(manual file data/raw/rbi/repo_rate.csv missing)")
    if parts:
        df = pd.concat(parts, ignore_index=True)
        df["fetched_at"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
        # A series that failed this run keeps its rows (and original fetched_at) from the previous run.
        previous_path = CSV_DIR / "macro.csv"
        if previous_path.exists():
            previous = pd.read_csv(previous_path)
            kept = previous[~previous["series"].isin(df["series"].unique())]
            df = pd.concat([df, kept], ignore_index=True)
        # Yahoo returns tz-aware timestamps and FRED/World Bank plain dates: store one ISO date per row.
        df["date"] = df["date"].astype(str).str[:10]
        df = df.drop_duplicates(subset=["series", "date"], keep="first")
        df = df.sort_values(["series", "date"]).reset_index(drop=True)
        validate_macro(df)
        df.to_csv(CSV_DIR / "macro.csv", index=False)
    else:
        empty = pd.DataFrame(columns=["series", "date", "value", "unit", "source", "fetched_at"])
        write_csv_guarded(empty, CSV_DIR / "macro.csv")
    append_fetch_log("macro", "ok" if not errors else "partial", sum(len(part) for part in parts), ", ".join(errors)[:200])
    return pd.read_csv(CSV_DIR / "macro.csv") if (CSV_DIR / "macro.csv").exists() else pd.DataFrame()


if __name__ == "__main__":
    collect_macro()
