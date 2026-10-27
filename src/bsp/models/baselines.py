"""Baselines every later model must beat (README Phase 4).

Sector baselines: equal weight, last year's winners, biggest allocation increase, ridge regression.
Stock baselines: equal weight, momentum, ridge regression.
Every model is deterministic; nothing here sees test rows when fitting.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge


class EqualWeight:
    """Hold everything. Its score is constant, so rank metrics are undefined and the portfolio is the whole universe."""

    selects_all = True

    def fit(self, train: pd.DataFrame, features: list[str]) -> EqualWeight:
        return self

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({"score": np.zeros(len(test))})


class SingleFeatureRank:
    """Rank by one pre-budget feature (higher = better). Missing values are scored at the training median."""

    selects_all = False

    def __init__(self, column: str, sign: float = 1.0) -> None:
        self.column, self.sign, self.fill = column, sign, 0.0

    def fit(self, train: pd.DataFrame, features: list[str]) -> SingleFeatureRank:
        self.fill = float(train[self.column].median()) if self.column in train else 0.0
        return self

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        values = test[self.column].astype(float).fillna(self.fill).to_numpy()
        return pd.DataFrame({"score": self.sign * values})


def last_years_winners() -> SingleFeatureRank:
    """Sectors/stocks with the best trailing 12-month return into the budget."""
    return SingleFeatureRank("momentum_12m")


def biggest_allocation_increase() -> SingleFeatureRank:
    """Sectors whose new BE rose most against last year's RE (the budget-surprise feature)."""
    return SingleFeatureRank("alloc_vs_prev_re_pct")


class RidgeBaseline:
    """Ridge on the pre-budget features, predicting the 12m excess return.

    Columns that are mostly missing in the training rows are dropped, the rest are median-imputed and
    standardised using training statistics only. The 80% interval is the forecast plus empirical quantiles of
    out-of-fold residuals (leave-one-budget-out inside the training rows).
    """

    selects_all = False

    def __init__(self, alpha: float = 10.0, interval_level: float = 0.8, min_coverage: float = 0.6,
                 with_interval: bool = True) -> None:
        self.alpha, self.interval_level, self.min_coverage, self.with_interval = alpha, interval_level, min_coverage, with_interval
        self.cols: list[str] = []
        self.stats: pd.DataFrame | None = None
        self.model: Ridge | None = None
        self.q_lo = self.q_hi = 0.0

    # -- design matrix helpers (training statistics only) ------------------------------------------------------
    def _fit_prep(self, train: pd.DataFrame, features: list[str]) -> np.ndarray:
        x = train[features].astype(float)
        self.cols = [c for c in features if x[c].notna().mean() >= self.min_coverage]
        x = x[self.cols]
        med = x.median()
        std = x.fillna(med).std(ddof=0).replace(0, 1.0)
        self.stats = pd.DataFrame({"median": med, "mean": x.fillna(med).mean(), "std": std})
        return self._prep(train)

    def _prep(self, frame: pd.DataFrame) -> np.ndarray:
        assert self.stats is not None
        x = frame[self.cols].astype(float).fillna(self.stats["median"])
        return ((x - self.stats["mean"]) / self.stats["std"]).to_numpy()

    def fit(self, train: pd.DataFrame, features: list[str]) -> RidgeBaseline:
        x = self._fit_prep(train, features)
        y = train["excess_return"].to_numpy(dtype=float)
        self.model = Ridge(alpha=self.alpha).fit(x, y)
        if self.with_interval:
            residuals = _oof_residuals(train, features, self.alpha, self.min_coverage)
            tail = (1 - self.interval_level) / 2
            if len(residuals) >= 10:
                self.q_lo, self.q_hi = (float(np.quantile(residuals, q)) for q in (tail, 1 - tail))
        return self

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        assert self.model is not None
        expected = self.model.predict(self._prep(test))
        out = pd.DataFrame({"score": expected, "expected": expected})
        if self.with_interval:
            out["lo"], out["hi"] = expected + self.q_lo, expected + self.q_hi
        return out


def _oof_residuals(train: pd.DataFrame, features: list[str], alpha: float, min_coverage: float) -> np.ndarray:
    """Leave-one-budget-out residuals of the ridge model, using only the training rows."""
    residuals: list[np.ndarray] = []
    for budget in train["budget_id"].unique():
        inner_train, inner_test = train[train["budget_id"] != budget], train[train["budget_id"] == budget]
        if inner_train["budget_id"].nunique() < 2:
            continue
        model = RidgeBaseline(alpha=alpha, min_coverage=min_coverage, with_interval=False).fit(inner_train, features)
        pred = model.predict(inner_test)["expected"].to_numpy()
        residuals.append(inner_test["excess_return"].to_numpy(dtype=float) - pred)
    return np.concatenate(residuals) if residuals else np.array([])


def make_ridge_tuner(alpha_grid: tuple[float, ...], min_coverage: float = 0.6):
    """Tuning hook: pick alpha by leave-one-budget-out mean squared error inside the training rows only."""

    def tune(train: pd.DataFrame, features: list[str]) -> dict[str, Any]:
        best_alpha, best_mse = alpha_grid[0], np.inf
        for alpha in alpha_grid:
            residuals = _oof_residuals(train, features, alpha, min_coverage)
            mse = float(np.mean(residuals**2)) if len(residuals) else np.inf
            if mse < best_mse:
                best_alpha, best_mse = alpha, mse
        return {"alpha": best_alpha}

    return tune
