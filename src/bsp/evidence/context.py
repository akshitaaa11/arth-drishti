"""Shared inputs for the Phase 8 evidence modules: config, market data, sector panel, windows and the Nifty 500 benchmark."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from bsp.evaluation.backtest import BacktestResult, run_backtest
from bsp.evaluation.config import EvalConfig, load_config
from bsp.evaluation.data import Panel, budget_calendar, load_sector_panel, trading_days
from bsp.evaluation.run_baselines import BENCHMARK
from bsp.features.baskets import MarketDataBundle, build_market_data_bundle


@dataclass
class Context:
    cfg: EvalConfig
    bundle: MarketDataBundle
    panel: Panel  # sector panel, hold-out and live year removed
    windows: pd.DataFrame  # budget_id, start, label_end
    calendar: pd.DataFrame
    market_level: pd.DataFrame
    bench: BacktestResult


def load_context(cfg: EvalConfig | None = None) -> Context:
    cfg = cfg or load_config()
    bundle = build_market_data_bundle(cfg.root)
    panel = load_sector_panel(cfg)
    calendar = budget_calendar(cfg.root, trading_days(cfg.root))
    windows = calendar[["budget_id", "start", "label_end"]]
    market_level = pd.DataFrame({BENCHMARK: (1.0 + bundle.market_returns.fillna(0.0)).cumprod()})
    budgets = sorted(panel.frame["budget_id"].unique())
    bench = run_backtest({b: [BENCHMARK] for b in budgets}, windows[windows["budget_id"].isin(budgets)], market_level, cfg.round_trip_cost)
    return Context(cfg, bundle, panel, windows, calendar, market_level, bench)
