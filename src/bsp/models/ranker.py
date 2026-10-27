"""LightGBM LambdaRank rankers and their Optuna tuning (README Phase 5, Tier 1 and Tier 2).

* Relevance labels: LambdaRank needs integer grades, so within each query group (one budget for sectors, one
  budget x sector for stocks) the 12m excess return is turned into quintile grades 0-4 by rank. Ties share a grade.
* Trees are shallow (depth <= 3) and the data is tiny, so results are noisy: this is stated in reports/models.md.
* Missing values are passed to LightGBM as NaN: it learns a default direction for them at each split. No row is dropped.
* Determinism: ``n_jobs=1``, ``deterministic=True`` and fixed seeds; two runs give identical predictions.
* Tuning (``make_ranker_tuner``) runs inside each walk-forward fold on the training rows only. Its inner validation is
  itself an expanding walk-forward over the training budgets (``inner_folds``), so a validation label never uses
  returns from before-the-fact rows and the search never sees the outer test budget.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
from scipy.stats import norm, rankdata

from bsp.evaluation import metrics

GRADES = 5
DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 60, "learning_rate": 0.05, "num_leaves": 4, "max_depth": 2, "min_child_samples": 10,
    "reg_lambda": 5.0, "colsample_bytree": 0.8,
}


def relevance_grades(values: np.ndarray, grades: int = GRADES) -> np.ndarray:
    """Quintile grades (0 = worst) from ranks within one group; ties share the average rank."""
    n = len(values)
    if n == 0:
        return np.array([], dtype=int)
    ranks = rankdata(values, method="average")
    return np.clip(np.floor((ranks - 1) / n * grades), 0, grades - 1).astype(int)


def inner_folds(train: pd.DataFrame, min_train_budgets: int = 3) -> Iterator[tuple[pd.DataFrame, pd.DataFrame]]:
    """Expanding walk-forward inside the training rows: validate on budget b using only rows resolved before b."""
    order = train.drop_duplicates("budget_id").sort_values("presented_on")
    for row in order.itertuples():
        past = train[(train["fiscal_year"].astype(str) < str(row.fiscal_year)) & (train["presented_on"] < row.presented_on)
                     & (train["label_end"] <= row.day0)]
        if past["budget_id"].nunique() >= min_train_budgets:
            yield past, train[train["budget_id"] == row.budget_id]


def _groups(frame: pd.DataFrame, group_cols: Sequence[str]) -> tuple[pd.DataFrame, list[int]]:
    ordered = frame.sort_values([*group_cols, "entity"], kind="mergesort").reset_index(drop=True)
    sizes = ordered.groupby(list(group_cols), sort=False).size().tolist()
    return ordered, sizes


def _grade_column(frame: pd.DataFrame, group_cols: Sequence[str]) -> np.ndarray:
    grades = np.zeros(len(frame), dtype=int)
    for _, index in frame.groupby(list(group_cols), sort=False).indices.items():
        grades[index] = relevance_grades(frame["excess_return"].to_numpy(dtype=float)[index])
    return grades


class LGBMRankerModel:
    """LambdaRank ranker. With ``with_forecast`` it also fits a shallow regressor for the expected excess return,
    and turns that into ``p_beat`` (P(excess return > 0)) and an interval using out-of-fold residuals."""

    selects_all = False

    def __init__(self, group_cols: Sequence[str] = ("budget_id",), seed: int = 42, with_forecast: bool = True,
                 interval_level: float = 0.8, **params: Any) -> None:
        self.group_cols, self.seed, self.with_forecast, self.interval_level = tuple(group_cols), seed, with_forecast, interval_level
        self.params = {**DEFAULT_PARAMS, **params}
        self.features: list[str] = []
        self.ranker: lgb.LGBMRanker | None = None
        self.regressor: lgb.LGBMRegressor | None = None
        self.sigma = 0.0
        self.q_lo = self.q_hi = 0.0

    def _kwargs(self) -> dict[str, Any]:
        return {**self.params, "random_state": self.seed, "n_jobs": 1, "deterministic": True, "force_row_wise": True,
                "verbose": -1}

    def _x(self, frame: pd.DataFrame) -> np.ndarray:
        return frame[self.features].to_numpy(dtype=float)

    def fit(self, train: pd.DataFrame, features: list[str]) -> LGBMRankerModel:
        self.features = list(features)
        ordered, sizes = _groups(train, self.group_cols)
        grades = _grade_column(ordered, self.group_cols)
        self.ranker = lgb.LGBMRanker(objective="lambdarank", **self._kwargs())
        self.ranker.fit(self._x(ordered), grades, group=sizes)
        if self.with_forecast:
            self.regressor = lgb.LGBMRegressor(objective="regression", **self._kwargs())
            self.regressor.fit(self._x(ordered), ordered["excess_return"].to_numpy(dtype=float))
            residuals = self._oof_residuals(train)
            if len(residuals) >= 10:
                tail = (1 - self.interval_level) / 2
                self.sigma = float(np.std(residuals, ddof=1))
                self.q_lo, self.q_hi = (float(np.quantile(residuals, q)) for q in (tail, 1 - tail))
        return self

    def _oof_residuals(self, train: pd.DataFrame) -> np.ndarray:
        out: list[np.ndarray] = []
        folds = list(inner_folds(train)) or list(inner_folds(train, 2))  # the first stock fold has only 3 training budgets
        for inner_train, inner_test in folds:
            model = LGBMRankerModel(self.group_cols, self.seed, True, self.interval_level, **self.params)
            model.features = self.features
            ordered, _ = _groups(inner_train, self.group_cols)
            reg = lgb.LGBMRegressor(objective="regression", **model._kwargs())
            reg.fit(model._x(ordered), ordered["excess_return"].to_numpy(dtype=float))
            out.append(inner_test["excess_return"].to_numpy(dtype=float) - reg.predict(model._x(inner_test)))
        return np.concatenate(out) if out else np.array([])

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        assert self.ranker is not None
        out = pd.DataFrame({"score": self.ranker.predict(self._x(test))})
        if self.with_forecast and self.regressor is not None:
            expected = np.asarray(self.regressor.predict(self._x(test)), dtype=float)
            out["expected"] = expected
            if self.sigma > 0:
                out["p_beat"] = norm.cdf(expected / self.sigma)
                out["lo"], out["hi"] = expected + self.q_lo, expected + self.q_hi
        return out


def _mean_group_ic(model: LGBMRankerModel, test: pd.DataFrame) -> float:
    scores = model.predict(test)["score"].to_numpy()
    actual = test["excess_return"].to_numpy(dtype=float)
    ics = []
    for _, index in test.reset_index(drop=True).groupby(list(model.group_cols), sort=False).indices.items():
        ic = metrics.spearman_ic(scores[index], actual[index])
        if not math.isnan(ic):
            ics.append(ic)
    return float(np.mean(ics)) if ics else float("nan")


def suggest(trial: optuna.Trial) -> dict[str, Any]:
    return {
        "n_estimators": trial.suggest_int("n_estimators", 20, 200, step=20),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 2, 6),
        "max_depth": trial.suggest_int("max_depth", 1, 3),
        "min_child_samples": trial.suggest_int("min_child_samples", 5, 30),
        "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 50.0, log=True),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
    }


def make_ranker_tuner(group_cols: Sequence[str] = ("budget_id",), n_trials: int = 15, seed: int = 42,
                      ) -> Callable[[pd.DataFrame, list[str]], dict[str, Any]]:
    """Tuning hook for the walk-forward: Optuna (TPE, seeded) maximising the mean inner-walk-forward IC."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def tune(train: pd.DataFrame, features: list[str]) -> dict[str, Any]:
        folds = list(inner_folds(train))
        if not folds:
            return dict(DEFAULT_PARAMS)

        def objective(trial: optuna.Trial) -> float:
            params = suggest(trial)
            ics = []
            for inner_train, inner_test in folds:
                model = LGBMRankerModel(group_cols, seed, with_forecast=False, **params).fit(inner_train, features)
                ic = _mean_group_ic(model, inner_test)
                if not math.isnan(ic):
                    ics.append(ic)
            return float(np.mean(ics)) if ics else -1.0

        study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
        study.enqueue_trial(dict(DEFAULT_PARAMS))  # the untuned defaults are always one of the candidates
        study.optimize(objective, n_trials=n_trials)
        return {**DEFAULT_PARAMS, **study.best_params}

    return tune
