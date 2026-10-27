"""MLflow store selection: the server when it answers, otherwise a local file store under mlruns/."""

from __future__ import annotations

from pathlib import Path

import mlflow
import pandas as pd

from bsp.evaluation import tracking


def test_unreachable_server_falls_back_to_a_local_file_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.setattr(tracking, "server_reachable", lambda uri, timeout=2.0: False)
    kind, uri = tracking.configure(tmp_path)
    assert kind == "file store" and uri == (tmp_path / "mlruns").as_uri() and (tmp_path / "mlruns").is_dir()


def test_reachable_server_is_used(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, str] = {}
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.example:5000")
    monkeypatch.setattr(tracking, "server_reachable", lambda uri, timeout=2.0: True)
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: seen.setdefault("uri", uri))
    monkeypatch.setattr(mlflow, "set_experiment", lambda name: None)
    assert tracking.configure(tmp_path) == ("server", "http://mlflow.example:5000") and seen["uri"].startswith("http://")


def test_dead_server_check_returns_false_quickly() -> None:
    assert tracking.server_reachable("http://127.0.0.1:9", timeout=0.5) is False  # nothing listens on port 9
    assert tracking.server_reachable("file:///tmp/whatever") is True  # file URIs need no server


def test_run_is_logged_to_the_local_file_store_with_per_year_metrics(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.setattr(tracking, "server_reachable", lambda uri, timeout=2.0: False)
    tracking.configure(tmp_path)
    per_year = pd.DataFrame({"budget_id": ["FY2012-13", "FY2013-14", "FY2014-15"], "ic": [0.1, -0.2, 0.3]})
    artifact = tmp_path / "report.md"
    artifact.write_text("x", encoding="utf-8")
    run_id = tracking.log_run("sector/test", {"model": "test", "seed": 42}, per_year, {"ic": 0.0667}, [artifact])
    client = mlflow.tracking.MlflowClient()
    history = client.get_metric_history(run_id, "ic")
    assert [round(m.value, 3) for m in sorted(history, key=lambda m: m.step)] == [0.1, -0.2, 0.3]
    assert client.get_run(run_id).data.params["seed"] == "42"
    assert client.get_run(run_id).data.metrics["summary_ic"] == 0.0667
    assert [a.path for a in client.list_artifacts(run_id)] == ["report.md"]
