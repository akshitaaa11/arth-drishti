"""FRED loader: new G-sec series id, manual-file fallback, and no filling of months before the series starts."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from bsp.ingest import _common, macro

FIXTURE = Path(__file__).parent / "fixtures" / "fred" / "INDIRLTLT01STM.csv"  # hand-made, 4 months incl. a "." gap


@pytest.fixture()
def raw_with_fred_file(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    (raw / "fred").mkdir(parents=True)
    shutil.copy(FIXTURE, raw / "fred" / "INDIRLTLT01STM.csv")
    csv = tmp_path / "csv"
    csv.mkdir()
    for module in (macro, _common):
        monkeypatch.setattr(module, "RAW_DIR", raw)
        monkeypatch.setattr(module, "CSV_DIR", csv)
    return raw, csv


def test_the_gsec_series_id_is_the_new_one() -> None:
    assert macro.FRED_SERIES["INDIRLTLT01STM"][0] == "g_sec_10y_yield"
    assert "IRLTLT01INM156N" not in macro.FRED_SERIES
    assert "fred.stlouisfed.org/series/INDIRLTLT01STM" in macro.FRED_SOURCES["INDIRLTLT01STM"]


def test_manual_file_is_read_and_missing_dot_values_are_dropped(raw_with_fred_file) -> None:
    frame = macro.load_fred_manual("INDIRLTLT01STM")
    assert list(frame["date"]) == ["2011-12-01", "2012-01-01", "2012-03-01"]  # the "." month is empty, not filled
    assert list(frame["value"]) == [8.5, 8.25, 8.0]


def test_manual_file_with_wrong_columns_is_rejected(raw_with_fred_file) -> None:
    raw, _ = raw_with_fred_file
    (raw / "fred" / "INDIRLTLT01STM.csv").write_text("date,value\n2011-12-01,8.5\n")
    with pytest.raises(ValueError, match="observation_date"):
        macro.load_fred_manual("INDIRLTLT01STM")


def test_fred_series_falls_back_to_the_manual_file_when_the_download_fails(raw_with_fred_file, monkeypatch) -> None:
    def failing(series):
        raise ConnectionError("blocked")

    monkeypatch.setattr(macro, "_fred_csv", failing)
    frame, how = macro.fred_series("INDIRLTLT01STM")
    assert len(frame) == 3 and how.startswith("manual file") and "download failed" in how
    monkeypatch.setattr(macro, "_fred_csv", lambda s: pd.DataFrame({"date": ["2020-01-01"], "value": [6.0]}))
    assert macro.fred_series("INDIRLTLT01STM")[1] == "download"  # a working download wins over the file


def test_fred_series_without_download_or_file_raises(raw_with_fred_file, monkeypatch) -> None:
    raw, _ = raw_with_fred_file
    (raw / "fred" / "INDIRLTLT01STM.csv").unlink()
    monkeypatch.setattr(macro, "_fred_csv", lambda s: (_ for _ in ()).throw(ConnectionError("blocked")))
    with pytest.raises(ConnectionError):
        macro.fred_series("INDIRLTLT01STM")


def test_collect_macro_writes_g_sec_10y_yield_from_the_manual_file(raw_with_fred_file, monkeypatch) -> None:
    raw, csv = raw_with_fred_file

    def fail(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(macro, "_fetch_yahoo_history", fail)
    monkeypatch.setattr(macro, "_world_bank", fail)
    monkeypatch.setattr(macro, "_fred_csv", fail)
    result = macro.collect_macro()
    gsec = result[result["series"] == "g_sec_10y_yield"].sort_values("date")
    assert list(gsec["date"]) == ["2011-12-01", "2012-01-01", "2012-03-01"]
    assert list(gsec["value"]) == [8.5, 8.25, 8.0]
    assert gsec["unit"].eq("percent").all() and gsec["source"].str.contains("OECD via FRED INDIRLTLT01STM").all()
    assert gsec["date"].min() == "2011-12-01"  # no rows before the series starts
    log = pd.read_csv(csv / "fetch_log.csv").iloc[-1]
    assert log["job"] == "macro" and "g_sec_10y_yield from manual file" in log["detail"]
