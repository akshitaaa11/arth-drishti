"""stocks.csv, sector_map.json and symbol_check.csv must describe the same stock universe."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def test_stock_universe_is_consistent_across_config_and_symbol_check() -> None:
    stocks = pd.read_csv(ROOT / "config" / "stocks.csv")
    check = pd.read_csv(ROOT / "reports" / "symbol_check.csv")
    sector_map = json.loads((ROOT / "config" / "sector_map.json").read_text(encoding="utf-8"))

    map_pairs = {(s["sector_id"], st["symbol"]): st["yahoo_symbol"] for s in sector_map["sectors"] for st in s["stocks"]}
    csv_pairs = {(r.sector_id, r.symbol): r.yahoo_symbol for r in stocks.itertuples()}

    assert len(stocks) == stocks["symbol"].nunique() == 116
    assert map_pairs == csv_pairs
    assert set(check["symbol"]) == set(stocks["symbol"])
    assert (check["status"] == "ok").all()
    assert stocks["sector_id"].nunique() == len(sector_map["sectors"]) == 15
