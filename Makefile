.PHONY: install format lint test migrate run container-build container-up container-down container-clean

PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff
ALEMBIC ?= .venv/bin/alembic

install:
	python -m venv .venv
	$(PYTHON) -m pip install -e '.[dev]'

format:
	$(RUFF) format .
	$(RUFF) check --fix .

lint:
	$(RUFF) format --check .
	$(RUFF) check .

test:
	$(PYTHON) -m pytest --cov=app --cov-report=term-missing

migrate:
	$(ALEMBIC) upgrade head

run:
	$(PYTHON) -m app

container-build:
	docker compose build

container-up:
	docker compose up --build --detach --wait

container-down:
	docker compose down

# Explicitly destructive: also deletes the local PostgreSQL volume.
container-clean:
	docker compose down --volumes
