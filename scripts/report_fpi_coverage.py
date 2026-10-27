"""Write reports/fpi_coverage.csv: per budget, the FPI window start/end and complete / partial / empty."""

from __future__ import annotations

from pathlib import Path

from bsp.features.fpi_window import coverage_table

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    table = coverage_table(ROOT)
    table.to_csv(ROOT / "reports" / "fpi_coverage.csv", index=False)
    print(table.groupby("status").size().to_dict())
    print("complete:", ", ".join(table[table["status"] == "complete"]["budget_id"]))
