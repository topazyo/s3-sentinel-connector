# Makefile - common developer tasks
# Note: On Windows, use PowerShell and replace 'export' with setting environment variables,
# or use WSL. Targets here assume a Unix-like shell.

.PHONY: help install dev install-dev lint format test clean

help:
	@echo "Makefile targets:"
	@echo "  install       - create venv and install runtime requirements"
	@echo "  install-dev   - install dev requirements (linters, test tools)"
	@echo "  lint          - run ruff, isort check, and black check"
	@echo "  format        - run black and isort to format code"
	@echo "  test          - run pytest"
	@echo "  clean         - remove common build artifacts"

install:
	python -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt

install-dev: install
	. .venv/bin/activate && pip install -r requirements-dev.txt

lint:
	. .venv/bin/activate && ruff check .
	. .venv/bin/activate && isort --check-only .
	. .venv/bin/activate && black --check .

format:
	. .venv/bin/activate && isort .
	. .venv/bin/activate && black .

test:
	. .venv/bin/activate && pytest -q

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .cache
