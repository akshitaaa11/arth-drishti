"""Idempotently load the Phase 2 market/flow/macro CSVs into the database (``make load``).

Each CSV is the source of truth for its table: rows are upserted on the table's natural key, and rows whose
key is no longer in the CSV (for example prices later removed by the cleaning rules) are deleted, so the table
always matches the file. Every table load writes one ``fetch_log`` row (``load_<table>``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import MetaData, Table, delete, inspect, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from bsp.common.config import get_project_root
from bsp.common.db import create_engine

CSV_DIR = get_project_root() / "data" / "csv"
CHUNK = 2000


def _clean(frame: pd.DataFrame, date_cols: tuple[str, ...], ts_cols: tuple[str, ...]) -> list[dict[str, Any]]:
    out = frame.copy()
    for col in date_cols:
        out[col] = pd.to_datetime(out[col]).dt.date
    for col in ts_cols:
        out[col] = pd.to_datetime(out[col], utc=True).dt.tz_localize(None).dt.to_pydatetime()
    out = out.astype(object).where(out.notna(), None)
    return [{str(k): v for k, v in row.items()} for row in out.to_dict("records")]


def _prices(csv_dir: Path) -> pd.DataFrame:
    cols = ["symbol", "date", "open", "high", "low", "close", "adj_close", "volume", "traded_value_cr",
            "source", "source_url", "fetched_at"]
    return pd.read_csv(csv_dir / "prices_daily.csv")[cols]


def _indices(csv_dir: Path) -> pd.DataFrame:
    return pd.read_csv(csv_dir / "index_daily.csv")[["index_name", "ticker", "date", "close", "volume", "source", "fetched_at"]]


def _macro(csv_dir: Path) -> pd.DataFrame:
    return pd.read_csv(csv_dir / "macro.csv")[["series", "date", "value", "unit", "source", "fetched_at"]]


def _fpi(csv_dir: Path) -> pd.DataFrame:
    frame = pd.read_csv(csv_dir / "fpi_sector_fortnightly.csv")
    frame = frame.rename(columns={"equity_net_cr": "equity_cr", "debt_net_cr": "debt_cr", "equity_aum_cr": "aum_cr"})
    return frame[["nsdl_sector", "period_end", "equity_cr", "debt_cr", "aum_cr", "source", "source_url", "fetched_at"]]


# table -> (CSV reader, natural key, date columns, timestamp columns, scope filter for deletes)
SPECS: dict[str, tuple[Callable[[Path], pd.DataFrame], tuple[str, ...], tuple[str, ...], tuple[str, ...], dict[str, Any]]] = {
    "prices_daily": (_prices, ("symbol", "date"), ("date",), ("fetched_at",), {}),
    "index_daily": (_indices, ("index_name", "date"), ("date",), ("fetched_at",), {}),
    "macro": (_macro, ("series", "date"), ("date",), ("fetched_at",), {}),
    "fpi_flows": (_fpi, ("nsdl_sector", "period_end"), ("period_end",), ("fetched_at",), {}),
}


def _predictions(csv_dir: Path) -> pd.DataFrame:
    cols = ["model_version", "entity", "budget_id", "expected_excess", "p10", "p90", "p_beat", "rank", "top_reasons"]
    return pd.read_csv(csv_dir / "predictions.csv")[cols]


# Phase 5-7 model output, loaded separately so the market loader keeps loading exactly the market tables.
MODEL_SPECS: dict[str, tuple[Callable[[Path], pd.DataFrame], tuple[str, ...], tuple[str, ...], tuple[str, ...], dict[str, Any]]] = {
    "predictions": (_predictions, ("model_version", "entity", "budget_id"), (), (), {}),
}


def _upsert_stmt(engine: Engine, table: Table, key: tuple[str, ...], columns: list[str]) -> Any:
    if engine.dialect.name == "postgresql":
        stmt: Any = pg_insert(table)
    elif engine.dialect.name == "sqlite":
        stmt = sqlite_insert(table)
    else:  # pragma: no cover
        raise NotImplementedError(f"upsert not implemented for {engine.dialect.name}")
    updates = {c: stmt.excluded[c] for c in columns if c not in key}
    # Rewrite a row only when something changed, so re-running an unchanged load writes (almost) nothing.
    changed = or_(*[table.c[c].is_distinct_from(stmt.excluded[c]) for c in updates])
    return stmt.on_conflict_do_update(index_elements=list(key), set_=updates, where=changed)


def load_table(engine: Engine, name: str, csv_dir: Path = CSV_DIR) -> int:
    reader, key, date_cols, ts_cols, scope = {**SPECS, **MODEL_SPECS}[name]
    started = datetime.now(UTC).replace(tzinfo=None)
    try:
        frame = reader(csv_dir)
        columns = list(frame.columns)
        records = _clean(frame.drop_duplicates(subset=list(key), keep="last"), date_cols, ts_cols)
        table = Table(name, MetaData(), autoload_with=engine)
        with engine.begin() as conn:
            stmt = _upsert_stmt(engine, table, key, columns)
            for start in range(0, len(records), CHUNK):
                batch = records[start:start + CHUNK]
                if engine.dialect.name == "postgresql":
                    conn.execute(stmt.values(batch))  # one multi-row INSERT per chunk: far faster than executemany
                else:
                    conn.execute(stmt, batch)
            # Remove rows whose key is no longer in the CSV so the table equals the file.
            key_cols = [table.c[k] for k in key]
            query = select(*key_cols)
            for col, value in scope.items():
                query = query.where(table.c[col] == value)
            existing = {tuple(row) for row in conn.execute(query)}
            wanted = {tuple(r[k] for k in key) for r in records}
            stale = list(existing - wanted)
            for start in range(0, len(stale), CHUNK):
                cond = tuple_(*key_cols).in_(stale[start:start + CHUNK])
                conn.execute(delete(table).where(cond))
            _log(conn, name, started, len(records), "success", None)
        return len(records)
    except Exception as exc:
        with engine.begin() as conn:
            _log(conn, name, started, 0, "failed", str(exc)[:2000])
        raise


def _log(conn: Any, name: str, started: datetime, rows: int, status: str, error: str | None) -> None:
    conn.execute(
        text("INSERT INTO fetch_log (job, started_at, finished_at, rows, status, error) "
             "VALUES (:job, :started_at, :finished_at, :rows, :status, :error)"),
        {"job": f"load_{name}", "started_at": started, "finished_at": datetime.now(UTC).replace(tzinfo=None),
         "rows": rows, "status": status, "error": error},
    )


def load_market_csvs(database_url: str | None = None, csv_dir: str | Path = CSV_DIR) -> dict[str, int]:
    engine = create_engine(database_url=database_url)
    try:
        inspector = inspect(engine)
        missing = [t for t in (*SPECS, "fetch_log") if not inspector.has_table(t)]
        if missing:
            raise RuntimeError(f"Database schema missing tables {missing}; run `make db-migrate` first")
        return {name: load_table(engine, name, Path(csv_dir)) for name in SPECS}
    finally:
        engine.dispose()


def load_prediction_csv(database_url: str | None = None, csv_dir: str | Path = CSV_DIR) -> int:
    """Load data/csv/predictions.csv (Phase 7) into the ``predictions`` table; 0 if the file does not exist."""
    if not (Path(csv_dir) / "predictions.csv").exists():
        return 0
    engine = create_engine(database_url=database_url)
    try:
        if not inspect(engine).has_table("predictions"):
            raise RuntimeError("Database schema missing table 'predictions'; run `make db-migrate` first")
        return load_table(engine, "predictions", Path(csv_dir))
    finally:
        engine.dispose()


def main() -> None:
    for name, rows in load_market_csvs().items():
        print(f"loaded {rows} rows into {name}")
    print(f"loaded {load_prediction_csv()} rows into predictions")


if __name__ == "__main__":
    main()
