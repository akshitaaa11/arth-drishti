# Stocks removed from every budget by the Nifty 500 universe filter

`config/stocks.csv` has 116 symbols; the stock-year features contain 112. The other four have no stock-year row at any
budget because the provisional Nifty 500 history (7 press releases, coverage from 2015-12-13) never lists them as a member
on a budget day they were listed for.

| Symbol | Sector | First price date | Budgets on/after listing (all dropped) | In today's Nifty 500 list? | In any of the 7 releases? |
| --- | --- | --- | ---: | --- | --- |
| GODREJAGRO | agriculture | 2017-10-16 | 11 | No | No |
| HGINFRA | roads | 2018-03-09 | 10 | No | No |
| PNCINFRA | roads | 2015-05-26 | 13 | No | No |
| SCHAND | education | 2017-05-09 | 11 | No | No |

**How "in today's list" was read.** `data/csv/nifty500_constituents.csv` was built from the downloaded current list: every
symbol in that list has an interval with a blank `effective_to` (501 such intervals). None of these four symbols appears in the
file at all, neither with an open nor a closed interval, so none is in the downloaded list under the symbol in `stocks.csv`.
The list file itself is under `data/raw/` (git-ignored), so this was derived from the CSV, not from the list. To confirm directly
on a machine that has it:

```
grep -i -E "GODREJAGRO|HGINFRA|PNCINFRA|SCHAND|godrej agrovet|h\.g\. infra|pnc infratech|s chand" data/raw/nifty500_constituents/ind_nifty500list_*.csv
```

No output means the company is not in today's list under any of those spellings (which also rules out a renamed symbol).
`config/nifty500_symbol_aliases.csv` is empty and was not edited: no source documents a rename for any of the four.

**Why they were dropped.** For every budget from FY2016-17 on, the history covers the budget day, and these symbols are neither in
today's list nor in an interval built from the releases, so the filter treats them as non-members. What the data cannot say is
whether any of them was a member for part of 2015-2025, because only seven of the index changes in that period are listed. A
stock that left in an unlisted review looks exactly like one that was never a member. The 18 other stocks with
`dropped_not_in_nifty500` at recent budgets are partly covered by releases and are kept at the budgets where the history shows them
as members.

**What to do.** Add the missing releases to `config/nifty500_press_releases.csv` and re-run
`python scripts/collect/nifty500_history.py`; if any of the four then gets an interval, `make features` brings it back. Until
then, these four are excluded from the evaluation universe and the result is provisional.
