"""Sourced, per-stock corrections to the Yahoo price series, kept in two small config files.

* ``config/listing_date_overrides.csv``: a stock whose Yahoo series starts before the company existed (for example a
  demerged company that inherits its parent's history). Every price row before ``listing_date`` is dropped by the
  price pipeline, and ``listing_date`` becomes the stock's listing date.
* ``config/return_exclusions.csv``: one day whose return is a corporate-action break (for example a demerger
  ex-date). The feature pipeline treats that day's return as MISSING; prices are not rescaled and no adjustment
  factor is invented. A window return that spans the day is the price ratio with that day's return divided out.

Both files carry a source URL and a verification note for every row; rows without a source are rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from bsp.common.config import get_project_root

REQUIRED = ["symbol", "verification", "source_url", "note"]


@dataclass(frozen=True)
class ListingOverride:
    symbol: str
    listing_date: str
    verification: str
    source_url: str
    note: str


@dataclass(frozen=True)
class ReturnExclusion:
    symbol: str
    date: str
    verification: str
    source_url: str
    note: str


def _read(path: Path, date_column: str) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=[*REQUIRED, date_column])
    frame = pd.read_csv(path, skipinitialspace=True, dtype=str).fillna("")
    missing = [c for c in (*REQUIRED, date_column) if c not in frame.columns]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")
    for row in frame.to_dict("records"):
        if not str(row["source_url"]).strip():
            raise ValueError(f"{path.name}: {row['symbol']} has no source_url; a correction needs a source")
        date.fromisoformat(str(row[date_column]).strip())  # raises on a malformed date
    return frame


def load_listing_overrides(root: Path | None = None) -> dict[str, ListingOverride]:
    frame = _read((root or get_project_root()) / "config" / "listing_date_overrides.csv", "listing_date")
    rows = [{str(k): str(v).strip() for k, v in r.items()} for r in frame.to_dict("records")]
    return {r["symbol"]: ListingOverride(r["symbol"], r["listing_date"], r["verification"], r["source_url"], r["note"])
            for r in rows}


def load_return_exclusions(root: Path | None = None) -> list[ReturnExclusion]:
    frame = _read((root or get_project_root()) / "config" / "return_exclusions.csv", "date")
    rows = [{str(k): str(v).strip() for k, v in r.items()} for r in frame.to_dict("records")]
    return [ReturnExclusion(r["symbol"], r["date"], r["verification"], r["source_url"], r["note"]) for r in rows]
