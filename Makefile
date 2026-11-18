.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose

.PHONY: help up up-llm down ingest eval test lint format clean logs ps

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

up: ## Build and start the stack (API, UI, Airflow, Postgres, MinIO)
	$(COMPOSE) up -d --build --wait

up-llm: ## Start the stack plus the optional Ollama LLM
	RAG_LLM_ENABLED=true $(COMPOSE) --profile llm up -d --build --wait

down: ## Stop the stack (keeps volumes)
	$(COMPOSE) --profile llm down

ingest: ## Trigger the Airflow ingest DAG and wait for it
	./scripts/trigger_ingest.sh

logs: ## Follow logs of all services
	$(COMPOSE) logs -f --tail=100

ps: ## Show service status
	$(COMPOSE) ps

lint: ## Ruff lint + format check + mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

format: ## Auto-format and fix lint issues
	uv run ruff format .
	uv run ruff check --fix .

test: ## Run unit and integration tests with coverage
	uv run pytest --cov --cov-report=term-missing

clean: ## Remove caches and build artefacts (use `docker compose down -v` to drop data)
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml build dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
