"""Final fits and the MLflow model registry (README Phase 5, FR-14).

The walk-forward models are refit on every unlocked, resolved row once (hold-out and live years stay untouched) and each
fit is registered as a new version, together with everything needed to reproduce its predictions later: the training
budgets and row count, the seed, the tuned parameters, the git commit, library versions and a SHA-256 of each input CSV.
Registered names: ``arth_drishti_sector_lgbm_ranker``, ``arth_drishti_sector_bayes_hier``, ``arth_drishti_stock_ranker``.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from typing import Any

import lightgbm
import mlflow
import mlflow.lightgbm
import mlflow.pyfunc
import numpy as np
import pandas as pd
import pymc

from bsp.evaluation.config import EvalConfig
from bsp.evaluation.data import Panel
from bsp.models.bayes import BayesHierarchical
from bsp.models.ranker import LGBMRankerModel, make_ranker_tuner

INPUTS = ["features_sector_year_wide.csv", "features_stock_year_wide.csv", "targets.csv", "prices_daily.csv"]
N_TRIALS = 15


class PosteriorMeanSectorModel(mlflow.pyfunc.PythonModel):  # type: ignore[misc,name-defined]
    """Point predictor from the Bayesian model's posterior means (expected excess return per sector row)."""

    def __init__(self, sectors: list[str], a: np.ndarray, b: np.ndarray, c: np.ndarray, columns: list[str],
                 stats: dict[str, dict[str, float]], y_mean: float, y_std: float) -> None:
        self.sectors, self.a, self.b, self.c, self.columns = sectors, a, b, c, columns
        self.stats, self.y_mean, self.y_std = stats, y_mean, y_std

    def predict(self, context: Any, model_input: pd.DataFrame, params: Any = None) -> np.ndarray:
        x = np.column_stack([(model_input[c].astype(float).fillna(self.stats[c]["median"]) - self.stats[c]["mean"]) / self.stats[c]["std"]
                             for c in self.columns])
        index = model_input["entity"].map({s: i for i, s in enumerate(self.sectors)}).to_numpy().astype(int)
        mean = self.a[index] + self.b[index] * x[:, 0] + (x[:, 1:] @ self.c if len(self.c) else 0.0)
        return mean * self.y_std + self.y_mean


def _sha(path: Any) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(root: Any) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # pragma: no cover - not a git checkout
        return "unknown"


def _usable(panel: Panel) -> pd.DataFrame:
    frame = panel.frame
    return frame[frame["target_complete"] & frame["excess_return"].notna()].copy()


def final_fit_and_register(cfg: EvalConfig, sector_panel: Panel, stock_panel: Panel, use_mlflow: bool,
                           ) -> tuple[pd.DataFrame, Callable[[], None]]:
    """Refit the three models on all unlocked, resolved rows. Returns the Bayesian slopes and a registration closure."""
    sector_rows, stock_rows = _usable(sector_panel), _usable(stock_panel)
    ranker_params = make_ranker_tuner(n_trials=N_TRIALS, seed=cfg.seed)(sector_rows, sector_panel.features)
    ranker = LGBMRankerModel(seed=cfg.seed, interval_level=cfg.interval_level, **ranker_params).fit(sector_rows, sector_panel.features)
    bayes = BayesHierarchical(seed=cfg.seed, interval_level=cfg.interval_level).fit(sector_rows, sector_panel.features)
    stock_params = make_ranker_tuner(("budget_id", "sector_id"), N_TRIALS, cfg.seed)(stock_rows, stock_panel.features)
    stock_ranker = LGBMRankerModel(("budget_id", "sector_id"), cfg.seed, False, **stock_params).fit(stock_rows, stock_panel.features)

    def register() -> None:
        if not use_mlflow:
            return
        common = {
            "seed": cfg.seed, "git_commit": _git_commit(cfg.root), "lightgbm": lightgbm.__version__, "pymc": pymc.__version__,
            "holdout_locked": not cfg.holdout_unlocked,
            **{f"sha256_{name}": _sha(cfg.root / "data" / "csv" / name) for name in INPUTS},
        }
        fits = [
            ("arth_drishti_sector_lgbm_ranker", sector_rows, sector_panel.features, ranker_params, ranker.ranker),
            ("arth_drishti_stock_ranker", stock_rows, stock_panel.features, stock_params, stock_ranker.ranker),
        ]
        for name, rows, features, params, estimator in fits:
            with mlflow.start_run(run_name=f"final/{name}"):
                mlflow.log_params({**{k: str(v) for k, v in common.items()}, "n_train_rows": len(rows),
                                   "train_budgets": ",".join(sorted(rows["budget_id"].unique())), "features": ",".join(features),
                                   **{f"param_{k}": str(v) for k, v in params.items()}})
                mlflow.lightgbm.log_model(estimator.booster_ if estimator is not None else None, name="model", registered_model_name=name)
        with mlflow.start_run(run_name="final/arth_drishti_sector_bayes_hier"):
            assert bayes.stats is not None
            mlflow.log_params({**{k: str(v) for k, v in common.items()}, "n_train_rows": len(sector_rows),
                               "train_budgets": ",".join(sorted(sector_rows["budget_id"].unique())), **{f"diag_{k}": str(v) for k, v in bayes.diagnostics.items()}})
            wrapper = PosteriorMeanSectorModel(
                bayes.sectors, bayes.post["a"].mean(axis=0), bayes.post["b"].mean(axis=0), bayes.post.get("c", np.zeros((1, 0))).mean(axis=0),
                bayes.columns, {str(k): {str(i): float(v) for i, v in d.items()} for k, d in bayes.stats.to_dict("index").items()}, bayes.y_mean, bayes.y_std)
            mlflow.pyfunc.log_model(name="model", python_model=wrapper, registered_model_name="arth_drishti_sector_bayes_hier")

    return bayes.slopes(), register
