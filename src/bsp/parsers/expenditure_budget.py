"""Normalize Expenditure Profile Statement 3 source rows into budget_demands.csv."""

from __future__ import annotations

import argparse
import csv
import math
import re
from datetime import UTC, datetime
from numbers import Real
from pathlib import Path
from typing import TypedDict

import pandas as pd
import pdfplumber

from bsp.parsers.canonical import canonicalise_ministry

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEPARTMENT_CSV = PROJECT_ROOT / "data" / "csv" / "budget_departments.csv"
SOURCE_URL_PREFIX = "https://www.indiabudget.gov.in/budget_archive/ub"
OUTPUT_COLUMNS = [
    "budget_year",
    "fiscal_year",
    "demand_no",
    "ministry",
    "department",
    "stage",
    "revenue_cr",
    "capital_cr",
    "total_cr",
    "source_doc",
    "source_page",
    "source_url",
    "fetched_at",
    "extraction_method",
    "quality_note",
]


class _Statement2Values(TypedDict):
    totals: list[str]
    revenue: list[str] | None
    capital: list[str] | None


STAGE_YEAR_RE = re.compile(
    r"\b(Actuals?|Budget(?:\s*Estimates?)?|Revised(?:\s*Estimates?)?|BE|RE)\s*"
    r"(20\d{2})\s*[-–]\s*(20)?(\d{2})\b",
    re.IGNORECASE,
)
VALUE_RE = re.compile(r"(?:-?[\d,]+(?:\.\d+)?|\.\.\.|[-–—])")
SUBLINE_RE = re.compile(
    r"^(?:Central Sector Schemes|Centrally Sponsored Schemes|Establishment Expenditure|"
    r"Other Central Sector Expenditure|Transfer to States|Grants-in-Aid|of which)\b",
    re.IGNORECASE,
)


def parse_transcription(path: str | Path) -> list[dict[str, object]]:
    source = Path(path)
    budget_year = source.stem.removeprefix("eb_").removesuffix("_A").removesuffix("_B")
    source_url = _source_url(budget_year)
    fetched_at = datetime.now(UTC).isoformat()
    rows: list[dict[str, object]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            url = re.search(r"\burl:\s*(\S+)", line, re.IGNORECASE)
            if url:
                source_url = url.group(1)
            continue
        fields = line.split("|")
        if len(fields) != 8:
            raise ValueError(f"{source.name}: expected 8 pipe-separated fields, got {len(fields)}")
        stage, fiscal_year, demand_no, department, revenue, capital, total, page = fields
        rows.append(
            {
                "budget_year": budget_year,
                "fiscal_year": fiscal_year.strip(),
                "demand_no": demand_no.strip(" ."),
                "ministry": "",
                "department": department.strip(),
                "stage": stage.strip(),
                "revenue_cr": _optional_number(revenue),
                "capital_cr": _optional_number(capital),
                "total_cr": _optional_number(total),
                "source_doc": f"Expenditure Profile {budget_year}, Statement 3",
                "source_page": page.strip(),
                "source_url": source_url,
                "fetched_at": fetched_at,
                "extraction_method": "provided web transcription",
            }
        )
    return rows


def parse_expenditure_pdf(path: str | Path) -> list[dict[str, object]]:
    """Extract sourced ministry/department totals from Expenditure Budget tables."""
    pdf_path = Path(path)
    budget_year = re.search(r"(20\d{2}-\d{2})", pdf_path.name)
    if not budget_year:
        raise ValueError(f"Cannot determine budget year from {pdf_path.name}")
    fetched_at = datetime.now(UTC).isoformat()
    source_url = _source_url(budget_year.group(1))
    rows: list[dict[str, object]] = []
    active_statement: str | None = None
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(layout=False) or ""
            statement = re.search(r"\bSTATEMENT\s*(\d+)[A-Z]?\b", text, re.IGNORECASE)
            if statement:
                statement_number = statement.group(1)
                if statement_number == "3" and re.search(
                    r"expenditure of ministries and departments", text, re.IGNORECASE
                ):
                    active_statement = "3"
                elif statement_number == "2" and re.search(
                    r"total expenditure of ministries\s*/?\s*departments",
                    text,
                    re.IGNORECASE,
                ):
                    active_statement = "2"
                elif statement_number == active_statement:
                    pass
                else:
                    active_statement = None
            has_ministry_header = bool(re.search(r"MINISTRY\s*/\s*DEPARTMENT", text, re.IGNORECASE))
            if active_statement == "3" and has_ministry_header and re.search(
                r"Revenue\s+Capital\s+Total", text, re.IGNORECASE
            ):
                rows.extend(
                    _parse_statement3_page(
                        text, budget_year.group(1), pdf_path.name, page_number, source_url, fetched_at
                    )
                )
            elif (
                active_statement == "2"
                and has_ministry_header
                and re.search(r"Plan\s+Non-Plan\s+Total", text, re.IGNORECASE)
            ):
                rows.extend(
                    _parse_statement2_page(
                        text, budget_year.group(1), pdf_path.name, page_number, source_url, fetched_at
                    )
                )
    if not rows:
        raise ValueError(f"{pdf_path.name} has no supported Statement 3 ministry table")
    return rows


def _source_url(fiscal_year: str) -> str:
    manifest = PROJECT_ROOT / "reports" / "budget_pdf_downloads.csv"
    if manifest.exists():
        with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
            for record in csv.DictReader(handle):
                if record.get("fiscal_year") == fiscal_year and record.get("source_url"):
                    return record["source_url"]
    return f"{SOURCE_URL_PREFIX}{fiscal_year}/eb/vol1.pdf"


def _stage_years(text: str) -> list[tuple[str, str]]:
    stages = []
    for label, start, century, end in STAGE_YEAR_RE.findall(text):
        stage = label.lower()
        if stage.startswith("actual"):
            normalized_stage = "Actual"
        elif stage.startswith("revised") or stage == "re":
            normalized_stage = "RE"
        else:
            normalized_stage = "BE"
        normalized_year = f"{start}-{end[-2:]}"
        pair = (normalized_stage, normalized_year)
        if pair not in stages:
            stages.append(pair)
        if len(stages) == 4:
            break
    return stages


def _parse_statement3_page(
    text: str,
    budget_year: str,
    source_doc: str,
    source_page: int,
    source_url: str,
    fetched_at: str,
) -> list[dict[str, object]]:
    stages = _stage_years(text)
    if len(stages) != 4:
        raise ValueError(
            f"{source_doc} page {source_page}: expected four Statement 3 stage/year columns, "
            f"found {stages}"
        )
    rows = []
    for line in text.splitlines():
        parsed = _statement3_row(line)
        if parsed is None:
            continue
        demand_no, department, values = parsed
        if SUBLINE_RE.match(department):
            continue
        for index, (stage, fiscal_year) in enumerate(stages):
            revenue, capital, total = (
                _optional_number(value) for value in values[index * 3 : index * 3 + 3]
            )
            if revenue is None and capital is None and total is None:
                continue
            if revenue is not None and capital is not None and total is not None:
                if abs(revenue + capital - total) > 0.02:
                    raise ValueError(
                        f"{source_doc} page {source_page}: revenue + capital does not match "
                        f"total for {department}, {stage} {fiscal_year}"
                    )
            rows.append(
                _demand_row(
                    budget_year,
                    fiscal_year,
                    demand_no,
                    department,
                    stage,
                    revenue,
                    capital,
                    total,
                    source_doc,
                    source_page,
                    source_url,
                    fetched_at,
                    "pdfplumber Statement 3",
                )
            )
    return rows


def _parse_statement2_page(
    text: str,
    budget_year: str,
    source_doc: str,
    source_page: int,
    source_url: str,
    fetched_at: str,
) -> list[dict[str, object]]:
    if not re.search(r"statement\s+2\b", text, re.IGNORECASE):
        return []
    stages = _stage_years(text)
    if len(stages) not in {3, 4}:
        raise ValueError(
            f"{source_doc} page {source_page}: unsupported Statement 2 stage/year columns {stages}"
        )
    grouped: dict[str, _Statement2Values] = {}
    active_name: str | None = None
    for line in text.splitlines():
        parsed = _statement2_row(line, len(stages) * 3)
        if parsed is None:
            continue
        name, values = parsed
        if name.startswith(("I.", "II.", "III.", "IV.")) or name.lower().startswith(
            "total expenditure"
        ):
            active_name = None
            continue
        name = re.sub(r"^[a-z]{1,2}\.\s+", "", name).strip()
        if name.lower() == "revenue":
            if active_name:
                grouped[active_name]["revenue"] = values
            continue
        if name.lower() == "capital":
            if active_name:
                grouped[active_name]["capital"] = values
            continue
        active_name = name
        grouped[name] = {"totals": values, "revenue": None, "capital": None}

    rows = []
    for name, values_by_kind in grouped.items():
        totals = values_by_kind["totals"]
        revenue_values = values_by_kind["revenue"]
        capital_values = values_by_kind["capital"]
        for index, (stage, fiscal_year) in enumerate(stages):
            value_index = index * 3 + 2
            if value_index >= len(totals):
                continue
            total = _optional_number(totals[value_index])
            revenue_token = (
                revenue_values[value_index]
                if revenue_values is not None and value_index < len(revenue_values)
                else None
            )
            capital_token = (
                capital_values[value_index]
                if capital_values is not None and value_index < len(capital_values)
                else None
            )
            revenue = _optional_number(revenue_token)
            capital = _optional_number(capital_token)
            if revenue is not None and capital is not None and total is not None:
                if abs(revenue + capital - total) > 0.02:
                    revenue = None
                    capital = None
                    quality_note = (
                        f"Statement 2 Revenue + Capital ({revenue_token} + "
                        f"{capital_token}) does not match reported total "
                        f"{totals[index * 3 + 2]}; components omitted"
                    )
                else:
                    quality_note = ""
            else:
                quality_note = ""
            rows.append(
                _demand_row(
                    budget_year,
                    fiscal_year,
                    "",
                    name,
                    stage,
                    revenue,
                    capital,
                    total,
                    source_doc,
                    source_page,
                    source_url,
                    fetched_at,
                    "pdfplumber Statement 2; Plan/Non-Plan totals",
                    quality_note,
                )
            )
    return rows


def _demand_row(
    budget_year: str,
    fiscal_year: str,
    demand_no: str,
    department: str,
    stage: str,
    revenue: float | None,
    capital: float | None,
    total: float | None,
    source_doc: str,
    source_page: int,
    source_url: str,
    fetched_at: str,
    extraction_method: str,
    quality_note: str = "",
) -> dict[str, object]:
    return {
        "budget_year": budget_year,
        "fiscal_year": fiscal_year,
        "demand_no": demand_no,
        "ministry": canonicalise_ministry(department),
        "department": department,
        "stage": stage,
        "revenue_cr": revenue,
        "capital_cr": capital,
        "total_cr": total,
        "source_doc": source_doc,
        "source_page": source_page,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "extraction_method": extraction_method,
        "quality_note": quality_note,
    }


def _statement3_row(line: str) -> tuple[str, str, list[str]] | None:
    parts = line.strip().split()
    if len(parts) < 13 or not parts[0].rstrip(".").isdigit():
        return None
    values = parts[-12:]
    if not all(VALUE_RE.fullmatch(value) for value in values):
        return None
    department = " ".join(parts[1:-12]).strip()
    if not department:
        return None
    return parts[0].rstrip("."), department, values


def _statement2_row(line: str, value_count: int) -> tuple[str, list[str]] | None:
    parts = line.strip().split()
    parts = [
        part
        for token in parts
        for part in re.split(r"(?<=\.\d{2})(?=\d)", token)
    ]
    value_start = len(parts)
    while value_start > 0 and VALUE_RE.fullmatch(parts[value_start - 1]):
        value_start -= 1
    actual_value_count = min(value_count, len(parts) - value_start)
    if actual_value_count < 3:
        return None
    values = parts[-actual_value_count:]
    if not all(VALUE_RE.fullmatch(value) for value in values):
        return None
    name = " ".join(parts[:-actual_value_count]).strip()
    return (name, values) if name else None


def _text(value: object) -> str:
    if value is None or (isinstance(value, Real) and math.isnan(value)):
        return ""
    return str(value)


def _optional_number(value: object) -> float | None:
    if value is None or (isinstance(value, Real) and math.isnan(value)):
        return None
    if not isinstance(value, (str, Real)):
        return None
    stripped = str(value).strip()
    if stripped in {"", "-", "..."}:
        return None
    return float(stripped.replace(",", ""))


def build_budget_demands(
    source_path: str | Path = DEPARTMENT_CSV,
    output_path: str | Path | None = None,
) -> list[dict[str, object]]:
    source = Path(source_path)
    if source.is_file() and source.suffix.lower() == ".csv":
        frame = pd.read_csv(source, dtype={"demand_no": str, "source_page": str})
        rows: list[dict[str, object]] = []
        fetched_at = datetime.now(UTC).isoformat()
        for record in frame.to_dict("records"):
            ministry = _text(record.get("ministry"))
            rows.append(
                {
                    "budget_year": str(record["budget_year"]),
                    "fiscal_year": str(record["fiscal_year"]),
                    "demand_no": _text(record.get("demand_no")),
                    "ministry": canonicalise_ministry(str(ministry)),
                    "department": _text(record.get("department")),
                    "stage": str(record["stage"]),
                    "revenue_cr": _optional_number(record.get("revenue_cr")),
                    "capital_cr": _optional_number(record.get("capital_cr")),
                    "total_cr": _optional_number(record.get("total_cr")),
                    "source_doc": _text(record.get("source_doc")),
                    "source_page": _text(record.get("source_page")),
                    "source_url": _text(record.get("source_url")),
                    "fetched_at": _text(record.get("fetched_at")) or fetched_at,
                    "extraction_method": _text(record.get("extraction_method")),
                }
            )
    else:
        rows = []
        for transcription in sorted(source.glob("eb_*.txt")):
            rows.extend(parse_transcription(transcription))
        if not rows:
            raise ValueError(f"No Statement 3 source files found in {source}")
    pdf_dir = PROJECT_ROOT / "data" / "raw" / "budget_pdfs"
    pdf_rows: list[dict[str, object]] = []
    transcribed_years = {str(row["budget_year"]) for row in rows}
    for pdf_path in sorted(pdf_dir.glob("expenditure_profile_*.pdf")):
        year = re.search(r"(20\d{2}-\d{2})", pdf_path.name)
        if year and year.group(1) in transcribed_years:
            continue
        parsed = parse_expenditure_pdf(pdf_path)
        pdf_rows.extend(parsed)
    rows = _prefer_transcribed_rows(rows, pdf_rows)
    for row in rows:
        row["ministry"] = canonicalise_ministry(str(row["ministry"]))
    if output_path:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
    return rows


def _prefer_transcribed_rows(
    transcribed_rows: list[dict[str, object]],
    pdf_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep complete verified transcriptions when a PDF layout yields only partial tables."""
    transcribed_years = {str(row["budget_year"]) for row in transcribed_rows}
    return [
        *transcribed_rows,
        *(row for row in pdf_rows if str(row["budget_year"]) not in transcribed_years),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEPARTMENT_CSV)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "csv" / "budget_demands.csv",
    )
    args = parser.parse_args()
    rows = build_budget_demands(args.source, args.output)
    print(f"wrote {len(rows)} sourced rows to {args.output}")


if __name__ == "__main__":
    main()
