"""Expanding-window walk-forward evaluation, sector level (README section 3, rule 5).

For every test budget t (full budgets from ``first_test_fiscal_year``, never a hold-out / live budget):
  * train on rows whose budget came BEFORE t and whose 12m label is already resolved on t's day 0
    (``label_end <= day0(t)``), so no training label ever uses returns from after the prediction date;
  * run the tuning hook on the training rows only (it has no access to the test rows);
  * predict t.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import pandas as pd

from bsp.evaluation.config import EvalConfig
from bsp.evaluation.data import Panel


class Model(Protocol):
    """Anything with fit/predict. ``predict`` returns a frame with a ``score`` column (higher = better) and
    optionally ``expected`` (a calibrated excess-return forecast) and ``lo`` / ``hi`` (interval)."""

    selects_all: bool

    def fit(self, train: pd.DataFrame, features: list[str]) -> Model: ...

    def predict(self, test: pd.DataFrame) -> pd.DataFrame: ...


TuneHook = Callable[[pd.DataFrame, list[str]], dict[str, Any]]


@dataclass
class FoldResult:
    budget_id: str
    n_train_rows: int
    n_train_budgets: int
    params: dict[str, Any]
    predictions: pd.DataFrame
    model: Any = None  # the fitted model of this fold (kept so predictions can be explained, Phase 7)


def test_budgets(panel: Panel, cfg: EvalConfig) -> list[str]:
    """Budgets to predict, oldest first. Locked budgets are never returned (and raise if the panel holds them)."""
    frame = panel.frame
    cfg.assert_not_locked(frame["fiscal_year"].astype(str).unique(), "walk-forward test budgets")
    meta = frame.drop_duplicates("budget_id").sort_values("presented_on")
    eligible = meta[meta["fiscal_year"].astype(str) >= cfg.first_test_fiscal_year]
    return [b for b in eligible["budget_id"] if frame.loc[frame["budget_id"] == b, "target_complete"].any()]


def training_rows(panel: Panel, budget_id: str) -> pd.DataFrame:
    frame = panel.frame
    test_meta = frame.loc[frame["budget_id"] == budget_id].iloc[0]
    train = frame[
        (frame["fiscal_year"].astype(str) < str(test_meta["fiscal_year"]))  # never year t or later
        & (frame["presented_on"] < test_meta["presented_on"])
        & (frame["label_end"] <= test_meta["day0"])
        & frame["target_complete"]
        & frame["excess_return"].notna()
    ]
    return train.copy()


def walk_forward(
    panel: Panel,
    make_model: Callable[..., Model],
    cfg: EvalConfig,
    tune: TuneHook | None = None,
) -> list[FoldResult]:
    """Run every fold. ``make_model(**params)`` builds an unfitted model from the tuning hook's output."""
    np.random.seed(cfg.seed)
    results: list[FoldResult] = []
    for budget_id in test_budgets(panel, cfg):
        train = training_rows(panel, budget_id)
        n_budgets = train["budget_id"].nunique()
        if n_budgets < cfg.min_train_budgets:
            continue
        test = panel.frame[panel.frame["budget_id"] == budget_id].copy()
        assert (train["label_end"] <= test["day0"].iloc[0]).all(), "training label resolves after prediction day"
        assert (train["presented_on"] < test["presented_on"].iloc[0]).all(), "training row is not from the past"
        assert (train["fiscal_year"].astype(str) < str(test["fiscal_year"].iloc[0])).all(), "trained on year t or later"
        params = tune(train, panel.features) if tune is not None else {}
        model = make_model(**params).fit(train, panel.features)
        out = model.predict(test)
        out = out.assign(budget_id=budget_id, entity=test["entity"].to_numpy(), sector_id=test["sector_id"].to_numpy(),
                         is_control=test["is_control"].to_numpy(), actual=test["excess_return"].to_numpy())
        results.append(FoldResult(budget_id, len(train), n_budgets, params, out, model))
    return results


def stack_predictions(results: list[FoldResult]) -> pd.DataFrame:
    return pd.concat([r.predictions for r in results], ignore_index=True)
