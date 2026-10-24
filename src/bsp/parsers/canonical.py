"""Canonical names for ministries and departments that changed over time."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from bsp.common.config import get_project_root


@lru_cache(maxsize=1)
def ministry_aliases(path: str | Path | None = None) -> dict[str, str]:
    alias_path = Path(path) if path else get_project_root() / "config" / "ministry_aliases.csv"
    with alias_path.open("r", encoding="utf-8-sig", newline="") as handle:
        aliases = {
            row["raw_name"].strip(): row["canonical_name"].strip()
            for row in csv.DictReader(handle)
            if row.get("raw_name") and row.get("canonical_name")
        }
    return aliases


def canonicalise_ministry(name: str, *, aliases: dict[str, str] | None = None) -> str:
    mapping = aliases if aliases is not None else ministry_aliases()
    return mapping.get(name.strip(), name.strip())
