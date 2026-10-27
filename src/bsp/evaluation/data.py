"""Evaluation panels: features + 12m targets + the date each label resolves, with the hold-out locked.

A panel row is one entity (sector or stock) at one budget. ``label_end`` is the trading day on which the
12m target is fully known (the next budget's day 0), which the walk-forward uses to keep a training label from
ever being used before it exists.
"""

from __future__ import annotations

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
STOCK_FEATURES = [
    "momentum_1m", "momentum_3m", "momentum_6m", "momentum_12m", "volatility_30d", "volatility_90d",
    "liquidity_90d", "size_traded_val", "beta_250d", "beta_90d",
]


@dataclass(frozen=True)
class Panel:
    """Rows for one entity type. ``frame`` never contains locked budgets unless the config unlocked them."""

    kind: str  # "sector" or "stock"
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


def _load(cfg: EvalConfig, kind: str, include_locked: bool) -> Panel:
    root = cfg.root
    csv = root / "data" / "csv"
    wide = pd.read_csv(csv / ("features_sector_year_wide.csv" if kind == "sector" else "features_stock_year_wide.csv"))
    entity_col = "sector_id" if kind == "sector" else "symbol"
    wide = wide.rename(columns={entity_col: "entity"})
    if "sector_id" not in wide.columns:
        wide["sector_id"] = wide["entity"]
    wide["fiscal_year"] = wide["fiscal_year"].astype(str)
    if include_locked:
        cfg.assert_not_locked(wide["fiscal_year"].unique(), f"{kind} panel rows")
    else:
        wide = wide[~wide["fiscal_year"].isin(cfg.locked_fiscal_years)]
    targets = pd.read_csv(csv / "targets.csv")
    targets = targets[(targets["entity_type"] == kind) & (targets["horizon"] == "12m")]
    targets = targets[["entity", "budget_id", "excess_return", "target_complete"]]
    frame = wide.merge(targets, on=["entity", "budget_id"], how="left")
    calendar = budget_calendar(root, trading_days(root))
    frame = frame.merge(calendar[["budget_id", "budget_type", "day0", "start", "label_end"]], on="budget_id", how="left")
    # Interim budgets carry no sector budget data and have shorter labels: models are trained and tested on full budgets.
    frame = frame[frame["budget_type"] == "full"]
    frame["target_complete"] = frame["target_complete"].fillna(False).astype(bool)
    frame = frame.sort_values(["presented_on", "entity"]).reset_index(drop=True)
    features = SECTOR_FEATURES if kind == "sector" else STOCK_FEATURES
    return Panel(kind=kind, frame=frame, features=[c for c in features if c in frame.columns])


def load_sector_panel(cfg: EvalConfig, include_locked: bool = False) -> Panel:
    """Sector panel. Locked hold-out / live budgets are removed; ``include_locked=True`` raises until unlocked."""
    return _load(cfg, "sector", include_locked)


def load_stock_panel(cfg: EvalConfig, include_locked: bool = False) -> Panel:
    return _load(cfg, "stock", include_locked)
