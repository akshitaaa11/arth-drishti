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

## Out of Phase 1

No Phase 2 market, index, macro or FPI collection was started. Historical index constituents, prices and other later-phase sources remain out of scope for this Phase 1 build.
