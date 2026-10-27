"""Phase 8: statistics helpers, feature families, DiD mechanics, event-effect tests, backtest lab and the committed evidence files."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bsp.evaluation.config import load_config
from bsp.evaluation.data import SECTOR_FEATURES
from bsp.evidence import regimes
from bsp.evidence.ablation import load_families, variant_features
from bsp.evidence.did import N_TREATED, _did, _match
from bsp.evidence.event_effects import sector_event_effects
from bsp.evidence.stats import benjamini_hochberg, paired_difference, summarise
from bsp.features.speech_features import SPEECH_FEATURES

ROOT = Path(__file__).resolve().parents[1]
LOCKED = {"FY2024-25", "FY2025-26", "FY2026-27"}


# ---------------------------------------------------------------- statistics
def test_summarise_matches_hand_values_and_is_seeded() -> None:
    s = summarise([0.1, 0.3, 0.2, 0.4])
    assert s.n == 4 and s.mean == pytest.approx(0.25)
    sd = np.std([0.1, 0.3, 0.2, 0.4], ddof=1)
    assert s.t_stat == pytest.approx(0.25 / (sd / 2))
    assert s.lo < s.mean < s.hi and s.p_two_sided == pytest.approx(2 * s.p_one_sided_positive)
    assert summarise([0.1, 0.3, 0.2, 0.4]) == s  # same seed, same bootstrap
    assert summarise([1.0, float("nan"), 3.0]).n == 2 and math.isnan(summarise([1.0]).t_stat)


def test_paired_difference_pairs_by_position_and_drops_missing() -> None:
    d = paired_difference([1.0, 2.0, np.nan, 4.0], [0.5, 1.0, 9.0, 3.0])
    assert d.n == 3 and d.mean == pytest.approx((0.5 + 1.0 + 1.0) / 3)


def test_benjamini_hochberg_by_hand() -> None:
    q = benjamini_hochberg([0.01, 0.04, 0.03, 0.2])
    np.testing.assert_allclose(q, [0.04, 0.04 * 4 / 3, 0.04 * 4 / 3, 0.2])
    assert np.isnan(benjamini_hochberg([0.5, np.nan])[1]) and benjamini_hochberg([0.5, np.nan])[0] == 0.5
    assert (benjamini_hochberg(np.random.default_rng(0).uniform(size=50)) >= 0).all()


# ---------------------------------------------------------------- feature families
def test_every_panel_feature_is_in_exactly_one_family_and_ablations_remove_only_that_family() -> None:
    families = load_families(ROOT)
    members = [f for feats in families["families"].values() for f in feats]
    assert len(members) == len(set(members))  # no feature in two families
    assert set(SECTOR_FEATURES) <= set(members) and set(SPEECH_FEATURES) <= set(members)
    variants = variant_features(SECTOR_FEATURES, families)
    for name, feats in families["families"].items():
        removed = set(variants["full"]) - set(variants[f"no_{name}"])
        assert removed == set(feats) & set(SECTOR_FEATURES)
    assert variants["no_speech_nlp"] == variants["full"]  # no speech features in the panel: untestable, skipped by the runner
    assert set(variants["price_plus_budget"]) == set(variants["price_only"]) | set(variants["budget_only"])
    assert not set(variants["price_only"]) & set(variants["budget_only"])


# ---------------------------------------------------------------- difference-in-differences
def test_matching_picks_top_surprises_and_distinct_nearby_controls() -> None:
    sectors = [f"s{i}" for i in range(12)]
    surprise = pd.Series(np.arange(12, dtype=float), index=sectors)  # s11 largest
    momentum = pd.Series([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1], index=sectors)
    volatility = pd.Series(0.02, index=sectors)
    pairs = _match(surprise, momentum, volatility)
    assert [t for t, _ in pairs] == ["s11", "s10", "s9", "s8"] and len(pairs) == N_TREATED
    controls = [c for _, c in pairs]
    assert len(set(controls)) == 4 and all(surprise[c] <= surprise.median() for c in controls)  # below-median, no replacement
    assert controls[0] == "s5"  # the nearest below-median sector in momentum to s11
    assert _match(surprise.iloc[:6], momentum, volatility) == []  # fewer than 10 sectors with a surprise: no matching


def test_did_arithmetic() -> None:
    before = pd.Series({"t1": 0.10, "c1": 0.02, "t2": 0.00, "c2": 0.05})
    after = pd.Series({"t1": 0.30, "c1": 0.12, "t2": 0.10, "c2": 0.05})
    # (0.20 - 0.10) and (0.10 - (-0.00)): mean = 0.10
    assert _did([("t1", "c1"), ("t2", "c2")], before, after) == pytest.approx((0.20 - 0.10 + 0.10 - 0.0) / 2)


def test_did_outputs_exclude_the_holdout_and_report_the_parallel_trends_check() -> None:
    by_budget = pd.read_csv(ROOT / "reports" / "did_by_budget.csv")
    summary = pd.read_csv(ROOT / "reports" / "did_summary.csv")
    assert not set(by_budget["budget_id"]) & LOCKED and by_budget["budget_id"].str.endswith("-I").sum() == 0
    assert list(summary["measure"]) == ["pretrend_did", "did_post60", "did_post120"]
    assert summary["p_permutation"].between(0, 1).all() and (summary["p_permutation"] > 0).all()
    for row in by_budget.itertuples():
        assert len(row.treated.split(",")) == len(set(row.controls.split(","))) == row.n_pairs
        assert not set(row.treated.split(",")) & set(row.controls.split(","))


# ---------------------------------------------------------------- event effects
def test_event_effects_use_unlocked_full_budgets_and_bh_never_lowers_a_p_value() -> None:
    effects = sector_event_effects(load_config())
    assert len(effects) == 75 and effects["n_budgets"].between(10, 19).all() and effects["n_budgets"].max() == 19  # 5 windows x 15 sectors
    assert (effects.groupby("sector")["n_budgets"].nunique() == 1).all()  # a sector has the same budgets in every window
    assert (effects["q_within_window"] >= effects["p_value"] - 1e-12).all() and (effects["q_all_75_tests"] >= effects["p_value"] - 1e-12).all()
    assert (effects["q_within_window"] <= 1).all() and effects["p_value"].between(0, 1).all()
    saved = pd.read_csv(ROOT / "reports" / "event_effects_bh.csv")
    assert len(saved) == 75 and saved["significant_within_window"].sum() == effects["significant_within_window"].sum()


# ---------------------------------------------------------------- regimes
def test_regime_errors_split_by_flag() -> None:
    from bsp.evaluation.backtest import BacktestResult

    rows = []
    for budget, flag, sign in (("B1", 1.0, 1), ("B2", 0.0, -1), ("B3", 0.0, -1)):
        for i in range(5):
            rows.append({"model": "m", "budget_id": budget, "is_control": False, "score": float(i), "actual": sign * float(i),
                         "expected": 0.5 * sign * i})
    preds = pd.DataFrame(rows)
    flags = pd.DataFrame({"budget_id": ["B1", "B2", "B3"], "regime_is_election_year": [1.0, 0.0, 0.0], "regime_is_covid_era": [0.0] * 3,
                          "regime_high_vix": [0.0] * 3})
    periods = pd.DataFrame({"budget_id": ["B1", "B2", "B3"], "net_return": [0.3, 0.1, 0.1]})
    run = BacktestResult(pd.Series(dtype=float), periods, {})
    bench = BacktestResult(pd.Series(dtype=float), pd.DataFrame({"budget_id": ["B1", "B2", "B3"], "net_return": [0.1, 0.1, 0.2]}), {})
    regimes.MODELS = ["m"]
    table = regimes.regime_errors(preds, flags, {"m": run}, bench).set_index(["regime", "flag"])
    assert table.loc[("election_year", "yes"), "mean_ic"] == pytest.approx(1.0) and table.loc[("election_year", "no"), "mean_ic"] == pytest.approx(-1.0)
    assert table.loc[("election_year", "yes"), "mean_top3_excess"] == pytest.approx(0.2)
    assert table.loc[("election_year", "no"), "mean_top3_excess"] == pytest.approx(-0.05)
    assert table.loc[("election_year", "yes"), "n_budgets"] == 1 and table.loc[("election_year", "no"), "n_budgets"] == 2


# ---------------------------------------------------------------- committed outputs
def test_backtest_lab_reproduces_the_phase_4_and_5_portfolio_numbers() -> None:
    lab = pd.read_csv(ROOT / "reports" / "backtest_lab_summary.csv").set_index(["level", "strategy"])
    base = pd.read_csv(ROOT / "reports" / "baselines_summary.csv").set_index("model")
    for model in ("equal_weight", "ridge", "last_years_winners"):
        assert lab.loc[("sector", model), "cagr"] == pytest.approx(base.loc[model, "bt_cagr"], abs=1e-6)
        assert lab.loc[("sector", model), "sharpe"] == pytest.approx(base.loc[model, "bt_sharpe"], abs=1e-6)
    models = pd.read_csv(ROOT / "reports" / "models_summary.csv").set_index(["level", "model"])
    assert lab.loc[("stock", "tier2_ranker"), "cagr"] == pytest.approx(models.loc[("stock", "tier2_ranker"), "bt_cagr"], abs=1e-6)
    equity = pd.read_csv(ROOT / "reports" / "backtest_lab_equity_sector.csv", index_col="date")
    assert equity.iloc[0].between(90, 110).all() and (equity.index <= "2024-02-01").all()  # starts near 100, ends before the hold-out
    assert (lab.loc[("sector", "ridge"), ["cagr_cost_0.0pct", "cagr_cost_0.2pct", "cagr_cost_0.5pct"]].diff().dropna() <= 0).all()  # more cost, less return


def test_the_benchmark_in_the_phase_4_and_5_tables_covers_the_same_windows_as_the_models() -> None:
    lab = pd.read_csv(ROOT / "reports" / "backtest_lab_summary.csv").set_index(["level", "strategy"])
    nifty = lab.loc[("sector", "NIFTY500")]
    assert nifty["n_windows"] == 12 and nifty["first_window"] == "2012-03-19"
    for report in ("baselines.md", "models.md"):
        row = next(ln for ln in (ROOT / "reports" / report).read_text(encoding="utf-8").splitlines() if ln.startswith("| **Nifty 500"))
        assert f"{nifty['cagr'] * 100:.1f}%" in row


def test_evidence_report_answers_the_question_and_never_touches_the_holdout() -> None:
    text = (ROOT / "reports" / "evidence.md").read_text(encoding="utf-8")
    assert "does the budget data add anything beyond price momentum" in text and "**Answer.**" in text
    for section in ("Ablations", "Bootstrap CIs", "Backtest lab", "Benjamini-Hochberg", "difference-in-differences", "Error reports by regime", "Limitations"):
        assert section in text
    for name in ("ablation_per_year_ridge.csv", "ablation_per_year_lgbm_ranker.csv"):
        years = set(pd.read_csv(ROOT / "reports" / name)["budget_id"])
        assert years and not years & LOCKED
    assert json.loads((ROOT / "config" / "evaluation.json").read_text())["holdout_unlocked"] is False
