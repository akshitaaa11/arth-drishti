from __future__ import annotations

from pathlib import Path

import pytest
from scripts.build_budget_csvs import legacy_d4_ministry_rows
from scripts.collect.download_budget_pdfs import candidate_urls
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    select,
)

from bsp.parsers.canonical import canonicalise_ministry
from bsp.parsers.expenditure_budget import (
    _prefer_transcribed_rows,
    _statement2_row,
    parse_expenditure_pdf,
    parse_transcription,
)
from bsp.parsers.load import load_budget_csvs
from bsp.parsers.prs import parse_pdf, split_row
from bsp.quality.reconcile import reconcile_ministry_rows

ROOT = Path(__file__).resolve().parents[1]

# Source PDFs are gitignored; tests that parse them only run where the PDFs are present.
requires_pdfs = pytest.mark.skipif(
    not (ROOT / "data" / "source_pdfs" / "Union_Budget_Analysis_-_2022-23.pdf").exists(),
    reason="source PDFs not available in this checkout",
)


def test_prs_parser_splits_value_columns_and_excludes_growth_percent() -> None:
    assert split_row("Defence  4,52,996 4,71,378 4,84,736 4,78,196 3%") == (
        "Defence",
        ["4,52,996", "4,71,378", "4,84,736", "4,78,196"],
    )


@requires_pdfs
def test_prs_pdf_rows_include_actual_page_and_source_metadata() -> None:
    source = ROOT / "data" / "source_pdfs" / "Union_Budget_Analysis_-_2021-22_0.pdf"
    rows = parse_pdf(source)
    ministry_rows = [row for row in rows if row["table_kind"] == "ministry"]
    assert len(ministry_rows) == 60
    assert {row["stage"] for row in ministry_rows} == {"Actual", "BE", "RE"}
    assert all(row["source_doc"] == source.name for row in ministry_rows)
    assert all(row["source_page"] for row in ministry_rows)
    assert all(row["source_url"] and row["fetched_at"] for row in ministry_rows)


@requires_pdfs
def test_prs_parser_omits_values_without_matching_header_columns() -> None:
    source = ROOT / "data" / "source_pdfs" / "Union_Budget_Analysis_-_2022-23.pdf"
    rows = parse_pdf(source)
    assert rows
    assert all(row["fiscal_year"] for row in rows)
    assert all(not str(row["stage"]).startswith("col") for row in rows)


def test_legacy_statement2_parser_splits_adjacent_decimal_columns() -> None:
    row = _statement2_row(
        "Rural Development 15501.18 18.08 15519.2613866.40 19.00 13885.40"
        "18334.00 19.87 18353.87",
        9,
    )
    assert row == (
        "Rural Development",
        [
            "15501.18",
            "18.08",
            "15519.26",
            "13866.40",
            "19.00",
            "13885.40",
            "18334.00",
            "19.87",
            "18353.87",
        ],
    )


def test_legacy_statement2_parser_reads_continuation_page_and_partial_rows() -> None:
    row = _statement2_row(
        "Financial Services# 1900.00 28469.00 30369.00 1542.00 21871.54 23413.54",
        9,
    )
    assert row == (
        "Financial Services#",
        ["1900.00", "28469.00", "30369.00", "1542.00", "21871.54", "23413.54"],
    )

    source = ROOT / "data" / "raw" / "budget_pdfs" / "expenditure_profile_2009-10.pdf"
    if not source.exists():
        pytest.skip("D4 source PDF not available in this checkout")
    rows = parse_expenditure_pdf(source)
    health_be = next(
        row
        for row in rows
        if row["department"] == "Health & Family Welfare"
        and row["stage"] == "BE"
        and row["fiscal_year"] == "2009-10"
    )
    assert health_be["total_cr"] == 21113.33
    financial_services = [
        row for row in rows if row["department"] == "Financial Services#"
    ]
    assert [(row["stage"], row["total_cr"]) for row in financial_services] == [
        ("Actual", 30369.0),
        ("RE", 23413.54),
    ]
    assert all(row["source_page"] == 2 for row in [health_be, *financial_services])


def test_pdf_rows_do_not_replace_years_with_verified_transcriptions() -> None:
    transcribed = [{"budget_year": "2024-25", "source_doc": "verified transcription"}]
    pdf_rows = [
        {"budget_year": "2024-25", "source_doc": "partial PDF extraction"},
        {"budget_year": "2005-06", "source_doc": "complete PDF extraction"},
    ]
    merged = _prefer_transcribed_rows(transcribed, pdf_rows)
    assert merged == [
        transcribed[0],
        {"budget_year": "2005-06", "source_doc": "complete PDF extraction"},
    ]


def test_ministry_canonicalisation_reads_aliases() -> None:
    assert canonicalise_ministry("Human Resource Development") == "Education"
    assert canonicalise_ministry("Ministry of Drinking Water and Sanitation") == "Jal Shakti"
    assert canonicalise_ministry("Agriculture & Cooperation") == "Agriculture and Farmers' Welfare"
    assert canonicalise_ministry("Telecommunications") == "Communications"
    assert canonicalise_ministry("Non-Conventional Energy Sources") == "New and Renewable Energy"
    assert canonicalise_ministry("Financial Services#") == "Finance - Financial Services"


def test_transcription_uses_its_recorded_source_url(tmp_path: Path) -> None:
    source = tmp_path / "eb_2026-27_A.txt"
    source.write_text(
        "# url: https://www.indiabudget.gov.in/doc/eb/vol1.pdf\n"
        "BE|2026-27|1|Education|10|2|12|5\n",
        encoding="utf-8",
    )
    assert parse_transcription(source)[0]["source_url"] == (
        "https://www.indiabudget.gov.in/doc/eb/vol1.pdf"
    )


def test_current_budget_pdf_candidate_uses_official_url() -> None:
    assert candidate_urls("2026-27")[-1] == "https://www.indiabudget.gov.in/doc/eb/vol1.pdf"


def test_legacy_d4_ministry_rows_build_canonical_sector_aggregates() -> None:
    source_rows = [
        {
            "budget_year": "2005-06",
            "fiscal_year": "2005-06",
            "stage": "BE",
            "ministry": name,
            "department": name,
            "total_cr": amount,
            "source_doc": "source.pdf",
            "source_page": "3",
            "source_url": "https://example.org/source.pdf",
            "fetched_at": "2026-10-23T00:00:00+00:00",
        }
        for name, amount in [
            ("Agriculture & Cooperation", 10),
            ("Agricultural Research and Education", 5),
            ("Power", 20),
            ("New and Renewable Energy", 3),
        ]
    ]
    result = legacy_d4_ministry_rows(source_rows)
    amounts = dict(zip(result.canonical_name, result.amount_cr))
    assert amounts["Agriculture and Farmers' Welfare"] == 15
    assert amounts["Power + MNRE"] == 23


def test_ministry_reconciliation_fails_without_other_or_when_over_tolerance() -> None:
    rows = [
        {
            "budget_year": "2024-25",
            "fiscal_year": "2024-25",
            "stage": "BE",
            "line_type": "ministry",
            "canonical_name": "Total Expenditure",
            "amount_cr": "100",
        },
        {
            "budget_year": "2024-25",
            "fiscal_year": "2024-25",
            "stage": "BE",
            "line_type": "ministry",
            "canonical_name": "Defence",
            "amount_cr": "99",
        },
        {
            "budget_year": "2024-25",
            "fiscal_year": "2024-25",
            "stage": "BE",
            "line_type": "ministry",
            "canonical_name": "Other Ministries",
            "amount_cr": "1",
        },
    ]
    assert reconcile_ministry_rows(rows)[0].status == "pass"
    rows[-1]["amount_cr"] = "2"
    with pytest.raises(ValueError, match="limit 0.500%"):
        reconcile_ministry_rows(rows)

    rows.pop()
    with pytest.raises(ValueError, match="Other Ministries"):
        reconcile_ministry_rows(rows)


def test_budget_csv_load_is_idempotent_and_logs_success(tmp_path: Path) -> None:
    database_path = tmp_path / "budget.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    engine = create_engine(database_url)
    metadata = MetaData()
    budget_lines = Table(
        "budget_lines",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("fiscal_year", String),
        Column("line_type", String),
        Column("line_name", String),
        Column("canonical_name", String),
        Column("stage", String),
        Column("amount_cr", Float),
        Column("capex_cr", Float),
        Column("revenue_cr", Float),
        Column("source_doc", String),
        Column("source_page", String),
        Column("source_url", String),
        Column("fetched_at", DateTime),
    )
    fetch_log = Table(
        "fetch_log",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("job", String),
        Column("started_at", DateTime),
        Column("finished_at", DateTime),
        Column("rows", Integer),
        Column("status", String),
        Column("error", String),
    )
    metadata.create_all(engine)
    engine.dispose()

    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    fixture = ROOT / "tests" / "fixtures" / "phase1" / "budget_ministries.csv"
    (csv_dir / fixture.name).write_bytes(fixture.read_bytes())

    assert load_budget_csvs(database_url, csv_dir) == 1
    assert load_budget_csvs(database_url, csv_dir) == 1

    engine = create_engine(database_url)
    with engine.connect() as connection:
        assert len(connection.execute(select(budget_lines)).all()) == 1
        logs = connection.execute(select(fetch_log.c.status, fetch_log.c.rows)).all()
    engine.dispose()
    assert logs == [("success", 1), ("success", 1)]
