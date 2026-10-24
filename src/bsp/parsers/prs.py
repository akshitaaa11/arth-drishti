"""Extract PRS Union Budget Analysis tables with PDF page provenance."""

from __future__ import annotations

import argparse
import csv
import re
from datetime import UTC, datetime
from pathlib import Path

import pdfplumber

TITLE_RE = re.compile(r"^\s*Table\s*(\d+)\s*:\s*(.+?)\s*$", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(20\d\d-\d\d)\b")
LABEL_RE = re.compile(r"\b(Actuals?|Budgeted|Revised|Interim|BE|RE)\b", re.IGNORECASE)
NUM_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
NUM_TOKEN_RE = re.compile(r"(?<![\w])[-+]?[\d,]+(?:\.\d+)?(?![\w])|(?<![\w])[–—-](?![\w])")
DASHES = {"-", "–", "—"}
STAGE = {
    "actual": "Actual",
    "actuals": "Actual",
    "budgeted": "BE",
    "be": "BE",
    "re": "RE",
    "revised": "RE",
    "interim": "BE_interim",
}
END_RE = re.compile(r"^\s*(Sources?:|Note:|Notes:)", re.IGNORECASE)
KIND_RULES = (
    (re.compile(r"Ministry-wise", re.IGNORECASE), "ministry"),
    (re.compile(r"Scheme[- ]wise", re.IGNORECASE), "scheme"),
    (re.compile(r"Subsidies", re.IGNORECASE), "subsidy"),
    (re.compile(r"Budget at a Glance", re.IGNORECASE), "glance"),
    (re.compile(r"receipts", re.IGNORECASE), "receipts"),
    (re.compile(r"expenditure in", re.IGNORECASE), "expenditure_breakup"),
)
RAW_COLUMNS = [
    "budget_year",
    "table_no",
    "table_title",
    "table_kind",
    "line_item",
    "column_index",
    "n_columns",
    "stage",
    "fiscal_year",
    "raw_value",
    "amount_cr",
    "source_doc",
    "source_page",
    "source_url",
    "fetched_at",
]
PRS_URL = "https://prsindia.org/budgets/parliament"


def split_row(line: str) -> tuple[str, list[str]] | None:
    if YEAR_RE.search(line):
        return None
    clean_line = re.sub(r"\s+-?[\d.]+%\s*$", "", line.strip())
    tokens = list(NUM_TOKEN_RE.finditer(clean_line))
    if len(tokens) < 3:
        return None
    first_value_index = len(tokens) - 1
    while (
        first_value_index > 0
        and clean_line[tokens[first_value_index - 1].end() : tokens[first_value_index].start()].strip()
        == ""
    ):
        first_value_index -= 1
    first_value = tokens[first_value_index]
    if clean_line[tokens[-1].end() :].strip():
        return None
    name = clean_line[: first_value.start()].strip(" *")
    values = [token.group() for token in tokens[first_value_index:]]
    if len(values) < 3 or not name:
        return None
    if not re.search(r"[A-Za-z]", name):
        return None
    return name, values


def parse_header(lines: list[str]) -> tuple[list[str], list[str]]:
    labels: list[str] = []
    years: list[str] = []
    for line in lines:
        before_change = re.split(r"\bchange\b", line, maxsplit=1, flags=re.IGNORECASE)[0]
        found_labels = LABEL_RE.findall(before_change)
        if len(found_labels) >= 3:
            labels = found_labels[:4]
            break
    year_lines = []
    for line in lines:
        found_years = YEAR_RE.findall(line)
        if found_years:
            year_lines.append((line.strip(), found_years))
    row_years = next(
        (
            found
            for line, found in year_lines
            if re.match(r"20\d{2}-\d{2}", line) and len(found) >= 3
        ),
        None,
    )
    if row_years is None and year_lines:
        row_years = max((found for _, found in year_lines), key=len)
    if row_years:
        years = row_years[:4]
    return labels, years


def budget_year_of(pdf_path: Path, first_page: str) -> str:
    match = re.search(r"(20\d\d)-(\d\d)", pdf_path.name)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    match = re.search(r"Union Budget (20\d\d-\d\d)", first_page)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot determine budget year from {pdf_path.name}")


def parse_pdf(pdf_path: str | Path, *, source_url: str = PRS_URL) -> list[dict[str, object]]:
    path = Path(pdf_path)
    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text(layout=True) or "" for page in pdf.pages]
    if not pages or not any(pages):
        raise ValueError(f"No extractable text in {path.name}; OCR is required")

    budget_year = budget_year_of(path, pages[0])
    fetched_at = datetime.now(UTC).isoformat()
    rows: list[dict[str, object]] = []
    for page_number, text in enumerate(pages, start=1):
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            match = TITLE_RE.match(lines[i])
            if not match:
                i += 1
                continue
            table_no, title = match.groups()
            table_kind = next((kind for pattern, kind in KIND_RULES if pattern.search(title)), "other")
            header: list[str] = []
            body: list[tuple[str, list[str]]] = []
            j = i + 1
            while j < len(lines) and not END_RE.match(lines[j]) and not TITLE_RE.match(lines[j]):
                parsed = split_row(lines[j])
                if parsed is None and not body:
                    header.append(lines[j])
                elif parsed is not None:
                    body.append(parsed)
                elif body and not lines[j].strip():
                    if j + 1 < len(lines) and not lines[j + 1].strip():
                        break
                j += 1

            labels, years = parse_header(header)
            column_count = min(len(labels), len(years))
            for name, values in body:
                for column_index, value in enumerate(values):
                    if column_index >= column_count:
                        continue
                    label = labels[column_index] if column_index < len(labels) else f"col{column_index + 1}"
                    fiscal_year = years[column_index] if column_index < len(years) else ""
                    numeric_value: float | str = float(value.replace(",", "")) if NUM_RE.fullmatch(value) else ""
                    if value in DASHES:
                        numeric_value = ""
                    rows.append(
                        {
                            "budget_year": budget_year,
                            "table_no": table_no,
                            "table_title": title,
                            "table_kind": table_kind,
                            "line_item": name,
                            "column_index": column_index + 1,
                            "n_columns": len(values),
                            "stage": STAGE.get(label.lower(), label),
                            "fiscal_year": fiscal_year,
                            "raw_value": value,
                            "amount_cr": numeric_value,
                            "source_doc": path.name,
                            "source_page": page_number,
                            "source_url": source_url,
                            "fetched_at": fetched_at,
                        }
                    )
            i = max(j, i + 1)
    if not rows:
        raise ValueError(f"No budget tables found in {path.name}")
    return rows


def parse_directory(source_dir: str | Path, output_dir: str | Path) -> int:
    source = Path(source_dir)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for pdf_path in sorted(source.glob("*.pdf")):
        if "DFG" in pdf_path.name:
            continue
        parsed = parse_pdf(pdf_path)
        print(f"{pdf_path.name}: {len(parsed)} values")
        rows.extend(parsed)
    if not rows:
        raise ValueError(f"No PRS budget tables found in {source}")
    with (output / "prs_tables_raw.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", nargs="?", default="data/source_pdfs")
    parser.add_argument("output_dir", nargs="?", default="data/csv")
    args = parser.parse_args()
    count = parse_directory(args.source_dir, args.output_dir)
    print(f"wrote {count} source-backed PRS values")


if __name__ == "__main__":
    main()
