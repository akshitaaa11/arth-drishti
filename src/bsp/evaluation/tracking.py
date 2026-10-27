"""MLflow logging for every evaluation run (params, per-year metrics, artifacts).

Tracking goes to ``MLFLOW_TRACKING_URI`` when set (for example the MLflow container at http://localhost:5000),
otherwise to a local SQLite store ``mlflow.db`` with artifacts under ``mlruns/`` (both git-ignored; MLflow's
plain-file backend is deprecated).
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd

EXPERIMENT = "phase4_baselines"


def configure(root: Path) -> str:
    uri = os.environ.get("MLFLOW_TRACKING_URI") or f"sqlite:///{(root / 'mlflow.db').as_posix()}"
    mlflow.set_tracking_uri(uri)
    if mlflow.get_experiment_by_name(EXPERIMENT) is None:
        mlflow.create_experiment(EXPERIMENT, artifact_location=(root / "mlruns").as_uri())
    mlflow.set_experiment(EXPERIMENT)
    return uri


def log_run(name: str, params: dict[str, Any], per_year: pd.DataFrame, summary: dict[str, float],
            artifacts: list[Path]) -> str:
    """Log one model run; ``per_year`` has a ``budget_id`` column and numeric metric columns (step = test year)."""
    with mlflow.start_run(run_name=name) as run:
        mlflow.log_params({k: str(v) for k, v in params.items()})
        for step, (_, row) in enumerate(per_year.sort_values("budget_id").iterrows()):
            for column, value in row.items():
                if column != "budget_id" and isinstance(value, (int, float)) and not math.isnan(value):
                    mlflow.log_metric(str(column), float(value), step=step)
        mlflow.log_metrics({k: float(v) for k, v in summary.items() if v is not None and not math.isnan(float(v))})
        for path in artifacts:
            mlflow.log_artifact(str(path))
        return str(run.info.run_id)
