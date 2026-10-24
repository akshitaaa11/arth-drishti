from __future__ import annotations

from pathlib import Path

from bsp.common.config import load_config
from bsp.common.db import get_session_factory

ROOT = Path(__file__).resolve().parents[1]


def test_config_loader_reads_sector_map() -> None:
    payload = load_config("sector_map.json")
    sectors = payload.get("sectors")
    assert isinstance(sectors, list)
    assert len(sectors) == 15


def test_sqlite_session_factory_works() -> None:
    factory = get_session_factory(database_url="sqlite:///:memory:")
    session = factory()
    try:
        assert session is not None
    finally:
        session.close()


def test_source_inventory_is_present() -> None:
    inventory = ROOT / "data" / "source_pdfs" / "INVENTORY.csv"
    assert inventory.exists()
    text = inventory.read_text(encoding="utf-8")
    assert "filename,document_type,fiscal_year,pages" in text
