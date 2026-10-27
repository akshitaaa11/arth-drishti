# Price-data fixes: TEXRAIL listing date and NIITLTD demerger break

Both fixes are applied by the pipeline from two sourced config files; no price CSV was edited by hand. Evidence is from secondary sources and is **not verified on the exchange**.

## 1. TEXRAIL (Texmaco Rail & Engineering)

- `config/listing_date_overrides.csv`: listing date **2011-03-03** (secondary source, not verified on the exchange): https://www.kotaksecurities.com/stocks/texmaco-rail-engineering-ltd
- The Yahoo series started 2004-12-01, before the company existed (demerged from Texmaco Ltd). The price job now drops every row before the listing date (`before_listing` in `reports/price_rows_dropped.csv`), `stocks.csv` carries the listing date, and `stock_first_price_date.csv` starts on it.
- The universe's "listed on or before the budget date" check therefore excludes TEXRAIL for every budget presented before 2011-03-03, including FY2011-12 (presented 2011-02-28).

### Railways basket (new start date: **2008-04-23**, previously 2004-12-02)

Stocks in the basket on each budget day (the basket only holds a stock from its listing date):

| Budget | Presented | Stocks | Members |
| --- | --- | ---: | --- |
| FY2005-06 | 2005-02-28 | 0 | (empty) |
| FY2006-07 | 2006-02-28 | 0 | (empty) |
| FY2007-08 | 2007-02-28 | 0 | (empty) |
| FY2008-09 | 2008-02-29 | 0 | (empty) |
| FY2009-10-I | 2009-02-16 | 1 | TITAGARH |
| FY2009-10 | 2009-07-06 | 1 | TITAGARH |
| FY2010-11 | 2010-02-26 | 1 | TITAGARH |
| FY2011-12 | 2011-02-28 | 1 | TITAGARH |
| FY2012-13 | 2012-03-16 | 2 | TITAGARH TEXRAIL |
| FY2013-14 | 2013-02-28 | 2 | TITAGARH TEXRAIL |
| FY2014-15-I | 2014-02-17 | 2 | TITAGARH TEXRAIL |
| FY2014-15 | 2014-07-10 | 2 | TITAGARH TEXRAIL |
| FY2015-16 | 2015-02-28 | 2 | TITAGARH TEXRAIL |
| FY2016-17 | 2016-02-29 | 2 | TITAGARH TEXRAIL |
| FY2017-18 | 2017-02-01 | 2 | TITAGARH TEXRAIL |
| FY2018-19 | 2018-02-01 | 2 | TITAGARH TEXRAIL |
| FY2019-20-I | 2019-02-01 | 4 | IRCON TITAGARH RITES TEXRAIL |
| FY2019-20 | 2019-07-05 | 5 | RVNL IRCON TITAGARH RITES TEXRAIL |
| FY2020-21 | 2020-02-01 | 6 | RVNL IRCON TITAGARH IRCTC RITES TEXRAIL |
| FY2021-22 | 2021-02-01 | 7 | RVNL IRCON IRFC TITAGARH IRCTC RITES TEXRAIL |
| FY2022-23 | 2022-02-01 | 8 | RVNL IRCON IRFC RAILTEL TITAGARH IRCTC RITES TEXRAIL |
| FY2023-24 | 2023-02-01 | 8 | RVNL IRCON IRFC RAILTEL TITAGARH IRCTC RITES TEXRAIL |
| FY2024-25-I | 2024-02-01 | 8 | RVNL IRCON IRFC RAILTEL TITAGARH IRCTC RITES TEXRAIL |
| FY2024-25 | 2024-07-23 | 8 | RVNL IRCON IRFC RAILTEL TITAGARH IRCTC RITES TEXRAIL |
| FY2025-26 | 2025-02-01 | 8 | RVNL IRCON IRFC RAILTEL TITAGARH IRCTC RITES TEXRAIL |
| FY2026-27 | 2026-02-01 | 8 | RVNL IRCON IRFC RAILTEL TITAGARH IRCTC RITES TEXRAIL |

Railways sector-years with an empty basket are **missing, never filled**: their price features are empty and their targets have `target_complete = False`:

FY2005-06, FY2006-07, FY2007-08, FY2008-09

**Tier 1 training rows removed: 4** (the Railways rows of FY2005-06, FY2006-07, FY2007-08, FY2008-09; they used to carry numbers computed from TEXRAIL's pre-listing prices). Every walk-forward fold from FY2012-13 on trains without them:

| Test budget | Training rows now | Training rows before | Removed |
| --- | ---: | ---: | ---: |
| FY2012-13 | 101 | 105 | 4 |
| FY2013-14 | 116 | 120 | 4 |
| FY2014-15 | 131 | 135 | 4 |
| FY2015-16 | 146 | 150 | 4 |
| FY2016-17 | 161 | 165 | 4 |
| FY2017-18 | 176 | 180 | 4 |
| FY2018-19 | 191 | 195 | 4 |
| FY2019-20 | 206 | 210 | 4 |
| FY2020-21 | 221 | 225 | 4 |
| FY2021-22 | 236 | 240 | 4 |
| FY2022-23 | 251 | 255 | 4 |
| FY2023-24 | 266 | 270 | 4 |

Three more Railways sector-years (FY2009-10 to FY2011-12) stay in the data but are now a one-stock basket (TITAGARH), because TEXRAIL's pre-listing prices no longer count. Other sectors' early targets moved by small amounts, because the market return that bridges Nifty 500 index gaps is the equal-weight mean of all stocks, and TEXRAIL's spurious prices were in that mean.

## 2. NIITLTD 2023-06-08 (demerger ex-date)

- `config/return_exclusions.csv`: secondary source, not verified on the exchange: https://www.businesstoday.in/amp/markets/stocks/story/niit-shares-to-turn-ex-date-for-demerger-today-key-details-384676-2023-06-08; https://www.niit.com/india/?p=8162
- That day's return (about -76%) is treated as **missing**: it never enters a basket, a volatility, a beta or an event study, and a momentum or target window that spans the day divides it out. Prices are not rescaled and no adjustment factor is invented; the only number used is that day's own observed return.
- Education basket return on 2023-06-08: -0.0125; the mean of its other stocks that day: -0.0125 (they match: NIITLTD is skipped).

## 3. Stocks whose first price date is the download start (2004-12-01)

56 stocks. Their true listing dates are unknown from this data and **none was changed** (no source). The universe's listing check is satisfied for them at every budget. Full list with company names (from Yahoo's quote summary) and sectors: `reports/stocks_first_price_at_download_start.csv`.

| Symbol | Company | Sector |
| --- | --- | --- |
| ESCORTS | Escorts Kubota Limited | agriculture |
| M&M | Mahindra & Mahindra Limited | agriculture |
| RALLIS | Rallis India Limited | agriculture |
| UPL | UPL Limited | agriculture |
| BEL | Bharat Electronics Limited | defence |
| BEML | BEML Limited | defence |
| APTECHT | Aptech Limited | education |
| NAVNETEDUL | Navneet Education Limited | education |
| NIITLTD | NIIT Limited | education |
| CHAMBLFERT | Chambal Fertilisers and Chemicals Limited | fertilisers |
| COROMANDEL | Coromandel International Limited | fertilisers |
| DEEPAKFERT | Deepak Fertilisers And Petrochemicals Corporation Limited | fertilisers |
| FACT | The Fertilisers and Chemicals Travancore Limited | fertilisers |
| GSFC | Gujarat State Fertilizers & Chemicals Limited | fertilisers |
| RCF | Rashtriya Chemicals and Fertilizers Limited | fertilisers |
| BRITANNIA | Britannia Industries Limited | fmcg |
| DABUR | Dabur India Limited | fmcg |
| HINDUNILVR | Hindustan Unilever Limited | fmcg |
| ITC | ITC Limited | fmcg |
| KRBL | KRBL Limited | fmcg |
| TATACONSUM | Tata Consumer Products Limited | fmcg |
| APOLLOHOSP | Apollo Hospitals Enterprise Limited | healthcare |
| BIOCON | Biocon Limited | healthcare |
| CIPLA | Cipla Limited | healthcare |
| DRREDDY | Dr. Reddy's Laboratories Limited | healthcare |
| LUPIN | Lupin Limited | healthcare |
| SUNPHARMA | Sun Pharmaceutical Industries Limited | healthcare |
| LICHSGFIN | LIC Housing Finance Limited | housing |
| HCLTECH | HCL Technologies Limited | it_control |
| INFY | Infosys Limited | it_control |
| MPHASIS | Mphasis Limited | it_control |
| TCS | Tata Consultancy Services Limited | it_control |
| WIPRO | Wipro Limited | it_control |
| NTPC | NTPC Limited | power |
| TATAPOWER | The Tata Power Company Limited | power |
| BANKBARODA | Bank of Baroda Limited | psu_banks |
| CANBK | Canara Bank | psu_banks |
| PNB | Punjab National Bank | psu_banks |
| SBIN | State Bank of India | psu_banks |
| UNIONBANK | Union Bank of India | psu_banks |
| LT | Larsen & Toubro Limited | roads |
| NCC | NCC Limited | roads |
| ULTRACEMCO | UltraTech Cement Limited | roads |
| HEROMOTOCO | Hero MotoCorp Limited | rural |
| TVSMOTOR | TVS Motor Company Limited | rural |
| BHARTIARTL | Bharti Airtel Limited | telecom |
| HFCL | HFCL Limited | telecom |
| ITI | ITI Limited | telecom |
| STLTECH | Sterlite Technologies Limited | telecom |
| TATACOMM | Tata Communications Limited | telecom |
| FINPIPE | Finolex Industries Limited | water |
| JINDALSAW | Jindal Saw Limited | water |
| KSB | KSB Limited | water |
| MAHSEAMLES | Maharashtra Seamless Limited | water |
| SUPREMEIND | The Supreme Industries Limited | water |
| WELCORP | Welspun Corp Limited | water |
