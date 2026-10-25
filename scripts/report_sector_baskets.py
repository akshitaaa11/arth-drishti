"""Document each self-built sector basket: start date, thin-start period and correlation with an official index.

Reads data/csv/sector_baskets_daily.csv and index_daily.csv; mapping in config/sector_official_index.csv
(a modelling choice, not a data value: sectors without a clean official index are left out).
Writes reports/sector_basket_report.csv.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MIN_STOCKS = 3


def main() -> None:
    baskets = pd.read_csv(ROOT / "data/csv/sector_baskets_daily.csv")
    baskets["date"] = baskets["date"].astype(str)
    idx = pd.read_csv(ROOT / "data/csv/index_daily.csv")
    idx["date"] = idx["date"].astype(str)
    mapping = pd.read_csv(ROOT / "config/sector_official_index.csv").set_index("sector_id")
    rows = []
    for sector, g in baskets.groupby("sector_id"):
        live = g[g["active_stocks"] > 0].sort_values("date")
        start = live.iloc[0]
        three = live[live["active_stocks"] >= MIN_STOCKS]
        row = {
            "sector_id": sector,
            "first_date": start["date"],
            "active_stocks_at_start": int(start["active_stocks"]),
            f"first_date_with_{MIN_STOCKS}_plus_stocks": three.iloc[0]["date"] if len(three) else "",
            "official_index": "", "overlap_days": "", "daily_return_corr": "",
        }
        if sector in mapping.index:
            name = mapping.loc[sector, "official_index"]
            official = idx[idx["index_name"] == name].set_index("date")["close"].sort_index().pct_change(fill_method=None)
            basket = g.set_index("date")["daily_return"]
            joined = pd.concat([basket, official], axis=1, join="inner").dropna()
            joined.columns = ["basket", "official"]
            row.update(official_index=name, overlap_days=len(joined),
                       daily_return_corr=round(float(joined["basket"].corr(joined["official"])), 4))
        rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(ROOT / "reports/sector_basket_report.csv", index=False)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
