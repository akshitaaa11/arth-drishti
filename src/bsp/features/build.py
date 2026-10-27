"""Phase 3 pipeline: build point-in-time features, targets and event study.

Builds and loads:
  - self-built sector baskets
  - sector-year features (features_sector_year)
  - stock-year features (features_stock_year)
  - excess return targets (targets)
  - market-model event study (event_study)
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import inspect, text

from bsp.common.config import get_project_root
from bsp.common.db import create_engine
from bsp.events.study import build_and_save_event_study
from bsp.features.baskets import build_market_data_bundle
from bsp.features.sector_features import build_and_save_sector_features
from bsp.features.stock_features import build_and_save_stock_features
from bsp.features.targets import build_and_save_targets
from bsp.nlp.speech_tagging import build_and_save_speech_scores
from bsp.quality.leakage import validate_feature_store


def build_all_features(project_root: Path | None = None) -> None:
    """Build all Phase 3 datasets and save to CSVs."""
    root = project_root or get_project_root()
    print("[1/5] Building market data bundle and sector baskets...")
    bundle = build_market_data_bundle(root)

    print("[1b] Scoring budget speeches (keyword tagging)...")
    build_and_save_speech_scores(root)

    print("[2/5] Building sector-year features...")
    build_and_save_sector_features(bundle, root)

    print("[3/5] Building stock-year features...")
    build_and_save_stock_features(bundle, root)

    print("[4/5] Building forward targets...")
    build_and_save_targets(bundle, root)

    print("[5/5] Building event study...")
    build_and_save_event_study(bundle, root)

    print("Running leakage validation...")
    validate_feature_store(root)
    print("Phase 3 feature generation and validation complete.")


def load_features_into_db(
    database_url: str | None = None,
    project_root: Path | None = None,
) -> None:
    """Idempotently load Phase 3 CSVs into the database tables."""
    root = project_root or get_project_root()
    csv_dir = root / "data" / "csv"
    engine = create_engine(database_url=database_url)
    inspector = inspect(engine)

    required_tables = ["features_sector_year", "features_stock_year", "targets", "event_study", "fetch_log"]
    missing = [t for t in required_tables if not inspector.has_table(t)]
    if missing:
        raise RuntimeError(f"Database schema missing tables {missing}; run `make db-migrate` first")

    started_at = datetime.now(UTC).replace(tzinfo=None)
    total_loaded = 0

    with engine.begin() as conn:
        # 1. Sector features
        sec_path = csv_dir / "features_sector_year.csv"
        if sec_path.exists():
            df_sec = pd.read_csv(sec_path)
            conn.execute(text("DELETE FROM features_sector_year"))
            # Insert in chunks
            # NaN must become NULL: Postgres stores NaN as a real float value, which poisons SUM/AVG.
            df_sec = df_sec.astype(object).where(df_sec.notna(), None)
            sec_records: list[dict[str, Any]] = [
                {str(k): v for k, v in r.items()} for r in df_sec.to_dict(orient="records")
            ]
            if sec_records:
                conn.execute(
                    text(
                        "INSERT INTO features_sector_year (sector_id, budget_id, feature_name, value, as_of_date) "
                        "VALUES (:sector_id, :budget_id, :feature_name, :value, :as_of_date)"
                    ),
                    sec_records,
                )
                total_loaded += len(sec_records)
                print(f"Loaded {len(sec_records)} rows into features_sector_year")

        # 2. Stock features
        stk_path = csv_dir / "features_stock_year.csv"
        if stk_path.exists():
            df_stk = pd.read_csv(stk_path)
            conn.execute(text("DELETE FROM features_stock_year"))
            # NaN must become NULL: Postgres stores NaN as a real float value, which poisons SUM/AVG.
            df_stk = df_stk.astype(object).where(df_stk.notna(), None)
            stk_records: list[dict[str, Any]] = [
                {str(k): v for k, v in r.items()} for r in df_stk.to_dict(orient="records")
            ]
            if stk_records:
                # Chunk insert for SQLite parameter limit
                chunk_size = 5000
                for i in range(0, len(stk_records), chunk_size):
                    chunk = stk_records[i : i + chunk_size]
                    conn.execute(
                        text(
                            "INSERT INTO features_stock_year (symbol, budget_id, feature_name, value, as_of_date) "
                            "VALUES (:symbol, :budget_id, :feature_name, :value, :as_of_date)"
                        ),
                        chunk,
                    )
                total_loaded += len(stk_records)
                print(f"Loaded {len(stk_records)} rows into features_stock_year")

        # 3. Targets
        tgt_path = csv_dir / "targets.csv"
        if tgt_path.exists():
            df_tgt = pd.read_csv(tgt_path)
            conn.execute(text("DELETE FROM targets"))
            tgt_records: list[dict[str, Any]] = [
                {
                    "entity": str(r["entity"]),
                    "budget_id": str(r["budget_id"]),
                    "horizon": str(r["horizon"]),
                    "excess_return": float(r["excess_return"]) if pd.notna(r["excess_return"]) else None,
                    "target_complete": bool(r["target_complete"]),
                }
                for r in df_tgt.to_dict(orient="records")
            ]
            if tgt_records:
                chunk_size = 5000
                for i in range(0, len(tgt_records), chunk_size):
                    tgt_chunk = tgt_records[i : i + chunk_size]
                    conn.execute(
                        text(
                            "INSERT INTO targets (entity, budget_id, horizon, excess_return, target_complete) "
                            "VALUES (:entity, :budget_id, :horizon, :excess_return, :target_complete)"
                        ),
                        tgt_chunk,
                    )
                total_loaded += len(tgt_records)
                print(f"Loaded {len(tgt_records)} rows into targets")

        # 4. Event study
        es_path = csv_dir / "event_study.csv"
        if es_path.exists():
            df_es = pd.read_csv(es_path)
            conn.execute(text("DELETE FROM event_study"))
            es_records: list[dict[str, Any]] = [
                {
                    "entity": str(r["entity"]),
                    "budget_id": str(r["budget_id"]),
                    "window": str(r["window"]),
                    "car": float(r["car"]) if pd.notna(r["car"]) else None,
                    "t_stat": float(r["t_stat"]) if pd.notna(r["t_stat"]) else None,
                    "alpha": float(r["alpha"]) if pd.notna(r["alpha"]) else None,
                    "beta": float(r["beta"]) if pd.notna(r["beta"]) else None,
                }
                for r in df_es.to_dict(orient="records")
            ]
            if es_records:
                chunk_size = 5000
                for i in range(0, len(es_records), chunk_size):
                    es_chunk = es_records[i : i + chunk_size]
                    conn.execute(
                        text(
                            "INSERT INTO event_study (entity, budget_id, \"window\", car, t_stat, alpha, beta) "
                            "VALUES (:entity, :budget_id, :window, :car, :t_stat, :alpha, :beta)"
                        ),
                        es_chunk,
                    )
                total_loaded += len(es_records)
                print(f"Loaded {len(es_records)} rows into event_study")

        # Log to fetch_log
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        conn.execute(
            text(
                "INSERT INTO fetch_log (job, started_at, finished_at, rows, status, error) "
                "VALUES (:job, :started_at, :finished_at, :rows, :status, :error)"
            ),
            {
                "job": "phase3_features_load",
                "started_at": started_at,
                "finished_at": finished_at,
                "rows": total_loaded,
                "status": "success",
                "error": None,
            },
        )
    print(f"Database loading complete: {total_loaded} rows inserted across Phase 3 tables.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true", help="Skip CSV building and only load DB")
    parser.add_argument("--skip-load", action="store_true", help="Skip DB loading and only build CSVs")
    args = parser.parse_args()

    root = get_project_root()
    if not args.skip_build:
        build_all_features(root)
    if not args.skip_load:
        load_features_into_db(project_root=root)


if __name__ == "__main__":
    main()
