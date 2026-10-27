"""MLflow logging for every evaluation run (params, per-year metrics, artifacts).

Store selection, in order:
  1. ``MLFLOW_TRACKING_URI`` if set, else the project default ``http://localhost:5000`` (the MLflow container from
     docker-compose.yml) - used only if the server answers its health check within 2 seconds;
  2. otherwise a local file store under ``mlruns/`` (git-ignored).
``configure`` returns which one is in use so the caller can print it.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
import requests

EXPERIMENT = "phase4_baselines"
DEFAULT_SERVER = "http://localhost:5000"


def server_reachable(uri: str, timeout: float = 2.0) -> bool:
    if not uri.startswith("http"):
        return True  # a file or database URI needs no server
    try:
        return requests.get(uri.rstrip("/") + "/health", timeout=timeout).status_code == 200
    except requests.RequestException:
        return False


def configure(root: Path) -> tuple[str, str]:
    """Point MLflow at the server if it is up, else at ``mlruns/``. Returns (kind, uri), kind = server | file store."""
    wanted = os.environ.get("MLFLOW_TRACKING_URI") or DEFAULT_SERVER
    if server_reachable(wanted):
        uri, kind = wanted, ("server" if wanted.startswith("http") else "file store")
    else:
        uri, kind = (root / "mlruns").as_uri(), "file store"
    if kind == "file store":
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")  # MLflow 3 warns that the plain file backend is deprecated
        (root / "mlruns").mkdir(exist_ok=True)
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(EXPERIMENT)
    return kind, uri


def log_run(name: str, params: dict[str, Any], per_year: pd.DataFrame, summary: dict[str, float],
            artifacts: list[Path]) -> str:
    """Log one model run; ``per_year`` has a ``budget_id`` column and numeric metric columns (step = test year)."""
    with mlflow.start_run(run_name=name) as run:
        mlflow.log_params({k: str(v) for k, v in params.items()})
        for step, (_, row) in enumerate(per_year.sort_values("budget_id").iterrows()):
            for column, value in row.items():
                if column != "budget_id" and isinstance(value, (int, float)) and not math.isnan(value):
                    mlflow.log_metric(str(column), float(value), step=step)
        mlflow.log_metrics({f"summary_{k}": float(v) for k, v in summary.items()
                            if v is not None and not math.isnan(float(v))})
        for path in artifacts:
            mlflow.log_artifact(str(path))
        return str(run.info.run_id)
