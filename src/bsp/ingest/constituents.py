from __future__ import annotations

from pathlib import Path

import pandas as pd

from bsp.ingest._common import CSV_DIR, RAW_DIR, append_fetch_log, ensure_dirs


def collect_constituents() -> pd.DataFrame:
    ensure_dirs()
    raw_dir = RAW_DIR / "nifty500_constituents"
    raw_dir.mkdir(parents=True, exist_ok=True)
    candidates = sorted(raw_dir.glob("*.csv"))
    collected: list[pd.DataFrame] = []
    for path in candidates:
        frame = pd.read_csv(path)
        if {"symbol", "effective_from", "effective_to"}.issubset(frame.columns):
            normalized = frame[["symbol", "effective_from", "effective_to"]].copy()
            normalized["symbol"] = normalized["symbol"].astype(str)
            collected.append(normalized)
    if collected:
        output = pd.concat(collected, ignore_index=True).drop_duplicates(subset=["symbol", "effective_from", "effective_to"]).sort_values(["symbol", "effective_from"]).reset_index(drop=True)
    else:
        output = pd.DataFrame(columns=["symbol", "effective_from", "effective_to"])
    output.to_csv(CSV_DIR / "nifty500_constituents.csv", index=False)
    append_fetch_log("constituents", "ok" if len(output) else "empty", len(output), "manual constituent list not available; file left empty")
    return output


if __name__ == "__main__":
    collect_constituents()
