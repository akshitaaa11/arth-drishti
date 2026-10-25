from __future__ import annotations

import pandas as pd

from bsp.ingest._common import CSV_DIR, RAW_DIR, append_fetch_log, ensure_dirs, write_csv_guarded

COLUMNS = ["symbol", "effective_from", "effective_to", "source", "source_url", "fetched_at"]


def collect_constituents() -> pd.DataFrame:
    ensure_dirs()
    raw_dir = RAW_DIR / "nifty500_constituents"
    raw_dir.mkdir(parents=True, exist_ok=True)
    candidates = sorted(raw_dir.glob("*.csv"))
    collected: list[pd.DataFrame] = []
    for path in candidates:
        frame = pd.read_csv(path)
        if {"symbol", "effective_from", "effective_to"}.issubset(frame.columns):
            normalized = frame.copy()
            normalized["symbol"] = normalized["symbol"].astype(str)
            if "source" not in normalized.columns:
                normalized["source"] = f"manual file {path.name}"
            if "source_url" not in normalized.columns:
                normalized["source_url"] = f"data/raw/nifty500_constituents/{path.name}"
            if "fetched_at" not in normalized.columns:
                normalized["fetched_at"] = pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC").isoformat(timespec="seconds")
            collected.append(normalized[COLUMNS])
    if collected:
        output = (
            pd.concat(collected, ignore_index=True)
            .drop_duplicates(subset=["symbol", "effective_from", "effective_to"])
            .sort_values(["symbol", "effective_from"])
            .reset_index(drop=True)
        )
    else:
        output = pd.DataFrame(columns=COLUMNS)
    write_csv_guarded(output, CSV_DIR / "nifty500_constituents.csv")
    detail = "" if len(output) else "no files in data/raw/nifty500_constituents; run scripts/collect/nifty500_history.py (existing CSV kept)"
    append_fetch_log("constituents", "ok" if len(output) else "empty", len(output), detail)
    return output


if __name__ == "__main__":
    collect_constituents()
