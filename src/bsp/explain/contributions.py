"""Additive attributions of one fold model's forecasts (README Phase 7, FR-10).

Every attribution is ``base + sum(contribution per feature)`` on the scale it explains:
  * LightGBM regressor (expected excess return): SHAP TreeExplainer values; additive to the regressor's prediction (exact).
  * LightGBM ranker (rank score): SHAP TreeExplainer values; additive to the ranker's raw score (exact).
  * Bayesian hierarchical model: the posterior-mean linear predictor is exactly additive: sector intercept (the baseline)
    + surprise slope x surprise + pooled slopes x controls, all multiplied back to the return scale. The stored forecast is the
    mean of posterior-predictive draws, which differs from the posterior-mean predictor only by Monte-Carlo noise.
  * Blend / stack: the same weights as the forecast, applied to the components' attributions (the blend's expected return is the
    weighted mean of its components' expected returns, so its attribution is the weighted mean of theirs).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import shap

from bsp.models.bayes import BayesHierarchical
from bsp.models.ranker import LGBMRankerModel


@dataclass
class Attribution:
    base: np.ndarray  # (n,) baseline per row
    contrib: pd.DataFrame  # (n, features) contribution per feature, index = position in the test frame

    def predicted(self) -> np.ndarray:
        return self.base + self.contrib.sum(axis=1).to_numpy()


def _tree_attribution(estimator: object, model: LGBMRankerModel, test: pd.DataFrame) -> Attribution:
    explainer = shap.TreeExplainer(estimator)
    x = test[model.features].to_numpy(dtype=float)
    values = np.asarray(explainer.shap_values(x), dtype=float)
    base = float(np.ravel(explainer.expected_value)[0])
    return Attribution(np.full(len(test), base), pd.DataFrame(values, columns=model.features))


def lgbm_expected_attribution(model: LGBMRankerModel, test: pd.DataFrame) -> Attribution:
    if model.regressor is None:
        raise ValueError("this ranker was fitted without the companion regressor, so it has no expected-return forecast")
    return _tree_attribution(model.regressor, model, test)


def lgbm_rank_attribution(model: LGBMRankerModel, test: pd.DataFrame) -> Attribution:
    assert model.ranker is not None
    return _tree_attribution(model.ranker, model, test)


def bayes_attribution(model: BayesHierarchical, test: pd.DataFrame) -> Attribution:
    design = model._design(test)
    index = test["entity"].map({s: i for i, s in enumerate(model.sectors)}).to_numpy().astype(int)
    a, b = model.post["a"].mean(axis=0), model.post["b"].mean(axis=0)
    terms = {model.columns[0]: b[index] * design[:, 0] * model.y_std}
    if "c" in model.post:
        c = model.post["c"].mean(axis=0)
        for j, name in enumerate(model.columns[1:]):
            terms[name] = c[j] * design[:, 1 + j] * model.y_std
    return Attribution(a[index] * model.y_std + model.y_mean, pd.DataFrame(terms))


def combine(parts: list[tuple[float, Attribution]]) -> Attribution:
    """Weighted mean of attributions; a feature a component does not use contributes 0 to that component."""
    total = sum(w for w, _ in parts)
    columns = sorted({c for _, a in parts for c in a.contrib.columns})
    base = sum(w * a.base for w, a in parts) / total
    contrib = pd.DataFrame(0.0, index=parts[0][1].contrib.index, columns=columns)
    for weight, attribution in parts:
        contrib = contrib + weight * attribution.contrib.reindex(columns=columns).fillna(0.0)
    return Attribution(np.asarray(base), contrib / total)
