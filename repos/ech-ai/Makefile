.PHONY: help install dev test lint format clean docker-build docker-up docker-down migrate

# Default target
help:
	@echo "Available commands:"
	@echo "  install     - Install dependencies with Poetry"
	@echo "  dev         - Start development server"
	@echo "  test        - Run tests"
	@echo "  test-cov    - Run tests with coverage"
	@echo "  lint        - Run linting (flake8, mypy)"
	@echo "  format      - Format code (black, isort)"
	@echo "  clean       - Clean up temporary files"
	@echo "  migrate     - Run database migrations"
	@echo "  docker-build - Build Docker image"
	@echo "  docker-up   - Start services with Docker Compose"
	@echo "  docker-down - Stop Docker Compose services"

# Install dependencies
install:
	poetry install
# Start development environment
dev-env:
	docker-compose -f docker-compose-base.yml up -d

# Start development server (ensures DB migrations are applied first)
dev: dev-env migrate
	poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8083

# Start full dev stack: DB up -> migrate -> app
dev-all: dev-env migrate
	poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8083

# Run tests
test:
	poetry run pytest

# Run tests with coverage
test-cov:
	poetry run pytest --cov=app --cov-report=html --cov-report=term-missing

# Run linting
lint:
	poetry run flake8 app tests
	poetry run mypy app

# Format code
format:
	poetry run black app tests
	poetry run isort app tests

# Clean up temporary files
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .coverage htmlcov/ .pytest_cache/ .mypy_cache/

# Database migrations
migrate:
	poetry run alembic upgrade heads

# Create new migration
migration:
	poetry run alembic revision --autogenerate -m "$(MSG)"

# Docker commands
docker-build:
	docker build -t tgo-ai-service .

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f tgo-ai-service

# Development setup
setup: install
	cp .env.example .env
	@echo "Setup complete! Edit .env file with your configuration."

# Run all quality checks
check: format lint test

# Production build
build: clean
	poetry build
