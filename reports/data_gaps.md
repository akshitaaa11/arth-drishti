# Phase 1 budget data coverage and gaps

## Built and validated

| Dataset | Coverage | Current output | Validation |
| --- | --- | --- | --- |
| PRS ministry, scheme, subsidy and fiscal tables (D1-D3) | FY2019-20 to FY2026-27 (8 budget years) | `data/csv/budget_ministries.csv`, `budget_schemes.csv`, `budget_fiscal.csv` | 480 ministry, 464 scheme and 1,447 fiscal rows; all have source document, page, URL and fetched timestamp |
| Expenditure Budget demands (D4) | FY2005-06 to FY2026-27 (22 budget years) | `data/csv/budget_demands.csv` | 5,589 sourced rows; unavailable values are null, not estimated |
| Sector budget panel | FY2005-06 to FY2026-27 (15 sectors x 22 budgets) | `data/csv/sector_budget_panel.csv` | 330 rows; 326 have a canonical primary allocation and 4 remain explicitly missing |
| Department-level Statement 3 transcriptions | FY2017-18 to FY2026-27 (10 editions) | `data/csv/budget_departments.csv` | 1,164 rows; revenue + capital matches total within ₹0.02 crore for every row |

The D4 downloader has a source PDF recorded for all 22 budget years in `reports/budget_pdf_downloads.csv`. The FY2026-27 PDF is available at the current official URL `https://www.indiabudget.gov.in/doc/eb/vol1.pdf`. For FY2017-18 onward, complete, page-referenced Statement 3 transcriptions are retained because the PDF text parser extracts only partial tables in several recent layouts. It does not overwrite those fuller transcriptions with partial PDF output.

All 25 values in `reports/budget_spot_check.csv` are marked as found on their cited pages; an independent comparison against the parsed rows for each cited document/page also matched 25/25. No PRS parser rows have a blank fiscal year or an unrecognized extra column.

## Reconciliation and cross-checks

- All 32 PRS ministry/stage tables in `reports/reconciliation.csv` pass the required 0.5% reconciliation.
- The subsidy table has 31 passing totals and one documented failure: FY2024-25 BE prints ₹4,38,423 crore while the listed components sum to ₹4,28,423 crore. The discrepancy is retained and not patched.
- `reports/statement3_vs_prs.csv` records 395 matches and 13 differences explicitly noted as PRS provisional-actual labeling differences; there are no unexplained `MISMATCH` rows.
- `reports/cross_edition_check.csv` contains 421 repeated PRS values: 410 agree within ₹1 crore, while 11 differ by more than ₹1 crore and remain listed for review.
- Thirty-six legacy Statement 2 rows have a `quality_note` because the printed Revenue/Capital components do not add to the reported total. Their component values are omitted; the reported total remains available.

## Unresolved Phase 1 gaps

| Gap | Effect | Status |
| --- | --- | --- |
| PRS D1-D3 analyses before FY2019-20 | The ministry/scheme/fiscal panel cannot be reconstructed from PRS analysis PDFs for FY2005-06 through FY2018-19. Seven PRS PDFs are present; FY2025-26 is supplied as a sourced web transcription. | Historical PRS analyses have not been located/downloaded. |
| Four historical PSU-bank sector allocations | The source Statement 2 tables contain no Financial Services allocation for FY2005-06, FY2006-07 or FY2007-08. The FY2009-10 table lists Financial Services only for Actual 2007-08 and RE 2008-09, with no BE 2009-10 value. These panel rows are missing, not zero-filled. | Source-page continuation parsing was fixed and the remaining source rows were checked; no FY2005-06–FY2007-08 line or FY2009-10 BE allocation is printed. |
| D4 revenue/capital component coverage | Legacy Statement 2 editions do not provide a consistent revenue/capital split; `revenue_cr`, `capital_cr` and `total_cr` therefore contain nulls where the source does not support a value. | Partial source coverage; no inference or OCR fallback is applied. |
| Recent D4 PDF table layout | The FY2026-27 PDF parser currently extracts 36 rows across two departments, while the verified source transcription contains the fuller table. Other recent editions also have layouts the text parser does not fully extract. | The complete sourced transcription is used; parser/OCR coverage remains to be improved. |
| Optional LLM fallback | `parsers/llm_fallback.py` is not implemented. | Optional FR-5 work remains open; accepted rows still pass the strict ministry reconciliation. |
| Interim budgets | The panel contains full budgets and does not model interim budgets separately. | Decide whether to add them in the later event/feature phase. |

`config/ministry_aliases.csv` documents legacy ministry and department names. `Power + MNRE` and `Other Ministries` are explicitly derived aggregates; neither is presented as a printed source line.

## Phase 2 market, flow and macro gaps

Checked 2026-10-25 from the cloud sandbox, whose network allowlist blocks NSDL, FRED, niftyindices.com, NSE and the World Bank (HTTP 403 from the egress proxy). Yahoo Finance is reachable. All collectors were hardened so a blocked run keeps the previous CSV instead of overwriting it with an empty one (`write_csv_guarded`; `macro.py` also keeps the rows of any series that failed this run).

| Gap | Effect | Status / what to do by hand |
| --- | --- | --- |
| NSDL FPI before 2018-09-15 | `fpi_sector_fortnightly.csv` still starts at `period_end` 2018-09-15 (2,922 rows). The 2017-01 to 2018-08 fortnights failed earlier because `html5lib` was missing; it is now a dependency. NSDL is blocked here, so the re-run could not fetch them. | On a laptop: `pip install -e ".[dev]"` then `python -m bsp.ingest.fpi`. Raw pages are cached in `data/raw/nsdl_fpi/`. |
| 10-year G-sec yield (FRED `IRLTLT01INM156N`) | No `g_sec_10y_yield` series in `macro.csv`. FRED returns 404 for that series URL earlier and is blocked here now. | On a laptop run `python -m bsp.ingest.macro`. If FRED still 404s, download the series from RBI DBIE and add it as a manual file (needs a loader; not built). |
| Repo rate | No `repo_rate` series. `data/raw/rbi/repo_rate.csv` does not exist. `policy_discount_rate` (World Bank/FRED, annual-frequency source) is the only policy-rate proxy. | Download the policy repo-rate history from RBI DBIE and save it as `data/raw/rbi/repo_rate.csv` with columns `date,value`; then run `python -m bsp.ingest.macro`. |
| Nifty Healthcare index | Yahoo returns 404 "Quote not found" for `^CNXHEALTH` (retried 2026-10-25). No official index cross-check for Healthcare. | Optional: put a niftyindices.com download in `data/raw/indices/` with columns `index_name,date,close` (the manual loader is in `ingest/benchmarks.py`). Otherwise: no official index cross-check for Healthcare. |
| Point-in-time Nifty 500 constituents | `nifty500_constituents.csv` is header-only (columns `symbol, effective_from, effective_to, source, source_url, fetched_at`). niftyindices.com and NSE are blocked from the sandbox, so neither the current list nor any index-change press release could be downloaded. History cannot be rebuilt back to any year yet. Until the file is populated the universe filter drops nothing (0 stock-year rows dropped; see `reports/universe_filter.csv`) and only the listing-date check applies. | See "Nifty 500 history: how to finish" below. |

### Nifty 500 history: how to finish (by hand, on a laptop)

`scripts/collect/nifty500_history.py` is written and unit-tested on hand-made fixtures (`tests/test_nifty500_history.py`) but has **never run against real niftyindices/NSE files**, so the press-release layout it assumes is unverified.

1. Download the current list from `https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv` (the script does this itself on a laptop; otherwise save it as `data/raw/nifty500_constituents/ind_nifty500list_<YYYY-MM-DD>.csv`).
2. Collect the niftyindices.com / NSE index-change press releases ("Changes in Nifty indices", semi-annual and ad hoc). Save each as `data/raw/nifty500_constituents/press_releases/<YYYY-MM-DD>.pdf`, where the date is the day the change takes effect, and/or list `effective_date,url` in `config/nifty500_press_releases.csv` so the script downloads them.
3. Run `python scripts/collect/nifty500_history.py`. Releases it cannot parse, and company names it cannot map to a symbol, are listed in `reports/nifty500_history_report.csv`; map names by hand in `config/nifty500_name_aliases.csv` (`company_name,symbol`).
4. Run `python -m bsp.ingest.constituents` and `make features`. Coverage starts the day before the oldest release you supply; budgets before that date are **not** filtered (earlier years are never filled). State the first covered year here once known.

Known limits of the method: symbol changes/mergers are not tracked; a company that is both included and excluded in one release is reported, not resolved.

### Price data decisions (Phase 2)

Every single-day move above 50% in the raw Yahoo download has a documented decision in `reports/price_flag_decisions.csv` (36 flags: 18 rows dropped as data errors, 14 rows kept because the jump came from a dropped neighbour, 1 split adjustment, 3 kept as real/unverified). Rows removed are listed in `reports/price_rows_dropped.csv`. Three moves remain unexplained and need a check against NSE corporate-actions files: **NIITLTD 2023-06-08** (-76%), **TEXRAIL 2010-11-01** (-60%) and **TEXRAIL 2011-03-03** (+74%). They stay in the data and will distort those stocks' momentum features until resolved. Also, `data/csv/prices_daily.csv` is about 93 MB, close to GitHub's 100 MB file limit; move it to Git LFS or split it before it grows.

### Git LFS for `data/csv/prices_daily.csv` (pending, needs network access)

The file is 93 MB, close to GitHub's 100 MB limit. The CI workflows already check out with `lfs: true`. The `.gitattributes` entry and pointer commit exist only on a local, unpushed branch because the cloud environment's network policy blocks `lfs.github.com` (HTTP 403 on the LFS verify call). To finish on a laptop (or after adding `lfs.github.com` to the environment's allowed domains):

```
git lfs install
git lfs track "data/csv/prices_daily.csv"          # writes .gitattributes
git rm --cached data/csv/prices_daily.csv && git add .gitattributes data/csv/prices_daily.csv
git commit -m "Track prices_daily.csv with Git LFS" && git push
```

The earlier history still contains the full file; do not rewrite pushed history unless you decide to run `git lfs migrate`.

### Sector baskets (Phase 2)

All 15 baskets start on 2004-12-02, but several are thin at the start (`reports/sector_basket_report.csv`): defence has 2 stocks until 2017-08, railways 1 until 2018-07, housing 1 until 2007-07, power and rural 2 until 2005-10 and 2006-03. Correlations with official indices are reported where a reasonable index exists (0.69 to 0.94); agriculture, defence, education, fertilisers, railways, telecom and water have no clean official index in the downloaded set.

### Phase 3 limitations

Sector-year features that depend on gaps above are sparse: scheme push (15% of rows), fiscal stance (41%, PRS tables start FY2019-20), FPI flows (21%, data starts 2018-09). The stock universe is filtered by listing date only until the Nifty 500 history exists. Macro features use the last observation on or before the budget date (dates were normalised to one ISO date per row when the date format was cleaned up).

## Out of Phase 1

Phase 1 itself did not cover market, index, macro or FPI collection; see the Phase 2 section above.
