# Budget dataset: what is in this folder

```
config/        sector_map.json, stocks.csv (118 stocks), budget_events.csv (26 budgets), sector_budget_lines.csv, canonical_names.csv
data/source_pdfs/   the PDFs you supplied (copies)
data/raw/web_transcribed/   numbers read from official PDFs through a web tool (Statement 3 editions, PRS 2025-26)
data/csv/      all clean CSVs (every row has source_doc + source_page)
reports/       checks: reconciliation, cross-edition, spot-check, data_gaps.md
scripts/       parse_prs.py, build_statement3.py, build_budget_csvs.py, collect_market_data.py
```

## Rebuild the budget CSVs from the PDFs and transcriptions
```
python scripts/parse_prs.py data/source_pdfs data/csv     # needs pdftotext (poppler)
python scripts/build_statement3.py
python scripts/build_budget_csvs.py
```
## Collect market data (laptop only)
```
pip install -r requirements.txt
python scripts/collect_market_data.py symbols   # fix reports/symbol_check.csv failures in config/stocks.csv first
python scripts/collect_market_data.py all
```
## Key CSVs
- `sector_budget_panel.csv`: one row per sector x budget. Columns include `be_current_cr`, `re_previous_cr`, `surprise_vs_prev_re_pct` (new BE vs last RE), `credibility_pct` (mean of Actual/BE - 1 over the last up-to-3 years whose actuals were public), `capex_share_be_pct`, `supporting_lines`, `source`.
- `budget_departments.csv`: ~100-demand-level lines with revenue / capital / total.
- `budget_ministries.csv`, `budget_schemes.csv`, `budget_fiscal.csv`: PRS tables in long format.
- `budget_allocations_FY2020-21_verified.csv`: your example file with the source page filled in.

Full status and caveats: `reports/data_gaps.md`.
