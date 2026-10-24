PYTHON ?= python
VENV ?= .venv
PIP := $(VENV)/Scripts/python.exe
PROJECT_ROOT := $(CURDIR)

.PHONY: setup db-migrate parse-pdfs download-budget-pdfs reconcile-budgets collect load data features train backtest holdout test api web console live retrain lint typecheck

setup:
	@echo "[1/6] Creating virtualenv if needed"
	@if not exist "$(VENV)" $(PYTHON) -m venv $(VENV)
	@echo "[2/6] Installing package in editable mode"
	@$(PIP) -m pip install --upgrade pip
	@$(PIP) -m pip install -e ".[dev]"
	@if not exist ".env" copy .env.example .env
	@echo "Setup complete. Fill in .env and run 'docker compose up -d'."

lint:
	@$(PIP) -m ruff check src tests

typecheck:
	@$(PIP) -m mypy src

test:
	@$(PIP) -m pytest -q

# Phase 0 database migration target. Defaults to SQLite so the repo works on a clean machine without Docker running.
db-migrate:
	@$(PIP) -m alembic upgrade head

parse-pdfs:
	@$(PIP) -m bsp.parsers.prs data/source_pdfs data/csv
	@$(PIP) scripts/build_statement3.py
	@$(PIP) scripts/build_budget_csvs.py
	@$(PIP) scripts/build_statement3.py

download-budget-pdfs:
	@$(PIP) scripts/collect/download_budget_pdfs.py

reconcile-budgets:
	@$(PIP) -m bsp.quality.reconcile

collect:
	@$(PIP) -m bsp.ingest.prices
	@$(PIP) -m bsp.ingest.benchmarks
	@$(PIP) -m bsp.ingest.constituents
	@$(PIP) -m bsp.ingest.macro
	@$(PIP) -m bsp.ingest.fpi

load:
	@$(PIP) -m bsp.parsers.load

data: parse-pdfs collect load

features:
	@$(PIP) -m bsp.features.build

train:
	@echo "Placeholder for Phase 4/7 training."

backtest:
	@echo "Placeholder for Phase 8 backtest."

holdout:
	@echo "Placeholder for hold-out evaluation."

api:
	@echo "Placeholder for FastAPI API."

web:
	@echo "Placeholder for React dashboard."

console:
	@echo "Placeholder for Streamlit analyst console."

live:
	@echo "Placeholder for live budget-day pipeline."

retrain:
	@echo "Placeholder for retraining workflow."
