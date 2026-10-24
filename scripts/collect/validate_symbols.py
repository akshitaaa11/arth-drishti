from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "stocks.csv"
REPORT_PATH = ROOT / "reports" / "symbol_check.csv"


def validate_symbols(csv_path: Path = CONFIG_PATH, report_path: Path = REPORT_PATH) -> list[dict[str, str]]:
    df = pd.read_csv(csv_path)
    rows: list[dict[str, str]] = []
    for row in df.itertuples(index=False):
        symbol = str(getattr(row, "symbol", "")).strip()
        yahoo_symbol = str(getattr(row, "yahoo_symbol", "")).strip()
        try:
            ticker = yf.Ticker(yahoo_symbol)
            info = ticker.fast_info
            # Use a tiny download to validate the symbol is reachable.
            history = ticker.history(period="5d", auto_adjust=True)
            status = "ok" if not history.empty else "failed"
            msg = "" if status == "ok" else "no data returned"
        except Exception as exc:  # pragma: no cover - network-dependent path
            status = "failed"
            msg = str(exc)

        rows.append({
            "symbol": symbol,
            "yahoo_symbol": yahoo_symbol,
            "status": status,
            "details": msg,
        })

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["symbol", "yahoo_symbol", "status", "details"])
        writer.writeheader()
        writer.writerows(rows)

    return rows


if __name__ == "__main__":
    try:
        rows = validate_symbols()
        ok_count = sum(1 for row in rows if row["status"] == "ok")
        print(f"Validated {len(rows)} symbols; {ok_count} OK.")
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"Failed to validate symbols: {exc}", file=sys.stderr)
        raise SystemExit(1)
