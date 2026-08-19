.PHONY: help dev build up down logs shell db-shell migrate migration test lint format clean install

# Default target
help: ## Show this help message
	@echo "TGO-Tech API Service - Development Commands"
	@echo "==========================================="
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Development Environment
dev: ## Start development environment (one-click startup)
	@echo "🚀 Starting TGO-Tech API development environment..."
	@cp -n .env.example .env 2>/dev/null || true
	@echo "📋 Environment file ready (.env)"
	@docker-compose up -d postgres redis adminer
	@echo "⏳ Waiting for database to be ready..."
	@sleep 10
	@$(MAKE) migrate
	@echo "🔧 Starting API server..."
	@poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Docker Commands
build: ## Build Docker images
	@echo "🔨 Building Docker images..."
	@docker-compose build

up: ## Start all services with Docker Compose
	@echo "🚀 Starting all services..."
	@docker-compose up -d

down: ## Stop all services
	@echo "🛑 Stopping all services..."
	@docker-compose down

logs: ## Show logs from all services
	@docker-compose logs -f

# Database Commands
db-up: ## Start only database services
	@echo "🗄️ Starting database services..."
	@docker-compose up -d postgres redis

db-shell: ## Connect to PostgreSQL database
	@echo "🔗 Connecting to database..."
	@docker-compose exec postgres psql -U postgres -d tgo_api

migrate: ## Run database migrations
	@echo "📊 Running database migrations..."
	@poetry run alembic upgrade head

migration: ## Create new migration (usage: make migration MESSAGE="description")
	@echo "📝 Creating new migration..."
	@poetry run alembic revision --autogenerate -m "$(MESSAGE)"

db-reset: ## Reset database (WARNING: destroys all data)
	@echo "⚠️ Resetting database..."
	@read -p "Are you sure? This will destroy all data (y/N): " confirm && [ "$$confirm" = "y" ]
	@docker-compose down -v
	@docker-compose up -d postgres redis
	@sleep 10
	@$(MAKE) migrate

# Development Tools
shell: ## Open Python shell with app context
	@echo "🐍 Opening Python shell..."
	@poetry run python -c "from app.main import app; from app.core.database import SessionLocal; from app.models import *; db = SessionLocal(); print('Available: app, db, models')"

test: ## Run tests
	@echo "🧪 Running tests..."
	@poetry run pytest

test-cov: ## Run tests with coverage
	@echo "🧪 Running tests with coverage..."
	@poetry run pytest --cov=app --cov-report=html --cov-report=term-missing

lint: ## Run linting
	@echo "🔍 Running linting..."
	@poetry run flake8 app tests
	@poetry run mypy app

format: ## Format code
	@echo "✨ Formatting code..."
	@poetry run black app tests
	@poetry run isort app tests

# Installation and Setup
install: ## Install dependencies
	@echo "📦 Installing dependencies..."
	@poetry install

install-dev: ## Install development dependencies
	@echo "📦 Installing development dependencies..."
	@poetry install --with dev

setup: ## Initial project setup
	@echo "🔧 Setting up project..."
	@$(MAKE) install-dev
	@cp -n .env.example .env 2>/dev/null || true
	@echo "✅ Project setup complete!"
	@echo "💡 Run 'make dev' to start development environment"

# Cleanup
clean: ## Clean up temporary files and containers
	@echo "🧹 Cleaning up..."
	@docker-compose down -v --remove-orphans
	@docker system prune -f
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf .pytest_cache htmlcov .coverage

# Production Commands
prod-build: ## Build production Docker image
	@echo "🏭 Building production image..."
	@docker build -t tgo-api:latest .

prod-up: ## Start production environment
	@echo "🏭 Starting production environment..."
	@docker-compose -f docker-compose.prod.yml up -d

# Utility Commands
check-deps: ## Check for dependency updates
	@echo "🔍 Checking for dependency updates..."
	@poetry show --outdated

update-deps: ## Update dependencies
	@echo "📦 Updating dependencies..."
	@poetry update

backup-db: ## Backup database
	@echo "💾 Creating database backup..."
	@mkdir -p backups
	@docker-compose exec postgres pg_dump -U postgres tgo_api > backups/backup_$(shell date +%Y%m%d_%H%M%S).sql

restore-db: ## Restore database from backup (usage: make restore-db BACKUP=filename)
	@echo "📥 Restoring database from backup..."
	@docker-compose exec -T postgres psql -U postgres -d tgo_api < backups/$(BACKUP)

# API Documentation
docs: ## Generate API documentation
	@echo "📚 Generating API documentation..."
	@poetry run python -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2))" > docs/openapi.json

# Health Checks
health: ## Check service health
	@echo "🏥 Checking service health..."
	@curl -f http://localhost:8000/health || echo "❌ API service is down"
	@docker-compose exec postgres pg_isready -U postgres || echo "❌ Database is down"
	@docker-compose exec redis redis-cli ping || echo "❌ Redis is down"

# Development Helpers
watch: ## Watch for file changes and restart server
	@echo "👀 Watching for changes..."
	@poetry run watchdog --patterns="*.py" --recursive --command="make restart-api" app/

restart-api: ## Restart API server
	@echo "🔄 Restarting API server..."
	@docker-compose restart api

# Security
security-check: ## Run security checks
	@echo "🔒 Running security checks..."
	@poetry run safety check
	@poetry run bandit -r app/
