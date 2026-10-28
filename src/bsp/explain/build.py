"""Phase 7 driver: attributions, three reasons, conformal intervals and the ``predictions`` table for every model.

Called by ``bsp.models.run_models`` after the walk-forward folds exist (it needs the fitted fold models). Nothing here changes a
forecast, a rank or a Phase 5 setting; it adds explanations and intervals to the out-of-sample predictions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from bsp.evaluation.walk_forward import FoldResult
from bsp.explain import contributions as con
from bsp.explain.conformal import conformal_intervals, coverage_table
from bsp.explain.reasons import reasons_for

PREDICTION_COLUMNS = ["model_version", "entity", "budget_id", "expected_excess", "p10", "p90", "p_beat", "rank", "top_reasons"]
REGIME_FLAGS = {"election_year": "regime_is_election_year", "covid_era": "regime_is_covid_era", "high_vix": "regime_high_vix"}


@dataclass
class ExplainOutputs:
    predictions: pd.DataFrame  # the database table
    detail: pd.DataFrame  # predictions plus level, interval method, native interval, actual
    shap_sector: pd.DataFrame
    shap_stock: pd.DataFrame
    coverage_year: pd.DataFrame
    coverage_regime: pd.DataFrame
    additivity: pd.DataFrame


def model_version(name: str, seed: int, root: Path) -> str:
    digest = hashlib.sha256()
    for file in ("features_sector_year_wide.csv", "features_stock_year_wide.csv", "targets.csv"):
        digest.update((root / "data" / "csv" / file).read_bytes())
    return f"{name}/walk-forward/seed{seed}/inputs-{digest.hexdigest()[:8]}"


def _values(test: pd.DataFrame, features: list[str]) -> list[dict[str, float | None]]:
    cols = [c for c in features if c in test.columns]
    return [{c: (None if pd.isna(v) else float(v)) for c, v in zip(cols, row, strict=True)} for row in test[cols].to_numpy()]


def _long(model: str, target: str, budget: str, test: pd.DataFrame, attribution: con.Attribution, entity_col: str = "entity") -> pd.DataFrame:
    rows = []
    entities = test[entity_col].tolist()
    for feature in attribution.contrib.columns:
        raw = test[feature].to_numpy() if feature in test.columns else np.full(len(test), np.nan)
        for i, entity in enumerate(entities):
            rows.append({"model": model, "target": target, "budget_id": budget, "entity": entity, "feature": feature,
                         "feature_value": raw[i], "base": attribution.base[i], "shap": attribution.contrib[feature].iloc[i]})
    return pd.DataFrame(rows)


def explain_model(name: str, budget: str, test: pd.DataFrame, attribution: con.Attribution, stored_expected: np.ndarray,
                  features: list[str], root: Path) -> tuple[list[str], dict[str, float]]:
    """(three reasons per row as JSON strings, additivity check for this fold)."""
    values = _values(test, list(attribution.contrib.columns))
    out = []
    for i in range(len(test)):
        contributions = {c: float(attribution.contrib[c].iloc[i]) for c in attribution.contrib.columns}
        out.append(json.dumps(reasons_for(contributions, values[i], root), ensure_ascii=False))
    gap = np.abs(attribution.predicted() - stored_expected)
    return out, {"max_abs_gap": float(gap.max()), "mean_abs_gap": float(gap.mean())}


def build_outputs(
    root: Path, seed: int, sector_panel: pd.DataFrame, stock_panel: pd.DataFrame,
    sector_folds: dict[str, list[FoldResult]], sector_predictions: dict[str, pd.DataFrame], stack_weights: pd.DataFrame,
    stock_folds: list[FoldResult], stock_predictions: pd.DataFrame, budgets: pd.DataFrame,
    explain_budgets: set[str] | None = None,
) -> ExplainOutputs:
    shap_sector, shap_stock, checks = [], [], []
    reason_frames: dict[tuple[str, str], pd.DataFrame] = {}
    weights = stack_weights.set_index("budget_id")["weight_first"].to_dict()

    def keep(model: str, level: str, budget: str, test: pd.DataFrame, reasons: list[str]) -> None:
        reason_frames[(model, budget)] = pd.DataFrame({"entity": test["entity"].to_numpy(), "top_reasons": reasons})

    lgbm_folds = {f.budget_id: f for f in sector_folds["lgbm_ranker"]}
    bayes_folds = {f.budget_id: f for f in sector_folds["bayes_hier"]}
    for budget in sorted(b for b in lgbm_folds if explain_budgets is None or b in explain_budgets):
        test = sector_panel[sector_panel["budget_id"] == budget]
        lg, by = lgbm_folds[budget].model, bayes_folds[budget].model
        a_lgbm, a_bayes = con.lgbm_expected_attribution(lg, test), con.bayes_attribution(by, test)
        a_rank = con.lgbm_rank_attribution(lg, test)
        shap_sector += [_long("lgbm_ranker", "expected_return", budget, test, a_lgbm), _long("lgbm_ranker", "rank_score", budget, test, a_rank)]
        w = float(weights[budget])
        attributions = {"lgbm_ranker": a_lgbm, "bayes_hier": a_bayes, "tier1_blend": con.combine([(0.5, a_lgbm), (0.5, a_bayes)]),
                        "tier1_stack": con.combine([(w, a_lgbm), (1 - w, a_bayes)])}
        for model, attribution in attributions.items():
            if model in ("bayes_hier", "tier1_blend", "tier1_stack"):
                shap_sector.append(_long(model, "expected_return", budget, test, attribution))
            stored = sector_predictions[model]
            stored = stored[stored["budget_id"] == budget].set_index("entity").loc[test["entity"], "expected"].to_numpy()
            reasons, check = explain_model(model, budget, test, attribution, stored, list(test.columns), root)
            checks.append({"model": model, "budget_id": budget, **check})
            keep(model, "sector", budget, test, reasons)
    for fold in stock_folds:
        budget = fold.budget_id
        if explain_budgets is not None and budget not in explain_budgets:
            continue
        test = stock_panel[stock_panel["budget_id"] == budget]
        a_exp, a_rank = con.lgbm_expected_attribution(fold.model, test), con.lgbm_rank_attribution(fold.model, test)
        shap_stock += [_long("tier2_ranker", "expected_return", budget, test, a_exp), _long("tier2_ranker", "rank_score", budget, test, a_rank)]
        stored = stock_predictions[stock_predictions["budget_id"] == budget].set_index("entity").loc[test["entity"], "expected"].to_numpy()
        reasons, check = explain_model("tier2_ranker", budget, test, a_exp, stored, list(test.columns), root)
        checks.append({"model": "tier2_ranker", "budget_id": budget, **check})
        keep("tier2_ranker", "stock", budget, test, reasons)

    frames = []
    for model, level, pred in [(m, "sector", p) for m, p in sector_predictions.items()] + [("tier2_ranker", "stock", stock_predictions)]:
        pred = conformal_intervals(pred, budgets)
        pred["rank"] = pred.groupby("budget_id")["score"].rank(method="first", ascending=False).astype(int)
        joined = pd.concat([reason_frames[(model, b)].assign(budget_id=b) for b in sorted(pred["budget_id"].unique()) if (model, b) in reason_frames])
        merged = pred.merge(joined, on=["budget_id", "entity"], how="left", validate="one_to_one")
        merged["model"], merged["level"] = model, level
        frames.append(merged)
    detail = pd.concat(frames, ignore_index=True)
    detail["model_version"] = detail["model"].map(lambda m: model_version(m, seed, root))
    detail["expected_excess"] = detail["expected"]
    table = detail[PREDICTION_COLUMNS].copy()

    flags = sector_panel.drop_duplicates("budget_id")[["budget_id", *REGIME_FLAGS.values()]].set_index("budget_id")
    headline = detail[~detail["is_control"]].copy()
    headline["fiscal_year"] = headline["budget_id"]
    by_year = coverage_table(headline.assign(method=headline["interval_method"]), ["model", "level", "budget_id"])
    by_year_native = coverage_table(headline.assign(p10=headline["lo"], p90=headline["hi"]), ["model", "level", "budget_id"]).rename(
        columns={"coverage": "native_coverage", "mean_width": "native_width"})[["model", "level", "budget_id", "native_coverage", "native_width"]]
    by_year = by_year.merge(by_year_native, on=["model", "level", "budget_id"], how="left")
    regime_rows = []
    for regime, column in REGIME_FLAGS.items():
        tagged = headline.assign(regime=regime, value=headline["budget_id"].map(flags[column]).map(lambda v: "yes" if v >= 0.5 else "no"))
        regime_rows.append(coverage_table(tagged, ["model", "level", "regime", "value"]))
    overall = coverage_table(headline.assign(scope="all test years"), ["model", "level", "scope"])
    return ExplainOutputs(table, detail, pd.concat(shap_sector, ignore_index=True), pd.concat(shap_stock, ignore_index=True),
                          pd.concat([by_year, overall.rename(columns={"scope": "budget_id"})], ignore_index=True),
                          pd.concat(regime_rows, ignore_index=True), pd.DataFrame(checks))
