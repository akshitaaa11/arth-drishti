"""Market CSV loader: upsert on natural keys, stale-row removal, fetch_log, NULL handling (hand-made CSVs)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from bsp.common.db import create_engine
from bsp.ingest.load import load_market_csvs

ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-01-01T00:00:00+00:00"


def _write(csv_dir: Path, close: float = 10.0, extra_price_row: bool = True) -> None:
    prices = [
        {"symbol": "AAA", "date": "2020-01-01", "open": 1, "high": 2, "low": 1, "close": close, "adj_close": close,
         "volume": 5, "traded_value_cr": 0.1, "source": "t", "source_url": "u", "fetched_at": STAMP},
    ]
    if extra_price_row:
        prices.append({**prices[0], "date": "2020-01-02"})
    pd.DataFrame(prices).to_csv(csv_dir / "prices_daily.csv", index=False)
    pd.DataFrame([{"index_name": "Nifty 500", "ticker": "^X", "date": "2020-01-01", "close": 100.0, "volume": 0,
                   "source": "t", "fetched_at": STAMP}]).to_csv(csv_dir / "index_daily.csv", index=False)
    pd.DataFrame([{"series": "usd_inr", "date": "2020-01-01", "value": None, "unit": "INR", "source": "t",
                   "fetched_at": STAMP}]).to_csv(csv_dir / "macro.csv", index=False)
    pd.DataFrame([{"period_end": "2020-01-15", "nsdl_sector": "Metals", "equity_net_cr": -5.0, "debt_net_cr": 0.0,
                   "equity_aum_cr": 99.0, "source_url": "u", "source": "t", "fetched_at": STAMP}]
                 ).to_csv(csv_dir / "fpi_sector_fortnightly.csv", index=False)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'bsp.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    return url, csv_dir


def _count(url: str, sql: str):
    with create_engine(database_url=url).connect() as conn:
        return conn.execute(text(sql)).scalar()


def test_load_is_idempotent_and_matches_csv(db) -> None:
    url, csv_dir = db
    _write(csv_dir)
    first = load_market_csvs(url, csv_dir)
    second = load_market_csvs(url, csv_dir)
    assert first == second == {"prices_daily": 2, "index_daily": 1, "macro": 1, "fpi_flows": 1}
    assert _count(url, "SELECT COUNT(*) FROM prices_daily") == 2
    assert _count(url, "SELECT equity_cr FROM fpi_flows") == -5.0
    assert _count(url, "SELECT value FROM macro") is None  # blank CSV cell stays NULL
    # one fetch_log row per table per run, all successful
    assert _count(url, "SELECT COUNT(*) FROM fetch_log WHERE job LIKE 'load%' AND status = 'success'") == 8


def test_changed_values_are_updated_and_removed_rows_deleted(db) -> None:
    url, csv_dir = db
    _write(csv_dir)
    load_market_csvs(url, csv_dir)
    _write(csv_dir, close=11.5, extra_price_row=False)  # value changed, one row removed (e.g. cleaned away)
    load_market_csvs(url, csv_dir)
    assert _count(url, "SELECT COUNT(*) FROM prices_daily") == 1
    assert _count(url, "SELECT close FROM prices_daily") == 11.5


def test_failed_load_is_logged_and_raises(db) -> None:
    url, csv_dir = db
    _write(csv_dir)
    (csv_dir / "macro.csv").unlink()
    with pytest.raises(FileNotFoundError):
        load_market_csvs(url, csv_dir)
    assert _count(url, "SELECT COUNT(*) FROM fetch_log WHERE job = 'load_macro' AND status = 'failed'") == 1


def test_migrations_create_every_readme_section9_table(db) -> None:
    from sqlalchemy import inspect

    url, _ = db
    tables = set(inspect(create_engine(database_url=url)).get_table_names())
    section9 = {"budget_events", "budget_lines", "sector_line_map", "stocks", "prices_daily",
                "fpi_flows", "macro", "features_sector_year", "features_stock_year", "targets", "event_study",
                "predictions", "sealed_ledger", "fetch_log"}
    assert section9 <= tables
    assert "index_constituents" not in tables  # dropped by migration 005 when the Nifty 500 constituent work was removed
    assert "index_daily" in tables


def test_migration_005_can_be_downgraded_and_upgraded_again(db) -> None:
    from sqlalchemy import inspect

    url, _ = db
    config = Config(str(ROOT / "alembic.ini"))
    command.downgrade(config, "-1")
    assert "index_constituents" in set(inspect(create_engine(database_url=url)).get_table_names())
    command.upgrade(config, "head")
    assert "index_constituents" not in set(inspect(create_engine(database_url=url)).get_table_names())
