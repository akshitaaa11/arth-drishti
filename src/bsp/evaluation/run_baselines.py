"""Run the Phase 4 sector baselines through the walk-forward harness, backtest them and write ``reports/baselines.md``.

``make backtest`` runs ``python -m bsp.evaluation.run_baselines``. Fixed seeds, no timestamps in the outputs:
two runs produce byte-identical CSV and Markdown files (checked in ``tests/test_phase4_evaluation.py``).

Sector level only. IT Services is the control sector (README section 3, rule 11): models are trained on all 15
sectors and predict all 15, but the headline metrics and portfolios use the 14 budget-sensitive sectors, and the
control sector is reported on its own in a separate table.
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
from scipy.stats import rankdata, spearmanr

from bsp.evaluation import metrics, tracking
from bsp.evaluation.backtest import BacktestResult, run_backtest, top_k_selection
from bsp.evaluation.config import EvalConfig, load_config
from bsp.evaluation.data import budget_calendar, load_sector_panel, trading_days
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
MODELS = ["equal_weight", "last_years_winners", "biggest_allocation_increase", "ridge"]
ALARM_P = 0.05  # control-sector alarm: model score vs realised excess return, one-sided p below this


@dataclass
class ModelRun:
    name: str
    predictions: pd.DataFrame  # all 15 sectors, including the control
    per_year: pd.DataFrame  # headline metrics on the budget-sensitive sectors, per test budget
    summary: dict[str, float]
    backtest: BacktestResult
    control: pd.DataFrame  # the control sector's rows: predicted rank vs realised rank, per test budget
    params: dict[str, Any]


def _nanmean(values: pd.Series) -> float:
    values = values.dropna()
    return float(values.mean()) if len(values) else float("nan")


def _cross_section_metrics(group: pd.DataFrame) -> dict[str, float]:
    score, actual = group["score"].to_numpy(), group["actual"].to_numpy()
    out = {
        "ic": metrics.spearman_ic(score, actual),
        "top3_hit": metrics.top_k_hit_rate(score, actual, 3),
        "precision5": metrics.precision_at_k(score, actual, 5),
        "ndcg10": metrics.ndcg_at_k(score, actual, 10),
    }
    if "expected" in group:
        out["mae"] = metrics.mae(group["expected"].to_numpy(), actual)
        out["directional"] = metrics.directional_accuracy(group["expected"].to_numpy(), actual)
    if "lo" in group:
        out["coverage"] = metrics.interval_coverage(group["lo"].to_numpy(), group["hi"].to_numpy(), actual)
        out["width"] = metrics.interval_width(group["lo"].to_numpy(), group["hi"].to_numpy())
    return out


def _control_rows(predictions: pd.DataFrame) -> pd.DataFrame:
    """Where the control sector landed each year: its predicted rank and its realised rank among all 15 sectors."""
    rows = []
    for budget_id, group in predictions.groupby("budget_id"):
        control = group[group["is_control"]]
        if control.empty or group["actual"].isna().all():
            continue
        score_rank = rankdata(-group["score"].to_numpy(), method="average")
        actual_rank = rankdata(-group["actual"].fillna(group["actual"].min()).to_numpy(), method="average")
        i = int(np.flatnonzero(group["is_control"].to_numpy())[0])
        rows.append({"budget_id": budget_id, "entity": group["entity"].iloc[i], "score": group["score"].iloc[i],
                     "actual": group["actual"].iloc[i], "predicted_rank": score_rank[i], "actual_rank": actual_rank[i],
                     "n_sectors": len(group), "in_predicted_top3": bool(score_rank[i] <= 3)})
    return pd.DataFrame(rows)


def evaluate(name: str, make_model: Callable[..., Model], tune: Any, cfg: EvalConfig, panel: Any,
             windows: pd.DataFrame, bundle: MarketDataBundle, bench: BacktestResult) -> ModelRun:
    folds = walk_forward(panel, make_model, cfg, tune)
    predictions = stack_predictions(folds)
    headline = predictions[~predictions["is_control"]]
    per_year = pd.DataFrame([{"budget_id": b, **_cross_section_metrics(g)} for b, g in headline.groupby("budget_id")])
    selects_all = bool(make_model(**folds[0].params).selects_all)
    selections = top_k_selection(headline, cfg.top_k_sectors, selects_all)
    levels = (1.0 + bundle.sector_returns.fillna(0.0)).cumprod()
    backtest = run_backtest(selections, windows[windows["budget_id"].isin(selections)], levels, cfg.round_trip_cost)
    per_year = per_year.merge(backtest.periods[["budget_id", "net_return"]].rename(columns={"net_return": "port_net"}),
                              on="budget_id", how="left")
    per_year["bench_net"] = per_year["budget_id"].map(bench.periods.set_index("budget_id")["net_return"])
    per_year["port_excess"] = per_year["port_net"] - per_year["bench_net"]
    summary = {col: _nanmean(per_year[col]) for col in per_year.columns if col != "budget_id"}
    summary["ic_positive_share"] = (float((per_year["ic"].dropna() > 0).mean())
                                    if per_year["ic"].notna().any() else float("nan"))
    summary.update({f"bt_{key}": value for key, value in backtest.summary.items()})
    params = {"level": "sector", "model": name, "top_k": cfg.top_k_sectors, "round_trip_cost": cfg.round_trip_cost,
              "seed": cfg.seed, "n_folds": len(folds), "first_test": folds[0].budget_id, "last_test": folds[-1].budget_id,
              "holdout_locked": not cfg.holdout_unlocked, "control_excluded_from_headline": True,
              "tuned_alphas": [f.params.get("alpha") for f in folds]}
    return ModelRun(name, predictions, per_year, summary, backtest, _control_rows(predictions), params)


def control_summary(run: ModelRun) -> dict[str, float]:
    """Does this model 'find' a budget effect in the control sector? Spearman of its score vs the realised return."""
    c = run.control
    out = {"mean_predicted_rank": float(c["predicted_rank"].mean()), "mean_actual_rank": float(c["actual_rank"].mean()),
           "years_in_predicted_top3": float(c["in_predicted_top3"].sum()), "n_years": float(len(c)),
           "rho": float("nan"), "p_one_sided": float("nan")}
    if c["score"].nunique() > 1 and len(c) >= 4:
        result = spearmanr(c["score"], c["actual"])
        rho = float(result.statistic)
        p_two = float(result.pvalue)
        out["rho"] = rho
        out["p_one_sided"] = p_two / 2 if rho > 0 else 1 - p_two / 2
    return out


def _fmt(value: float | None, digits: int = 3, pct: bool = False) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value * 100:.1f}%" if pct else f"{value:.{digits}f}"


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def write_report(runs: list[ModelRun], bench: BacktestResult, cfg: EvalConfig, path: Path) -> None:
    by_name = {r.name: r for r in runs}
    bench_by_year = bench.periods.set_index("budget_id")["net_return"]
    years = sorted({b for r in runs for b in r.per_year["budget_id"]})
    out = ["# Phase 4 baselines (sector level)", "",
           "Generated by `make backtest` (`src/bsp/evaluation/run_baselines.py`). Every number is out-of-sample: "
           "expanding-window walk-forward, and a budget is predicted only from rows whose 12m label was already known "
           "on its day 0. Nothing here is investment advice.", "",
           "## Setup", "",
           f"- Test budgets: the {len(years)} full budgets from FY{cfg.first_test_fiscal_year} to {years[-1]}; interim "
           "budgets have no sector budget data and are not predicted. Training grows every year (rows from year t or "
           f"later are never used; minimum {cfg.min_train_budgets} training budgets; rows with `target_complete = False` "
           "are excluded from training).",
           f"- **Locked hold-out: FY{', FY'.join(cfg.holdout_fiscal_years)} (with their interim budgets); sealed live year: "
           f"FY{', FY'.join(cfg.live_fiscal_years)}.** The evaluation panel does not load them, and asking for them "
           "raises `HoldoutLockedError` until Phase 9 sets `holdout_unlocked` in `config/evaluation.json`.",
           "- Target: 12m excess return of the sector basket over the Nifty 500 (day after the budget to the next budget's day 0).",
           "- **IT Services is the control sector.** Models train on and predict all 15 sectors, but every headline "
           "number below uses the 14 budget-sensitive sectors; the control is reported on its own in the last section.",
           f"- Portfolios: equal weight, top {cfg.top_k_sectors} of the 14 sectors (equal weight = all 14), bought at the close "
           f"of the day after the budget and sold at the target window's end; {cfg.round_trip_cost * 100:.1f}% round-trip "
           "cost per window (0.1% each side); cash earns 0% between windows; Sharpe uses risk-free = 0 over the whole span "
           "including cash days. The Nifty 500 benchmark is bought and sold over the same windows with the same costs.",
           f"- Seed {cfg.seed}; two runs give byte-identical files.",
           "- Limitations: 12 test years, so every statistic is noisy; sector baskets are equal-weight baskets of today's "
           "stock list (survivorship, small/mid-cap tilt), so every basket tends to beat the cap-weighted Nifty 500 and the "
           "fair bar for a model is the **equal-weight** row; baskets are thin in early years (defence has 2 stocks until "
           "2017, railways 1 until 2018; `reports/sector_basket_report.csv`). Stock-level evaluation is deferred until the "
           "Nifty 500 point-in-time history is complete (`reports/data_gaps.md`).", ""]

    out += ["## Results across the 12 test years (14 budget-sensitive sectors)", ""]
    header = ["Model", "Mean IC", "IC>0 years", "Top-3 hit", "Precision@5", "NDCG@10", "MAE", "Directional",
              "80% coverage", "Interval width"]
    rows = []
    for r in runs:
        s = r.summary
        nan = float("nan")
        rows.append([r.name, _fmt(s.get("ic", nan)), _fmt(s.get("ic_positive_share", nan), pct=True),
                     _fmt(s.get("top3_hit", nan), pct=True), _fmt(s.get("precision5", nan)), _fmt(s.get("ndcg10", nan)),
                     _fmt(s.get("mae", nan)), _fmt(s.get("directional", nan), pct=True),
                     _fmt(s.get("coverage", nan), pct=True), _fmt(s.get("width", nan))])
    out += [_table(header, rows), "",
            f"Chance for the top-3 hit rate is 3/14 = {3 / 14 * 100:.1f}%. IC, hit rate and NDCG are n/a for equal weight "
            "(constant score). MAE, directional accuracy and intervals exist only for ridge, the one model that forecasts "
            "a return.", ""]

    out += ["## Backtest: top-3 sector portfolios", ""]
    header = ["Strategy", "CAGR", "Sharpe", "Max drawdown", "Turnover", "Mean window return (net)", "Mean excess vs Nifty 500"]
    nan = float("nan")
    rows = [[("equal_weight (all 14)" if r.name == "equal_weight" else f"{r.name} (top {cfg.top_k_sectors})"),
             _fmt(r.summary.get("bt_cagr", nan), pct=True), _fmt(r.summary.get("bt_sharpe", nan), 2),
             _fmt(r.summary.get("bt_max_drawdown", nan), pct=True), _fmt(r.summary.get("bt_turnover", nan), pct=True),
             _fmt(r.summary.get("bt_mean_period_net_return", nan), pct=True), _fmt(r.summary.get("port_excess", nan), pct=True)]
            for r in runs]
    b = bench.summary
    rows.append(["**Nifty 500 (same windows)**", _fmt(b.get("cagr", nan), pct=True), _fmt(b.get("sharpe", nan), 2),
                 _fmt(b.get("max_drawdown", nan), pct=True), "n/a", _fmt(b.get("mean_period_net_return", nan), pct=True), "0.0%"])
    out += [_table(header, rows), "",
            "Turnover is the average share of the portfolio replaced between consecutive windows.", ""]

    scored = [r for r in runs if r.name != "equal_weight"]
    out += ["## Per test year", "", "### Spearman IC (14 sectors)", "",
            _table(["Budget"] + [r.name for r in scored],
                   [[y] + [_fmt(float(r.per_year.set_index("budget_id")["ic"].get(y, nan))) for r in scored] for y in years]), "",
            "### Top-3 hit rate", "",
            _table(["Budget"] + [r.name for r in scored],
                   [[y] + [_fmt(float(r.per_year.set_index("budget_id")["top3_hit"].get(y, nan)), pct=True) for r in scored]
                    for y in years]), "",
            "### Net return of each strategy's portfolio over the window", "",
            _table(["Budget"] + [r.name for r in runs] + ["Nifty 500"],
                   [[y] + [_fmt(float(r.per_year.set_index("budget_id")["port_net"].get(y, nan)), pct=True) for r in runs]
                    + [_fmt(float(bench_by_year.get(y, nan)), pct=True)] for y in years]), ""]

    out += ["## Bars every real model must clear (README section 12)", ""]
    ics = {r.name: r.summary.get("ic", nan) for r in scored}
    best_name = max(ics, key=lambda k: ics[k] if not math.isnan(ics[k]) else -9)
    best_ic = ics[best_name]
    sharpe = {r.name: r.summary.get("bt_sharpe", nan) for r in runs}
    out += [f"- Mean IC above 0.10: {', '.join(f'{n} {_fmt(v)}' for n, v in ics.items())}. "
            + ("**Null result: no baseline clears 0.10**; the best, " + f"{best_name}, scores {_fmt(best_ic)}."
               if best_ic < 0.10 else f"{best_name} clears it with {_fmt(best_ic)}."),
            f"- Top-3 Sharpe to beat: Nifty 500 {_fmt(b.get('sharpe', nan), 2)}, equal weight {_fmt(sharpe['equal_weight'], 2)}, "
            f"last year's winners {_fmt(sharpe['last_years_winners'], 2)}.",
            "- 80% interval coverage between 75% and 85%: ridge "
            f"{_fmt(by_name['ridge'].summary.get('coverage', nan), pct=True)}.", ""]
    beaten = [n for n in ("biggest_allocation_increase", "ridge") if sharpe[n] <= sharpe["equal_weight"]]
    if beaten:
        out += [f"- **Null result on the budget signal:** {', '.join(beaten)} did not beat the equal-weight Sharpe "
                f"({_fmt(sharpe['equal_weight'], 2)}). With 12 test years this is weak evidence either way.", ""]

    out += ["## IT Services (control sector), reported separately", "",
            "The control sector is not meant to respond to the budget. Per README rule 11, a strong 'budget effect' here is "
            f"treated as a **leakage alarm**, not a discovery. The alarm rule used: a model's score for the control sector "
            f"correlates positively with its realised excess return across the test years with one-sided p < {ALARM_P}.", ""]
    header = ["Model", "Mean predicted rank (of 15)", "Mean realised rank (of 15)", "Years in predicted top 3", "Spearman rho",
              "p (one-sided)", "Alarm"]
    rows, alarm_any = [], False
    for r in scored:
        c = control_summary(r)
        alarm = (not math.isnan(c["p_one_sided"])) and c["p_one_sided"] < ALARM_P and c["rho"] > 0
        alarm_any = alarm_any or alarm
        rows.append([r.name, _fmt(c["mean_predicted_rank"], 1), _fmt(c["mean_actual_rank"], 1),
                     f"{int(c['years_in_predicted_top3'])} of {int(c['n_years'])}", _fmt(c["rho"]), _fmt(c["p_one_sided"]),
                     "**ALARM**" if alarm else "no"])
    out += [_table(header, rows), "",
            ("**Leakage alarm raised** - investigate before trusting any result." if alarm_any else
             "No model finds a significant budget effect in the control sector, so there is no leakage alarm from this check."),
            "", "Control sector, per test year (realised excess return over the Nifty 500 and where each model ranked it):", ""]
    ctrl = {r.name: r.control.set_index("budget_id") for r in scored}
    first = next(iter(ctrl.values()))
    header = ["Budget", "Realised excess", "Realised rank"] + [f"{n} rank" for n in ctrl]
    rows = [[y, _fmt(float(first["actual"].get(y, nan)), pct=True), _fmt(float(first["actual_rank"].get(y, nan)), 1)]
            + [_fmt(float(c["predicted_rank"].get(y, nan)), 1) for c in ctrl.values()] for y in years]
    out += [_table(header, rows), ""]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def run(cfg: EvalConfig | None = None, use_mlflow: bool = True, report_dir: Path | None = None) -> list[ModelRun]:
    cfg = cfg or load_config()
    np.random.seed(cfg.seed)
    reports = report_dir or cfg.root / "reports"
    reports.mkdir(exist_ok=True)
    bundle = build_market_data_bundle(cfg.root)
    panel = load_sector_panel(cfg)
    calendar = budget_calendar(cfg.root, trading_days(cfg.root))
    windows = calendar[["budget_id", "start", "label_end"]]

    market_level = pd.DataFrame({BENCHMARK: (1.0 + bundle.market_returns.fillna(0.0)).cumprod()})
    budgets = sorted(panel.frame["budget_id"].unique())
    bench = run_backtest({b: [BENCHMARK] for b in budgets}, windows[windows["budget_id"].isin(budgets)], market_level,
                         cfg.round_trip_cost)

    tuner = make_ridge_tuner(cfg.ridge_alpha_grid)
    specs: list[tuple[str, Callable[..., Model], Any]] = [
        ("equal_weight", lambda: EqualWeight(), None),
        ("last_years_winners", lambda: last_years_winners(), None),
        ("biggest_allocation_increase", lambda: biggest_allocation_increase(), None),
        ("ridge", lambda alpha=10.0: RidgeBaseline(alpha=alpha, interval_level=cfg.interval_level), tuner),
    ]
    runs = [evaluate(name, factory, tune, cfg, panel, windows, bundle, bench) for name, factory, tune in specs]

    summary_rows = [{"model": r.name, **{k: round(v, 8) for k, v in r.summary.items()}} for r in runs]
    pd.DataFrame(summary_rows).to_csv(reports / "baselines_summary.csv", index=False)
    pd.concat([r.per_year.assign(model=r.name) for r in runs]).round(8).to_csv(reports / "baselines_per_year.csv", index=False)
    pd.concat([r.predictions.assign(model=r.name) for r in runs]).round(8).to_csv(
        reports / "baselines_predictions_sector.csv", index=False)
    pd.concat([r.control.assign(model=r.name) for r in runs if r.name != "equal_weight"]).round(8).to_csv(
        reports / "baselines_control_sector.csv", index=False)
    write_report(runs, bench, cfg, reports / "baselines.md")

    if use_mlflow:
        kind, uri = tracking.configure(cfg.root)
        print(f"MLflow store: {kind} ({uri})")
        artifacts = [reports / "baselines_summary.csv", reports / "baselines_per_year.csv", reports / "baselines.md"]
        for r in runs:
            tracking.log_run(f"sector/{r.name}", {**r.params, "mlflow_store": kind}, r.per_year, r.summary, artifacts)
    return runs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()
    for r in run(use_mlflow=not args.no_mlflow):
        print(f"{r.name:<28} IC={_fmt(r.summary.get('ic', float('nan')))} "
              f"Sharpe={_fmt(r.summary.get('bt_sharpe', float('nan')), 2)} CAGR={_fmt(r.summary.get('bt_cagr', float('nan')), pct=True)}")


if __name__ == "__main__":
    main()
