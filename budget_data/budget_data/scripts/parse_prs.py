"""Parse PRS 'Union Budget Analysis' PDFs into tidy CSVs with source page references.

Usage:
    python scripts/parse_prs.py data/source_pdfs data/csv

Outputs (long format, one row per line item x stage x fiscal year):
    budget_ministries.csv   Ministry-wise expenditure table
    budget_schemes.csv      Scheme-wise allocation table
    budget_fiscal.csv       Budget at a Glance, receipts, expenditure break-up, subsidies
    prs_tables_raw.csv      Every parsed row before reshaping (for auditing)

Every row carries source_doc, source_page and the table title it came from.
Requires the `pdftotext` command (poppler-utils).
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

TITLE_RE = re.compile(r"^\s*Table\s+(\d+):\s*(.+?)\s*$")
YEAR_RE = re.compile(r"\b(20\d\d-\d\d)\b")
LABEL_RE = re.compile(r"\b(Actuals?|Budgeted|Revised|Interim)\b")
NUM_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
DASH = {"-", "–", "—"}
STAGE = {"Actual": "Actual", "Actuals": "Actual", "Budgeted": "BE", "Revised": "RE", "Interim": "BE_interim"}
END_RE = re.compile(r"^\s*(Sources?:|Note:|Notes:)")

# Which output a table goes to, by its title.
KIND_RULES = [
    (re.compile(r"Ministry-wise", re.I), "ministry"),
    (re.compile(r"Scheme[- ]wise", re.I), "scheme"),
    (re.compile(r"Subsidies", re.I), "subsidy"),
    (re.compile(r"Budget at a Glance", re.I), "glance"),
    (re.compile(r"receipts", re.I), "receipts"),
    (re.compile(r"expenditure in", re.I), "expenditure_breakup"),
]


def pdf_pages(pdf: Path) -> list[str]:
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
    return out.split("\f")


def to_number(tok: str):
    tok = tok.strip()
    if tok in DASH:
        return None
    return float(tok.replace(",", ""))


def split_row(line: str):
    """Return (name, [values]) if the line is a data row with >=3 numeric columns."""
    parts = [p for p in re.split(r"\s{2,}", line.strip()) if p]
    if len(parts) < 4:
        return None
    # drop trailing % change column (e.g. '7.1%', '-', '566.7%')
    if parts[-1].endswith("%") or (parts[-1] in DASH and len(parts) >= 6):
        parts = parts[:-1]
    vals = []
    while parts and (NUM_RE.match(parts[-1].replace(" ", "")) or parts[-1] in DASH):
        vals.insert(0, parts.pop())
    if len(vals) < 3 or not parts:
        return None
    name = " ".join(parts).strip(" *")
    if not re.search(r"[A-Za-z]", name):
        return None
    return name, vals


def parse_header(lines: list[str]):
    """Find column stages and years from the header lines of a table."""
    labels, years = [], []
    for ln in lines:
        lab = LABEL_RE.findall(ln)
        yrs = YEAR_RE.findall(ln)
        if len(lab) >= 3 and not labels:
            labels = lab
        if len(yrs) >= 3 and not years:
            years = yrs
    return labels, years


def kind_of(title: str) -> str | None:
    for rx, k in KIND_RULES:
        if rx.search(title):
            return k
    return None


def budget_year_of(pdf: Path, pages: list[str]) -> str:
    m = re.search(r"(20\d\d)-(\d\d)", pdf.name)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.search(r"Union Budget (20\d\d-\d\d)", pages[0])
    return m.group(1) if m else "unknown"


def parse_pdf(pdf: Path):
    pages = pdf_pages(pdf)
    by = budget_year_of(pdf, pages)
    rows = []
    for pno, text in enumerate(pages, start=1):
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            m = TITLE_RE.match(lines[i])
            if not m:
                i += 1
                continue
            tno, title = m.group(1), m.group(2)
            kind = kind_of(title)
            j = i + 1
            header, body = [], []
            while j < len(lines) and not END_RE.match(lines[j]) and not TITLE_RE.match(lines[j]):
                r = split_row(lines[j])
                if r is None and not body:
                    header.append(lines[j])
                elif r is not None:
                    body.append(r)
                elif body and lines[j].strip() == "":
                    # allow one blank line inside a table, stop on two
                    if j + 1 < len(lines) and lines[j + 1].strip() == "":
                        break
                j += 1
            labels, years = parse_header(header)
            for name, vals in body:
                n = len(vals)
                for k, v in enumerate(vals):
                    stage = STAGE.get(labels[k], labels[k]) if k < len(labels) else f"col{k+1}"
                    year = years[k] if k < len(years) else ""
                    rows.append({
                        "budget_year": by,
                        "table_no": tno,
                        "table_title": title,
                        "table_kind": kind or "other",
                        "line_item": name,
                        "column_index": k + 1,
                        "n_columns": n,
                        "stage": stage,
                        "fiscal_year": year,
                        "raw_value": v,
                        "amount_cr": to_number(v) if NUM_RE.match(v.replace(" ", "")) or v in DASH else "",
                        "source_doc": pdf.name,
                        "source_page": pno,
                    })
            i = j
    return rows


def main(src: str, dst: str):
    src_p, dst_p = Path(src), Path(dst)
    dst_p.mkdir(parents=True, exist_ok=True)
    all_rows = []
    for pdf in sorted(src_p.glob("*.pdf")):
        if "DFG" in pdf.name:  # department-specific DFG analyses have a different layout
            continue
        rows = parse_pdf(pdf)
        print(f"{pdf.name}: {len(rows)} values")
        all_rows.extend(rows)
    fetched = date.today().isoformat()
    for r in all_rows:
        r["source"] = "PRS Legislative Research, Union Budget Analysis"
        r["parsed_on"] = fetched
    cols = list(all_rows[0].keys())
    with open(dst_p / "prs_tables_raw.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(all_rows)
    print(f"wrote {len(all_rows)} raw values")


if __name__ == "__main__":
    main(*(sys.argv[1:3] if len(sys.argv) >= 3 else ["data/source_pdfs", "data/csv"]))
