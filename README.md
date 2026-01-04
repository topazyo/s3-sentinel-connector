# S3 to Sentinel Log Connector

A high-performance, secure connector for transferring logs from AWS S3 to Microsoft Sentinel.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python: 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

## Features
- Real-time log transfer from S3 to Sentinel
- Multi-format log parsing support
- Secure credential management
- Comprehensive monitoring and alerting
- Production-grade error handling

## Installation

```bash
# Clone the repository
git clone https://github.com/topazyo/s3-sentinel-connector.git
cd s3-sentinel-connector
```

## Quick Start (5-minute)
Run these commands from the repository root. They use existing scripts and files included in the project.

```bash
# S3 to Sentinel Log Connector

A connector that ingests logs from AWS S3 and routes them into Microsoft Sentinel / Azure Log Analytics. This repository contains the ingestion, parsing, routing, and monitoring components used during development and deployment.

[License: MIT](LICENSE)

**Notes:** All factual claims in this README are limited to items verified in the repository (code, configs, and CI). Where verification was not possible, a TODO is included pointing to what to check.

## Key Features (verified)
- Batch S3 ingestion and processing (see [src/core/s3_handler.py](src/core/s3_handler.py)).
- Schema-based parsing utilities (see [src/core/log_parser.py](src/core/log_parser.py)).
- Azure Key Vault-backed secret access is referenced in code (see [src/security/credential_manager.py](src/security/credential_manager.py)).
- Prometheus-compatible metrics helper present under [src/monitoring/](src/monitoring/).
- Development CI: GitHub Actions workflow at [.github/workflows/ci.yml](.github/workflows/ci.yml).

## Quickstart (minutes)
These steps produce a local development environment and run tests. They assume a Unix-like shell; Windows PowerShell commands are noted where different.

1. Clone and change directory

```bash
git clone https://github.com/topazyo/s3-sentinel-connector.git
cd s3-sentinel-connector
```

2. Create a virtual environment and install dependencies

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. (Optional) install developer tools

```bash
pip install -r requirements-dev.txt
```

4. Run tests

```bash
pytest -q
```

5. Run linters (checks only)

```bash
black --check .
isort --check-only .
ruff check .
```

If you prefer, the `Makefile` exposes `make install`, `make install-dev`, `make test`, `make lint`, and `make format` (note: Makefile targets use a Unix shell; on Windows use PowerShell equivalents).

## Prerequisites
- Python 3.9+ (project configured for py39 in `pyproject.toml`).
- pip for installing requirements.
- (Optional) Docker, Terraform, Azure CLI (`az`), and `kubectl` for deployment artifacts under `deployment/`.

## Configuration
Configuration is read from YAML files under `config/` and environment variables. The repository contains `.env.example` to bootstrap local env vars.

Copy the example `.env` for local development:

```bash
cp .env.example .env
# PowerShell: Copy-Item .env.example .env
```

Important environment variables (present in `.env.example`):

- `AWS_REGION` — AWS region (e.g., `us-west-2`)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` — AWS credentials for local testing
- `S3_BUCKET_NAME` — S3 bucket to ingest from
- `KEY_VAULT_URL` — Azure Key Vault URL
- `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` — Azure credentials (see TODO below for managed identity guidance)
- `SENTINEL_WORKSPACE_ID` — Log Analytics workspace ID
- `POLLING_INTERVAL_MINUTES`, `BATCH_SIZE` — runtime tuning parameters

Security: do NOT commit secrets. This repository uses Key Vault integration in code; the `.env.example` is a template only.

TODOs (verification needed):
- Confirm whether managed identity is the recommended auth method in production (see `src/security/credential_manager.py`).

## Usage (developer commands)
- Create venv and install: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` (PowerShell notes above).
- Run tests: `pytest -q` or `make test`.
- Lint: `ruff check .`, `isort --check-only .`, `black --check .` or `make lint`.
- Format: `isort .` and `black .` or `make format`.

## Project layout (important paths)
- `src/` — application source code
    - `src/core/` — ingestion, parsing, routing (S3, parsers, sentinel router)
    - `src/config/` — configuration manager
    - `src/security/` — credential and rotation helpers
    - `src/monitoring/` — metrics and alerting helpers
    - `src/utils/` — retry/backoff utilities
- `config/` — YAML configuration files (`base.yaml`, `dev.yaml`, `prod.yaml`, `tables.yaml`)
- `deployment/` — Terraform, Kubernetes, and deployment scripts
- `tests/` — unit and integration tests
- `examples/` / `Solutions/` — sample verification scripts and packaging

## CI/CD
- GitHub Actions CI is configured at [.github/workflows/ci.yml](.github/workflows/ci.yml) and runs tests and linters on `push`/`pull_request` to `main`.
- There are additional deployment workflows under `deployment/.github/workflows/` — inspect those files before changing deployment behavior.

## Contributing
- See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines (keep tests and linters passing, small PRs).
- If you open a PR, make sure CI passes: `pytest`, `black --check .`, `isort --check-only .`, `ruff check .`.

## Security
- Do not commit secrets. Use the Key Vault integration implemented in the codebase for runtime secrets.
- If you discover a security vulnerability, create a private issue and contact the repo owners.

## License
This project is licensed under MIT — see the `LICENSE` file.

## What changed and why
- Reorganized README to be Quickstart-first and to only state facts verified in the repository.
- Added TODOs where behavior or recommended practices require confirmation against runtime or ops knowledge.
