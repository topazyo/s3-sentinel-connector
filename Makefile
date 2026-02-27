# Makefile - common developer tasks
# Note: On Windows, use PowerShell and replace 'export' with setting environment variables,
# or use WSL. Targets here assume a Unix-like shell.

.PHONY: help install install-dev install-test lint format test test-coverage type-check security-scan clean

help:
	@echo "Makefile targets:"
	@echo "  install       - create venv and install runtime requirements"
	@echo "  install-dev   - install dev requirements (linters, test tools)"
	@echo "  install-test  - install test requirements"
	@echo "  lint          - run ruff, isort check, and black check"
	@echo "  type-check    - run mypy against src"
	@echo "  security-scan - run bandit against src"
	@echo "  format        - run black and isort to format code"
	@echo "  test          - run pytest"
	@echo "  test-coverage - run pytest with coverage gate"
	@echo "  clean         - remove common build artifacts"

install:
	python -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt

install-dev: install
	. .venv/bin/activate && pip install -r requirements-dev.txt

install-test: install
	. .venv/bin/activate && pip install -r requirements-test.txt

lint:
	. .venv/bin/activate && ruff check .
	. .venv/bin/activate && isort --check-only .
	. .venv/bin/activate && black --check .

type-check:
	. .venv/bin/activate && mypy src/ --ignore-missing-imports

security-scan:
	. .venv/bin/activate && bandit -r src/ -ll -ii

format:
	. .venv/bin/activate && isort .
	. .venv/bin/activate && black .

test:
	. .venv/bin/activate && pytest -q

test-coverage:
	. .venv/bin/activate && pytest --cov=src --cov-fail-under=80

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .cache
