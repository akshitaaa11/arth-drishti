"""Run every Phase 2 ingestion job twice and report CSV row counts (jobs must leave them unchanged).

Usage: python scripts/check_idempotence.py   (writes reports/idempotence_check.md)
Needs the network that the jobs themselves need; a blocked source keeps its previous CSV (guarded writes),
which also counts as unchanged, and is noted in the report.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bsp.ingest.benchmarks import collect_benchmarks
from bsp.ingest.fpi import collect_fpi
from bsp.ingest.macro import collect_macro
from bsp.ingest.prices import collect_prices

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data" / "csv"
JOBS = {
    "prices": (collect_prices, ["prices_daily.csv", "stock_first_price_date.csv"]),
    "benchmarks": (collect_benchmarks, ["index_daily.csv"]),
    "macro": (collect_macro, ["macro.csv"]),
    "fpi": (collect_fpi, ["fpi_sector_fortnightly.csv", "fpi_sector_fortnightly_long.csv"]),
}


def counts(files: list[str]) -> dict[str, int]:
    return {f: (len(pd.read_csv(CSV / f)) if (CSV / f).exists() else -1) for f in files}


def main() -> int:
    lines = [
        "# Idempotence check",
        "",
        f"Run at {datetime.now(UTC).isoformat(timespec='seconds')} by `scripts/check_idempotence.py`. "
        "Each Phase 2 ingestion job is run twice; data rows (excluding the header) must not change between runs.",
        "",
        "| Job | CSV | Before | After run 1 | After run 2 | Result |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    failures = 0
    for name, (job, files) in JOBS.items():
        before = counts(files)
        for _ in range(2):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                job()
            if _ == 0:
                run1 = counts(files)
        run2 = counts(files)
        for f in files:
            ok = run1[f] == run2[f] == before[f]
            failures += not ok
            lines.append(f"| {name} | `{f}` | {before[f]} | {run1[f]} | {run2[f]} | {'PASS' if ok else 'FAIL'} |")
    lines += [
        "",
        "Notes:",
        "- Only row counts are compared; `fetched_at` timestamps legitimately change on every run.",
        "- `fpi` (NSDL returns HTTP 403 from the cloud sandbox) did not download anything here, so its PASS only "
        "shows that a blocked run leaves the existing CSV untouched. Re-run this script on a laptop for a real test.",
        "- `prices`, `benchmarks` and `macro` hit Yahoo Finance / the World Bank where reachable; macro series "
        "from FRED are blocked here and keep their previous rows.",
        "",
        f"Overall: {'PASS' if not failures else f'FAIL ({failures} mismatches)'}"]
    (ROOT / "reports" / "idempotence_check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
