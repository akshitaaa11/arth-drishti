"""Nifty 500 press-release parser: the seven real releases, wording variants and the interval builder."""

from __future__ import annotations

from datetime import date
from functools import cache
from pathlib import Path

import pandas as pd
import pytest
from scripts.collect import nifty500_history as n500
from scripts.collect.nifty500_history import (
    build_intervals,
    is_nifty_500_heading,
    parse_effective_date,
    parse_release_text,
    read_release,
)

from bsp.features.universe import Universe
from bsp.quality.leakage import LeakageError, validate_index_membership

FIXTURES = Path(__file__).parent / "fixtures" / "nifty500_press_releases"

# Exact Nifty 500 changes printed in each real release (read from the PDFs, in the printed order).
EXPECTED: dict[str, tuple[date, list[str], list[str]]] = {
    "2015-12-14": (date(2015, 12, 14), ["FRL", "MANDHANA"], ["ARVIND", "GAYAPROJ"]),
    "2017-03-31": (
        date(2017, 3, 31),
        ["ALOKTEXT", "BRFL", "BRIGADE", "DYNAMATECH", "FLFL", "INGERRAND", "IPAPPM", "JPPOWER", "JPINFRATEC", "JSWHL",
         "KSBPUMPS", "LAOPALA", "LITL", "LINDEINDIA", "MAHLIFE", "MAYURUNIQ", "SEQUENT", "SHOPERSTOP", "SIMPLEXINF",
         "SINTEX", "SITINET", "SBBJ", "MYSOREBANK", "SBT", "SUPRAJIT"],
        ["DBL", "ENDURANCE", "FMGOETZE", "FRETAIL", "GHCL", "GNFC", "GUJALKALI", "ICICIPRULI", "KNRCON", "LTI", "LTTS",
         "MAXINDIA", "MGL", "MINDACORP", "MINDAIND", "NAVNETEDUL", "NBVENTURES", "PARAGMILK", "QUESS", "RATNAMANI",
         "SHILPI", "STRTECH", "SUDARSCHEM", "TATAINVEST", "THYROCARE"],
    ),
    "2019-06-28": (date(2019, 6, 28), ["GUJFLUORO", "MONSANTO"], ["CHALET", "DALBHARAT"]),
    "2021-04-29": (date(2021, 4, 29), ["GHCL", "TATASTLBSL"], ["BURGERKING", "INFIBEAM"]),
    "2022-08-08": (date(2022, 8, 8), ["NMDC", "PEL", "SHRIRAMCIT"], ["CAMPUS", "DELHIVERY", "LICI"]),
    "2025-09-23": (date(2025, 9, 23), ["PEL"], ["RELINFRA"]),
    "2025-12-31": (date(2025, 12, 31), ["SKFINDIA"], ["JSWCEMENT"]),
}


@cache
def _text(name: str) -> str:
    return read_release(FIXTURES / f"{name}.pdf")  # PDF text extraction is slow; do it once per file


def _parse(name: str):
    return parse_release_text(_text(name), date.fromisoformat(name), source=f"{name}.pdf")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_real_release_gives_exact_nifty_500_symbols_and_effective_date(name: str) -> None:
    effective, excluded, included = EXPECTED[name]
    change = _parse(name)
    assert change is not None
    assert change.effective == effective
    assert [s for _, s in change.excluded] == excluded
    assert [s for _, s in change.included] == included


def test_all_seven_fixtures_are_present_and_covered() -> None:
    assert sorted(p.stem for p in FIXTURES.glob("*.pdf")) == sorted(EXPECTED)


def test_other_index_sections_of_the_same_release_are_not_counted() -> None:
    change = _parse("2025-12-31")
    symbols = {s for _, s in change.excluded + change.included}
    # Nifty Smallcap 250 / MNC / Multicap India Manufacturing / FPI 150 / strategy indices all list other names
    assert symbols == {"SKFINDIA", "JSWCEMENT"}
    sept = _parse("2025-09-23")
    # RELINFRA is also *excluded* from Nifty Microcap 250 "on account of inclusion in Nifty 500": not a Nifty 500 exclusion
    assert [s for _, s in sept.excluded] == ["PEL"]
    assert "KITEX" not in {s for _, s in sept.included}


def test_effective_date_comes_from_the_first_effective_from_sentence() -> None:
    text = "These changes shall become effective from\nDecember 31, 2025 (close of December 30, 2025).\nlater: effective from September 30, 2025"
    assert parse_effective_date(text) == date(2025, 12, 31)
    assert parse_effective_date("nothing here") is None


def test_filed_date_that_disagrees_with_the_text_is_an_error() -> None:
    text = "effective from March 31, 2017\n1) NIFTY 500 Index\nThe following company is being excluded:\n1 A Ltd. AAA\n"
    with pytest.raises(ValueError, match="filed as"):
        parse_release_text(text, date(2017, 4, 1), source="x")


# ---------------------------------------------------------------- wording variants (hand-made text)
@pytest.mark.parametrize("heading,expected", [
    ("Nifty 500", True), ("NIFTY 500", True), ("NIFTY 500 Index", True), ("Nifty 500 Index:", True),
    ("Nifty500", True), ("Nifty500 Equal Weight", False), ("Nifty500 Value 50", False), ("Nifty 50", False),
    ("Nifty Smallcap 250", False), ("Nifty Midcap 150", False), ("Nifty 500 Multicap 50:25:25", False),
])
def test_heading_recognition(heading: str, expected: bool) -> None:
    assert is_nifty_500_heading(heading) is expected


VARIANT = """effective from June 1, 2020
A. Replacements on account of review:
1) NIFTY 500 Index
The following scrips are being excluded:
Sr. No. Company Name Symbol
1 Old One Ltd. OLDONE
2 Old Two Ltd. OLD-TWO
Sr.
Company Name Symbol
No.
3 Old M&M Ltd. M&M
The following company is being included:
Sr. No. Company Name Symbol
1 New One Ltd.* NEWONE
The above replacements will also be applicable to Nifty500 Equal Weight and Nifty500 Multicap indices.
2) Nifty500 Equal Weight
The following companies are being excluded:
Sr. No. Company Name Symbol
1 Wrong Ltd. WRONG
B. Replacements on account of quarterly review:
The following companies are being excluded:
Sr. No. Company Name Symbol
1 Also Wrong Ltd. ALSOWRONG
"""


def test_scrips_wording_page_break_header_and_non_nifty_500_headings() -> None:
    change = parse_release_text(VARIANT, source="variant")
    assert change is not None and change.effective == date(2020, 6, 1)
    assert [s for _, s in change.excluded] == ["OLDONE", "OLD-TWO", "M&M"]
    assert [(n, s) for n, s in change.included] == [("New One Ltd.", "NEWONE")]


def test_singular_and_plural_company_wording_and_no_inclusion_line() -> None:
    text = ("effective from June 1, 2020\n1) Nifty 500\nThe following company is being excluded:\n1 A Ltd. AAA\n"
            "No inclusion is being made in the index.\n2) Nifty 100\n")
    change = parse_release_text(text)
    assert change is not None and [s for _, s in change.excluded] == ["AAA"] and change.included == []


def test_release_without_a_nifty_500_section_returns_none() -> None:
    text = "effective from June 1, 2020\n1) Nifty 50\nThe following company is being excluded:\n1 A Ltd. AAA\n"
    assert parse_release_text(text) is None


def test_skipped_serial_number_fails_loudly_instead_of_losing_a_row() -> None:
    text = ("effective from June 1, 2020\n1) Nifty 500\nThe following companies are being excluded:\n"
            "1 A Ltd. AAA\n3 C Ltd. CCC\n")
    with pytest.raises(ValueError, match="row was lost"):
        parse_release_text(text)


def test_unreadable_table_row_fails_loudly() -> None:
    text = "effective from June 1, 2020\n1) Nifty 500\nThe following companies are being excluded:\n1 company without symbol column ???\n"
    with pytest.raises(ValueError, match="cannot read table row"):
        parse_release_text(text)


# ---------------------------------------------------------------- interval builder on the real 2025 releases
def test_reverse_walk_over_real_releases_builds_point_in_time_membership() -> None:
    changes = [_parse("2025-09-23"), _parse("2025-12-31")]
    current = {"JSWCEMENT", "RELINFRA", "TCS"}  # as of today: SKFINDIA and PEL are gone, the newcomers are in
    intervals, problems = build_intervals(current, changes, {}, "current-list-url", "2026-01-01T00:00:00+00:00")
    assert problems == []
    rows = {(r.symbol, str(r.effective_from.date() if hasattr(r.effective_from, "date") else r.effective_from),
             None if pd.isna(r.effective_to) else str(r.effective_to)) for r in intervals.itertuples()}
    assert rows == {
        ("JSWCEMENT", "2025-12-31", None),
        ("SKFINDIA", "2025-09-22", "2025-12-30"),   # member from the coverage start until the day before exclusion
        ("RELINFRA", "2025-09-23", None),
        ("PEL", "2025-09-22", "2025-09-22"),
        ("TCS", "2025-09-22", None),
    }
    assert {"symbol", "effective_from", "effective_to", "source", "source_url", "fetched_at"} <= set(intervals.columns)
    uni = Universe(intervals.assign(effective_from=intervals["effective_from"].astype(str),
                                    effective_to=intervals["effective_to"].astype(str)))
    assert uni.members("2025-12-01") == {"SKFINDIA", "RELINFRA", "TCS"}
    assert uni.members("2025-12-31") == {"JSWCEMENT", "RELINFRA", "TCS"}
    assert uni.members("2024-01-01") is None  # before the oldest release: not covered, never filled


def test_symbol_alias_maps_an_old_printed_symbol_to_the_current_one() -> None:
    change = _parse("2025-09-23")
    intervals, problems = build_intervals({"RELINFRA2"}, [change], {"RELINFRA": "RELINFRA2"}, "u", "t")
    assert problems == []
    assert set(intervals["symbol"]) == {"RELINFRA2", "PEL"}  # the printed symbol RELINFRA never appears


def test_included_symbol_missing_from_todays_list_is_reported_not_guessed() -> None:
    intervals, problems = build_intervals({"TCS"}, [_parse("2025-12-31")], {}, "u", "t")
    assert any("JSWCEMENT" in p["name"] and "not a member afterwards" in p["reason"] for p in problems)


def test_leakage_check_catches_a_stock_that_was_not_a_member() -> None:
    intervals, _ = build_intervals({"TCS"}, [_parse("2025-12-31")], {}, "u", "t")
    uni = Universe(intervals.assign(effective_from=intervals["effective_from"].astype(str),
                                    effective_to=intervals["effective_to"].astype(str)))
    events = pd.DataFrame([{"budget_id": "B", "fiscal_year": "2025-26", "presented_on": "2025-12-31"}])
    with pytest.raises(LeakageError):
        validate_index_membership(pd.DataFrame([{"symbol": "ZZZ", "budget_id": "B"}]), uni, events)


# ---------------------------------------------------------------- command line behaviour
def _point_module_at(tmp_path: Path, monkeypatch, listed: dict[str, str]) -> Path:
    csv = tmp_path / "releases.csv"
    csv.write_text("effective_date,url\n" + "".join(f"  {d},{u}\n" for d, u in listed.items()), encoding="utf-8")
    monkeypatch.setattr(n500, "RELEASE_LIST", csv)
    monkeypatch.setattr(n500, "REPORT", tmp_path / "report.csv")
    monkeypatch.setattr(n500, "CSV_OUT", tmp_path / "out.csv")
    monkeypatch.setattr(n500, "INTERVALS_RAW", tmp_path / "raw_intervals.csv")
    monkeypatch.setattr(n500, "RAW_DIR", tmp_path)
    (tmp_path / "ind_nifty500list_2026-01-01.csv").write_text(
        "Company Name,Industry,Symbol,Series,ISIN Code\nJSW Cement Ltd.,Cement,JSWCEMENT,EQ,X\n", encoding="utf-8")
    return tmp_path


def test_cli_prints_per_release_counts_and_succeeds_on_the_real_fixtures(tmp_path, monkeypatch, capsys) -> None:
    listed = {name: f"https://example.org/{name}.pdf" for name in EXPECTED}
    _point_module_at(tmp_path, monkeypatch, listed)
    assert n500.main(["--no-download", "--releases-dir", str(FIXTURES)]) == 0
    out = capsys.readouterr().out
    assert "2017-03-31  excluded=25 included=25" in out and "2025-12-31  excluded=1 included=1" in out
    assert (tmp_path / "out.csv").exists()


def test_cli_exits_nonzero_when_a_listed_release_yields_no_nifty_500_changes(tmp_path, monkeypatch, capsys) -> None:
    releases = tmp_path / "pr"
    releases.mkdir()
    (releases / "2024-01-01.txt").write_text("effective from January 1, 2024\n1) Nifty 50\nnothing relevant\n")
    _point_module_at(tmp_path, monkeypatch, {"2024-01-01": "u", "2024-02-02": "u2"})  # second one has no file at all
    assert n500.main(["--no-download", "--releases-dir", str(releases)]) == 1
    captured = capsys.readouterr()
    assert "NO NIFTY 500 CHANGES FOUND" in captured.out and "MISSING FILE" in captured.out
    assert not (tmp_path / "out.csv").exists()
