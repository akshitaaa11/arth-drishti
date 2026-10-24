"""Download official Expenditure Profile PDFs, recording unavailable source years."""

from __future__ import annotations

import argparse
import csv
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data" / "raw" / "budget_pdfs"
MANIFEST = ROOT / "reports" / "budget_pdf_downloads.csv"
HEADERS = {"User-Agent": "ArthDrishti research-data downloader/1.0"}


def fiscal_years(start_year: int, end_year: int) -> list[str]:
    return [f"{year}-{(year + 1) % 100:02d}" for year in range(start_year, end_year + 1)]


def candidate_urls(fiscal_year: str) -> list[str]:
    urls = [
        f"https://www.indiabudget.gov.in/budget_archive/ub{fiscal_year}/eb/vol1.pdf",
        f"https://www.indiabudget.gov.in/budget{fiscal_year}/doc/eb/vol1.pdf",
        f"https://www.indiabudget.gov.in/budget_archive/ub{fiscal_year}/eb/stat02.pdf",
    ]
    if fiscal_year == "2026-27":
        urls.append("https://www.indiabudget.gov.in/doc/eb/vol1.pdf")
    return urls


def cached_source_url(fiscal_year: str) -> str:
    start = int(fiscal_year[:4])
    urls = candidate_urls(fiscal_year)
    if fiscal_year == "2026-27":
        return urls[-1]
    if start <= 2014:
        return urls[-1]
    if start <= 2019:
        return urls[0]
    return urls[1]


def download_year(
    session: requests.Session,
    fiscal_year: str,
    output_dir: Path,
    *,
    timeout: int = 30,
    force: bool = False,
) -> dict[str, str]:
    destination = output_dir / f"expenditure_profile_{fiscal_year}.pdf"
    if not force and destination.exists() and destination.stat().st_size > 1024:
        return {
            "fiscal_year": fiscal_year,
            "status": "cached",
            "source_url": cached_source_url(fiscal_year),
            "filename": destination.name,
            "error": "",
        }
    errors: list[str] = []
    for url in candidate_urls(fiscal_year):
        try:
            response = session.get(url, timeout=timeout)
            if response.status_code == 404:
                errors.append("404")
                continue
            response.raise_for_status()
            if not response.content.startswith(b"%PDF-"):
                errors.append(f"non-PDF response ({response.status_code})")
                continue
            destination.write_bytes(response.content)
            return {
                "fiscal_year": fiscal_year,
                "status": "downloaded",
                "source_url": url,
                "filename": destination.name,
                "error": "",
            }
        except requests.RequestException as exc:
            errors.append(f"{url}: {exc}")
        time.sleep(0.2)
    return {
        "fiscal_year": fiscal_year,
        "status": "unavailable",
        "source_url": candidate_urls(fiscal_year)[-1]
        if fiscal_year == "2026-27"
        else candidate_urls(fiscal_year)[0],
        "filename": "",
        "error": "; ".join(errors),
    }


def download_all(
    start_year: int,
    end_year: int,
    output_dir: str | Path = DEFAULT_OUTPUT,
    *,
    force: bool = False,
) -> list[dict[str, str]]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    records = [
        download_year(session, year, destination, force=force)
        for year in fiscal_years(start_year, end_year)
    ]
    previous: dict[str, dict[str, str]] = {}
    if MANIFEST.exists():
        with MANIFEST.open("r", encoding="utf-8-sig", newline="") as handle:
            previous = {row["fiscal_year"]: row for row in csv.DictReader(handle)}
    merged = {**previous, **{record["fiscal_year"]: record for record in records}}
    manifest = MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["fiscal_year", "status", "source_url", "filename", "error"],
        )
        writer.writeheader()
        writer.writerows(merged[year] for year in sorted(merged))
    for record in records:
        print(f"{record['fiscal_year']}: {record['status']}")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2005)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true", help="redownload even when a PDF already exists")
    args = parser.parse_args()
    if args.start_year < 2000 or args.end_year < args.start_year:
        parser.error("years must be ordered and start no earlier than 2000")
    started_at = datetime.now(UTC)
    records = download_all(args.start_year, args.end_year, args.output_dir, force=args.force)
    failures = sum(record["status"] == "unavailable" for record in records)
    print(f"downloaded/cached {len(records) - failures}/{len(records)} files since {started_at.isoformat()}")
    if failures:
        print(f"{failures} years unavailable; see {MANIFEST}")


if __name__ == "__main__":
    main()
