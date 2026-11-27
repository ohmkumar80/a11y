.DEFAULT_GOAL := help
PY := .venv/bin/python
COMPOSE := docker compose

.PHONY: help env up down reset seed migrate venv test-api test-web lint a11y-tokens

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing
	@test -f .env || cp .env.example .env

up: env ## Start the full stack (migrations + seed data run automatically)
	$(COMPOSE) up --build

down: ## Stop the stack
	$(COMPOSE) down

reset: ## Stop the stack and delete all data volumes
	$(COMPOSE) down -v

venv: ## Create the Python venv with API deps
	python3.12 -m venv .venv
	$(PY) -m pip install -q -U pip
	$(PY) -m pip install -q -e "libs/core[dev]" -e "workers/web_audit[dev]" -e "apps/api[dev]"
	$(PY) -m playwright install chromium

migrate: ## Run Alembic migrations against local Postgres
	cd apps/api && ../../$(PY) -m alembic upgrade head

seed: ## Load seed data (idempotent)
	$(PY) -m a11y_api.seed

test-api: ## API tests (needs `docker compose up -d postgres`)
	cd apps/api && ../../$(PY) -m pytest

test-web: ## UI + web tests
	pnpm -r --if-present test

engines: ## Build the pinned scan-engine bundles (needed by the scanner and its tests)
	pnpm install --filter @a11y/engine-bundles... && pnpm --filter @a11y/engine-bundles build

rules-catalog: ## Regenerate rules/engine-catalog.json after changing engine versions
	$(PY) workers/web_audit/scripts/gen_engine_catalog.py

lint: ## Lint everything
	.venv/bin/ruff check libs apps/api workers
	pnpm -r --if-present lint

a11y-tokens: ## Verify design-token contrast
	pnpm --filter @a11y/ui check:contrast
