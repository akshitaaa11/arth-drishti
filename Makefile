# Cross-platform: works with GNU make on Linux/macOS and Git Bash/WSL on Windows.
PYTHON ?= python
VENV ?= .venv
ifeq ($(OS),Windows_NT)
VENV_PY := $(VENV)/Scripts/python.exe
else
VENV_PY := $(VENV)/bin/python
endif
# Use the virtualenv interpreter when it exists, otherwise the active Python (e.g. CI).
PY := $(if $(wildcard $(VENV_PY)),$(VENV_PY),$(PYTHON))

.PHONY: setup db-migrate parse-pdfs download-budget-pdfs reconcile-budgets collect load data features train backtest holdout test api web console live retrain lint typecheck

setup:
	@echo "[1/4] Creating virtualenv if needed"
	@test -d "$(VENV)" || $(PYTHON) -m venv $(VENV)
	@echo "[2/4] Installing package in editable mode"
	@$(PY) -m pip install --upgrade pip
	@$(PY) -m pip install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo "Setup complete. Fill in .env and run 'docker compose up -d'."

lint:
	@$(PY) -m ruff check src tests scripts

typecheck:
	@$(PY) -m mypy src

test:
	@$(PY) -m pytest -q

# Phase 0 database migration target. Defaults to SQLite so the repo works on a clean machine without Docker running.
db-migrate:
	@$(PY) -m alembic upgrade head

parse-pdfs:
	@$(PY) -m bsp.parsers.prs data/source_pdfs data/csv
	@$(PY) scripts/build_statement3.py
	@$(PY) scripts/build_budget_csvs.py
	@$(PY) scripts/build_statement3.py

download-budget-pdfs:
	@$(PY) scripts/collect/download_budget_pdfs.py

reconcile-budgets:
	@$(PY) -m bsp.quality.reconcile

collect:
	@$(PY) -m bsp.ingest.prices
	@$(PY) -m bsp.ingest.benchmarks
	@$(PY) -m bsp.ingest.macro
	@$(PY) -m bsp.ingest.fpi

load: db-migrate
	@$(PY) -m bsp.parsers.load
	@$(PY) -m bsp.ingest.load
	@$(PY) -m bsp.features.build --skip-build

data: parse-pdfs collect load

features: db-migrate
	@$(PY) -m bsp.features.build

train:
	@MLFLOW_DISABLE_AGENT_HINT=1 $(PY) -m bsp.models.run_models

backtest:
	@MLFLOW_DISABLE_AGENT_HINT=1 $(PY) -m bsp.evaluation.run_baselines

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
