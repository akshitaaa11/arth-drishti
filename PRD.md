# PRD — Budget-Based Sector Growth and Stock Return Prediction

Oct 23, 2026 · @akshita

## 1. Summary

The product is an explainable, backtested system. It reads each Union Budget the day it is presented, scores 15 budget-sensitive sectors and about 120 NSE stocks, and shows which ones history says should outperform the Nifty 500 over the next 12 months, with calibrated confidence ranges.

**What changes from the submitted synopsis.** The synopsis version trained on synthetic data and a word-count "budget score". This version trains only on real data:

- **Budget money.** Ministry, scheme and subsidy allocations at three stages each: Budget Estimate (BE), Revised Estimate (RE) and Actuals. FY2017-18 to FY2026-27 is already extracted, with source page numbers; older years are extended back to FY2005-06.
- **Market prices.** Daily prices for sector baskets and stocks, 2005 to today.
- **Money flows and macro.** Fortnightly foreign investor (FPI) flows by sector, plus macro series.
- **Budget text.** The budget speech and highlights documents, for NLP features.

**The research question, stated so it can be tested.** Does the *surprise* in a sector's allocation predict its excess return after the budget? Surprise means the new BE compared with last year's revised run-rate, not the headline rupee number. How does that compare with what the market already priced in on budget day?

**Headline deliverables**

1. A real, versioned dataset, documented in this PRD. This is a contribution in itself, because no clean public panel links Indian budget lines to listed companies.
2. A two-tier model: sector ranking, then stock ranking. It is evaluated with walk-forward backtests against simple baselines.
3. A live dashboard with a Budget-Day mode, a what-if simulator, plain-language explanations and a full Budget Copilot chatbot.

Current status: real budget panels and the collection scripts are in the team's data kit (`budget_data_kit.zip`). Market and flow data is fetched by running the kit's scripts on a laptop.

## 2. Problem, users and goals

Retail investors react to budget headlines on budget day. Three things they read about the budget are often wrong:

- **Headline totals are misleading.** A ministry's BE often differs from what it actually spends, by tens of percent. In 2025-26, PMAY-Urban had a ₹25,794 cr BE and a ₹7,900 cr RE. Bharatnet's RE was 25% of its BE.
- **The real signal is the change against the latest run-rate.** Last year's BE is the wrong comparison point.
- **Prices often move before the speech.** Pre-budget expectations can mean the news is already priced in.

No tool today connects budget line items to the listed companies that receive that money, and then checks whether that link ever paid off.

**Users**

| User | Need | What they get |
| --- | --- | --- |
| Retail investor | "Which sectors does this budget really favour?" | Sector heat-map, watchlist, plain-language reasons |
| Finance student or analyst | Evidence, not opinion | Event studies, backtests, downloadable dataset |
| Policy researcher or journalist | Did promised spending happen? | Budget-promise vs actual-spend tracker |
| Project panel | A rigorous, honest ML system | Walk-forward evaluation, baselines, ablations, live demo |

**Goals and success metrics.** Every metric is measured out-of-sample with walk-forward validation, never on the training years.

| Goal | Metric | Target |
| --- | --- | --- |
| Rank sectors better than chance | Spearman rank IC: predicted vs realised 12-month excess return | Mean IC > 0.10 across test years |
| Beat naive strategies | Top-3-sector basket vs Nifty 500, equal-weight all sectors, and "last year's winners" | Higher Sharpe ratio than all three baselines |
| Pick stocks within a sector | Precision@5 (beats sector median) | > 0.55 |
| Honest uncertainty | 80% prediction-interval coverage | 75–85% |
| Budget-day speed | Time from PDF upload to full dashboard | < 3 minutes |
| Explainability | Every prediction carries its top drivers | 100% of predictions |

If the models do *not* beat the baselines, that is a valid result, and it is still reported clearly. Panels respect a team that shows the null result and explains it more than one that hides it.

## 3. Scope

The scope grows from 8 to 15 sectors. Each one is tied to the ministry or scheme lines that fund it, so every prediction traces back to real rupees. IT Services is kept as a deliberately weakly linked *control* sector: if the model "finds" a strong budget effect there, something is leaking.

| Sector | Budget lines it follows | Example NSE stocks | FPI sector (NSDL) |
| --- | --- | --- | --- |
| Defence & Aerospace | Ministry of Defence (incl. capital outlay) | HAL, BEL, BDL, Mazagon Dock, Cochin Shipyard | Capital Goods |
| Roads & Construction | Road Transport & Highways, PMGSY | L&T, IRB, KNR, PNC Infratech, UltraTech | Construction |
| Railways | Ministry of Railways | RVNL, IRCON, IRFC, RailTel, Titagarh | Capital Goods |
| Housing & Real Estate | Housing & Urban Affairs, PMAY-U/G, AMRUT | DLF, Godrej Properties, NBCC, HUDCO | Realty |
| Healthcare & Pharma | Health & Family Welfare, NHM, Biopharma SHAKTI | Sun Pharma, Cipla, Apollo Hospitals | Healthcare |
| Agriculture & Agri-inputs | Agriculture & Farmers' Welfare, PM-KISAN, PMFBY | UPL, PI Industries, Dhanuka, M&M | Chemicals |
| Fertilisers | Chemicals & Fertilisers, fertiliser subsidy | Chambal, Coromandel, RCF, NFL | Chemicals |
| FMCG & Food | Consumer Affairs, Food & PD, food subsidy | HUL, ITC, Britannia, KRBL | FMCG |
| Telecom & Digital Infra | Communications, Bharatnet | Bharti Airtel, HFCL, Tejas, ITI | Telecommunication |
| Rural Consumption & Credit | Rural Development, MGNREGS / VB-G RAM G | Hero MotoCorp, Emami, CreditAccess | Auto, Financial Services |
| Water & Pipes | Jal Shakti, Jal Jeevan Mission | VA Tech Wabag, Jindal Saw, Welspun Corp | Capital Goods |
| Education | Education, Samagra Shiksha, PM POSHAN | Navneet, Aptech, NIIT | Consumer Services |
| Power & Renewables | Power, MNRE, PM Surya Ghar, RDSS | NTPC, Power Grid, Tata Power, IREDA | Power |
| IT Services (control) | MeitY, RDI scheme | TCS, Infosys, HCLTech | Information Technology |
| PSU Banks & Infra Finance | Financial Services dept, credit guarantees | SBI, Bank of Baroda, PFC, REC | Financial Services |

The full list of about 120 stocks is in `config/sector_map.json`.

**Time span.** Budget speeches run from FY2005-06 to FY2026-27: 22 full budgets plus 4 interim budgets, all listed in `config/budget_events.csv`. Prices are daily from Jan 2005. The FY2026-27 budget (1 Feb 2026, a Sunday trading session) is the live out-of-sample year. Its 12-month outcome resolves in Feb 2027, so the team can show predictions made *before* the result is known.

**Prediction horizons.** The primary horizon is the forward 12-month excess return over the Nifty 500, from the day after the budget to the next budget. Secondary horizons are

- the excess return to 31 March (end of the financial year), and
- the 5-day and 30-day reaction after the budget.

**Out of scope.** Intraday trading signals, derivatives, buy or sell advice to individuals, state budgets (listed as future work), and political forecasting.

## 4. Data catalogue

The original zip had real budget numbers for only 10 ministries over 9 years, and price data for 3 sector indices. The model needs four families of data: budget money, market prices, money flows, and text and events. The table shows which datasets are done and which still need collecting.

**Status key:** **In kit** = extracted and verified (25 of 25 spot-checked values match the source page). **Script ready** = run the kit's script on a laptop. **To build** = the team writes the scraper or parser.

| # | Dataset | Source | Granularity and span | Feeds | Status |
| --- | --- | --- | --- | --- | --- |
| D1 | Ministry BE / RE / Actuals | [PRS Union Budget Analyses](https://prsindia.org/budgets/parliament) | Top 13 ministries, FY17-18 to FY26-27 | Allocation growth, surprise vs RE, execution gap | In kit |
| D2 | Scheme allocations | PRS (same) | 32 flagship schemes, FY17-18 to FY26-27 | Scheme-level push (PM Surya Ghar, Bharatnet, PMAY…) | In kit |
| D3 | Subsidies, receipts, deficits | PRS (same) | Annual, FY17-18 to FY26-27 | Fiscal-stance features | In kit |
| D4 | Full Demand for Grants, all \~100 ministries, capital vs revenue split | [indiabudget.gov.in](https://www.indiabudget.gov.in) Expenditure Budget, "Statement of Budget Estimates" | Annual, FY05-06 to FY26-27 | Capex ratio per sector; fills Power, MNRE, MeitY gaps; extends history to 20 years | To build (pdfplumber parser; PRS extractor is the template) |
| D5 | Older PRS analyses | PRS archive | FY05-06 to FY18-19 | Cross-checks D4 | Script ready (`extract_prs_tables.py`) |
| D6 | Monthly fiscal execution | Controller General of Accounts [monthly accounts](https://cga.gov.in/Page/Monthly-Accounts-Review.aspx) | Monthly | "Is the money being spent?" tracker; mid-year signal | To build |
| D7 | Daily stock prices, about 120 stocks | Yahoo Finance via `yfinance` | Daily, 2005 to today | Sector baskets, momentum, volatility, targets | Script ready |
| D8 | Benchmarks and official sector indices | Yahoo Finance; [niftyindices.com](https://www.niftyindices.com) for indices missing on Yahoo (e.g. [Nifty India Defence](https://www.niftyindices.com/Factsheet/Factsheet_NiftyIndiaDefence.pdf)) | Daily | Benchmark, cross-check of the self-built baskets | Script ready / manual CSV |
| D9 | Stock universe rule (replaces the Nifty 500 constituent history, dropped 2026-10-27) | Derived from D7 prices: listed on budget day and 60-day average traded value of at least ₹5 cr | Per budget | Reduces, does not remove, survivorship bias (see risks) | Built |
| D10 | FPI flows by sector | [NSDL fortnightly sector-wise FPI](https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_July312024.html) (24 sectors, ₹ cr) | Fortnightly, 2017 to today | Smart-money flow before and after budget | Script ready |
| D11 | Macro: repo rate, CPI, 10-year G-sec, USD/INR, crude | [RBI DBIE](https://data.rbi.org.in), MoSPI, World Bank API, Yahoo | Monthly / annual | Regime and macro controls | Script ready (World Bank, Yahoo); RBI manual |
| D12 | Company fundamentals: sales, EBITDA, debt, order book, promoter pledge | Annual reports, Screener.in export, NSE shareholding pattern | Annual / quarterly | Stock-level quality and risk | To build |
| D13 | Order wins and contract announcements | BSE/NSE corporate announcements ("order received"), PIB, Ministry of Defence press releases | Event-level | `OrderInflow_c`: rupees won vs market cap | To build (NLP extraction) |
| D14 | Government procurement | [GeM](https://gem.gov.in) public dashboards; [CPPP](https://eprocure.gov.in) award-of-contract results | Event-level | `GovRevDep_c`, tender win rate | To build (best-effort; coverage partial) |
| D15 | Budget speech and highlights text | indiabudget.gov.in (the team's scraper already downloads 2004–2024) | Per budget | NLP: sector mention intensity, sentiment, new-scheme detection | Partly done |
| D16 | Budget-week news | GDELT 2.0 API, Google News RSS | Daily | Pre-budget expectation, "priced in" signal | To build |
| D17 | Live quotes | Broker developer API over WebSocket: Upstox API or Angel One SmartAPI (Dhan and Zerodha Kite Connect are alternatives). Needs a trading account; check current pricing and terms | Tick-level, market hours | Budget-Day live ticker, live sector moves vs forecast, Copilot's live-price tool | To build |

**Two data decisions worth defending at the viva**

1. **Self-built sector baskets.** Each basket is an equal-weight index of the mapped stocks, with each stock entering only from its listing date. Official Nifty sector indices start late (Nifty India Defence is recent) and do not match ministry boundaries. Official indices are kept only as a cross-check.
2. **The surprise feature, not the level.** `alloc_vs_prev_re_pct` compares the new BE with last year's RE, the most recent signal the market had. This is the closest public proxy for what was *new* on budget day.

**Known gaps.** The FY2025-26 PRS PDF is missing from the zip. Its BE and RE values were recovered from the FY2026-27 analysis, but its scheme table is thinner. Download it to complete D2.

## 5. System architecture

Data flows top to bottom through five layers. The feature store is the hinge: everything above it is collection and checking, and everything below it reads only point-in-time features that carry their source page.

&#91;embedded content: System architecture · 4 source families, 5 layers\]

Tier 1's sector forecast is an input to Tier 2. Both feed the explain-and-calibrate step before anything reaches a user, and every published forecast is hashed to the ledger.

## 6. Core functional requirements

There are seven modules. **Must** items are the minimum for a passing final demo, **Should** items make it strong, and **Could** items are stretch goals.

| ID | Module | Requirement | Priority |
| --- | --- | --- | --- |
| FR-1 | Ingestion | Scheduled jobs fetch prices, FPI flows and macro data, saved as raw files and loaded into PostgreSQL. Each job is idempotent (safe to re-run) and keeps a fetch log. | Must |
| FR-2 | Ingestion | Every number stores its source document, page and fetch date, so any figure on screen can be traced to its PDF page. | Must |
| FR-3 | Budget parser | The parser reads a new budget PDF (PRS analysis or Expenditure Budget) and outputs ministry, scheme and subsidy tables at BE/RE/Actuals stages. | Must |
| FR-4 | Budget parser | Parsed totals must reconcile: the sum of ministries plus "Other" equals Total Expenditure within 0.5%. Otherwise the run fails loudly. | Must |
| FR-5 | Budget parser | An LLM fallback extracts tables the regex parser misses, and its output must pass FR-4 before it is accepted. | Should |
| FR-6 | Feature store | Point-in-time features for each sector-year and stock-year. Only information public on budget day may be used: no actuals, no stocks listed after the budget, and no stock below the liquidity floor measured on the 60 trading days before the budget. | Must |
| FR-7 | Event study | Market-model CAR with t-stats for every sector and stock around every budget, for windows \[-5,-1\], 0, \[0,+5\], \[0,+30\] and \[0,+90\]. | Must |
| FR-8 | Tier-1 model | Ranks the 15 sectors for the coming year. Output: expected excess return, 10th–90th percentile interval, and probability of beating the Nifty 500. | Must |
| FR-9 | Tier-2 model | Ranks stocks within each sector using Tier-1 output plus stock features. Liquidity filter: average daily traded value ≥ ₹5 cr. | Must |
| FR-10 | Explainability | SHAP values for every prediction, turned into a three-bullet plain-English reason. | Must |
| FR-11 | Backtest | Walk-forward portfolio backtest of top-k sectors and stocks, with transaction costs, against baselines (§9). | Must |
| FR-12 | API | REST endpoints, e.g. `/budgets`, `/sectors/{id}/forecast`, `/stocks/{symbol}`, `/backtest`, `/simulate`. OpenAPI documentation. | Must |
| FR-13 | Dashboard | Screens as listed in §10. Works on phone width. | Must |
| FR-14 | Ops | One-command retrain when a new budget lands. Model registry keeps every past model so old predictions can be reproduced. | Should |
| FR-15 | Budget Copilot | Chatbot that calls the project's tools, writes answers with the Groq API, cites sources, shows basic visuals and enforces guardrails, as specified in §8. | Must |
| FR-16 | Live market feed | A WebSocket client streams live quotes for the \~120 stocks from a broker API (D17), aggregates them into live sector-basket moves, and pushes them to the dashboard and the Copilot. Falls back to delayed data when the market is closed or the feed drops. | Should |
| FR-17 | Secrets | API keys (Groq, broker, Telegram) live only in environment variables or a git-ignored .env file, never in code or the public ledger repo; a CI secret scan blocks any commit that contains one. | Must |

The kit's `build_dataset.py` already implements FR-6 and FR-7 for the sector and stock tables, and part of FR-11's targets.

## 7. Standout features

The three signature features are **Budget-Day Live Mode with sealed predictions**, the **Promise-vs-Reality tracker**, and the **What-If Budget Simulator**. Together they show that the system is real, honest and interactive. Build them first; the rest add depth.

### Signature features (build first)

**F1. Budget-Day Live Mode with sealed predictions.** On budget day, the system pulls the PDF, parses it (FR-3), and publishes the sector and stock forecasts within minutes. The predictions file's SHA-256 hash is then committed to a public GitHub repo with a timestamp. Nobody, including the team, can edit those predictions after the fact.

- The 2027-28 budget (expected 1 Feb 2027) falls before the final viva. The team can therefore demo a *real* live run, then show how the sealed FY2026-27 forecasts are tracking.
- Why it impresses: it is the strongest possible answer to "did you just overfit history?"

**F2. Promise-vs-Reality tracker.** For every ministry and scheme, the tracker compares what was promised (BE), what was revised (RE) and what was spent (Actuals). From this it computes a *credibility score*: the average execution gap over the last 3 years.

- The real data already shows big gaps. In 2025-26, Jal Jeevan Mission was budgeted at ₹67,000 cr but revised to ₹17,000 cr; Bharatnet ran at 25% of its BE.
- The score is also a model feature. The hypothesis to test: markets should discount allocations from ministries that chronically under-spend.

**F3. What-If Budget Simulator.** Sliders change any ministry or scheme allocation, and the Tier-1 model re-scores every sector live, with SHAP showing why. Presets replay real history, e.g. "Give Defence 2026-27 the same +1.4% it got in 2021-22."

- Judges love touching the model, and this turns a static ranking into an instrument.

### Depth features

| # | Feature | What it does | Why the panel will care | Effort |
| --- | --- | --- | --- | --- |
| F4 | Budget Surprise Index | Measures surprise two ways: new BE vs last RE, and the speech's sector emphasis vs the pre-budget news consensus (D16) | Separates *new* information from what was already known | Medium |
| F5 | Event-study explorer | Interactive CAR curves for each sector across 22 budgets; pre-budget drift shows what was "priced in" | Textbook finance method, done properly on real data | Low (kit computes it) |
| F6 | Speech NLP: "talk vs money" | Tags every speech sentence to a sector with a zero-shot or FinBERT classifier and scores emphasis. Divergence = high talk, low money (or the reverse) | Combines NLP and numbers; finds "announcement-only" sectors | Medium |
| F7 | Money-to-company knowledge graph | Ministry → scheme → product → company graph, built from order-win filings (D13) and procurement awards (D14). Each company gets a budget exposure score | Makes "which stock benefits" explainable as a path, not a black box | High |
| F8 | Order-win extractor | NLP over exchange filings pulls order value, client and government flag, giving `OrderInflow / MarketCap` | Converts unstructured filings into a strong stock-level signal | Medium |
| F9 | Calibrated uncertainty | Conformal prediction intervals on every forecast, with a coverage report | Honest confidence ranges; rare in student projects | Low |
| F10 | Regime awareness | Flags election-year and interim budgets, COVID-era fiscal shocks and high-VIX regimes as features, with separate error reports by regime | Shows the team understands *why* some years break models | Low |
| F11 | Causal check | Difference-in-differences: sectors with large allocation surprises vs matched sectors without, before and after the budget | Moves the claim from "correlated" to "evidence of effect" | Medium |
| F12 | Backtest lab | Equity curve of "follow the model since FY2012-13" vs the Nifty 500 and baselines, with costs, drawdown and turnover | One chart that answers "would this have made money?" | Low |
| F13 | Budget Copilot (full chatbot, §8) | Chatbot that calls the project's tools and writes answers with Groq. It answers from the documents, the database, the models and live prices, with citations and inline charts | A real product the judges can talk to, not a keyword bot | Medium |
| F14 | FPI flow radar | Fortnightly FPI flows by sector around each budget, overlaid on the forecast | Smart-money confirmation or divergence | Low |
| F15 | Budget-day alerts | Telegram or email digest when a watchlist sector's allocation surprise crosses a threshold | Feels like a product, not a notebook | Low |

**What makes the panel take it seriously:** sealed predictions (F1), a null-result-safe evaluation (§9), and a dataset that traces every number to its PDF page.

## 8. Budget Copilot: the chatbot

Budget Copilot answers each question like a real chatbot: in natural, conversational language, using the project's own data. It calls the project's tools to fetch the facts, then uses an AI model through the Groq API to write the answer. Every answer cites its sources and shows a simple chart or table when that helps. Each question is answered on its own; there is no conversation memory.

### What a user can ask

| User asks | What Copilot does |
| --- | --- |
| "Why is Defence ranked first this year?" | Gets the forecast and its top 3 reasons; cites the PRS page behind each budget figure |
| "Compare Railways and Roads allocations since 2018" | Queries the budget tables; replies with a short table and a bar or line chart |
| "What if Railways got 10% less?" | Runs the what-if simulator; lists how the sector ranking changes |
| "How did HAL react to past budgets?" | Pulls the event study; shows the budget-day moves in a small chart |
| "What are defence stocks doing right now?" | Reads the live feed (D17); compares the live move with the forecast |
| "What did the FM say about semiconductors?" | Searches the speeches; quotes the passage with year and page |
| "Should I buy BEL?" | Declines personal advice; offers the model's view, its confidence range and the risks |

### Tools the chatbot can call

| Tool | Returns | Backed by |
| --- | --- | --- |
| `search_documents(query, year?)` | Matching passages with document and page | Search index over the budget PDFs, speeches and PRS analyses |
| `query_budget(item, years, stage)` | BE / RE / Actuals figures | PostgreSQL budget tables (D1–D4) |
| `get_sector_forecast(sector)` | Expected excess return, range, P(beat Nifty 500) | Tier-1 model |
| `get_stock_ranking(sector)` | Ranked stocks with scores | Tier-2 model |
| `explain_prediction(target)` | Top reasons in plain words | SHAP results |
| `run_what_if(changes)` | Re-ranked sectors | What-if simulator (F3) |
| `get_event_study(target)` | Budget-day abnormal returns | Event-study tables |
| `get_live_quotes(sector)` | Live prices and moves | Live feed (D17) |

All tools are read-only: none can change data or place an order.

### How an answer is produced

1. The question and the tool definitions go to the Groq model, which decides which tools to call.
2. The backend runs those tools and sends the results back to the model.
3. The model writes the answer from those results only. It never uses numbers from its own memory.
4. The reply shows the answer text, citation chips and, when useful, one basic chart or table.

### Answers, sources and visuals

- **Citations.** Every fact carries a source chip, such as "PRS Budget Analysis 2026-27, p.5" or "Event study table". Clicking it opens the PDF page or the dashboard screen.
- **Basic visuals.** A bar chart, a line chart or a small table, drawn by the frontend from the tool's data. The model only chooses the chart type.
- **Plain language.** Short answers, with the key number first.

### AI API setup

- **Model:** a Groq-hosted model that supports tool calling, chosen from the current list at console.groq.com.
- **Key:** `GROQ_API_KEY` is kept on the server in an environment variable (FR-17). The browser never sees it.
- **Demo safety:** cache answers to common questions, and keep one backup model configured in case of rate limits.

### Guardrails

- **No investment advice.** No buy/sell or personalised advice, and a short disclaimer on market answers.
- **Answers only from data.** If the tools and documents don't contain the answer, it says it doesn't know instead of guessing.
- **Numbers are checked.** Before an answer is shown, every number in it must appear in a tool result. If one doesn't, the answer is regenerated.
- **Injection-safe.** Text inside documents is treated as data, never as instructions, so a PDF cannot hijack the bot.
- **Stays on topic.** Off-topic requests are politely redirected to the budget and markets.

### Testing

Run 50 questions with known answers and pages, plus 15 prompts that ask for advice or try to trick the bot. Targets:

- every number traceable to a source
- at least 95% correct citations
- every trick prompt refused

## 9. Modelling and evaluation

The data is small: 15 sectors × about 20 budgets gives roughly 300 sector-year rows, and the stock tables have about 2,000 stock-year rows. The modelling plan therefore favours pooled, regularised models and strict walk-forward testing over deep networks. The LSTM from the synopsis stays only if it beats the simpler models in an ablation.

### Key quantities

Budget surprise for sector s in year t, using the latest revised estimate as the reference:

```latex
\text{Surprise}_{s,t} = \frac{\sum_{m \in s} BE_{m,t}}{\sum_{m \in s} RE_{m,t-1}} - 1
```

Execution credibility (F2), the average gap between spending and promise over the last 3 years:

```latex
\text{Cred}_{s,t} = \frac{1}{3}\sum_{k=1}^{3} \left( \frac{\text{Actual}_{s,t-k}}{BE_{s,t-k}} - 1 \right)
```

Cumulative abnormal return (CAR) from a market model estimated on trading days −250 to −31 before the budget:

```latex
CAR_{s}[\tau_1,\tau_2] = \sum_{\tau=\tau_1}^{\tau_2} \left( r_{s,\tau} - \hat{\alpha}_s - \hat{\beta}_s \, r_{m,\tau} \right)
```

### Models

| Tier | Model | Role |
| --- | --- | --- |
| Baselines | Equal-weight all sectors; last year's winners (momentum); "biggest allocation increase wins" rule; ridge regression | The bars every model must clear |
| Tier 1, sectors | LightGBM / XGBoost with ranking objective (LambdaRank), shallow trees, Optuna tuning inside the walk-forward loop | Main sector ranker |
| Tier 1, sectors | Bayesian hierarchical regression (PyMC): sector-specific slopes on surprise, partially pooled | Honest on small data; gives a credible interval per sector |
| Tier 2, stocks | LightGBM ranker on stock features + Tier-1 output, trained within sector | Stock ranking |
| Tier 2, stocks | Optional LSTM or temporal CNN on 250-day pre-budget price paths, used as an embedding into the ranker | Kept only if the ablation shows gain |
| Both | Conformal prediction wrapper | Calibrated 80% intervals (F9) |
| Both | Stacked ensemble of the above | Final forecast |

### Validation protocol

1. **Expanding-window walk-forward.** Train on budgets up to year t−1 and predict year t, for every t from FY2012-13 onward. Report each year separately, not just the average.
2. **Non-overlapping targets.** Each target runs budget-to-budget, so there is no overlap between adjacent years. Rows with `target_complete = False` are excluded from training.
3. **Point-in-time features only.** No Actuals for the same year, no stocks listed after the budget, and only stocks whose average daily traded value over the prior 60 trading days is at least ₹5 crore (D9). Index membership on budget day is not checked, and the stock list is today's symbols, so survivorship bias is reduced but not removed.
4. **Hyperparameters tuned inside each fold.** Never tune on the test year.
5. **Final hold-out.** FY2024-25 and FY2025-26 stay untouched until the end. FY2026-27 is the sealed live year (F1).

### Metrics

- **Sector:** Spearman rank IC, hit-rate of the top 3 sectors, MAE of excess return, directional accuracy.
- **Stock:** Precision@5 and NDCG@10 within each sector.
- **Portfolio:** CAGR, Sharpe ratio, maximum drawdown and turnover of the top-k strategy after 0.2% round-trip costs, vs the baselines and the Nifty 500.
- **Uncertainty:** interval coverage and width.

### Ablations (reported in the final report)

Remove each family of features in turn and measure the drop in IC:

- budget money
- surprise
- execution credibility
- speech NLP
- FPI flows
- momentum

This answers the panel's central question directly: *does the budget data add anything beyond price momentum?*

### Statistical honesty

- Report t-stats or bootstrap confidence intervals for IC.
- Apply a Benjamini–Hochberg correction when claiming significant sector event effects across 15 sectors.

## 10. Dashboard screens

The dashboard has eight screens. Each one answers a single question, and each one carries a standing footer: "Research tool, not investment advice."

| Screen | Question it answers | Key visuals | Features |
| --- | --- | --- | --- |
| 1. Budget overview | What did this budget do with the money? | Ministry treemap; BE vs RE vs Actual bars; capex vs revenue split | D1–D4 |
| 2. Sector heat-map | Which sectors should outperform this year? | 15-sector grid coloured by expected excess return, with interval whiskers and P(beat Nifty 500) | FR-8, F9 |
| 3. Sector deep-dive | Why this sector? | SHAP waterfall; surprise and credibility cards; event-study CAR curve; FPI flow strip | F2, F4, F5, F14 |
| 4. Stock watchlist | Which stocks within it? | Ranked table: score, interval, liquidity, order-win flag; filter by risk | FR-9, F8 |
| 5. What-if simulator | What if the allocation were different? | Sliders per ministry or scheme; live re-ranked heat-map; diff vs actual budget | F3 |
| 6. Promise vs reality | Is the money being spent? | Credibility league table of ministries and schemes; monthly execution line (CGA) | F2, D6 |
| 7. Backtest and evidence | Would this have worked? | Equity curve vs baselines; IC by year; ablation bars; sealed-prediction ledger with hashes | FR-11, F1, F12 |
| 8. Budget Copilot | Anything about the budget, sectors, stocks or forecasts | Chat page with cited answers and basic charts or tables; a chat button on every other screen | F13 |

**Budget-Day Live Mode** is a banner state across all screens. It shows parse progress, then a "Forecast sealed at HH:MM, hash 3f2a…" stamp.

During the speech, a live ticker streams sector-basket moves from the broker API (D17) next to the model's forecast, so viewers watch the market react in real time.

**UX rules**

- Every number is clickable to its source page (FR-2).
- Every chart has a one-line takeaway.
- Layout works at phone width.
- Dark mode is supported.

## 11. Non-functional requirements and tech stack

The stack stays close to the synopsis, with three upgrades:

- FastAPI instead of Flask, which gives automatic OpenAPI documentation.
- An MLflow model registry.
- Free-tier hosting, which cuts the ₹31,000 cloud budget to near zero.

**Non-functional requirements**

| Area | Requirement |
| --- | --- |
| Reproducibility | `make data && make train && make backtest` rebuilds every number in the report from raw files. Seeds fixed; data versioned with DVC or dated snapshots. |
| Latency | Budget PDF to dashboard < 3 min; API p95 < 500 ms for cached forecasts |
| Data quality | Automated checks (Great Expectations or pandera): totals reconcile, no future dates, no duplicate symbol-days, price jumps > 50% flagged |
| Traceability | Every stored value carries source, page and fetch time |
| Testing | Unit tests for parsers and feature functions; a "leakage test" that fails if any feature date ≥ its prediction date |
| Security and compliance | No user trading data collected; scrape politely (rate limits, robots.txt); clear not-advice disclaimer |

**Stack**

| Layer | Choice |
| --- | --- |
| Language | Python 3.11 |
| Data | pandas, pdfplumber, requests, yfinance, PostgreSQL 15 (Supabase free tier or local) |
| ML | scikit-learn, LightGBM / XGBoost, PyMC, MAPIE (conformal prediction), SHAP, Optuna, MLflow |
| NLP | Hugging Face Transformers (FinBERT / zero-shot), sentence-transformers for retrieval-augmented generation (RAG), Groq API for the chatbot and parser fallback (tool calling), with a backup model configured |
| Backend | FastAPI, APScheduler for jobs |
| Frontend | React + Vite + Recharts/Plotly; Streamlit kept as an internal analyst console |
| Ops | Docker Compose, GitHub Actions CI, deploy on Render / Railway free tier |
| Live data and chat | Broker WebSocket API (Upstox or Angel One SmartAPI); FastAPI WebSockets to stream live quotes to the browser; Redis to cache live quotes and common chatbot answers |

**Hardware.** Any 8 GB-RAM laptop handles the full pipeline; the data is under 1 GB. A GPU is needed only for optional NLP fine-tuning. Google Colab suffices.

## 12. Risks, limitations and ethics

The biggest risk is the small sample: about 20 budgets cannot prove a trading edge. The project is framed as rigorous evidence-gathering plus a decision tool, not a money machine.

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Small sample, noisy target | Overfitting; unstable rankings | Pooled hierarchical models, few features, walk-forward, ablations, report per-year results |
| Look-ahead bias | Inflated backtest | Listing-date and liquidity universe rule (D9), leakage unit test, sealed live forecasts (F1) |
| Survivorship bias (not fully removed) | Inflated stock-level results | The stock list is today's symbols, so delisted names are missing, and index membership on budget day is not checked; the liquidity rule limits but does not remove it, and it is stated in the data-gaps report |
| Older budget PDFs are scanned or inconsistent | Missing history before FY2017-18 | Use the Expenditure Budget statements (D4); OCR fallback; reconciliation check (FR-4) |
| Ministry renames and restructuring (e.g. HRD → Education, Jal Shakti from 2019) | Broken time series | Alias table in `build_budget_panels.py`; document each mapping |
| Yahoo symbol changes, delistings | Missing prices | Fetch log, manual fixes, NSE bhavcopy fallback |
| Scrapers break (NSDL, GeM, exchanges) | Stale features | Cached snapshots; the model degrades gracefully when a feature family is missing |
| Election, interim and COVID years behave differently | Large errors in those years | Regime flags (F10); report errors by regime |
| Users read output as advice | Harm, regulatory issues | Persistent disclaimer; the assistant refuses buy/sell requests; no personalised recommendations. SEBI's research-analyst rules apply only to commercial advice; a student research tool should still say so plainly |
| Chatbot hallucinates a number | Wrong figure shown to a judge | Numbers come only from tool results, never from the model's memory; a post-check verifies every number in a reply appears in a tool result or cited chunk |
| Groq free-tier rate limits or outage | Chatbot fails mid-demo | Cache common answers and keep a backup model configured |
| Broker API feed drops or terms change | No live ticker on Budget Day | Auto-reconnect; fall back to delayed quotes; keep a recorded replay of a past budget day as backup |

**Stated limitations (to say before the panel does)**

- Budget allocations are one driver among many: earnings, global rates and flows dominate year-to-year returns.
- The mapping from ministry to stocks is a judgement call and is documented as such.

## 13. References and sources

**Literature.** Items 1–7 are kept from the synopsis; items 8–9 are added.

1. R. J. Barro, "Government Spending in a Simple Model of Endogenous Growth," *Journal of Political Economy*, 98(5), 1990.
2. O. Blanchard and R. Perotti, "An Empirical Characterization of the Dynamic Effects of Changes in Government Spending and Taxes on Output," *QJE*, 117(4), 2002.
3. T. Fischer and C. Krauss, "Deep Learning with LSTM Networks for Financial Market Predictions," *EJOR*, 270(2), 2018.
4. N. R. Bhanumurthy et al., "Modelling India's Fiscal Policy: Macro-Fiscal Linkages," NIPFP Working Paper 272, 2019.
5. J. Patel et al., "Predicting stock and stock price index movement using trend deterministic data preparation and machine learning techniques," *Expert Systems with Applications*, 42(1), 2015.
6. F. Carril-Caccia et al., "Foreign Direct Investment and Public Procurement," *International Business Review*, 31(4), 2022.
7. S. M. Lundberg and S.-I. Lee, "A Unified Approach to Interpreting Model Predictions," NeurIPS 30, 2017.
8. M. Patel et al., ["Analysis of the Impact of the Union Budget Announcements on the Indian Stock Market: A Fractal Perspective,"](https://arxiv.org/pdf/2502.15787) arXiv:2502.15787, 2025. Event study around Budget 2023 and 2024 on the Nifty 50.
9. A. N. Angelopoulos and S. Bates, "A Gentle Introduction to Conformal Prediction," arXiv:2107.07511, 2021.

**Data sources (pages opened while writing this PRD)**

- [PRS Legislative Research — Union Budget analyses](https://prsindia.org/budgets/parliament)
- [CGA — Monthly Accounts](https://cga.gov.in/Page/Monthly-Accounts-Review.aspx)
- [NSDL — Fortnightly sector-wise FPI investment (example, July 2024)](https://www.fpi.nsdl.co.in/web/StaticReports/Fortnightly_Sector_wise_FII_Investment_Data/FIIInvestSector_July312024.html)
- [Nifty India Defence factsheet](https://www.niftyindices.com/Factsheet/Factsheet_NiftyIndiaDefence.pdf)
- [ETV Bharat — exchanges trade on Sunday 1 Feb 2026 for the Budget](https://www.etvbharat.com/en/business/stock-market-update-bse-nse-to-conduct-regular-trading-session-on-budget-day-enn26013103011)
- [Union Budget portal](https://www.indiabudget.gov.in), [GeM](https://gem.gov.in), [CPPP](https://eprocure.gov.in), [RBI DBIE](https://data.rbi.org.in)

Budget figures quoted in this PRD come from the PRS analyses in the team's zip, extracted with page references into `data/extracted/`.
