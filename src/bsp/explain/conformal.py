"""Walk-forward conformal 80% intervals with MAPIE, and the coverage report by year and regime (README Phase 7, F9).

For a test budget t, the calibration set is every earlier out-of-sample forecast of the same model whose 12m label was already
known on t's day 0 (``label_end <= day0(t)``), i.e. the forecast errors a user could have seen on budget day. MAPIE's split
conformal regressor (prefit, absolute-residual scores, finite-sample quantile) turns those errors into a symmetric interval around
the model's expected excess return. With fewer than ``MIN_FOLDS`` resolved calibration budgets the interval falls back to the
model's own out-of-fold residual interval (``interval_method = oof_residual``) so that no forecast is left without an interval.

Conformal guarantees assume exchangeable errors; returns over time are not, so the nominal 80% is a target to check, not a
promise. ``coverage_table`` reports what was actually achieved.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from mapie.regression import SplitConformalRegressor
from sklearn.base import BaseEstimator, RegressorMixin

LEVEL = 0.8
MIN_FOLDS = 3


class _Forecast(BaseEstimator, RegressorMixin):  # type: ignore[misc]
    """Prefit 'estimator' whose prediction is the model's own forecast, passed in as the only feature."""

    fitted_ = True  # nothing to fit: MAPIE's prefit check looks for a fitted attribute

    def fit(self, X: np.ndarray, y: np.ndarray | None = None) -> _Forecast:
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(X, dtype=float)[:, 0]

    def __sklearn_is_fitted__(self) -> bool:
        return True


def conformal_intervals(predictions: pd.DataFrame, budgets: pd.DataFrame, level: float = LEVEL,
                        min_folds: int = MIN_FOLDS) -> pd.DataFrame:
    """Add ``p10``, ``p90`` and ``interval_method`` to one model's out-of-sample predictions.

    ``predictions``: columns budget_id, expected, actual, lo, hi. ``budgets``: budget_id, presented_on, day0, label_end.
    """
    meta = budgets.set_index("budget_id")
    out = predictions.copy()
    out["p10"], out["p90"], out["interval_method"] = np.nan, np.nan, ""
    order = sorted(out["budget_id"].unique(), key=lambda b: meta.loc[b, "presented_on"])
    for budget in order:
        rows = out["budget_id"] == budget
        past = [b for b in order if meta.loc[b, "presented_on"] < meta.loc[budget, "presented_on"]
                and meta.loc[b, "label_end"] <= meta.loc[budget, "day0"]]
        calibration = out[out["budget_id"].isin(past)].dropna(subset=["expected", "actual"])
        if len(past) >= min_folds and len(calibration) >= 20:
            wrapper = SplitConformalRegressor(estimator=_Forecast(), confidence_level=level, prefit=True)
            wrapper.conformalize(calibration[["expected"]].to_numpy(), calibration["actual"].to_numpy())
            _, interval = wrapper.predict_interval(out.loc[rows, ["expected"]].to_numpy())
            out.loc[rows, "p10"] = interval[:, 0, 0]
            out.loc[rows, "p90"] = interval[:, 1, 0]
            out.loc[rows, "interval_method"] = "conformal_walk_forward"
        else:
            out.loc[rows, "p10"] = out.loc[rows, "lo"].to_numpy()
            out.loc[rows, "p90"] = out.loc[rows, "hi"].to_numpy()
            out.loc[rows, "interval_method"] = "oof_residual"
    return out


def coverage_table(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """Share of realised excess returns inside [p10, p90] and the mean width, per group (rows with a known outcome only)."""
    known = frame.dropna(subset=["actual", "p10", "p90"]).copy()
    known["covered"] = (known["actual"] >= known["p10"]) & (known["actual"] <= known["p90"])
    known["width"] = known["p90"] - known["p10"]
    grouped = known.groupby(group_cols, sort=True).agg(n=("covered", "size"), coverage=("covered", "mean"), mean_width=("width", "mean"))
    return grouped.reset_index()
