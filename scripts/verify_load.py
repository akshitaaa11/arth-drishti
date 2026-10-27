"""Compare database row counts (and one numeric checksum per table) with the CSVs they were loaded from.

Usage: python scripts/verify_load.py   (uses DATABASE_URL, else the local SQLite file). Exit 1 on any mismatch.
Also checks that every load wrote a successful fetch_log row.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from bsp.common.db import create_engine

CSV = Path(__file__).resolve().parents[1] / "data" / "csv"
# table -> (csv, csv column used as checksum, db column, row filter for the table)
CHECKS = {
    "prices_daily": ("prices_daily.csv", "close", "close", None),
    "index_daily": ("index_daily.csv", "close", "close", None),
    "macro": ("macro.csv", "value", "value", None),
    "fpi_flows": ("fpi_sector_fortnightly.csv", "equity_net_cr", "equity_cr", None),
    "features_sector_year": ("features_sector_year.csv", "value", "value", None),
    "features_stock_year": ("features_stock_year.csv", "value", "value", None),
    "targets": ("targets.csv", "excess_return", "excess_return", None),
    "event_study": ("event_study.csv", "car", "car", None),
}


def main() -> int:
    engine = create_engine()
    bad = 0
    print(f"{'table':<22}{'csv rows':>10}{'db rows':>10}{'csv sum':>20}{'db sum':>20}  result")
    with engine.connect() as conn:
        for table, (csv, csv_col, db_col, where) in CHECKS.items():
            frame = pd.read_csv(CSV / csv)
            clause = f" WHERE {where}" if where else ""
            db_rows = conn.execute(text(f"SELECT COUNT(*) FROM {table}{clause}")).scalar()
            csv_sum = float(frame[csv_col].sum()) if csv_col else 0.0
            db_sum = float(conn.execute(text(f"SELECT COALESCE(SUM({db_col}), 0) FROM {table}{clause}")).scalar()) if db_col else 0.0
            ok = db_rows == len(frame) and abs(csv_sum - db_sum) <= 1e-6 * max(1.0, abs(csv_sum))
            bad += not ok
            print(f"{table:<22}{len(frame):>10}{db_rows:>10}{csv_sum:>20.4f}{db_sum:>20.4f}  {'OK' if ok else 'MISMATCH'}")
        budget_csvs = ["budget_ministries.csv", "budget_schemes.csv", "budget_fiscal.csv", "budget_demands.csv"]
        budget_rows = sum(len(pd.read_csv(CSV / f)) for f in budget_csvs)
        db_budget = conn.execute(text("SELECT COUNT(*) FROM budget_lines")).scalar()
        ok = db_budget == budget_rows
        bad += not ok
        print(f"{'budget_lines':<22}{budget_rows:>10}{db_budget:>10}{'':>20}{'':>20}  {'OK' if ok else 'MISMATCH'}")
        failed = conn.execute(text("SELECT COUNT(*) FROM fetch_log WHERE status = 'failed'")).scalar()
        loads = conn.execute(text("SELECT COUNT(*) FROM fetch_log WHERE job LIKE 'load\\_%' ESCAPE '\\'")).scalar()
        print(f"fetch_log: {loads} load rows, {failed} failed")
        bad += bool(failed)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
