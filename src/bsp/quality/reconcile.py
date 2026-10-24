"""Budget total reconciliation checks."""

from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable
from dataclasses import dataclass
from numbers import Real
from pathlib import Path


@dataclass(frozen=True)
class Reconciliation:
    budget_year: str
    fiscal_year: str
    stage: str
    ministry_sum: float
    total_expenditure: float
    difference_pct: float
    status: str


def reconcile_ministry_rows(
    rows: Iterable[dict[str, object]], *, tolerance: float = 0.005
) -> list[Reconciliation]:
    """Require each complete ministry table to reconcile, without filling missing values."""
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in rows:
        if row.get("line_type") != "ministry":
            continue
        key = (
            str(row.get("budget_year", "")),
            str(row.get("fiscal_year", "")),
            str(row.get("stage", "")),
        )
        grouped.setdefault(key, []).append(row)

    results: list[Reconciliation] = []
    for (budget_year, fiscal_year, stage), group in sorted(grouped.items()):
        total = next(
            (
                amount
                for row in group
                if row.get("canonical_name") == "Total Expenditure"
                and (amount := _number(row.get("amount_cr"))) is not None
            ),
            None,
        )
        other_present = any(row.get("canonical_name") == "Other Ministries" for row in group)
        if total is None or not other_present:
            raise ValueError(
                f"{budget_year} {fiscal_year} {stage}: cannot reconcile ministry table; "
                "Total Expenditure and Other Ministries are both required"
            )
        ministry_sum = sum(
            amount
            for row in group
            if row.get("canonical_name") != "Total Expenditure"
            and (amount := _number(row.get("amount_cr"))) is not None
        )
        difference_pct = abs(ministry_sum - total) / abs(total) if total else 0.0
        result = Reconciliation(
            budget_year,
            fiscal_year,
            stage,
            ministry_sum,
            total,
            difference_pct,
            "pass" if difference_pct <= tolerance else "fail",
        )
        results.append(result)
        if result.status == "fail":
            raise ValueError(
                f"{budget_year} {fiscal_year} {stage}: ministries + Other differ from "
                f"Total Expenditure by {difference_pct:.3%} (limit {tolerance:.3%})"
            )
    return results


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            number = float(value)
        except ValueError:
            return None
        return number if number == number else None
    if isinstance(value, Real):
        number = float(value)
        return number if number == number else None
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "data" / "csv" / "budget_ministries.csv",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "reports" / "ministry_reconciliation.csv",
    )
    args = parser.parse_args()
    with args.input.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"No budget ministry rows in {args.input}")
    results = reconcile_ministry_rows(rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Reconciliation.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(result.__dict__ for result in results)
    print(f"reconciled {len(results)} budget/stage tables; report: {args.report}")


if __name__ == "__main__":
    main()
