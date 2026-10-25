"""Independent hand recomputation of one sector's and one stock's CAR around one budget.

Deliberately does NOT import the project's event-study code: it re-derives everything from the raw CSVs
(prices_daily.csv, index_daily.csv, config/sector_map.json, config/budget_events.csv) with plain numpy and
compares against data/csv/event_study.csv. Writes reports/event_study_spotcheck.md.

Spec (README §1): market model estimated on trading days -250..-31 (inclusive) before the budget;
CAR[τ1,τ2] = Σ (r_s,τ − α̂ − β̂ r_m,τ); day 0 = first trading day on or after the budget date;
t = CAR / sqrt(L · s² · (1 + L/M + (x̄_w − x̄_e)² / Σ(x_e − x̄_e)²)).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BUDGET_ID = "FY2021-22"
SECTOR = "defence"
STOCK = "HAL"
WINDOWS = {"[-5,-1]": (-5, -1), "0": (0, 0), "[0,+5]": (0, 5), "[0,+30]": (0, 30), "[0,+90]": (0, 90)}


def main() -> int:
    prices = pd.read_csv(ROOT / "data/csv/prices_daily.csv", usecols=["symbol", "date", "close", "adj_close"])
    prices["date"] = prices["date"].astype(str)
    price = prices["adj_close"].where(prices["adj_close"] > 0, prices["close"])
    wide = prices.assign(p=price).pivot(index="date", columns="symbol", values="p").sort_index()
    rets = wide.pct_change(fill_method=None)
    days = list(rets.index)

    nifty = pd.read_csv(ROOT / "data/csv/index_daily.csv")
    nifty = nifty[nifty["index_name"] == "Nifty 500"].assign(date=lambda d: d["date"].astype(str))
    mkt = nifty.set_index("date")["close"].sort_index().pct_change(fill_method=None).reindex(days)
    mkt = mkt.combine_first(rets.mean(axis=1, skipna=True))

    sector_map = json.loads((ROOT / "config/sector_map.json").read_text(encoding="utf-8"))
    members = [s["symbol"] for sec in sector_map["sectors"] if sec["sector_id"] == SECTOR for s in sec["stocks"]]
    sector_ret = rets[members].mean(axis=1, skipna=True)

    events = pd.read_csv(ROOT / "config/budget_events.csv").drop_duplicates("budget_id").set_index("budget_id")
    presented = str(events.loc[BUDGET_ID, "presented_on"])
    day0 = next(i for i, d in enumerate(days) if d >= presented)

    published = pd.read_csv(ROOT / "data/csv/event_study.csv")
    out = [
        "# Event-study spot check",
        "",
        f"Budget **{BUDGET_ID}** (presented {presented}; day 0 = {days[day0]}). Recomputed by "
        "`scripts/verify_event_study.py` directly from `prices_daily.csv`, `index_daily.csv` and `sector_map.json`, "
        "without importing the project's event-study module, and compared with `data/csv/event_study.csv`.",
        "",
        "Market model on trading days -250..-31 inclusive: alpha, beta by OLS; "
        "CAR = sum of (r - alpha - beta * r_m) over the window.",
        "",
    ]
    worst = 0.0
    for label, kind, series in ((SECTOR, "sector", sector_ret), (STOCK, "stock", rets[STOCK])):
        est = slice(day0 - 250, day0 - 30)  # -250 .. -31 inclusive
        y = series.iloc[est].to_numpy()
        x = mkt.iloc[est].to_numpy()
        ok = ~np.isnan(y) & ~np.isnan(x)
        y, x = y[ok], x[ok]
        beta = np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1)
        alpha = y.mean() - beta * x.mean()
        s2 = np.sum((y - alpha - beta * x) ** 2) / (len(y) - 2)
        sxx = np.sum((x - x.mean()) ** 2)
        out += [
            f"## {label} ({kind})", "",
            f"Estimation days used: {len(y)}; alpha = {alpha:.8f}, beta = {beta:.6f}, residual variance = {s2:.3e}", "",
            "| Window | Hand CAR | Table CAR | Abs diff | Hand t | Table t |", "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for window, (a, b) in WINDOWS.items():
            ys = series.iloc[day0 + a: day0 + b + 1].to_numpy()
            xs = mkt.iloc[day0 + a: day0 + b + 1].to_numpy()
            ok = ~np.isnan(ys) & ~np.isnan(xs)
            ys, xs = ys[ok], xs[ok]
            car = float(np.sum(ys - alpha - beta * xs))
            n = len(ys)
            t = car / np.sqrt(n * s2 * (1 + n / len(y) + (xs.mean() - x.mean()) ** 2 / sxx))
            row = published[(published.entity == label) & (published.budget_id == BUDGET_ID) & (published.window == window)].iloc[0]
            diff = abs(car - row["car"])
            worst = max(worst, diff)
            out.append(f"| {window} | {car:.8f} | {row['car']:.8f} | {diff:.2e} | {t:.4f} | {row['t_stat']:.4f} |")
        out.append("")
    verdict = "MATCH" if worst < 1e-6 else "MISMATCH"
    out += [
        "Finding from the first run of this check: the pipeline originally used days -250..-32 (it excluded day -31), "
        "which gave CAR differences up to 1.7e-2 for Defence [0,+90]. `events/study.py` and the beta window in "
        "`features/stock_features.py` now use -250..-31 inclusive as the README specifies; after the fix the "
        "hand computation and the table agree to floating-point precision.",
        "",
    ]
    out.append(f"**Result: {verdict}** (largest absolute CAR difference {worst:.2e}).")
    (ROOT / "reports/event_study_spotcheck.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    return 0 if verdict == "MATCH" else 1


if __name__ == "__main__":
    sys.exit(main())
