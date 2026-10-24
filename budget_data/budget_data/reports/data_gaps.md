# Data status and gaps (built 2026-10-23)

## Done, real data, verified
| Dataset | Coverage | File | How it was checked |
| --- | --- | --- | --- |
| Ministry / scheme / subsidy / fiscal tables (PRS) | Budgets 2019-20 to 2026-27 (7 PDFs you supplied) + 2025-26 | `budget_ministries/schemes/fiscal.csv` | 59 of 60 total-reconciliations pass; 25 of 25 random values found on their recorded PDF page |
| Department-level expenditure with revenue / capital split | Budgets 2017-18 to 2026-27 (10 Expenditure Profiles, Statement 3) | `budget_departments.csv` | 395 of 395 values match PRS; 520 of 520 values printed in two editions are identical; revenue + capital = total in all 1,164 rows |
| Sector panel: 15 sectors x 10 budgets = 150 rows | 2017-18 to 2026-27 | `sector_budget_panel.csv` | Your 2020-21 example reproduced exactly (10 of 10 sectors, BE and capex share) |

## Not done, and why
| Item | Status | What to do |
| --- | --- | --- |
| Budgets FY2005-06 to FY2016-17 | Not collected. The pattern `https://www.indiabudget.gov.in/budget_archive/ubYYYY-YY/eb/vol1.pdf` (Statement 3) works for older years; each year needs about 2 fetches and a new department-name alias | Add year by year, newest first. Run `build_statement3.py` then `build_budget_csvs.py` |
| Interim budgets (Feb 2019, Feb 2024, 2014, 2009) | Not in panel. The panel uses the full July budgets | Decide in Phase 3 whether interim events get their own rows |
| Daily stock prices, indices, macro, FPI | **Scripts written and syntax-checked; not run.** Yahoo, FRED and NSDL block this workspace | Run `python scripts/collect_market_data.py all` on your laptop |
| Historical Nifty 500 constituents | Not collected. niftyindices.com publishes semi-annual lists only as separate files | Manual download into `data/raw/nifty500_constituents/`, then a loader (Phase 2) |
| RBI repo rate | Manual: DBIE has no stable CSV link | Save `data/raw/rbi/repo_rate.csv` with columns `date,value` |
| Company fundamentals, order wins, procurement, speech text, budget-week news, CGA monthly | Not started | Phases 5 and 6 |
| Scheme history for Power, IT and PSU banks | PRS lists only the 13-15 largest schemes per year | Use the department-level lines (already in the panel) |

## Caveats to state at the viva
1. **Transcription route.** The Expenditure Profile numbers were read from the official PDFs through a web tool because the workspace cannot download them directly. They are checked three ways (above), but the earliest column of each edition (e.g. Actuals 2015-16, 2016-17) appears in one edition only and is not cross-checked.
2. **Ministry definitions are my grouping.** Departments are summed to PRS ministry names in `scripts/build_statement3.py` (`MINISTRY_OF`). Examples: Communications = Telecom + Posts; Jal Shakti = Drinking Water + Water Resources (also before the 2019 merger); Housing & Urban Affairs = two ministries in the 2017-18 edition; Power + MNRE is one sector line.
3. **Series breaks.** Railways before 2017-18 was a separate budget; Defence demands were reclassified in 2017-18 (Defence Misc. fell while Defence Services rose; the ministry total is stable); Finance-Financial Services is dominated by bank recapitalisation, so it is very lumpy.
4. **PRS 2024-25 (July 2024) labels 2023-24 RE as "Actual".** The panel uses the true RE from Statement 3 for that year. 13 PRS values differ from Statement 3 for this reason, documented in `reports/statement3_vs_prs.csv`.
5. **PRS editions sometimes restate.** 10 of 423 repeated PRS values differ between editions (e.g. NHM 2023-24 BE); see `reports/cross_edition_check.csv`.
6. **PRS 2024-25 subsidy total** is printed as 4,38,423 but its rows add to 4,28,423; the other edition prints 4,28,423. This is the one failed reconciliation.
7. **2025-26 PRS tables** were read through a web tool (the PDF is not in your folder); see `data/raw/web_transcribed/prs_2025-26_tables.txt`.
