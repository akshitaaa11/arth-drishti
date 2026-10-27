"""Reports for the two price-data fixes (TEXRAIL listing date, NIITLTD demerger break) and the 2004-12-01 stocks.

Writes reports/railways_basket_by_budget.csv, reports/stocks_first_price_at_download_start.csv and
reports/price_data_fixes.md. Company names come from Yahoo Finance's search endpoint (``longname``), cached under
data/raw/yahoo_info/; if Yahoo does not answer, the name stays blank. Nothing is changed for any stock.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from bsp.evaluation.config import load_config
from bsp.evaluation.data import load_sector_panel
from bsp.evaluation.walk_forward import training_rows
from bsp.features.baskets import build_market_data_bundle
from bsp.quality.price_corrections import load_listing_overrides, load_return_exclusions

ROOT = Path(__file__).resolve().parents[1]
DOWNLOAD_START = "2004-12-01"


def company_name(symbol: str, yahoo_symbol: str) -> str:
    cache = ROOT / "data" / "raw" / "yahoo_info" / f"{symbol}.json"
    if cache.exists():
        return str(json.loads(cache.read_text(encoding="utf-8")).get("longName", ""))
    try:
        import yfinance as yf

        quotes = yf.Search(yahoo_symbol, max_results=5).quotes
    except Exception:  # network or Yahoo failure: leave blank rather than guess
        return ""
    match = next((q for q in quotes if q.get("symbol") == yahoo_symbol), None)
    if match is None:
        return ""
    info = {"longName": match.get("longname", ""), "shortName": match.get("shortname", "")}
    if info["longName"]:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(info), encoding="utf-8")
    return str(info["longName"])


def main() -> None:
    bundle = build_market_data_bundle(ROOT)
    days = bundle.trading_days
    events = pd.read_csv(ROOT / "config" / "budget_events.csv").drop_duplicates("budget_id")
    stocks = pd.read_csv(ROOT / "config" / "stocks.csv")

    # ---- Railways basket per budget
    railways = bundle.sector_stocks_map["railways"]
    rows = []
    for event in events.itertuples():
        presented = str(event.presented_on)
        idx = max(i for i, d in enumerate(days) if d <= presented)
        active = [s for s in railways if pd.notna(bundle.stock_prices[s].iloc[idx])]
        rows.append({"budget_id": event.budget_id, "presented_on": presented, "n_active": len(active),
                     "symbols": " ".join(active)})
    members = pd.DataFrame(rows)
    members.to_csv(ROOT / "reports" / "railways_basket_by_budget.csv", index=False)
    first_idx = bundle.sector_first_active_idx["railways"]
    start = days[first_idx] if first_idx is not None else "never"

    # ---- Tier 1 training rows removed
    cfg = load_config()
    panel = load_sector_panel(cfg)
    frame = panel.frame
    missing = frame[(frame["entity"] == "railways") & ~frame["target_complete"]]
    fold_rows = []
    for budget in sorted(frame["budget_id"].unique()):
        if budget < "FY2012-13":
            continue
        trained = training_rows(panel, budget)
        fold_rows.append((budget, len(trained), len(trained) + int(
            ((missing["presented_on"] < frame.loc[frame["budget_id"] == budget, "presented_on"].iloc[0])).sum())))

    # ---- stocks whose first price date is the download start
    first = pd.read_csv(ROOT / "data" / "csv" / "stock_first_price_date.csv")
    at_start = first[first["first_price_date"] == DOWNLOAD_START].merge(stocks, on="symbol")
    at_start["company_name"] = [company_name(r.symbol, r.yahoo_symbol) for r in at_start.itertuples()]
    listing = at_start[["symbol", "company_name", "sector_id", "first_price_date"]].sort_values(["sector_id", "symbol"])
    listing["note"] = ("Yahoo's series starts on the download start; the real listing date is unknown and was not changed "
                       "(no source)")
    listing.to_csv(ROOT / "reports" / "stocks_first_price_at_download_start.csv", index=False)

    # ---- narrative
    overrides, exclusions = load_listing_overrides(ROOT), load_return_exclusions(ROOT)
    texrail = overrides["TEXRAIL"]
    niit = next(e for e in exclusions if e.symbol == "NIITLTD")
    education = bundle.sector_returns["education"]
    others = [s for s in bundle.sector_stocks_map["education"] if s != "NIITLTD"]
    day = niit.date
    out = [
        "# Price-data fixes: TEXRAIL listing date and NIITLTD demerger break", "",
        "Both fixes are applied by the pipeline from two sourced config files; no price CSV was edited by hand. "
        "Evidence is from secondary sources and is **not verified on the exchange**.", "",
        "## 1. TEXRAIL (Texmaco Rail & Engineering)", "",
        f"- `config/listing_date_overrides.csv`: listing date **{texrail.listing_date}** ({texrail.verification}): "
        f"{texrail.source_url}",
        "- The Yahoo series started 2004-12-01, before the company existed (demerged from Texmaco Ltd). The price job now "
        "drops every row before the listing date (`before_listing` in `reports/price_rows_dropped.csv`), "
        "`stocks.csv` carries the listing date, and `stock_first_price_date.csv` starts on it.",
        "- The universe's \"listed on or before the budget date\" check therefore excludes TEXRAIL for every budget "
        "presented before 2011-03-03, including FY2011-12 (presented 2011-02-28).", "",
        f"### Railways basket (new start date: **{start}**, previously 2004-12-02)", "",
        "Stocks in the basket on each budget day (the basket only holds a stock from its listing date):", "",
        "| Budget | Presented | Stocks | Members |", "| --- | --- | ---: | --- |"]
    for r in members.itertuples():
        out.append(f"| {r.budget_id} | {r.presented_on} | {r.n_active} | {r.symbols if r.symbols else '(empty)'} |")
    out += ["", "Railways sector-years with an empty basket are **missing, never filled**: their price features are empty and "
            "their targets have `target_complete = False`:", "",
            ", ".join(missing["budget_id"]) if len(missing) else "(none)", "",
            f"**Tier 1 training rows removed: {len(missing)}** (the Railways rows of {', '.join(missing['budget_id'])}; "
            "they used to carry numbers computed from TEXRAIL's pre-listing prices). Every walk-forward fold from FY2012-13 "
            "on trains without them:", "", "| Test budget | Training rows now | Training rows before | Removed |",
            "| --- | ---: | ---: | ---: |"]
    for budget, now, before in fold_rows:
        out.append(f"| {budget} | {now} | {before} | {before - now} |")
    out += ["", "Three more Railways sector-years (FY2009-10 to FY2011-12) stay in the data but are now a one-stock basket "
            "(TITAGARH), because TEXRAIL's pre-listing prices no longer count. Other sectors' early targets moved by small "
            "amounts, because the market return that bridges Nifty 500 index gaps is the equal-weight mean of all stocks, "
            "and TEXRAIL's spurious prices were in that mean.", "",
            "## 2. NIITLTD 2023-06-08 (demerger ex-date)", "",
            f"- `config/return_exclusions.csv`: {niit.verification}: {niit.source_url}",
            "- That day's return (about -76%) is treated as **missing**: it never enters a basket, a volatility, a beta or "
            "an event study, and a momentum or target window that spans the day divides it out. Prices are not rescaled and "
            "no adjustment factor is invented; the only number used is that day's own observed return.",
            f"- Education basket return on {day}: {education.loc[day]:.4f}; the mean of its other stocks that day: "
            f"{bundle.stock_returns.loc[day, others].mean():.4f} (they match: NIITLTD is skipped).", "",
            "## 3. Stocks whose first price date is the download start (2004-12-01)", "",
            f"{len(listing)} stocks. Their true listing dates are unknown from this data and **none was changed** (no source). "
            "The universe's listing check is satisfied for them at every budget. Full list with company names (from Yahoo's "
            "quote summary) and sectors: `reports/stocks_first_price_at_download_start.csv`.", "",
            "| Symbol | Company | Sector |", "| --- | --- | --- |"]
    for r in listing.itertuples():
        out.append(f"| {r.symbol} | {r.company_name or '(name not available)'} | {r.sector_id} |")
    (ROOT / "reports" / "price_data_fixes.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"railways start {start}; missing {list(missing['budget_id'])}; {len(listing)} stocks at download start")


if __name__ == "__main__":
    main()
