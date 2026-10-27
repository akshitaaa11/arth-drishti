"""Phase 7: attributions, three reasons, walk-forward conformal intervals, the predictions table and its database load."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from bsp.common.db import create_engine
from bsp.evaluation.config import load_config
from bsp.evaluation.data import load_sector_panel
from bsp.evaluation.walk_forward import training_rows
from bsp.explain import contributions as con
from bsp.explain.build import PREDICTION_COLUMNS, model_version
from bsp.explain.conformal import conformal_intervals, coverage_table
from bsp.explain.reasons import format_value, reasons_for
from bsp.ingest.load import load_prediction_csv
from bsp.models.bayes import BayesHierarchical
from bsp.models.ranker import LGBMRankerModel

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- reasons
def test_reasons_are_exactly_three_ordered_by_size_with_numbers_and_sources() -> None:
    contributions = {"alloc_vs_prev_re_pct": 0.031, "momentum_12m": -0.062, "credibility_pct": 0.004, "beta_250d": 0.04}
    values = {"alloc_vs_prev_re_pct": 12.44, "momentum_12m": -0.091, "credibility_pct": 3.0, "beta_250d": 1.234}
    bullets = reasons_for(contributions, values)
    assert len(bullets) == 3
    assert bullets[0].startswith("Price return over the last 12 months is -9.1%, which lowered the expected excess return by 6.2 percentage points")
    assert "beta" in bullets[1].lower() and "raised" in bullets[1] and "1.23" in bullets[1]
    assert "+12.4%" in bullets[2] and "sector_budget_panel.csv" in bullets[2]
    assert all("source:" in b for b in bullets)
    assert not any("credibility" in b.lower() for b in bullets)  # the smallest contribution is left out


def test_missing_values_are_said_to_be_missing_and_ties_break_by_name() -> None:
    bullets = reasons_for({"b_feat": 0.01, "a_feat": 0.01, "fpi_net_equity_1m_cr": -0.02, "zz": 0.0}, {"fpi_net_equity_1m_cr": None})
    assert "was not available" in bullets[0] and "Rs" not in bullets[0]
    assert bullets[1].startswith("A_feat") and bullets[2].startswith("B_feat")  # unknown names fall back to the feature name
    assert "feature store" in bullets[1]


def test_reasons_need_three_features_and_formats_are_right() -> None:
    with pytest.raises(ValueError, match="at least 3"):
        reasons_for({"a": 1.0, "b": 2.0}, {})
    assert format_value(0.1234, "frac_pct") == "+12.3%" and format_value(-5.0, "pct") == "-5.0%"
    assert format_value(12345.6, "crore") == "Rs 12,346 crore" and format_value(1.0, "flag") == "yes"
    assert format_value(float("nan"), "number") == "not available"


# ---------------------------------------------------------------- attributions
@pytest.fixture(scope="module")
def fold():
    cfg = load_config()
    panel = load_sector_panel(cfg)
    train = training_rows(panel, "FY2018-19")
    test = panel.frame[panel.frame["budget_id"] == "FY2018-19"].reset_index(drop=True)
    return panel, train, test


def test_lightgbm_attributions_add_up_to_the_forecast_and_the_rank_score(fold) -> None:
    panel, train, test = fold
    model = LGBMRankerModel(seed=42).fit(train, panel.features)
    expected = con.lgbm_expected_attribution(model, test)
    np.testing.assert_allclose(expected.predicted(), model.predict(test)["expected"].to_numpy(), atol=1e-8)
    rank = con.lgbm_rank_attribution(model, test)
    np.testing.assert_allclose(rank.predicted(), model.predict(test)["score"].to_numpy(), atol=1e-8)
    assert list(expected.contrib.columns) == panel.features


def test_bayes_attribution_matches_the_forecast_up_to_monte_carlo_noise() -> None:
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({"budget_id": np.repeat([f"B{i}" for i in range(10)], 5), "entity": list("abcde") * 10,
                          "alloc_vs_prev_re_pct": rng.normal(size=50), "momentum_12m": rng.normal(size=50),
                          "credibility_pct": rng.normal(size=50)})
    frame["excess_return"] = 0.3 * frame["alloc_vs_prev_re_pct"] + 0.05 * rng.normal(size=50)
    model = BayesHierarchical(seed=1, draws=300, tune=300, chains=2).fit(frame, [])
    test = frame.head(5)
    attribution = con.bayes_attribution(model, test)
    assert set(attribution.contrib.columns) == {"alloc_vs_prev_re_pct", "momentum_12m", "credibility_pct"}
    assert np.abs(attribution.predicted() - model.predict(test)["expected"].to_numpy()).max() < 0.05


def test_combine_is_the_weighted_mean_and_missing_features_count_as_zero() -> None:
    a = con.Attribution(np.array([1.0, 1.0]), pd.DataFrame({"x": [0.2, 0.4], "y": [0.1, 0.1]}))
    b = con.Attribution(np.array([3.0, 3.0]), pd.DataFrame({"x": [0.0, 0.0]}))
    mixed = con.combine([(0.75, a), (0.25, b)])
    np.testing.assert_allclose(mixed.base, [1.5, 1.5])
    np.testing.assert_allclose(mixed.contrib["x"], [0.15, 0.3])
    np.testing.assert_allclose(mixed.contrib["y"], [0.075, 0.075])
    np.testing.assert_allclose(mixed.predicted(), 0.75 * a.predicted() + 0.25 * b.predicted())


# ---------------------------------------------------------------- conformal intervals
def _world(n_budgets: int = 8, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_budgets):
        for j in range(15):
            e = rng.normal(0, 0.2)
            rows.append({"budget_id": f"B{i}", "entity": f"s{j}", "expected": e, "actual": e + rng.normal(0, 0.3),
                         "lo": e - 0.3, "hi": e + 0.3})
    budgets = pd.DataFrame({"budget_id": [f"B{i}" for i in range(n_budgets)],
                            "presented_on": [f"2020-{i + 1:02d}-01" for i in range(n_budgets)],
                            "day0": [f"2020-{i + 1:02d}-02" for i in range(n_budgets)],
                            "label_end": [f"2020-{i + 2:02d}-02" if i < n_budgets - 1 else "2021-06-01" for i in range(n_budgets)]})
    return pd.DataFrame(rows), budgets


def test_conformal_uses_the_fallback_until_three_budgets_are_resolved_and_always_gives_an_interval() -> None:
    predictions, budgets = _world()
    out = conformal_intervals(predictions, budgets)
    methods = out.groupby("budget_id")["interval_method"].first()
    assert methods["B0"] == methods["B1"] == methods["B2"] == "oof_residual"
    assert methods["B3"] == methods["B7"] == "conformal_walk_forward"
    assert out[["p10", "p90"]].notna().all().all() and (out["p10"] < out["p90"]).all()
    covered = coverage_table(out[out["budget_id"].isin(["B5", "B6", "B7"])], ["interval_method"])
    assert 0.65 <= covered["coverage"].iloc[0] <= 0.95  # about 80% on iid errors, 45 forecasts so loose bounds


def test_conformal_interval_ignores_the_labels_of_its_own_and_later_budgets() -> None:
    predictions, budgets = _world()
    base = conformal_intervals(predictions, budgets)
    scrambled = predictions.copy()
    late = scrambled["budget_id"].isin(["B5", "B6", "B7"])
    scrambled.loc[late, "actual"] = scrambled.loc[late, "actual"].to_numpy()[::-1] + 5.0
    again = conformal_intervals(scrambled, budgets)
    early = base["budget_id"].isin(["B0", "B1", "B2", "B3", "B4", "B5"])  # B5's calibration uses B0..B4 only
    np.testing.assert_allclose(base.loc[early, ["p10", "p90"]], again.loc[early, ["p10", "p90"]])
    assert not np.allclose(base.loc[base["budget_id"] == "B7", "p10"], again.loc[again["budget_id"] == "B7", "p10"])


def test_a_budget_whose_label_is_not_yet_resolved_is_not_used_for_calibration() -> None:
    predictions, budgets = _world()
    budgets.loc[budgets["budget_id"] == "B3", "label_end"] = "2020-12-31"  # B3's outcome is unknown until the end of the year
    out = conformal_intervals(predictions, budgets)
    scrambled = predictions.copy()
    scrambled.loc[scrambled["budget_id"] == "B3", "actual"] += 9.0
    again = conformal_intervals(scrambled, budgets)
    after = out["budget_id"].isin(["B4", "B5", "B6"])  # these predate the resolution of B3
    np.testing.assert_allclose(out.loc[after, "p90"], again.loc[after, "p90"])


# ---------------------------------------------------------------- committed outputs
def test_predictions_table_meets_the_phase_7_exit_criteria() -> None:
    table = pd.read_csv(ROOT / "data" / "csv" / "predictions.csv")
    assert list(table.columns) == PREDICTION_COLUMNS
    assert not table.duplicated(["model_version", "entity", "budget_id"]).any()
    reasons = table["top_reasons"].map(json.loads)
    assert (reasons.map(len) == 3).all() and all(isinstance(r, str) and "source:" in r for rs in reasons for r in rs)
    assert table[["expected_excess", "p10", "p90", "p_beat", "rank"]].notna().all().all()
    assert (table["p10"] < table["p90"]).all() and table["p_beat"].between(0, 1).all()
    assert table.groupby(["model_version", "budget_id"])["rank"].apply(lambda r: sorted(r) == list(range(1, len(r) + 1))).all()
    assert not set(table["budget_id"]) & {"FY2024-25", "FY2025-26", "FY2026-27"}  # hold-out and live year untouched
    assert table["model_version"].str.split("/").str[0].nunique() == 5


def test_model_version_hash_matches_the_current_inputs() -> None:
    table = pd.read_csv(ROOT / "data" / "csv" / "predictions.csv")
    expected = {model_version(m, 42, ROOT) for m in ("lgbm_ranker", "bayes_hier", "tier1_blend", "tier1_stack", "tier2_ranker")}
    assert set(table["model_version"]) == expected  # the predictions were built from the committed feature files


def test_interval_coverage_is_reported_by_year_and_regime() -> None:
    by_year = pd.read_csv(ROOT / "reports" / "interval_coverage_by_year.csv")
    by_regime = pd.read_csv(ROOT / "reports" / "interval_coverage_by_regime.csv")
    assert {"coverage", "mean_width", "native_coverage"} <= set(by_year.columns)
    assert {"all test years"} <= set(by_year["budget_id"]) and by_year["budget_id"].nunique() >= 13
    assert set(by_regime["regime"]) == {"election_year", "covid_era", "high_vix"}
    assert "PASS" in (ROOT / "reports" / "explainability.md").read_text(encoding="utf-8")


def test_shap_files_add_up_per_prediction() -> None:
    shap_sector = pd.read_csv(ROOT / "reports" / "shap_values_sector.csv")
    one = shap_sector[(shap_sector["model"] == "lgbm_ranker") & (shap_sector["target"] == "expected_return")]
    grouped = one.groupby(["budget_id", "entity"]).agg(base=("base", "first"), total=("shap", "sum")).reset_index()
    stored = pd.read_csv(ROOT / "reports" / "predictions_detail.csv")
    stored = stored[stored["model"] == "lgbm_ranker"][["budget_id", "entity", "expected"]]
    merged = grouped.merge(stored, on=["budget_id", "entity"])
    assert len(merged) == len(stored) == 180
    np.testing.assert_allclose(merged["base"] + merged["total"], merged["expected"], atol=1e-6)


# ---------------------------------------------------------------- database
def test_predictions_load_is_idempotent_and_matches_the_csv(tmp_path: Path, monkeypatch) -> None:
    url = f"sqlite:///{(tmp_path / 'bsp.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    source = pd.read_csv(ROOT / "data" / "csv" / "predictions.csv")
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    source.to_csv(csv_dir / "predictions.csv", index=False)
    assert load_prediction_csv(url, csv_dir) == len(source) == load_prediction_csv(url, csv_dir)
    with create_engine(database_url=url).connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM predictions")).scalar() == len(source)
        row = conn.execute(text("SELECT top_reasons, p10, p90 FROM predictions LIMIT 1")).one()
    assert len(json.loads(row[0])) == 3 and row[1] < row[2]
    assert load_prediction_csv(url, tmp_path / "nothing") == 0
