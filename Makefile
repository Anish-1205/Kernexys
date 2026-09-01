.PHONY: install format lint test migrate run

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
