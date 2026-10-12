.PHONY: install dev test test-unit test-integration lint fmt migrate migration up down

install:
	uv sync --locked

dev:
	uv run uvicorn app.main:app --reload

test:
	uv run pytest

test-unit:
	uv run pytest tests/unit

test-integration:
	uv run pytest tests/integration

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

migrate:
	uv run alembic upgrade head

migration:
	uv run alembic revision --autogenerate -m "$(m)"

up:
	docker compose up -d --build

down:
	docker compose down
