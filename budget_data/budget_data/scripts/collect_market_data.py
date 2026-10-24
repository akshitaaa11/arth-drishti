"""Collect market, flow and macro data into CSVs. RUN THIS ON A LAPTOP WITH NORMAL INTERNET.

Yahoo Finance, NSDL and FRED block most cloud servers, so this script could not be run in the build
workspace. It was written and syntax-checked there; the first real run is yours. Every step is
idempotent (re-running overwrites its CSV) and logs to data/csv/fetch_log.csv.

    pip install -r requirements.txt
    python scripts/collect_market_data.py symbols     # 1. check every stock symbol works  (run this first)
    python scripts/collect_market_data.py prices      # 2. daily prices for all stocks     -> prices_daily.csv
    python scripts/collect_market_data.py indices     # 3. Nifty 500 + sector indices      -> index_daily.csv
    python scripts/collect_market_data.py macro       # 4. macro series                     -> macro.csv
    python scripts/collect_market_data.py fpi         # 5. NSDL sector-wise FPI             -> fpi_sector_fortnightly_long.csv
    python scripts/collect_market_data.py all

Nothing here invents data. A failed download leaves a gap that is written to the fetch log.
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
CSV, RAW, CFG, REP = ROOT / "data/csv", ROOT / "data/raw", ROOT / "config", ROOT / "reports"
START = "2004-12-01"  # a little before the first budget (Feb 2005) so the 250-day windows exist
UA = {"User-Agent": "Mozilla/5.0 (research project; contact: see repository README)"}

INDICES = {  # Yahoo ticker -> our name. Some may be missing on Yahoo; failures are logged, not hidden.
    "^CRSLDX": "Nifty 500", "^NSEI": "Nifty 50", "^CNXIT": "Nifty IT", "^CNXINFRA": "Nifty Infrastructure",
    "^CNXREALTY": "Nifty Realty", "^CNXPHARMA": "Nifty Pharma", "^CNXHEALTH": "Nifty Healthcare",
    "^CNXFMCG": "Nifty FMCG", "^CNXPSUBANK": "Nifty PSU Bank", "^CNXENERGY": "Nifty Energy",
    "^CNXAUTO": "Nifty Auto", "^CNXPSE": "Nifty PSE", "^NSEBANK": "Nifty Bank", "^CNXMETAL": "Nifty Metal",
    "^CNXFIN": "Nifty Financial Services", "^CNXMEDIA": "Nifty Media", "^CNXCONSUM": "Nifty India Consumption",
    "^INDIAVIX": "India VIX",
}
YAHOO_MACRO = {"USDINR=X": ("usd_inr", "INR per USD"), "BZ=F": ("brent_crude_usd", "USD per barrel"),
               "CL=F": ("wti_crude_usd", "USD per barrel"), "^INDIAVIX": ("india_vix", "index")}
FRED_SERIES = {  # monthly, free CSV download, no API key. Originally from OECD / IMF, India.
    "INDCPIALLMINMEI": ("cpi_index_2015", "index 2015=100"),
    "IRLTLT01INM156N": ("g_sec_10y_yield", "percent"),
    "INTDSRINM193N": ("policy_discount_rate", "percent"),
}
WORLD_BANK = {"FP.CPI.TOTL.ZG": ("cpi_inflation_annual", "percent"), "NY.GDP.MKTP.KD.ZG": ("gdp_growth_annual", "percent")}

_log: list[dict] = []


def log(job: str, status: str, rows: int = 0, detail: str = ""):
    _log.append(dict(job=job, finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), status=status, rows=rows, detail=detail[:300]))
    print(f"[{status}] {job} rows={rows} {detail[:120]}")


def flush_log():
    CSV.mkdir(parents=True, exist_ok=True)
    p = CSV / "fetch_log.csv"
    old = pd.read_csv(p) if p.exists() else pd.DataFrame()
    pd.concat([old, pd.DataFrame(_log)], ignore_index=True).to_csv(p, index=False)


def stocks() -> pd.DataFrame:
    return pd.read_csv(CFG / "stocks.csv")


def yahoo_history(ticker: str, start: str = START, retries: int = 3) -> pd.DataFrame:
    import yfinance as yf
    err = ""
    for k in range(retries):
        try:
            h = yf.Ticker(ticker).history(start=start, auto_adjust=False, actions=False)
            if len(h):
                h = h.reset_index()
                h["Date"] = pd.to_datetime(h["Date"]).dt.tz_localize(None).dt.date
                return h
            err = "empty response"
        except Exception as e:  # network / delisted
            err = str(e)
        time.sleep(2 * (k + 1))
    raise RuntimeError(err)


# ---------------------------------------------------------------- 1. symbols
def cmd_symbols():
    rows = []
    for r in stocks().itertuples():
        try:
            h = yahoo_history(r.yahoo_symbol, start=(date.today() - timedelta(days=20)).isoformat(), retries=1)
            rows.append(dict(symbol=r.symbol, yahoo_symbol=r.yahoo_symbol, status="ok", last_close=round(float(h.Close.iloc[-1]), 2)))
        except Exception as e:
            rows.append(dict(symbol=r.symbol, yahoo_symbol=r.yahoo_symbol, status="FAILED", last_close=None, error=str(e)[:100]))
        time.sleep(0.3)
    REP.mkdir(exist_ok=True)
    out = pd.DataFrame(rows)
    out.to_csv(REP / "symbol_check.csv", index=False)
    bad = out[out.status != "ok"]
    log("symbols", "ok" if bad.empty else "partial", len(out), f"{len(bad)} failed: {','.join(bad.symbol)}")
    print("\nFix or drop the FAILED symbols in config/stocks.csv (renamed / merged / delisted), then run `prices`.")


# ---------------------------------------------------------------- 2. prices
def cmd_prices():
    frames, failed = [], []
    for r in stocks().itertuples():
        try:
            h = yahoo_history(r.yahoo_symbol)
            h = h.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close",
                                  "Adj Close": "adj_close", "Volume": "volume"})
            h.insert(0, "symbol", r.symbol)
            frames.append(h[["symbol", "date", "open", "high", "low", "close", "adj_close", "volume"]])
        except Exception as e:
            failed.append(f"{r.symbol}({str(e)[:40]})")
        time.sleep(0.4)
    if not frames:
        log("prices", "FAILED", 0, "no symbol downloaded; check internet / yfinance version")
        return
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["symbol", "date"]).sort_values(["symbol", "date"])
    df["traded_value_cr"] = (df.close * df.volume / 1e7).round(3)
    df["source"], df["source_url"], df["fetched_at"] = "Yahoo Finance via yfinance", "https://finance.yahoo.com", datetime.now(timezone.utc).isoformat(timespec="seconds")
    df.to_csv(CSV / "prices_daily.csv", index=False)
    # first trading day per stock -> proxy for listing date inside the window
    first = df.groupby("symbol").date.min().rename("first_price_date").reset_index()
    first.to_csv(CSV / "stock_first_price_date.csv", index=False)
    quality(df)
    log("prices", "ok" if not failed else "partial", len(df), f"{len(failed)} failed: {', '.join(failed)[:200]}")


def quality(df: pd.DataFrame):
    """Flag suspicious rows; never delete them silently."""
    d = df.sort_values(["symbol", "date"]).copy()
    d["ret"] = d.groupby("symbol").close.pct_change()
    flags = d[(d.ret.abs() > 0.5) | (d.close <= 0) | (d.volume < 0)]
    REP.mkdir(exist_ok=True)
    flags.to_csv(REP / "price_quality_flags.csv", index=False)
    print(f"price quality: {len(flags)} flagged rows (jumps >50%, non-positive prices) -> reports/price_quality_flags.csv")


# ---------------------------------------------------------------- 3. indices
def cmd_indices():
    frames, failed = [], []
    for t, name in INDICES.items():
        try:
            h = yahoo_history(t)
            h = h.rename(columns={"Date": "date", "Close": "close", "Volume": "volume"})
            h.insert(0, "index_name", name)
            h.insert(1, "ticker", t)
            frames.append(h[["index_name", "ticker", "date", "close", "volume"]])
        except Exception as e:
            failed.append(f"{name}({str(e)[:30]})")
        time.sleep(0.4)
    if frames:
        df = pd.concat(frames, ignore_index=True).drop_duplicates(["index_name", "date"])
        df["source"], df["fetched_at"] = "Yahoo Finance via yfinance", datetime.now(timezone.utc).isoformat(timespec="seconds")
        df.to_csv(CSV / "index_daily.csv", index=False)
        span = df.groupby("index_name").date.agg(["min", "max", "count"]).reset_index()
        span.to_csv(REP / "index_coverage.csv", index=False)
        print(span.to_string(index=False))
    log("indices", "ok" if frames and not failed else "partial", sum(len(f) for f in frames), f"missing on Yahoo: {', '.join(failed)[:200]}")
    if failed:
        print("For indices missing on Yahoo (e.g. Nifty India Defence) download the history CSV from niftyindices.com "
              "into data/raw/indices_manual/<name>.csv with columns Date,Close; the build step merges them.")


# ---------------------------------------------------------------- 4. macro
def fred_csv(series: str) -> pd.DataFrame:
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series}, headers=UA, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df.value, errors="coerce")
    return df.dropna()


def world_bank(ind: str) -> pd.DataFrame:
    r = requests.get(f"https://api.worldbank.org/v2/country/IND/indicator/{ind}", params={"format": "json", "per_page": 200}, headers=UA, timeout=60)
    r.raise_for_status()
    rows = r.json()[1]
    return pd.DataFrame([{"date": f"{x['date']}-12-31", "value": x["value"]} for x in rows if x["value"] is not None])


def cmd_macro():
    out, failed = [], []
    for t, (name, unit) in YAHOO_MACRO.items():
        try:
            h = yahoo_history(t)
            out.append(pd.DataFrame({"series": name, "date": h.Date, "value": h.Close, "unit": unit, "source": "Yahoo Finance"}))
        except Exception as e:
            failed.append(f"{name}({str(e)[:30]})")
    for s, (name, unit) in FRED_SERIES.items():
        try:
            d = fred_csv(s)
            out.append(d.assign(series=name, unit=unit, source=f"FRED {s} (OECD/IMF)")[["series", "date", "value", "unit", "source"]])
        except Exception as e:
            failed.append(f"{name}({str(e)[:30]})")
    for s, (name, unit) in WORLD_BANK.items():
        try:
            d = world_bank(s)
            out.append(d.assign(series=name, unit=unit, source=f"World Bank {s}")[["series", "date", "value", "unit", "source"]])
        except Exception as e:
            failed.append(f"{name}({str(e)[:30]})")
    # RBI repo rate: DBIE has no stable CSV URL. Drop the file in by hand: data/raw/rbi/repo_rate.csv  (date,value)
    manual = RAW / "rbi/repo_rate.csv"
    if manual.exists():
        m = pd.read_csv(manual)
        out.append(m.assign(series="repo_rate", unit="percent", source="RBI DBIE (manual download)")[["series", "date", "value", "unit", "source"]])
    else:
        failed.append("repo_rate(manual file data/raw/rbi/repo_rate.csv missing)")
    if out:
        df = pd.concat(out, ignore_index=True)
        df["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        df.to_csv(CSV / "macro.csv", index=False)
    log("macro", "ok" if not failed else "partial", sum(len(o) for o in out), "; ".join(failed)[:250])


# ---------------------------------------------------------------- 5. FPI
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
FPI_URL = "https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_{month}{day}{year}.html"


def fortnight_ends(first_year: int = 2017):
    d = date(first_year, 1, 1)
    today = date.today()
    while d <= today:
        mid = date(d.year, d.month, 15)
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        for pe in (mid, nxt - timedelta(days=1)):
            if pe < today:  # only fortnights that have ended
                yield pe
        d = nxt


def flatten_columns(cols) -> list[str]:
    out = []
    for c in cols:
        parts = [str(p).strip() for p in (c if isinstance(c, tuple) else [c]) if not str(p).startswith("Unnamed")]
        seen = []
        for p in parts:
            if p not in seen:
                seen.append(p)
        out.append(" | ".join(seen))
    return out


def parse_fpi_html(html: str, period_end: date) -> pd.DataFrame:
    tables = pd.read_html(io.StringIO(html))
    best = max(tables, key=lambda t: t.shape[1])
    best.columns = flatten_columns(best.columns)
    sector_col = next((c for c in best.columns if "Sector" in c), best.columns[1])
    best = best.drop(columns=[c for c in best.columns if c.strip().lower().startswith("sr")], errors="ignore")
    long = best.melt(id_vars=[sector_col], var_name="column_header", value_name="value").rename(columns={sector_col: "sector"})
    long["value"] = pd.to_numeric(long.value.astype(str).str.replace(",", "").str.replace("(", "-").str.replace(")", ""), errors="coerce")
    long = long.dropna(subset=["value"])
    long = long[~long.sector.astype(str).str.fullmatch(r"\d+")]
    long["period_end"] = period_end.isoformat()
    return long


def cmd_fpi(first_year: int = 2017):
    raw_dir = RAW / "nsdl_fpi"
    raw_dir.mkdir(parents=True, exist_ok=True)
    frames, missing = [], []
    for pe in fortnight_ends(first_year):
        url = FPI_URL.format(month=MONTHS[pe.month - 1], day=pe.day, year=pe.year)
        f = raw_dir / f"{pe.isoformat()}.html"
        if not f.exists():
            try:
                r = requests.get(url, headers=UA, timeout=60)
                if r.status_code != 200:
                    missing.append(pe.isoformat())
                    continue
                f.write_text(r.text, encoding="utf-8")
                time.sleep(1.0)  # be polite
            except Exception:
                missing.append(pe.isoformat())
                continue
        try:
            part = parse_fpi_html(f.read_text(encoding="utf-8"), pe)
            part["source_url"] = url
            frames.append(part)
        except Exception as e:
            missing.append(f"{pe.isoformat()}(parse: {str(e)[:30]})")
    if frames:
        df = pd.concat(frames, ignore_index=True)
        df["source"], df["fetched_at"] = "NSDL FPI Monitor, fortnightly sector-wise", datetime.now(timezone.utc).isoformat(timespec="seconds")
        df.to_csv(CSV / "fpi_sector_fortnightly_long.csv", index=False)
        print("column headers seen (use these to pick Equity / Debt / Net Investment columns):")
        print(df.column_header.drop_duplicates().head(50).to_string(index=False))
    log("fpi", "ok" if frames and len(missing) < 5 else "partial", sum(len(f) for f in frames), f"{len(missing)} fortnights not found/parsed: {missing[:6]}")


COMMANDS = {"symbols": cmd_symbols, "prices": cmd_prices, "indices": cmd_indices, "macro": cmd_macro, "fpi": cmd_fpi}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=[*COMMANDS, "all"])
    a = ap.parse_args()
    CSV.mkdir(parents=True, exist_ok=True)
    REP.mkdir(exist_ok=True)
    try:
        for name in (COMMANDS if a.command == "all" else [a.command]):
            COMMANDS[name]()
    finally:
        flush_log()
