# Symbols dropped between the original kit (118) and `config/stocks.csv` (116)

The original kit list is preserved in `budget_data/budget_data/config/stocks.csv` (118 symbols). The working list
`config/stocks.csv` and `config/sector_map.json` hold **116** symbols, and `reports/symbol_check.csv` shows all 116
downloading from Yahoo Finance. The difference is exactly two dropped stocks plus one rename.

| Symbol (original) | Sector | What happened | Evidence (Yahoo probe 2026-10-25, `data/raw/yahoo_symbol_probe/probe_2026-10-25.csv`) |
| --- | --- | --- | --- |
| `CAREERP` (`CAREERP.NS`) | education | **Dropped**: no data on Yahoo | `CAREERP.NS` and `CAREERP.BO`: 0 rows, "possibly delisted; no timezone found". No alternative symbol was found, so it cannot be priced. Education now has 5 stocks. |
| `LTIM` (`LTIM.NS`) | it_control | **Dropped**: no data on Yahoo | `LTIM.NS` and `LTIM.BO`: 0 rows. IT Services is the control sector, now with 7 stocks. |
| `EMAMI` (`EMAMI.NS`) | rural | **Renamed** to `EMAMILTD` (`EMAMILTD.NS`), not dropped | `EMAMI.NS`: 0 rows (404 quote not found); `EMAMILTD.NS`: 4,988 rows, 2006-08-03 to 2026-10-23. |

Rows 118 - 2 dropped = 116. Re-adding either dropped stock needs a working Yahoo symbol or an NSE bhavcopy
download (README Phase 2 fallback); do not add them back without a source file under `data/raw/`.

Consistency is enforced by `tests/test_config_consistency.py`: `stocks.csv`, `sector_map.json` and
`symbol_check.csv` must contain the same 116 symbols, and every symbol must belong to one of the 15 sectors.
