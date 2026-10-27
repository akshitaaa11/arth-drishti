"""Phase 8 driver: backtest lab, IC confidence intervals, ablations, event-effect tests, DiD, regime errors -> reports/evidence.md.

``make evidence`` runs the two ablations (slow, refits) and then this module (fast; no model is refitted here). Fixed seeds, no
timestamps: two runs give identical files. The FY2024-25 / FY2025-26 hold-out and the live year are not loaded anywhere.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from bsp.evaluation import metrics
from bsp.evaluation.run_baselines import _fmt, _table
from bsp.evidence import backtest_lab as lab_mod
from bsp.evidence.context import Context, load_context
from bsp.evidence.did import run_did
from bsp.evidence.event_effects import sector_event_effects
from bsp.evidence.regimes import regime_errors
from bsp.evidence.stats import paired_difference, summarise

NAN = float("nan")
ABLATION_MODELS = ("ridge", "lgbm_ranker")


def _ci(s: object) -> str:
    return f"{_fmt(s.mean)} [{_fmt(s.lo)}, {_fmt(s.hi)}]"  # type: ignore[attr-defined]


def ic_table(predictions: pd.DataFrame, models: list[str], level: str) -> pd.DataFrame:
    rows = []
    for model in models:
        frame = predictions[(predictions["model"] == model) & (~predictions["is_control"].astype(bool))]
        ics = [metrics.spearman_ic(g["score"].to_numpy(), g["actual"].to_numpy()) for _, g in frame.groupby("budget_id")]
        if not any(not math.isnan(v) for v in ics):
            continue
        s = summarise(ics)
        rows.append({"level": level, "model": model, "n_years": s.n, "mean_ic": s.mean, "ci_lo": s.lo, "ci_hi": s.hi, "t_stat": s.t_stat,
                     "p_two_sided": s.p_two_sided, "p_one_sided_positive": s.p_one_sided_positive,
                     "share_years_positive": float(np.mean([v > 0 for v in ics if not math.isnan(v)]))})
    return pd.DataFrame(rows)


def ablation_summary(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames = [pd.read_csv(root / "reports" / f"ablation_per_year_{m}.csv") for m in ABLATION_MODELS]
    per_year = pd.concat(frames, ignore_index=True)
    rows = []
    for model, g in per_year.groupby("model"):
        full = g[g["variant"] == "full"].set_index("budget_id")
        for variant, v in g.groupby("variant"):
            v = v.set_index("budget_id")
            years = full.index.intersection(v.index)
            ic = summarise(v.loc[years, "ic"].to_numpy())
            drop = paired_difference(full.loc[years, "ic"].to_numpy(), v.loc[years, "ic"].to_numpy())
            excess_drop = paired_difference(full.loc[years, "port_excess"].to_numpy(), v.loc[years, "port_excess"].to_numpy())
            rows.append({"model": model, "variant": variant, "n_features": int(v["n_features"].iloc[0]), "mean_ic": ic.mean, "ic_ci_lo": ic.lo,
                         "ic_ci_hi": ic.hi, "ic_drop_vs_full": drop.mean, "drop_ci_lo": drop.lo, "drop_ci_hi": drop.hi, "drop_t": drop.t_stat,
                         "mean_top3_excess": float(v["port_excess"].mean()), "top3_excess_drop_vs_full": excess_drop.mean})
    return per_year, pd.DataFrame(rows)


def group_contrasts(per_year: pd.DataFrame) -> pd.DataFrame:
    """Does adding budget data to price data raise IC? Paired by test year."""
    pairs = [("price_plus_budget", "price_only", "budget data added to price data"), ("budget_only", "momentum_only", "budget data alone vs momentum alone"),
             ("price_plus_budget", "momentum_only", "price + budget vs momentum alone"), ("full", "price_plus_budget", "everything else (FPI, macro, regime) added")]
    rows = []
    for model, g in per_year.groupby("model"):
        by = {v: x.set_index("budget_id") for v, x in g.groupby("variant")}
        for a, b, label in pairs:
            if a not in by or b not in by:
                continue
            years = by[a].index.intersection(by[b].index)
            ic = paired_difference(by[a].loc[years, "ic"].to_numpy(), by[b].loc[years, "ic"].to_numpy())
            ex = paired_difference(by[a].loc[years, "port_excess"].to_numpy(), by[b].loc[years, "port_excess"].to_numpy())
            rows.append({"model": model, "contrast": f"{a} minus {b}", "meaning": label, "n_years": ic.n, "ic_difference": ic.mean,
                         "ic_ci_lo": ic.lo, "ic_ci_hi": ic.hi, "ic_t": ic.t_stat, "ic_p_two_sided": ic.p_two_sided,
                         "top3_excess_difference": ex.mean, "excess_ci_lo": ex.lo, "excess_ci_hi": ex.hi})
    return pd.DataFrame(rows)


def noise_floor(per_year: pd.DataFrame) -> dict[str, float]:
    g = per_year[(per_year["model"] == "lgbm_ranker") & per_year["variant"].str.startswith("full")]
    means = g.groupby("variant")["ic"].mean()
    return {"n_runs": float(len(means)), "min": float(means.min()), "max": float(means.max()), "sd": float(means.std(ddof=1))}


def run(root: Path | None = None) -> None:
    ctx: Context = load_context()
    cfg = ctx.cfg
    root = root or cfg.root
    reports = root / "reports"

    # 1. backtest lab
    lab = lab_mod.run_lab(ctx, root)
    sector_summary, sector_equity, sector_runs = lab["sector"]
    stock_summary, stock_equity, _ = lab["stock"]
    pd.concat([sector_summary, stock_summary]).round(8).to_csv(reports / "backtest_lab_summary.csv", index=False)
    sector_equity.round(6).to_csv(reports / "backtest_lab_equity_sector.csv", index_label="date")
    stock_equity.round(6).to_csv(reports / "backtest_lab_equity_stock.csv", index_label="date")
    lab_mod.plot_lab(sector_equity, reports / "backtest_lab_sector.png",
                     "Top-3 sector portfolios, net of 0.2% round-trip costs, rebalanced at each budget (FY2012-13 to FY2023-24)",
                     ["equal_weight", "ridge", "tier1_blend", "lgbm_ranker"])
    lab_mod.plot_lab(stock_equity, reports / "backtest_lab_stock.png",
                     "Top-15 stock portfolios, net of costs (survivorship bias not removed; FY2015-16 to FY2023-24)",
                     ["equal_weight", "momentum_12m", "ridge", "tier2_ranker"])

    # 2. IC confidence intervals
    sector_preds = lab_mod.load_sector_predictions(root)
    stock_preds = pd.read_csv(root / "reports" / "models_predictions_stock.csv")
    ic = pd.concat([ic_table(sector_preds, lab_mod.SECTOR_MODELS, "sector"), ic_table(stock_preds, lab_mod.STOCK_MODELS, "stock")], ignore_index=True)
    ic.round(8).to_csv(reports / "ic_bootstrap.csv", index=False)

    # 3. ablations
    per_year, abl = ablation_summary(root)
    contrasts = group_contrasts(per_year)
    abl.round(8).to_csv(reports / "ablation_summary.csv", index=False)
    contrasts.round(8).to_csv(reports / "ablation_contrasts.csv", index=False)
    floor = noise_floor(per_year)

    # 4. event effects (BH) and DiD
    effects = sector_event_effects(cfg)
    effects.round(8).to_csv(reports / "event_effects_bh.csv", index=False)
    did_budget, did_summary = run_did(ctx)
    did_budget.round(8).to_csv(reports / "did_by_budget.csv", index=False)
    did_summary.round(8).to_csv(reports / "did_summary.csv", index=False)

    # 5. regimes
    flags = ctx.panel.frame.drop_duplicates("budget_id")[["budget_id", *lab_mod_flag_columns()]]
    regimes = regime_errors(sector_preds, flags, sector_runs, ctx.bench)
    regimes.round(8).to_csv(reports / "regime_errors.csv", index=False)

    write_evidence(reports / "evidence.md", cfg, sector_summary, stock_summary, ic, abl, contrasts, floor, effects, did_summary, did_budget, regimes)


def lab_mod_flag_columns() -> list[str]:
    from bsp.evidence.regimes import FLAGS

    return list(FLAGS.values())


def write_evidence(path: Path, cfg, sector_summary, stock_summary, ic, abl, contrasts, floor, effects, did_summary, did_budget, regimes) -> None:  # type: ignore[no-untyped-def]
    out = ["# Phase 8 evidence: does the budget data add anything beyond price momentum?", "",
           "Generated by `make evidence` (`src/bsp/evidence/`). Every number is out-of-sample (walk-forward) or computed on the unlocked "
           "years FY2005-06 to FY2023-24; the FY2024-25 / FY2025-26 hold-out and the live year were not loaded. 12 sector test years "
           "(9 for stocks) make every statistic here weak: read the intervals, not just the means. Nothing is investment advice.", ""]

    # --- the question
    out += ["## 1. The question, answered with numbers", ""]
    rows = []
    for r in contrasts[contrasts["contrast"] == "price_plus_budget minus price_only"].itertuples():
        rows.append([r.model, _fmt(r.ic_difference), f"[{_fmt(r.ic_ci_lo)}, {_fmt(r.ic_ci_hi)}]", _fmt(r.ic_t, 2), _fmt(r.ic_p_two_sided),
                     _fmt(r.top3_excess_difference, pct=True), f"[{_fmt(r.excess_ci_lo, pct=True)}, {_fmt(r.excess_ci_hi, pct=True)}]"])
    out += ["Same model, same folds, with price features only (momentum and volatility) against price plus budget features (allocation "
            "growth, capex share, schemes, fiscal stance, surprise, execution credibility). Difference per test year, then averaged:", "",
            _table(["Model", "IC gain from budget data", "95% bootstrap CI", "t", "p (two-sided)", "Top-3 net excess gain", "95% CI"], rows), ""]
    verdicts = []
    main = list(contrasts[contrasts["contrast"] == "price_plus_budget minus price_only"].itertuples())
    for r in main:
        if r.ic_ci_lo > 0:
            verdicts.append(f"{r.model}: budget data raises IC by {_fmt(r.ic_difference)} (interval excludes 0; t-test p {_fmt(r.ic_p_two_sided)})")
        elif r.ic_ci_hi < 0:
            verdicts.append(f"{r.model}: budget data lowers IC by {_fmt(-r.ic_difference)} (interval excludes 0; t-test p {_fmt(r.ic_p_two_sided)})")
        else:
            verdicts.append(f"{r.model}: the IC difference is {_fmt(r.ic_difference)}, interval includes 0 (t-test p {_fmt(r.ic_p_two_sided)}), so no detectable gain or loss")
    if not any(r.ic_ci_lo > 0 for r in main):
        bottom = ("**Bottom line: in these 12 test years the budget features did not add detectable predictive power beyond price momentum and volatility"
                  + ("; both point estimates are negative.**" if all(r.ic_difference < 0 for r in main) else ".**"))
    else:
        bottom = "**Bottom line: at least one model gains from the budget features; see the intervals below.**"
    out += [bottom, "", "**Answer.** " + "; ".join(verdicts) + f". For scale, re-running the same LightGBM model with {int(floor['n_runs'])} different seeds moves its "
            f"mean IC between {_fmt(floor['min'])} and {_fmt(floor['max'])} (sd {_fmt(floor['sd'])}), so differences smaller than that are noise.", ""]
    rows = []
    for r in contrasts.itertuples():
        rows.append([r.model, r.meaning, _fmt(r.ic_difference), f"[{_fmt(r.ic_ci_lo)}, {_fmt(r.ic_ci_hi)}]", _fmt(r.ic_p_two_sided)])
    out += ["All contrasts (IC difference, a minus b, paired by test year):", "", _table(["Model", "Contrast", "IC difference", "95% CI", "p"], rows), ""]

    # --- ablations
    out += ["## 2. Ablations: IC without each feature family", "",
            "Drop = IC of the full model minus IC without the family (positive = the family helped), paired by test year with a bootstrap CI. "
            "`speech_nlp` cannot be ablated: no speech data exists yet, so the panel has no such feature.", ""]
    for model in ABLATION_MODELS:
        g = abl[abl["model"] == model].set_index("variant")
        full = g.loc["full"]
        out += [f"### {model} (full model IC {_fmt(full['mean_ic'])}, {int(full['n_features'])} features)", ""]
        rows = []
        for variant in [v for v in g.index if v.startswith("no_")]:
            r = g.loc[variant]
            rows.append([variant.replace("no_", "without "), str(int(r["n_features"])), _fmt(r["mean_ic"]), _fmt(r["ic_drop_vs_full"]),
                         f"[{_fmt(r['drop_ci_lo'])}, {_fmt(r['drop_ci_hi'])}]", _fmt(r["top3_excess_drop_vs_full"], pct=True)])
        rows.append(["without speech_nlp", "-", "untestable", "-", "-", "-"])
        out += [_table(["Variant", "Features", "Mean IC", "IC drop", "95% CI of drop", "Top-3 excess drop"], rows), ""]
        rows = [[v, str(int(g.loc[v, "n_features"])), _fmt(g.loc[v, "mean_ic"]), f"[{_fmt(g.loc[v, 'ic_ci_lo'])}, {_fmt(g.loc[v, 'ic_ci_hi'])}]",
                 _fmt(g.loc[v, "mean_top3_excess"], pct=True)] for v in ("price_only", "momentum_only", "budget_only", "price_plus_budget", "full") if v in g.index]
        out += ["Groups:", "", _table(["Group", "Features", "Mean IC", "95% CI of IC", "Mean top-3 net excess"], rows), ""]
    out += [f"LightGBM noise floor: the full model with seeds 42 and {', '.join(str(s) for s in (1, 2, 3))} gives mean IC "
            f"{_fmt(floor['min'])} to {_fmt(floor['max'])}. A family whose removal changes IC by less than this has no detectable effect.", ""]

    # --- IC CIs
    out += ["## 3. Is any model's IC different from 0? Bootstrap CIs and t-tests", "",
            "Years are the independent units (percentile bootstrap, 10,000 resamples; one-sample t-test). Spearman IC across 14 sectors per year "
            "(across the stock universe per year for stocks).", "",
            _table(["Level", "Model", "Years", "Mean IC", "95% CI", "t", "p (two-sided)", "Years with IC > 0"],
                   [[r.level, r.model, str(r.n_years), _fmt(r.mean_ic), f"[{_fmt(r.ci_lo)}, {_fmt(r.ci_hi)}]", _fmt(r.t_stat, 2), _fmt(r.p_two_sided),
                     _fmt(r.share_years_positive, pct=True)] for r in ic.itertuples()]), ""]
    good = ic[(ic["ci_lo"] > 0)]
    out += [("Models whose 95% interval excludes 0: " + ", ".join(f"{r.level}/{r.model} (t-test p {_fmt(r.p_two_sided)})" for r in good.itertuples()) + ".") if len(good) else
            "No model's 95% interval for mean IC excludes 0.",
            "Ten or more models are shown, so a lone interval that just excludes 0 would be expected by chance about 1 time in 20.", ""]

    # --- backtest lab
    out += ["## 4. Backtest lab (F12): would following the model have made money?", "",
            "![Sector portfolios](backtest_lab_sector.png)", "", "![Stock portfolios](backtest_lab_stock.png)", "",
            "Portfolios are rebuilt from the saved out-of-sample predictions (no refit), equal weight, held from the day after each budget to the "
            "next budget, 0.2% round-trip cost, cash earns 0 between windows. Sector baskets are equal-weight baskets of today's stocks and the "
            "stock list has survivorship bias, so every portfolio tends to beat the cap-weighted Nifty 500; **the fair bar is the equal-weight row**.", ""]
    for name, summary in (("Sector (top 3 of 14, FY2012-13 to FY2023-24)", sector_summary), ("Stock (top 15, FY2015-16 to FY2023-24)", stock_summary)):
        rows = [[r.strategy, _fmt(r.cagr, pct=True), _fmt(r.sharpe, 2), _fmt(r.max_drawdown, pct=True), _fmt(r.turnover, pct=True),
                 f"{r.final_value_of_100:,.0f}"] for r in summary.itertuples()]
        out += [f"### {name}", "", _table(["Strategy", "CAGR", "Sharpe", "Max drawdown", "Turnover", "Value of 100"], rows), ""]
    cost_cols = [c for c in sector_summary.columns if c.startswith("cagr_cost_")]
    rows = [[r["strategy"], *[_fmt(r[c], pct=True) for c in cost_cols]] for r in sector_summary.to_dict("records") if not pd.isna(r[cost_cols[0]])]
    out += ["Cost sensitivity, sector portfolios (CAGR):", "", _table(["Strategy", *[c.replace("cagr_cost_", "").replace("pct", "% cost") for c in cost_cols]], rows), ""]

    # --- BH
    out += ["## 5. Do budgets move sectors? Event effects with Benjamini-Hochberg correction", "",
            "Mean cumulative abnormal return per sector across the full budgets FY2005-06 to FY2023-24 that have an event study for it (up to 19, one value per budget; sectors whose basket did not yet exist for early budgets have fewer, shown in the Budgets column), t-test against 0, "
            "BH over the 15 sectors of each window (q) and over all 75 tests. IT Services is the control.", ""]
    for window in effects["window"].unique():
        g = effects[effects["window"] == window]
        rows = [[r.sector, str(r.n_budgets), _fmt(r.mean_car, pct=True), f"[{_fmt(r.ci_lo, pct=True)}, {_fmt(r.ci_hi, pct=True)}]", _fmt(r.t_stat, 2), _fmt(r.p_value),
                 _fmt(r.q_within_window), "yes" if r.significant_within_window else "no"] for r in g.itertuples()]
        out += [f"### Window {window}", "", _table(["Sector", "Budgets", "Mean CAR", "95% CI", "t", "p", "BH q (15 tests)", "q < 0.05"], rows), ""]
    sig = effects[effects["significant_within_window"]]
    sig_all = effects[effects["significant_all_75_tests"]]
    raw = effects[effects["p_value"] < 0.05]
    out += [f"Uncorrected, {len(raw)} of {len(effects)} sector-window tests have p < 0.05 (about {len(effects) * 0.05:.1f} would by chance alone). "
            f"After BH within each window, {len(sig)} survive" + (": " + ", ".join(f"{r.sector} {r.window}" for r in sig.itertuples()) if len(sig) else "")
            + f"; after BH over all 75 tests, {len(sig_all)} survive" + (": " + ", ".join(f"{r.sector} {r.window}" for r in sig_all.itertuples()) if len(sig_all) else "") + ".",
            "Caveats: the baskets are thin in early years (railways has 1 stock until 2018, defence 2 until 2017); the five windows are nested, so the tests "
            "within a sector are correlated and BH over the 15 sectors does not account for that; the market model is estimated on the 220 days before the budget.",
            "Control check (IT Services): " + (
                "significant after correction - treat as a warning." if (sig["sector"] == "it_control").any() else "not significant after correction."), ""]

    # --- DiD
    out += ["## 6. Causal check (F11): difference-in-differences", "",
            "Large-surprise sectors (top 4 by allocation surprise) against look-alike sectors (below-median surprise, matched on pre-budget momentum and "
            "volatility), excess return over the Nifty 500, post window minus the 60 days before the budget (details in `bsp/evidence/did.py`). "
            "The first row is the parallel-trends check: it should be near 0.", "",
            _table(["Measure", "Budgets", "Mean DiD", "95% CI", "t", "p (t-test)", "p (permutation)", "Budgets with DiD > 0"],
                   [[r.measure, str(r.n_budgets), _fmt(r.mean_did, pct=True), f"[{_fmt(r.ci_lo, pct=True)}, {_fmt(r.ci_hi, pct=True)}]", _fmt(r.t_stat, 2),
                     _fmt(r.p_t_test), _fmt(r.p_permutation), _fmt(r.share_budgets_positive, pct=True)] for r in did_summary.itertuples()]), ""]
    post = did_summary[did_summary["measure"].str.startswith("did_post")]
    trend = did_summary[did_summary["measure"] == "pretrend_did"].iloc[0]
    n_did = int(trend["n_budgets"])
    out += ["Reading it: " + ("the parallel-trends check is " + ("rejected" if trend["p_t_test"] < 0.05 else "not rejected") +
            f" (pre-trend DiD {_fmt(trend['mean_did'], pct=True)}, p {_fmt(trend['p_t_test'])}). ") +
            "; ".join(f"{r.measure.replace('did_post', '+1..+')} days: DiD {_fmt(r.mean_did, pct=True)}, "
                      + ("interval excludes 0" if (r.ci_lo > 0 or r.ci_hi < 0) else "interval includes 0") for r in post.itertuples())
            + f". With {n_did} budgets (FY2005-06 lacks the 120 days of history the check needs), matching on two observables and large-surprise status partly proxying for sector type, this is suggestive at best and "
              "does not establish that the allocation surprise caused the move.", ""]

    # --- regimes
    out += ["## 7. Error reports by regime (F10)", "",
            "Per-model averages over the test budgets with and without each flag (14 budget-sensitive sectors). Election-year, Covid-era and high-VIX flags "
            "come from the feature store. **Interim budgets are not modelled** (no sector budget data, 4-5 month labels), so there is no interim error row; the "
            "election-year flag covers the full budgets of election years only.", ""]
    for regime in ("election_year", "covid_era", "high_vix"):
        g = regimes[regimes["regime"] == regime]
        rows = [[r.model, r.flag, str(r.n_budgets), _fmt(r.mean_ic), _fmt(r.mean_mae), _fmt(r.mean_directional, pct=True), _fmt(r.mean_top3_excess, pct=True)]
                for r in g.itertuples()]
        out += [f"### {regime.replace('_', ' ')}", "", _table(["Model", "Flag", "Budgets", "Mean IC", "MAE", "Directional", "Top-3 net excess vs Nifty 500"], rows), ""]

    out += ["## 8. Limitations", "",
            "- 12 sector test years and 14 sectors: every interval above is wide; absence of a detectable effect is not evidence of no effect.",
            "- Sector baskets and the stock list carry survivorship bias; portfolio levels are flattered, comparisons between strategies on the same list are fairer.",
            "- Ablations remove one family at a time; correlated families (momentum and volatility, macro and regime) can stand in for each other.",
            "- The speech family is untestable until real speeches exist (`reports/data_gaps.md`); FPI is available for only two modelled budgets.",
            "- The DiD treats the four largest surprises as 'treated'; the cut-off was fixed in advance and not tuned.", ""]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> None:
    run()


if __name__ == "__main__":
    main()
