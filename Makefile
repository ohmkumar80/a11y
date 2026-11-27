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
	$(PY) -m pip install -q -e "libs/core[dev]" -e "apps/api[dev]"

migrate: ## Run Alembic migrations against local Postgres
	cd apps/api && ../../$(PY) -m alembic upgrade head

seed: ## Load seed data (idempotent)
	$(PY) -m a11y_api.seed

test-api: ## API tests (needs `docker compose up -d postgres`)
	cd apps/api && ../../$(PY) -m pytest

test-web: ## UI + web tests
	pnpm -r --if-present test

lint: ## Lint everything
	.venv/bin/ruff check libs apps/api
	pnpm -r --if-present lint

a11y-tokens: ## Verify design-token contrast
	pnpm --filter @a11y/ui check:contrast
