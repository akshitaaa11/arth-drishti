"""Phase 4: metrics, walk-forward folds, hold-out lock, backtest arithmetic and reproducibility."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bsp.evaluation import metrics
from bsp.evaluation.backtest import run_backtest, top_k_selection
from bsp.evaluation.config import HoldoutLockedError, load_config
from bsp.evaluation.data import Panel, load_sector_panel
from bsp.evaluation.walk_forward import test_budgets as list_test_budgets
from bsp.evaluation.walk_forward import training_rows, walk_forward
from bsp.models.baselines import (
    EqualWeight,
    RidgeBaseline,
    make_ridge_tuner,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- metrics (values worked out by hand)
def test_spearman_ic_perfect_reversed_and_undefined() -> None:
    actual = np.array([1.0, 2.0, 3.0, 4.0])
    assert metrics.spearman_ic(np.array([10, 20, 30, 40]), actual) == pytest.approx(1.0)
    assert metrics.spearman_ic(np.array([4, 3, 2, 1]), actual) == pytest.approx(-1.0)
    assert np.isnan(metrics.spearman_ic(np.zeros(4), actual))  # constant score (equal weight) has no rank signal


def test_top_k_hit_rate_and_precision_at_k() -> None:
    actual = np.array([0.5, 0.4, 0.3, 0.2, 0.1, 0.0, -0.1, -0.2])
    good = np.array([8, 7, 6, 5, 4, 3, 2, 1])
    assert metrics.top_k_hit_rate(good, actual, 3) == 1.0
    assert metrics.top_k_hit_rate(-good, actual, 3) == 0.0
    # predicted top-5 = actual best five (0.5 .. 0.1); the median of actual is 0.15, so 4 of the 5 beat it
    assert metrics.precision_at_k(good, actual, 5) == pytest.approx(0.8)
    assert metrics.precision_at_k(-good, actual, 5) == pytest.approx(0.2)  # reversed top-5: only 0.2 beats 0.15


def test_ndcg_mae_directional_and_interval_metrics() -> None:
    actual = np.array([3.0, 1.0, 2.0])
    assert metrics.ndcg_at_k(np.array([3.0, 1.0, 2.0]), actual, 3) == pytest.approx(1.0)
    assert metrics.ndcg_at_k(np.array([1.0, 3.0, 2.0]), actual, 3) < 1.0
    pred = np.array([0.1, -0.2, 0.3])
    truth = np.array([0.2, 0.1, 0.0])
    assert metrics.mae(pred, truth) == pytest.approx((0.1 + 0.3 + 0.3) / 3)
    assert metrics.directional_accuracy(pred, truth) == pytest.approx(1 / 3)
    lo, hi = np.array([0.0, 0.0, 0.0]), np.array([1.0, 1.0, 1.0])
    assert metrics.interval_coverage(lo, hi, np.array([0.5, 2.0, 0.9, ])) == pytest.approx(2 / 3)
    assert metrics.interval_width(lo, hi) == 1.0


# ---------------------------------------------------------------- backtest arithmetic
def test_backtest_gross_net_cost_and_turnover() -> None:
    days = [f"2020-01-{d:02d}" for d in range(1, 11)]
    levels = pd.DataFrame({"A": np.linspace(100, 110, 10), "B": np.linspace(100, 90, 10)}, index=days)
    windows = pd.DataFrame({"budget_id": ["w1", "w2"], "start": ["2020-01-01", "2020-01-06"],
                            "label_end": ["2020-01-04", "2020-01-10"]})
    result = run_backtest({"w1": ["A"], "w2": ["B"]}, windows, levels, 0.002)
    p = result.periods.set_index("budget_id")
    assert p.loc["w1", "gross_return"] == pytest.approx(levels["A"].iloc[3] / levels["A"].iloc[0] - 1)
    assert p.loc["w1", "net_return"] == pytest.approx((1 + p.loc["w1", "gross_return"]) * 0.999**2 - 1)  # 0.1% on each side
    assert p.loc["w2", "turnover"] == 1.0  # the whole portfolio changed
    # cash days between the windows earn nothing
    assert result.daily.loc["2020-01-05"] == 0.0


def test_top_k_selection_is_deterministic_and_equal_weight_takes_all() -> None:
    preds = pd.DataFrame({"budget_id": ["b"] * 4, "entity": ["d", "c", "b", "a"], "score": [1.0, 1.0, 0.5, 0.0]})
    assert top_k_selection(preds, 2, False) == {"b": ["c", "d"]}  # tie broken by name
    assert top_k_selection(preds, 2, True)["b"] == ["c", "d", "b", "a"]


# ---------------------------------------------------------------- walk-forward on a hand-made panel
def _toy_panel(n_budgets: int = 8, per_budget: int = 6) -> Panel:
    rng = np.random.default_rng(0)
    rows = []
    for i in range(n_budgets):
        for j in range(per_budget):
            rows.append({
                "budget_id": f"B{i:02d}", "fiscal_year": f"20{10 + i}-{11 + i}", "entity": f"E{j}", "sector_id": "S",
                "presented_on": f"20{10 + i}-02-01", "day0": f"20{10 + i}-02-01", "start": f"20{10 + i}-02-02",
                "label_end": f"20{11 + i}-02-01", "x": rng.normal(), "excess_return": rng.normal(),
                "target_complete": True, "is_control": j == 0,
            })
    return Panel("sector", pd.DataFrame(rows), ["x"])


def test_walk_forward_trains_only_on_resolved_past_labels_and_tunes_inside_the_fold() -> None:
    cfg = load_config(first_test_fiscal_year="2013-14", holdout_fiscal_years=(), live_fiscal_years=())
    panel = _toy_panel()
    seen: list[tuple[str, str, int]] = []

    def tune(train: pd.DataFrame, features: list[str]) -> dict:
        seen.append((train["presented_on"].max(), train["label_end"].max(), len(train)))
        return {}

    folds = walk_forward(panel, lambda: RidgeBaseline(with_interval=False), cfg, tune)
    assert [f.budget_id for f in folds] == [f"B{i:02d}" for i in range(3, 8)]
    for fold, (max_presented, max_label_end, _) in zip(folds, seen, strict=True):
        test_day0 = panel.frame.loc[panel.frame["budget_id"] == fold.budget_id, "day0"].iloc[0]
        assert max_presented < test_day0 and max_label_end <= test_day0  # no label from the future
    assert [f.n_train_budgets for f in folds] == [3, 4, 5, 6, 7]  # expanding window


def test_test_budgets_respect_first_test_year() -> None:
    cfg = load_config(first_test_fiscal_year="2014-15", holdout_fiscal_years=(), live_fiscal_years=())
    assert list_test_budgets(_toy_panel(), cfg)[0] == "B04"


def test_ridge_tuner_picks_from_grid_and_ridge_predicts_with_interval() -> None:
    panel = _toy_panel(n_budgets=6)
    train = panel.frame[panel.frame["budget_id"] < "B05"]
    params = make_ridge_tuner((0.1, 10.0, 1000.0))(train, ["x"])
    assert params["alpha"] in (0.1, 10.0, 1000.0)
    model = RidgeBaseline(**params).fit(train, ["x"])
    out = model.predict(panel.frame[panel.frame["budget_id"] == "B05"])
    assert {"score", "expected", "lo", "hi"} <= set(out.columns) and (out["hi"] > out["lo"]).all()


# ---------------------------------------------------------------- hold-out lock on the real data
def test_default_panel_contains_no_holdout_or_live_budget_and_loading_them_raises() -> None:
    cfg = load_config()
    panel = load_sector_panel(cfg)
    assert not set(panel.frame["fiscal_year"].astype(str)) & cfg.locked_fiscal_years
    assert "FY2024-25-I" not in set(panel.frame["budget_id"])  # interim budgets of a locked year are locked too
    with pytest.raises(HoldoutLockedError, match="locked hold-out"):
        load_sector_panel(cfg, include_locked=True)


def test_unlocking_flag_allows_holdout_rows() -> None:
    cfg = load_config(holdout_unlocked=True, holdout_spent=False)  # the real config is now spent; this exercises only the loader gate
    assert "FY2024-25" in set(load_sector_panel(cfg, include_locked=True).frame["budget_id"])


def test_walk_forward_refuses_a_panel_that_contains_locked_budgets() -> None:
    locked = _toy_panel(n_budgets=3)
    cfg = load_config(holdout_fiscal_years=("2012-13",), live_fiscal_years=())
    with pytest.raises(HoldoutLockedError):
        walk_forward(locked, lambda: EqualWeight(), cfg)


# ---------------------------------------------------------------- consistency with the Phase 3 targets
def test_backtest_window_returns_reproduce_the_published_12m_targets() -> None:
    """Sector gross window return minus the market's over the same window equals targets.csv (12m)."""
    from bsp.evaluation.data import budget_calendar, trading_days
    from bsp.features.baskets import build_market_data_bundle

    bundle = build_market_data_bundle(ROOT)
    calendar = budget_calendar(ROOT, trading_days(ROOT)).set_index("budget_id")
    sector_levels = (1 + bundle.sector_returns.fillna(0.0)).cumprod()
    market_level = pd.DataFrame({"M": (1 + bundle.market_returns.fillna(0.0)).cumprod()})
    targets = pd.read_csv(ROOT / "data" / "csv" / "targets.csv")
    targets = targets[(targets["entity_type"] == "sector") & (targets["horizon"] == "12m")]
    for budget_id, sector in (("FY2016-17", "fmcg"), ("FY2021-22", "defence"), ("FY2022-23", "psu_banks")):
        row = calendar.loc[budget_id]
        window = pd.DataFrame({"budget_id": [budget_id], "start": [row["start"]], "label_end": [row["label_end"]]})
        sector_gross = run_backtest({budget_id: [sector]}, window, sector_levels, 0.0).periods["gross_return"].iloc[0]
        market_gross = run_backtest({budget_id: ["M"]}, window, market_level, 0.0).periods["gross_return"].iloc[0]
        published = targets[(targets["entity"] == sector) & (targets["budget_id"] == budget_id)]["excess_return"].iloc[0]
        assert sector_gross - market_gross == pytest.approx(published, abs=1e-6)


# ---------------------------------------------------------------- the split never trains on year t or later
def test_every_real_fold_trains_only_on_earlier_fiscal_years_and_resolved_complete_labels() -> None:
    cfg = load_config()
    panel = load_sector_panel(cfg)
    folds = walk_forward(panel, lambda: EqualWeight(), cfg)
    assert [f.budget_id for f in folds][0] == "FY2012-13" and len(folds) == 12
    for fold in folds:
        test = panel.frame[panel.frame["budget_id"] == fold.budget_id].iloc[0]
        train = training_rows(panel, fold.budget_id)
        assert len(train) and train["target_complete"].all() and train["excess_return"].notna().all()
        assert (train["fiscal_year"].astype(str) < str(test["fiscal_year"])).all()  # not year t, not later
        assert (train["presented_on"] < test["presented_on"]).all()
        assert (train["label_end"] <= test["day0"]).all()  # every training label resolved before the prediction day
        assert fold.n_train_budgets == train["budget_id"].nunique()


def test_incomplete_labels_are_excluded_from_training() -> None:
    panel = _toy_panel()
    frame = panel.frame.copy()
    frame.loc[(frame["budget_id"] == "B03") & (frame["entity"] == "E0"), "target_complete"] = False
    frame.loc[(frame["budget_id"] == "B04") & (frame["entity"] == "E1"), "excess_return"] = np.nan
    train = training_rows(Panel("sector", frame, ["x"]), "B07")
    assert len(train) == len(panel.frame[panel.frame["budget_id"] < "B07"]) - 2
    assert train["target_complete"].all()


# ---------------------------------------------------------------- control sector
def test_control_sector_is_flagged_and_excluded_from_the_headline_cross_section() -> None:
    from bsp.evaluation.run_baselines import ModelRun, _control_rows, control_summary

    cfg = load_config()
    panel = load_sector_panel(cfg)
    assert set(panel.frame.loc[panel.frame["is_control"], "entity"]) == {"it_control"}
    preds = pd.DataFrame({
        "budget_id": ["b1"] * 4 + ["b2"] * 4, "entity": ["c", "a", "b", "d"] * 2,
        "is_control": [True, False, False, False] * 2,
        "score": [4.0, 3.0, 2.0, 1.0, 1.0, 2.0, 3.0, 4.0], "actual": [0.1, 0.4, 0.3, 0.2, 0.4, 0.3, 0.2, 0.1],
    })
    control = _control_rows(preds)
    assert list(control["predicted_rank"]) == [1.0, 4.0] and list(control["actual_rank"]) == [4.0, 1.0]
    summary = control_summary(ModelRun("m", preds, pd.DataFrame(), {}, None, control, {}))  # type: ignore[arg-type]
    assert summary["mean_predicted_rank"] == 2.5 and summary["years_in_predicted_top3"] == 1.0


# ---------------------------------------------------------------- reproducibility and headline universe
def test_baselines_are_reproducible_and_headline_portfolios_exclude_the_control(tmp_path: Path) -> None:
    from bsp.evaluation.run_baselines import run

    first, second = tmp_path / "a", tmp_path / "b"
    runs = run(use_mlflow=False, report_dir=first)
    run(use_mlflow=False, report_dir=second)
    for name in ("baselines_summary.csv", "baselines_per_year.csv", "baselines_predictions_sector.csv",
                 "baselines_control_sector.csv", "baselines.md"):
        assert (first / name).read_bytes() == (second / name).read_bytes(), name
    by_name = {r.name: r for r in runs}
    assert set(by_name["equal_weight"].backtest.periods["n_held"]) == {14}  # 15 sectors minus the control
    assert set(by_name["ridge"].backtest.periods["n_held"]) == {3}
    predictions = pd.read_csv(first / "baselines_predictions_sector.csv")
    assert predictions.groupby(["model", "budget_id"]).size().eq(15).all()  # the control is still predicted
    assert "IT Services (control sector), reported separately" in (first / "baselines.md").read_text(encoding="utf-8")
    assert max(predictions["budget_id"]) == "FY2023-24"  # nothing from the hold-out
