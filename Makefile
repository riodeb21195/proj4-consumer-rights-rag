.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: help lint format test clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

lint: ## Ruff lint + format check + mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

format: ## Auto-format and fix lint issues
	uv run ruff format .
	uv run ruff check --fix .

test: ## Run unit and integration tests with coverage
	uv run pytest --cov --cov-report=term-missing

clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml build dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
