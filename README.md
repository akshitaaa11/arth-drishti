# Budget-Based Sector Growth and Stock Return Prediction

An explainable, backtested system that reads each Union Budget on the day it is presented. It scores **15 budget-sensitive sectors** and **~120 NSE stocks**, and shows which ones history says should outperform the **Nifty 500 over the next 12 months**, with calibrated confidence ranges.

> **Research tool, not investment advice.** This project never gives buy/sell or personalised recommendations.

The full product spec is in [`PRD.md`](./PRD.md) (*PRD — Budget-Based Sector Growth and Stock Return Prediction*, 23 Oct 2026). This README is the **build guide**: repo layout, ground rules, and the complete phase-by-phase plan from empty repo to Budget Day and the final viva. Section references like "PRD §6" point into that document.

> **Scope change from the synopsis.** The first version covered **3 sectors**. This version covers **15 sectors and 116 stocks**, each tied to the ministry or scheme lines that fund it (see `config/sector_map.json`).
>
> **Starting point: only budget PDFs and documents exist.** The team has the PRS budget analysis PDFs and related documents. There is **no ready dataset**: every other dataset (prices, indices, FPI flows, macro, fundamentals, speeches, news) must be **collected by scripts the coding tool writes, and saved as CSV files** in `data/csv/`. Phase 1 and Phase 2 below do exactly that. Wherever the PRD says "In kit" or "Script ready", read it as "to build".

---

## Table of contents

1. [Research question](#1-research-question)
2. [What gets built](#2-what-gets-built)
3. [Ground rules (read before writing any code)](#3-ground-rules-read-before-writing-any-code)
4. [Tech stack](#4-tech-stack)
5. [Repository layout](#5-repository-layout)
6. [Setup](#6-setup)
7. [Configuration and secrets](#7-configuration-and-secrets)
8. [Data catalogue (quick reference)](#8-data-catalogue-quick-reference)
9. [Core database tables](#9-core-database-tables)
10. [Build phases, start to end](#10-build-phases-start-to-end)
11. [Make targets](#11-make-targets)
12. [Success metrics](#12-success-metrics)
13. [Testing strategy](#13-testing-strategy)
14. [Timeline](#14-timeline)
15. [How to use this README with an AI coding tool](#15-how-to-use-this-readme-with-an-ai-coding-tool)
16. [Risks and limitations](#16-risks-and-limitations)
17. [References](#17-references)

---

## 1. Research question

> Does the **surprise** in a sector's budget allocation predict its excess return after the budget? And how does that compare with what the market had already priced in on budget day?

**Surprise** is the new Budget Estimate (BE) against last year's Revised Estimate (RE), not the headline rupee number:

```
Surprise[s,t] = Σ BE[m,t] / Σ RE[m,t-1] − 1        (m = ministries/schemes mapped to sector s)
```

**Execution credibility** is the average gap between spending and promise over the last 3 years:

```
Cred[s,t] = (1/3) · Σ_{k=1..3} ( Actual[s,t-k] / BE[s,t-k] − 1 )
```

**Cumulative abnormal return (CAR)** uses a market model estimated on trading days −250 to −31 before the budget:

```
CAR[s][τ1,τ2] = Σ_{τ=τ1..τ2} ( r[s,τ] − α̂[s] − β̂[s] · r[m,τ] )
```

A null result (the models do not beat the baselines) is a valid outcome. It must be reported clearly, not hidden.

---

## 2. What gets built

| # | Deliverable | Description |
| --- | --- | --- |
| 1 | **Versioned dataset** | Budget lines (BE/RE/Actuals) linked to sectors and listed companies, with every number traceable to its source PDF page |
| 2 | **Two-tier model** | Tier 1 ranks the 15 sectors; Tier 2 ranks stocks within each sector. Walk-forward backtested against simple baselines |
| 3 | **Live dashboard** | 8 screens, including Budget-Day Live Mode, a what-if simulator, plain-language explanations and the **Budget Copilot** chatbot |

**Signature features (build these first among the features):**

- **F1 Budget-Day Live Mode with sealed predictions.** Forecasts published within minutes of the budget; their SHA-256 hash is committed to a public GitHub repo so they cannot be edited later.
- **F2 Promise-vs-Reality tracker.** BE vs RE vs Actuals for every ministry and scheme, with a credibility score.
- **F3 What-If Budget Simulator.** Sliders change allocations and the Tier-1 model re-scores every sector live, with SHAP reasons.

---

## 3. Ground rules (read before writing any code)

These rules apply to every human contributor and every AI coding agent. A change that breaks one of them is wrong even if the tests pass.

1. **No look-ahead.** A feature for budget year *t* may only use information public on that budget day. No same-year Actuals, no stocks listed after the budget, and no stock that fails the liquidity rule measured before the budget (average daily traded value over the prior 60 trading days of at least ₹5 cr). The leakage test (`tests/test_leakage.py`) must fail if any feature date ≥ its prediction date, if a same-year Actual is used, if a stock is not yet listed, or if a stock is below the liquidity threshold. **The universe rule does not check index membership on budget day, and the 116 stocks are today's symbols (delisted names are missing), so survivorship bias is reduced but NOT removed** (`reports/data_gaps.md`).
2. **No synthetic data.** Train and evaluate only on real data. Fixtures for unit tests may be small and hand-made, but must live under `tests/fixtures/` and never reach the feature store.
3. **Every number is traceable.** Every stored value carries `source_doc`, `source_page` (where applicable), `source_url` and `fetched_at` (FR-2).
4. **Budget totals must reconcile.** Sum of ministries + "Other" = Total Expenditure within 0.5%, or the parse **fails loudly** (FR-4). Never silently patch.
5. **Walk-forward only.** Train on budgets up to *t−1*, predict *t*. Hyperparameters are tuned *inside* each fold. FY2024-25 and FY2025-26 are the final hold-out; FY2026-27 is the sealed live year. Do not touch the hold-out until Phase 9.
6. **Idempotent jobs.** Every ingestion job is safe to re-run and writes a fetch log (FR-1).
7. **Secrets never in code.** API keys live in environment variables or a git-ignored `.env`. CI runs a secret scan that blocks commits containing one (FR-17).
8. **Read-only tools for the chatbot.** No Copilot tool can change data or place an order.
9. **Scrape politely.** Respect robots.txt, rate-limit requests, cache raw downloads.
10. **Reproducible.** `make data && make train && make backtest` must rebuild every number in the report from raw files. Seeds are fixed.
11. **IT Services is a control sector.** If the model finds a strong budget effect there, treat it as a leakage alarm, not a discovery.
12. **Every dataset lands as a CSV first.** Each collector writes a raw download to `data/raw/<source>/` and a clean, documented CSV to `data/csv/` (schemas in §8). Only then is it loaded into Postgres. The CSVs are the hand-off point: anyone can open them in Excel and check them.
13. **Collectors run on a laptop with normal internet.** Yahoo Finance, NSE, NSDL and similar sites often block cloud servers and AI sandboxes. If a download fails with a 403 or connection error inside the coding tool, do not invent data or retry endlessly: write the script, then run it locally (`make collect`).
14. **Never type in numbers from memory.** No hard-coded prices, allocations or flows. If a source cannot be reached, leave the CSV empty and log the gap.

---

## 4. Tech stack

| Layer | Choice |
| --- | --- |
| Language | Python 3.11 |
| Data | pandas, pdfplumber, requests, yfinance, PostgreSQL 15 (Supabase free tier or local Docker) |
| Data quality | pandera (or Great Expectations) |
| ML | scikit-learn, LightGBM / XGBoost, PyMC, MAPIE (conformal), SHAP, Optuna, MLflow |
| NLP | Hugging Face Transformers (FinBERT / zero-shot), sentence-transformers (retrieval), Groq API (chatbot + parser fallback, tool calling) |
| Backend | FastAPI, APScheduler, FastAPI WebSockets, Redis (live-quote and answer cache) |
| Frontend | React + Vite + Recharts/Plotly; Streamlit as an internal analyst console |
| Live data | Broker WebSocket API: Upstox or Angel One SmartAPI (Dhan / Zerodha Kite Connect as alternatives) |
| Ops | Docker Compose, GitHub Actions CI, DVC or dated snapshots, deploy on Render / Railway free tier |

Hardware: any 8 GB-RAM laptop runs the full pipeline (data < 1 GB). A GPU (or Google Colab) is only needed for optional NLP fine-tuning.

---

## 5. Repository layout

```
arth-drishti/
├── README.md
├── PRD.md
├── Makefile
├── pyproject.toml
├── docker-compose.yml            # postgres, redis, api, web, mlflow
├── .env.example                  # every variable, no real values
├── .gitignore                    # includes .env, data/raw, mlruns
├── .github/workflows/
│   ├── ci.yml                    # lint, type-check, tests, leakage test
│   └── secret-scan.yml           # gitleaks or trufflehog
│
├── config/
│   ├── sector_map.json           # PROVIDED: 15 sectors → budget lines, 116 stocks, NSDL FPI sector
│   ├── stocks.csv                # PROVIDED: same stock list as a flat table
│   ├── budget_events.csv         # PROVIDED: 22 full + 4 interim budgets, dates, flags
│   ├── ministry_aliases.csv      # renames: HRD→Education, Jal Shakti 2019, …
│   └── settings.yaml             # horizons, liquidity filter, cost assumptions
│
├── data/                         # large folders are git-ignored / DVC-tracked
│   ├── source_pdfs/              # YOUR budget PDFs and docs go here (PRS analyses etc.)
│   ├── raw/                      # untouched downloads, one folder per source
│   ├── csv/                      # clean CSVs, one per dataset (schemas in §8)
│   ├── interim/
│   ├── processed/                # feature tables, targets
│   └── snapshots/                # dated, immutable copies for reproducibility
│
├── scripts/collect/              # one collector script per dataset → writes data/csv/*.csv
│
├── src/bsp/                      # main Python package
│   ├── common/                   # db, logging, provenance, config loader
│   ├── ingest/                   # prices, benchmarks, fpi, macro, news
│   ├── parsers/                  # prs, expenditure_budget, cga, speech, llm_fallback
│   ├── quality/                  # pandera schemas, reconciliation checks
│   ├── features/                 # point-in-time feature builders
│   ├── events/                   # event study (CAR, t-stats)
│   ├── models/
│   │   ├── baselines.py
│   │   ├── tier1/                # LambdaRank, Bayesian hierarchical
│   │   ├── tier2/                # stock ranker, optional sequence embedding
│   │   ├── conformal.py
│   │   └── ensemble.py
│   ├── evaluation/               # walk-forward harness, metrics, backtest, ablations
│   ├── explain/                  # SHAP → three plain-English bullets
│   ├── simulator/                # what-if engine
│   ├── nlp/                      # speech tagging, talk-vs-money, order-win extractor
│   ├── live/                     # budget-day pipeline, sealing, broker feed, alerts
│   ├── copilot/                  # tools, Groq client, guardrails, number checker
│   └── api/                      # FastAPI app, routers, schemas
│
├── web/                          # React + Vite dashboard
├── console/                      # Streamlit analyst console
├── notebooks/                    # exploration only; nothing the report depends on
├── reports/                      # generated figures, tables, final report assets
├── ledger/                       # local copy of sealed-prediction hashes
└── tests/
    ├── fixtures/
    ├── test_parsers.py
    ├── test_reconciliation.py
    ├── test_features.py
    ├── test_leakage.py
    ├── test_api.py
    └── copilot_eval/             # 50 known-answer questions + 15 trick prompts
```

---

## 6. Setup

```bash
# 1. Clone and enter
git clone <repo-url> arth-drishti && cd arth-drishti

# 2. Python environment
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Environment variables
cp .env.example .env        # then fill in values; never commit .env

# 4. Services (Postgres, Redis, MLflow)
docker compose up -d postgres redis mlflow

# 5. Database schema
make db-migrate

# 6. Add your budget documents
cp ~/Downloads/budget-pdfs/*.pdf data/source_pdfs/   # PRS analyses, speeches, etc.

# 7. Collect everything into CSVs (run on a laptop with internet)
make parse-pdfs             # your PDFs → data/csv/budget_*.csv
make collect                # prices, indices, FPI, macro … → data/csv/*.csv

# 8. Load CSVs and build everything
make load && make features && make train && make backtest

# 9. Run the app
make api                    # FastAPI on :8000, docs at /docs
make web                    # dashboard on :5173
```

---

## 7. Configuration and secrets

`.env.example` (names only, no values):

```dotenv
DATABASE_URL=postgresql://user:pass@localhost:5432/bsp
REDIS_URL=redis://localhost:6379/0
MLFLOW_TRACKING_URI=http://localhost:5000

GROQ_API_KEY=
GROQ_MODEL=                 # a tool-calling model from console.groq.com
GROQ_BACKUP_MODEL=

BROKER=upstox               # or angelone
BROKER_API_KEY=
BROKER_API_SECRET=
BROKER_ACCESS_TOKEN=

LEDGER_REPO=                # public GitHub repo for sealed hashes
LEDGER_GITHUB_TOKEN=

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Keys are read only on the server. The browser never sees `GROQ_API_KEY` or broker credentials.

---

## 8. Data catalogue: what exists and what must be built

Full detail is in PRD §4. **Today the team has only budget PDFs and documents.** Everything else is built by collector scripts that write CSVs.

**Data status as of 23 Oct 2026** (details in `reports/data_gaps.md`)

| Done (real data, checked) | Still to collect |
| --- | --- |
| Budget tables from your 7 PRS PDFs + PRS 2025-26: ministries, schemes, subsidies, fiscal (`budget_*.csv`) | Budgets FY2005-06 to FY2016-17 (same Statement 3 method, newest year first) |
| Department-level expenditure with capex split, 10 budgets 2017-18 to 2026-27 (`budget_departments.csv`) | Prices, indices, macro, FPI: **scripts ready in `scripts/collect_market_data.py`, run on a laptop** |
| **Sector panel: 15 sectors x 10 budgets = 150 rows**, with surprise, credibility, capex share (`sector_budget_panel.csv`) | Fundamentals, order wins, speeches, news, CGA monthly (Phases 2, 5, 6) |

Checks passed: 395 of 395 department sums match PRS; 520 of 520 values printed in two editions identical; 25 of 25 random values found on their PDF page; the 2020-21 example file reproduced for all 10 sectors.

**How each dataset is obtained**

- **Your PDFs** — already in hand; the coding tool writes a parser that turns them into CSV.
- **Download PDFs** — more official PDFs to download (by script or by hand), then parse.
- **Script** — the coding tool writes a collector that downloads the data and saves a CSV. Run it on a laptop.
- **Manual** — the site has no usable API; download the file by hand into `data/raw/<source>/`, and the script converts it to CSV.

| # | Dataset | Source | Span | How | Output CSV | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| D1 | Ministry BE / RE / Actuals | PRS budget analyses | FY17-18 → FY26-27 | Your PDFs | `budget_ministries.csv` | 1 |
| D2 | Scheme allocations | PRS budget analyses | FY17-18 → FY26-27 | Your PDFs (+ download FY25-26 if missing) | `budget_schemes.csv` | 1 |
| D3 | Subsidies, receipts, deficits | PRS budget analyses | FY17-18 → FY26-27 | Your PDFs | `budget_fiscal.csv` | 1 |
| D4 | Full Demand for Grants, ~100 ministries, capex/revenue | indiabudget.gov.in Expenditure Budget | FY05-06 → FY26-27 | Download PDFs | `budget_demands.csv` | 1 |
| D5 | Older PRS analyses | PRS archive | FY05-06 → FY16-17 | Download PDFs | appends to `budget_ministries.csv` | 1 |
| D6 | Monthly fiscal execution | CGA monthly accounts | Monthly | Download PDFs / Manual | `cga_monthly.csv` | 6 |
| D7 | Daily stock prices (116 stocks) | Yahoo Finance via `yfinance`; NSE bhavcopy fallback | 2005 → today | Script | `prices_daily.csv` | 2 |
| D8 | Nifty 500 + official sector indices | Yahoo Finance; niftyindices.com | 2005 → today | Script + Manual | `index_daily.csv` | 2 |
| D9 | Stock universe rule (replaces the dropped Nifty 500 constituent history) | Derived from the D7 prices: listed on budget day and 60-day average traded value ≥ ₹5 cr | Per budget | Script | `reports/universe_filter.csv` | 3 |
| D10 | FPI flows by sector | NSDL fortnightly reports | 2018-09 → today (earlier pages blocked, not collected) | Script | `fpi_sector_fortnightly.csv` | 2 |
| D11 | Macro: repo, CPI, 10y G-sec, USD/INR, crude, India VIX | RBI DBIE, MoSPI, World Bank API, Yahoo | Monthly / daily | Script + Manual (RBI) | `macro.csv` | 2 |
| D12 | Company fundamentals | Screener.in export, annual reports, NSE shareholding | Annual / quarterly | Manual + Script | `fundamentals.csv` | 5 |
| D13 | Order wins | NSE/BSE corporate announcements, PIB, MoD releases | Event-level | Script (NLP) | `order_wins.csv` | 5 |
| D14 | Government procurement | GeM, CPPP | Event-level | Script (best-effort) | `procurement_awards.csv` | 12 |
| D15 | Budget speech + highlights text | indiabudget.gov.in | Per budget | Download PDFs | `speech_sentences.csv` | 6 |
| D16 | Budget-week news | GDELT 2.0 API, Google News RSS | Daily, ±30 days around each budget | Script | `budget_news.csv` | 6 |
| D17 | Live quotes | Broker WebSocket (Upstox / Angel One) | Tick-level | Script (needs trading account) | not stored as CSV; recorded replay in `data/raw/live/` | 12 |

**Files already provided** (in `config/`, no internet needed):

- `sector_map.json` and `stocks.csv` — 15 sectors, 116 NSE stocks (118 in the original kit; see `reports/symbol_drops.md`), the budget lines each sector follows, and its NSDL FPI sector. Symbols are a starting list: Phase 0 checks every one against Yahoo and fixes or drops any that fail.
- `budget_events.csv` — all 26 budget dates (22 full + 4 interim), FY2005-06 → FY2026-27, with interim and election-year flags.

**CSV schemas** (every CSV also has `source`, `source_url` and `fetched_at`; budget CSVs also have `source_doc` and `source_page`)

| CSV | Columns |
| --- | --- |
| `budget_ministries.csv` | `fiscal_year, ministry, canonical_ministry, stage (BE/RE/Actual), amount_cr, capex_cr, revenue_cr` |
| `budget_schemes.csv` | `fiscal_year, scheme, canonical_scheme, ministry, stage, amount_cr` |
| `budget_fiscal.csv` | `fiscal_year, item (e.g. fiscal_deficit, food_subsidy), stage, amount_cr` |
| `budget_demands.csv` | `fiscal_year, demand_no, ministry, department, stage, revenue_cr, capital_cr, total_cr` |
| `cga_monthly.csv` | `fiscal_year, month, ministry, actual_to_date_cr, pct_of_be` |
| `prices_daily.csv` | `symbol, date, open, high, low, close, adj_close, volume` |
| `index_daily.csv` | `index_name, date, close` |
| `fpi_sector_fortnightly.csv` | `period_end, nsdl_sector, equity_net_cr, debt_net_cr, equity_aum_cr` |
| `macro.csv` | `series, date, value, unit` |
| `fundamentals.csv` | `symbol, period_end, sales_cr, ebitda_cr, net_profit_cr, debt_cr, market_cap_cr, promoter_pledge_pct, order_book_cr` |
| `order_wins.csv` | `symbol, announced_on, order_value_cr, client, is_government, text` |
| `speech_sentences.csv` | `budget_id, sentence_no, page, text` |
| `budget_news.csv` | `budget_id, published_at, outlet, title, url` |

---

## 9. Core database tables

Every table that stores sourced values includes provenance columns: `source_doc`, `source_page`, `source_url`, `fetched_at`.

| Table | Key columns |
| --- | --- |
| `budget_events` | `budget_id`, `fiscal_year`, `presented_on`, `is_interim`, `is_election_year`, `regime_flags` |
| `budget_lines` | `fiscal_year`, `line_type` (ministry/scheme/subsidy), `line_name`, `canonical_name`, `stage` (BE/RE/Actual), `amount_cr`, `capex_cr`, `revenue_cr`, provenance |
| `sector_line_map` | `sector_id`, `canonical_name`, `weight`, `notes` |
| `stocks` | `symbol`, `sector_id`, `listing_date`, `delisting_date`, `yahoo_symbol` |
| `prices_daily` | `symbol`, `date`, `open`, `high`, `low`, `close`, `adj_close`, `volume`, `traded_value_cr` |
| `fpi_flows` | `nsdl_sector`, `period_end`, `equity_cr`, `debt_cr`, `aum_cr` |
| `macro` | `series`, `date`, `value` |
| `features_sector_year` | `sector_id`, `budget_id`, `feature_name`, `value`, `as_of_date` |
| `features_stock_year` | `symbol`, `budget_id`, `feature_name`, `value`, `as_of_date` |
| `targets` | `entity`, `budget_id`, `horizon`, `excess_return`, `target_complete` |
| `event_study` | `entity`, `budget_id`, `window`, `car`, `t_stat` |
| `predictions` | `model_version`, `entity`, `budget_id`, `expected_excess`, `p10`, `p90`, `p_beat`, `rank`, `top_reasons` |
| `sealed_ledger` | `budget_id`, `file_sha256`, `sealed_at`, `commit_url` |
| `fetch_log` | `job`, `started_at`, `finished_at`, `rows`, `status`, `error` |

---

## 10. Build phases, start to end

Each phase lists its **goal**, **tasks**, the PRD requirements it covers, and **exit criteria**. A phase is done only when every exit criterion passes. Priorities follow the PRD: **Must** = minimum for a passing demo, **Should** = makes it strong, **Could** = stretch.

### Phase 0 — Foundations and repo setup

**Goal:** an empty but correctly wired project.

> **Status: Phase 0 is built and verified, with one open item.** Ruff, mypy and pytest pass in CI, the secret scan blocks a fake key (`reports/secret_scan_check.md`), and both SQLite and a clean Postgres 15 migrate with `make db-migrate`. Open: the MLflow image could not be pulled from the cloud sandbox, so run `docker compose up -d` on a laptop to confirm all three services. The stock list is 116, not 118: see [`reports/symbol_drops.md`](./reports/symbol_drops.md). Other gaps are in [`reports/data_gaps.md`](./reports/data_gaps.md).

Tasks:
- [x] Create the repo layout in §5, `pyproject.toml`, and a `Makefile` with every target in §11 (stubs are fine).
- [ ] `docker-compose.yml` with Postgres 15, Redis and MLflow. *Still open: Postgres and Redis start healthy and migrate cleanly (`reports/` and task log); the MLflow image (ghcr.io) could not be pulled in the cloud sandbox, so verify `docker compose up` on a laptop.*
- [x] `.env.example`, `.gitignore` (`.env`, `data/raw/`, `mlruns/`, `*.pdf` under raw).
- [x] `src/bsp/common/`: config loader (reads `config/*.yaml|json|csv` and env), DB session, structured logging, a `Provenance` dataclass.
- [x] Database migrations (Alembic) for the tables in §9. *Five migrations create every §9 table except `index_constituents` (created in 004, dropped in 005 when the Nifty 500 constituent work was removed; 001-004 are unchanged) plus `index_daily`; verified on clean SQLite and Postgres 15 and in CI.*
- [x] GitHub Actions: ruff, mypy, pytest; a separate secret-scan workflow (gitleaks) that fails the build (FR-17). *CI green on PR #1; secret scan verified in `reports/secret_scan_check.md`.*
- [x] Put the team's budget PDFs and documents in `data/source_pdfs/` and write `data/source_pdfs/INVENTORY.csv` listing each file: `filename, document_type (PRS analysis / speech / highlights / other), fiscal_year, pages`.
- [x] Use the provided `config/sector_map.json`, `config/stocks.csv` and `config/budget_events.csv`.
- [x] `scripts/collect/validate_symbols.py`: try a short yfinance download for every stock in `stocks.csv`; write `reports/symbol_check.csv` (ok / failed / renamed). Fix or drop failures by hand. *(Run on a laptop.)* *116 of 116 symbols ok; see `reports/symbol_drops.md` for the 2 dropped from the original 118.*

Exit criteria:
- `docker compose up` and `make db-migrate` succeed on a clean machine.
- CI is green; committing a fake key is blocked by the secret scan.
- `sector_map.json` validates against a JSON schema (15 sectors, every stock has a sector and Yahoo symbol).
- `reports/symbol_check.csv` shows every remaining symbol downloads; the inventory lists which budget years the team's PDFs cover and which are missing.

---

### Phase 1 — Budget data: turn your PDFs into CSVs

**Goal:** a clean, provenance-tagged budget panel from FY2005-06 to FY2026-27, built from PDFs, saved as CSVs.

> **Status: Phase 1 pipeline is implemented and rebuildable.** D4 demand data covers FY2005-06 through FY2026-27, and the 15-sector panel has 330 year/sector rows (4 historical PSU-bank allocations remain unavailable in the source tables). PRS D1-D3 coverage starts at FY2019-20; FY2025-26 is a sourced web transcription. See [`reports/data_gaps.md`](./reports/data_gaps.md) for source coverage, validation results and unresolved gaps. Do not start Phase 2 until those gaps have been reviewed.

Tasks:
- [x] `parsers/prs.py` (pdfplumber): extract ministry, scheme and fiscal tables with source document/page metadata into the three PRS CSVs. Current source coverage is limited to FY2019-20–FY2026-27; see the gaps report. **(FR-2, FR-3, Must)**
- [x] Spot-check: 25 randomly selected PRS values are recorded in `reports/budget_spot_check.csv`; all 25 match the parsed value on the recorded PDF page.
- [x] `scripts/collect/download_budget_pdfs.py`: download the official D4 PDFs into `data/raw/budget_pdfs/` for FY2005-06 through FY2026-27.
- [ ] Download the missing PRS analysis PDFs (older years and FY2025-26); historical PRS sources have not yet been located and are listed in `reports/data_gaps.md`.
- [x] `parsers/expenditure_budget.py`: build `budget_demands.csv` from legacy Statement 2 PDFs and sourced Statement 3 transcriptions, preserving unavailable revenue/capital splits as null. Verified complete transcriptions are retained instead of being overwritten by partial PDF extraction.
- [ ] OCR fallback for scanned or unsupported D4 table layouts is not implemented; the current PDF parser misses some rows in recent layouts.
- [x] `config/ministry_aliases.csv` and canonicaliser: map documented ministry and department renames, including historical D4 labels.
- [x] `quality/reconcile.py`: ministry totals plus Other reconcile within 0.5% or fail loudly. A separate PRS subsidy-table inconsistency is recorded in the reconciliation report.
- [x] Cross-check PRS figures against Statement 3 where they overlap; match/difference status and notes are in `reports/statement3_vs_prs.csv`.
- [ ] `parsers/llm_fallback.py`: optional Groq fallback is not implemented. **(FR-5, Should)**
- [x] `make load` target is wired to load budget CSVs into `budget_lines`; the loader was run twice against the migrated SQLite schema to verify idempotence.

Exit criteria:
- Budget CSVs exist for every year the PDFs cover; missing years are listed in `reports/data_gaps.md`.
- Every parsed year reconciles within 0.5%.
- 25/25 spot-check values match their PDF pages.
- Every budget row has a non-null `source_doc` and `source_page`.
- Every budget line in `sector_map.json` resolves to a canonical name in every year it exists.

---

### Phase 2 — Market, flow and macro ingestion

> **Status: Phase 2 collectors and database loads run; three data gaps remain.** Prices (cleaned, with a documented decision for every >50% jump, three of them "unexplained, kept"), indices, macro, FPI and sector baskets are in `data/csv/` and load into Postgres/SQLite with `make load` (idempotent, verified by `scripts/verify_load.py`). A blocked or failed source keeps the previous CSV instead of overwriting it. Gaps (details and what to do in [`reports/data_gaps.md`](./reports/data_gaps.md)): FPI data starts 2018-09 (2017-01 to 2018-08 was not collected because NSDL blocked the sandbox and the Codespace, so earlier budgets have missing FPI features); the policy repo rate was not collected (no official table found; each MPC resolution on rbi.org.in states it); the 10-year G-sec yield only starts in 2011-12 (`INDIRLTLT01STM`, OECD via FRED); no Nifty Healthcare index cross-check. The Nifty 500 constituent history was dropped in favour of a listing-date plus liquidity universe rule; the Nifty 500 **index** prices stay as the benchmark. Open infrastructure item: `data/csv/prices_daily.csv` (93 MB) should move to Git LFS, which needs network access the sandbox lacks (steps in the gaps report).

**Goal:** collect daily prices, benchmarks, FPI flows and macro series as CSVs, then load them into Postgres.

All collectors live in `scripts/collect/`, write raw downloads to `data/raw/<source>/` and clean CSVs to `data/csv/` (schemas in §8), and are run with `make collect` **on a laptop** (these sites usually block cloud servers).

Tasks:
- [ ] `ingest/prices.py`: yfinance daily OHLCV for the 116 stocks from Jan 2005 → `prices_daily.csv`; fill `listing_date` in `stocks.csv` from the first trading day; NSE bhavcopy fallback for missing or renamed symbols (D7). **(FR-1, Must)** *Still open: NSE bhavcopy fallback is not built. Prices, flag decisions (`reports/price_flag_decisions.csv`) and `listing_date` for the 59 stocks that listed after 2004 are done; the other 57 were already trading when the download window opens.*
- [x] `ingest/benchmarks.py`: Nifty 500 and official sector indices; manual CSV loader for indices missing on Yahoo, e.g. Nifty India Defence (D8). *Manual loader reads `data/raw/indices/*.csv`; no Nifty Healthcare or Nifty India Defence file supplied yet (see `reports/data_gaps.md`).*
- ~~`ingest/constituents.py`: historical Nifty 500 constituents (D9)~~ *Removed by decision (2026-10-27): the point-in-time constituent history needed every index change since 2015 and only seven were available. The universe is now the listing-date plus liquidity rule in ground rule 1 (`features/universe.py`); the Nifty 500 index prices stay as the benchmark.*
- [ ] `ingest/fpi.py`: NSDL fortnightly sector-wise FPI (24 sectors) from 2018-09-15 (D10). *The collection start is `FPI_START = 2018-09-15` (the first period NSDL served us): 2017-01 to 2018-08 is not collected because NSDL blocked the sandbox and the Codespace, and the manual collection of those pages is dropped. Budgets whose FPI window is not fully covered have missing (NaN) FPI features, never 0 or filled; coverage per budget is in `reports/fpi_coverage.csv`. 120 fortnights after 2018-09 are also missing; re-run `python -m bsp.ingest.fpi` from a network NSDL accepts, and move `FPI_START` earlier only if the old pages ever become reachable.*
- [x] `ingest/macro.py`: World Bank API and Yahoo series; manual loader for RBI DBIE downloads (D11). *Also FRED, including the 10-year G-sec yield from `INDIRLTLT01STM` (starts 2011-12, manual-file fallback, tested). The policy repo rate is not collected (no official table found; each MPC resolution on rbi.org.in states it); `data/raw/rbi/repo_rate.csv` would be loaded if built by hand from the resolutions.*
- [x] Every job is idempotent (re-running overwrites the CSV and upserts on natural keys) and writes to `fetch_log`. *`reports/idempotence_check.md`; FPI is only trivially tested here because NSDL is blocked.*
- [x] `make load` loads every CSV in `data/csv/` into Postgres. *`make load` migrates, then loads budget lines, prices, indices, macro, FPI flows and the Phase 3 tables as idempotent upserts on natural keys with a `fetch_log` row per table (`src/bsp/ingest/load.py`). Run twice on clean SQLite and clean Postgres: row counts and checksums match the CSVs (`scripts/verify_load.py`); the Postgres CI job repeats this. Stock and sector-basket CSVs have no section 9 table and are not loaded.*
- [x] `quality/schemas.py` (pandera): no future dates, no duplicate symbol-days, flag single-day price jumps > 50%, positive prices. *Wired into the collectors and run on every CSV in `tests/test_quality_schemas.py`; >50% jumps are decided in `reports/price_flag_decisions.csv`.*
- [x] APScheduler job definitions for daily prices and fortnightly FPI. *`src/bsp/ingest/scheduler.py`, tested in `tests/test_scheduler.py`.*
- [x] Build **self-built sector baskets**: equal-weight index of mapped stocks, each stock entering only from its listing date. Keep official indices only as a cross-check. *`reports/sector_basket_report.csv`: all start 2004-12-02 but several are thin (defence has 2 stocks until 2017, railways 1 until 2018, housing 1 until 2007).*

Exit criteria:
- Every Phase 2 CSV in §8 exists in `data/csv/` with the documented columns.
- Re-running every ingestion job twice leaves row counts unchanged.
- All pandera checks pass, or the flagged rows are listed in a report with a manual decision.
- Sector baskets exist for all 15 sectors with a documented start date each; correlation with the official index is reported where one exists.

---

### Phase 3 — Feature store, targets and event study

**Goal:** point-in-time features, non-overlapping targets and the event-study tables.

> **Status: Phase 3 is built and tested; its inputs still have gaps.** 330 sector-year and 1,882 stock-year rows (115 of the 116 symbols; universe rule below), 11,416 targets (133 incomplete, FY2026-27) and 14,210 event-study rows; the leakage test passes and fails when a leak is injected (future date, same-year Actual, not-yet-listed stock, below-liquidity stock); the Defence/HAL hand-check matches. Features that depend on Phase 1/2 gaps are sparse (scheme push, fiscal stance, FPI). The stock universe is the listing-date plus liquidity rule from ground rule 1; **survivorship bias is reduced but not removed** (today's 116 symbols, no delisted names, no index-membership check), see [`reports/data_gaps.md`](./reports/data_gaps.md) and `reports/universe_filter.csv`.

Tasks:
- [x] Build `features/` and `events/` from scratch (there is no existing dataset script), with unit tests for every feature function.
- [x] **Sector-year features** (each with `as_of_date` ≤ budget day): allocation level and growth, `alloc_vs_prev_re_pct` (surprise), execution credibility (3-year), capex ratio, scheme-level push, fiscal-stance features (deficit, subsidies), pre-budget momentum (1/3/6/12 months), volatility, FPI flow before the budget, macro controls, regime flags (interim, election year, COVID, high VIX). **(FR-6, Must; F2, F10)** *Coverage is limited by upstream gaps: scheme push 15%, fiscal-stance 41%, FPI 21% of rows.*
- [x] **Stock-year features:** momentum, volatility, liquidity (average daily traded value), beta, size; a stock gets a row only if it is listed on or before the budget date and its average daily traded value over the prior 60 trading days is at least ₹5 cr (`features/universe.py`; counts per budget in `reports/universe_filter.csv`). *Index membership is not checked, and delisted stocks are missing (survivorship bias remains).*
- [x] **Targets:** forward 12-month excess return over Nifty 500 (day after budget → next budget, non-overlapping); secondary horizons to 31 March, +5 and +30 days. Set `target_complete = False` for unresolved rows (FY2026-27 until Feb 2027).
- [x] **Event study:** market model on days −250 to −31; CAR and t-stats for windows [−5,−1], 0, [0,+5], [0,+30], [0,+90] for every sector and stock around every budget. **(FR-7, Must)** *Hand-check in `reports/event_study_spotcheck.md` (Defence and HAL, FY2021-22) matches; it also caught and fixed a one-day error in the estimation window.*
- [x] `tests/test_leakage.py`: fails if any feature's `as_of_date` ≥ its prediction date, if any same-year Actual is used, if a stock that is not yet listed appears, or if a stock below the liquidity threshold appears. *Each case has an injected-leak test.*

Exit criteria:
- ~300 sector-year rows and ~2,000 stock-year rows built.
- Leakage test passes, and fails when a deliberately leaked feature is injected.
- Event-study tables are populated and spot-checked by hand for one sector and one stock.

---

### Phase 4 — Baselines and the walk-forward harness

**Goal:** the evaluation machinery and the bars every model must clear, before any "real" model exists.

> **Status: Phase 4 is built at sector level only; its exit criteria pass.** `make backtest` rebuilds `reports/baselines.md` (and the CSVs beside it) with fixed seeds: two runs give byte-identical files, and every run is logged to MLflow. **Null result:** no baseline reaches the README target of mean IC > 0.10 (best: last year's winners, 0.065), and neither the budget-surprise baseline nor ridge beats the equal-weight Sharpe. IT Services is the control sector and is reported separately (no leakage alarm). Stock-level evaluation is not built, because the stock universe uses listing-date plus liquidity filters only and survivorship bias is not removed (see `reports/data_gaps.md`). The FY2024-25 and FY2025-26 hold-out has not been touched.

Tasks:
- [x] `evaluation/walk_forward.py`: expanding window; train on budgets ≤ t−1, predict t, for every t from FY2012-13; hyperparameter tuning hook runs **inside** each fold. Lock FY2024-25 and FY2025-26 as hold-out (raise an error if accessed before Phase 9 is unlocked by a config flag). *Sector level. Expanding window over the 12 full budgets FY2012-13 to FY2023-24; a training row needs fiscal year < t, `label_end <= day 0` of t and `target_complete`; the ridge tuning hook sees training rows only. The hold-out is locked by fiscal year in `config/evaluation.json` (FY2024-25-I is locked with FY2024-25) and raises `HoldoutLockedError`; tests cover the lock, the unlock path and "never trains on year t or later".*
- [x] `models/baselines.py`: equal-weight all sectors; last year's winners (momentum); "biggest allocation increase wins"; ridge regression. *Sector baselines: equal weight, last year's winners (12m momentum), biggest allocation increase (`alloc_vs_prev_re_pct`), ridge.*
- [x] `evaluation/metrics.py`: Spearman rank IC, top-3 hit rate, MAE, directional accuracy; Precision@5 and NDCG@10; interval coverage and width. *Each metric is unit-tested against hand-computed values.*
- [x] `evaluation/backtest.py`: top-k sector and stock portfolios, 0.2% round-trip costs; CAGR, Sharpe, maximum drawdown, turnover. **(FR-11, Must)** *Sector portfolios only: stock portfolios are not built, because the stock universe uses listing-date plus liquidity filters only and survivorship bias is not removed (see `reports/data_gaps.md`). Top-3 of the 14 budget-sensitive sectors, 0.2% round trip, benchmark charged identically; window returns reproduce the published 12m targets (tested). IT Services (control) is reported separately.*
- [x] MLflow logging for every run (params, per-year metrics, artifacts). *`bsp/evaluation/tracking.py` uses the MLflow server if it answers a health check, else a local file store under `mlruns/` (git-ignored); the run prints which one it used.*

Exit criteria:
- Baseline results per year, logged to MLflow and written to `reports/baselines.md`.
- Backtest numbers for baselines are reproducible from `make backtest` with fixed seeds.

---

### Phase 5 — Tier-1 and Tier-2 models

**Goal:** the sector ranker and the stock ranker.

Tasks:
- [ ] **Tier 1:** LightGBM/XGBoost with LambdaRank objective, shallow trees, Optuna tuning inside the walk-forward loop. Output per sector: expected excess return, rank, P(beat Nifty 500). **(FR-8, Must)**
- [ ] **Tier 1:** Bayesian hierarchical regression in PyMC, sector-specific slopes on surprise, partially pooled; produces credible intervals.
- [ ] Data for Tier 2: company fundamentals (D12: sales, EBITDA, debt, order book, promoter pledge) and the order-win extractor (D13 / F8: order value, client, government flag → `OrderInflow / MarketCap`).
- [ ] **Tier 2:** LightGBM ranker within each sector on stock features + Tier-1 output; liquidity filter of average daily traded value ≥ ₹5 cr. **(FR-9, Must)**
- [ ] *(Could)* LSTM or temporal CNN on 250-day pre-budget price paths, used as an embedding into the ranker. Keep it only if the ablation shows a gain.
- [ ] Stacked ensemble of the above.
- [ ] Model registry in MLflow: every model version kept so old predictions can be reproduced. **(FR-14, Should)**

Exit criteria:
- Per-year walk-forward results for every model vs every baseline in `reports/models.md`.
- IT Services (control) shows no strong budget effect; if it does, investigate for leakage before moving on.

---

### Phase 6 — Text, news and execution signals

**Goal:** the NLP and execution features that the ablation needs.

Tasks:
- [ ] Speech and highlights corpus (D15): finish the scraper for 2004 → 2026, store text with year and page.
- [ ] **F6 "talk vs money":** tag every speech sentence to a sector (zero-shot or FinBERT), score emphasis and sentiment, detect new schemes; divergence = high talk, low money (or the reverse).
- [ ] Budget-week news (D16) from GDELT 2.0 and Google News RSS; build a pre-budget expectation score.
- [ ] **F4 Budget Surprise Index:** surprise two ways — new BE vs last RE, and speech emphasis vs pre-budget news consensus.
- [ ] CGA monthly accounts (D6) parser for the monthly execution line in the Promise-vs-Reality tracker.
- [ ] Add the new features to the feature store (point-in-time) and re-run Phase 5 models.

Exit criteria:
- NLP features exist for every budget year with text; leakage test still passes.
- Updated model results logged; the change vs Phase 5 is recorded either way.

---

### Phase 7 — Explainability and calibrated uncertainty

**Goal:** every prediction carries its reasons and an honest interval.

Tasks:
- [ ] SHAP values for every Tier-1 and Tier-2 prediction. **(FR-10, Must)**
- [ ] `explain/reasons.py`: turn top SHAP drivers into exactly three plain-English bullets with the underlying numbers and source references.
- [ ] Conformal prediction wrapper (MAPIE) for 80% intervals on every forecast; coverage report by year and regime. **(F9)**
- [ ] Store `p10`, `p90`, `p_beat`, `top_reasons` in `predictions`.

Exit criteria:
- 100% of predictions have three reasons and an interval.
- Walk-forward 80% interval coverage is reported (target 75–85%).

---

### Phase 8 — Backtest lab, ablations and statistical honesty

**Goal:** the evidence the panel will ask for.

Tasks:
- [ ] **F12 Backtest lab:** equity curve of "follow the model since FY2012-13" vs Nifty 500 and baselines, with costs, drawdown and turnover.
- [ ] **Ablations:** remove each feature family in turn (budget money, surprise, execution credibility, speech NLP, FPI flows, momentum) and measure the drop in IC.
- [ ] Bootstrap confidence intervals or t-stats for IC.
- [ ] Benjamini–Hochberg correction when claiming significant sector event effects across 15 sectors.
- [ ] **F11 Causal check:** difference-in-differences, large-surprise sectors vs matched sectors, before and after the budget.
- [ ] Error reports split by regime (F10): election, interim, COVID, high VIX.

Exit criteria:
- `reports/evidence.md` answers: *does the budget data add anything beyond price momentum?* — with numbers, either way.

---

### Phase 9 — Final hold-out evaluation

**Goal:** a single, honest look at FY2024-25 and FY2025-26.

Tasks:
- [ ] Freeze feature definitions, model configs and seeds; tag the commit.
- [ ] Unlock the hold-out flag and run once. No re-tuning afterwards.
- [ ] Record results in `reports/holdout.md`, including any null result and its explanation.

Exit criteria:
- Hold-out results exist from exactly one tagged run.

---

### Phase 10 — API and dashboard

**Goal:** the product surface.

Tasks:
- [ ] **FastAPI** (`src/bsp/api/`): `/budgets`, `/budgets/{id}/lines`, `/sectors`, `/sectors/{id}/forecast`, `/sectors/{id}/event-study`, `/stocks/{symbol}`, `/backtest`, `/simulate`, `/credibility`, `/ledger`, `/sources/{id}`; OpenAPI docs; Redis cache for forecasts (p95 < 500 ms). **(FR-12, Must)**
- [ ] **What-if engine** (`simulator/`): takes allocation changes, rebuilds affected features, re-scores Tier 1 with SHAP; presets that replay real history. **(F3)**
- [ ] **React dashboard**, eight screens (PRD §10): **(FR-13, Must)**
  1. Budget overview — ministry treemap, BE vs RE vs Actual, capex vs revenue
  2. Sector heat-map — 15 sectors by expected excess return, whiskers, P(beat)
  3. Sector deep-dive — SHAP waterfall, surprise and credibility cards, CAR curve, FPI strip
  4. Stock watchlist — ranked table, interval, liquidity, order-win flag, risk filter
  5. What-if simulator — sliders, live re-ranked heat-map, diff vs actual
  6. Promise vs reality — credibility league table, CGA monthly execution line
  7. Backtest and evidence — equity curve, IC by year, ablation bars, sealed ledger
  8. Budget Copilot — chat page; chat button on every other screen
- [ ] UX rules: every number clickable to its source page; one-line takeaway per chart; phone-width layout; dark mode; footer "Research tool, not investment advice."
- [ ] *(Should)* F14 FPI flow radar overlay; F5 interactive event-study explorer.
- [ ] Streamlit analyst console for internal checks.

Exit criteria:
- All 8 screens render real data on desktop and phone width.
- Clicking any number opens its source PDF page or dataset row.
- API tests pass; p95 latency for cached forecasts < 500 ms.

---

### Phase 11 — Budget Copilot (chatbot)

**Goal:** a tool-calling chatbot that answers only from the project's data. Spec in PRD §8. **(FR-15, Must; F13)**

Tasks:
- [ ] Retrieval index over budget PDFs, speeches and PRS analyses (sentence-transformers), returning passage + document + page.
- [ ] Read-only tools: `search_documents`, `query_budget`, `get_sector_forecast`, `get_stock_ranking`, `explain_prediction`, `run_what_if`, `get_event_study`, `get_live_quotes`.
- [ ] Groq client with tool calling; primary and backup model from env; answer cache in Redis. Single-turn only, no conversation memory.
- [ ] Answer flow: question + tool definitions → model picks tools → backend runs them → model writes answer from tool results only → reply with text, citation chips and at most one chart/table (model picks chart type; frontend draws it).
- [ ] **Guardrails:** no buy/sell or personal advice (short disclaimer on market answers); "I don't know" when tools lack the answer; document text treated as data, never instructions; off-topic redirect.
- [ ] **Number checker:** every number in a reply must appear in a tool result or cited chunk, otherwise regenerate (then fall back to a safe "couldn't verify" answer).
- [ ] Evaluation set in `tests/copilot_eval/`: 50 known-answer questions with pages, 15 advice or injection trick prompts.

Exit criteria:
- 100% of numbers traceable; ≥ 95% correct citations; every trick prompt refused.
- The chatbot works with the backup model when the primary is disabled.

---

### Phase 12 — Budget-Day Live Mode, live feed and alerts

**Goal:** the end-to-end live run. **(F1, FR-16, F15)**

Tasks:
- [ ] `live/pipeline.py`: one command takes a new budget PDF (upload or URL) → parse (FR-3) → reconcile (FR-4) → features → Tier 1 + Tier 2 → explain + calibrate → publish. Target: PDF to dashboard < 3 minutes.
- [ ] **Sealing:** write the predictions file, compute SHA-256, commit the hash and timestamp to the public ledger repo, store in `sealed_ledger`. Dashboard banner shows "Forecast sealed at HH:MM, hash 3f2a…".
- [ ] **Seal the FY2026-27 forecast** from the frozen model and show how it is tracking until the target resolves in Feb 2027.
- [ ] **Live feed:** broker WebSocket client for ~120 stocks → live sector-basket moves → FastAPI WebSocket to the browser and Copilot's `get_live_quotes`; auto-reconnect; fall back to delayed quotes when the market is closed or the feed drops; recorded replay of a past budget day as a demo backup. **(FR-16, Should)**
- [ ] Budget-Day banner state across all screens with parse progress and a live ticker next to the forecast.
- [ ] *(Should)* F15 Telegram/email digest when a watchlist sector's surprise crosses a threshold.
- [ ] One-command retrain when a new budget lands. **(FR-14)**
- [ ] *(Could)* F7 money-to-company knowledge graph from order wins (D13) and procurement awards (D14 GeM/CPPP), with a budget-exposure score per company.

Exit criteria:
- A full dry run on a past budget PDF finishes in < 3 minutes and produces a sealed hash visible on GitHub.
- Live ticker works in market hours and falls back cleanly when disconnected.

---

### Phase 13 — Hardening, deployment and documentation

**Goal:** a stable, reproducible, deployed system.

Tasks:
- [ ] `make data && make train && make backtest` from raw files on a clean machine rebuilds every number in the report.
- [ ] Data versioning with DVC or dated snapshots in `data/snapshots/`.
- [ ] Deploy API + web on Render/Railway free tier; Postgres on Supabase; secrets set in the host's environment.
- [ ] Graceful degradation: the model runs when a feature family is missing (e.g. a scraper broke) and the UI says so.
- [ ] Final report assets in `reports/`: dataset documentation, methods, per-year results, ablations, hold-out, limitations.
- [ ] Demo safety: pre-warm the Copilot cache with common questions; test the backup model; keep the recorded replay ready.

Exit criteria:
- Fresh-clone reproduction succeeds.
- Deployed URL works on phone and laptop.

---

### Phase 14 — Budget Day and the viva

**Goal:** the live demo and the defence.

Tasks:
- [ ] Full dress rehearsal on a past budget at least one week before 1 Feb 2027.
- [ ] **Budget Day, FY2027-28 (expected 1 Feb 2027):** run Live Mode, seal forecasts, stream the live ticker.
- [ ] **FY2026-27 resolution (Feb 2027):** compare the sealed FY2026-27 forecasts with realised returns and publish the result, good or bad.
- [ ] Prepare viva answers for: self-built baskets vs official indices, surprise vs level, leakage controls, the control sector, the null-result plan, and the stated limitations (PRD §12).

Exit criteria:
- Sealed hash for FY2027-28 is public with a timestamp before market close on budget day.
- Final report includes the FY2026-27 out-of-sample outcome.

---

## 11. Make targets

| Target | Does |
| --- | --- |
| `make setup` | Install dependencies, create `.env` from example if missing |
| `make db-migrate` | Apply database migrations |
| `make parse-pdfs` | Parse budget PDFs in `data/source_pdfs/` and `data/raw/budget_pdfs/` → budget CSVs |
| `make collect` | Run every collector in `scripts/collect/` → `data/csv/*.csv` (laptop, needs internet) |
| `make load` | Load all CSVs into Postgres, then run quality checks |
| `make data` | `parse-pdfs` + `collect` + `load` |
| `make features` | Build point-in-time features, targets and event study |
| `make train` | Walk-forward training of baselines and models, logged to MLflow |
| `make backtest` | Portfolio backtests, ablations, reports |
| `make holdout` | One-time hold-out evaluation (requires unlock flag) |
| `make test` | Unit tests, leakage test, API tests |
| `make copilot-eval` | Run the 65-prompt chatbot evaluation |
| `make api` / `make web` / `make console` | Run backend, dashboard, analyst console |
| `make live PDF=<path or url>` | Budget-Day pipeline: parse → forecast → seal → publish |
| `make retrain` | Retrain all models after a new budget lands |

---

## 12. Success metrics

All measured out-of-sample with walk-forward validation, never on training years.

| Goal | Metric | Target |
| --- | --- | --- |
| Rank sectors better than chance | Spearman rank IC (predicted vs realised 12-month excess return) | Mean IC > 0.10 across test years |
| Beat naive strategies | Top-3-sector basket Sharpe vs Nifty 500, equal-weight, last year's winners | Higher than all three |
| Pick stocks within a sector | Precision@5 (beats sector median) | > 0.55 |
| Honest uncertainty | 80% interval coverage | 75–85% |
| Budget-day speed | PDF upload → full dashboard | < 3 minutes |
| Explainability | Predictions with top drivers | 100% |
| Copilot accuracy | Numbers traceable / correct citations / trick prompts refused | 100% / ≥ 95% / 100% |

---

## 13. Testing strategy

- **Unit tests** for every parser and feature function, using small fixtures in `tests/fixtures/`.
- **Reconciliation tests** (FR-4) on every parsed budget year.
- **Leakage test** that fails if any feature date ≥ its prediction date; verified by an injected-leak test case.
- **Data-quality checks** (pandera) in `make data`: totals reconcile, no future dates, no duplicate symbol-days, price jumps > 50% flagged.
- **API tests** with FastAPI's test client against a seeded test database.
- **Copilot evaluation**: 50 known-answer questions + 15 trick prompts, run in CI on a schedule (not on every commit, to save API quota).
- **CI secret scan** on every push.

---

## 14. Timeline

Suggested schedule from today (23 Oct 2026) to Budget Day. Adjust to the team's actual deadlines.

| Weeks | Dates (approx.) | Phases |
| --- | --- | --- |
| 1 | 23 Oct – 1 Nov | Phase 0 |
| 2–3 | 2 – 15 Nov | Phases 1 and 2 in parallel: PDF parsing and data collection (the biggest job, since nothing exists yet) |
| 4 | 16 – 22 Nov | Phase 3 |
| 5 | 23 – 29 Nov | Phase 4 |
| 6–7 | 30 Nov – 13 Dec | Phases 5 and 6 |
| 8 | 14 – 20 Dec | Phases 7 and 8 |
| 9 | 21 – 27 Dec | Phase 9, start Phase 10 |
| 10–11 | 28 Dec – 10 Jan | Phases 10 and 11 |
| 12 | 11 – 17 Jan | Phase 12 |
| 13 | 18 – 24 Jan | Phase 13, dress rehearsal |
| 14 | 25 Jan – 1 Feb | Buffer; **Budget Day 1 Feb 2027** (Phase 14) |
| After | Feb 2027 | FY2026-27 resolution, final report, viva |

The minimum passing demo is all **Must** items: Phases 0–5, 7, 10 (API + 8 screens), 11, and the parse-and-seal part of Phase 12. If time runs short, cut **Could** items first (F7 knowledge graph, LSTM embedding, D14 procurement), then **Should** items (live feed, alerts, LLM parser fallback).

---

## 15. How to use this README with an AI coding tool

1. **Give the tool both files.** Put `PRD.md` and this `README.md` in the repo root so the agent can read them.
2. **One phase per session.** Ask for a single phase, e.g. *"Implement Phase 1 tasks 1–3 from README.md. Follow the ground rules in §3. Stop when the exit criteria pass."*
3. **Point to the exit criteria.** Ask the tool to run the tests that prove each exit criterion and show the output before calling a phase done.
4. **Keep the rules in front of it.** If your tool supports a project-instructions file (e.g. `CLAUDE.md`, `AGENTS.md`, `.cursorrules`), copy §3 into it so every session sees the ground rules.
5. **Review data and modelling code yourself.** Leakage and look-ahead bugs pass tests silently; read every feature builder and the walk-forward split by hand.
6. **Never paste real API keys into a prompt.** Give the tool `.env.example` only.
7. **Commit after each phase** with the phase number in the message, and tag phase milestones.

---

## 16. Risks and limitations

| Risk | Mitigation |
| --- | --- |
| Data sites block scripts (Yahoo, NSE, NSDL) | Run collectors on a laptop; manual download into `data/raw/`; cache every raw file |
| FPI history is short and gappy (NSDL blocked 2017-01 to 2018-08 and 120 later fortnights) | FPI is "2018-09 to today"; a budget whose two-fortnight window is not fully covered has missing FPI features (never 0, never filled). Only FY2020-21 and FY2024-25 of the 22 modelled budgets have complete windows (`reports/fpi_coverage.csv`), so the Phase 8 FPI ablation is low-powered; read it as weak evidence either way |
| Small sample (~20 budgets) | Pooled hierarchical models, few features, walk-forward, per-year results, ablations |
| Look-ahead bias | Listing-date and liquidity universe rule measured before the budget, leakage test, sealed forecasts |
| **Survivorship bias (not fully removed)** | The 116 stocks come from today's symbols, so delisted names are missing, and index membership on budget day is not checked. The liquidity rule drops illiquid names the same way every year, which limits but does not remove the bias. Stated in `reports/data_gaps.md`; read all stock-level results with it in mind |
| Scanned or inconsistent old PDFs | Expenditure Budget statements (D4), OCR fallback, reconciliation check |
| Ministry renames and restructuring | Alias table, documented mappings |
| Yahoo symbol changes and delistings | Fetch log, manual fixes, NSE bhavcopy fallback |
| Scrapers break | Cached snapshots, graceful degradation |
| Election, interim and COVID years | Regime flags, error reports by regime |
| Users read output as advice | Persistent disclaimer, Copilot refuses buy/sell requests |
| Chatbot hallucinates a number | Numbers only from tool results; post-check on every reply |
| Groq rate limits or outage | Answer cache, backup model |
| Broker feed drops or terms change | Auto-reconnect, delayed-quote fallback, recorded replay |

**Stated limitations:** budget allocations are one driver among many (earnings, global rates and flows dominate year-to-year returns), and the ministry-to-stock mapping is a documented judgement call.

---

## 17. References

Literature and data sources are listed in PRD §13. Key data sources:

- [PRS Legislative Research — Union Budget analyses](https://prsindia.org/budgets/parliament)
- [Union Budget portal](https://www.indiabudget.gov.in)
- [CGA — Monthly Accounts](https://cga.gov.in/Page/Monthly-Accounts-Review.aspx)
- [NSDL — Fortnightly sector-wise FPI](https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_July312024.html)
- [Nifty Indices](https://www.niftyindices.com)
- [RBI DBIE](https://data.rbi.org.in), [GeM](https://gem.gov.in), [CPPP](https://eprocure.gov.in)

---

*Research tool, not investment advice.*
