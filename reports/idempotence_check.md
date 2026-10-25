# Idempotence check

Run at 2026-10-25T08:59:55+00:00 by `scripts/check_idempotence.py`. Each Phase 2 ingestion job is run twice; data rows (excluding the header) must not change between runs.

| Job | CSV | Before | After run 1 | After run 2 | Result |
| --- | --- | ---: | ---: | ---: | --- |
| prices | `prices_daily.csv` | 511915 | 511915 | 511915 | PASS |
| prices | `stock_first_price_date.csv` | 116 | 116 | 116 | PASS |
| benchmarks | `index_daily.csv` | 62375 | 62375 | 62375 | PASS |
| constituents | `nifty500_constituents.csv` | 0 | 0 | 0 | PASS |
| macro | `macro.csv` | 22147 | 22147 | 22147 | PASS |
| fpi | `fpi_sector_fortnightly.csv` | 2922 | 2922 | 2922 | PASS |
| fpi | `fpi_sector_fortnightly_long.csv` | 8766 | 8766 | 8766 | PASS |

Notes:
- Only row counts are compared; `fetched_at` timestamps legitimately change on every run.
- `constituents` (no source files yet) and `fpi` (NSDL returns HTTP 403 from the cloud sandbox) did not download anything here, so their PASS only shows that a blocked or empty run leaves the existing CSV untouched. Re-run this script on a laptop for a real test of those two.
- `prices`, `benchmarks` and `macro` hit Yahoo Finance / the World Bank where reachable; macro series from FRED are blocked here and keep their previous rows.

Overall: PASS
