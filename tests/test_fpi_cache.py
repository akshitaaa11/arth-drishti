"""FPI collector: a "Request Rejected" page is never cached, never parsed, logged as blocked, and the CSV survives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import pytest

from bsp.ingest import _common, fpi

REJECTED = ("<html><head><title>Request Rejected</title></head><body>The requested URL was rejected. "
            "Please consult with your administrator.<br><br>Your support ID is: 1234567890</body></html>")
REPORT = "<html><body><table><tr><td>Sector</td></tr><tr><td>Metals</td></tr></table></body></html>"
OLD_ROW = {"period_end": "2018-09-15", "nsdl_sector": "Metals", "equity_net_cr": 5.0, "debt_net_cr": 0.0,
           "equity_aum_cr": 99.0, "source_url": "u", "source": "s", "fetched_at": "t"}


@dataclass
class FakeResponse:
    text: str
    status_code: int = 200


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    csv_dir, raw_dir = tmp_path / "csv", tmp_path / "raw"
    csv_dir.mkdir()
    for module in (fpi, _common):
        monkeypatch.setattr(module, "CSV_DIR", csv_dir)
    monkeypatch.setattr(fpi, "RAW_DIR", raw_dir)
    monkeypatch.setattr(_common, "RAW_DIR", raw_dir)
    monkeypatch.setattr(fpi, "_fortnight_ends", lambda start=None: iter([date(2018, 9, 15), date(2018, 9, 30), date(2018, 10, 15)]))
    return csv_dir, raw_dir / "nsdl_fpi"


def test_blocked_page_detection() -> None:
    assert fpi.is_blocked_page(REJECTED)
    assert fpi.is_blocked_page("<html>Your Support ID is: 5 <table></table></html>")
    assert fpi.is_blocked_page("<html><body>maintenance</body></html>")  # no table: not a report
    assert not fpi.is_blocked_page(REPORT)


def test_fetch_report_never_caches_a_blocked_page_and_does_cache_a_real_one(tmp_path) -> None:
    status, html = fpi.fetch_report(date(2018, 9, 15), tmp_path, get=lambda *a, **k: FakeResponse(REJECTED))
    assert (status, html) == ("blocked", None) and list(tmp_path.glob("*.html")) == []
    status, html = fpi.fetch_report(date(2018, 9, 15), tmp_path, get=lambda *a, **k: FakeResponse(REPORT))
    assert status == "fetched" and (tmp_path / "2018-09-15.html").exists()
    # a cached genuine report is not fetched again
    assert fpi.fetch_report(date(2018, 9, 15), tmp_path, get=lambda *a, **k: 1 / 0)[0] == "cached"
    assert fpi.fetch_report(date(2018, 9, 30), tmp_path, get=lambda *a, **k: FakeResponse("", 404))[0] == "not_found"
    assert fpi.fetch_report(date(2018, 9, 30), tmp_path, get=lambda *a, **k: FakeResponse("", 403))[0] == "blocked"


def test_poisoned_cache_from_an_older_run_is_purged_and_refetched(sandbox) -> None:
    csv_dir, raw = sandbox
    raw.mkdir(parents=True)
    (raw / "2018-09-15.html").write_text(REJECTED, encoding="utf-8")  # what the old code cached
    (raw / "2018-09-30.html").write_text(REPORT, encoding="utf-8")    # a good one must survive
    assert fpi.purge_poisoned_cache(raw) == ["2018-09-15"]
    assert not (raw / "2018-09-15.html").exists() and (raw / "2018-09-30.html").exists()


def test_blocked_run_logs_blocked_keeps_the_csv_and_caches_nothing(sandbox, monkeypatch) -> None:
    csv_dir, raw = sandbox
    pd.DataFrame([OLD_ROW]).to_csv(csv_dir / "fpi_sector_fortnightly.csv", index=False)
    before = (csv_dir / "fpi_sector_fortnightly.csv").read_bytes()
    result = fpi.collect_fpi(get=lambda *a, **k: FakeResponse(REJECTED), pause=0)
    assert (csv_dir / "fpi_sector_fortnightly.csv").read_bytes() == before
    assert list(raw.glob("*.html")) == []
    log = pd.read_csv(csv_dir / "fetch_log.csv")
    assert log.iloc[-1]["job"] == "fpi" and log.iloc[-1]["status"] == "blocked"
    assert "existing CSV kept" in log.iloc[-1]["detail"]
    assert len(result) == 1


def test_good_pages_are_merged_with_existing_rows_not_replacing_them(sandbox, monkeypatch) -> None:
    csv_dir, raw = sandbox
    pd.DataFrame([OLD_ROW, {**OLD_ROW, "period_end": "2018-03-15"}]).to_csv(csv_dir / "fpi_sector_fortnightly.csv", index=False)
    monkeypatch.setattr(fpi, "parse_fpi_html", lambda html, period_end: pd.DataFrame([{
        "period_end": period_end.isoformat(), "nsdl_sector": "Metals", "equity_net_cr": 1.0, "debt_net_cr": 0.0,
        "equity_aum_cr": 2.0}]))
    result = fpi.collect_fpi(get=lambda *a, **k: FakeResponse(REPORT), pause=0)
    assert sorted(result["period_end"]) == ["2018-03-15", "2018-09-15", "2018-09-30", "2018-10-15"]
    # 2018-09-15 was rebuilt from the fresh page (equity_net 1.0), the untouched 2018-03-15 row survived
    assert result.set_index("period_end").loc["2018-09-15", "equity_net_cr"] == 1.0
    assert pd.read_csv(csv_dir / "fetch_log.csv").iloc[-1]["status"] == "ok"
    assert len(list(raw.glob("*.html"))) == 3


def test_collector_stops_after_repeated_blocks(sandbox, monkeypatch) -> None:
    csv_dir, raw = sandbox
    calls: list[int] = []
    monkeypatch.setattr(fpi, "_fortnight_ends", lambda start=None: (date(2018, 1, 15) for _ in range(20)))
    fpi.collect_fpi(get=lambda *a, **k: calls.append(1) or FakeResponse(REJECTED), pause=0)
    assert len(calls) == fpi.MAX_CONSECUTIVE_BLOCKS  # no endless retrying


def test_url_builder_matches_the_pattern_seen_in_the_loaded_csv() -> None:
    assert fpi.fpi_url(date(2018, 9, 15)).endswith("/FIIInvestSector_September152018.html")
    assert fpi.fpi_url(date(2024, 7, 31)).endswith("/FIIInvestSector_July312024.html")  # example URL printed in the PRD
