from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTOR_MAP = ROOT / "config" / "sector_map.json"


def validate_sector_map(path: Path = SECTOR_MAP) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    sectors = payload.get("sectors")
    if not isinstance(sectors, list):
        raise ValueError("sector_map.json is missing a valid 'sectors' array")
    if len(sectors) != 15:
        raise ValueError(f"Expected 15 sectors, found {len(sectors)}")

    for sector in sectors:
        sector_id = sector.get("sector_id")
        if not sector_id:
            raise ValueError("Sector missing sector_id")
        stocks = sector.get("stocks")
        if not isinstance(stocks, list) or not stocks:
            raise ValueError(f"Sector {sector_id} has no stocks")
        for stock in stocks:
            symbol = stock.get("symbol")
            yahoo_symbol = stock.get("yahoo_symbol")
            if not symbol or not yahoo_symbol:
                raise ValueError(f"Sector {sector_id} has a stock missing symbol or yahoo_symbol")

    print(f"Validated {len(sectors)} sectors and all stock symbols.")


if __name__ == "__main__":
    validate_sector_map()
