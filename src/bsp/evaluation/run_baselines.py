"""Run every Phase 4 baseline through the walk-forward harness, backtest it and write ``reports/baselines.md``.

``make backtest`` runs ``python -m bsp.evaluation.run_baselines``. Fixed seeds, no timestamps in the outputs:
two runs produce byte-identical CSV and Markdown files (checked in ``tests/test_phase4_baselines.py``).
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bsp.evaluation import metrics, tracking
from bsp.evaluation.backtest import BacktestResult, run_backtest, top_k_selection
from bsp.evaluation.config import EvalConfig, load_config
from bsp.evaluation.data import (
    Panel,
    budget_calendar,
    load_sector_panel,
    load_stock_panel,
    trading_days,
)
from bsp.evaluation.walk_forward import Model, stack_predictions, walk_forward
from bsp.features.baskets import MarketDataBundle, build_market_data_bundle
from bsp.models.baselines import (
    EqualWeight,
    RidgeBaseline,
    biggest_allocation_increase,
    last_years_winners,
    make_ridge_tuner,
)

BENCHMARK = "NIFTY500"
SECTOR_MODELS = ["equal_weight", "last_years_winners", "biggest_allocation_increase", "ridge"]
STOCK_MODELS = ["equal_weight", "momentum", "ridge"]


@dataclass
class ModelRun:
    level: str
    name: str
    predictions: pd.DataFrame
    per_year: pd.DataFrame
    summary: dict[str, float]
    backtest: BacktestResult
    params: dict[str, Any]


def _nanmean(values: pd.Series) -> float:
    values = values.dropna()
    return float(values.mean()) if len(values) else float("nan")


def _cross_section_metrics(group: pd.DataFrame, level: str) -> dict[str, float]:
    score, actual = group["score"].to_numpy(), group["actual"].to_numpy()
    out = {
        "ic": metrics.spearman_ic(score, actual),
        "ndcg10": metrics.ndcg_at_k(score, actual, 10),
    }
    if level == "sector":
        out["top3_hit"] = metrics.top_k_hit_rate(score, actual, 3)
        out["precision5"] = metrics.precision_at_k(score, actual, 5)
    else:
        by_sector = [metrics.precision_at_k(g["score"].to_numpy(), g["actual"].to_numpy(), 5)
                     for _, g in group.groupby("sector_id")]
        out["precision5"] = float(np.nanmean(by_sector)) if not np.all(np.isnan(by_sector)) else float("nan")
    if "expected" in group:
        out["mae"] = metrics.mae(group["expected"].to_numpy(), actual)
        out["directional"] = metrics.directional_accuracy(group["expected"].to_numpy(), actual)
    if "lo" in group:
        out["coverage"] = metrics.interval_coverage(group["lo"].to_numpy(), group["hi"].to_numpy(), actual)
        out["width"] = metrics.interval_width(group["lo"].to_numpy(), group["hi"].to_numpy())
    return out


def _levels(bundle: MarketDataBundle, level: str) -> pd.DataFrame:
    if level == "sector":
        return (1.0 + bundle.sector_returns.fillna(0.0)).cumprod()
    return bundle.stock_prices


def evaluate(level: str, name: str, panel: Panel, make_model: Callable[..., Model], tune: Any, cfg: EvalConfig,
             windows: pd.DataFrame, bundle: MarketDataBundle, bench: BacktestResult | None) -> ModelRun:
    folds = walk_forward(panel, make_model, cfg, tune)
    predictions = stack_predictions(folds)
    rows = [{"budget_id": b, **_cross_section_metrics(g, level)} for b, g in predictions.groupby("budget_id")]
    per_year = pd.DataFrame(rows)
    k = cfg.top_k_sectors if level == "sector" else cfg.top_k_stocks
    selects_all = bool(make_model(**folds[0].params).selects_all)
    selections = top_k_selection(predictions, k, selects_all)
    used = windows[windows["budget_id"].isin(selections)]
    backtest = run_backtest(selections, used, _levels(bundle, level), cfg.round_trip_cost)
    per_year = per_year.merge(backtest.periods[["budget_id", "net_return"]].rename(columns={"net_return": "port_net"}),
                              on="budget_id", how="left")
    if bench is not None:
        bench_ret = bench.periods.set_index("budget_id")["net_return"]
        per_year["bench_net"] = per_year["budget_id"].map(bench_ret)
        per_year["port_excess"] = per_year["port_net"] - per_year["bench_net"]
    summary = {col: _nanmean(per_year[col]) for col in per_year.columns if col != "budget_id"}
    summary["ic_positive_share"] = float((per_year["ic"].dropna() > 0).mean()) if per_year["ic"].notna().any() else float("nan")
    summary.update({f"bt_{key}": value for key, value in backtest.summary.items()})
    params = {"level": level, "model": name, "top_k": k, "round_trip_cost": cfg.round_trip_cost, "seed": cfg.seed,
              "n_folds": len(folds), "first_test": folds[0].budget_id, "last_test": folds[-1].budget_id,
              "holdout_locked": not cfg.holdout_unlocked, "tuned_alphas": [f.params.get("alpha") for f in folds]}
    return ModelRun(level, name, predictions, per_year, summary, backtest, params)


def _fmt(value: float, digits: int = 3, pct: bool = False) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value * 100:.1f}%" if pct else f"{value:.{digits}f}"


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def write_report(runs: list[ModelRun], bench: BacktestResult, cfg: EvalConfig, path: Path) -> None:
    out = ["# Phase 4 baselines", "",
           "Generated by `make backtest` (`src/bsp/evaluation/run_baselines.py`). Every number is out-of-sample: "
           "expanding-window walk-forward, a budget is only predicted from rows whose 12m label was already known on "
           "its day 0. Nothing here is investment advice.", "",
           "## Setup", "",
           f"- Test budgets: full budgets from FY{cfg.first_test_fiscal_year} to FY2023-24; interim budgets have no "
           "sector features and are not predicted or used for training stocks either. Training grows each year (minimum "
           f"{cfg.min_train_budgets} budgets).",
           f"- **Locked hold-out: FY{', FY'.join(cfg.holdout_fiscal_years)} (including their interim budgets); sealed live year: "
           f"FY{', FY'.join(cfg.live_fiscal_years)}.** They are not loaded by the evaluation panels and loading them raises `HoldoutLockedError` until Phase 9.",
           "- Target: 12m excess return over the Nifty 500 (day after the budget to the next budget's day 0).",
           f"- Portfolios: equal weight, top {cfg.top_k_sectors} sectors / top {cfg.top_k_stocks} stocks, bought at the "
           "close of the day after the budget and sold at the target window's end; "
           f"{cfg.round_trip_cost * 100:.1f}% round-trip cost per window; cash earns 0% between windows; Sharpe uses "
           "risk-free = 0 over the whole span including cash days.",
           "- The **Nifty 500 benchmark** is bought and sold over the same windows with the same costs.",
           f"- Seed {cfg.seed}; two runs give identical files.",
           "- Limitations: stock results carry **survivorship bias** (the stock list is today's list, and a stock with no "
           "price on the sell date is dropped); the Nifty 500 point-in-time universe is not available yet (listing-date "
           "filter only); sector baskets are thin in early years (see `reports/sector_basket_report.csv`); with 12 test "
           "years every statistic is noisy. A null result is a valid result.",
           "- **Every baseline beats the Nifty 500 by a wide margin, mostly for structural reasons**: the baselines hold "
           "equal-weight baskets of today's (survivor) stocks, which tilts to small and mid caps, while the Nifty 500 is "
           "cap-weighted. The fair bar for a model is therefore the **equal-weight** row, not the Nifty 500.",
           "- The stock ridge's high IC should be read with the same survivorship caveat: it is trained and tested on "
           "today's survivors, so size and liquidity features can look more predictive than they would on the true "
           "point-in-time universe. Re-run after the Nifty 500 history is added.", ""]

    bench_s = bench.summary
    for level, title, models in (("sector", "Sector baselines (15 sectors)", SECTOR_MODELS),
                                 ("stock", "Stock baselines (~100 stocks per year)", STOCK_MODELS)):
        subset = [r for r in runs if r.level == level]
        if not subset:
            continue
        out += [f"## {title}", ""]
        header = ["Model", "Mean IC", "IC>0 years", "Top-3 hit", "Precision@5", "NDCG@10", "MAE", "Directional",
                  "80% coverage", "Interval width"]
        rows = []
        for r in subset:
            s = r.summary
            rows.append([r.name, _fmt(s.get("ic", float("nan"))), _fmt(s.get("ic_positive_share", float("nan")), pct=True),
                         _fmt(s.get("top3_hit", float("nan")), pct=True), _fmt(s.get("precision5", float("nan"))),
                         _fmt(s.get("ndcg10", float("nan"))), _fmt(s.get("mae", float("nan"))),
                         _fmt(s.get("directional", float("nan")), pct=True), _fmt(s.get("coverage", float("nan")), pct=True),
                         _fmt(s.get("width", float("nan")))])
        out += [_table(header, rows), "",
                "IC, top-3 hit and NDCG are undefined (n/a) for equal weight because its score is constant. MAE, directional "
                "accuracy and intervals exist only for models that forecast a return (ridge).", ""]
        header = ["Strategy", "CAGR", "Sharpe", "Max drawdown", "Turnover", "Mean window return (net)",
                  "Mean excess vs Nifty 500"]
        rows = [[f"{r.name} (top {r.params['top_k']})" if r.name != "equal_weight" else "equal_weight (all)",
                 _fmt(r.summary.get("bt_cagr", float("nan")), pct=True), _fmt(r.summary.get("bt_sharpe", float("nan")), 2),
                 _fmt(r.summary.get("bt_max_drawdown", float("nan")), pct=True), _fmt(r.summary.get("bt_turnover", float("nan")), pct=True),
                 _fmt(r.summary.get("bt_mean_period_net_return", float("nan")), pct=True),
                 _fmt(r.summary.get("port_excess", float("nan")), pct=True)] for r in subset]
        rows.append(["**Nifty 500 (same windows)**", _fmt(bench_s.get("cagr", float("nan")), pct=True),
                     _fmt(bench_s.get("sharpe", float("nan")), 2), _fmt(bench_s.get("max_drawdown", float("nan")), pct=True),
                     "n/a", _fmt(bench_s.get("mean_period_net_return", float("nan")), pct=True), "0.0%"])
        out += ["### Backtest", "", _table(header, rows), ""]

        out += ["### Per test year", ""]
        years = sorted({b for r in subset for b in r.per_year["budget_id"]})
        header = ["Budget"] + [f"{r.name} IC" for r in subset if r.name != "equal_weight"] + [f"{r.name} net" for r in subset] + ["Nifty 500 net"]
        rows = []
        for y in years:
            row = [y]
            for r in subset:
                if r.name != "equal_weight":
                    row.append(_fmt(float(r.per_year.set_index("budget_id")["ic"].get(y, float("nan")))))
            for r in subset:
                row.append(_fmt(float(r.per_year.set_index("budget_id")["port_net"].get(y, float("nan"))), pct=True))
            bench_row = bench.periods.set_index("budget_id")["net_return"]
            row.append(_fmt(float(bench_row.get(y, float("nan"))), pct=True))
            rows.append(row)
        out += [_table(header, rows), ""]

    sector_runs = {r.name: r for r in runs if r.level == "sector"}
    if not sector_runs:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
        return
    out += ["## Bars every real model must clear", "",
            "From README section 12 (all out-of-sample):", "",
            "- Mean Spearman IC across test years above 0.10: baselines score "
            + ", ".join(f"{n} {_fmt(r.summary.get('ic', float('nan')))}" for n, r in sector_runs.items() if n != "equal_weight") + ".",
            "- Top-3 sector basket Sharpe above Nifty 500, equal weight and last year's winners: "
            f"Nifty 500 {_fmt(bench_s.get('sharpe', float('nan')), 2)}, equal weight "
            f"{_fmt(sector_runs['equal_weight'].summary.get('bt_sharpe', float('nan')), 2)}, last year's winners "
            f"{_fmt(sector_runs['last_years_winners'].summary.get('bt_sharpe', float('nan')), 2)}.",
            "- Stock Precision@5 above 0.55 (baselines in the stock table above).",
            "- 80% interval coverage between 75% and 85% (ridge row above).", ""]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def run(cfg: EvalConfig | None = None, use_mlflow: bool = True, report_dir: Path | None = None,
        levels: tuple[str, ...] = ("sector", "stock")) -> list[ModelRun]:
    cfg = cfg or load_config()
    np.random.seed(cfg.seed)
    reports = report_dir or cfg.root / "reports"
    reports.mkdir(exist_ok=True)
    bundle = build_market_data_bundle(cfg.root)
    sector_panel, stock_panel = load_sector_panel(cfg), load_stock_panel(cfg)
    calendar = budget_calendar(cfg.root, trading_days(cfg.root))
    windows = calendar[["budget_id", "start", "label_end"]]

    market_level = pd.DataFrame({BENCHMARK: (1.0 + bundle.market_returns.fillna(0.0)).cumprod()})
    sector_budgets = sorted(sector_panel.frame["budget_id"].unique())
    bench_sel = {b: [BENCHMARK] for b in sector_budgets}
    bench = run_backtest(bench_sel, windows[windows["budget_id"].isin(bench_sel)], market_level, cfg.round_trip_cost)

    tuner = make_ridge_tuner(cfg.ridge_alpha_grid)
    sector_specs: list[tuple[str, Callable[..., Model], Any]] = [
        ("equal_weight", lambda: EqualWeight(), None),
        ("last_years_winners", lambda: last_years_winners(), None),
        ("biggest_allocation_increase", lambda: biggest_allocation_increase(), None),
        ("ridge", lambda alpha=10.0: RidgeBaseline(alpha=alpha, interval_level=cfg.interval_level), tuner),
    ]
    stock_specs: list[tuple[str, Callable[..., Model], Any]] = [
        ("equal_weight", lambda: EqualWeight(), None),
        ("momentum", lambda: last_years_winners(), None),
        ("ridge", lambda alpha=10.0: RidgeBaseline(alpha=alpha, interval_level=cfg.interval_level), tuner),
    ]
    runs: list[ModelRun] = []
    for name, factory, tune in sector_specs if "sector" in levels else []:
        runs.append(evaluate("sector", name, sector_panel, factory, tune, cfg, windows, bundle, bench))
    if "stock" in levels:
        stock_bench_sel = {b: [BENCHMARK] for b in sorted(stock_panel.frame["budget_id"].unique())}
        stock_bench = run_backtest(stock_bench_sel, windows[windows["budget_id"].isin(stock_bench_sel)], market_level,
                                   cfg.round_trip_cost)
        for name, factory, tune in stock_specs:
            runs.append(evaluate("stock", name, stock_panel, factory, tune, cfg, windows, bundle, stock_bench))

    summary_rows = [{"level": r.level, "model": r.name, **{k: round(v, 8) for k, v in r.summary.items()}} for r in runs]
    pd.DataFrame(summary_rows).to_csv(reports / "baselines_summary.csv", index=False)
    pd.concat([r.per_year.assign(level=r.level, model=r.name) for r in runs]).round(8).to_csv(
        reports / "baselines_per_year.csv", index=False)
    for level in levels:
        pd.concat([r.predictions.assign(model=r.name) for r in runs if r.level == level]).round(8).to_csv(
            reports / f"baselines_predictions_{level}.csv", index=False)
    write_report(runs, bench, cfg, reports / "baselines.md")

    if use_mlflow:
        tracking.configure(cfg.root)
        artifacts = [reports / "baselines_summary.csv", reports / "baselines_per_year.csv", reports / "baselines.md"]
        for r in runs:
            tracking.log_run(f"{r.level}/{r.name}", r.params, r.per_year, r.summary, artifacts)
    return runs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()
    runs = run(use_mlflow=not args.no_mlflow)
    for r in runs:
        print(f"{r.level:>6} {r.name:<28} IC={_fmt(r.summary.get('ic', float('nan')))} "
              f"Sharpe={_fmt(r.summary.get('bt_sharpe', float('nan')), 2)} CAGR={_fmt(r.summary.get('bt_cagr', float('nan')), pct=True)}")


if __name__ == "__main__":
    main()
