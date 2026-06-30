# =============================================================================
# Distillery — developer task runner
# =============================================================================
.DEFAULT_GOAL := help
SHELL := /bin/bash
PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PKG := src/distillery
COMPOSE := docker compose -f docker-compose.yml

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ---- Environment -----------------------------------------------------------
.PHONY: venv
venv: ## Create a virtual environment
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip wheel

.PHONY: install
install: venv ## Install the package with dev extras (editable)
	$(BIN)/pip install -e ".[dev]"

.PHONY: install-hooks
install-hooks: ## Install pre-commit git hooks
	$(BIN)/pre-commit install

# ---- Quality gates ---------------------------------------------------------
.PHONY: format
format: ## Auto-format with black + ruff --fix
	$(BIN)/ruff check --fix $(PKG) tests
	$(BIN)/black $(PKG) tests

.PHONY: lint
lint: ## Lint with ruff + black --check
	$(BIN)/ruff check $(PKG) tests
	$(BIN)/black --check $(PKG) tests

.PHONY: typecheck
typecheck: ## Static type-check with mypy
	$(BIN)/mypy $(PKG)

.PHONY: test
test: ## Run the full test suite with coverage
	$(BIN)/pytest --cov --cov-report=term-missing --cov-report=xml

.PHONY: test-unit
test-unit: ## Run only fast unit tests
	$(BIN)/pytest -m unit

.PHONY: test-integration
test-integration: ## Run integration tests
	$(BIN)/pytest -m integration

.PHONY: test-e2e
test-e2e: ## Run end-to-end tests
	$(BIN)/pytest -m e2e

.PHONY: check
check: lint typecheck test ## Run all quality gates (lint + types + tests)

.PHONY: security
security: ## Run dependency + static security scans
	$(BIN)/pip install pip-audit bandit >/dev/null 2>&1 || true
	$(BIN)/pip-audit || true
	$(BIN)/bandit -r $(PKG) -ll || true

# ---- Application -----------------------------------------------------------
.PHONY: run-api
run-api: ## Run the API locally (reload)
	$(BIN)/uvicorn distillery.api.app:create_app --factory --reload \
		--host 0.0.0.0 --port 8000

.PHONY: run-worker
run-worker: ## Run a Celery worker locally
	$(BIN)/celery -A distillery.infrastructure.queue.celery_app:celery_app worker \
		--loglevel=INFO --concurrency=2

.PHONY: migrate
migrate: ## Apply database migrations
	$(BIN)/alembic upgrade head

.PHONY: migration
migration: ## Autogenerate a migration: make migration m="message"
	$(BIN)/alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## Seed the database with bootstrap data
	$(BIN)/distillery db seed

# ---- Docker / Compose ------------------------------------------------------
.PHONY: up
up: ## Start the full stack with Docker Compose
	$(COMPOSE) up -d --build

.PHONY: down
down: ## Stop the stack
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Tail Compose logs
	$(COMPOSE) logs -f

.PHONY: ps
ps: ## Show Compose services
	$(COMPOSE) ps

# ---- Housekeeping ----------------------------------------------------------
.PHONY: clean
clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml \
		dist build *.egg-info site
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
