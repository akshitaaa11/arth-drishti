"""F10 error reports split by regime: election year, Covid era, high VIX (and interim budgets, which are not modelled).

For each sector model and each regime flag, the per-budget metrics of the 14 budget-sensitive sectors (Spearman IC, MAE of the
expected excess return, directional accuracy, and the top-3 portfolio's net return minus the Nifty 500's over the same window)
are averaged over the test budgets with and without the flag. Flags come from the sector feature store. Interim budgets are not
predicted (they carry no sector budget data and have 4-5 month labels), so their row says so instead of showing a number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bsp.evaluation import metrics
from bsp.evaluation.backtest import BacktestResult

FLAGS = {"election_year": "regime_is_election_year", "covid_era": "regime_is_covid_era", "high_vix": "regime_high_vix"}
MODELS = ["equal_weight", "last_years_winners", "biggest_allocation_increase", "ridge", "lgbm_ranker", "bayes_hier", "tier1_blend"]


def regime_errors(predictions: pd.DataFrame, flags: pd.DataFrame, runs: dict[str, BacktestResult], bench: BacktestResult) -> pd.DataFrame:
    bench_net = bench.periods.set_index("budget_id")["net_return"]
    rows = []
    for model in MODELS:
        frame = predictions[(predictions["model"] == model) & (~predictions["is_control"].astype(bool))]
        if frame.empty or model not in runs:
            continue
        port = runs[model].periods.set_index("budget_id")["net_return"]
        per_budget = []
        for budget_id, g in frame.groupby("budget_id"):
            actual = g["actual"].to_numpy()
            has_forecast = "expected" in g and g["expected"].notna().any()
            per_budget.append({
                "budget_id": budget_id, "ic": metrics.spearman_ic(g["score"].to_numpy(), actual),
                "mae": metrics.mae(g["expected"].to_numpy(), actual) if has_forecast else np.nan,
                "directional": metrics.directional_accuracy(g["expected"].to_numpy(), actual) if has_forecast else np.nan,
                "top3_excess_vs_nifty": float(port.get(budget_id, np.nan) - bench_net.get(budget_id, np.nan))})
        table = pd.DataFrame(per_budget).merge(flags, on="budget_id", how="left")
        for regime, column in FLAGS.items():
            for value, label in ((1.0, "yes"), (0.0, "no")):
                g = table[table[column] == value]
                rows.append({"model": model, "regime": regime, "flag": label, "n_budgets": len(g), "mean_ic": g["ic"].mean(),
                             "mean_mae": g["mae"].mean(), "mean_directional": g["directional"].mean(),
                             "mean_top3_excess": g["top3_excess_vs_nifty"].mean()})
    return pd.DataFrame(rows)
