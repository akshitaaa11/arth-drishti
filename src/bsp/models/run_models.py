"""Phase 5: Tier-1 sector models, the Tier-2 stock ranker, their walk-forward evaluation and ``reports/models.md``.

``make train`` runs ``python -m bsp.models.run_models``. Same harness, same hold-out lock and same metrics as Phase 4
(``bsp.evaluation``), so every model is compared with the Phase 4 baselines on identical folds.

Sector level (Tier 1): LightGBM LambdaRank ranker (Optuna-tuned inside every fold), Bayesian hierarchical regression
(PyMC), and an equal-weight rank blend of the two. Stock level (Tier 2): one LightGBM LambdaRank ranker whose query groups
are budget x sector, on the stock features plus the out-of-sample Tier-1 output of the stock's sector.
IT Services is the control sector at both levels and is reported separately.
Not built, and why: see the "Not built" section the report writes (company fundamentals / order wins, LSTM).
"""

from __future__ import annotations

import argparse
import math
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

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
from bsp.evaluation.run_baselines import (
    ALARM_P,
    BENCHMARK,
    ModelRun,
    _fmt,
    _nanmean,
    _table,
    control_summary,
    evaluate_predictions,
)
from bsp.evaluation.run_baselines import run as run_baselines
from bsp.evaluation.walk_forward import FoldResult, Model, stack_predictions, walk_forward
from bsp.features.baskets import MarketDataBundle, build_market_data_bundle
from bsp.models.baselines import EqualWeight, RidgeBaseline, SingleFeatureRank, make_ridge_tuner
from bsp.models.bayes import BayesHierarchical
from bsp.models.ensemble import SectorThenMomentum, blend_predictions, learned_stack, tier1_features
from bsp.models.ranker import LGBMRankerModel, make_ranker_tuner

N_TRIALS = 15
SECTOR_MODELS = ["lgbm_ranker", "bayes_hier", "tier1_blend", "tier1_stack"]
NAN = float("nan")


@dataclass
class StockRun:
    name: str
    predictions: pd.DataFrame
    per_year: pd.DataFrame
    summary: dict[str, float]
    backtest: BacktestResult
    params: dict[str, Any]
    folds: list[FoldResult] | None = None  # the walk-forward folds with their fitted models (Phase 7 explains them)
    rerun: Callable[[pd.DataFrame], list[FoldResult]] | None = None  # walk-forward again on a modified copy of the panel


# ------------------------------------------------------------------------------------------------ sector level
def _brier(p: np.ndarray, actual: np.ndarray) -> float:
    ok = ~np.isnan(p) & ~np.isnan(actual)
    return float(np.mean((p[ok] - (actual[ok] > 0)) ** 2)) if ok.any() else NAN


def add_brier(run: ModelRun) -> None:
    """P(beat Nifty 500) scored with the Brier score; the always-0.5 forecast scores 0.25."""
    headline = run.predictions[~run.predictions["is_control"]]
    if "p_beat" not in headline:
        return
    by_year = {b: _brier(g["p_beat"].to_numpy(), g["actual"].to_numpy()) for b, g in headline.groupby("budget_id")}
    run.per_year["brier"] = run.per_year["budget_id"].map(by_year)
    run.summary["brier"] = _nanmean(run.per_year["brier"])


def run_sector_models(cfg: EvalConfig, panel: Panel, windows: pd.DataFrame, bundle: MarketDataBundle,
                      bench: BacktestResult) -> tuple[dict[str, ModelRun], dict[str, list[FoldResult]], pd.DataFrame]:
    folds: dict[str, list[FoldResult]] = {}
    folds["lgbm_ranker"] = walk_forward(
        panel, lambda **p: LGBMRankerModel(seed=cfg.seed, interval_level=cfg.interval_level, **p), cfg,
        make_ranker_tuner(n_trials=N_TRIALS, seed=cfg.seed))
    bayes_models: list[BayesHierarchical] = []

    def make_bayes() -> Model:
        model = BayesHierarchical(seed=cfg.seed, interval_level=cfg.interval_level)
        bayes_models.append(model)
        return model

    folds["bayes_hier"] = walk_forward(panel, make_bayes, cfg)
    for fold, model in zip(folds["bayes_hier"], bayes_models, strict=False):
        fold.params = dict(model.diagnostics)
    predictions = {name: stack_predictions(f) for name, f in folds.items()}
    two = {k: predictions[k] for k in ("lgbm_ranker", "bayes_hier")}
    predictions["tier1_blend"] = blend_predictions(two)
    budget_meta = panel.frame.drop_duplicates("budget_id")[["budget_id", "presented_on", "day0", "label_end"]]
    predictions["tier1_stack"], stack_weights = learned_stack(two, budget_meta)
    runs: dict[str, ModelRun] = {}
    for name in SECTOR_MODELS:
        params = {"level": "sector", "model": name, "top_k": cfg.top_k_sectors, "round_trip_cost": cfg.round_trip_cost,
                  "seed": cfg.seed, "optuna_trials": N_TRIALS, "holdout_locked": not cfg.holdout_unlocked,
                  "n_folds": predictions[name]["budget_id"].nunique()}
        runs[name] = evaluate_predictions(name, predictions[name], False, params, cfg, windows, bundle, bench)
        add_brier(runs[name])
    return runs, folds, stack_weights


# ------------------------------------------------------------------------------------------------- stock level
def _stock_metrics(group: pd.DataFrame, k: int) -> dict[str, float]:
    score, actual = group["score"].to_numpy(), group["actual"].to_numpy()
    within = []
    for _, g in group.groupby("sector_id"):
        if len(g) >= 5:
            ic = metrics.spearman_ic(g["score"].to_numpy(), g["actual"].to_numpy())
            if not math.isnan(ic):
                within.append(ic)
    top = group.sort_values(["score", "entity"], ascending=[False, True]).head(k)
    return {"ic": metrics.spearman_ic(score, actual), "within_sector_ic": float(np.mean(within)) if within else NAN,
            "topk_hit": metrics.top_k_hit_rate(score, actual, k),
            "topk_excess": float(top["actual"].mean() - group["actual"].mean()), "n_stocks": float(len(group))}


def evaluate_stock(name: str, folds: list[FoldResult], selects_all: bool, cfg: EvalConfig, windows: pd.DataFrame,
                   bundle: MarketDataBundle, bench: BacktestResult, params: dict[str, Any],
                   rerun: Callable[[pd.DataFrame], list[FoldResult]] | None = None) -> StockRun:
    predictions = stack_predictions(folds)
    headline = predictions[~predictions["is_control"]]
    per_year = pd.DataFrame([{"budget_id": b, **_stock_metrics(g, cfg.top_k_stocks)} for b, g in headline.groupby("budget_id")])
    selections = top_k_selection(headline, cfg.top_k_stocks, selects_all)
    levels = (1.0 + bundle.stock_returns.fillna(0.0)).cumprod()
    backtest = run_backtest(selections, windows[windows["budget_id"].isin(selections)], levels, cfg.round_trip_cost)
    per_year = per_year.merge(backtest.periods[["budget_id", "net_return"]].rename(columns={"net_return": "port_net"}),
                              on="budget_id", how="left")
    per_year["bench_net"] = per_year["budget_id"].map(bench.periods.set_index("budget_id")["net_return"])
    per_year["port_excess"] = per_year["port_net"] - per_year["bench_net"]
    summary = {c: _nanmean(per_year[c]) for c in per_year.columns if c != "budget_id"}
    summary["ic_positive_share"] = float((per_year["ic"].dropna() > 0).mean()) if per_year["ic"].notna().any() else NAN
    summary.update({f"bt_{k}": v for k, v in backtest.summary.items()})
    return StockRun(name, predictions, per_year, summary, backtest, params, folds, rerun)


def stock_control(run: StockRun) -> dict[str, float]:
    """Does the model 'find' a budget effect among the control sector's stocks? Pooled Spearman, one-sided p."""
    c = run.predictions[run.predictions["is_control"]].dropna(subset=["actual"])
    out = {"n": float(len(c)), "rho": NAN, "p_one_sided": NAN}
    if len(c) >= 10 and c["score"].nunique() > 1:
        result = spearmanr(c["score"], c["actual"])
        rho, p_two = float(result.statistic), float(result.pvalue)
        out.update({"rho": rho, "p_one_sided": p_two / 2 if rho > 0 else 1 - p_two / 2})
    return out


def run_stock_models(cfg: EvalConfig, tier1: pd.DataFrame, windows: pd.DataFrame, bundle: MarketDataBundle,
                     bench: BacktestResult) -> tuple[dict[str, StockRun], Panel]:
    from bsp.evaluation.data import STOCK_FEATURES

    panel = load_stock_panel(cfg, tier1)
    base_panel = Panel(panel.kind, panel.frame, [c for c in STOCK_FEATURES if c in panel.frame.columns])
    specs: list[tuple[str, Panel, Callable[..., Model], Any, bool]] = [
        ("equal_weight", base_panel, lambda: EqualWeight(), None, True),
        ("momentum_12m", base_panel, lambda: SingleFeatureRank("momentum_12m"), None, False),
        ("ridge", base_panel, lambda alpha=10.0: RidgeBaseline(alpha=alpha, interval_level=cfg.interval_level),
         make_ridge_tuner(cfg.ridge_alpha_grid), False),
        ("sector_then_momentum", panel, lambda: SectorThenMomentum(), None, False),
        ("tier2_ranker", panel, lambda **p: LGBMRankerModel(("budget_id", "sector_id"), cfg.seed, True, cfg.interval_level, **p),
         make_ranker_tuner(("budget_id", "sector_id"), N_TRIALS, cfg.seed), False),
    ]
    runs: dict[str, StockRun] = {}
    for name, pnl, factory, tune, selects_all in specs:
        folds = walk_forward(pnl, factory, cfg, tune)
        params = {"level": "stock", "model": name, "top_k": cfg.top_k_stocks, "round_trip_cost": cfg.round_trip_cost,
                  "seed": cfg.seed, "n_folds": len(folds), "first_test": folds[0].budget_id, "last_test": folds[-1].budget_id,
                  "holdout_locked": not cfg.holdout_unlocked, "features": ",".join(pnl.features)}
        def rerun(frame: pd.DataFrame, pnl: Panel = pnl, factory: Callable[..., Model] = factory, tune: Any = tune) -> list[FoldResult]:
            return walk_forward(Panel(pnl.kind, frame, pnl.features), factory, cfg, tune)

        runs[name] = evaluate_stock(name, folds, selects_all, cfg, windows, bundle, bench, params, rerun)
    return runs, panel


def _label_scramble_check(run: StockRun, frame: pd.DataFrame, seed: int, from_fy: str = "2021-22") -> bool:
    """Scramble the 12m labels of every row from ``from_fy`` on and refit: predictions for budgets before that fiscal year
    must not move at all. If a model used a label from its own or a later year, they would."""
    if run.rerun is None:
        return False
    scrambled = frame.copy()
    late = scrambled["fiscal_year"].astype(str) >= from_fy
    rng = np.random.default_rng(seed)
    scrambled.loc[late, "excess_return"] = rng.permutation(scrambled.loc[late, "excess_return"].to_numpy())
    again = stack_predictions(run.rerun(scrambled))
    before = run.predictions.merge(again, on=["budget_id", "entity"], suffixes=("", "_again"))
    early_budgets = set(frame.loc[~late, "budget_id"])
    before = before[before["budget_id"].isin(early_budgets)]
    return bool(len(before) > 0 and np.allclose(before["score"], before["score_again"], equal_nan=True))


def stock_control_investigation(stock: dict[str, StockRun], stock_panel: Panel, seed: int = 42) -> tuple[list[str], bool]:
    """Investigate every stock-level control alarm (README Phase 5 exit criterion) and say whether it is explained.

    Mechanism checks (a leak would fail these): (1) every stock feature row is dated on or before its budget; (2) scrambling the
    labels of the later fiscal years leaves every earlier prediction unchanged, so no model used a label from its own year or later.
    Statistics: the pooled alarm counts the same stocks in several years as independent, so it is repeated with one IC per test
    year (the independent unit) and a one-sided t-test over years; a placebo over the non-control sectors is shown as context.
    An alarm is *explained* if both mechanism checks pass and the per-year test is not significant; otherwise it is not.
    Returns (markdown lines, all alarms explained).
    """
    from scipy.stats import ttest_1samp

    frame = stock_panel.frame
    dated_ok = bool((frame["as_of_date"].astype(str) <= frame["presented_on"].astype(str)).all())
    out = [f"- Check 1, dates: every stock feature row has `as_of_date` <= its budget date: **{'yes' if dated_ok else 'NO'}** "
           f"({len(frame)} rows). The stock features are price-based only (momentum, volatility, liquidity, beta, size) and the Tier-1 "
           "inputs are out-of-sample, so the control sector's budget allocation never enters a stock model."]
    all_explained = dated_ok
    alarmed = []
    for name, run in stock.items():
        if name == "equal_weight":
            continue
        c = stock_control(run)
        if (not math.isnan(c["p_one_sided"])) and c["p_one_sided"] < ALARM_P and c["rho"] > 0:
            alarmed.append((name, run, c))
    if not alarmed:
        return out + ["- No model raised a stock-level control alarm, so there is nothing to investigate."], all_explained
    for name, run, c in alarmed:
        preds = run.predictions.dropna(subset=["actual"])
        it = preds[preds["is_control"]]
        yearly = [metrics.spearman_ic(g["score"].to_numpy(), g["actual"].to_numpy()) for _, g in it.groupby("budget_id") if len(g) >= 4]
        yearly = [v for v in yearly if not math.isnan(v)]
        t_p = float(ttest_1samp(yearly, 0.0, alternative="greater").pvalue) if len(yearly) >= 4 else NAN
        placebo = []
        for _, g in preds[~preds["is_control"]].groupby("sector_id"):
            if len(g) >= 10 and g["score"].nunique() > 1:
                placebo.append(float(spearmanr(g["score"], g["actual"]).statistic))
        outlier_share = float(np.mean([r >= c["rho"] for r in placebo])) if placebo else NAN
        scramble_ok = _label_scramble_check(run, frame, seed)
        significant_by_year = (not math.isnan(t_p)) and t_p < ALARM_P
        explained = dated_ok and scramble_ok and not significant_by_year
        all_explained = all_explained and explained
        out.append(
            f"- `{name}` (pooled rho {_fmt(c['rho'])}, p {_fmt(c['p_one_sided'])}). Check 2, label scramble: earlier predictions "
            f"unchanged when later labels are scrambled: **{'yes' if scramble_ok else 'NO'}**. Independent per-year test: mean IC of "
            f"the control stocks {_fmt(float(np.mean(yearly)) if yearly else NAN)} over {len(yearly)} years, one-sided t-test p = {_fmt(t_p)}. "
            f"Context: {_fmt(outlier_share, pct=True)} of the {len(placebo)} budget-sensitive sectors have a pooled rho at least as "
            f"large (median {_fmt(float(np.median(placebo)) if placebo else NAN)}). "
            + ("**Explained, not leakage evidence:** no label or date leak path exists, and the effect is not significant once each year counts "
               "once; the pooled alarm is most likely stocks that stayed winners or losers across years (a "
               "hypothesis, not tested here) on a survivorship-biased list."
               if explained else "**NOT explained: investigate before moving on.**"))
    return out, all_explained


# ------------------------------------------------------------------------------------------------- report
def _sector_row(r: ModelRun) -> list[str]:
    s = r.summary
    return [r.name, _fmt(s.get("ic", NAN)), _fmt(s.get("ic_positive_share", NAN), pct=True), _fmt(s.get("top3_hit", NAN), pct=True),
            _fmt(s.get("ndcg10", NAN)), _fmt(s.get("mae", NAN)), _fmt(s.get("directional", NAN), pct=True),
            _fmt(s.get("coverage", NAN), pct=True), _fmt(s.get("brier", NAN)),
            _fmt(s.get("bt_sharpe", NAN), 2), _fmt(s.get("bt_cagr", NAN), pct=True), _fmt(s.get("port_excess", NAN), pct=True)]


def write_models_report(base: dict[str, ModelRun], sector: dict[str, ModelRun], sector_folds: dict[str, list[FoldResult]],
                        stock: dict[str, StockRun], bench: BacktestResult, cfg: EvalConfig, path: Path,
                        slopes: pd.DataFrame, stock_bench: BacktestResult,
                        investigation: tuple[list[str], bool], stack_weights: pd.DataFrame) -> None:
    allruns = {**base, **sector}
    years = sorted(sector["lgbm_ranker"].per_year["budget_id"])
    out = ["# Phase 5 models (Tier 1 sector, Tier 2 stock)", "",
           "Generated by `make train` (`src/bsp/models/run_models.py`). Same walk-forward harness, hold-out lock, metrics and "
           "costs as `reports/baselines.md`; every number is out-of-sample. Nothing here is investment advice.", "",
           "## Setup", "",
           f"- Test budgets: {len(years)} full budgets, {years[0]} to {years[-1]}. A training row needs fiscal year < t, "
           "`label_end <= day 0` of t and a complete target. Optuna tuning and every inner validation fold use training rows only "
           "(inner expanding walk-forward). Locked hold-out "
           f"FY{', FY'.join(cfg.holdout_fiscal_years)} and sealed live FY{', FY'.join(cfg.live_fiscal_years)} were not loaded.",
           "- **Tier 1, `lgbm_ranker`:** LightGBM LambdaRank (shallow trees, depth <= 3), relevance = quintile grade of the 12m "
           f"excess return within each budget, Optuna TPE with {N_TRIALS} seeded trials per fold maximising the inner walk-forward IC "
           "(the untuned defaults are always trial 0). Missing values are left to LightGBM's native NaN handling; no row is dropped. "
           "Expected excess return comes from a companion shallow LightGBM regressor; `P(beat Nifty 500)` = Phi(expected / sigma), "
           "sigma and the 80% interval from inner out-of-fold residuals (a normal approximation, not a calibrated probability).",
           "- **Tier 1, `bayes_hier`:** PyMC hierarchical regression, sector-specific partially pooled slopes on the budget surprise "
           "(`alloc_vs_prev_re_pct`), partially pooled intercepts, pooled slopes on 12m momentum and execution credibility. NUTS, "
           "2 chains x 500 draws, seeded. Predictions are posterior predictive: mean, 80% credible interval, P(excess > 0). "
           "A missing predictor is the training median (0 after standardising).",
           "- **Tier 1, `tier1_blend`:** equal-weight mean of the two models' within-budget rank percentiles (and of their forecasts). "
           "This pre-specified blend is the Tier-1 output that feeds the Tier-2 ranker.",
           "- **Tier 1, `tier1_stack`:** the stacked ensemble. Same two models, but the weight on the LightGBM ranker (grid 0, .25, .5, .75, 1) "
           "is learned for each test budget from the earlier out-of-sample folds whose 12m label was already resolved on its day 0 "
           "(highest mean IC; 0.5 until three such folds exist). Weights per budget: `reports/models_stack_weights.csv`.",
           "- **Tier 2, `tier2_ranker`:** one LightGBM LambdaRank model for all stocks with query groups budget x sector (so it "
           "learns to rank inside a sector), features = the 11 stock features + the sector's out-of-sample Tier-1 blend output "
           "(`t1_rank_score`, `t1_expected`, `t1_p_beat`). Stocks are the listing-date plus liquidity universe (average daily traded "
           "value >= Rs 5 cr). Tier-1 output exists only from the first test budget, so stock training starts there and the first "
           f"stock test budget is {min(r.predictions['budget_id'].min() for r in stock.values())}. **Survivorship bias is not removed** "
           "(today's 116 symbols, no delisted names): stock results are biased upward and must be read with that in mind.",
           f"- Portfolios: top {cfg.top_k_sectors} sectors / top {cfg.top_k_stocks} stocks, equal weight, 0.2% round trip, same windows "
           "and benchmark charging as Phase 4. IT Services is the control sector: headline numbers use the 14 budget-sensitive "
           "sectors (and the stocks in them).", "",
           "## Tier 1: sector results (12 test years, 14 budget-sensitive sectors)", ""]
    header = ["Model", "Mean IC", "IC>0 years", "Top-3 hit", "NDCG@10", "MAE", "Directional", "80% coverage", "Brier (P beat)",
              "Sharpe", "CAGR", "Excess vs Nifty 500"]
    rows = [_sector_row(allruns[n]) for n in ("equal_weight", "last_years_winners", "biggest_allocation_increase", "ridge",
                                            *SECTOR_MODELS)]
    b = bench.summary
    rows.append(["**Nifty 500**", "", "", "", "", "", "", "", "", _fmt(b.get("sharpe", NAN), 2), _fmt(b.get("cagr", NAN), pct=True), "0.0%"])
    out += [_table(header, rows), "",
            f"Chance for the top-3 hit rate is {3 / 14 * 100:.1f}%; a constant P(beat) = 0.5 has Brier 0.25. The first four rows are the Phase 4 "
            "baselines, recomputed on the same data.", ""]
    ics = {n: allruns[n].summary.get("ic", NAN) for n in allruns}
    shp = {n: allruns[n].summary.get("bt_sharpe", NAN) for n in allruns}
    model_names = list(SECTOR_MODELS)
    beat_ic = [n for n in model_names if ics[n] > max(ics[x] for x in ("last_years_winners", "biggest_allocation_increase", "ridge"))]
    beat_sharpe = [n for n in model_names if shp[n] > shp["equal_weight"]]
    out += ["**Reading it.** " + (f"Above the best baseline IC: {', '.join(beat_ic)}. " if beat_ic else "No Tier-1 model beats the best "
            "baseline IC. ") + (f"Above the equal-weight Sharpe ({_fmt(shp['equal_weight'], 2)}): {', '.join(beat_sharpe)}. " if beat_sharpe
            else f"No Tier-1 model beats the equal-weight Sharpe ({_fmt(shp['equal_weight'], 2)}). ")
            + "With 12 test years and 14 sectors a difference of a few hundredths of IC is within noise; the README bar is mean IC > 0.10.", ""]

    out += ["### Spearman IC per test year", "", _table(["Budget", *SECTOR_MODELS, "ridge", "last_years_winners"],
            [[y, *[_fmt(float(allruns[n].per_year.set_index("budget_id")["ic"].get(y, NAN))) for n in (*SECTOR_MODELS, "ridge", "last_years_winners")]]
             for y in years]), "", "### Net return of the top-3 portfolio per test year", "",
            _table(["Budget", *SECTOR_MODELS, "equal_weight", "Nifty 500"],
                   [[y, *[_fmt(float(allruns[n].per_year.set_index("budget_id")["port_net"].get(y, NAN)), pct=True) for n in (*SECTOR_MODELS, "equal_weight")],
                     _fmt(float(bench.periods.set_index("budget_id")["net_return"].get(y, NAN)), pct=True)] for y in years]), ""]

    out += ["### Sampler and tuning diagnostics", ""]
    bayes_rows = [[f.budget_id, _fmt(f.params.get("max_rhat", NAN), 3), _fmt(f.params.get("min_ess_bulk", NAN), 0),
                   _fmt(f.params.get("divergences", NAN), 0)] for f in sector_folds["bayes_hier"]]
    out += ["PyMC (R-hat should be below 1.01, divergences 0):", "", _table(["Fold", "max R-hat", "min bulk ESS", "divergences"], bayes_rows), "",
            "Optuna-chosen LightGBM sector-ranker parameters per fold:", "",
            _table(["Fold", "trees", "learning rate", "leaves", "depth", "min child", "lambda"],
                   [[f.budget_id, str(f.params.get("n_estimators")), _fmt(f.params.get("learning_rate"), 3), str(f.params.get("num_leaves")),
                     str(f.params.get("max_depth")), str(f.params.get("min_child_samples")), _fmt(f.params.get("reg_lambda"), 1)]
                    for f in sector_folds["lgbm_ranker"]]), "",
            "Bayesian model, sector-specific surprise slopes from the final fit on all unlocked, resolved rows (standardised units; "
            "80% credible interval; a slope whose interval excludes 0 would be a sector where the surprise carries information):", "",
            _table(["Sector", "slope mean", "80% lo", "80% hi"],
                   [[str(row["sector"]), _fmt(float(row["slope_mean"])), _fmt(float(row["slope_lo"])), _fmt(float(row["slope_hi"]))]
                    for row in slopes.to_dict("records")]), ""]

    out += ["## IT Services (control sector), sector level", "",
            f"Alarm rule as in Phase 4: score correlates positively with the realised excess return across test years, one-sided p < {ALARM_P}.", ""]
    rows, alarm_any = [], False
    for n in SECTOR_MODELS:
        c = control_summary(sector[n])
        alarm = (not math.isnan(c["p_one_sided"])) and c["p_one_sided"] < ALARM_P and c["rho"] > 0
        alarm_any = alarm_any or alarm
        rows.append([n, _fmt(c["mean_predicted_rank"], 1), _fmt(c["mean_actual_rank"], 1),
                     f"{int(c['years_in_predicted_top3'])} of {int(c['n_years'])}", _fmt(c["rho"]), _fmt(c["p_one_sided"]),
                     "**ALARM**" if alarm else "no"])
    out += [_table(["Model", "Mean predicted rank (of 15)", "Mean realised rank", "Years in predicted top 3", "Spearman rho", "p (one-sided)", "Alarm"], rows), "",
            "**Leakage alarm raised: investigate before moving on.**" if alarm_any else
            "No Tier-1 model finds a significant budget effect in the control sector: no leakage alarm.", ""]

    out += ["## Tier 2: stock results (14 budget-sensitive sectors, top-15 portfolios)", ""]
    first = min(r.predictions["budget_id"].min() for r in stock.values())
    n_years = stock["tier2_ranker"].per_year["budget_id"].nunique()
    header = ["Model", "Pooled IC", "Within-sector IC", "Top-15 hit", "Top-15 excess (pre-cost)", "Sharpe", "CAGR", "Excess vs Nifty 500"]
    rows = [[n, _fmt(r.summary.get("ic", NAN)), _fmt(r.summary.get("within_sector_ic", NAN)), _fmt(r.summary.get("topk_hit", NAN), pct=True),
             _fmt(r.summary.get("topk_excess", NAN), pct=True), _fmt(r.summary.get("bt_sharpe", NAN), 2),
             _fmt(r.summary.get("bt_cagr", NAN), pct=True), _fmt(r.summary.get("port_excess", NAN), pct=True)] for n, r in stock.items()]
    sb = stock_bench.summary
    rows.append(["**Nifty 500**", "", "", "", "", _fmt(sb.get("sharpe", NAN), 2), _fmt(sb.get("cagr", NAN), pct=True), "0.0%"])
    out += [f"{n_years} test years ({first} onward). Stocks are today's symbols passing the liquidity rule: **survivorship bias is not "
            "removed**, so every stock number is flattered and the equal-weight row is the fair bar.", "", _table(header, rows), ""]
    s_ic = {n: r.summary.get("ic", NAN) for n, r in stock.items()}
    best_base = max(s_ic[n] for n in ("momentum_12m", "ridge", "sector_then_momentum"))
    out += [("**Reading it.** The Tier-2 ranker " + ("beats" if s_ic["tier2_ranker"] > best_base else "does not beat")
             + f" the best stock baseline on pooled IC ({_fmt(s_ic['tier2_ranker'])} vs {_fmt(best_base)}). "
             "`sector_then_momentum` isolates what the stock features add on top of the sector call."), ""]
    out += ["### Stock IC per test year", "", _table(["Budget", *stock],
            [[y, *[_fmt(float(r.per_year.set_index("budget_id")["ic"].get(y, NAN))) for r in stock.values()]]
             for y in sorted(stock["tier2_ranker"].per_year["budget_id"])]), "",
            "### IT Services stocks (control), pooled", ""]
    rows = []
    for n, r in stock.items():
        if n == "equal_weight":
            continue
        c = stock_control(r)
        alarm = (not math.isnan(c["p_one_sided"])) and c["p_one_sided"] < ALARM_P and c["rho"] > 0
        rows.append([n, str(int(c["n"])), _fmt(c["rho"]), _fmt(c["p_one_sided"]), "**ALARM**" if alarm else "no"])
    out += [_table(["Model", "stock-years", "Spearman rho", "p (one-sided)", "Alarm"], rows), "",
            "The pooled test treats the same stocks in different years as independent, so it can over-flag; any alarm is "
            "therefore investigated (README Phase 5 exit criterion):", "", *investigation[0], ""]

    out += ["## Not built, and why", "",
            "- **Company fundamentals (D12) and order-win extractor (D13 / F8).** No point-in-time source is reachable: Yahoo's "
            "fundamentals are a current snapshot (using them for 2012-2023 budgets would be look-ahead), and filings/exchange "
            "announcement archives need manual download. Nothing was estimated or typed in. Tier 2 therefore uses price-based stock "
            "features plus Tier-1 output only; the README's fundamentals and `OrderInflow / MarketCap` features are open.",
            "- **LSTM / temporal CNN embedding (Could).** Not built (no deep-learning library in the project, and the README keeps it only if "
            "the ablation shows a gain; that ablation is Phase 8).",
            "- **Stack over Tier 2 and the LSTM.** The stack covers the two Tier-1 models only.", "",
            "## Exit criteria", "",
            "- Per-year walk-forward results for every model vs every baseline: this file and `reports/models_per_year.csv`, "
            "`reports/models_stock_per_year.csv`.",
            "- IT Services (control): sector level " + ("shows no alarm. " if not alarm_any else "RAISED an alarm. ")
            + ("Stock level: every alarm was investigated and explained (see above)." if investigation[1]
               else "Stock level: an alarm is NOT explained; do not move on."), ""]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------------------------------- driver
def run(cfg: EvalConfig | None = None, use_mlflow: bool = True, report_dir: Path | None = None,
        with_speech: bool = False) -> tuple[dict[str, ModelRun], dict[str, StockRun]]:
    """``with_speech`` adds the Phase 6 speech features to the sector models (same settings, no re-tuning) and writes
    ``*_speech`` files next to the Phase 5 ones. It refuses to run until real speeches have been parsed."""
    cfg = cfg or load_config()
    sfx = "_speech" if with_speech else ""
    if with_speech:
        scores = cfg.root / "data" / "csv" / "speech_sector_scores.csv"
        if not scores.exists() or len(pd.read_csv(scores)) == 0:
            raise SystemExit("BLOCKED: no speeches parsed. Put the speech PDFs in data/source_pdfs/speeches/ "
                             "(names in reports/speech_pdfs_needed.csv), then run `make parse-speeches features`.")
    np.random.seed(cfg.seed)
    reports = report_dir or cfg.root / "reports"
    reports.mkdir(exist_ok=True)
    bundle = build_market_data_bundle(cfg.root)
    from bsp.features.speech_features import SPEECH_FEATURES

    panel = load_sector_panel(cfg, extra_features=tuple(SPEECH_FEATURES) if with_speech else ())
    calendar = budget_calendar(cfg.root, trading_days(cfg.root))
    windows = calendar[["budget_id", "start", "label_end"]]
    market_level = pd.DataFrame({BENCHMARK: (1.0 + bundle.market_returns.fillna(0.0)).cumprod()})
    budgets = sorted(panel.frame["budget_id"].unique())
    bench = run_backtest({b: [BENCHMARK] for b in budgets}, windows[windows["budget_id"].isin(budgets)], market_level, cfg.round_trip_cost)

    with tempfile.TemporaryDirectory() as tmp:  # the Phase 4 reports are not rewritten here
        base = {r.name: r for r in run_baselines(cfg, use_mlflow=False, report_dir=Path(tmp))}
    sector, sector_folds, stack_weights = run_sector_models(cfg, panel, windows, bundle, bench)
    blend_t1 = tier1_features(sector["tier1_blend"].predictions)
    stock, stock_panel = run_stock_models(cfg, blend_t1, windows, bundle, bench)
    stock_budgets = sorted(stock["tier2_ranker"].predictions["budget_id"].unique())
    stock_bench = run_backtest({b: [BENCHMARK] for b in stock_budgets}, windows[windows["budget_id"].isin(stock_budgets)], market_level, cfg.round_trip_cost)

    from bsp.models.registry import final_fit_and_register

    slopes, registry = final_fit_and_register(cfg, panel, stock_panel, use_mlflow)
    if not with_speech:
        from bsp.explain.build import build_outputs
        from bsp.explain.report import write_explainability_report

        explained = build_outputs(
            cfg.root, cfg.seed, panel.frame, stock_panel.frame, sector_folds,
            {n: r.predictions for n, r in sector.items()}, stack_weights, stock["tier2_ranker"].folds or [],
            stock["tier2_ranker"].predictions, panel.frame.drop_duplicates("budget_id")[["budget_id", "presented_on", "day0", "label_end"]])
        explained.predictions.round(8).to_csv(cfg.root / "data" / "csv" / "predictions.csv", index=False)
        explained.detail.round(8).to_csv(reports / "predictions_detail.csv", index=False)
        explained.shap_sector.round(8).to_csv(reports / "shap_values_sector.csv", index=False)
        explained.shap_stock.round(8).to_csv(reports / "shap_values_stock.csv", index=False)
        explained.coverage_year.round(8).to_csv(reports / "interval_coverage_by_year.csv", index=False)
        explained.coverage_regime.round(8).to_csv(reports / "interval_coverage_by_regime.csv", index=False)
        write_explainability_report(explained, reports / "explainability.md")
    write_models_report(base, sector, sector_folds, stock, bench, cfg, reports / f"models{sfx}.md", slopes, stock_bench,
                        stock_control_investigation(stock, stock_panel, cfg.seed), stack_weights)

    rows = [{"model": r.name, "level": "sector", **{k: round(v, 8) for k, v in r.summary.items()}} for r in (*base.values(), *sector.values())]
    rows += [{"model": r.name, "level": "stock", **{k: round(v, 8) for k, v in r.summary.items()}} for r in stock.values()]
    pd.DataFrame(rows).to_csv(reports / f"models_summary{sfx}.csv", index=False)
    pd.concat([r.per_year.assign(model=r.name) for r in (*base.values(), *sector.values())]).round(8).to_csv(reports / f"models_per_year{sfx}.csv", index=False)
    pd.concat([r.per_year.assign(model=r.name) for r in stock.values()]).round(8).to_csv(reports / f"models_stock_per_year{sfx}.csv", index=False)
    for kind, runs_ in (("sector", sector), ("stock", stock)):  # one row per entity and budget: score, rank (1 = best), forecasts
        frame = pd.concat([r.predictions.assign(model=r.name) for r in runs_.values()])
        frame["rank"] = frame.groupby(["model", "budget_id"])["score"].rank(method="first", ascending=False).astype(int)
        frame.round(8).to_csv(reports / f"models_predictions_{kind}{sfx}.csv", index=False)
    slopes.round(8).to_csv(reports / f"models_bayes_slopes{sfx}.csv", index=False)
    stack_weights.to_csv(reports / f"models_stack_weights{sfx}.csv", index=False)

    if use_mlflow:
        kind, uri = tracking.configure(cfg.root)
        print(f"MLflow store: {kind} ({uri})")
        artifacts = [reports / f"models_summary{sfx}.csv", reports / f"models_per_year{sfx}.csv", reports / f"models{sfx}.md"]
        for r in sector.values():
            tracking.log_run(f"sector{sfx}/{r.name}", {**r.params, "mlflow_store": kind, "speech_features": with_speech}, r.per_year, r.summary, artifacts)
        for s in stock.values():
            tracking.log_run(f"stock{sfx}/{s.name}", {**s.params, "mlflow_store": kind, "speech_features": with_speech}, s.per_year, s.summary, artifacts)
        if not with_speech:
            registry()
    return sector, stock


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument("--with-speech", action="store_true", help="add the Phase 6 speech features (needs parsed speeches)")
    args = parser.parse_args()
    sector, stock = run(use_mlflow=not args.no_mlflow, with_speech=args.with_speech)
    for r in sector.values():
        print(f"sector {r.name:<14} IC={_fmt(r.summary.get('ic', NAN))} Sharpe={_fmt(r.summary.get('bt_sharpe', NAN), 2)}")
    for s in stock.values():
        print(f"stock  {s.name:<22} IC={_fmt(s.summary.get('ic', NAN))} Sharpe={_fmt(s.summary.get('bt_sharpe', NAN), 2)}")


if __name__ == "__main__":
    main()
