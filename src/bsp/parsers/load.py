"""Idempotently load Phase 1 CSV files into the budget_lines database table."""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, inspect, text

from bsp.common.config import get_project_root
from bsp.common.db import create_engine

CSV_DIR = get_project_root() / "data" / "csv"
BUDGET_FILES = (
    "budget_ministries.csv",
    "budget_schemes.csv",
    "budget_fiscal.csv",
    "budget_demands.csv",
)
SOURCE_TYPES = {"ministry", "scheme", "subsidy", "fiscal", "demand"}


def _number(value: str | None) -> float | None:
    return float(value) if value not in (None, "") else None


def _read_budget_rows(csv_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    loaded_at = datetime.now(UTC).replace(tzinfo=None)
    for filename in BUDGET_FILES:
        path = csv_dir / filename
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                line_type = str(source.get("line_type") or ("demand" if "demand" in filename else ""))
                if line_type == "demand":
                    line_name = source.get("department") or source.get("ministry")
                    canonical_name = source.get("ministry") or line_name
                    amount = _number(source.get("total_cr"))
                    capex = _number(source.get("capital_cr"))
                    revenue = _number(source.get("revenue_cr"))
                else:
                    line_name = source.get("line_item")
                    canonical_name = source.get("canonical_name")
                    amount = _number(source.get("amount_cr"))
                    capex = _number(source.get("capex_cr"))
                    revenue = _number(source.get("revenue_cr"))
                if line_type not in SOURCE_TYPES or not line_name or not source.get("fiscal_year"):
                    raise ValueError(f"{filename}: malformed budget row {source}")
                missing_provenance = [
                    field
                    for field in ("source_doc", "source_page", "source_url", "fetched_at")
                    if not source.get(field)
                ]
                if missing_provenance:
                    raise ValueError(
                        f"{filename}: budget row is missing provenance "
                        f"{missing_provenance}: {source}"
                    )
                rows.append(
                    {
                        "fiscal_year": source["fiscal_year"],
                        "line_type": line_type,
                        "line_name": line_name,
                        "canonical_name": canonical_name,
                        "stage": source.get("stage"),
                        "amount_cr": amount,
                        "capex_cr": capex,
                        "revenue_cr": revenue,
                        "source_doc": source.get("source_doc"),
                        "source_page": str(source.get("source_page") or ""),
                        "source_url": source.get("source_url"),
                        "fetched_at": _parse_fetched_at(source.get("fetched_at"), loaded_at),
                    }
                )
    return rows


def _parse_fetched_at(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed


def load_budget_csvs(
    database_url: str | None = None, csv_dir: str | Path = CSV_DIR
) -> int:
    rows = _read_budget_rows(Path(csv_dir))
    engine = create_engine(database_url=database_url)
    inspector = inspect(engine)
    if not inspector.has_table("budget_lines") or not inspector.has_table("fetch_log"):
        raise RuntimeError("Database schema is not migrated; run `make db-migrate` first")
    started_at = datetime.now(UTC).replace(tzinfo=None)
    job_name = "phase1_budget_csv_load"
    try:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM budget_lines WHERE line_type IN :line_types").bindparams(
                    bindparam("line_types", expanding=True),
                    line_types=tuple(SOURCE_TYPES)
                )
            )
            if rows:
                connection.execute(text("INSERT INTO budget_lines "
                    "(fiscal_year, line_type, line_name, canonical_name, stage, amount_cr, capex_cr, "
                    "revenue_cr, source_doc, source_page, source_url, fetched_at) "
                    "VALUES (:fiscal_year, :line_type, :line_name, :canonical_name, :stage, :amount_cr, "
                    ":capex_cr, :revenue_cr, :source_doc, :source_page, :source_url, :fetched_at)"), rows)
            connection.execute(
                text(
                    "INSERT INTO fetch_log (job, started_at, finished_at, rows, status, error) "
                    "VALUES (:job, :started_at, :finished_at, :rows, :status, :error)"
                ),
                {
                    "job": job_name,
                    "started_at": started_at,
                    "finished_at": datetime.now(UTC).replace(tzinfo=None),
                    "rows": len(rows),
                    "status": "success",
                    "error": None,
                },
            )
    except Exception as exc:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO fetch_log (job, started_at, finished_at, rows, status, error) "
                    "VALUES (:job, :started_at, :finished_at, :rows, :status, :error)"
                ),
                {
                    "job": job_name,
                    "started_at": started_at,
                    "finished_at": datetime.now(UTC).replace(tzinfo=None),
                    "rows": 0,
                    "status": "failed",
                    "error": str(exc),
                },
            )
        raise
    finally:
        engine.dispose()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url")
    parser.add_argument("--csv-dir", type=Path, default=CSV_DIR)
    args = parser.parse_args()
    count = load_budget_csvs(args.database_url, args.csv_dir)
    print(f"loaded {count} budget rows")


if __name__ == "__main__":
    main()
