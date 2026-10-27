"""Sector evaluation panel: features + 12m targets + the date each label resolves, with the hold-out locked.

Sector level only: stock-level evaluation waits for a complete point-in-time Nifty 500 history (reports/data_gaps.md).
A panel row is one sector at one budget. ``label_end`` is the trading day on which the
12m target is fully known (the next budget's day 0), which the walk-forward uses to keep a training label from
ever being used before it exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from bsp.evaluation.config import EvalConfig

SECTOR_FEATURES = [
    "alloc_vs_prev_re_pct", "growth_vs_prev_be_pct", "credibility_pct", "capex_share_be_pct",
    "scheme_push_total_cr", "fiscal_deficit_be_cr", "fiscal_subsidies_cr",
    "momentum_1m", "momentum_3m", "momentum_6m", "momentum_12m", "volatility_30d", "volatility_90d",
    "fpi_net_equity_1m_cr", "macro_usd_inr_1y_pct", "macro_brent_crude_1y_pct", "macro_policy_rate",
    "macro_cpi_inflation", "macro_gdp_growth", "regime_is_election_year", "regime_is_covid_era", "regime_high_vix",
]


@dataclass(frozen=True)
class Panel:
    """Sector rows. ``frame`` never contains locked budgets unless the config unlocked them."""

    kind: str  # always "sector" for now
    frame: pd.DataFrame
    features: list[str]


def trading_days(root: Path) -> list[str]:
    """Same calendar the feature store uses: every date that has at least one stock price."""
    dates = pd.read_csv(root / "data" / "csv" / "prices_daily.csv", usecols=["date"])["date"].astype(str)
    return sorted(dates.unique())


def budget_calendar(root: Path, days: list[str]) -> pd.DataFrame:
    """Per budget: day 0 (first trading day on/after presented_on), start (day 0 + 1) and the next budget's day 0."""
    events = (
        pd.read_csv(root / "config" / "budget_events.csv")
        .drop_duplicates("budget_id").sort_values("presented_on").reset_index(drop=True)
    )
    index = {d: i for i, d in enumerate(days)}
    day0 = []
    for presented in events["presented_on"].astype(str):
        later = [d for d in days if d >= presented]
        day0.append(later[0] if later else None)
    events["day0"] = day0
    events["start"] = [days[min(index[d] + 1, len(days) - 1)] if d else None for d in day0]
    events["label_end"] = events["day0"].shift(-1)
    return events[["budget_id", "fiscal_year", "presented_on", "budget_type", "day0", "start", "label_end"]]


def control_sectors(root: Path) -> frozenset[str]:
    """Sectors flagged ``is_control`` in config/sector_map.json (IT Services): reported separately, never ranked."""
    sector_map = json.loads((root / "config" / "sector_map.json").read_text(encoding="utf-8"))
    return frozenset(s["sector_id"] for s in sector_map["sectors"] if s.get("is_control"))


def load_sector_panel(cfg: EvalConfig, include_locked: bool = False) -> Panel:
    """Sector panel. Locked hold-out / live budgets are removed; ``include_locked=True`` raises until unlocked."""
    root = cfg.root
    csv = root / "data" / "csv"
    wide = pd.read_csv(csv / "features_sector_year_wide.csv").rename(columns={"sector_id": "entity"})
    wide["sector_id"] = wide["entity"]
    wide["fiscal_year"] = wide["fiscal_year"].astype(str)
    if include_locked:
        cfg.assert_not_locked(wide["fiscal_year"].unique(), "sector panel rows")
    else:
        wide = wide[~wide["fiscal_year"].isin(cfg.locked_fiscal_years)]
    targets = pd.read_csv(csv / "targets.csv")
    targets = targets[(targets["entity_type"] == "sector") & (targets["horizon"] == "12m")]
    targets = targets[["entity", "budget_id", "excess_return", "target_complete"]]
    frame = wide.merge(targets, on=["entity", "budget_id"], how="left")
    calendar = budget_calendar(root, trading_days(root))
    frame = frame.merge(calendar[["budget_id", "budget_type", "day0", "start", "label_end"]], on="budget_id", how="left")
    # Interim budgets carry no sector budget data and have shorter labels: models are trained and tested on full budgets.
    frame = frame[frame["budget_type"] == "full"]
    frame["target_complete"] = frame["target_complete"].fillna(False).astype(bool)
    frame["is_control"] = frame["entity"].isin(control_sectors(root))
    frame = frame.sort_values(["presented_on", "entity"]).reset_index(drop=True)
    return Panel(kind="sector", frame=frame, features=[c for c in SECTOR_FEATURES if c in frame.columns])
