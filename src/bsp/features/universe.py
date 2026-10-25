"""Point-in-time Nifty 500 universe lookup built from ``data/csv/nifty500_constituents.csv``.

The history only extends back to the oldest index-change press release that was rebuilt (see
``scripts/collect/nifty500_history.py``). A budget dated before that coverage start, or an empty
constituents file, gives no membership information: those budgets fall back to the listing-date check
only, and the stock-year report says so.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


class Universe:
    def __init__(self, constituents: pd.DataFrame | None) -> None:
        if constituents is None or constituents.empty:
            self.frame = pd.DataFrame(columns=["symbol", "effective_from", "effective_to"])
        else:
            self.frame = constituents[["symbol", "effective_from", "effective_to"]].copy()
            self.frame["effective_from"] = self.frame["effective_from"].astype(str)
            self.frame["effective_to"] = self.frame["effective_to"].fillna("9999-12-31").astype(str)
            self.frame.loc[self.frame["effective_to"].isin(["", "nan"]), "effective_to"] = "9999-12-31"

    @classmethod
    def from_csv(cls, path: Path) -> Universe:
        if not path.exists():
            return cls(None)
        return cls(pd.read_csv(path))

    @property
    def coverage_start(self) -> str | None:
        return None if self.frame.empty else str(self.frame["effective_from"].min())

    def covers(self, on: str) -> bool:
        start = self.coverage_start
        return start is not None and on >= start

    def members(self, on: str) -> set[str] | None:
        """Symbols in the index on ``on`` (ISO date), or None when the history does not cover that date."""
        if not self.covers(on):
            return None
        rows = self.frame[(self.frame["effective_from"] <= on) & (self.frame["effective_to"] >= on)]
        return set(rows["symbol"].astype(str))
