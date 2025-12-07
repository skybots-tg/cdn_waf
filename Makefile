# Makefile for FlareCloud

.PHONY: help install dev test clean docker-up docker-down migrate format lint

help:
	@echo "FlareCloud - Makefile Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install       - Install dependencies"
	@echo "  make dev           - Run development server"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up     - Start Docker containers"
	@echo "  make docker-down   - Stop Docker containers"
	@echo "  make docker-logs   - View Docker logs"
	@echo ""
	@echo "Database:"
	@echo "  make migrate       - Run database migrations"
	@echo "  make migrate-auto  - Create auto migration"
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run tests"
	@echo "  make test-cov      - Run tests with coverage"
	@echo ""
	@echo "Code Quality:"
	@echo "  make format        - Format code with Black"
	@echo "  make lint          - Lint code with Ruff"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean         - Remove cache files"

install:
	pip install -r requirements.txt

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

docker-up:
	docker-compose up -d
	@echo "Waiting for services..."
	@sleep 5
	docker-compose exec app alembic upgrade head
	@echo "Services are ready!"

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

migrate:
	alembic upgrade head

migrate-auto:
	alembic revision --autogenerate -m "Auto migration"

test:
	pytest

test-cov:
	pytest --cov=app --cov-report=html --cov-report=term

format:
	black app/ tests/
	@echo "Code formatted!"

lint:
	ruff check app/ tests/
	@echo "Linting complete!"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	@echo "Cleaned up cache files!"


