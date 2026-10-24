from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
CFG_DIR = ROOT / "config"
CSV_DIR = ROOT / "data" / "csv"
RAW_DIR = ROOT / "data" / "raw"
REPORT_DIR = ROOT / "reports"

UA = {"User-Agent": "Mozilla/5.0 (research project; contact: see repository README)"}


def ensure_dirs() -> None:
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def load_stocks() -> pd.DataFrame:
    return pd.read_csv(CFG_DIR / "stocks.csv")


def append_fetch_log(job: str, status: str, rows: int = 0, detail: str = "") -> None:
    ensure_dirs()
    path = CSV_DIR / "fetch_log.csv"
    row = {
        "job": job,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": status,
        "rows": rows,
        "detail": detail[:250],
    }
    if path.exists():
        history = pd.read_csv(path)
        combined = pd.concat([history, pd.DataFrame([row])], ignore_index=True)
    else:
        combined = pd.DataFrame([row])
    combined.to_csv(path, index=False)
