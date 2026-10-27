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
| NSDL FPI before 2018-09-15 (and 120 later fortnights) | `fpi_sector_fortnightly.csv` has 75 of the 235 fortnights since 2017-01: all 40 fortnights before 2018-09-15 and 120 between 2018-09 and 2026-06 are missing (by year: 2019: 2, 2020: 10, 2021: 16, 2022: 18, 2023: 22, 2024: 18, 2025: 18, 2026: 15). The collector used to cache NSDL's "Request Rejected" page (it comes back as HTTP 200) as if it were a report, so re-runs never asked again. | Fixed in `ingest/fpi.py`: such a page is detected, never cached, logged in `fetch_log` as `blocked`, previously poisoned cache files are deleted on the next run, and the CSV is merged, never shrunk. On the laptop/Codespace run `python -m bsp.ingest.fpi` again (it stops after 5 consecutive blocks instead of hammering the site; wait and re-run if it reports `blocked`). |
| 10-year G-sec yield | No `g_sec_10y_yield` series in `macro.csv` yet. The old FRED id `IRLTLT01INM156N` no longer exists; the series is now `INDIRLTLT01STM` (OECD via FRED, https://fred.stlouisfed.org/series/INDIRLTLT01STM), **monthly and only from 2011-12**, so months before 2011-12 stay empty (nothing is filled or estimated), and every budget before FY2011-12 has no G-sec feature. | `ingest/macro.py` now downloads `INDIRLTLT01STM` and, if the download fails, reads `data/raw/fred/INDIRLTLT01STM.csv` (columns `observation_date, INDIRLTLT01STM`; `.` = missing). Run `python -m bsp.ingest.macro` where FRED is reachable, or save that file by hand and run it; `fetch_log` then says "g_sec_10y_yield from manual file". The series is not yet used by any feature. |
| Repo rate | No `repo_rate` series. `data/raw/rbi/repo_rate.csv` does not exist. `policy_discount_rate` (World Bank/FRED, annual-frequency source) is the only policy-rate proxy. | Download the policy repo-rate history from RBI DBIE and save it as `data/raw/rbi/repo_rate.csv` with columns `date,value`; then run `python -m bsp.ingest.macro`. |
| Nifty Healthcare index | Yahoo returns 404 "Quote not found" for `^CNXHEALTH` (retried 2026-10-25). No official index cross-check for Healthcare. | Optional: put a niftyindices.com download in `data/raw/indices/` with columns `index_name,date,close` (the manual loader is in `ingest/benchmarks.py`). Otherwise: no official index cross-check for Healthcare. |
| Point-in-time Nifty 500 constituents | `nifty500_constituents.csv` is header-only (columns `symbol, effective_from, effective_to, source, source_url, fetched_at`). niftyindices.com and NSE are blocked from the sandbox, so neither the current list nor any index-change press release could be downloaded. History cannot be rebuilt back to any year yet. Until the file is populated the universe filter drops nothing (0 stock-year rows dropped; see `reports/universe_filter.csv`) and only the listing-date check applies. | See "Nifty 500 history: how to finish" below. |

### Nifty 500 history: how to finish (on a laptop / Codespace)

`scripts/collect/nifty500_history.py` now reads the seven real NSE Indices press releases in
`tests/fixtures/nifty500_press_releases/` (2015-12-14, 2017-03-31, 2019-06-28, 2021-04-29, 2022-08-08, 2025-09-23,
2025-12-31) and gives the exact symbols and effective dates asserted in `tests/test_nifty500_history.py`; only the
"Nifty 500" sub-section of each release counts (sections for Nifty Smallcap 250, "Nifty500 Equal Weight" notes and
similar are ignored). It still has not run against the live current list, which only a networked machine can download.

1. `python scripts/collect/nifty500_history.py` downloads the releases listed in `config/nifty500_press_releases.csv`
   (effective date, URL) into `data/raw/nifty500_constituents/press_releases/` and the current list from
   `https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv`. It prints excluded/included counts per release and exits
   non-zero, writing nothing, if a listed release yields no Nifty 500 changes or cannot be read.
2. Problems that are not parser errors go to `reports/nifty500_history_report.csv`: a symbol included in a release that is not a
   member afterwards, or excluded but already a member. A company whose symbol changed since a release was printed is mapped by
   hand in `config/nifty500_symbol_aliases.csv` (`old_symbol,current_symbol`).
3. `python -m bsp.ingest.constituents`, then `make features`. Coverage starts the day before the oldest release (2015-12-13);
   budgets before that are not filtered and no earlier year is filled.

**Coverage caveat (important).** Only seven releases are listed, while NSE Indices also publishes the semi-annual review and
ad hoc replacements that are not in the list. Between two listed releases the history is therefore not known to be complete:
a company that joined or left in an unlisted review is shown as a member for the whole span (if it is in today's list) or as
never a member (if it is not). Until every Nifty 500 change since 2015-12 is listed, treat `universe_filter.csv` and the
stock-year rows it drops as provisional, and check `reports/nifty500_history_report.csv` after each run: an "included but not
a member afterwards" line usually means a release is missing in between. Add the missing release URLs to
`config/nifty500_press_releases.csv` and re-run.

### Price data decisions (Phase 2)

Every single-day move above 50% in the raw Yahoo download has a documented decision in `reports/price_flag_decisions.csv` (36 flags: 18 rows dropped as data errors, 14 rows kept because the jump came from a dropped neighbour, 1 split adjustment, 3 kept as real/unverified). Rows removed are listed in `reports/price_rows_dropped.csv`. The three moves that were unexplained are now resolved from sourced config files (secondary sources, **not verified on the exchange**; details in `reports/price_data_fixes.md`): **TEXRAIL** was listed on 2011-03-03 (`config/listing_date_overrides.csv`), so every Yahoo row before that date is dropped as a data error (including the 2010-11-01 and 2011-03-03 flags); **NIITLTD 2023-06-08** is a demerger ex-date (`config/return_exclusions.csv`), so that day's return is treated as missing in momentum, beta, baskets and the event study, with no adjustment factor invented. Consequence: the Railways basket starts 2008-04-23 (TITAGARH alone until TEXRAIL joins), so the Railways sector-years FY2005-06 to FY2008-09 are missing, not filled (4 Tier 1 training rows fewer per walk-forward fold). 56 stocks have 2004-12-01 (the download start) as first price date; their true listing dates are unknown and unchanged (`reports/stocks_first_price_at_download_start.csv`). Also, `data/csv/prices_daily.csv` is about 93 MB, close to GitHub's 100 MB file limit; move it to Git LFS or split it before it grows.

### FPI URL pattern for 2017-01 to 2018-08: not established

The question was whether those 40 reports use a different file name. Evidence in the repository does not show it:
every one of the 2,922 loaded rows (2018-09-15 to 2026-06-30) has a `source_url` identical to what `fpi_url()` builds
(`.../FIIInvestSector_<Month><day><year>.html`, for example `September152018`), and the PRD's example for July 2024 has the
same shape. The first Codespace run (`data/csv/fetch_log.csv`, 2026-10-24 14:53) lists 163 failed fortnights, each
"parse: Import html5lib failed", which `pandas.read_html` raises when a page contains no table, i.e. when the response
was not a report. Those failures are not confined to the early years (120 of the 195 fortnights after 2018-09 failed
too), which points to intermittent blocking and the poisoned cache rather than a different name. I therefore did **not**
change the URL builder. To settle it with real evidence after re-running the collector, run
`python -m bsp.ingest.fpi --probe 2017-01-15`: it prints the HTTP status and whether the response is a report or an error
page, and saves it under `data/raw/nsdl_fpi/probe/`. If it is not a report, open NSDL's fortnightly-report archive in a
browser, copy the link of one 2017 report and run `python -m bsp.ingest.fpi --probe <that full URL>`; send me the output
and the link and I will adapt the builder. No FPI value has been typed in or estimated.

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
