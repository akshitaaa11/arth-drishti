"""Phase 5: rankers, Optuna tuning, Bayesian model, blend, stock panel, label-leak guard and the written reports."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bsp.evaluation.config import load_config
from bsp.evaluation.data import STOCK_FEATURES, Panel, load_sector_panel, load_stock_panel
from bsp.evaluation.walk_forward import stack_predictions, training_rows, walk_forward
from bsp.models.bayes import BayesHierarchical
from bsp.models.ensemble import (
    SectorThenMomentum,
    blend_predictions,
    rank_percentile,
    tier1_features,
)
from bsp.models.ranker import (
    DEFAULT_PARAMS,
    LGBMRankerModel,
    inner_folds,
    make_ranker_tuner,
    relevance_grades,
)
from bsp.models.registry import PosteriorMeanSectorModel
from bsp.models.run_models import _brier

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def sector_panel() -> Panel:
    return load_sector_panel(load_config())


# ---------------------------------------------------------------- labels and inner validation
def test_relevance_grades_are_quintiles_by_rank_and_ties_share_a_grade() -> None:
    grades = relevance_grades(np.arange(15, dtype=float))
    assert grades.min() == 0 and grades.max() == 4 and (np.diff(grades) >= 0).all()
    assert np.bincount(grades).tolist() == [3, 3, 3, 3, 3]
    tied = relevance_grades(np.array([1.0, 1.0, 1.0, 1.0, 1.0]))
    assert len(set(tied.tolist())) == 1


def test_inner_folds_only_validate_on_budgets_with_resolved_past_labels(sector_panel: Panel) -> None:
    cfg = load_config()
    train = training_rows(sector_panel, "FY2018-19")
    folds = list(inner_folds(train))
    assert folds
    for inner_train, inner_test in folds:
        day0 = inner_test["day0"].iloc[0]
        assert (inner_train["label_end"] <= day0).all()
        assert (inner_train["fiscal_year"].astype(str) < str(inner_test["fiscal_year"].iloc[0])).all()
        assert inner_train["budget_id"].nunique() >= 3
        assert set(inner_test["budget_id"]) <= set(train["budget_id"])  # never the outer test budget
    assert "FY2018-19" not in {b for _, t in folds for b in t["budget_id"]}
    assert cfg.holdout_unlocked is False


# ---------------------------------------------------------------- LightGBM ranker
def test_ranker_is_deterministic_keeps_nan_rows_and_gives_forecasts(sector_panel: Panel) -> None:
    train = training_rows(sector_panel, "FY2018-19")
    test = sector_panel.frame[sector_panel.frame["budget_id"] == "FY2018-19"].copy()
    test.loc[test.index[:3], sector_panel.features] = np.nan  # fully missing rows are still scored, not dropped
    first = LGBMRankerModel(seed=42).fit(train, sector_panel.features).predict(test)
    second = LGBMRankerModel(seed=42).fit(train, sector_panel.features).predict(test)
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == len(test) and first["score"].notna().all()
    assert first["p_beat"].between(0, 1).all() and (first["lo"] < first["hi"]).all()


def test_tuner_returns_bounded_params_and_uses_training_rows_only(sector_panel: Panel) -> None:
    train = training_rows(sector_panel, "FY2018-19")
    tune = make_ranker_tuner(n_trials=3, seed=42)
    params = tune(train, sector_panel.features)
    assert set(DEFAULT_PARAMS) <= set(params) and 1 <= params["max_depth"] <= 3 and 2 <= params["num_leaves"] <= 6
    assert tune(train, sector_panel.features) == params  # seeded: same data, same choice
    # a training set too short to validate falls back to the defaults instead of looking elsewhere
    assert tune(train[train["budget_id"].isin(train["budget_id"].unique()[:2])], sector_panel.features) == DEFAULT_PARAMS


def test_scrambling_later_labels_does_not_move_earlier_predictions(sector_panel: Panel) -> None:
    cfg = load_config()
    make = lambda **p: LGBMRankerModel(seed=cfg.seed, with_forecast=False, **p)  # noqa: E731
    base = stack_predictions(walk_forward(sector_panel, make, cfg))
    frame = sector_panel.frame.copy()
    late = frame["fiscal_year"].astype(str) >= "2018-19"
    frame.loc[late, "excess_return"] = np.random.default_rng(1).permutation(frame.loc[late, "excess_return"].to_numpy())
    again = stack_predictions(walk_forward(Panel("sector", frame, sector_panel.features), make, cfg))
    early = base[base["budget_id"] < "FY2018-19"].reset_index(drop=True)
    early_again = again[again["budget_id"].isin(early["budget_id"])].reset_index(drop=True)
    assert len(early) > 0
    np.testing.assert_allclose(early["score"], early_again.loc[early_again["budget_id"] < "FY2018-19", "score"].to_numpy())


# ---------------------------------------------------------------- Bayesian hierarchical model
def _synthetic(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for budget in range(12):
        for sector in range(6):
            surprise = rng.normal()
            rows.append({"budget_id": f"B{budget:02d}", "entity": f"S{sector}", "alloc_vs_prev_re_pct": surprise,
                         "momentum_12m": rng.normal(), "credibility_pct": rng.normal(),
                         "excess_return": 0.5 * surprise + 0.1 * rng.normal()})
    return pd.DataFrame(rows)


def test_bayes_recovers_a_planted_surprise_slope_and_keeps_missing_rows() -> None:
    frame = _synthetic()
    model = BayesHierarchical(seed=1, draws=200, tune=200, chains=2).fit(frame, ["alloc_vs_prev_re_pct"])
    assert (model.slopes()["slope_mean"] > 0).all()
    test = _synthetic(5).head(6)
    test.loc[test.index[0], ["alloc_vs_prev_re_pct", "momentum_12m"]] = np.nan  # missing predictors are imputed, never dropped
    out = model.predict(test)
    assert len(out) == 6 and out["expected"].notna().all()
    assert out["p_beat"].between(0, 1).all() and (out["lo"] < out["hi"]).all()
    again = BayesHierarchical(seed=1, draws=200, tune=200, chains=2).fit(frame, ["alloc_vs_prev_re_pct"]).predict(test)
    pd.testing.assert_frame_equal(out, again)  # same seed, same posterior
    assert model.diagnostics["divergences"] == 0


def test_posterior_mean_pyfunc_matches_a_hand_computation() -> None:
    wrapper = PosteriorMeanSectorModel(["A", "B"], np.array([0.1, 0.2]), np.array([1.0, 2.0]), np.array([0.5]),
                                       ["s", "m"], {"s": {"median": 0.0, "mean": 0.0, "std": 1.0},
                                                    "m": {"median": 0.0, "mean": 0.0, "std": 1.0}}, 0.0, 1.0)
    got = wrapper.predict(None, pd.DataFrame({"entity": ["A", "B"], "s": [1.0, np.nan], "m": [2.0, 2.0]}))
    np.testing.assert_allclose(got, [0.1 + 1.0 * 1.0 + 0.5 * 2.0, 0.2 + 0.0 + 0.5 * 2.0])


# ---------------------------------------------------------------- blend, Brier, stock helpers
def _preds(shift: float) -> pd.DataFrame:
    return pd.DataFrame({"budget_id": ["B1"] * 3, "entity": ["a", "b", "c"], "sector_id": ["a", "b", "c"],
                         "is_control": [False, False, True], "actual": [0.1, 0.0, -0.1],
                         "score": [3.0 + shift, 1.0, 2.0], "expected": [0.3, 0.1, 0.2], "p_beat": [0.9, 0.3, 0.6],
                         "lo": [0.0, -0.2, -0.1], "hi": [0.6, 0.4, 0.5]})


def test_blend_averages_rank_percentiles_and_forecasts() -> None:
    blend = blend_predictions({"x": _preds(0.0), "y": _preds(0.0).assign(score=[1.0, 3.0, 2.0])})
    assert blend["score"].round(6).tolist() == [round((1 + 1 / 3) / 2, 6), round((1 / 3 + 1) / 2, 6), round(2 / 3, 6)]
    assert blend["expected"].tolist() == [0.3, 0.1, 0.2] and len(blend) == 3
    assert rank_percentile(np.array([5.0, 1.0, 3.0])).tolist() == [1.0, 1 / 3, 2 / 3]
    assert list(tier1_features(blend).columns) == ["budget_id", "entity", "t1_rank_score", "t1_expected", "t1_p_beat"]


def test_brier_and_sector_then_momentum() -> None:
    assert _brier(np.array([1.0, 0.0]), np.array([0.2, -0.2])) == 0.0
    assert _brier(np.array([0.5, 0.5]), np.array([0.2, -0.2])) == pytest.approx(0.25)
    test = pd.DataFrame({"sector_id": ["a", "a", "b", "b"], "momentum_12m": [0.1, 0.2, 0.9, -0.5],
                         "t1_rank_score": [0.5, 0.5, 1.0, 1.0]})
    score = SectorThenMomentum().predict(test)["score"].to_numpy()
    assert score[3] > score[1] and score[2] > score[3] and score[1] > score[0]  # sector rank first, momentum breaks ties


# ---------------------------------------------------------------- stock panel
def test_stock_panel_excludes_the_holdout_and_joins_only_out_of_sample_tier1() -> None:
    cfg = load_config()
    plain = load_stock_panel(cfg)
    assert not set(plain.frame["fiscal_year"]) & cfg.locked_fiscal_years
    assert plain.features == STOCK_FEATURES
    t1 = pd.DataFrame({"budget_id": ["FY2015-16"] * 2, "entity": ["fmcg", "power"], "t1_rank_score": [0.5, 0.9],
                       "t1_expected": [0.0, 0.1], "t1_p_beat": [0.5, 0.6]})
    joined = load_stock_panel(cfg, t1)
    assert set(joined.frame["budget_id"]) == {"FY2015-16"} and set(joined.frame["sector_id"]) == {"fmcg", "power"}
    assert "t1_rank_score" in joined.features
    for budget in ("FY2018-19",):
        train = training_rows(plain, budget)
        assert (train["fiscal_year"].astype(str) < "2018-19").all() and (train["label_end"] <= plain.frame.loc[plain.frame["budget_id"] == budget, "day0"].iloc[0]).all()


# ---------------------------------------------------------------- committed reports
def test_models_report_and_prediction_files_have_the_required_outputs() -> None:
    text = (ROOT / "reports" / "models.md").read_text(encoding="utf-8")
    for name in ("lgbm_ranker", "bayes_hier", "tier1_blend", "tier2_ranker", "ridge", "equal_weight", "Not built, and why", "survivorship"):
        assert name in text
    sector = pd.read_csv(ROOT / "reports" / "models_predictions_sector.csv")
    assert {"expected", "rank", "p_beat", "lo", "hi", "score"} <= set(sector.columns)  # FR-8: expected return, rank, P(beat)
    assert sector.groupby(["model", "budget_id"])["rank"].apply(lambda r: sorted(r) == list(range(1, len(r) + 1))).all()
    cfg = load_config()
    stock = pd.read_csv(ROOT / "reports" / "models_predictions_stock.csv")
    assert not set(sector["budget_id"]) & {"FY2024-25", "FY2025-26", "FY2026-27"} and "FY2024-25" not in set(stock["budget_id"])
    assert cfg.holdout_unlocked is False


# ---------------------------------------------------------------- learned stack
def test_learned_stack_weight_uses_only_resolved_earlier_folds() -> None:
    from bsp.models.ensemble import learned_stack

    budgets, frames_a, frames_b = [], [], []
    for i in range(7):  # model A ranks perfectly, model B ranks backwards, in every budget
        budget = f"B{i}"
        budgets.append({"budget_id": budget, "presented_on": f"2020-0{i + 1}-01", "day0": f"2020-0{i + 1}-02",
                        "label_end": f"2020-0{i + 2}-02"})
        actual = [0.3, 0.2, 0.1, 0.0, -0.1]
        base = pd.DataFrame({"budget_id": budget, "entity": list("abcde"), "sector_id": list("abcde"), "is_control": False,
                             "actual": actual, "expected": actual, "p_beat": 0.5, "lo": -1.0, "hi": 1.0})
        frames_a.append(base.assign(score=[5.0, 4, 3, 2, 1]))
        frames_b.append(base.assign(score=[1.0, 2, 3, 4, 5]))
    stacked, weights = learned_stack({"a": pd.concat(frames_a), "b": pd.concat(frames_b)}, pd.DataFrame(budgets))
    weights = weights.set_index("budget_id")
    assert weights.loc["B0", "weight_first"] == 0.5 and weights.loc["B2", "weight_first"] == 0.5  # fewer than 3 resolved folds
    assert weights.loc["B3", "n_past_folds"] == 3 and weights.loc["B3", "weight_first"] > 0.5  # B2's label resolves on B3's day 0
    assert weights.loc["B6", "n_past_folds"] == 6 and weights.loc["B6", "weight_first"] == 0.75  # first grid value reaching IC = 1
    assert len(stacked) == 35 and stacked["score"].notna().all()
