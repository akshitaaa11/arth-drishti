"""FPI lookback window of a budget, and how much of it the collected NSDL data covers.

The FPI features use the last two NSDL fortnightly reports whose period ends on or before the budget's presented date
(``fpi_net_equity_1f_cr`` = the latest, ``fpi_net_equity_1m_cr`` = the sum of both, ``fpi_equity_aum_cr`` = the latest
AUM). A report that was never collected is a gap, not a zero and not a reason to reach back to an older report, so a
feature is computed only when the report(s) it needs are present; otherwise it is missing (NaN).

Windows: ``complete`` = both expected reports present, ``partial`` = one of the two, ``empty`` = neither.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd


def expected_periods(presented_on: str) -> tuple[str, str]:
    """(earlier, latest) NSDL fortnight ends on or before ``presented_on``: the 15th and the last day of a month."""
    day = date.fromisoformat(presented_on)
    ends: list[date] = []
    month_start = date(day.year, day.month, 1)
    while len(ends) < 2:
        month_end = date(month_start.year + (month_start.month == 12), (month_start.month % 12) + 1, 1) - timedelta(days=1)
        for end in (month_end, date(month_start.year, month_start.month, 15)):
            if end <= day and len(ends) < 2:
                ends.append(end)
        month_start = (month_start - timedelta(days=1)).replace(day=1)
    return ends[1].isoformat(), ends[0].isoformat()


def window_start(earlier_end: str) -> str:
    """First day of the earlier fortnight: the 1st if it ends on the 15th, else the 16th."""
    end = date.fromisoformat(earlier_end)
    return end.replace(day=1 if end.day == 15 else 16).isoformat()


def window_status(available: set[str], presented_on: str) -> str:
    earlier, latest = expected_periods(presented_on)
    present = (earlier in available) + (latest in available)
    return {2: "complete", 1: "partial", 0: "empty"}[present]


def coverage_table(root: Path) -> pd.DataFrame:
    """Per budget: window start/end and complete / partial / empty, from data/csv/fpi_sector_fortnightly.csv."""
    path = root / "data" / "csv" / "fpi_sector_fortnightly.csv"
    available = set(pd.read_csv(path, usecols=["period_end"])["period_end"].astype(str)) if path.exists() else set()
    events = pd.read_csv(root / "config" / "budget_events.csv").drop_duplicates("budget_id").sort_values("presented_on")
    rows = []
    for event in events.itertuples():
        presented = str(event.presented_on)
        earlier, latest = expected_periods(presented)
        rows.append({
            "budget_id": event.budget_id, "presented_on": presented,
            "window_start": window_start(earlier), "window_end": latest,
            "periods_present": f"{(earlier in available) + (latest in available)} of 2",
            "status": window_status(available, presented),
        })
    return pd.DataFrame(rows)
