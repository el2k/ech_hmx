SHELL := /bin/bash

# Configuration
PORT ?= 8001
APP_MODULE := app.main:app
ENV_FILE := .env
POSTGRES_CONTAINER := tgo-platform-postgres

# Ensure .env exists
check-env: ## Verify .env exists (copy from .env.example if missing)
	@if [ ! -f $(ENV_FILE) ]; then \
		echo "Error: $(ENV_FILE) not found."; \
		echo "Please create it: cp .env.example $(ENV_FILE) && edit values."; \
		exit 1; \
	fi

# Ensure Docker installed and running
check-docker: ## Verify Docker is installed and running
	@if ! command -v docker >/dev/null 2>&1; then \
		echo "Error: Docker is not installed. Please install Docker Desktop or Docker Engine."; \
		exit 1; \
	fi
	@if ! docker info >/dev/null 2>&1; then \
		echo "Error: Docker daemon not running. Please start Docker."; \
		exit 1; \
	fi

# Development server with dependencies and hot reload
dev: check-env check-docker ## Start Docker deps, wait healthy, then FastAPI dev server (reload) on $(PORT)
	@echo "Starting Docker services...";
	@# Prefer 'docker compose', fallback to 'docker-compose'
	@if docker compose version >/dev/null 2>&1; then docker compose up -d; \
	elif docker-compose version >/dev/null 2>&1; then docker-compose up -d; \
	else echo "Error: Docker Compose not found. Install Docker Compose v2 or v1."; exit 1; fi
	@echo "Waiting for PostgreSQL to be healthy...";
	@for i in {1..60}; do \
		status=$$(docker inspect -f '{{.State.Health.Status}}' $(POSTGRES_CONTAINER) 2>/dev/null || echo "starting"); \
		if [ "$$status" = "healthy" ]; then echo "PostgreSQL is healthy."; break; fi; \
		echo "  status: $$status (retry $$i/60)"; sleep 2; \
		if [ $$i -eq 60 ]; then echo "Timeout waiting for PostgreSQL to be healthy."; exit 1; fi; \
	done
	@echo "Starting development server (reload enabled)...";
	@echo "Using env file: $(ENV_FILE)";
	@echo "Access URL:  http://127.0.0.1:$(PORT)";
	@echo "Health URL:  http://127.0.0.1:$(PORT)/health";
	@echo "DB DSN:      postgresql+asyncpg://tgo_user:tgo_pass@127.0.0.1:5432/tgo";
	@set -a; source $(ENV_FILE); set +a; \
		poetry run uvicorn $(APP_MODULE) --reload --port $(PORT)

# Docker helpers
dev-down: check-docker ## Stop Docker services
	@echo "Stopping Docker services...";
	@if docker compose version >/dev/null 2>&1; then docker compose down; \
	elif docker-compose version >/dev/null 2>&1; then docker-compose down; \
	else echo "Error: Docker Compose not found."; exit 1; fi

dev-logs: check-docker ## Tail Docker services logs
	@if docker compose version >/dev/null 2>&1; then docker compose logs -f; \
	elif docker-compose version >/dev/null 2>&1; then docker-compose logs -f; \
	else echo "Error: Docker Compose not found."; exit 1; fi

dev-clean: check-docker ## Stop and remove Docker services and volumes
	@echo "Stopping and removing Docker services and volumes...";
	@if docker compose version >/dev/null 2>&1; then docker compose down -v; \
	elif docker-compose version >/dev/null 2>&1; then docker-compose down -v; \
	else echo "Error: Docker Compose not found."; exit 1; fi

# Dependency management
install: ## Install dependencies with Poetry
	poetry install

# Quality and tests
test: ## Run tests with pytest
	poetry run pytest

lint: ## Lint code with ruff
	poetry run ruff check .

format: ## Format code with ruff
	poetry run ruff format .


# Database and migrations
db-verify: check-docker ## Verify database connection and show tables
	@echo "Verifying database connection...";
	@docker exec -it $(POSTGRES_CONTAINER) psql -U tgo_user -d tgo -c "\dt" || \
		(echo "Error: Cannot connect to database. Ensure Docker services are running (make dev)."; exit 1)

db-shell: check-docker ## Open psql shell in the database
	@docker exec -it $(POSTGRES_CONTAINER) psql -U tgo_user -d tgo

db-reset: check-docker ## Drop and recreate the database (WARNING: destroys all data)
	@echo "WARNING: This will destroy all data in the database!";
	@read -p "Are you sure? [y/N] " -n 1 -r; echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker exec -it $(POSTGRES_CONTAINER) psql -U postgres -c "DROP DATABASE IF EXISTS tgo;"; \
		docker exec -it $(POSTGRES_CONTAINER) psql -U postgres -c "CREATE DATABASE tgo OWNER tgo_user;"; \
		docker exec -it $(POSTGRES_CONTAINER) psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE tgo TO tgo_user;"; \
		echo "Database reset complete. Run 'make migrate-upgrade' to apply migrations."; \
	else \
		echo "Cancelled."; \
	fi

db-init: ## Create tables using SQLAlchemy Base.metadata (no Alembic)
	poetry run python -m app.db.init_db

db-seed: check-docker ## Seed database with sample email platform
	@echo "Seeding database with sample email platform...";
	@docker exec -i $(POSTGRES_CONTAINER) psql -U tgo_user -d tgo < scripts/seed_email_platform.sql

migrate-rev: ## Create an Alembic revision with autogenerate; requires alembic installed
	PYTHONPATH=. poetry run alembic revision --autogenerate -m "init"

migrate-upgrade: ## Apply Alembic migrations to head
	PYTHONPATH=. poetry run alembic upgrade head

migrate-downgrade: ## Revert last Alembic migration step
	PYTHONPATH=. poetry run alembic downgrade -1

# Show help
help: ## Show this help message
	@echo "Available make targets:";
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

.PHONY: dev dev-down dev-logs dev-clean install test lint format help check-env check-docker
